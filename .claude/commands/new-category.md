---
description: Scaffold a new triage category for a workspace (Triage Studio)
argument-hint: <slug> "<name>" "<description>"
---

Create a new triage category in the Triage Studio backend.

Arguments: `$ARGUMENTS` — expected as `<slug> "<name>" "<description>"`.
- `slug`: lowercase `[a-z0-9_]`, stable and immutable (it is the classification value).
- `name`: human-readable display label.
- `description`: one line; it goes verbatim into the `<category><description>` of the prompt.

Steps:
1. Confirm the workspace id (from `TRIAGE_WORKSPACE_ID` or ask). Do not invent it.
2. Call the `create_category` MCP tool (server `triage-studio`) with the parsed args.
   If the MCP server is not connected, fall back to:
   `POST {TRIAGE_API_URL}/workspaces/{tid}/categories` with the Bearer session token and
   body `{"slug","name","description"}`.
3. On success, run `preview_prompt` and show the `<categories>` block so the user sees the
   category is now in the compiled prompt.
4. Suggest adding at least one few-shot example with `/add-example`.

Report the created category (id, slug) and any API error verbatim (e.g. 409 duplicate slug,
422 reserved/invalid slug, 403 missing `triage:configure`). Never retry a 4xx blindly.
