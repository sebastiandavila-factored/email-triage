# Delivery guide — Observability & Evals talk (30 min)

Guía de preparación para dar la charla en **inglés** con `presentation-en.html`.
La coaching está en español; **las líneas entre comillas son lo que decís, en inglés** (podés leerlas casi tal cual).

> Regla de oro para hoy: sabés más de este proyecto que nadie en la sala. No estás "presentando teoría", estás **contando lo que hiciste**. Si te trabás, volvé al código real: es tu terreno.

---

## 0. Cómo prepararte en las próximas 2 horas

| Tiempo | Qué hacer |
|---|---|
| 0:00–0:20 | Leé esta guía entera una vez. Abrí el deck y hacé un pase rápido con las flechas. |
| 0:20–0:50 | **Primer ensayo en voz alta** con cronómetro. No pares aunque te trabes. Anotá dónde te pasás de tiempo. |
| 0:50–1:00 | Descanso. Anotá las 5 frases que SÍ o SÍ querés decir (están marcadas ⭐ abajo). |
| 1:00–1:30 | **Segundo ensayo**, ahora respetando los cortes `[SKIP IF SHORT]`. Apuntá a 25 min para dejar aire. |
| 1:30–1:45 | Repasá el bloque de Q&A. Decí las respuestas en voz alta una vez. |
| 1:45–2:00 | Chequeo técnico (abajo) + respirar. Dejá el deck abierto en la primera slide. |

### Manejo del reveal.js
- **Flechas** →/↓ avanzan (↓ entra en las sub-slides verticales de cada Parte).
- Tecla **`S`** abre la vista de **speaker notes** (cada slide ya tiene notas embebidas con el guion resumido y los detalles técnicos). Usala en la pantalla que solo ves vos.
- Tecla **`F`** = pantalla completa · **`Esc`** = vista de grilla para saltar a cualquier slide · **`B`** = pantalla en negro (útil si querés que te miren a vos).
- Abajo a la derecha ves `actual / total` para controlar el ritmo.

### Chequeo técnico (5 min antes)
- Abrí `presentation-en.html` en Chrome, `F` para fullscreen, probá que el código se resalte bien.
- Necesita internet (reveal + highlight vienen de CDN). Si el WiFi es dudoso, abrilo una vez antes para cachear, o descargá los assets.
- Probá el modo presentador (`S`) en tu monitor y el fullscreen en el proyector.

---

## 1. El arco de la charla (tu mapa mental)

Contás una historia en 4 actos + resultado:

1. **Tenemos un agente observable** (email-triage con Logfire/OTEL). ← lo conocido
2. **Los evals dan un lenguaje para medir calidad** (Anthropic). ← el marco
3. **Sacamos el prompt del código** (prompt versioning). ← mejora 1
4. **Estructuramos los evals** (Pydantic Evals). ← mejora 2
5. **Resultado: 7 fases, 115 tests, y una lección** (el gate que falló). ← el gancho final

El hilo que une todo: **una sola señal —los spans de OTEL— sirve para observar, versionar y evaluar.**

---

## 2. Presupuesto de tiempo (30 min)

| Bloque | Min | Acumulado |
|---|---|---|
| Apertura + Agenda + Proyecto | 3 | 3 |
| Parte 1 — Observability | 4.5 | 7.5 |
| Parte 2 — Evals fundamentals | 6 | 13.5 |
| Parte 3 — Prompt versioning | 5 | 18.5 |
| Parte 4 — Pydantic Evals | 6 | 24.5 |
| Resultados + cierre | 2.5 | 27 |
| **Q&A** | 3 | **30** |

**Marcadores de ritmo:** al minuto **13** deberías estar entrando a Parte 3. Al minuto **24** deberías estar en Resultados. Si vas atrasado, aplicá los `[SKIP IF SHORT]`.

---

## 3. Guion por slide

Notación: **⭐ = frase clave que no te quiero ver saltear** · `[CORE]` siempre · `[SKIP IF SHORT]` = cortala si vas justo (una flecha y seguís).

### Apertura — *Title* `[CORE]` (~30 s)
> ⭐ "Hi everyone. Today I want to show you how we took an LLM agent that already had observability, and pushed it to production-grade prompt versioning and evals — all on a real service we run, `email-triage`."
> "The nice part: this isn't a wishlist. All seven phases are already shipped, so I'll show you real code and one lesson that surprised me."

Transición: "Quick agenda, then straight into it."

### *Agenda* `[CORE]` (~20 s)
Señalá las 4 cajas. > "Four blocks: observability, evals fundamentals, prompt versioning, and evals with the framework. Then results."

