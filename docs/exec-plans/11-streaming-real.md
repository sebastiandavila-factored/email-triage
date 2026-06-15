# 11. Real Streaming with Pydantic AI's `agent.run_stream()`

**Status:** ✅ delivered + fixed
**Estimate:** 4 hrs (1 session)

## Post-delivery note — `PromptedOutput` (decision made after measuring TTFT)

The initial implementation used `output_type=StreamingTriageResponse` directly, which enables **ToolOutput** mode by default in Pydantic AI (tool/function calling). After implementing and measuring with `make ttft`, the TTFT turned out identical to the latency of `POST /triage` (p50 ≈ 620 ms vs 629 ms). No real improvement.

**Root cause confirmed in official Groq documentation:**
> *"Streaming and tool use are not currently supported with Structured Outputs."*

This applies to both ToolOutput (function calling) and NativeOutput (`json_schema` mode). Both buffer the complete response before sending the first token.

**Adopted solution:** `PromptedOutput(StreamingTriageResponse)` in `LLMService.triage_stream()`. This mode injects the JSON schema into the system prompt and the model generates JSON as plain text. Groq streams plain text token by token with the LPU → target TTFT < 150 ms.

**Accepted tradeoff:** the model is not forced to the schema (only instructed via prompt). With `llama-3.3-70b-versatile` adherence is high for a simple 3-field schema, and integration tests would detect a parse failure. The SSE contract and tests were not changed.

**Code change:** one line in `src/email_triage/services/llm.py`:
```python
# Before:
output_type=StreamingTriageResponse
# After:
output_type=PromptedOutput(StreamingTriageResponse)
```

## Intent

Replace the current cosmetic streaming of `POST /triage/stream` with real token streaming via Pydantic AI's `agent.run_stream()`. The quantitative goal: reduce the **TTFT** (time-to-first-token visible to the client) from ~1.5–3 s (full Groq latency) to ~300–500 ms (latency until the first useful Groq token), while maintaining the existing SSE contract (`event: meta` → `data:` → `event: done`) and the 503 code before starting the stream.

Resolves the open risk from exec plan 01 ("Streaming + structured parsing") without duplicating LLM calls (not Option B).

## Scope

**Included:**
- New method `LLMService.triage_stream()` that opens `agent.run_stream()` and exposes validated partials.
- Auxiliary model `StreamingTriageResponse` with optional fields for incremental validation, without altering `TriageResponse` (public contract of the synchronous endpoint).
- Refactor of the `triage_stream` handler to:
  - Detect Groq connection failure **before** emitting 200 (maintain 503 semantics).
  - Emit `event: meta` as soon as `category` and `confidence` are available.
  - Emit only the **new delta** of `draft_reply` in each chunk (not the accumulated value).
