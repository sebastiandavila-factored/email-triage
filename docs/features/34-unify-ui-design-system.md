# Unified UI/UX — one design system, light + dark

## What it does

Brings the whole app onto the landing's "control-room" design system: teal/amber palette,
mono kickers, card surfaces — with **light + dark mode everywhere** and the brand renamed
"Email Triage" → **"Triage Studio"** across the UI. Before this, the app pages were Tailwind
indigo/gray with a navbar copy-pasted into five pages and no dark mode, while the landing was a
different-looking product.

## How it works

- **Tokens (single source):** `src/theme.css` defines the semantic CSS vars (`--paper`, `--ink`,
  `--teal`, `--line`, …) for light, `@media (prefers-color-scheme: dark)`, and
  `:root[data-theme="light|dark"]`. The landing no longer declares its own copy — it consumes
  these. `src/index.css` bridges them to Tailwind v4 utilities with `@theme inline`
  (`--color-brand: var(--teal)`, …), so `bg-paper` / `text-ink` / `bg-brand` / `border-line` are
  **theme-aware automatically**.
- **Theme state:** `src/ThemeContext.tsx` (`ThemeProvider` + `useTheme`) sets `data-theme` on
  `<html>`, persists to `localStorage`, and defaults from `prefers-color-scheme`. A pre-paint
  inline script in `index.html` applies it before React mounts → **no flash**. The landing's
  toggle delegates to the same provider, so landing and app share one theme.
- **Shared components (`src/components/ui/`):** `AppShell` (one navbar for every authenticated
  page — replaces the five duplicates), `AuthLayout` (centered card for Login/Signup),
  `ThemeToggle`, and `kit.tsx` primitives (`Button`, `Card`, `SectionHead`, `Field`, `Tag`).
- **Pages:** all 9 restyled to the shell + primitives + tokens (presentation only; handlers
  unchanged). Category chips in Compare use the `--cat-*` tokens; `WorkspaceSwitcher` and
  `TraceChat` restyled to tokens.

## Files involved

| File | Role |
|---|---|
| `frontend/src/theme.css` | design tokens (light/dark) + global base |
| `frontend/src/index.css` | `@theme inline` bridge to Tailwind utilities |
| `frontend/src/ThemeContext.tsx` | theme state + persistence |
| `frontend/index.html` | `<title>` "Triage Studio", no-flash script |
| `frontend/src/components/ui/{AppShell,AuthLayout,ThemeToggle,kit}.tsx` | shared UI |
| `frontend/src/components/{WorkspaceSwitcher,TraceChat}.tsx` | restyled to tokens |
| `frontend/src/pages/*.tsx` (9) | redesigned; brand rename |
| `frontend/src/pages/Landing.{tsx,css}` | consume global tokens; toggle via provider |

## Verified

- Landing, Login, Signup in **light and dark** (browser); theme toggle persists, no flash.
- `tsc --noEmit` + `eslint` + `vite build` green.
- Authenticated pages compile and reuse the verified shell/primitives; final visual pass needs a
  login (see testing doc).
