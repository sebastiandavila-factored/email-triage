---
description: Add a few-shot example to a triage category (Triage Studio)
argument-hint: <category_id> [positive|negative]
---

Attach a few-shot example to a category so it is injected into the `<examples>` block of
the compiled prompt.

Arguments: `$ARGUMENTS` — a `category_id` and optionally the kind (`positive` default, or
`negative`).

Steps:
1. If no `category_id` was given, call `list_categories` and ask which one.
2. Ask the user (or infer from context) for the example `subject`, `body`, and an optional
   `expected_reply` that demonstrates the desired tone.
3. Call the `add_example` MCP tool with `{category_id, kind, subject, body, expected_reply?}`.
4. Run `preview_prompt` and show the new `<example kind="...">` so the user can verify it.

Guidance:
- A `negative` example is powerful for edge cases — including a prompt-injection attempt
  labelled as correctly handled reinforces the guardrail.
- Keep examples short and representative; there is a per-category cap (currently 20).

Surface any API error verbatim (404 category not found, 409 example cap reached,
403 missing scope). Do not paste secrets into tool arguments.
