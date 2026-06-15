# Testing: Pydantic AI Refactor

## Prerequisites

- Valid `GROQ_API_KEY` in `.env` for the real integration smoke test
- Automated suite does not need `.env`

## Automated tests (without Groq)

```bash
uv run pytest tests/ -v
```

**Expected:** 9 passed. The refactor doesn't change observable behavior from the tests.

## Real integration smoke test (with Groq)

```bash
uv run uvicorn email_triage.main:app --reload --env-file .env &
sleep 2
curl -s -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: dev-local-key" \
  -d '{
    "subject": "Do you have model X in stock?",
    "sender": "customer@example.com",
    "body": "Hi, I want to buy model X but I am not sure if it is available."
  }' | python3 -m json.tool
```

**Expected:**
```json
{
  "category": "availability",
  "draft_reply": "...",
  "confidence": 0.9
}
```

## Verify Pydantic AI parses correctly

The background task logs the result after responding. In the server logs:

```bash
# Look for the triage.result log:
# {"category": "availability", "confidence": ..., "sender": "...", "event": "triage.result", ...}
```

The log confirms that `result.output` was a valid `TriageResponse`.

## Edge Cases

| Scenario | Expected |
|---|---|
| Groq returns JSON non-conforming to `TriageResponse` | Pydantic AI retries; if it fails → `LLMError` → 503 |
| Incorrect `GROQ_API_KEY` | Groq returns 401 → `LLMError` → 503 |
| `DEFAULT_MODEL` disabled in Groq | Change `GROQ_MODEL` in `.env` to the available model |

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| `503 LLM service unavailable` with valid key | `UnexpectedModelBehavior` from Pydantic AI | Verify the model in `GROQ_MODEL` is available in Groq |
| `LLMError: ...` in logs | Any exception from pydantic-ai | Read the exception message for diagnosis |
| Output without `confidence` | Pydantic AI partially parsed | Review SYSTEM_PROMPT in `services/llm.py`; add retry via `retries=2` in the Agent |
| Deprecation warning in tests about httpx/httpx2 | starlette testclient + httpx2 coexist | Ignore; doesn't affect functionality |