### *email-triage* `[CORE]` (~45 s)
> "The system is simple: it classifies e-commerce support emails into one of five categories and drafts a reply."
> "Stack is FastAPI, Pydantic AI over Groq, and Logfire for observability. The critical path — `POST /triage` — waits one to three seconds on the model, so latency will matter later."

### *Pydantic contract* `[CORE]` (~45 s)
> "Two things to notice. The output is a Pydantic model — so we get validation for free. And the system prompt…" (señalá) "…lives right here, hardcoded. Hold that thought — it's exactly what we fix in part three."
Transición: "First, the foundation everything else stands on: observability."

---

### Parte 1 — Observability

**Part 1 title** `[CORE]` (~10 s) > "We already had this, and it turns out to be the substrate for evals too."

**OpenTelemetry** `[CORE]` (~60 s)
> ⭐ "OpenTelemetry is to observability what SQL is to databases — an open, vendor-neutral standard."
> "You instrument once against the OTEL SDK and export to any backend. The key consequence: we instrument against OTEL, not against Logfire. Logfire is swappable."
> "And semantic conventions mean different tools agree on names — `gen_ai.*` is the convention for LLMs, which becomes relevant for online evals."

**Span anatomy** `[SKIP IF SHORT]` (~50 s)
> "A span is the building block: a named unit of work with a duration, attributes, and a parent. The `trace_id` ties the whole request together into a tree."
> "This tree is literally what we see in Logfire — and, foreshadowing, what span-based evaluators read later."
*(Si vas bien de tiempo, dale. Si no, saltala: el concepto de span ya lo diste en la anterior.)*

**Logfire** `[CORE]` (~45 s)
> "Logfire is Pydantic's observability backend. Three things matter: it's an ergonomic SDK but plain OTEL underneath; it's Pydantic-aware, so it understands Pydantic AI natively; and traces are queryable with SQL."
> "The new bits we'll use today — prompt management and evals — live right here."

**Three signals** `[SKIP IF SHORT]` (~20 s)
> "Traces, metrics, logs — one protocol. Instrument once, use it for debugging, dashboards, and evals."

**Configuration** `[CORE]` (~45 s)
> "Here's our actual setup. One `configure` call with tail sampling and PII scrubbing, then one line per layer to auto-instrument FastAPI, Pydantic AI, httpx and system metrics."
> "Tail sampling means we decide which traces to keep at the end — once we know if it errored or was slow."

**Business metrics** `[CORE]` (~40 s)
> ⭐ "And we don't only measure infra. Look at `confidence` — we histogram the model's own confidence in production. That's already a quality signal, not just service health. Remember it — it comes back as calibration in part four."
Transición: "So we can see the system. But seeing isn't measuring quality. That's what evals are for."

---

### Parte 2 — Evals fundamentals

**Part 2 title** `[CORE]` (~10 s) > "This part leans on Anthropic's article, 'Demystifying evals for AI agents'."

**What is an eval** `[CORE]` (~40 s)
> "An eval is just a test for an AI system: an input, some grading logic, a measure of success."
> ⭐ "The analogy that lands with engineers: a Case plus an Evaluator is a unit test, a Dataset is the suite, an Experiment is running pytest. The difference — AI is probabilistic, so scores are graded, not just pass/fail."

**Vocabulary** `[SKIP IF SHORT]` (~30 s) — *no leas la tabla entera*
> "Quick shared vocabulary — task, trial, grader, transcript, outcome. The point is the right column: every term already has a counterpart in our code. We didn't start from zero."

**Three graders** `[CORE]` (~50 s)
> "Three families of graders. Code-based: fast, cheap, reproducible, but brittle. Model-based — an LLM judge: flexible and captures nuance, but non-deterministic and needs calibration. And human: the gold standard, but slow and expensive."
> ⭐ "Anthropic's rule: deterministic whenever you can, LLM only where you must, humans to calibrate."

**Capability vs Regression** `[CORE]` ⭐ (~70 s) — *slide fuerte, tomate el tiempo*
> "Two kinds of suites. Capability asks 'what can it do well?' — it starts at a low pass rate, it's your hill to climb. Regression asks 'does it still do what it did?' — near 100%, and a drop means something broke."
> "We split our mixed dataset into both: 25 regression cases with a strict 0.95 gate, 22 capability cases."
> ⭐ "And here's a real finding. Two `status` cases were consistently predicted as `shipments`. The honest read: that's a defensible ambiguity. We did NOT lower the threshold to make it pass — we re-curated them into capability and added clearer status cases. Because a gate you loosen so it passes is not a gate."

