# Testing — Gmail inbox UI (Plan 38)

## Automated (frontend gates)

```bash
cd frontend
npx tsc --noEmit
npx eslint src
npx vite build
```

All three must be green (no type errors, no lint errors, build succeeds).

## Manual (real session + connected Gmail)

Prerequisite: backend running with a real `DATABASE_URL`, `GROQ_API_KEY`, and the Gmail env
(`GOOGLE_CLIENT_ID/SECRET`, `GMAIL_REDIRECT_URI`, `GMAIL_TOKEN_ENC_KEY`) from
[36 testing](36-gmail-connect-oauth_testing.md); frontend via `npm run dev`.

1. **Log in** (password or Google SSO) and open **Inbox** from the nav.
2. **Not connected:** as owner/admin you see the "Connect your inbox" card with a "Connect Gmail"
   button and the read-only note. As a member you see the "ask an owner/admin" message.
3. **Connect:** click "Connect Gmail" → Google consent → you return to `/inbox?gmail=connected`
   with a "Gmail connected." notice and the header now shows the mailbox address.
4. **Sync:** click "Fetch today's emails":
   - a loading skeleton appears, then the list of today's unread emails.
   - each row shows sender/subject/time + a category tag + confidence.
   - expand a row → draft reply + "Copy reply"; as owner/admin with a trace, the "Ver traces"
     chat panel is available.
5. **Empty inbox:** with no unread emails today → the "No new emails today 🎉" state.
6. **Reconnect path:** revoke access at myaccount.google.com/permissions, sync again → the
   reconnect banner appears (not a raw error); "Reconnect" restarts the flow.
7. **Disconnect** (Settings or Inbox header) → status returns to "not connected".
8. **Theme:** toggle light/dark — the page, cards, tags and states all adapt (Plan 34 tokens).
9. **Settings card:** the Gmail card reflects the same connected/disconnected state.

## Checklist

- [ ] `tsc --noEmit` + `eslint` + `vite build` green
- [ ] `/inbox` protected; visible in the nav
- [ ] Disconnected → "Connect Gmail" (owner/admin) with privacy note; member sees the ask-message
- [ ] Connected → header with mailbox + last sync + "Fetch today's emails"
- [ ] Synced list shows category + confidence; row expands to draft + "Copy reply" (+ traces for owner/admin)
- [ ] Skeleton, celebratory empty, and reconnect (409) states all render
- [ ] Verified in light and dark
