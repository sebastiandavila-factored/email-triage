# Refactor LLMService — raw httpx → Pydantic AI

## What it does

Replaces the manual `LLMService` implementation (httpx + JSON parsing) with `pydantic-ai-slim[groq]`. The public interface is identical (`__init__(api_key, model)` + `async triage(req) -> TriageResponse`), so all tests and the rest of the code don't change.

## How it works

**Before (raw httpx):**
```
LLMService.triage()
  → POST /chat/completions with response_format: json_object
  → response.json()["choices"][0]["message"]["content"]
  → TriageResponse.model_validate_json(content)
```

**After (Pydantic AI):**
```
LLMService.triage()
  → self._agent.run(user_msg)
      ├── Agent sends the prompt to Groq
      ├── Groq returns structured JSON
      └── Pydantic AI validates and parses to TriageResponse
  → result.output   ← TriageResponse already typed
```

Pydantic AI automatically handles:
- The JSON schema of `TriageResponse` in the prompt
- Serialization / deserialization
- Retries if the output doesn't validate

## Files involved

| File | Role |
|---|---|
| `src/email_triage/services/llm.py` | Refactored `LLMService` + `LLMError` |
| `src/email_triage/routers/triage.py` | Catches `LLMError` in addition to httpx errors |
| `pyproject.toml` | Dep `pydantic-ai-slim[groq]>=1.104.0` |
| `CLAUDE.md` | §Stack updated |

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| Explicit `GroqProvider(api_key=...)` | Read `GROQ_API_KEY` from env in Pydantic AI | The key already comes from `Settings`; duplicating env reads is confusing |
| `LLMError(RuntimeError)` as wrapper | Re-raise pydantic-ai exceptions directly | The router doesn't depend on the provider's exception types |
| `ModelSettings(temperature=0.2)` | Literal dict `{"temperature": 0.2}` | TypedDict typed; pyright validates the value |
| `aclose()` as no-op | Remove `aclose()` | Day 6 (lifespan) expects to be able to call it; keeps it compatible |
| `except Exception as exc: raise LLMError(...)` | Catch only `ModelHTTPError` | More robust: catches network errors, validation errors and timeouts |

## Gotchas / Edge cases

- Pydantic AI uses `httpx2` (an httpx fork) internally. There's a starlette deprecation warning about this — not a bug, just a conflict between starlette testclient and the installed httpx version.
- If the model can't produce a valid `TriageResponse` after retries, Pydantic AI raises `UnexpectedModelBehavior`, which is caught by the `except Exception` in `triage()` and converted to `LLMError` → 503.
- Temperature is passed via `ModelSettings`, not as a model constructor parameter — it's part of the `Agent` contract, not the model.

## Testing

📋 [Testing guide](../testing/08-pydantic-ai-refactor_testing.md)