**pass@k vs pass^k** `[CORE]` ⭐ (~60 s)
> "Because models are non-deterministic, a single run lies. Two metrics: pass-at-k is the chance of at least one success in k tries — it rises with k. pass-hat-k is the chance that ALL k pass — it falls with k."
> ⭐ "Our temperature is 0.2, not zero — the same email can classify differently. For a customer-facing agent, pass-hat-k is the honest metric: does it get it right every time, not just once."
> "We shipped this as `--repeat K`, plus a flaky-case list. Tested invariant: pass-hat-k is always ≤ accuracy."

**8 steps** `[SKIP IF SHORT]` (~30 s) — *resumí, no leas los 8*
> "Anthropic's zero-to-one roadmap is eight steps, but if you remember one, remember step six: read the transcripts. A score that won't climb is often a broken grader, not a bad model."

**Swiss cheese** `[SKIP IF SHORT]` (~20 s)
> "And evals are just one layer. Automated evals, production monitoring, A/B tests, user feedback — no single layer catches everything. We already had the monitoring layer; evals add the fast pre-deploy one."
Transición: "Okay — theory done. Let's ship the two improvements. First, that hardcoded prompt."

---

### Parte 3 — Prompt versioning

**Part 3 title** `[CORE]` (~10 s) > "Getting the prompt out of the code without a redeploy."

**The problem** `[CORE]` (~40 s)
> "Today, every prompt tweak is a commit and a redeploy. There's no history of which prompt was in prod on Tuesday. Rollback means reverting code. And product or support can't touch it without touching the repo. The prompt is the thing we iterate on most, and it's the most coupled to deploys."

**prompt & version** `[CORE]` (~45 s)
> "Logfire Prompt Management gives three concepts. A prompt is what you author — name, slug, template. A version is an immutable snapshot of the template text: v1, v2, v3."
> ⭐ "And a label — like `production` — is a movable pointer to a version. Your app consumes by label, not by number. Think git tags plus a production pointer."

**Save ≠ Promote** `[CORE]` (~35 s)
> "Two separate steps. You save a version on the Prompts page — iterate on drafts freely. You promote by moving the label on Managed Variables. Only then does production change. That decoupling is the whole governance story — and rollback is just moving the label back."

**The code** `[CORE]` ⭐ (~70 s) — *tu momento "yo me peleé con esto"*
> "Here's what actually shipped — and two production surprises."
> ⭐ "First: `logfire.var()` registers the variable and is NOT idempotent. I found this live — calling it inside a function broke the whole test suite with 'already registered'. So it lives at module level, once. And `.get()` returns a ResolvedVariable with `.value` — it's not a context manager like the docs' first example suggests."
> "We cache the resolution with `lru_cache`, so it's resolved once per process in the lifespan — zero fetch per request, the critical path pays nothing. The `default` is the code prompt, so if Logfire is down, we fall back and don't break."
> "And that last guard protects governance: if someone edits the prompt in the UI and drops a category, it warns via log instead of silently breaking classification."

**Applied** `[CORE]` (~40 s)
> "So: resolved by label, injected via Depends, cached in the lifespan, code stays the source of truth, governance guard in place. The only manual step is creating the prompt and moving the label in the UI — and the code boots fine without it."
> ⭐ "The payoff: rolling back a bad prompt is moving a label. No commit, no deploy."
Transición: "Second improvement: our home-grown eval harness, meet the framework."

---

### Parte 4 — Pydantic Evals

**Part 4 title** `[CORE]` (~10 s) > "From our custom harness to Pydantic Evals — without losing anything we built."

**Data model** `[SKIP IF SHORT]` (~25 s)
> "Simple model: a Dataset has Cases, an Experiment runs a Task against them with Evaluators. Code-first — evals live in the repo, versioned with git, and Logfire visualizes the results."

**Minimal eval** `[CORE]` (~50 s)
> "Here's an end-to-end eval. A Case with input and expected output, a custom Evaluator — that's our `is_correct` — a Dataset, and `evaluate_sync` runs the suite."
> "One real quirk: `expected_output` is typed as the task's output type, so we keep the ground-truth category in metadata and read it from there. We reused our existing metrics.py untouched."

**LLM judge** `[CORE]` ⭐ (~55 s)
> "We had a home-grown JudgeAgent with a five-dimension rubric. We wrapped it in a framework Evaluator instead of throwing it away."
> ⭐ "And we took Anthropic's advice: give the judge a way out. We added an 'unknown' verdict — when it can't tell, it abstains instead of inventing. Those cases are excluded from the averages but counted in an unknown-rate. Plus an export for human spot-check — that's the seam for calibration."

