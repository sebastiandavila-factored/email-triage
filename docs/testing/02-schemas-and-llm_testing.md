# Testing: Day 2 — Schemas and LLMService

## Prerequisites

- Day 1 closed (TC-01 to TC-05 from `01-day1-skeleton_testing.md` pass)
- `.env` contains `GROQ_API_KEY` with a valid key (not the placeholder)
- Internet connection (the smoke test calls `api.groq.com`)

## Test Cases

### TC-01: Schemas validate

**Action:**
```bash
uv run python -c "
from email_triage.schemas import Category, TriageRequest
print('categories:', [c.value for c in Category])
r = TriageRequest(subject='hello', sender='a@b.com', body='test')
print('request OK:', r.model_dump())
"
```

**Expected:**
- `categories: ['status', 'refunds', 'availability', 'shipments', 'prices']`
- `request OK: {'subject': 'hello', 'sender': 'a@b.com', 'body': 'test'}`

### TC-02: Pydantic validations run

**Action:**
```bash
uv run python -c "
from email_triage.schemas import TriageRequest
try:
    TriageRequest(subject='', sender='not-email', body='x')
except Exception as e:
    print('rejected:', type(e).__name__)
"
```

**Expected:** `rejected: ValidationError`. Catches both empty `subject` and invalid `sender`.

### TC-03: Smoke test against real Groq

**Action:**
```bash
uv run --env-file .env python scripts/smoke_llm.py
```

**Expected:**
```
category   : Category.STATUS
confidence : 0.9   (some number between 0 and 1)
draft_reply:
[a polite draft about the order status]
```

If `category` is not `STATUS`, note the result but **don't block** — the LLM has variability. If it happens frequently, adjust the prompt.

## Edge Cases

| Scenario | Expected |
|---|---|
| `GROQ_API_KEY` invalid or empty | Smoke test crashes with `httpx.HTTPStatusError: 401` |
| No internet | Crashes with `httpx.ConnectError` |
| `body` with 21,000 chars | `TriageRequest` raises `ValidationError` before reaching Groq |
| Email in Spanish | Draft comes out in Spanish |
| Ambiguous email (mixed topics) | `confidence` should drop (~0.5-0.7); if it reaches 0.95, the prompt needs adjustment |

## Log verification

The smoke script prints to stdout. To inspect the raw LLM JSON (prompt debug), **temporarily** modify `llm.py`:

```python
data: dict[str, Any] = response.json()
print(f"DEBUG raw content: {data['choices'][0]['message']['content']}")
content: str = data["choices"][0]["message"]["content"]
```

Revert to the original state before committing.

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| `KeyError: 'GROQ_API_KEY'` | `.env` not loaded | Use `--env-file .env` in `uv run` |
| `httpx.HTTPStatusError 401` | Invalid or expired key | Generate new key at `console.groq.com/keys` |
| `httpx.HTTPStatusError 429` | Groq rate limit | Wait 60s, or change model in `DEFAULT_MODEL` |
| `ValidationError: category` | LLM returned a category outside the enum (e.g. "billing") | Reinforce the prompt: list the 5 categories explicitly |
| `ValidationError: confidence` | LLM returned `"0.9"` as string | Reinforce JSON format in the prompt; slightly raise `temperature` |
| Draft in wrong language | LLM ignored the instruction | Try a newer model, or reinforce the prompt |

## Known agent blockers

- **The agent cannot run the smoke test if the human's key is exhausted.** Report and ask the human to confirm quota before retrying.
- **The agent must not call Groq from automated tests.** Day 5 introduces the mock with `app.dependency_overrides`.