- structlog logging at stream close (replaces `BackgroundTasks`, which doesn't fit the generator lifecycle).
- Tests updated with a `StreamingMockLLMService` that yields synthetic partials without calling the network.
- Documentation: rewrite `docs/features/04-streaming.md` and add TTFT-measurable case in `docs/testing/04-streaming_testing.md`.

**Out of scope (post-implementation):**
- Changes to `POST /triage` (stays synchronous).
- Changes to `TriageResponse` (public contract intact).
- TTFT metrics/dashboards (left to Logfire; sufficient to validate the change).
- Explicit upstream cancellation when client disconnects (FastAPI + Pydantic AI's context manager cover it; manual verification included in the testing doc).
- Buffer/reordering if Groq returns JSON fields out of declared order (see Risks).

## Prior reading

- Pydantic AI docs: [Streaming](https://ai.pydantic.dev/output/#streaming-structured-output) — `run_stream()` method, `StreamedRunResult.stream_output()`, partial validation semantics.
- FastAPI docs: [Custom Response → StreamingResponse](https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse) (re-read) and [Background Tasks vs streaming generators](https://fastapi.tiangolo.com/tutorial/background-tasks/).
- Installed code: verify the real API in `.venv/lib/python3.14/site-packages/pydantic_ai/agent.py` and `.../result.py` before coding — confirm the exact name of `stream_output()` / `stream()` / `stream_text()` and the `debounce_by` parameter in v1.104.0.

## Concrete changes

| File | Change |
|---|---|
| `src/email_triage/schemas.py` | + `StreamingTriageResponse(BaseModel)` with `category: Category \| None = None`, `draft_reply: str = ""`, `confidence: float \| None = None`. No `Field(min_length=...)` or `ge/le` to allow valid partials. |
| `src/email_triage/services/llm.py` | + `triage_stream(req)` as `@asynccontextmanager` that opens `self._agent.run_stream(user_msg, output_type=StreamingTriageResponse)` and wraps provider exceptions in `LLMError`. |
| `src/email_triage/routers/triage.py` | Refactor of `triage_stream`: manual `__aenter__` of the context manager to capture pre-stream 503; replace `_sse_from_result` with `_sse_from_partials(stream)` that computes the `draft_reply` delta. Log at the end of the generator (not `BackgroundTasks`). |
| `tests/conftest.py` | + `StreamingMockLLMService` that yields 4–5 synthetic partials via `triage_stream`. Keep `MockLLMService` and `FailingLLMService`. |
| `tests/test_triage.py` | + tests: (a) meta arrives before any `data:`, (b) reconstruction of `draft_reply` from deltas equals the expected value, (c) 503 if the stream fails to open. Keep the 2 existing streaming tests. |
| `docs/features/04-streaming.md` | Rewrite the "How it works" section with the new flow. Remove note "real streaming left for Day 5". Document the delta contract. |
| `docs/testing/04-streaming_testing.md` | + TC-05: measure TTFT with Python script (`time.perf_counter()` between request and first useful byte) and compare against `POST /triage`. Keep TC-01..TC-04. |
| `AGENTS.md` §5 | Replace note "streaming is cosmetic" with "real streaming (token-level)". |
| `docs/exec-plans/README.md` | Add entry #11 to the plans table. |

## Technical design

### 1. Incremental validation model

`TriageResponse` remains as the public contract with strict constraints. For streaming we use a parallel model that tolerates missing fields:

```python
# src/email_triage/schemas.py
class StreamingTriageResponse(BaseModel):
    category: Category | None = None
    draft_reply: str = ""
    confidence: float | None = None
```

**Why a separate model rather than relaxing `TriageResponse`:** `TriageResponse` is exposed in OpenAPI as the response model of `POST /triage`. Making it optional would break the documented contract and weaken validation on the synchronous path.

### 2. Service: open the stream with error handling

```python
# src/email_triage/services/llm.py
from contextlib import asynccontextmanager

class LLMService:
    @asynccontextmanager
    async def triage_stream(self, req: TriageRequest):
        user_msg = f"Subject: {req.subject}\nFrom: {req.sender}\n\n{req.body}"
        try:
            async with self._agent.run_stream(
                user_msg,
                output_type=PromptedOutput(StreamingTriageResponse),  # see Post-delivery note
            ) as result:
                yield result
        except Exception as exc:
            raise LLMError(str(exc)) from exc
```

`output_type=` per-call overrides the `output_type=TriageResponse` declared in the Agent constructor, only for this path.

### 3. Handler: pre-fetch for 503 + delta encoding

```python
# src/email_triage/routers/triage.py
@router.post("/stream")
@limiter.limit("20/minute")
async def triage_stream(request: Request, req: TriageRequest, llm: LLMDep) -> StreamingResponse:
    stream_cm = llm.triage_stream(req)
    try:
        stream = await stream_cm.__aenter__()
    except LLMError as exc:
        raise HTTPException(status_code=503, detail="LLM service unavailable") from exc

    async def gen() -> AsyncGenerator[str]:
        emitted_text = ""
        emitted_meta = False
        final: StreamingTriageResponse | None = None
        try:
            async for partial in stream.stream_output(debounce_by=None):
                final = partial
                if not emitted_meta and partial.category and partial.confidence is not None:
                    meta = {"category": str(partial.category), "confidence": partial.confidence}
                    yield f"event: meta\ndata: {json.dumps(meta)}\n\n"
                    emitted_meta = True
                if len(partial.draft_reply) > len(emitted_text):
                    delta = partial.draft_reply[len(emitted_text):]
                    yield f"data: {json.dumps(delta)}\n\n"
                    emitted_text = partial.draft_reply
            yield "event: done\ndata: [DONE]\n\n"
        finally:
            await stream_cm.__aexit__(None, None, None)
            if final is not None and final.category and final.confidence is not None:
                _log.info(
                    "triage.stream.result",
                    category=str(final.category),
                    confidence=final.confidence,
                    sender=str(req.sender),
                )

    return StreamingResponse(gen(), media_type="text/event-stream")
```

**Key design points:**
- Manual `__aenter__` allows capturing Groq connection failures as `HTTPException(503)` *before* returning `StreamingResponse` (status 200). After returning the `StreamingResponse`, the status code can no longer be changed.
- The `try/finally` inside the generator guarantees that `stream_cm.__aexit__` is always called, including when the client disconnects mid-stream (FastAPI cancels the coroutine and triggers `finally`).
- The delta is calculated by slicing. Pydantic AI emits each `partial.draft_reply` with the text **accumulated** up to that point, not the raw delta. Slicing is O(1) since it's an index + view.
- The final log replaces the `BackgroundTasks` from the synchronous handler: the result is only known when the generator finishes, and `BackgroundTasks` executes after closing the response — an incompatible combination. Equivalent result for the caller.

### 4. Tests without network

```python
# tests/conftest.py
class StreamingMockLLMService(LLMService):
    def __init__(self) -> None:
        pass

    @asynccontextmanager
    async def triage_stream(self, req: TriageRequest):
        partials = [
            StreamingTriageResponse(category=Category.REFUNDS, confidence=0.95, draft_reply=""),
            StreamingTriageResponse(category=Category.REFUNDS, confidence=0.95, draft_reply="We will"),
            StreamingTriageResponse(category=Category.REFUNDS, confidence=0.95, draft_reply="We will process"),
            StreamingTriageResponse(category=Category.REFUNDS, confidence=0.95, draft_reply="We will process your refund shortly."),
        ]

        class FakeResult:
            async def stream_output(self, debounce_by: float | None = None):
                for p in partials:
                    yield p

        yield FakeResult()
```

Couples the tests to the public signature `stream_output()` of Pydantic AI. If the API changes (low risk in minor versions), the fake is updated. More robust alternative: `pydantic_ai.models.test.TestModel`, but requires building a real Agent with a fake model — more boilerplate. Accepted tradeoff.

**New tests:**
- `test_triage_stream_meta_before_data`: parse the response and ensure the byte offset of `event: meta` < first `data:`.
- `test_triage_stream_delta_reconstructs_full_reply`: concatenate all JSON-decoded `data:` → must equal the expected `draft_reply` (`"We will process your refund shortly."`).
- `test_triage_stream_open_failure_returns_503`: variant of `FailingLLMService` whose `triage_stream.__aenter__` raises `LLMError`; assert 503.

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| Separate `StreamingTriageResponse` | Make `TriageResponse` with Optional fields | Breaking the OpenAPI contract of the synchronous endpoint is worse than having two closely related models |
| Manual `__aenter__` + `try/finally` in generator | `async with` inside the generator (cleaner) | We need to capture the open failure as 503 *before* returning the `StreamingResponse`; an `async with` inside the generator only executes when the iterator is consumed by the ASGI server, with status 200 already sent |
| Delta by slicing the accumulated value | Raw LLM tokens | Pydantic AI with structured `output_type` does not expose raw tokens: the partial is always the partially validated object. Slicing is O(1) and sufficient |
| `debounce_by=None` | `debounce_by=100ms` (default) | We minimize TTFT. The cost of validating each delta is low for short JSONs like `TriageResponse` |
| Log at end of generator (not `BackgroundTasks`) | `BackgroundTasks` with nonlocal capturing `final` | `BackgroundTasks` runs after closing the response; the log would be OK but couples the handler to a pattern that doesn't apply for streams. Direct log is simpler |
| Maintain existing SSE format (`event: meta`, `data:`, `event: done`) | More efficient format (e.g. ND-JSON) | Backward-compat with any client already consuming the endpoint (even if no prod yet, this disciplines the change) |
| Streaming model placed in `schemas.py` | New file `schemas_streaming.py` | 3 optional fields don't justify a separate module; increases cognitive load without benefit |

## Risks / Open questions

- **Field order in LLM JSON**: If Groq emits `draft_reply` *before* `category` and `confidence`, the handler will emit `data:` chunks before `event: meta`, breaking the MVP expectation. **Primary mitigation**: declare `category` and `confidence` before `draft_reply` in `StreamingTriageResponse` (OpenAI-compatible providers usually respect schema field order). **Validation**: smoke test against real Groq on the first commit, with at least 5 executions, to confirm stable order. **Fallback** (if it fails): buffer `data:` chunks until meta arrives or until a cap (e.g. 50 chars or 200 ms), then flush. Do not implement in this plan; open issue.

- **API compatibility with Pydantic AI 1.104.0**: the exact method name (`stream_output()` vs `stream()`) and the `debounce_by` signature must be confirmed by reading the installed code *before* coding, not assumed. If the API differs, update the handler and `StreamingMockLLMService` in the same session.

- **Client cancellation mid-stream**: FastAPI cancels the generator coroutine when the client closes the connection. The `try/finally` should call `__aexit__` and close the Groq connection. **Manual verification** included as TC-06 in the testing doc: open the stream with `curl`, press `Ctrl-C` before `done`, confirm in logs that no Groq request is left hanging (Logfire span must close).

- **Mock coupling to internal API**: `StreamingMockLLMService` reproduces the shape of `stream_output()`. If Pydantic AI changes that API in a minor version, tests break even though production code still works against real Groq. **Mitigation**: pin `pydantic-ai-slim` to `~=1.104` in `pyproject.toml`. Accept the cost.

- **Mock vs reality — partial validation**: the mock yields already-constructed objects. In production, `StreamingTriageResponse` is constructed via `pydantic.experimental.partial_validate` (or equivalent) from partial bytes. There's a risk that an edge case of the real parser (e.g. `\n` escape mid-emission in `draft_reply`) generates an unhandled `ValidationError`. **Mitigation**: in the handler, wrap the `async for` in `try/except ValidationError` and translate to `LLMError` → closes the stream with a final error event (not 503; we're already in 200).

- **Streaming tests + TestClient**: `TestClient` (based on httpx) reads the full stream before returning. Does not measure real TTFT. **Solution for TTFT**: TC-05 uses `httpx.AsyncClient().stream()` and measures `time.perf_counter()` between request and first useful byte, run manually by the human (not in CI).

## Execution plan (suggested commit order)

1. **Confirm Pydantic AI API** (10 min): read installed `agent.py` and `result.py`. If it differs from this plan, update the plan before coding.
2. **Schemas + service** (45 min): add `StreamingTriageResponse`; add `triage_stream()` to `LLMService`; manual smoke test with `scripts/smoke_llm_stream.py` (new, prints partials).
3. **Handler + delta encoding** (45 min): refactor `triage_stream` with pre-fetch and delta. Verify with manual curl against real Groq that `event: meta` arrives before `data:`.
4. **Tests** (45 min): `StreamingMockLLMService`, 3 new tests, adjust the 2 existing ones if they break. Suite green locally.
5. **Docs + TTFT measurement** (45 min): update `04-streaming.md` and `04-streaming_testing.md`. Run TC-05 (script that measures TTFT) against real Groq and record the improvement in the doc.
6. **Final polish** (30 min): AGENTS.md §5, exec-plans/README index, pre-commit, pyright. Plan status → 🚧 → ✅.

## Done when

- [ ] `LLMService.triage_stream()` implemented with `agent.run_stream()` and `output_type=StreamingTriageResponse`
- [ ] `StreamingTriageResponse` in `schemas.py`
- [ ] Handler `/triage/stream` emits `event: meta` within the first ~500 ms (measured empirically in TC-05) vs ~2 s of the synchronous flow
- [ ] Pre-stream 503 still works (test green)
- [ ] 9 existing tests pass + 3 new streaming tests
- [ ] `docs/features/04-streaming.md` rewritten describing the new flow and removing the note about "real streaming left for Day 5"
- [ ] `docs/testing/04-streaming_testing.md` with TC-05 (measurable TTFT) and TC-06 (client cancellation)
- [ ] AGENTS.md §5 updated
- [ ] `docs/exec-plans/README.md` adds entry #11 with status ✅
- [ ] Pre-commit (ruff + pyright) passes
- [ ] Human ran the testing guide and confirmed TTFT < 500 ms empirically
