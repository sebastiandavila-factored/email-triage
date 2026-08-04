# Testing: Triage Studio F2 — Prompt compiler + dynamic output type

## Prerequisites

- Real DB + migrations (`uv run alembic upgrade head`), a workspace with an API key,
  and a valid `GROQ_API_KEY` for the live checks.
- Automated: `uv run pytest tests/test_prompt_compiler.py tests/test_triage.py -v`.
- `$KEY` = the workspace API key; `$TID` / `$TOKEN` for category edits (F1 endpoints).

## Test Cases

### TC-01: Classify against the tenant's taxonomy
**Action**: Add a category the legacy enum never had (e.g. `warranty`) via
`POST /workspaces/$TID/categories`, then `POST /triage` (with `$KEY`) an email that
clearly asks about a warranty.
**Expected**: 200, `category` may be `warranty` — a value impossible under the legacy
5-category enum. Proves the compiled prompt drives classification.

### TC-02: Live edit reflected without restart
**Action**: Call `/triage` once. Then rename/add a category. Call `/triage` again.
**Expected**: The second call reflects the new taxonomy immediately (the service
cache is keyed by a taxonomy version that changed). No process restart.

### TC-03: Hallucinated / stale slug → unknown
**Action**: Hard to force manually; covered by
`test_hallucinated_slug_coerced_to_unknown`. Conceptually: if the model returns a
slug not in the active set, the response `category` is `unknown`.
**Expected**: `/triage` never returns a category outside the tenant's active slugs ∪ `{unknown}`.

### TC-04: Streaming carries a valid category
**Action**: `POST /triage/stream` with `$KEY`.
**Expected**: `event: meta` carries a `category` that is an active slug or `unknown`;
`event: done` terminates the stream.

### TC-05: Regression — no-DB path unchanged
**Action**: Run the suite with the static API key path (`tests/test_triage.py`).
**Expected**: Identical behavior to pre-F2; classification still uses the legacy
prompt + enum. `/triage` shape unchanged.

### TC-06: Fallback when taxonomy unreadable
**Action**: (unit) `test_no_tenant_falls_back_to_legacy`; conceptually, a tenant with
no active categories or a DB error.
**Expected**: `/triage` serves via the legacy service; a `prompt.fallback` warning is
logged with a `reason`. No 500.

## Edge Cases

| Scenario | Expected |
|---|---|
| Category `name`/`description` contains `<`, `>`, `&`, `"` | Escaped in the compiled prompt; no raw markup leaks |
| Compiled prompt vs active categories | Every active slug + `unknown` present (structural invariant) |
| Two calls, same taxonomy | Same cached `LLMService` instance (identity) |
| Deactivate a category | Next `/triage` no longer offers it (new version → rebuild) |
| >256 distinct active taxonomies in-process | Bounded LRU evicts oldest; recomputed on next hit |

## Log / trace verification

- `triage.sync` span attrs: `tenant_id`, `triage.dynamic` (bool).
- `prompt.fallback` warning with `reason ∈ {taxonomy_query_failed, no_active_categories}`.
- `triage_logs.category` stores the (coerced) slug string.

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| `/triage` still returns only the 5 legacy categories | No API key / no-DB path, or tenant has no active categories | Use the workspace `X-API-Key`; confirm active categories exist |
| `AttributeError: allowed_slugs` in a custom test double | Double bypasses `LLMService.__init__` and shadows the class attr | Don't override it, or set `allowed_slugs = None` |
| Category edit not reflected | Looking at a different worker's cache | Per-process cache; version-keyed — a new request on that worker rebuilds |
