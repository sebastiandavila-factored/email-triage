# Postmortem 01 — FastAPI Cloud cannot import `email_triage` (src layout)

| Field | Value |
|---|---|
| Date | 2026-06-04 |
| Resolved | 2026-06-05 |
| Severity | Production deploy blocked (no user impact — service was not live yet) |
| Surface | FastAPI Cloud deployment |
| Author | Initial deploy attempt |

## Summary

We linked the project to FastAPI Cloud and ran `fastapi deploy`. Every replica failed at boot with:

```
ModuleNotFoundError: No module named 'email_triage'
```

The cause was the `src/` layout: the package lived at `/app/src/email_triage/` inside the container, but FastAPI Cloud's runtime was importing from `/app`. After ruling out PYTHONPATH and Dockerfile fixes (FastAPI Cloud ignores both), we flattened the layout to `email_triage/` at the project root. Tests passed locally, deploy succeeded.

## Timeline

- **18:31 UTC** — First failed deploy. `fastapi run` boots, prints `Using import string: email_triage.main:app`, uvicorn raises `ModuleNotFoundError`.
- **~19:00** — Added `ENV PYTHONPATH="/app/src"` to the `Dockerfile`. Redeployed. Same error.
- **~19:30** — Switched the Dockerfile to `uv sync --frozen --no-dev --no-editable` so the package would be installed as a wheel in `site-packages`. Same error.
- **~20:00** — Noticed the traceback's Python path was `/python/cpython-3.14.5-linux-x86_64-gnu/lib/python3.14/…`. That is uv's managed Python install layout, not `python:3.14-slim` (which would put Python under `/usr/local/lib/`). Concluded that **FastAPI Cloud is not using our `Dockerfile`** — it runs its own buildpack.
- **June 5** — Verified fastapi-cli's `[tool.fastapi]` schema only supports `entrypoint`; no `path` / `src` option exists. Confirmed via the `fastapi-cli` source that discovery only walks `__init__.py` parents when given a file path argument, not an import string. Flattened the layout (`src/email_triage/` → `email_triage/`), updated `pyproject.toml`, `pyrightconfig.json`, `Dockerfile`, `CLAUDE.md`. `uv sync` + `uv run pytest` (20/20) green locally. Deploy succeeded.

## Root cause

Three independent factors had to line up for the bug to manifest:

1. **FastAPI Cloud ignores the `Dockerfile`.** It uses its own uv-based buildpack. Anything we configured in `Dockerfile` (CMD, ENV, COPY layout) has no effect on the Cloud build. The Dockerfile only matters for Render / self-hosted Docker.
2. **`fastapi-cli` has no `src` layout configuration.** The only field accepted under `[tool.fastapi]` in `pyproject.toml` is `entrypoint` (a Python import string). When given only an import string, fastapi-cli does **not** walk `__init__.py` parents to add a source root to `sys.path`. It relies on the package being importable from cwd or `site-packages`.
3. **The package was not installed in `site-packages` at runtime.** FastAPI Cloud's buildpack installs dependencies, but the project's own package did not land in `site-packages` in a way `import email_triage` could see — likely an editable install whose `.pth` file pointed at `/app/src` while the runtime worked from a different filesystem view, or the buildpack skipped the project install entirely.

With `email_triage/` at the project root, `/app/email_triage/__init__.py` exists, fastapi-cli's import-from-cwd finds it, and the import succeeds regardless of how the buildpack handles installs.

## What we tried that did NOT work, and why

| Attempt | Why it failed |
|---|---|
| `ENV PYTHONPATH="/app/src"` in the Dockerfile | FastAPI Cloud builds its own image — the Dockerfile is not used. |
| `uv sync --no-editable` in the Dockerfile | Same — FastAPI Cloud ignores the Dockerfile. |
| Adding `[tool.fastapi] path = "src/email_triage/main.py"` | Not a valid field. fastapi-cli's config schema only knows `entrypoint`. |
| Bumping the deploy hoping to pick up new config | Same buildpack, same cwd, same `sys.path` — same error. |

## Fix

Flat layout. Package directly at the project root:

