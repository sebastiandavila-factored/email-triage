# Testing: Unified UI/UX (light + dark)

## Prerequisites

- Gates: `cd frontend && npx tsc --noEmit && npx eslint . && npx vite build`.
- Manual: `cd frontend && npm run dev`, and a login (Google SSO or email/password) to reach the
  authenticated pages.

## Test Cases

### TC-01: no "Email Triage" in the UI
Grep + spot-check: the brand is "Triage Studio" everywhere (navbar, auth cards, `<title>`). The
only residual "email-triage" is a code comment in `api.ts` referring to the backend package.

### TC-02: theme toggle + persistence + no flash
Toggle light/dark from the navbar (app) or the landing's Theme button. **Expected**: the whole UI
flips; reloading keeps the choice (localStorage) with **no light→dark flash**; a fresh profile
follows the OS `prefers-color-scheme`.

### TC-03: landing / login / signup in both themes (verified)
**Expected**: teal/amber palette, brand glyph `</>`, readable contrast in light and dark.

### TC-04: authenticated pages in both themes
Log in and walk Dashboard, Studio, Settings, Workspace, Compare in light and dark.
**Expected**: one shared navbar (brand + Compare/Workspace/Studio/Settings + theme toggle +
logout), cards on `bg-ground`, brand-teal primary buttons/links, no hardcoded grays that break in
dark.

### TC-05: functional regression
**Expected**: triage runs; "Ver traces" chat works; Studio (categories / few-shot / publish /
rollback), Settings (rotate API key), Workspace (members / invites) all operate as before — only
presentation changed.

## Gates

`cd frontend && npx tsc --noEmit && npx eslint . && npx vite build` — green.
