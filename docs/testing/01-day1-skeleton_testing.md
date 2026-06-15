# Testing: Day 1 — Skeleton + Tooling

## Prerequisites

- `uv` installed (`uv --version` responds)
- Python 3.14 available (`uv python list` shows it)
- In the project root (`pwd` ends in `/email-triage`)

## Test Cases

### TC-01: Environment sync

**Action:**
```bash
uv sync
```

**Expected:** Completes without error. Output mentions `email-triage==0.1.0` installed. `.venv/bin/python` exists.

### TC-02: Package import

**Action:**
```bash
uv run python -c "from email_triage.main import app; print(app.title)"
```

**Expected:** Prints `Email Triage API` without warnings. If it says `ModuleNotFoundError: email_triage`, the wheel is not built correctly — check `[tool.hatch.build.targets.wheel]` in `pyproject.toml`.

### TC-03: Server up

**Action:**
```bash
uv run uvicorn email_triage.main:app --reload
```

Open in browser:
- `http://localhost:8000/health` → `{"status":"ok"}`
- `http://localhost:8000/docs` → Swagger UI with title "Email Triage API"

**Expected:** Both URLs respond 200. Swagger shows `GET /health`.

### TC-04: Tooling passes

**Action:**
```bash
uv run ruff format --check
uv run ruff check
uv run pyright
```

**Expected:**
- `ruff format --check`: `N files already formatted`
- `ruff check`: `All checks passed!`
- `pyright`: `0 errors, 0 warnings, 0 informations`

### TC-05: pre-commit installed and functional

**Action:**
```bash
ls .git/hooks/pre-commit
uv run pre-commit run --files src/email_triage/main.py
```

**Expected:** The `.git/hooks/pre-commit` file exists. The command shows `ruff check ... Passed`, `ruff format ... Passed`, `pyright ... Passed`.

## Edge Cases

| Scenario | Expected |
|---|---|
| `.env` doesn't exist | `uv sync` works fine. Only fails when the key is used (Day 2+) |
| Python installed is 3.13 | `uv sync` fails with a clear message requesting 3.14 |
| Change `version` in `[project]` | Appears in `/openapi.json → info.version` after restarting the server |
| Edit `main.py` and save | With `--reload`, uvicorn re-imports in <1s |

## Log verification

After `uvicorn ... --reload`, the terminal shows:
- `INFO:     Started server process [<pid>]`
- `INFO:     Application startup complete`
- Per request: `INFO:     127.0.0.1:<port> - "GET /health HTTP/1.1" 200 OK`

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| `ModuleNotFoundError: email_triage` | `uv sync` not run after adding `[build-system]` | `uv sync` |
| `pyright subprocess.CalledProcessError` with `nodeenv` | No Node on system and the pyright wrapper couldn't set one up | `uv remove pyright && uv add "pyright[nodejs]"` |
| `ruff check` reports line > 100 | `line-length = 100` applies | Split the string with parentheses and implicit concatenation |
| pre-commit says "no files to check" | Untracked files; hooks only watch tracked + staged | `git add <files>` or pass with `--files <paths>` |
| `uv sync` very slow the first time | Downloading Python 3.14 and compiling wheels | Wait; subsequent runs are instant (cache) |
