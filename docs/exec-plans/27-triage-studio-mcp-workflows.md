# 27. Triage Studio F4 — MCP server + Claude Code workflows

**Status:** ✅ delivered (MCP server con 6 tools tipadas + `ApiClient` + 4 slash commands + 9 tests + docs). SDK oficial `mcp>=2.0` (`MCPServer`).
**Estimate:** ~5 hrs
**Depends on:** Plan 24 (F1 categories), Plan 25 (F2 `/triage` dynamic), Plan 26 (F3 Studio API).
**Propuesta madre:** [docs/proposals/001-triage-studio.md](../proposals/001-triage-studio.md) — Fase F4.

## Intent

Exponer Triage Studio como un **servidor MCP** para que cualquier cliente Claude
(Claude Desktop, Claude Code, el SDK) opere el producto con **tools tipadas**
—clasificar un email, listar/crear categorías, añadir ejemplos, previsualizar el
prompt— y añadir **slash commands** de Claude Code que automatizan flujos de operador.
Materializa el dominio 4 (Tool Design & MCP Integration) y el dominio 2 (Claude Code
config & workflows) de la certificación.

El servidor MCP es un **cliente del API HTTP existente** (no importa la app ni la DB):
así queda desacoplado, funciona contra una instancia desplegada, y no duplica auth ni
reglas de negocio — el enforcement RBAC/errores ya vive en FastAPI.

## Prior reading

- Propuesta [001](../proposals/001-triage-studio.md) §8 (superficie MCP).
- **MCP — Python SDK / FastMCP**: https://modelcontextprotocol.io — tool schemas, stdio transport.
- **Anthropic — designing tools for agents** (nombres claros, descripciones, errores accionables).
- Endpoints existentes: `/triage` (`X-API-Key`), `/workspaces/{tid}/categories*`, `/workspaces/{tid}/prompt/*` (Bearer).

## Scope

**Incluido:**
- Dependencia `mcp` (SDK oficial) — grupo opcional `[mcp]` en `pyproject` para no cargar
  el runtime del API con ella.
- `email_triage/mcp_server.py`: servidor **FastMCP** sobre **stdio** con tools tipadas
  (tabla abajo). Config por env: `TRIAGE_API_URL`, `TRIAGE_API_KEY` (máquina, para
  `/triage`), `TRIAGE_SESSION_TOKEN` + `TRIAGE_WORKSPACE_ID` (Bearer, para el Studio).
- Un cliente HTTP fino (`_ApiClient`) con httpx, reutilizable y **testeable con mock**.
- Entrypoint de consola `triage-mcp` (en `[project.scripts]`).
- **Slash commands** en `.claude/commands/`: `new-category.md`, `add-example.md`,
  `preview-prompt.md`, `eval-prompt.md`.
- Tests: cada tool con httpx mockeado (sin red); mapeo de errores del API a mensajes MCP.
- Docs `27-*`.

**Fuera de scope:**
- Cambios al API FastAPI (el MCP solo lo consume).
- Transportes HTTP/SSE del MCP (stdio cubre Claude Desktop/Code local).
- OAuth dentro del MCP (credenciales por env; la obtención del token es del usuario).
- Publicar el server en un registry MCP.

## Tools expuestas

| Tool | Args | API que llama | Auth |
|---|---|---|---|
| `classify_email` | subject, sender, body | `POST /triage` | `X-API-Key` |
| `list_categories` | (workspace del env) | `GET /workspaces/{tid}/categories` | Bearer |
| `create_category` | slug, name, description | `POST /workspaces/{tid}/categories` | Bearer |
| `add_example` | category_id, kind, subject, body, expected_reply? | `POST .../categories/{cid}/examples` | Bearer |
| `preview_prompt` | (workspace del env) | `POST .../prompt/preview` | Bearer |
| `list_prompt_versions` | (workspace del env) | `GET .../prompt/versions` | Bearer |

