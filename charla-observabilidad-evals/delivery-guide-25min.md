# Delivery guide — 25 min cut

Guion para `presentation-25min-en.html` (30 slides). Charla en **inglés**; coaching en español, líneas entre comillas = lo que decís.

> Objetivo de ritmo: **~23 min de contenido + 2 de preguntas**. Marcadores: min **8** → entrando a Parte 3 · min **18** → entrando a Resultados.

## Reveal (recordatorio)
`→`/`↓` avanzan · **`S`** speaker notes (el guion detallado está en cada slide) · **`F`** fullscreen · **`Esc`** grilla · **`B`** pantalla negra.

## Presupuesto de tiempo (25 min)

| Bloque | Min | Acum |
|---|---|---|
| Apertura + Proyecto | 2.5 | 2.5 |
| Parte 1 — Observability | 3.5 | 6 |
| Parte 2 — Evals fundamentals | 5.5 | 11.5 |
| Parte 3 — Prompt versioning | 4.5 | 16 |
| Parte 4 — Pydantic Evals | 5.5 | 21.5 |
| Resultados + cierre | 2.5 | 24 |
| Q&A | ~1–2 | 25 |

Si vas atrasado, los primeros candidatos a acelerar: *Three graders*, *minimal eval*, *calibration*.

---

## Guion por slide (⭐ = frase que no salteás)

### Apertura (2.5 min)
**Title** (~20s) > ⭐ "We took an LLM agent that already had observability, and pushed it to production-grade prompt versioning and evals — on a real service, `email-triage`. Real code, and one lesson that surprised me."

**Agenda** (~15s) > "Four blocks: observability, evals fundamentals, prompt versioning, evals with the framework. Then results."

**email-triage** (~40s) > "It classifies e-commerce support emails into five categories and drafts a reply. FastAPI, Pydantic AI over Groq, Logfire for observability. The critical path waits 1–3 s on the model — remember that for later."

**Pydantic contract** (~45s) > "Two things: the output is a Pydantic model — validation for free. And the system prompt lives here, hardcoded. Hold that thought — it's what we fix in part three."

### Parte 1 — Observability (3.5 min)
**Part 1 title** (~10s) > "We already had this — turns out it's the substrate for evals too."

**OpenTelemetry** (~60s) > ⭐ "OTEL is to observability what SQL is to databases: an open, vendor-neutral standard. You instrument once and export anywhere. So we instrument against OTEL, not Logfire — Logfire is swappable."
> *(Si te preguntan span vs trace: "a span is one unit of work; a trace is the whole tree of spans for one request, tied by a trace_id.")*

**Logfire** (~45s) > "Pydantic's observability backend. Ergonomic SDK but plain OTEL underneath, Pydantic-aware, and traces are queryable with SQL. The new bits we use today — prompt management and evals — live here."

**Configuration** (~45s) > "Our actual setup: one configure call with tail sampling and PII scrubbing, then one line per layer to auto-instrument FastAPI, Pydantic AI, httpx and system metrics."

**Business metrics** (~40s) > ⭐ "And we don't only measure infra — we histogram the model's own `confidence` in production. That's a quality signal, and it comes back as calibration in part four."

### Parte 2 — Evals fundamentals (5.5 min)
**Part 2 title** (~10s) > "Based on Anthropic's 'Demystifying evals for AI agents'."

**What is an eval** (~40s) > ⭐ "Input, grading logic, measure of success. The analogy: Case + Evaluator is a unit test, Dataset is the suite, Experiment is running pytest. Difference — AI is probabilistic, so scores are graded, not pass/fail."

**Three graders** (~50s) > "Code-based: fast, cheap, brittle. Model-based (an LLM judge): flexible, captures nuance, needs calibration. Human: gold standard, slow. Rule: deterministic when you can, LLM where you must, humans to calibrate."

**Capability vs Regression** ⭐ (~70s) > "Capability asks 'what can it do well' — starts low, your hill to climb. Regression asks 'does it still work' — near 100%, a drop means something broke. We split into 25 regression cases at a 0.95 gate and 22 capability cases."
> ⭐ "Real finding: two `status` cases were consistently predicted as `shipments`. We did NOT lower the threshold — we re-curated them into capability. Because a gate you loosen so it passes is not a gate."

**pass@k vs pass^k** ⭐ (~55s) > "A single run lies. pass-at-k = at least one success in k tries, rises with k. pass-hat-k = all k pass, falls with k. Temperature 0.2 isn't zero — for a customer-facing agent, pass-hat-k is the honest metric."

**The same run, three stories** ⭐ (~55s) — *tu slide fuerte, dejá que lean la tabla*
> ⭐ "Same data, three stories: pass@k says 100% — everything's reachable. Accuracy says 67%. But pass-hat-k says 33% — only one case is reliable every time. Single-run accuracy would have let you relax; pass^k tells the uncomfortable truth."

