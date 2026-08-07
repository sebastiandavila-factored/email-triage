# 35. Live product demo on the landing (hero)

**Status:** 🚧 implemented (pending human review/merge)
**Estimate:** ~5 hrs
**Depends on:** Plan 30 (landing as SPA root), Plan 34 (shared design tokens / theme).
**Relacionado:** el demo animado ya existe como Artifact standalone (cold-open inbox → héroe con chat de
traces sobre el MCP → montaje → CTA). Este plan lo **porta a la landing React**, hecho bien.

## Intent

La landing hoy *describe* las features en secciones estáticas. El demo animado las *muestra
funcionando* — y enseña el diferenciador (debug del trace vía MCP) que el texto no transmite. Es el
activo de mayor conversión que tenemos. Este plan lo integra como **pieza central del hero**, con
control del usuario, sin castigar performance/mobile/accesibilidad.

**No** se usa un iframe del Artifact (es una URL privada de claude.ai, no un asset de producción): se
**porta el demo a un componente React** que reusa los tokens globales (`theme.css`), así light/dark
funciona solo.

## Prior reading

- Demo actual (fuente): el HTML del Artifact — motor de animación (cursor, tipeo, escenas, loop) +
  markup de las pantallas (inbox, dashboard, compare, studio, endcard).
- `frontend/src/pages/Landing.tsx` — monta `LANDING_BODY` (string) con `dangerouslySetInnerHTML`,
  tiene un `ref` + `useEffect` (scroll-reveal, theme toggle, links).
- `frontend/src/pages/landingBody.ts` — el HTML del hero (`.hero` con la card-mockup "Inbound email").
- `frontend/src/theme.css` + `index.css` — tokens/utilidades ya compartidos (Plan 34).

## Scope

**Incluido:**
- `frontend/src/components/DemoReel.tsx` (**nuevo**): componente self-contained — markup de las
  escenas + el **motor de animación portado a un `useEffect`** con **cancelación/cleanup** (clear de
  timers al desmontar/pausar). CSS scopeado bajo `.ts-demo` reusando los tokens globales.
- **Integración en el hero** de la landing: reemplaza la card-mockup estática por el demo (o va justo
  bajo el headline). Montaje vía **React portal** en un placeholder `#demo-mount` insertado en
  `landingBody.ts`, para no reescribir todo el string.
- **Performance/a11y (obligatorio):**
  - **Lazy + on-view:** el motor arranca solo cuando el demo entra en viewport (IntersectionObserver)
    y **pausa cuando sale** — nada corre arriba del fold sin verse.
  - **`prefers-reduced-motion`:** no autoplay; primer frame estático (cold-open "0 · all sorted") +
    botón "▶ Ver demo".
  - Control **play/pause + restart** visible.
- **Mobile fallback (<~640px):** la ventana de app 16:9 queda ilegible en teléfono → mostrar un
  **póster estático** (frame del cold-open) + "▶ Ver demo" que lo reproduce (o versión reducida).

**Fuera de scope:**
- Rehacer las secciones existentes de la landing (quedan como el "deep dive" debajo del demo).
- Grabar un MP4 / hosting de video externo.
- Cambios de backend.

## Concrete changes

| Archivo | Cambio |
|---|---|
| `frontend/src/components/DemoReel.tsx` | **nuevo** — escenas + motor (useEffect con cancel) + CSS `.ts-demo` |
| `frontend/src/pages/landingBody.ts` | insertar `<div id="demo-mount"></div>` en el hero; quitar/reducir la card-mockup estática (evita redundancia) |
| `frontend/src/pages/Landing.tsx` | `createPortal(<DemoReel/>, #demo-mount)`; IntersectionObserver para play/pause on-view |
| (opcional) `frontend/src/components/DemoReel.css` | si se prefiere CSS aparte al inline |
| `docs/features/35-*`, `docs/testing/35-*` | docs |

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Portar a componente React | iframe del Artifact | El Artifact es URL privada; un iframe no es asset de producción y no controla perf/CSP |
| Demo como héroe (reemplaza el mockup estático) | Demo además de todo | El mockup estático le roba el lugar al mejor comercial; sumarlo encima duplica las secciones |
| Play on-view + pause off-view (IntersectionObserver) | Autoplay eterno | No quemar CPU/batería arriba del fold; menos distracción |
| Reduced-motion → póster + play | Ignorar la preferencia | Accesibilidad; movimiento continuo necesita opt-in |
| Reusar tokens globales, scope `.ts-demo` | Copiar tokens al componente | Una sola fuente (Plan 34); light/dark gratis; sin fugas de CSS |
| Portal a un placeholder | Reescribir `landingBody` a JSX | Menor riesgo; mantiene el string existente casi intacto |

## Risks / Open questions

- **Cleanup del motor:** el loop actual corre para siempre con `setTimeout`. En React hay que
  garantizar cancelación (token + clear de timers) al desmontar/pausar, o hay leaks/estado zombie.
- **Mobile:** decidir póster estático vs. versión vertical simplificada. v1: póster + play.
- **Hero teaser vs demo completo:** alternativa a evaluar — en el hero solo el cold-open de 4s como
  teaser y el demo completo más abajo. Empezar con el demo completo como héroe; medir.
- **Peso del bundle:** el markup del demo suma JS/CSS; mitigar con lazy-mount (no montar hasta cerca
  del viewport).
- **Deploy:** frontend en Vercel (auto en push); sin cambios de backend.

## Execution order

1. `DemoReel.tsx`: portar markup + motor a `useEffect` con cancel/cleanup; CSS `.ts-demo`. (verificar aislado)
2. Placeholder en `landingBody.ts` + portal en `Landing.tsx`.
3. IntersectionObserver (play on-view / pause off-view) + control play/pause/restart.
4. Reduced-motion (póster + play) + fallback mobile.
5. Gates + walkthrough visual (desktop/mobile, claro/oscuro, reduced-motion).

## Done when

- [x] El demo se ve como héroe de la landing (`DemoReel` montado vía `createRoot` en `#demo-mount`), reproduce al entrar en viewport y **pausa al salir** (IntersectionObserver)
- [x] Respeta `prefers-reduced-motion` (póster + play) y tiene control play/pause/restart
- [x] Mobile (<640px): póster + "Watch the demo" en vez de autoplay de una ventana diminuta
- [x] Sin leaks de CPU: el motor **pausa** (park) cuando el host sale de vista; cleanup del observer al desmontar
- [x] `tsc --noEmit` + `eslint` + `vite build` verdes
- [x] `docs/features/35-*` y `docs/testing/35-*`
- [ ] Humano validó en desktop y mobile, claro y oscuro (recorrido completo de los actos en la landing)

> **Notas de implementación:** el demo va en **Shadow DOM** (aislamiento total de CSS; los tokens de
> `:root`/`theme.css` heredan hacia adentro, así claro/oscuro funciona solo). Se monta con `createRoot`
> propio en `#demo-mount` (no `createPortal`, que se rompe dentro de `dangerouslySetInnerHTML`), con
> guard en el nodo contra el double-invoke de StrictMode. Se reemplazó la card-mockup estática del hero.
> Verificado: monta (1 host), corre al entrar en vista, claro y oscuro. Follow-up posible: lazy-load del
> código del `DemoReel` (hoy suma ~4KB gzip al bundle inicial).
