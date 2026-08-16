# 46. Frontend de las features agénticas — reporte de voz, diagnóstico, tuning

**Status:** 📋 proposed
**Estimate:** ~7 hrs (F1 ~2, F2 ~2, F3 ~3)
**Depends on:** Plan 41 (`/reports/voice`), Plan 43 (`/traces/{trace_id}/diagnose`), Plan 44 (`/tune`).
**Alcance:** solo frontend (React SPA). Backends ya implementados (43/44) o planeados en detalle (41).

## Intent

Los tres endpoints nuevos no tienen UI. Este plan los expone en la SPA, cada uno en el lugar donde
el usuario **ya tiene el contexto** que necesitan:

- **Reporte de voz (F1):** en **`/inbox`** — reporta sobre los items ya en pantalla.
- **Diagnóstico (F2):** junto al panel **"Ver traces"** (Dashboard + Inbox), anclado a un `trace_id`.
- **Tuning (F3):** en el **resultado del Dashboard** — el único lugar con el **email completo**
  (subject/sender/body) que `/tune` necesita (el `InboxItem` no trae body, es efímero).

Fases independientes; se pueden mergear por separado. Cada una calca patrones existentes
(`api.ts` + `can(role, scope)` + componentes `ui/kit`).

## Prior reading

- [frontend/src/api.ts](../../frontend/src/api.ts) — helper `request()`, tipos, métodos (`traceChat` como molde).
- [frontend/src/pages/Dashboard.tsx](../../frontend/src/pages/Dashboard.tsx) — resultado de triage + `result.trace_id` + panel "Ver traces" (`can(role,'traces:read')`, línea ~122). Tiene el email tipeado por el usuario.
- [frontend/src/pages/Inbox.tsx](../../frontend/src/pages/Inbox.tsx) — items con `trace_id`, `TraceChat` por item, controles de sync (Plan 40).
- [frontend/src/components/TraceChat.tsx](../../frontend/src/components/TraceChat.tsx) — molde de panel colapsable anclado a `trace_id`.
- [frontend/src/rbac.ts](../../frontend/src/rbac.ts) — `traces:read` = owner/admin; `prompt:publish` = **owner**.

## Contratos de API (nuevos en `api.ts`)

```ts
// tipos espejo de los schemas backend
export interface VoiceReport { script: VoiceScript; headline: string; by_category: CategoryCount[]; total: number; audio_url: string | null }
export interface TraceDiagnosis { root_cause: string; evidence: EvidenceSpan[]; confidence: number; suggested_fix_kind: string; target_slug: string | null; rationale: string }
export interface TuningProposal { diagnosis: TraceDiagnosis | null; changes: string[]; score_before: EvalScore | null; score_after: EvalScore | null; gate_passed: boolean; cycles: number; recommendation: string }

api.voiceReport(token, items): POST /reports/voice   { items }
api.diagnoseTrace(token, tid, traceId): POST /workspaces/{tid}/traces/{traceId}/diagnose
api.tune(token, tid, { trace_id, email, expected_category }): POST /workspaces/{tid}/tune
```

Todos vía el `request()` existente (Bearer + JSON + manejo 401/422/…).

---

## F1 — Reporte de voz (en `/inbox`) — Plan 41

