# Day 1 — Skeleton + Tooling

## What it does

Establishes the project foundation before coding functionality: installable package, formatter, linter, type checker and hooks that validate everything before each commit. When Day 2 starts there is already a safety net — no code "passes" without formatting, broken types or dead imports.

## How it works

There are three layers worth keeping mentally separate:

1. **Package layer** (`pyproject.toml` + `src/` + hatchling): makes `email_triage` importable as an installed Python module, not as a loose script next to the cwd.
2. **Quality layer** (ruff + pyright + configs in `pyproject.toml`): defines the format and type rules.
3. **Enforcement layer** (`pre-commit` + git hooks): applies the rules automatically before each commit.

## Files involved

| File | Role |
|---|---|
| `pyproject.toml` | Package metadata, deps, tooling configs |
| `src/email_triage/__init__.py` | Marks the directory as a Python package |
| `src/email_triage/main.py` | FastAPI app with `GET /health` |
| `.python-version` | Pins Python 3.14 for `uv` and `pyenv` |
| `.env` / `.env.example` | Real local secrets (gitignored) vs committable template |
| `.gitignore` | Excludes `.env`, caches, IDE, venv |
| `.pre-commit-config.yaml` | Hook pipeline (ruff, pyright) |

## The `pyproject.toml`, block by block

### `[project]` — who this package is

```toml
[project]
name = "email-triage"
version = "0.1.0"
description = "AI email triage API: classify support emails and draft replies"
readme = "README.md"
requires-python = ">=3.14"
dependencies = ["fastapi>=0.136.3", "httpx>=0.28.1", "uvicorn>=0.48.0"]
```

- **`name`** — the package name on PyPI **and** the `pip install <name>`. Not the module name (`email_triage`). Convention: `kebab-case` in name, `snake_case` in module.
- **`version`** — semver. When we deploy, this number appears in `/openapi.json → info.version`.
- **`requires-python`** — locks the venv. If someone has Python 3.13, `uv sync` fails with a clear message. Kills "works on my machine".
- **`dependencies`** — runtime only. Development tools go in `dependency-groups`.

### `[dependency-groups]` — separate dev from runtime

```toml
[dependency-groups]
dev = ["pre-commit>=4.6.0", "pyright[nodejs]>=1.1.409", "ruff>=0.15.15"]
```

PEP 735 (2024) moved development deps from `[project.optional-dependencies]` to `[dependency-groups]`. Key difference: extras are published with the package; groups are private to the project. If someone does `pip install email-triage`, they **don't** get `ruff`.

`uv sync` installs the `dev` group by default. In the Day 6 Dockerfile we will use `uv sync --no-dev`.

### `[build-system]` — how the package is built

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Without this block, `pyproject.toml` declares metadata but the package **is not installable**. When you run `uv sync`, uv:

1. Reads `[build-system]`.
2. Installs `hatchling` in an isolated venv.
3. Asks hatchling to build a wheel of the project.
4. Installs the wheel in `.venv/` in **editable** mode (code changes are reflected without reinstalling).

**Discarded alternatives:**

- `setuptools` — the historical default; more verbose, requires `setup.cfg` or `setup.py`.
- `poetry-core` — tied to Poetry; adding another tool alongside uv is redundant.
- `pdm-backend` — tied to PDM.
- `hatchling` — from the Hatch team, minimal, declarative, recommended by PyPA.

### `[tool.hatch.build.targets.wheel]` — where the code is

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/email_triage"]
```

We tell hatchling: "the `email_triage` package lives in `src/email_triage/`". Without this, hatchling looks for a package with the same name as the project at the root, doesn't find it, and fails.

**Why `src/` layout instead of flat:**

When Python starts, it adds cwd to `sys.path`. With flat layout (`email_triage/` at root), `import email_triage` works in dev even if the package isn't installed — because it's next to the script. That **masks bugs**: your package depends on files that only exist in dev, and when installing the wheel it fails in production. With `src/`, the import only works from the installed wheel. If your tests pass, you know the wheel is correctly built.

### `[tool.ruff]` — format and lint

```toml
[tool.ruff]
line-length = 100
target-version = "py314"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.ruff.format]
quote-style = "double"
```

`ruff` is formatter + linter in a single tool. Replaces `black` + `isort` + `flake8` + `pyupgrade` with Rust speed.

**Each selector we activate:**

| Selector | What it checks | Example error caught |
|---|---|---|
| `E` | pycodestyle errors (PEP 8) | `E501` line > 100 chars |
| `F` | pyflakes | `F401` unused import, `F841` unused variable |
| `I` | isort | Unsorted or ungrouped imports |
| `UP` | pyupgrade | Suggest `dict[str, int]` instead of `Dict[str, int]` |
| `B` | flake8-bugbear | `B008` mutable default arg, `B904` raise without `from` |
| `SIM` | flake8-simplify | `SIM102` `if x: if y:` → `if x and y:` |

What we **don't** activate on purpose:

- `D` (docstrings) — `CLAUDE.md` says "default no comments". Forcing docstrings on every function is noise.
- `ANN` (annotations) — pyright already handles this in strict mode.
- `C90` (complexity) — weak metric, better to review manually.

`line-length = 100` — 88 (Black's default) is from when monitors were small. 100 gives more space without sacrificing diff readability.

`target-version = "py314"` — ruff writes assuming 3.14 features (e.g. doesn't suggest `from __future__ import annotations`).

### `[tool.pyright]` — type checker

```toml
[tool.pyright]
include = ["src", "tests"]
typeCheckingMode = "strict"
pythonVersion = "3.14"
```

`pyright` is Microsoft's type checker (same engine as Pylance in VS Code). Strict mode requires:

- All parameters and returns typed
- No implicit `Any`
- Report unresolved imports
- Validate generics strictly

It's aggressive, but catches bugs before runtime. In a small project the errors are few and the fixes are surgical.

**Why `pyright[nodejs]` instead of `pyright`:**

pyright is written in TypeScript and runs on Node.js. The `pyright` PyPI package is a wrapper that tries to use the system Node. On this machine there's no Node installed, and the fallback (`nodeenv`) failed to compile against Python 3.14. `pyright[nodejs]` downloads a portable Node binary as a wheel — self-contained, no system installation.

## The `src/` layout in practice

```
src/
└── email_triage/
    ├── __init__.py    # empty; marks the directory as a package
    └── main.py        # `app = FastAPI(...)`
