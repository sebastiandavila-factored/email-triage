# 39. Few-shot negatives render as real counter-examples

**Status:** ✅ delivered (compilador ramifica por `kind`; test de contra-ejemplo; docs). `make check` verde.
**Estimate:** ~1 hr
**Depends on:** Plan 26 (examples), Plan 29 (prompt simplification).

## Intent

An example has a `kind` — `positive` or `negative` — stored in `triage_examples` and
chosen in the Studio UI. Plan 29 dropped the `kind="…"` attribute when it moved examples
to a cleaner shape, so **a negative example now renders identically to a positive one**:
both emit `category: {slug}`, which tells the model *"this email IS {slug}"* — the exact
opposite of what a negative is meant to teach.

This makes negatives actively harmful (they mislabel), and wastes a genuinely useful
signal: a legit bank email filed as a **negative under `estafa`** should teach *"do NOT
classify this as estafa"* — the cheapest way to kill a specific false positive.

## Fix

Branch `_render_example` on `spec.kind` (compiler-only; the DB, API and UI already carry
`kind`):

- **positive** (unchanged): the correct label, plus optional reply.
  ```
  <example>
  <email>
  Subject: …

  …body…
  </email>
  category: estafa
  reply: …            # only if present
  </example>
  ```
- **negative** (new): a counter-example line, no reply (a counter-example asserts what it
  is *not*, so a suggested reply is meaningless).
  ```
  <example>
  <email>
  Subject: …

  …body…
  </email>
  This email is NOT "estafa" — do not classify it there.
  ```

The `<examples>` intro line becomes neutral ("Here are examples to guide your
classification:") so it fits both kinds. Positives still teach what a category looks like;
negatives sharpen its edge. A negative doesn't carry the true label — it doesn't need to;
paired with the positives it reduces over-triggering on that one category.

## Concrete changes

| Archivo | Cambio |
|---|---|
| `email_triage/services/prompt_compiler.py` | `_render_example` branches on `kind`; neutral `<examples>` intro |
| `tests/test_prompt_studio.py` | keep the positive assertion; add a negative-renders-as-counter-example test |
| `docs/features/26-triage-studio-examples-publish.md` | document positive vs negative rendering |
| `docs/exec-plans/29-*.md` | note this supersedes the "negatives render like positives" caveat |

**Not touched:** DB/model (`kind` already exists), API, Studio UI (already has the
positive/negative selector), the landing (its examples section is illustrative and stays).

## Design decisions

| Decision | Alternative | Reason |
|---|---|---|
| Negative = "this email is NOT {slug}" | Add a "true category" field to negatives | No schema/UI change; a counter-example only needs to say what it isn't |
| Drop the reply for negatives | Keep it | A reply implies a chosen category, which a negative deliberately withholds |
| Neutral `<examples>` intro | Two separate blocks (examples / counter-examples) | One block keeps the prompt compact; each line self-describes |

## Risks / Open questions

- **Published versions are snapshots** — already-published prompts keep their old text; only
  new compiles/publishes get counter-examples. No migration.
- **A negative without positives** for the same category still helps (says "not X"), but the
  pairing is where it shines — documented as guidance, not enforced.

## Done when

- [x] A `kind="negative"` example renders a `This email is NOT "{slug}"` line and no `category: {slug}` / `reply:`
- [x] Positives unchanged (`category: {slug}` + optional `reply:`)
- [x] Tests cover both (`test_negative_example_renders_as_counter_example`); `make check` green (ruff + pyright 0 + 229 tests)
- [x] `docs/features/26-*` documents the two kinds; plan 29 caveat updated
