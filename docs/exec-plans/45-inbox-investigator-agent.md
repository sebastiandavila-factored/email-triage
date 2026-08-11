# 45. Agente investigador de bandeja — preguntas NL abiertas (plan a futuro)

**Status:** 📋 proposed — **plan a futuro** (backlog; no priorizado)
**Estimate:** ~7 hrs (estimación gruesa)
**Depends on:** Plan 37/40 (sync + filtros), Plan 25 (Groq/pydantic-ai). Comparte el patrón agéntico de Plan 43/44.

## Intent

Un agente que responde **preguntas en lenguaje natural sobre la bandeja**, del estilo:
"¿hay algún cliente enojado que mencione un reembolso y no haya sido respondido?" o "resumime los
correos de envíos atrasados de esta semana". El agente decide dinámicamente qué buscar, qué correos
abrir y cómo cruzarlos → loop y tool-calls **variables según la pregunta**.

Es un caso lindo y genuinamente agéntico, pero **queda documentado para más adelante**: el ejemplo
del taller de telemetría ya lo cubren Plan 43 (diagnóstico) y Plan 44 (tuning), que además están
más atados al norte del producto (config de triage por-workspace). Este plan existe para retomarlo
sin re-derivar el diseño.

## Boceto de diseño

- **Agente** pydantic-ai (Groq, en-stack) con tools read-only ligadas al `tenant_id` del contexto:
  - `search_inbox(unread_only, days, query)` → reusa la sync de Plan 37/40 y filtra.
  - `get_email_detail(message_id)` → cuerpo/headers de un correo puntual.
  - (opc.) `get_thread(message_id)` → hilo, si se agrega soporte.
- **Salida** estructurada `InboxAnswer` (respuesta + correos citados como evidencia).
- **Endpoint** `POST /inbox/ask` (scope `triage:read`/`triage:write`) → `InboxAnswer`.
- **Loop ReAct** real: buscar → leer detalles → cruzar → responder; nº de pasos según la pregunta.

## Por qué es genuinamente agéntico

El pipeline **no** se conoce de antemano: una pregunta simple resuelve en una búsqueda; una compleja
requiere varias búsquedas + lecturas + comparaciones. Ese es exactamente el criterio para usar un
agente (no un workflow), y produce las 6 métricas de forma natural — igual que Plan 43/44.

## Consideraciones (a resolver cuando se priorice)

- **Privacidad:** los correos son **efímeros** (no se persisten cuerpos, decisión del modelo
  actual). El agente los lee en vuelo; nada de contenido a spans/logs (respetar el scrubbing).
- **Aislamiento multi-tenant:** toda tool fija `tenant_id` del contexto; nunca del modelo.
- **Coste/latencia:** acotar con `usage_limits` y con los filtros de Plan 40.
- **Alcance de la búsqueda:** el `search_inbox` opera sobre la ventana de la sync, no sobre todo el
  histórico de Gmail (que no se persiste).
- **Solapamiento con el reporte de voz (Plan 41):** el investigador es *pregunta→respuesta abierta*;
  el reporte de voz es un *pipeline fijo*. Son features distintas; no fusionar.

## Done when (cuando se retome)

- [ ] `POST /inbox/ask {question, filtros}` devuelve un `InboxAnswer` con correos citados
- [ ] El agente decide dinámicamente búsquedas/lecturas (loop de nº variable)
- [ ] Read-only; no persiste cuerpos; respeta scrubbing y aislamiento por tenant
- [ ] Ningún test toca red real (sync + Groq mockeados) — `CLAUDE.md`
- [ ] `make check` verde
