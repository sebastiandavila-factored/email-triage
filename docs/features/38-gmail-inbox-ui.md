# Gmail inbox UI — connect + today's triaged inbox (F3)

## What it does

The user-facing surface for Gmail ingestion: a new **`/inbox`** page where a user connects
Gmail, clicks **"Fetch today's emails"**, and sees each of today's unread emails already
triaged (category + confidence + a draft reply), reusing the same visual language as the
Dashboard result and the unified design system (Plan 34). A connection card also lives in
Settings. Frontend-only — consumes the Plan 36/37 endpoints.

## How it works

- **Routing:** `/inbox` is a `ProtectedRoute` in `App.tsx`; `AppShell` gains an "Inbox" nav link.
- **`pages/Inbox.tsx`:**
  - On mount, fetches `GET /gmail/status`. Not connected → a "Connect Gmail" card (owner/admin
    only, with a read-only privacy note); members see "ask an owner/admin". Connected → a header
    with the mailbox address, last-sync time, "Fetch today's emails", and "Disconnect".
  - **Connect** calls `POST /gmail/connect` (which returns Google's `authorization_url`; identity
    travels in the encrypted OAuth `state`, no cookie) and navigates the browser there. The
    callback redirects back to `/inbox?gmail=connected`; the page reads that flag once at mount and
    strips it from the URL.
  - **Sync** calls `POST /gmail/sync` and renders the returned items. Each row expands to show the
    draft reply with "Copy reply" and, for owner/admin with a `trace_id`, the `TraceChat` panel —
    the exact affordances from the Dashboard.
  - **States:** a loading skeleton while syncing, a celebratory empty state ("No new emails
    today 🎉"), and a reconnect banner when sync returns **409** (expired connection).
- **`api.ts`:** `gmailStatus`, `gmailConnect` (with `credentials:'include'` so the connect
  cookie is stored), `gmailSync`, `gmailDisconnect`, plus `GmailStatus` / `InboxItem` types.
- **`rbac.ts`:** mirrors the backend `gmail:connect` scope (owner + admin) to gate the connect
  affordances. Security is still enforced server-side; this only shows/hides UI.

## Files involved

| File | Role |
|---|---|
| `frontend/src/pages/Inbox.tsx` | the inbox page (connection header, list, states) |
| `frontend/src/pages/Settings.tsx` | Gmail connection card (connect/disconnect) |
| `frontend/src/App.tsx` | `/inbox` protected route |
| `frontend/src/components/ui/AppShell.tsx` | "Inbox" nav entry |
| `frontend/src/api.ts` | `gmailStatus`/`gmailConnect`/`gmailSync`/`gmailDisconnect` + types |
| `frontend/src/rbac.ts` | `gmail:connect` in the owner/admin mirror |

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| Dedicated `/inbox` page | Fold the inbox into the Dashboard | The inbox (a list to work through) is a different mode from the manual triage form |
| Reuse the Dashboard result render (Tag + confidence + Copy + TraceChat) | A bespoke row component | Visual continuity; the user already knows the pattern |
| Connect = `POST` (get URL) then `window.location.assign(url)` | fetch the whole OAuth flow | OAuth consent needs a top-level navigation; a fetch can't complete it. Identity rides in the encrypted `state`, so no cookie is needed cross-origin |
| On-demand "Fetch today's emails" button | Auto-sync on page load | User control + avoids triage cost on every visit; auto-sync is v2 |
| Celebratory empty state | "No data" message | An empty inbox is a good outcome, not an error |
| Derive the `?gmail` notice via a lazy `useState` initializer | `setState` inside an effect | Satisfies `react-hooks/set-state-in-effect`; the effect only strips the URL param |

## Gotchas / Edge cases

- **No cross-origin cookie:** connect identity rides in the encrypted OAuth `state` (Plan 36), so
  the SPA/API origin split needs no third-party cookie and no `allow_credentials`. CORS only had
  to add `DELETE` (for disconnect).
- **409 on sync** → reconnect banner, not a raw error.
- **Member role:** sees a connected inbox and can sync (`triage:write`) but cannot connect or
  disconnect (`gmail:connect`).
- All colors are semantic tokens → light/dark aware automatically (Plan 34).

## Verified

- Frontend gates green: `tsc --noEmit` + `eslint` + `vite build`.
- Dev server boots with the new route/imports and no console errors; `/inbox` is guarded by
  `ProtectedRoute` (unauthenticated → redirected). The authenticated visual pass (connected
  header, triaged list, states) needs a logged-in session against a running backend with a real
  Gmail connection — deferred to the human's e2e pass (same as Plan 36/37's Google validation).
  The intended layout is captured in the design mockup shared with the user.

## Testing

📋 [Testing guide](../testing/38-gmail-inbox-ui_testing.md)
