# 26. Triage Studio F3 — Few-shot examples + template overrides + publish/eval-gate

**Status:** ✅ delivered (3 tablas + compilador few-shot/overrides + `prompt_studio` service + `prompt:publish` + router + 19 tests + docs). Decisión de gobernanza aprobada: "publicado gana, si existe".
**Estimate:** ~9 hrs (la fase más grande; ver "Execution order" para el sub-split F3a/F3b)
**Depends on:** Plan 24 (F1 — categorías), Plan 25 (F2 — compilador + servicio por versión).
**Propuesta madre:** [docs/proposals/001-triage-studio.md](../proposals/001-triage-studio.md) — Fase F3.

## Intent

F1 dio taxonomía por workspace; F2 la compiló en un prompt XML servido en `/triage`.
F3 completa el **self-service del prompt**: ejemplos few-shot por categoría, overrides
de los bloques del template (role/task/guardrails/tone), y un flujo
**draft → preview → publish** con **eval-gate** y **versionado inmutable** (rollback).
Es la fase que materializa los dominios de gobernanza de la certificación:
evaluación antes de publicar (dominio 3) y confiabilidad/versionado (dominio 1).

## Decisión clave (requiere visto bueno antes de implementar)

F2 hace que **editar una categoría se refleje en `/triage` al instante** (cache por
hash de taxonomía). F3 introduce publish con eval-gate. ¿Conviven?

**Diseño recomendado — "publicado gana, si existe":**
- Editar categorías/ejemplos/template muta un **draft** (working set).
- `preview` compila el draft **sin** publicar (para verlo).
- `publish` corre el eval-gate y, si pasa, **congela** el prompt compilado como una
  nueva `prompt_versions` inmutable.
- `/triage` sirve: **la versión publicada** si el tenant tiene una; **si no**, cae al
  comportamiento F2 (compilar en vivo desde las categorías activas).

Así, un workspace que nunca toca el Studio conserva el comportamiento cero-config de
F2; uno que publica obtiene gobernanza (versión, gate, rollback). El precio: para ese
workspace, los edits ya **no** son live — requieren `publish`. Es el trade-off correcto
para un producto multi-tenant serio, y es la historia que evalúa la certificación.

> **Esto cambia la semántica de F2** para tenants con versión publicada. Se documenta y
> se actualiza el feature doc de F2. **Confirmar antes de codear.**

## Data model (3 tablas nuevas, migración `0005`)

```
triage_examples
  id            UUID PK
  tenant_id     UUID FK tenants(id) ON DELETE CASCADE, INDEX
  category_id   UUID FK categories(id) ON DELETE CASCADE, INDEX
  kind          VARCHAR(10)   -- 'positive' | 'negative'
  subject       VARCHAR(500)
  body          TEXT
  expected_reply TEXT NULL    -- opcional: demuestra tono, no solo la clase
  created_by    UUID FK users(id)
  created_at    TIMESTAMPTZ

prompt_templates             -- un draft mutable por tenant (overrides de bloques)
  tenant_id     UUID PK FK tenants(id) ON DELETE CASCADE
  role_block    TEXT NULL     -- NULL ⇒ usa el default del compilador
  task_block    TEXT NULL
  guardrails_block TEXT NULL
  tone          TEXT NULL
  updated_by    UUID FK users(id)
  updated_at    TIMESTAMPTZ

prompt_versions              -- historial inmutable (publish + rollback)
  id            UUID PK
  tenant_id     UUID FK, INDEX
  version       INTEGER       -- incremental por tenant (UNIQUE(tenant_id, version))
  compiled_prompt TEXT        -- el prompt XML final, congelado
  allowed_slugs JSON          -- set de slugs de esa versión (reproducibilidad)
  eval_run_id   UUID FK eval_runs(id) NULL   -- el gate que la aprobó
  published_by  UUID FK users(id)
  published_at  TIMESTAMPTZ
  is_active     BOOLEAN       -- exactamente una activa por tenant
```

## Compiler (F3 amplía F2, retrocompatible)

`compile_system_prompt` gana parámetros **opcionales** (defaults = comportamiento F2):

