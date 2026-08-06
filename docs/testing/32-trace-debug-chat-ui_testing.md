# Testing: Trace-Debug Chat — UI

## Prerequisites

- Gates de frontend: `cd frontend && npx tsc --noEmit && npx eslint . && npx vite build`.
- Manual: backend con Plan 31 activo (`LOGFIRE_READ_TOKEN` seteado, telemetría fluyendo), una
  cuenta `owner`/`admin` y una `member`, API key del workspace configurada en Settings.

## Test Cases (manual)

### TC-01: el botón solo aparece para owner/admin
**Action**: correr una triage como `owner` y como `member`.
**Expected**: `owner`/`admin` ven "▸ Ver traces" en la card de resultado; `member` no.

### TC-02: sin trace_id no hay botón
**Action**: si por alguna razón la respuesta no trae `trace_id`.
**Expected**: el botón no se renderiza (no rompe la card).

### TC-03: abrir el chat y preguntar
**Action**: pulsar "Ver traces", escribir "¿por qué fue lenta esta triage?".
**Expected**: aparece el turno del usuario, luego "Reading traces…", luego la respuesta del
agente basada en los spans reales. El `trace_id` corto se muestra arriba del hilo.

### TC-04: error de red / backend
**Action**: forzar un fallo (p.ej. backend sin `LOGFIRE_READ_TOKEN` → 503).
**Expected**: se muestra el detalle del error; el turno optimista del usuario se revierte y el
texto vuelve al input para reintentar.

### TC-05: nueva triage resetea el panel
**Action**: con el panel abierto, correr otra triage.
**Expected**: el panel se colapsa y el chat queda anclado al nuevo `trace_id`.

### TC-06: aislamiento (defensa en profundidad)
**Action**: (backend) confirmar que aunque el cliente enviara otro `tid`, el backend usa el de
la sesión; un `trace_id` de otro workspace responde 404 (ver testing Plan 31).
**Expected**: el usuario nunca ve traces de otra organización.

## Gates

`cd frontend && npx tsc --noEmit && npx eslint . && npx vite build` — verde.
