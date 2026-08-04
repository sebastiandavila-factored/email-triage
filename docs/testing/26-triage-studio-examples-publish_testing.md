# Testing: Triage Studio F3 — Few-shot + template overrides + publish

## Prerequisites

- Real DB + migrations (`uv run alembic upgrade head`); a team workspace with an
  `owner`, an `admin`, a `member`, and a category id `$CID`.
- `$TID`/`$TOKEN(role)` for the Studio endpoints (Bearer session).
- Automated: `uv run pytest tests/test_prompt_studio.py -v`.

## Test Cases

### TC-01: Add a few-shot example (owner/admin)
**Action**: `POST /workspaces/$TID/categories/$CID/examples`
`{"kind":"positive","subject":"Where is my order","body":"...","expected_reply":"..."}`
**Expected**: 201. `member` → 403 (`triage:configure`).

### TC-02: Example appears in the compiled prompt
**Action**: `POST /workspaces/$TID/prompt/preview` (admin/owner).
**Expected**: 200; `prompt` contains an `<examples>` block with an
`<example kind="positive">` and `<classification>$slug</classification>`.

### TC-03: Edit template blocks
**Action**: `PUT /workspaces/$TID/prompt/draft` `{"tone":"Be concise and warm."}`, then
preview.
**Expected**: preview contains `<style>\nBe concise and warm.\n</style>`.

### TC-04: Publish (owner only)
**Action**: `POST /workspaces/$TID/prompt/publish`.
**Expected**: `admin` → 403 (`prompt:publish`); `owner` → 201 with `version:1`,
`is_active:true`.

### TC-05: Published wins — edits no longer live
**Action**: Publish. Then deactivate a category. Call `/triage` (workspace API key).
**Expected**: `/triage` still classifies against the **published** taxonomy until the
owner publishes again. (Automated: `test_published_version_wins_over_live_compile`.)

### TC-06: Eval-gate blocks a regression
**Action**: (service-level) publish with a gate returning high metrics (baseline), then
publish again with a gate returning much lower metrics.
**Expected**: second publish → 409 `Eval-gate failed: accuracy … vs baseline …`.
(Automated: `test_eval_gate_blocks_regression`.)

### TC-07: Rollback
**Action**: Publish twice (v1, v2). `POST /workspaces/$TID/prompt/versions/1/activate`.
**Expected**: 200, `version:1`, `is_active:true`; `/triage` serves v1 again.

### TC-08: Unpublished tenant keeps F2 live-compile
**Action**: A workspace that never published: add an example, then `/triage`.
**Expected**: the example is live in the prompt immediately (no publish needed).

## Edge Cases

| Scenario | Expected |
|---|---|
| `kind` not in {positive, negative} | 422 |
| Example on a category of another tenant | 404 |
| > 20 examples on one category | 409 |
| Publish with zero active categories | 409 |
| Delete an example that doesn't exist / other tenant | 404 |

## Log / trace verification

- `example.created`, `prompt_version.published` (with `version`), `prompt_version.activated`.
- `prompt.fallback` (`reason=no_active_categories`) when a tenant has no active categories.

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| Category edit not reflected in `/triage` | Tenant has a published version ("published wins") | Publish again, or roll back to a version, to change what `/triage` serves |
| Publish returns 409 "at least one active category" | All categories inactive | Activate/create a category first |
| Publish never blocks on bad metrics | Router publishes with `gate=None` | The eval-gate is exercised at the service level; wire a real gate to enforce in prod |