Nombres verbo-objeto, descripciones claras y **errores accionables** (el `_ApiClient`
traduce 4xx/5xx del API a un mensaje que el modelo puede usar, p.ej. "403: falta scope
triage:configure" en vez de un stack trace). Diseño de schema = dominio 4.

## Auth y seguridad

- Las credenciales viven **solo en env** del proceso MCP; nunca en argumentos de tool ni
  en el prompt. El servidor actúa con la identidad configurada (una API key de workspace
  + opcionalmente un token de sesión). Documentar que quien corre el MCP hereda esos
  permisos (mismo modelo que un `.env`).
- Sin credenciales de Studio (Bearer) configuradas, las tools de escritura devuelven un
  error claro ("configura TRIAGE_SESSION_TOKEN") en vez de fallar oscuro.

## Concrete changes

| Archivo | Cambio |
|---|---|
| `pyproject.toml` | dep opcional `mcp` en `[project.optional-dependencies].mcp`; script `triage-mcp` |
| `email_triage/mcp_server.py` | **nuevo** — FastMCP server + tools + `_ApiClient` |
| `.claude/commands/new-category.md` | slash command: crear categoría (+ ejemplo + preview) |
| `.claude/commands/add-example.md` | slash command: añadir few-shot a una categoría |
| `.claude/commands/preview-prompt.md` | slash command: compilar y mostrar el prompt del workspace |
| `.claude/commands/eval-prompt.md` | slash command: correr el eval-gate local sobre un draft |
| `tests/test_mcp_server.py` | tools con httpx mock; error mapping |
| `docs/features/27-*`, `docs/testing/27-*` | docs |
| `README.md` | sección "MCP server" (config + uso) |

## Design decisions

| Decisión | Alternativa | Razón |
|---|---|---|
| MCP = cliente HTTP del API | Importar services/DB en el server | Desacople; funciona contra prod; no duplica RBAC/reglas |
| Dep `mcp` opcional (`[mcp]`) | Dep del runtime principal | No inflar el contenedor del API con el SDK del cliente |
| stdio | HTTP/SSE del MCP | Es lo que consumen Claude Desktop/Code local; menos superficie |
| Credenciales por env | Args de tool / prompt | Nunca exponer secretos al modelo; mismo modelo que `.env` |
| `_ApiClient` traduce errores | Propagar excepciones httpx | Errores accionables para el agente (dominio 4) |

## Risks / Open questions

- **Instalación de `mcp`:** si el SDK no resuelve limpio con `uv`, degradar a un server
  stdio mínimo propio (JSON-RPC) — pero preferir el SDK. Verificar antes de codear.
- **Rate limit de `/triage`** (20/min por IP): el MCP hereda el límite; documentar.
- **Token de sesión caduca:** las tools de Studio devolverán 401; el error mapeado indica
  renovar el token. (Refresh automático fuera de scope.)
- **Tests sin red:** se mockea httpx; no se levanta el server MCP real en CI.

## Execution order

1. Añadir dep `mcp` opcional + verificar import (20 min).
2. `_ApiClient` (httpx) + mapeo de errores + tests (60 min).
3. `mcp_server.py`: FastMCP + tools tipadas cableadas al cliente (75 min).
4. Entrypoint `triage-mcp` + config por env (20 min).
5. Slash commands `.claude/commands/*` (40 min).
6. Tests de tools (mock) + docs `27-*` + README (60 min).
7. `make check` verde.

## Done when

- [x] `triage-mcp` arranca por stdio y `tools/list` devuelve las 6 tools tipadas
- [x] `classify_email` clasifica vía `/triage` con la API key del env (auth verificada en test)
- [x] Las tools de Studio (Bearer) crean categoría / ejemplo y hacen preview del prompt
- [x] Un 4xx del API se traduce a un mensaje accionable (no stack trace)
- [x] Slash commands operativos en `.claude/commands/` (4)
- [x] `make check` verde (ruff + pyright 0 + 179 tests); `docs/features/27-*` y `docs/testing/27-*`

> **Ajuste durante ejecución:** el SDK oficial instaló como **`mcp==2.0`**, que renombró
> `FastMCP` → `mcp.server.mcpserver.MCPServer` y usa `Tool.input_schema` (snake_case). La
> dep se fijó a `mcp>=2.0`. El SDK es cliente-Y-servidor; se usa solo la parte servidor.
