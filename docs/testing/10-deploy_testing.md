# Testing: Deploy + Polish — Logfire, Rate Limiting, Render

## Prerequisites

- `.env` with valid `GROQ_API_KEY` and `API_KEY`
- `LOGFIRE_TOKEN` optional (leave empty for local mode)
- `uv sync` run

## Test Cases

### TC-01: Metadata at `/docs`
**Action**:
```bash
uv run uvicorn email_triage.main:app --reload --env-file .env
# Open http://localhost:8000/docs in the browser
```
**Expected**: Swagger UI shows title "Email Triage API", summary, description, contact and license.

### TC-02: Rate limiting — happy path
**Action**: Make 3 requests to `/triage` with a valid API key.
```bash
for i in 1 2 3; do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST http://localhost:8000/triage \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"subject":"Test","sender":"a@b.com","body":"hello"}'
done
```
**Expected**: All return `200`.

### TC-03: Rate limiting — limit exceeded
**Action**: Make 21 rapid requests from the same IP.
```bash
for i in $(seq 1 21); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST http://localhost:8000/triage \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"subject":"Test","sender":"a@b.com","body":"hello"}'
done
```
**Expected**: The first 20 return `200`, the 21st returns `429`.

### TC-04: Logfire in local mode (no token)
**Action**: Start the server with `LOGFIRE_TOKEN` empty or not defined.
```bash
uv run uvicorn email_triage.main:app --reload --env-file .env 2>&1 | head -10
```
**Expected**: Server starts without errors. No Logfire connection error appears. May show "Logfire configured in local mode" or similar.

### TC-05: Logfire with real token (if available)
**Action**: Set `LOGFIRE_TOKEN=<your token>` in `.env`, start the server and make a request.
**Expected**: The span appears in `logfire.pydantic.dev` within ~5 seconds with:
- HTTP span of the request
- Span of the `Agent.run()` call with tokens and duration

### TC-06: Verify `/openapi.json`
**Action**:
```bash
curl -s http://localhost:8000/openapi.json | python3 -m json.tool | grep -E '"title"|"version"|"summary"'
```
**Expected**:
```json
"title": "Email Triage API",
"version": "0.1.0",
"summary": "Classify support emails and draft replies in <3 seconds."
```

### TC-07: Deploy on Render
**Action**:
1. Connect the repo at `render.com` → "New Web Service"
2. Render detects `render.yaml` automatically
3. Configure `GROQ_API_KEY`, `API_KEY` in the dashboard (Environment section)
4. Wait for the build (~3 min)
**Expected**:
- Successful build in logs
- `GET https://<app>.onrender.com/health` → `{"status": "ok"}`
- `GET https://<app>.onrender.com/docs` → Swagger UI loads correctly

### TC-08: Founder test
**Action**: Open `/docs` in the founder's browser, expand `POST /triage`, click "Try it out", paste:
```json
{
  "subject": "Where is my order #12345?",
  "sender": "customer@example.com",
  "body": "I placed an order 5 days ago and haven't received any tracking info. Can you help?"
}
```
**Expected**: Response with `category: "shipments"`, coherent `draft_reply`, `confidence` > 0.7.

## Edge Cases

| Scenario | Expected |
|---|---|
| Empty `LOGFIRE_TOKEN` in production | API works, no spans in Logfire cloud |
| Rate limit from Zapier (fixed IP) | Zapier retries with backoff; 20/min is sufficient for normal flows |
| Render healthcheck fails | Render doesn't route traffic to the worker until `/health` responds 200 |
| 429 on `/triage/stream` | SlowAPI returns 429 before starting the stream |

## Log verification

With Logfire active, each request generates two types of telemetry:
1. **structlog** (stdout): `{"event": "request.start", "request_id": "...", "method": "POST", "path": "/triage"}`
2. **Logfire** (dashboard): HTTP span + nested pydantic-ai span

In production, Gunicorn and structlog logs are independent. Gunicorn logs in plain text (worker pid, etc.) and structlog logs JSON. For pure JSON, add `logconfig_dict` in `gunicorn.conf.py`.

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| Immediate `429 Too Many Requests` | Tests accumulate requests under the same IP | The 9 tests are under the 20/min limit; shouldn't happen |
| Logfire doesn't show spans | `LOGFIRE_TOKEN` not defined or incorrect | Check in Render dashboard → Environment |
| Render build fails on `python:3.14-slim` | Image not available | Change `FROM python:3.14-slim` to `FROM python:3.13-slim` in Dockerfile |
| `/docs` doesn't load on Render | `root_path` misconfigured | Render doesn't use subpath by default; no `root_path` needed |