```

After `uv sync`, the venv has `email_triage` installed in editable mode. That means:

- `from email_triage.main import app` works from anywhere (tests, scripts, uvicorn).
- Edit `main.py` and the change is visible without reinstalling.
- The command that starts the server is `uv run uvicorn email_triage.main:app --reload`.

The `email_triage.main:app` is an import path — `email_triage.main` is the module, `app` is the attribute (the `FastAPI` instance).

## `.env`, `.env.example` and the pattern

`.env` contains real secrets (`GROQ_API_KEY=gsk_real_...`) and is in `.gitignore`. `.env.example` is committed with placeholders. When someone clones the repo:

```bash
cp .env.example .env
# edit .env with their real values
```

`pydantic-settings` (Day 4) reads `.env` by convention, so `python-dotenv` is not needed in production code. For Day 2 and 3, scripts use `uv run --env-file .env python ...` which loads `.env` into the environment for that invocation.

## pre-commit hooks — how they work under the hood

`pre-commit` is a meta-runner of git hooks. The flow:

1. When you run `uv run pre-commit install`, it writes a script to `.git/hooks/pre-commit`.
2. Before each commit, git executes that script.
3. The script reads `.pre-commit-config.yaml` and runs each hook on staged files.
4. If any hook fails (ruff finds an error it can't auto-fix, pyright reports a bad type), the commit is aborted.
5. If ruff or ruff-format apply fixes, the files are left modified but **not staged** — you need to `git add` again and commit again.

**Why `local` for pyright instead of the official repo:**

```yaml
- repo: local
  hooks:
    - id: pyright
      name: pyright
      entry: uv run pyright
      language: system
      types: [python]
      pass_filenames: false
```

The official pyright repo (`RobertCraigie/pyright-python`) creates its own venv to run pyright, **without access to the project's deps**. That makes pyright not find `fastapi`, `pydantic`, etc. and report false positives. Using `uv run pyright` from `local` makes it use the project's venv and imports resolve correctly. `pass_filenames: false` runs pyright on the whole project, not file by file (important because pyright understands the full type graph).

## Design decisions

| Decision | Alternative | Reason |
|---|---|---|
| `uv` | `pip` + `virtualenv` + `pyenv` | One tool for deps, locks, venv and Python install. 10-100× faster |
| `hatchling` build backend | `setuptools` / `poetry-core` | Minimal, declarative, no `setup.py`, recommended by PyPA |
| `src/` layout | Flat (`email_triage/` at root) | Tests only pass if the wheel is correct — catches packaging bugs |
| `ruff` (format + lint) | `black` + `isort` + `flake8` | One tool vs three, Rust speed, shared config |
| `pyright` strict | `mypy` | Strict by default, better inference, native VS Code integration |
| `pyright[nodejs]` | `pyright` + system Node | Doesn't require installing Node separately; portable binary |
| `pre-commit` with `local` for pyright | Official pyright repo | Project venv resolves imports correctly |
| line-length 100 | 88 (Black default) | 2026 monitors; better space usage without losing diff readability |

## Gotchas / Edge cases

- **If you change `[build-system]` or `[tool.hatch...]` in `pyproject.toml`, run `uv sync` before coding.** The venv has the "old" wheel and imports can break in weird ways.
- **Untracked files don't go through pre-commit with `--all-files`.** Pass them explicitly with `--files <path>` or stage them first (`git add`).
- **ruff-format and ruff-check can clash.** `ruff check --fix` can add imports that `ruff format` then reorders. The order in `.pre-commit-config.yaml` (check first, format after) is designed to minimize back-and-forth.
- **Pyright strict in `tests/`:** when we add tests on Day 5, watch out with `pytest.fixture` — the decorator loses types. Solution: explicit annotations on test arguments.
- **Python 3.14 is very new.** If a dep doesn't have a wheel for 3.14, `uv sync` may be slow (compiles from source) or fail. Suspect #1 if something breaks; fall back to 3.13 in `.python-version`.

## Testing

📋 [Testing guide](../testing/01-day1-skeleton_testing.md)
