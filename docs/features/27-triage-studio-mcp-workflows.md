# Triage Studio F4 — MCP server + Claude Code workflows

## What it does

Exposes Triage Studio as an **MCP server** (`triage-studio`) with typed tools so any
Claude client (Desktop, Code, the SDK) can classify emails and operate the Studio, plus
**Claude Code slash commands** that script operator flows. Materializes cert domain 4
(Tool Design & MCP Integration) and domain 2 (Claude Code config & workflows).

The server is a **client of the HTTP API** — it never imports the app or the DB, so RBAC
and business rules stay in FastAPI and the same server works against a deployed instance.

## How it works

```
Claude client ──stdio──▶ triage-studio MCP server ──httpx──▶ FastAPI (/triage, /workspaces/*)
                              (typed tools)          (X-API-Key / Bearer from env)
```

- **Transport:** stdio (`triage-mcp` console script → `server.run("stdio")`).
- **Tools** (typed signatures → auto JSON schema): `classify_email`, `list_categories`,
  `create_category`, `add_example`, `preview_prompt`, `list_prompt_versions`.
- **`ApiClient`:** a thin httpx wrapper that injects the right auth per endpoint and
  **translates errors** — a 4xx/5xx becomes an actionable `ApiError`
  (e.g. `API returned 403: Scope required: triage:configure`), a network failure becomes
  `Cannot reach the Triage API: …`. That is the domain-4 discipline: the agent gets a
  message it can act on, not a stack trace.
- **Config from env only** (never tool args or the prompt): `TRIAGE_API_URL`,
  `TRIAGE_API_KEY` (for `/triage`), `TRIAGE_SESSION_TOKEN` + `TRIAGE_WORKSPACE_ID` (Studio).
  Missing creds yield a clear "set TRIAGE_… " error instead of an obscure failure.

## Files involved

| File | Role |
|---|---|
| `pyproject.toml` | optional dep `mcp>=2.0` (`[mcp]` extra) + dev group; `triage-mcp` console script |
| `email_triage/mcp_server.py` | `MCPServer` + 6 typed tools + `ApiClient` (auth + error translation) |
| `.claude/commands/new-category.md` | slash command: scaffold a category (+ preview) |
| `.claude/commands/add-example.md` | slash command: add a few-shot example |
| `.claude/commands/preview-prompt.md` | slash command: compile & show the draft prompt |
| `.claude/commands/eval-prompt.md` | slash command: run `make eval-quick` before publishing |
| `tests/test_mcp_server.py` | `ApiClient` vs httpx MockTransport + tool registration |

## Running it

```bash
uv sync --extra mcp   # install the MCP SDK
export TRIAGE_API_URL=http://localhost:8000
export TRIAGE_API_KEY=<workspace api key>          # for classify_email
export TRIAGE_SESSION_TOKEN=<bearer jwt>           # for the Studio tools
export TRIAGE_WORKSPACE_ID=<tid>
uv run triage-mcp
```

Register it in a client's MCP config as command `uv run triage-mcp` (cwd = repo).

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| MCP = HTTP client of the API | Import services/DB into the server | Decouple; works against prod; no duplicated RBAC/rules |
| `mcp` optional (`[mcp]`) + dev group | Core runtime dep | Don't bloat the API container with the client SDK; keep tests/typecheck green |
| stdio transport | HTTP/SSE MCP | What Claude Desktop/Code consume locally; least surface |
| Credentials from env | Tool args / prompt | Never expose secrets to the model; same model as `.env` |
| `ApiClient` translates errors | Propagate httpx exceptions | Actionable errors for the agent (domain 4) |

## Gotchas / Edge cases

- **SDK is `mcp>=2.0`** — the high-level class is `mcp.server.mcpserver.MCPServer` (the
  renamed FastMCP), and `Tool.input_schema` is snake_case in this major.
- **Rate limit:** `/triage` is 20/min per IP; the MCP inherits it.
- **Token expiry:** Studio tools return a mapped 401 when the Bearer JWT expires; refresh
  the token in the env (auto-refresh is out of scope).
- **Tests are network-free:** httpx `MockTransport`; the real stdio server is not launched.

## Testing

📋 [Testing guide](../testing/27-triage-studio-mcp-workflows_testing.md)
