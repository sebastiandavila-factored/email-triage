# 17. React Frontend — Auth + Triage UI

**Status:** 📋 proposed
**Estimate:** 5 hrs
**Depends on:** Plan 16 (Users + Password Auth + JWT)

## Intent

The API is fully functional but requires Postman or curl to use. This plan adds a minimal React SPA that covers the two core user flows: authentication (signup, login, Google SSO) and email triage (submit an email, view the AI classification and draft reply). The goal is to practice connecting a React frontend to a JWT-secured FastAPI backend — a standard full-stack pattern — and to have a working UI for demos.

The frontend lives in `frontend/` inside the same repo (monorepo). This avoids coordinating two repos during MVP development. Splitting into a separate repo is straightforward later if the teams diverge.

## Prior reading

**Vite + React + TypeScript:**
- **Vite Getting Started** — https://vite.dev/guide/
- **React — Adding TypeScript** — https://react.dev/learn/typescript

**Auth and JWT in the browser:**
- **OWASP — HTML5 Security Cheat Sheet (storage)** — https://cheatsheetseries.owasp.org/cheatsheets/HTML5_Security_Cheat_Sheet.html
- **Auth0 blog — Where to store tokens** — https://auth0.com/docs/secure/security-guidance/data-security/token-storage
- **RFC 6749 §4.2 — Implicit grant (why fragments are safer than query params)** — https://datatracker.ietf.org/doc/html/rfc6749#section-4.2

**React patterns used:**
- **React Context** — https://react.dev/reference/react/createContext
- **React Router v7** — https://reactrouter.com/start/framework/routing

**Tailwind CSS:**
- **Tailwind CSS v4 — Installation with Vite** — https://tailwindcss.com/docs/installation/using-vite

## Scope

**Included:**
- `frontend/` directory with Vite + React 18 + TypeScript + Tailwind CSS v4
- `AuthContext` — stores JWT in `localStorage`; exposes `user`, `login`, `logout`, `signup`
- `ProtectedRoute` — redirects to `/login` if no valid token
- Pages: `/login`, `/signup`, `/dashboard`, `/settings`
- Google SSO: "Continue with Google" button → redirect flow → backend returns token via URL fragment
- One backend change: after `/auth/callback`, redirect browser to `{FRONTEND_URL}/#token=<jwt>` instead of returning JSON
- `Makefile` targets: `make frontend-dev`, `make frontend-build`
- `frontend/.env.example` documenting `VITE_API_URL`

**Out of scope:**
- Streaming triage UI (`/triage/stream`) — add in a follow-up plan
- Token refresh / silent refresh
- Toast notifications / error UI polish
- Tests (Vitest / Playwright) — Plan 19
- Production deploy of the frontend (Vercel/Netlify) — Plan 20

## Repository layout

```
email-triage/                  ← existing repo, unchanged Python layout
├── email_triage/
├── frontend/                  ← new
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── .env.example           ← VITE_API_URL=http://localhost:8000
│   └── src/
│       ├── main.tsx
│       ├── App.tsx            ← router setup
│       ├── api.ts             ← typed fetch wrappers for all endpoints
│       ├── AuthContext.tsx    ← JWT state + localStorage persistence
│       ├── ProtectedRoute.tsx
│       └── pages/
│           ├── Login.tsx
│           ├── Signup.tsx
│           ├── Dashboard.tsx
│           └── Settings.tsx
├── tests/
├── Makefile
└── pyproject.toml
```

## Pages

| Route | Auth required | Description |
|---|---|---|
| `/login` | No | Email + password form, "Continue with Google" button |
| `/signup` | No | Signup form (email, password, display name) |
| `/dashboard` | Yes | User greeting, email triage form, result card |
| `/settings` | Yes | Workspace info (tenant name, plan, role), rotate API key button |

## JWT storage decision

JWT is stored in `localStorage`. This is the simplest approach and standard in learning/demo contexts.

**The tradeoff:** `localStorage` is accessible to any JavaScript on the page, making the token vulnerable to XSS attacks. The alternative — `httpOnly` cookies — is more secure but requires changing the backend to set cookies (incompatible with stateless Bearer tokens as currently designed).

For production, the recommended upgrade path is:
1. Keep JWT short-lived (30 min — already our default)
2. Add a strict Content Security Policy (CSP) to mitigate XSS
3. Or switch to `httpOnly` cookies + a CSRF token when the product matures

For this MVP, `localStorage` is acceptable and keeps the frontend simple.

## Google SSO redirect flow

The existing `/auth/callback` returns JSON — correct for Postman, wrong for a browser that just finished the Google redirect and has nowhere to send the token.

**Solution:** detect the `Accept` header or add a `?mode=browser` query param. When coming from a browser, after the callback succeeds, redirect to:

```
{FRONTEND_URL}/#token=eyJhbGci...&token_type=bearer
```

The URL fragment (`#`) is never sent to the server, so the token does not appear in access logs. The frontend reads `window.location.hash` on mount and stores the token.

**One backend change required** in `email_triage/routers/auth.py` → `GET /auth/callback`:
- Read new `Settings.frontend_url` (default: `http://localhost:5173`)
- If request has `Accept: text/html` (browser), redirect to `{frontend_url}/#token=<jwt>&...`
- Otherwise (API client / Postman), return JSON as today — backward compatible

## AuthContext API

