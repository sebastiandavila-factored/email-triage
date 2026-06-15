# Testing: POST /triage — Synchronous triage endpoint

## Prerequisites

- Server running: `uv run uvicorn email_triage.main:app --reload`
- `.env` with valid `GROQ_API_KEY`
- `curl` or Swagger UI at `http://localhost:8000/docs`

## Test Cases

### TC-01: Happy path — refund email
**Action**:
```bash
curl -s -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -d '{
    "subject": "I want a refund",
    "sender": "customer@example.com",
    "body": "Hi, I bought the product 3 days ago and it never arrived. How do I get a refund?"
  }' | python3 -m json.tool
```
**Expected**: HTTP 200, JSON with `category: "refunds"`, non-empty `draft_reply`, `confidence` between 0 and 1.

### TC-02: Happy path — order status query
**Action**:
```bash
curl -s -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -d '{
    "subject": "Where is my order #12345?",
    "sender": "buyer@test.com",
    "body": "I placed an order a week ago and have no information about its status."
  }' | python3 -m json.tool
```
**Expected**: HTTP 200, `category: "status"`.

### TC-03: Field validation — empty body
**Action**:
```bash
curl -s -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -d '{"subject": "test", "sender": "a@b.com", "body": ""}' | python3 -m json.tool
```
**Expected**: HTTP 422, Pydantic validation detail (body min_length=1).

### TC-04: Validation — invalid sender
**Action**:
```bash
curl -s -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -d '{"subject": "test", "sender": "not-an-email", "body": "text"}' | python3 -m json.tool
```
**Expected**: HTTP 422, validation error on `sender` field.

### TC-05: Without GROQ_API_KEY — 503
**Action**: Stop the server. Export `GROQ_API_KEY=` (empty) and restart. Send the TC-01 request.
**Expected**: HTTP 503, `{"detail": "LLM service not configured"}`.

## Edge Cases

| Scenario | Expected |
|---|---|
| `subject` with 501 characters | 422 (max_length=500) |
| `body` with 20001 characters | 422 (max_length=20000) |
| Email in Spanish | `draft_reply` in Spanish (the LLM detects the language) |
| Malformed JSON in body | 422 from FastAPI before reaching the handler |

## Log verification

With the server in `--reload`, verify that uvicorn logs show `POST /triage 200 OK` for TC-01.

When Day 4 arrives (middleware + structlog), each request will have `request_id` in the logs.

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| `503 LLM service not configured` | `GROQ_API_KEY` not in environment | Verify the server started with `--env-file .env` or that `.env` is active |
| `503 LLM service unavailable` | Groq rejected the request (401, 429) | Verify the API key is valid at `console.groq.com` |
| Unexpected `422` | Body is not valid JSON | Add `-H "Content-Type: application/json"` to the curl command |
| `404 Not Found` | Router not registered | Verify `app.include_router(triage.router)` in `main.py` |