**Span-based** `[CORE]` ⭐ (~45 s) — *el "aha" de la charla*
> ⭐ "This is where it all connects. A span-based evaluator reads the SAME OTEL span tree we saw in part one. So your eval assertions are aligned with your production telemetry — you can grade HOW the agent got there, not just the final answer. Observability and evals are the same signal."

**Calibration** `[CORE]` (~40 s)
> "Remember the confidence histogram from part one? Here it pays off. We compute Expected Calibration Error — when the model says 0.9, is it right 90% of the time?"
> ⭐ "Lots of teams measure accuracy. Very few measure calibration. If confidence is miscalibrated, you can't use it to decide when to escalate to a human."

**Online** `[CORE]` (~45 s)
> "Finally, evaluating production traffic. Three cheap checks — output not empty, confidence in range, language matches — as an agent capability, off by default."
> "They dispatch async after the run, so zero added latency. Sample rate and max-concurrency bound the cost. I verified `/triage` latency was untouched, and that pydantic-ai actually supports the capabilities API — that was the main risk of this phase."
Transición: "So what did all this leave in the repo?"

---

### Resultados y cierre

**What landed** `[CORE]` (~40 s)
> "Seven phases, seven reviewable PRs. Versioned prompt, the harness on Pydantic Evals with all metrics intact, two suites with a gate, pass-hat-k, the abstaining judge, online evals, a balanced dataset. 115 tests, pyright strict, pre-commit green — and no test ever calls Groq."

**The lesson** `[CORE]` ⭐ (~50 s) — *cerrá fuerte con esto*
> ⭐ "The most useful moment was a failure. The regression gate failed on the first real run — 0.92. It wasn't the harness or the model: two status cases were borderline labels in the wrong suite. We re-curated instead of lowering the bar. And we found a run with too many errors was passing vacuously, so we added an error-rate guard. Final regression: accuracy 1.0, and a gate we actually trust."

**Takeaways** `[CORE]` (~40 s)
> "Five things to take away." (dejá que lean, resaltá 2)
> ⭐ "One signal, many uses — OTEL spans do debugging, dashboards, and evals. And: a gate you loosen so it passes is not a gate. Re-curate the dataset, not the threshold."
> "Thanks — happy to take questions."

**Resources** — dejala en pantalla durante Q&A.

---

## 4. Q&A — preguntas probables y respuestas cortas

- **"Why Logfire and not LangSmith / Langfuse / Phoenix?"**
  > "Mainly because it's OTEL-native, so no lock-in, and it's Pydantic-aware — we're already all-in on Pydantic AI. But the instrumentation is standard OTEL, so we could point it elsewhere."

- **"Doesn't fetching the prompt from Logfire add latency to every request?"**
  > "No — we resolve it once per process in the lifespan and cache it with lru_cache. Zero fetch on the hot path. And there's a code default, so if Logfire is unreachable we fall back instead of failing."

- **"Isn't an LLM judge just as unreliable as the model it grades?"**
  > "That's exactly why you calibrate it against human spot-checks, give it an 'unknown' exit, and grade each dimension in isolation. It's a signal, not ground truth — that's why it's one layer of several."

- **"Why pass^k instead of just accuracy?"**
  > "Accuracy on a single run hides variance. With temperature above zero, the same input can flip. For a customer-facing agent, what matters is being right every time, and pass-hat-k measures exactly that."

- **"How many cases is enough?"**
  > "Anthropic says 20–50 from real failures is a fine start, and that matched us. Early on, each change has a big, visible effect, so small samples suffice. You grow the suite as it saturates."

- **"What was the hardest part technically?"**
  > "Two things: `logfire.var()` not being idempotent broke the test suite until I moved it to module level; and confirming pydantic-ai's capabilities API for online evals. Both are in the speaker notes if you want details."

- **Si no sabés algo:**
  > "Good question — I don't want to guess. Let me check the docs and get back to you." (perfectamente válido; no inventes.)

---

## 5. Recordatorios de entrega (nervios y ritmo)

- Hablás **más rápido** cuando estás nervioso. Respirá en cada transición de Parte (las slides-título son tu momento para bajar un cambio).
- Si te quedás en blanco: apretá **`S`**, las notas tienen el guion. O apretá **`B`** (pantalla negra) y hablá de memoria mirando a la gente.
- No leas el código línea por línea. Señalá **una** línea clave y contá el "por qué".
- Tenés permiso de **saltear** cualquier `[SKIP IF SHORT]` sin avisar. Nadie sabe lo que ibas a decir.
- Cerrá siempre con la frase del gate ⭐ — es la que se van a acordar.

Éxitos. Lo tenés dominado: esto lo construiste vos.