```typescript
interface AuthUser {
  user_id: string
  email: string
  display_name: string
  email_verified: boolean
  tenant_id: string
  tenant_name: string
  tenant_type: string
  plan: string
  role: string
}

interface AuthContextValue {
  user: AuthUser | null
  token: string | null
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  signup: (email: string, password: string, displayName: string) => Promise<void>
  logout: () => void
}
```

On mount, `AuthContext` reads the token from `localStorage`, calls `GET /auth/me` to validate it (expired tokens are rejected by the backend), and populates `user`. If the call fails, it clears the token.

## Dashboard — triage form

```
┌─────────────────────────────────────────────────┐
│  Email Triage                    [Settings] [Logout]
├─────────────────────────────────────────────────┤
│  Subject  [________________________________]     │
│  From     [________________________________]     │
│  Body     [________________________________]     │
│           [________________________________]     │
│           [________________________________]     │
│                              [Triage email ▶]   │
├─────────────────────────────────────────────────┤
│  Category:   REFUNDS           Confidence: 0.94 │
│  Draft reply:                                   │
│  "We will process your refund within 48 hours." │
└─────────────────────────────────────────────────┘
```

Calls `POST /triage` with the `X-Api-Key` header (stored alongside the JWT after signup, or entered manually in Settings).

## Concrete changes

| File | Change |
|---|---|
| `frontend/` | New directory — full React app |
| `email_triage/config.py` | Add `frontend_url: str = "http://localhost:5173"` |
| `email_triage/routers/auth.py` | In `/auth/callback`: if browser request, redirect to `{frontend_url}/#token=...` |
| `.env.example` | Add `FRONTEND_URL=http://localhost:5173` |
| `Makefile` | Add `frontend-dev`, `frontend-build`, `frontend-install` targets |
| `docs/exec-plans/README.md` | Entry #17 |

## Tech stack

| Tool | Version | Role |
|---|---|---|
| Vite | ≥6.0 | Build tool + dev server |
| React | ≥18.3 | UI framework |
| TypeScript | ≥5.6 | Type safety |
| Tailwind CSS | v4 | Utility-first styles (no config file in v4) |
| React Router | v7 | Client-side routing |
| Native `fetch` | — | HTTP calls (no library needed for this scope) |

No component library (shadcn, MUI, etc.) — keeping it minimal and learning-focused.

## Makefile additions

```makefile
frontend-install: ## Install frontend dependencies
	cd frontend && npm install

frontend-dev: ## Start frontend dev server (requires backend running on :8000)
	cd frontend && npm run dev

frontend-build: ## Build frontend for production
	cd frontend && npm run build
```

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| Monorepo (`frontend/`) | Separate repo | Single team, MVP; one commit can span frontend + backend changes; trivial to split later |
| Vite + React + TypeScript | Next.js, Remix, CRA | Vite is the fastest bare-bones setup; no SSR complexity; matches the learning goal |
| Tailwind CSS v4 | shadcn/ui, MUI, plain CSS | No component library adds cognitive load; Tailwind teaches utility patterns without magic |
| `localStorage` for JWT | `httpOnly` cookie | Keeps backend stateless Bearer design; acceptable for MVP with short-lived tokens |
| URL fragment for Google SSO token | Query param, postMessage | Fragment is never sent to server; cleaner than query param which appears in logs |
| Native `fetch` | axios, TanStack Query | Scope is small enough; avoids an extra dependency; teaches the underlying API |
| `Accept: text/html` detection for SSO redirect | `?mode=browser` query param | Browsers set `Accept: text/html` automatically; no URL pollution; API clients (Postman) set `Accept: application/json` |

## Execution order

1. **Bootstrap** (30 min): `npm create vite@latest frontend -- --template react-ts`; add Tailwind v4; add React Router v7; confirm dev server starts.
2. **`api.ts`** (30 min): typed wrappers for all endpoints (`signup`, `login`, `me`, `triage`, `rotateKey`).
3. **`AuthContext`** (30 min): JWT storage, `login`/`signup`/`logout`, `GET /auth/me` on mount, fragment reader for Google SSO.
4. **`ProtectedRoute`** (15 min): redirects to `/login` if `token === null`.
5. **Login + Signup pages** (45 min): forms, error messages, "Continue with Google" button.
6. **Dashboard page** (45 min): triage form + result card.
7. **Settings page** (30 min): workspace info + rotate key button.
8. **Backend change** (20 min): `frontend_url` in Settings; redirect in `/auth/callback` for browser requests.
9. **Makefile + `.env.example`** (10 min): `frontend-dev`, `frontend-build`, `frontend-install` targets.
10. **Smoke test** (15 min): full end-to-end: signup → dashboard → triage → settings.

## Done when

- [ ] `make frontend-install && make frontend-dev` starts the React app on port 5173
- [ ] `POST /auth/signup` from the form creates a user and lands on `/dashboard`
- [ ] `POST /auth/login` from the form logs in and lands on `/dashboard`
- [ ] "Continue with Google" completes the SSO flow and lands on `/dashboard`
- [ ] `POST /triage` from the dashboard form returns a category + draft reply
- [ ] `/settings` shows workspace info and rotate-key works
- [ ] Navigating to `/dashboard` without a token redirects to `/login`
- [ ] `make frontend-build` produces a `frontend/dist/` with no build errors