```python
def compile_system_prompt(
    categories: list[CategorySpec],
    examples: list[ExampleSpec] | None = None,     # → <examples>
    overrides: TemplateOverrides | None = None,     # role/task/guardrails/tone
) -> str: ...
```

- `<examples>` se emite entre `<categories>` y `<output_format>` (few-shot antes de la
  tarea). Cada `<example kind=…>` lleva `<email><subject/><body/></email>`,
  `<classification>slug</classification>` y `<reply>` si hay `expected_reply`.
- Overrides `None`/campo `None` ⇒ el bloque default actual. `tone` se concatena a
  `<guardrails>` o a un `<style>` propio.
- Se mantiene el escapado XML y el invariante de cobertura de F2.

## RBAC

| Scope | owner | admin | member | Protege |
|---|---|---|---|---|
| `triage:configure` (F1) | ✅ | ✅ | ❌ | CRUD ejemplos, editar draft del template, preview |
| `prompt:publish` (**nuevo**) | ✅ | ❌ | ❌ | Publicar/activar/rollback de versiones |

`PublishPromptDep = require_scope("prompt:publish")`.

## Endpoints (scoped por `{tid}`)

| Método | Ruta | Scope | Acción |
|---|---|---|---|
| `GET`/`POST` | `/workspaces/{tid}/categories/{cid}/examples` | member / `triage:configure` | Listar / añadir few-shot |
| `DELETE` | `/workspaces/{tid}/examples/{eid}` | `triage:configure` | Borrar ejemplo |
| `GET`/`PUT` | `/workspaces/{tid}/prompt/draft` | member / `triage:configure` | Ver / editar overrides del template |
| `POST` | `/workspaces/{tid}/prompt/preview` | `triage:configure` | Compilar draft (no publica) → devuelve el XML |
| `GET` | `/workspaces/{tid}/prompt/versions` | member | Historial de versiones |
| `POST` | `/workspaces/{tid}/prompt/publish` | `prompt:publish` | Eval-gate + congelar nueva versión activa |
| `POST` | `/workspaces/{tid}/prompt/versions/{v}/activate` | `prompt:publish` | Rollback a una versión previa |

## Eval-gate

`publish` compila el draft, corre el dataset del tenant vía **pydantic-evals** (ya en
`evals/`) contra el prompt compilado, y compara con el baseline de la versión activa:

- Sin versión activa previa ⇒ se publica (primer baseline).
- `accuracy` o `macro_f1` por debajo del baseline (margen configurable) ⇒ **409**, no
  publica; devuelve el diff de métricas. El `eval_run_id` se liga a `prompt_versions`.
- **Dataset del tenant:** F3 arranca con el dataset legacy compartido; un dataset por
  tenant es una extensión (fuera de scope, anotada).

## Runtime (`get_triage_service`, evolución de F2)

```
resolver servicio(tenant):
  v = versión activa del tenant?
    sí → LLMService(prompt=v.compiled_prompt, allowed_slugs=set(v.allowed_slugs));
         cache key = (tenant, "v{n}")
    no → comportamiento F2 (compilar en vivo; cache key = (tenant, taxonomy_hash))
```

Publicar/activar/rollback llama `clear_triage_service_cache()` (o invalida la entrada
del tenant) para propagar sin reinicio.

## Concrete changes

| Archivo | Cambio |
|---|---|
| `email_triage/db/models.py` | + `TriageExample`, `PromptTemplate`, `PromptVersion` |
| `alembic/versions/0005_examples_prompt_versions.py` | 3 tablas |
| `email_triage/db/repos/examples.py`, `prompts.py` | repos nuevos |
| `email_triage/services/prompt_compiler.py` | `examples`/`overrides` opcionales + `ExampleSpec`/`TemplateOverrides` |
| `email_triage/services/prompt_studio.py` | **nuevo** — reglas de draft/preview/publish/rollback + eval-gate |
| `email_triage/auth/scopes.py` | + `prompt:publish` (owner) |
| `email_triage/deps.py` | `get_triage_service` resuelve versión activa; `PublishPromptDep` |
| `email_triage/routers/prompt_studio.py` | **nuevo** router (examples + draft + preview + versions + publish) |
| `email_triage/main.py` | registra el router |
| `tests/test_prompt_studio.py` | ejemplos, compilación con few-shot, gate (pasa/bloquea), rollback, RBAC |
| `docs/features/26-*`, `docs/testing/26-*` | docs |

