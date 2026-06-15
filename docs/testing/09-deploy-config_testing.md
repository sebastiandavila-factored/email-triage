# Testing: Production configuration — Lifespan + Gunicorn + Docker

## Prerequisites

- `.env` with valid `GROQ_API_KEY` and `API_KEY`
- Docker installed (for the Dockerfile test)
- `uv sync` run

## Test Cases

### TC-01: Lifespan — startup log with model
**Action**:
```bash
uv run uvicorn email_triage.main:app --reload --env-file .env 2>&1 | head -5
```
**Expected**: Before the first request, a JSON line:
```json
{"groq_model": "llama-3.3-70b-versatile", "event": "startup", "level": "info", "timestamp": "..."}
```

### TC-02: Lifespan — shutdown log
**Action**: Run the TC-01 server, press Ctrl+C or send SIGTERM.
**Expected**: JSON line `{"event": "shutdown", ...}` on stop.

### TC-03: Gunicorn with UvicornWorker
**Action**:
```bash
source .env && uv run gunicorn -c gunicorn.conf.py email_triage.main:app &
sleep 3 && curl -s http://localhost:8000/health
kill %1
```
**Expected**:
1. `N workers` started where `N = (2×CPUs)+1`
2. `{"event": "startup"}` logged by each worker
3. `curl` returns `{"status": "ok"}`
4. On kill: `{"event": "shutdown"}` per worker

### TC-04: Docker build (if Docker available)
**Action**:
```bash
docker build -t email-triage:local .
```
**Expected**: Successful build in two stages without errors. The final image does not include `.env` or `.venv` from the host.

### TC-05: Docker run (if Docker available)
**Action**:
```bash
docker run --rm -p 8000:8000 \
  --env-file .env \
  email-triage:local &
sleep 5
curl -s http://localhost:8000/health
docker stop $(docker ps -q --filter ancestor=email-triage:local)
```
**Expected**: `{"status": "ok"}`, JSON logs visible in stdout.

### TC-06: Dockerfile Healthcheck (if Docker available)
**Action**: Run the TC-05 container and wait 30 seconds.
```bash
docker inspect <container_id> | python3 -c "import sys,json; c=json.load(sys.stdin); print(c[0]['State']['Health']['Status'])"
```
**Expected**: `healthy` (after the 5s `start-period` and first 30s check).

## Edge Cases

| Scenario | Expected |
|---|---|
| `GROQ_API_KEY` not defined on startup | `ValidationError` from pydantic-settings in lifespan; process doesn't start |
| `python:3.14-slim` not available on Docker Hub | Change `FROM python:3.14-slim` to `FROM python:3.13-slim` in Dockerfile |
| VPS with 2 CPUs | 5 workers (2×2+1) — correct |

## Log verification

Gunicorn with multiple workers shows one startup and one shutdown log per worker. This is correct. For production, add `logconfig_dict` in gunicorn.conf.py if you want pure JSON without gunicorn's plain text logs.

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| `ModuleNotFoundError: email_triage` in Docker | `.venv` doesn't have the package installed | Verify that `uv sync --frozen --no-dev` includes the package (not just `--no-install-project`) |
| Container restarts in a loop | `GROQ_API_KEY` or `API_KEY` not in `--env-file` | Pass `--env-file .env` or define env vars on the platform |
| `gunicorn: No module named uvicorn.workers` | `uvicorn` not installed in the env | Verify that `uvicorn` is in `dependencies` (not just `dev`) in `pyproject.toml` |
| Workers = 1 in production | `multiprocessing.cpu_count()` returns 1 in container | Add `workers = int(os.environ.get("GUNICORN_WORKERS", (2 * multiprocessing.cpu_count()) + 1))` for env override |