### Parte 3 — Prompt versioning (4.5 min)
**Part 3 title** (~10s) > "Getting the prompt out of the code without a redeploy."

**The problem** (~40s) > "Every prompt tweak is a commit and a redeploy. No history of what was in prod on Tuesday. Product and support can't touch it. And it's the thing we iterate on most."

**prompt & version** (~50s) > ⭐ "Three concepts: a prompt (name + template), a version (immutable snapshot — v1, v2), and a label like `production` — a movable pointer. The app consumes by label, not by number. Git tags plus a production pointer."
> *(Backup, save≠promote: "you save versions freely on the Prompts page; you promote by moving the label — that decoupling is the governance, and rollback is just moving the label back.")*

**The code** ⭐ (~65s) > ⭐ "Two production surprises. `logfire.var()` is NOT idempotent — I found it live, calling it in a function broke the whole test suite. So it's module-level, once, cached with lru_cache — zero fetch per request. And the `default` is the code prompt, so if Logfire is down we fall back and don't break."

**Applied** (~40s) > ⭐ "Resolved once in the lifespan, code stays the source of truth, governance guard included. The payoff: rolling back a bad prompt is moving a label — no commit, no deploy."

### Parte 4 — Pydantic Evals (5.5 min)
**Part 4 title** (~10s) > "From our custom harness to Pydantic Evals — without losing anything."

**Minimal eval** (~55s) > "A Case with input and expected output, a custom Evaluator — our `is_correct` — a Dataset, and `evaluate_sync` runs the suite. We reused our existing metrics.py untouched."
> *(Backup, data model: "Dataset has Cases, an Experiment runs a Task with Evaluators. Code-first — evals live in the repo, git-versioned.")*

**LLM judge** ⭐ (~55s) > ⭐ "We wrapped our JudgeAgent in a framework Evaluator instead of throwing it away. And we took Anthropic's advice — we gave the judge an 'unknown' verdict, so it abstains instead of inventing. Plus an export for human spot-check: that's the calibration seam."

**Span-based** ⭐ (~45s) > ⭐ "Here it all connects. A span-based evaluator reads the SAME OTEL span tree from part one. Your eval assertions are aligned with production telemetry — you grade HOW the agent got there, not just the answer."

**Calibration** (~40s) > ⭐ "Remember the confidence histogram? We compute Expected Calibration Error — when the model says 0.9, is it right 90% of the time? Lots of teams measure accuracy; few measure calibration."

**Online** (~45s) > "Evaluating production traffic: three cheap checks as an agent capability, off by default, dispatched async after the run — zero added latency. Sample rate bounds the cost. I verified `/triage` latency was untouched."

### Resultados y cierre (2.5 min)
**What landed** (~40s) > "Seven phases, seven reviewable PRs. Versioned prompt, the harness on Pydantic Evals with metrics intact, two suites with a gate, pass-hat-k, the abstaining judge, online evals. 115 tests, and no test calls Groq."

**The lesson** ⭐ (~50s) > ⭐ "The most useful moment was a failure. The regression gate failed on the first run — 0.92. Not the harness, not the model: two borderline labels in the wrong suite. We re-curated instead of lowering the bar, and found a run with too many errors passing vacuously, so we added an error-rate guard. Final regression: accuracy 1.0, and a gate we actually trust."

**Takeaways** (~35s) > ⭐ "One signal, many uses — OTEL spans do debugging, dashboards, and evals. And: a gate you loosen so it passes is not a gate. Thanks — questions?"

**Resources** — dejala en pantalla durante Q&A.

---

## Q&A (respuestas cortas)
- **Logfire vs LangSmith/Langfuse/Phoenix** → "OTEL-native, so no lock-in, and Pydantic-aware — we're all-in on Pydantic AI."
- **¿Latencia por fetchear el prompt?** → "No — resolved once in the lifespan, cached. And there's a code default if Logfire is unreachable."
- **¿El LLM judge no es tan poco confiable como el modelo?** → "That's why you calibrate against human spot-checks, give it an 'unknown' exit, and grade each dimension separately. It's one layer of several."
- **¿Por qué pass^k?** → "Single-run accuracy hides variance. For customer-facing, what matters is being right every time."
- **¿Cuántos casos alcanzan?** → "20–50 from real failures is a fine start; you grow it as it saturates."
- **No sé algo** → "Good question — I don't want to guess. Let me check and get back to you."

## Nervios
Respirá en cada slide-título (son tu pausa). Si te quedás en blanco: `S` (notas) o `B` (pantalla negra) y hablás de memoria. No leas el código línea por línea — señalá una línea y contá el porqué. Cerrá con la frase del gate ⭐.