```
email-triage/
├── email_triage/        # <-- was src/email_triage/
│   ├── __init__.py
│   ├── main.py
│   └── …
├── tests/
├── pyproject.toml
└── …
```

Files touched in the fix commit:
- `email_triage/` — moved from `src/email_triage/` (no code changes).
- `pyproject.toml` — `[tool.hatch.build.targets.wheel] packages = ["email_triage"]`, `[tool.ruff] src = ["email_triage", "tests"]`, `[tool.pyright] include = ["email_triage", "tests"]`.
- `pyrightconfig.json` — `include` and `extraPaths` updated.
- `Dockerfile` — `COPY email_triage/ ./email_triage/` (still used by Render / self-hosted Docker).
- `CLAUDE.md` — project-structure diagram and path references updated.

## How to deploy correctly

### FastAPI Cloud (primary target)

```bash
fastapi deploy
```

Requirements that must hold:

- `pyproject.toml` declares `[tool.fastapi] entrypoint = "email_triage.main:app"`.
- The package directory `email_triage/` is at the project root (NOT under `src/`).
- `email_triage/__init__.py` exists.
- `email_triage/main.py` defines `app = FastAPI(…)`.
- Secrets (`GROQ_API_KEY`, `API_KEY`, `LOGFIRE_TOKEN`, `DATABASE_URL`) are set in the FastAPI Cloud dashboard.

### Render (fallback)

Render uses the `Dockerfile` (via `render.yaml`). The multi-stage build with `uv sync --frozen --no-dev --no-editable` installs `email_triage` into `/app/.venv/lib/python3.14/site-packages/`, then runs gunicorn with `UvicornWorker`.

### Local Docker

```bash
docker compose up --build
```

Same Dockerfile, plus the Postgres service from `docker-compose.yml`.

## Do NOT touch

These are the load-bearing decisions. Changing any of them will likely reproduce the incident.

1. **Do NOT reintroduce a `src/` layout.** `email_triage/` must remain at the project root. FastAPI Cloud's `fastapi run` walks from cwd; nesting the package under `src/` hides it.
2. **Do NOT rename the package or move `main.py`.** The entrypoint `email_triage.main:app` is referenced in:
   - `pyproject.toml` → `[tool.fastapi] entrypoint`
   - `Dockerfile` CMD
   - `gunicorn.conf.py` callers
   - FastAPI Cloud's app config
3. **Do NOT add `[tool.fastapi]` fields beyond `entrypoint`.** Anything else is silently ignored (see `fastapi_cli/config.py`).
4. **Do NOT rely on `Dockerfile` changes to fix FastAPI Cloud issues.** Cloud uses its own buildpack. The Dockerfile exists for Render and self-hosted Docker only.
5. **Do NOT set `PYTHONPATH` to work around import issues.** It is a symptom-masker for FastAPI Cloud (which ignores it anyway) and creates divergence between environments.
6. **Do NOT remove `--no-editable` from the Dockerfile's `uv sync` step.** Editable installs depend on `.pth` files at a specific filesystem location; the wheel install puts the package in `site-packages` where every tool finds it predictably.

## Detection / prevention going forward

- **Pre-deploy smoke test**: `uv run python -c "from email_triage.main import app; print(app)"` from the project root in a clean checkout. If this fails, deploy will fail.
- **CI check** (future): run the same import inside a Docker build and inside a vanilla `uv sync` to catch layout regressions before they reach Cloud.
- **`CLAUDE.md` rule (already added)**: project structure section pins the flat layout. New agents must not reorganise it without updating this postmortem.

## References

- `fastapi-cli` discovery: walks `__init__.py` parents only when given a file path (see `fastapi_cli/discover.py:get_module_data_from_path`).
- `fastapi-cli` config schema: only `entrypoint` (`fastapi_cli/config.py:FastAPIConfig`).
- Open discussion on the same incompatibility: <https://github.com/fastapi/fastapi-cli/discussions/255>.
- FastAPI Cloud deployment docs: <https://fastapi.tiangolo.com/deployment/fastapicloud/>.
