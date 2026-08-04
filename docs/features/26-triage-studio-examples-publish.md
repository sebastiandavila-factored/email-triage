# Triage Studio F3 — Few-shot examples + template overrides + publish/eval-gate

## What it does

Completes the prompt self-service. On top of the per-workspace taxonomy (F1) and the
XML compiler (F2), owners/admins can now: attach **few-shot examples** to each
category, edit the prompt's **template blocks** (role/task/guardrails/tone), and run a
**draft → preview → publish** flow that freezes an immutable, versioned prompt behind
an **eval-gate**, with **rollback** to any prior version.

Governance model — **"published wins if present"**: a workspace with no published
version keeps F2's live-compile behavior (edits apply immediately); once it publishes,
`/triage` serves the frozen version and further edits require another publish. This
preserves zero-config for casual users and gives governance to teams that want it.

This is phase F3 of [proposal 001 — Triage Studio](../proposals/001-triage-studio.md).

## How it works

```
Examples   → triage_examples (per category), injected into <examples> of the prompt
Template   → prompt_templates (one mutable draft per tenant; NULL block ⇒ compiler default)
Preview    → compile_draft(active categories + active examples + overrides) → XML, no write
Publish    → compile draft → [eval-gate] → freeze immutable prompt_versions row (is_active)
Rollback   → activate a prior version (deactivate the rest)

/triage resolution (deps.get_triage_service):
  active PromptVersion?  yes → serve compiled_prompt + allowed_slugs (cache key "v{n}")
                         no  → live-compile the draft (cache key = sha1(prompt))
```

- **Compiler (extended):** `compile_system_prompt(categories, examples=None,
  overrides=None)`. With neither, it's the plain-prose base prompt. Few-shot examples are
  wrapped in `<examples>` after the `Categories:` list (per Plan 29 — tags only for
  examples and the email); `tone` renders as a `- Tone: …` guideline line.
- **Eval-gate (injectable):** `PromptStudioService(gate=...)`. The gate maps a compiled
  prompt → `GateMetrics(accuracy, macro_f1)`; publish blocks with **409** if metrics
  regress below the active version's stored baseline by more than `GATE_MARGIN` (0.02).
  Metrics are stored on `prompt_versions` as the next baseline. Tests inject a fake
  gate, so no LLM is called; the router publishes with `gate=None` (versioned publish,
  gate wiring is a config point).
- **Cache invalidation:** publish/rollback call `clear_triage_service_cache()`.

## Files involved

| File | Role |
|---|---|
| `email_triage/db/models.py` | `TriageExample`, `PromptTemplate`, `PromptVersion` |
| `alembic/versions/0005_examples_prompt_versions.py` | 3 tables |
| `email_triage/db/repos/examples.py` | `ExampleRepo` (+ `active_specs` for the compiler) |
| `email_triage/db/repos/prompts.py` | `PromptTemplateRepo`, `PromptVersionRepo` |
| `email_triage/services/prompt_compiler.py` | `ExampleSpec`, `TemplateOverrides`; `<examples>`/`<style>` |
| `email_triage/services/prompt_studio.py` | `PromptStudioService` — rules, compile_draft, publish (gate), rollback |
| `email_triage/auth/scopes.py` | `prompt:publish` (owner only) |
| `email_triage/deps.py` | `get_triage_service` resolves active version; `PublishPromptDep` |
| `email_triage/routers/prompt_studio.py` | examples + draft + preview + versions + publish + activate |
| `tests/test_prompt_studio.py` | compiler few-shot, service rules, gate, RBAC |

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| "Published wins if present"; else F2 live | Everything always via publish | Don't break zero-config for tenants that never use the Studio |
| `prompt_versions` immutable + `is_active` | Edit the version in place | Trivial audit + rollback (just activate another row) |
| Eval-gate injectable, blocks with 409 | Hard-wire an LLM eval in the request | Hermetic tests; the LLM/dataset is a config concern, not a rule |
| `NULL block ⇒ compiler default` | Copy the full template into the draft | Less drift; defaults evolve with the code |
| Router publishes with `gate=None` | Run a real eval on every publish | Publish stays fast/versioned; a real gate is opt-in (per-tenant datasets are future work) |
| Cache key = version no. / prompt hash | Track `updated_at` | Publish → `v{n}`; live edits → new hash; both invalidate for free |

## Gotchas / Edge cases

- **Semantics change vs F2:** once a tenant publishes, category/example/template edits no
  longer hit `/triage` until the next publish. See [F2 feature doc](25-triage-studio-prompt-compiler.md).
- **Publish needs ≥1 active category** (409 otherwise) — a prompt of only `unknown` is useless.
- **`prompt:publish` is owner-only;** `admin` has `triage:configure` (examples, draft,
  preview) but cannot publish/rollback.
- **Real per-tenant eval datasets don't exist yet** — the gate framework is wired and
  tested, but production wiring of a real classification gate (and per-tenant labeled
  data) is a documented future extension.

## Testing

📋 [Testing guide](../testing/26-triage-studio-examples-publish_testing.md)