**Ubicación:** botón **"Generar reporte de voz"** en la barra de acciones del Inbox (junto a "Fetch
emails"), habilitado cuando hay `items`. Al click → `api.voiceReport(token, items)` → panel con el
guion.

**UI del guion:** un `Card` con `headline`, un chip por `by_category` (categoría + count), y el
`VoiceScript` renderizado (opening → sections[heading/body] → closing). Botón **"Copiar guion"**
(texto plano concatenado) — reusa el patrón de copiar draft que ya existe en Inbox.

**Estados:** loading ("Generando…"), vacío (si `total===0`, mostrar el "sin novedades" del guion),
error (banner). Sin gating extra (cualquier miembro con acceso al inbox).

**Cambios:** `api.ts` (`voiceReport` + tipos), `Inbox.tsx` (estado `report`/`generating`, botón,
panel). Opcional: extraer `VoiceScriptView` a `components/`.

---

## F2 — Diagnóstico (junto a "Ver traces") — Plan 43

**Ubicación:** donde hoy está el panel "Ver traces" (Dashboard `result` e Inbox item), agregar un
botón **"Diagnosticar"** (mismo gating `can(role,'traces:read')` + `trace_id`). Al click →
`api.diagnoseTrace(token, tid, traceId)` → tarjeta de veredicto.

**UI del veredicto (`TraceDiagnosisView`, nuevo componente):** `root_cause`, un `Tag` con
`suggested_fix_kind` (+ `target_slug` si hay), una barra/valor de `confidence`, `rationale`, y la
lista de `evidence` (span_name · duración · nota) colapsable.

**Estados:** loading, 404 ("traza no encontrada"), 422 (id inválido), 503 ("diagnóstico no
configurado"). Reusa el manejo de `ApiError` del `TraceChat`.

**Cambios:** `api.ts` (`diagnoseTrace` + `TraceDiagnosis`/`EvidenceSpan`), nuevo
`components/TraceDiagnosisView.tsx`, y montarlo en Dashboard + Inbox junto a `TraceChat` (misma
condición de gating).

---

## F3 — Tuning copilot (en el resultado del Dashboard) — Plan 44

**Por qué solo Dashboard:** `/tune` necesita `email` (subject/sender/body) + `expected_category` +
`trace_id`. El Dashboard tiene el **email completo** (lo tipeó el usuario) y `result.trace_id`. El
Inbox **no** tiene el body → no se ofrece tuning ahí.

**Gating:** `can(role,'prompt:publish')` → **solo owner** (coincide con que el publish real es
humano y también owner).

**Flujo:** en el resultado, un control **"¿Mal clasificado? Sugerir mejora"** →
1. selector de **categoría esperada** (de la lista de categorías del workspace — usar el endpoint de
   categorías que ya consume el Studio; o pedirla si no está cargada).
2. botón **"Sugerir mejora"** → `api.tune(token, tid, { trace_id: result.trace_id, email: { subject, sender, body }, expected_category })`.
3. panel **`TuningProposalView`**: el diagnóstico (reusa `TraceDiagnosisView` de F2), la lista de
   `changes`, `score_before → score_after` (target_fixed / regressions), un badge `gate_passed`, y la
   `recommendation`. **CTA claro:** "Los cambios están en el **borrador**; revisá y **publicá** en
   Studio" (link a `/studio`) — la UI **no publica** (el backend tampoco).

**Estados:** loading (puede tardar — varios ciclos), 403/503, y el caso `gate_passed=false` (mostrar
que no se logró sin regresiones y sugerir revisar en Studio).

**Cambios:** `api.ts` (`tune` + `TuningProposal`/`EvalScore`), `components/TuningProposalView.tsx`
(reusa `TraceDiagnosisView`), y el bloque en `Dashboard.tsx` (gating owner + selector de categoría +
panel). Reusa la carga de categorías del Studio.

---

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Reporte de voz sobre los `items` en pantalla | Botón que re-sincroniza | Coincide con Plan 41 (endpoint recibe items); instantáneo, sin re-triage |
| Tuning solo en Dashboard | También en Inbox | El Inbox no tiene el body del correo (efímero); `/tune` lo necesita |
| Diagnóstico junto a "Ver traces" | Página nueva | El `trace_id` y el gating ya viven ahí; mínimo ruido |
| `TraceDiagnosisView` reusado por F2 y F3 | Duplicar el render | El tuning muestra el mismo diagnóstico |
| La UI enlaza a Studio para publicar | Botón "Publicar" en el panel de tuning | Publish es irreversible y humano (Plan 26/44); la UI no debe publicar |
| Gating por `can(role, scope)` | Chequear en el server solamente | Consistencia con el resto de la SPA; evita mostrar acciones sin permiso |

## Risks / Open questions

- **Latencia del tuning:** el loop puede tardar (varios ciclos + evals). Mostrar progreso y no
  bloquear la UI; considerar un aviso "esto puede tardar unos segundos".
- **Categoría esperada:** el selector necesita la lista de categorías del workspace; reusar la carga
  del Studio o cachearla en el Dashboard.
- **Verificación:** al ser flujos autenticados con Groq/Logfire reales, el pase visual e2e es humano;
  los gates de frontend (tsc+eslint+build) + un smoke con datos mockeados es lo automatizable.
- **audio_url:** F1 ignora `audio_url` (siempre null en v1); dejar el hueco para el TTS futuro.

## Execution order

- **F1** (Plan 41 mergeado): `api.voiceReport` + tipos → botón + `VoiceScriptView` en Inbox → gates.
- **F2** (Plan 43, ya en backend): `api.diagnoseTrace` + tipos → `TraceDiagnosisView` → montar en Dashboard+Inbox → gates.
- **F3** (Plan 44, ya en backend): `api.tune` + tipos → selector de categoría + `TuningProposalView` en Dashboard → gates.

## Done when

- [ ] F1: "Generar reporte de voz" en `/inbox` muestra `headline` + conteos + guion, con "Copiar"
- [ ] F2: "Diagnosticar" junto a "Ver traces" (Dashboard+Inbox) muestra `TraceDiagnosis`, gated `traces:read`
- [ ] F3: "Sugerir mejora" en el resultado del Dashboard (solo owner) muestra `TuningProposal` y enlaza a Studio para publicar; **no publica**
- [ ] Manejo de estados: loading / 403 / 404 / 422 / 503 en cada flujo
- [ ] Gates de frontend verdes (tsc + eslint + vite build)
- [ ] Pase visual autenticado (humano) de los tres flujos
