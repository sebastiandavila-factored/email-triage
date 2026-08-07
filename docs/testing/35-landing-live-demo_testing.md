# Testing: Live product demo on the landing

## Prerequisites

- Gates: `cd frontend && npx tsc --noEmit && npx eslint . && npx vite build`.
- Manual: `cd frontend && npm run dev`, open `/` (the landing).

## Test Cases (manual)

### TC-01: mounts as the hero
Open `/`. **Expected**: below the headline, an app-window demo (browser chrome + Triage Studio UI)
replaces the old static mockup. Exactly one demo instance.

### TC-02: play-on-view / pause-off-view
Scroll the demo into view. **Expected**: it starts (inbox counter "47 → 0 · all sorted", then the
email/trace/compare/studio acts, then the CTA, looping). Scroll it fully out of view → it pauses
(no CPU churn); scroll back → it resumes/continues.

### TC-03: light + dark
Toggle the landing theme. **Expected**: the demo flips with the page (tokens inherit through the
shadow boundary) — teal accents and category colors correct in both.

### TC-04: reduced-motion / mobile
With `prefers-reduced-motion: reduce`, or on a phone (<640px): **Expected**: no autoplay; a poster
with "▶ Watch the demo" that starts it on tap.

### TC-05: controls
Pause/resume and restart (↺) buttons on the window work.

### TC-06: the acts read correctly
Inbox auto-triage → one email classified (`refunds`, 95%) + drafted reply → "Ask the trace" chat
answers about the trace → Sync 1.8s vs Streaming TTFT 0.3s → add category `warranty` → CTA
"Your inbox, on autopilot · Start free →".

### TC-07: no leak
Navigate away from `/` and back. **Expected**: still one demo; no runaway timers (the engine parks
off-view).

## Gates

`cd frontend && npx tsc --noEmit && npx eslint . && npx vite build` — green.
(Note: a `createRoot` StrictMode warning may appear in the dev console from HMR buffering; it does
not occur in the production build, which runs the effect once.)
