# Testing: Triage Studio F5 — Studio UI

## Prerequisites

- Backend running with a DB (`uv run uvicorn email_triage.main:app --reload`).
- Frontend dev server: `cd frontend && npm run dev` (proxies to the API).
- Log in as an **owner** of a team workspace (full Studio access), and separately as an
  **admin** and a **member** to check gating.
- Static gate: `cd frontend && npm run build` (tsc) and `npx eslint .` — both clean.

## Test Cases

### TC-01: Categories CRUD
**Action**: `/studio` → add a category (slug/name/description); edit a name/description
(blur to save); toggle `active`; delete one.
**Expected**: changes persist across reload. Duplicate slug → inline 409; reserved
`unknown` → 422; deleting the last active → 409.

### TC-02: Examples per category
**Action**: Pick a category → add a positive and a negative example; delete one.
**Expected**: list updates; the example shows in **Preview** under `<examples>`.

### TC-03: Prompt draft + preview
**Action**: Fill `tone` (e.g. "Be concise"); Save draft; Preview.
**Expected**: preview `<style>` block contains the tone; empty blocks fall back to defaults;
`allowed_slugs` lists the active slugs + `unknown`.

### TC-04: Publish + banner (owner)
**Action**: As owner, click **Publish current draft**.
**Expected**: a version appears (v1, active); the amber "published wins" banner shows.

### TC-05: Rollback
**Action**: Publish again (v2), then **Activate** v1.
**Expected**: v1 becomes active; `/triage` serves it.

### TC-06: Role gating
**Action**: Open `/studio` as `member`, then `admin`.
**Expected**: `member` sees read-only (no create/edit/delete/publish controls); `admin` can
edit categories/examples/draft but has **no** Publish/Activate buttons (owner-only).

## Edge Cases

| Scenario | Expected |
|---|---|
| Non-member opens `/studio` for a workspace they left | API 403 surfaces as an inline error |
| Preview with zero active categories | 409 "at least one active category" shown inline |
| Slug field in edit | Not present — slug is immutable (read-only code) |

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| Publish button missing | Not an owner | `prompt:publish` is owner-only |
| Edits don't change `/triage` output | A version is published ("published wins") | Publish again, or activate a version |
| eslint `set-state-in-effect` | setState called synchronously in an effect | Set state only in async `.then` guarded by `active` |
