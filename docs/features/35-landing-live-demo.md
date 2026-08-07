# Live product demo on the landing (hero)

## What it does

Replaces the static "email → refunds → draft" mockup in the landing hero with a **self-playing
product demo**: the app in action — an inbox auto-triaged, one email up close with trace-debugging
via the Logfire MCP, a sync-vs-streaming montage, a category added, and a closing CTA. It plays when
scrolled into view and pauses when it leaves, in the viewer's light/dark theme.

## How it works

- **`components/DemoReel.tsx`** — a self-contained animated screencast (cursor, typing, scenes, loop).
  It renders into a **Shadow DOM**, so its generic class names (`.card`/`.chip`/`.nav`) can never
  collide with the app or the landing. The design tokens (`--teal`, `--paper`, …) are CSS custom
  properties on `:root` (from `theme.css`) and **inherit through the shadow boundary**, so light/dark
  works with no extra code.
- **Mounting** — the landing body is an HTML string (`landingBody.ts`) with a `#demo-mount`
  placeholder where the hero mockup used to be. `Landing.tsx` mounts `<DemoReel>` there with its own
  `createRoot` (not `createPortal`, which is unreliable inside `dangerouslySetInnerHTML`), guarded so
  StrictMode's double-invoke doesn't call `createRoot` twice on one node.
- **Performance / a11y:**
  - **IntersectionObserver** on the host: the animation engine starts when it enters the viewport and
    **pauses (parks its timers)** when it leaves — nothing animates off-screen.
  - The engine runs with a **cancellation token**; every `wait()` bails on cancel and parks on pause.
  - **`prefers-reduced-motion`** and **small screens (<640px)**: no autoplay — a poster with
    "▶ Watch the demo" instead, so a tiny window never autoplays on a phone.
  - **Controls:** pause/resume + restart, overlaid on the app window.

## Files involved

| File | Role |
|---|---|
| `frontend/src/components/DemoReel.tsx` | the demo — Shadow DOM markup + scoped CSS + engine + observer/controls |
| `frontend/src/pages/landingBody.ts` | hero now single-column copy + `#demo-mount` (static mockup removed) |
| `frontend/src/pages/Landing.tsx` | `createRoot(#demo-mount).render(<DemoReel/>)` with a StrictMode-safe guard |

## Verified

- Mounts as the hero (`hosts: 1`, ~537px), plays on view (counter animating), pauses off-view.
- Tokens inherit through the shadow boundary — **light and dark both correct**.
- `tsc --noEmit` + `eslint` + `vite build` green.
- Follow-up: lazy-load the `DemoReel` code (adds ~4KB gzip to the initial bundle today).
