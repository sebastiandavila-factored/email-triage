# Triage Studio F2 — Prompt compiler + dynamic output type

## What it does

Connects the per-workspace taxonomy from F1 to the classification path. `/triage`
now compiles an **XML system prompt** from the calling workspace's active categories,
classifies against **that** taxonomy (not the frozen `Category` enum), and returns a
category that is one of the tenant's slugs (or `unknown`). Each workspace gets its
own `LLMService`, cached by `(tenant, taxonomy version)`.

The critical path degrades safely: with no tenant (no-DB/dev), no DB, or an
unreadable taxonomy, `/triage` falls back to the legacy static prompt + enum. It
never 500s on prompt configuration.

This is phase F2 of [proposal 001 — Triage Studio](../proposals/001-triage-studio.md).

> **Superseded for published tenants (F3):** once a workspace publishes a prompt version
> (Plan 26), `/triage` serves that frozen version and edits stop being live until the next
> publish. The "live edit reflects immediately" behavior below applies only to workspaces
> that have **not** published. See [feature 26](26-triage-studio-examples-publish.md).

## How it works

```
POST /triage  (X-API-Key → tenant_id)
  → get_triage_service(tenant)
      tenant_id is None / no DB / no active cats → legacy LLMService (fallback)
      else → active categories → taxonomy_version (sha1 of slugs+name+description)
             cache hit (tenant, version)? reuse : build LLMService(
                 system_prompt = compile_system_prompt(specs),   # XML, cacheable prefix
                 output_type   = DynamicTriageResponse,          # category: str
                 allowed_slugs = {slugs} | {"unknown"})
  → agent.run(<email>…)                # volatile block, sent as the user message
  → post-hoc coercion: category ∉ allowed_slugs → "unknown"
```

- **Compiler** (`services/prompt_compiler.py`): pure function. Emits a plain-prose
  role/task, a `Categories:` list (one `- slug: description` per active category +
  `unknown`), a `Guidelines:` block, and a one-line output instruction. Per Anthropic's
  guidance (Plan 29) XML tags are reserved for the few-shot `<examples>` and the
  `<email>` input. Coverage is structural — the prompt is built *from* the categories,
  so none can be missing. Structural characters (`<`, `>`, `&`) in interpolated text are
  neutralized so they can't forge a delimiter.
- **Stable/volatile split** (cert domain 5): role+categories go in the system prompt
  (cacheable prefix); the `<email>` is added per request as the user message.
- **Dynamic output** (cert domain 3): `DynamicTriageResponse.category: str`. The
  allowed set is enforced by the prompt plus a post-hoc coercion in `LLMService`
  (hallucinated slug → `unknown`), for both sync and streaming.
- **Cache invalidation for free:** the version hashes slug+name+description of the
  active set, so any category edit yields a new key and the stale service ages out of
  the bounded LRU. No `prompt_versions` table yet (that's F3's publish flow).

## Files involved

| File | Role |
|---|---|
| `email_triage/services/prompt_compiler.py` | `compile_system_prompt`, `render_email`, `CategorySpec` (pure) |
| `email_triage/schemas.py` | `DynamicTriageResponse` / `DynamicStreamingTriageResponse` + `AnyTriageResponse`/`AnyStreamingResponse` unions |
| `email_triage/services/llm.py` | `LLMService` gains `output_type`/`streaming_output_type`/`allowed_slugs`; XML email + coercion |
| `email_triage/deps.py` | `get_triage_service`, `_taxonomy_version`, `_svc_cache` LRU, `clear_triage_service_cache`; `get_llm_service` demoted to legacy/fallback |
| `email_triage/routers/triage.py` | Resolves service by tenant; `response_model=DynamicTriageResponse`; stream slug coercion; span attrs |
| `email_triage/db/repos/triage.py` | `insert_log`/`persist_triage_log` accept `AnyTriageResponse`, `str(category)` |
| `evals/run_evals.py` | `cast` — eval task stays on the legacy `TriageResponse` |
| `tests/conftest.py` | Overrides `get_triage_service` (was `get_llm_service`) |
| `tests/test_prompt_compiler.py` | Compiler + coercion + cache/fallback |

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| Degrade to legacy on any failure/no-DB | 503 on the dynamic path | `/triage` bills; never break on prompt config |
| `category: str` + post-hoc coercion | Strict dynamic `Literal`/`StrEnum` | Robust to slug hallucination; trivial serialization |
| Version = hash of active categories | Explicit `prompt_versions` table now | Free invalidation without the publish machinery (F3) |
| `<examples>` omitted in F2 | Add few-shot now | Isolate the compiler from content; F3 adds examples on a proven base |
| Keep legacy `TriageResponse` (enum) | Widen the one model to `str` | Offline evals depend on `.category.value`; don't disturb them |
| Stable prompt / volatile email split | One combined message | Enables prompt caching; the token-budgeting of domain 5 |

## Gotchas / Edge cases

- **Test doubles & `allowed_slugs`:** the stream router reads `llm.allowed_slugs`.
  `LLMService` declares it as a **class attribute** (`= None`) so mocks that skip
  `__init__` still expose it.
- **`response_model=DynamicTriageResponse`:** the public `/triage` response now types
  `category` as `str`. Legacy `TriageResponse` (enum is a `str` subclass) serializes
  through it cleanly, so the no-DB path is unchanged on the wire.
- **In-memory SQLite doesn't share across sessions:** `get_triage_service` opens its
  own session, so its tests use file-backed SQLite (like the F1 API tests).
- **Groq prompt caching** is best-effort at the provider; the stable/volatile split is
  correct regardless and costs nothing if the provider doesn't cache.

## Testing

📋 [Testing guide](../testing/25-triage-studio-prompt-compiler_testing.md)
