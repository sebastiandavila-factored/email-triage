# Testing Plan — Feature 14: PostgreSQL + SQLAlchemy Persistence

## Scope

Verifies the async DB persistence layer: ORM insert correctness, cascade deletes, fire-and-forget background task integration, and optional DB (no-op when `DATABASE_URL` is absent).

## Test environment

- **Engine**: `sqlite+aiosqlite:///:memory:` — no Docker required.
- **Fixture**: `db_session` in `tests/conftest.py` creates the schema via `Base.metadata.create_all`, yields an `AsyncSession`, then tears down.
- **No external calls**: all tests are fully offline.

## Test cases

### TC-01 — Insert triage log

**File**: `tests/test_db.py::test_insert_triage_log`

**Steps**:
1. Call `TriageLogRepo.insert_log()` with a `TriageRequest` and `TriageResponse`.
2. Flush the session.
3. Query the `triage_logs` table.

**Expected**: one row with correct `request_id`, `category`, `confidence`, `latency_ms`, `endpoint`, `model_id`, `subject_chars`, and `body_chars`.

---

### TC-02 — Insert eval run and cases

**File**: `tests/test_db.py::test_insert_eval_run_and_cases`

**Steps**:
1. Call `EvalRepo.insert_run()` with aggregate metrics.
2. Call `EvalRepo.insert_cases()` with two case dicts — one correct, one incorrect.
3. Flush and query `eval_runs` and `eval_cases`.

**Expected**:
- `EvalRun` row has correct `n_cases`, `accuracy`, `ece`, `mean_judge_score`.
- `EvalCase` rows: correct case has `judge_overall=5`, `judge_language_match=True`; incorrect case has `judge_overall=None`.

---

### TC-03 — EvalCase cascade delete

**File**: `tests/test_db.py::test_eval_case_cascade_delete`

**Steps**:
1. Insert an `EvalRun` with one `EvalCase`.
2. Delete the `EvalRun` row.
3. Query `eval_cases`.

**Expected**: no `EvalCase` rows remain (CASCADE enforced at DB level).

---

### TC-04 — No-op when DATABASE_URL is absent (manual)

**Steps**:
1. Ensure `DATABASE_URL` is not set in the environment.
2. Start the app with `make dev`.

**Expected**: app starts cleanly. `_log.info("db.connected")` is **not** emitted. `POST /triage` returns `200` as before.

---

### TC-05 — `persist_triage_log` swallows exceptions (manual)

**Steps**:
1. Configure a `DATABASE_URL` pointing to a host that is down.
2. Call `POST /triage`.

**Expected**: HTTP `200` returned (background task failure is swallowed); `triage_log.db_write_failed` log emitted by `structlog`.

---

### TC-06 — Alembic migration applies cleanly (manual)

**Steps**:
1. Run `make db-up`.
2. Run `make db-migrate`.

**Expected**: `alembic upgrade head` exits 0. Connecting via `make db-shell` and running `\dt` shows `tenants`, `triage_logs`, `eval_runs`, `eval_cases`.

---

### TC-07 — Eval run persisted to DB (manual)

**Steps**:
1. Set `DATABASE_URL` in `.env`.
2. Run `make eval-quick`.

**Expected**: `eval_run.persisted` log emitted with `n_cases=40`. Query `SELECT * FROM eval_runs ORDER BY ran_at DESC LIMIT 1;` shows a row.

## Running the automated tests

```bash
make test          # runs all 20 tests including the 3 DB tests
uv run pytest tests/test_db.py -v   # DB tests only
```
