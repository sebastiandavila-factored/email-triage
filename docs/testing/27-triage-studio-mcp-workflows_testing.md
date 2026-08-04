# Testing: Triage Studio F4 — MCP server + workflows

## Prerequisites

- `uv sync --extra mcp` (or the dev group, which includes `mcp`).
- Automated: `uv run pytest tests/test_mcp_server.py -v` (no network — httpx MockTransport).
- Manual E2E: a running API (`uv run uvicorn email_triage.main:app`), a workspace API key,
  a Bearer session token, and the workspace id.

## Test Cases

### TC-01: Tools are registered and typed
**Action**: `test_server_exposes_typed_tools`.
**Expected**: the 6 tools exist; `classify_email` input schema is exactly
`{subject, sender, body}` (derived from the typed signature).

### TC-02: Correct auth per endpoint
**Action**: `test_classify_uses_api_key_header`, `test_list_categories_uses_bearer_and_workspace`.
**Expected**: `/triage` carries `X-API-Key`; Studio calls carry `Authorization: Bearer …`
and hit `/workspaces/{tid}/…`.

### TC-03: API errors become actionable messages
**Action**: `test_http_error_is_translated_to_actionable_message`, `test_network_error_is_translated`.
**Expected**: a 403 → `ApiError` containing `403` and the detail; a connection failure →
`ApiError` containing `Cannot reach`.

### TC-04: Missing credentials are actionable
**Action**: `test_missing_api_key_is_actionable` / `_token_` / `_workspace_`.
**Expected**: `ApiError` naming the exact env var to set (`TRIAGE_API_KEY`,
`TRIAGE_SESSION_TOKEN`, `TRIAGE_WORKSPACE_ID`).

### TC-05: Manual — stdio server end-to-end
**Action**: Configure a client (or the MCP inspector) to launch `uv run triage-mcp` with the
env vars set; call `list_categories`, then `classify_email`.
**Expected**: `list_tools` shows the 6 tools; `classify_email` returns
`{category, draft_reply, confidence}` from the live API.

### TC-06: Slash commands
**Action**: In Claude Code, run `/preview-prompt`, `/new-category`, `/add-example`, `/eval-prompt`.
**Expected**: each drives the corresponding MCP tool (or documented HTTP fallback) and
surfaces API errors verbatim without blind retries.

## Edge Cases

| Scenario | Expected |
|---|---|
| `classify_email` without `TRIAGE_API_KEY` | Actionable ApiError, no request sent |
| Studio tool without `TRIAGE_SESSION_TOKEN` | Actionable ApiError |
| Expired Bearer token | Mapped 401 asking to refresh the token |
| `/triage` over 20/min | Mapped 429 from the API |

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| `ModuleNotFoundError: mcp` | Extra not installed | `uv sync --extra mcp` |
| `create_category` → 403 | Token lacks `triage:configure` | Use an owner/admin token |
| Server starts but no tools | Wrong SDK major | Requires `mcp>=2.0` (`MCPServer`, `Tool.input_schema`) |