## Design decisions

| Decisión | Alternativa | Razón |
|---|---|---|
| "Publicado gana, si existe"; sin versión ⇒ F2 live | Todo por publish siempre | No romper el cero-config de tenants que no usan el Studio |
| `prompt_versions` inmutable + `is_active` | Editar la versión en sitio | Auditoría y rollback trivial (activar otra fila) |
| Eval-gate bloquea con 409 + diff | Publicar y avisar | La gobernanza que evalúa la certificación; evita regresiones silenciosas |
| Overrides con `NULL ⇒ default` | Copiar el template completo al draft | Menos deriva; el default evoluciona con el código |
| `expected_reply` opcional en ejemplos | Siempre exigirlo | Un ejemplo de solo-clasificación ya aporta señal |

## Risks / Open questions

- **Semántica F2 cambia** para tenants con versión publicada (ver Decisión clave).
- **Coste/latencia del eval-gate:** corre el dataset con LLM real en el request de
  publish → puede tardar. Mitigación: correrlo como tarea en background y exponer estado
  (`pending`/`passed`/`failed`), o límite de tamaño de dataset. Decidir en F3b.
- **Tamaño del prompt** con muchos ejemplos → coste. Límite de N ejemplos activos por
  categoría; el split estable/volátil de F2 ya ayuda al caching.
- **Dataset por tenant:** F3 usa el legacy compartido; por-tenant es extensión futura.
- **Inyección vía ejemplos:** un ejemplo `negative` puede documentar intentos de
  injection etiquetados como manejo correcto (refuerza el guardrail de F2).

## Execution order (sub-split sugerido)

**F3a — Few-shot (live, sin publish):**
1. `TriageExample` + migración `0005` (parcial) + repo (40 min).
2. Compiler: `examples` opcional + `ExampleSpec` + tests (60 min).
3. Endpoints de examples + `get_triage_service` incluye ejemplos activos en el hash (50 min).
4. Tests examples + RBAC (50 min).

**F3b — Template overrides + publish + gate:**
5. `PromptTemplate`/`PromptVersion` (migración) + repos (50 min).
6. `prompt_studio` service: draft/preview/publish/rollback + eval-gate (120 min).
7. Scope `prompt:publish` + endpoints + runtime resuelve versión activa (75 min).
8. Tests: gate pasa/bloquea, rollback, "publicado gana" (90 min).
9. Docs `26-*` + actualizar feature doc de F2 (semántica) (40 min).
10. `make check` verde.

## Done when

- [x] Añadir ejemplos a una categoría los inyecta en `<examples>` del prompt compilado
- [x] `preview` devuelve el XML del draft sin publicar; `/triage` no cambia hasta `publish`
- [x] `publish` con métricas ≥ baseline crea versión activa; por debajo → 409 con diff (gate inyectable, testeado)
- [x] Rollback: activar una versión previa cambia `/triage` sin reiniciar (`clear_triage_service_cache`)
- [x] Tenant sin versión publicada conserva el comportamiento F2 (live-compile) — `test_published_version_wins_over_live_compile` + F2 suite verde
- [x] `prompt:publish` solo owner; `triage:configure` para el resto del CRUD
- [x] `make check` verde (ruff + pyright 0 + 170 tests); `docs/features/26-*` y `docs/testing/26-*`

> **Ajustes durante ejecución:** (1) métricas del gate (`accuracy`/`macro_f1`) se guardan
> **inline** en `prompt_versions` como baseline, en vez de un FK a `eval_runs` — más simple y
> self-contained. (2) El endpoint `publish` corre con `gate=None` (publish versionado sin
> evaluación); el gate se ejercita a nivel de servicio con un doble inyectado. Cablear un gate
> real con dataset por-tenant queda como extensión documentada.
