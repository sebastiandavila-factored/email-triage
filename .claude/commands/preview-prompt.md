---
description: Compile and show the workspace's current draft prompt (Triage Studio)
---

Show the compiled XML system prompt for the current workspace's draft, without publishing.

Steps:
1. Call the `preview_prompt` MCP tool (server `triage-studio`).
2. Render the returned `prompt` in a fenced ```xml block and list `allowed_slugs`.
3. Point out the structural tags present (`<role>`, `<task>`, `<categories>`, optional
   `<examples>`/`<style>`, `<output_format>`, `<guardrails>`) and note whether the tenant
   has a published version (in which case `/triage` serves that, not this draft — run
   `list_prompt_versions` to check).

Do not publish. Publishing is a separate, owner-only action.
