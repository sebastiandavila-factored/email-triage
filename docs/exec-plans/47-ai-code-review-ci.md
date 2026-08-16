# 47. Code review asistido por IA en CI (Claude Code Action + skill del repo)

**Status:** 🚧 implemented (pending human review/merge)
**Estimate:** ~2 hrs
**Depends on:** nada del código de la app. Depende de infra externa: instalar la
**Claude GitHub App** en el repo y cargar el secret `ANTHROPIC_API_KEY` (lo hace el humano — ver §Setup).
**Tipo:** tooling / CI (no toca `email_triage/`; no cambia la superficie pública `/triage`, `/triage/stream`, `/health`).

## Intent

Correr un **code review asistido por IA en cada pull request**, que conozca las
convenciones reales de este repo (async en el critical path, DI vía `Depends`, códigos
HTTP semánticos, "los tests nunca llaman a Groq", pyright strict, y sobre todo las
reglas de **Triage Studio** — no re-freezear categorías ni rutear `/triage` por el enum).
El review postea **comentarios inline** en el PR. El humano sigue siendo quien aprueba y
mergea (AGENTS.md §3): esto es una red de seguridad automática, no un gate bloqueante.

## Hallazgo que definió el diseño

Anthropic ofrece **tres caminos oficiales** para code review con IA, y "usar el Agent SDK"
y "usar una GitHub Action" **no son excluyentes** — la Action oficial ya está construida
sobre el Agent SDK:

1. **Code Review** (producto administrado): review automático sin escribir workflow.
   Cero mantenimiento, pero **no conoce las convenciones del repo**.
2. **`anthropics/claude-code-action@v1`** (GitHub Action, sobre el Agent SDK): trae un
   plugin `code-review` oficial. Se le puede pasar un **skill propio** del repo como prompt.
3. **`claude-agent-sdk`** (Python/TS): agente 100% custom corrido en CI. Máximo control
   (integrable con Logfire/evals), pero uno mantiene el agent loop y el posteo a GitHub.

**Decisión (con el humano):** camino **2 con skill del repo** — la Action oficial
(bajo mantenimiento de Anthropic) invocando `.claude/skills/review-pr/`, que codifica las
convenciones de `CLAUDE.md`. Balance entre bajo mantenimiento y conocimiento del repo.
Auth con `ANTHROPIC_API_KEY` (Console), no con token de suscripción, porque el secret
no queda atado a una cuenta personal y factura por API (apto para CI/org).

## Prior reading

- [CLAUDE.md](../../CLAUDE.md) — convenciones técnicas y **Agent limits** (fuente de verdad del skill).
- [AGENTS.md](../../AGENTS.md) §3-4 — protocolo (por eso existe este exec-plan) y "el humano commitea".
- [docs/proposals/001-triage-studio.md](../proposals/001-triage-studio.md) — regla crítica de categorías que el review debe hacer respetar.
- Docs oficiales: `code.claude.com/docs/en/github-actions` (workflow, inputs, `--comment`, MCP inline-comment) y `.../en/skills` (frontmatter: `allowed-tools`, `disable-model-invocation`).

## Diseño implementado

- **`.claude/skills/review-pr/SKILL.md`** (nuevo) — el skill de review. Nombre `review-pr`
  (no `code-review`) para **evitar colisión** con el skill bundled `/code-review` de Claude Code.
  - Frontmatter: `disable-model-invocation: true` (solo corre cuando se lo invoca
    explícitamente, no auto-triggerea en sesiones locales); `allowed-tools` pre-aprueba
    la tool MCP `mcp__github_inline_comment__create_inline_comment` + `Read/Grep/Glob` +
    `Bash(git diff/fetch/log/status *)`.
  - Cuerpo: obtiene el diff con `git fetch origin <base>` + `git diff origin/<base>...HEAD`
    (revisa **solo las líneas cambiadas**), y chequea contra las convenciones en orden de
    prioridad: correctness → contratos del repo (Pydantic/DI/HTTP-codes/logging/**Triage
    Studio**/scope) → tests (no Groq) → secretos → calidad (pyright strict, sin nits de estilo
    que ya cubre ruff). Reporta con severidad `blocker/should-fix/nit`.
  - Modo CI (`--comment`): postea inline. Modo local (`/review-pr`): imprime hallazgos.
- **`.github/workflows/code-review.yml`** (nuevo) — job en `pull_request`
  (`opened/synchronize/ready_for_review/reopened`), skip de drafts, `concurrency` con
  cancel-in-progress, `timeout-minutes: 20`. Permisos mínimos (`contents: read`,
  `pull-requests: write`, `id-token: write`). `actions/checkout@v6` con `fetch-depth: 0`
  para poder diffear contra la base. Invoca `/review-pr --comment <repo>/pull/<n> --base <ref>`;
  `claude_args` habilita la tool inline-comment, fija `--model claude-opus-5` (cambiar a
  `claude-sonnet-5` para abaratar) y `--max-turns 30`.
- **`docs/CODE-REVIEW.md`** (nuevo) — doc de setup/handoff: cómo funciona, los pasos
  one-time del humano, notas de costo/fork-PRs/uso local, y alternativas consideradas.

## Decisiones clave

- **`--base <ref>` explícito** (desde `github.event.pull_request.base.ref`) en vez de
  depender de `gh` autenticado: el diff es determinístico y no necesita token de shell.
- **`pull-requests: write`** (no `read`): necesario para postear los comentarios inline.
- **Modelo:** `claude-opus-5` por defecto (mejor recall/precision en review); documentada
  la baja a `claude-sonnet-5` para costo.

## Setup (humano — el agente no puede)

1. Instalar la **Claude GitHub App** (`github.com/apps/claude`) en `sebastiandavila-factored/email-triage`.
2. Cargar el secret `ANTHROPIC_API_KEY` (repo → Settings → Secrets → Actions).
3. Mergear el PR con estos archivos. Detalle en [docs/CODE-REVIEW.md](../CODE-REVIEW.md).

## Testing

- **Estático (hecho):** YAML del workflow y frontmatter del skill parsean OK (`yaml.safe_load`).
- **Funcional (humano, post-merge):** abrir un PR de prueba con un cambio que viole una
  convención (p.ej. instanciar `LLMService` dentro de un handler, o un test que llame a Groq)
  y verificar que Claude postea el comentario inline correspondiente. Probar también un cambio
  limpio → un único comentario-resumen aprobando.
- **Local:** `/review-pr` dentro de `claude` en el repo imprime hallazgos sin postear.

## Fuera de alcance

- No es un gate bloqueante del merge (el humano decide). Se puede volver required check después.
- No corre en PRs desde forks (GitHub oculta secrets ahí); el repo es privado, así que las
  ramas internas están cubiertas.
- No reemplaza a ruff/pyright/pre-commit; los complementa con revisión semántica.
