# Triage Studio F5 — Studio UI (React)

## What it does

A no-code UI at `/studio` where owners/admins configure their workspace: manage
categories, add few-shot examples, edit the prompt's template blocks, **preview** the
compiled XML, and **publish / roll back** prompt versions. Consumes the F1–F3 API with
the frontend's existing conventions (`api.ts` typed client, `useAuth`, `can(role, scope)`,
Tailwind). Frontend-only — no backend change.

## How it works

```
/studio (ProtectedRoute) → Studio.tsx
  loads: categories, prompt versions, draft  (Promise.all on mount / workspace change)
  Categories  → list + inline edit (name/description/active) + delete + create
  Examples    → pick a category → list + add (kind/subject/body/reply?) + delete
  Prompt      → role/task/guardrails/tone textareas → Save draft + Preview (shows XML)
  Versions    → Publish (owner) + list w/ metrics + Activate (rollback)
```

- **Role gating** mirrors the backend via `can()`: editing needs `triage:configure`
  (owner/admin), publish/rollback needs `prompt:publish` (owner). Members read only.
  It is convenience only — the backend re-checks every request.
- **"Published wins" banner:** when an active version exists, a banner tells the user that
  edits won't hit `/triage` until they publish again — surfacing the F3 governance model.
- **Preview** calls the backend's `/prompt/preview` (single source of truth for the
  compiler), never recompiles in JS.

## Files involved

| File | Role |
|---|---|
| `frontend/src/api.ts` | `Category`/`TriageExample`/`PromptDraft`/`PromptPreview`/`PromptVersion` + methods |
| `frontend/src/rbac.ts` | `triage:configure`, `prompt:publish` added to the scope mirror |
| `frontend/src/pages/Studio.tsx` | the Studio page |
| `frontend/src/App.tsx` | `/studio` protected route |
| `frontend/src/pages/Dashboard.tsx`, `Workspace.tsx` | "Studio" nav link |

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| One page with sections | Multiple routes | Configuration is a linear flow; less navigation |
| Reuse `can()` for gating | Ad-hoc role checks | Consistency with the Workspace UI; backend re-validates |
| Preview via endpoint | Recompile in JS | One source of truth (the backend compiler) |
| Inline edit on blur | A modal edit form | Fewer clicks for name/description tweaks |
| Slug read-only in edit | Editable slug | Slug is immutable (it is the classification value) |

## Gotchas / Edge cases

- **`react-hooks/set-state-in-effect`:** the mount effect inlines the `Promise.all` and sets
  state only in the async `.then` (guarded by an `active` flag) — never synchronously in the
  effect body. `loadAll` (useCallback) is used by the mutation handlers, not the effect.
- **No frontend test infra:** the gate is `npm run build` (tsc) + `eslint`. Visual/E2E
  verification is manual against a running backend.

## Testing

📋 [Testing guide](../testing/28-triage-studio-ui_testing.md)
