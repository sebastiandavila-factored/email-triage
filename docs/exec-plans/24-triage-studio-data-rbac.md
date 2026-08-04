# 24. Triage Studio F1 — Taxonomía por workspace (Data & RBAC)

**Status:** ✅ delivered (tabla + migración + repo + servicio + scope + CRUD + 26 tests + docs). UI en F5.
**Estimate:** ~5 hrs
**Depends on:** Plan 21 (Workspaces + RBAC, `require_scope`), Plan 14 (DB).
**Propuesta madre:** [docs/proposals/001-triage-studio.md](../proposals/001-triage-studio.md) — Fase F1.

## Intent

Hoy las 5 categorías de triage están **congeladas en código** (`schemas.Category`
StrEnum) e idénticas para todos los tenants. Esta es la primera fase de **Triage
Studio**: mover la taxonomía a la base de datos para que cada workspace defina
**sus propias categorías**, gestionadas por `owner`/`admin` vía API con RBAC.

F1 es deliberadamente la rebanada de **menor riesgo**: crea la tabla, el scope y
el CRUD, **sin tocar el critical path de `/triage`**. El compilador de prompt que
consume estas categorías (output type dinámico, XML tags) llega en F2; los
ejemplos few-shot y el flujo publish/eval-gate en F3. Al terminar F1, las
categorías existen y son editables, pero `/triage` sigue usando el enum legacy —
cero regresión en producción.

## Prior reading

- Propuesta madre [001-triage-studio](../proposals/001-triage-studio.md), §4 (modelo de datos), §6 (RBAC), §9 (gobernanza).
- Plan [21](21-team-workspaces-rbac.md) — patrón `require_scope(...)`, `WorkspaceService`, CRUD scoped por `{tid}`.
- Plan [14](14-database-postgresql.md) — Alembic, repos async.
- **OWASP Authorization Cheat Sheet** (IDOR / object-level) — https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html

## Scope

**Incluido:**
- Tabla `categories` + migración `0004` (scoped por `tenant_id`).
- Scope nuevo `triage:configure` en `auth/scopes.py` (owner + admin).
- `CategoryRepo` (SQL) + `TriageConfigService` (reglas de negocio).
- Dependencia `ConfigureTriageDep = require_scope("triage:configure")` en `deps.py`.
- Router `/workspaces/{tid}/categories*`: list (miembro), create/patch/delete (`triage:configure`).
- **Seed de compatibilidad:** al crear un workspace, sembrar las 5 categorías legacy
  (`status`, `refunds`, `availability`, `shipments`, `prices`) para que ningún tenant
  arranque con taxonomía vacía. Workspaces existentes se siembran en la migración (data migration).
- Reglas: slug único por tenant, slug `unknown` **reservado** (no creable, no borrable), no
  desactivar la última categoría activa.
- Tests: servicio (reglas) + endpoints (scopes, IDOR) + migración idempotente.

**Fuera de scope (fases siguientes):**
- Compilador de prompt XML, output type dinámico, cache por `(tenant, versión)` → **F2**.
- Tablas `triage_examples`, `prompt_templates`, `prompt_versions`; ejemplos few-shot;
  draft/preview/publish; eval-gate → **F3**.
- Scope `prompt:publish` → se define en **F3** (no se definen scopes sin uso).
- Servidor MCP, slash commands → **F4**. UI → **F5**.
- Cualquier cambio a `/triage`, `services/llm.py` o `schemas.Category`.

## Data model

Una tabla nueva. `prompt_templates`/`prompt_versions`/`triage_examples` se difieren
a F2/F3 porque su esquema está acoplado al diseño del compilador y evitaría rework
definirlas ahora.

```
categories
  id            UUID PK
  tenant_id     UUID FK → tenants.id ON DELETE CASCADE, INDEX
  slug          VARCHAR(50)   NOT NULL   — estable; valor de clasificación
  name          VARCHAR(255)  NOT NULL   — display
  description   TEXT          NOT NULL   — irá en <category><description> (F2)
  is_active     BOOLEAN       NOT NULL DEFAULT true
  sort_order    INTEGER       NOT NULL DEFAULT 0
  created_at    TIMESTAMPTZ   NOT NULL DEFAULT now()
  updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now()

  UNIQUE (tenant_id, slug)
  INDEX  (tenant_id)
```

> **`unknown` reservado:** no se persiste como fila. Es una categoría implícita que
> el compilador (F2) siempre añade al prompt. F1 solo garantiza que nadie pueda crear
> una categoría con `slug="unknown"` (colisión futura).

## Migración `0004`

`alembic/versions/0004_categories.py` hace dos cosas:

1. **Schema:** `op.create_table("categories", ...)` con el UNIQUE y el índice.
2. **Data migration (seed):** para cada `tenant` existente, insertar las 5 categorías
   legacy con `sort_order` 0..4 y `description` tomada del `SYSTEM_PROMPT` actual.
   Idempotente (chequear existencia antes de insertar) para que re-correr no duplique.

El seed de **nuevos** workspaces se hace en código (ver `TriageConfigService.seed_defaults`),
no en la migración — la migración solo cubre los que ya existen.

```python
LEGACY_CATEGORIES = [
    ("status",       "Order status",  "Question about the status of an order"),
    ("refunds",      "Refunds",       "Question about refund eligibility or process"),
    ("availability", "Availability",  "Question about product availability or stock"),
    ("shipments",    "Shipments",     "Question about shipping times, costs or methods"),
    ("prices",       "Prices",        "Question about prices, discounts or promotions"),
]
```

## RBAC

Se añade un scope al mapa de `auth/scopes.py`, respetando la jerarquía existente:

```python
TRIAGE_CONFIGURE: Final = "triage:configure"

ROLE_SCOPES = {
    "owner":  frozenset({TRIAGE_WRITE, TRIAGE_CONFIGURE, WORKSPACE_MANAGE, WORKSPACE_DELETE}),
    "admin":  frozenset({TRIAGE_WRITE, TRIAGE_CONFIGURE, WORKSPACE_MANAGE}),
    "member": frozenset({TRIAGE_WRITE}),
}
```

Dependencia en `deps.py`, idéntica al patrón del Plan 21:

```python
ConfigureTriageDep = Annotated[WorkspaceContext, Depends(require_scope("triage:configure"))]
```

`require_scope` ya carga la membership por `(user_id, tid)` → verifica pertenencia
al workspace (defensa IDOR) además del rol. No hace falta lógica nueva de auth.

## Endpoints

Todos scoped por `{tid}` en el path; el enforcement usa el rol del caller **en ese workspace**.

| Método | Ruta | Scope exigido | Notas |
|---|---|---|---|
| `GET` | `/workspaces/{tid}/categories` | miembro | Lista categorías (incluye inactivas; `?active=true` filtra). |
| `POST` | `/workspaces/{tid}/categories` | `triage:configure` | Crea. Rechaza slug duplicado (409) y `unknown` (422). |
| `PATCH` | `/workspaces/{tid}/categories/{cid}` | `triage:configure` | Edita name/description/is_active/sort_order. |
| `DELETE` | `/workspaces/{tid}/categories/{cid}` | `triage:configure` | Borra. Prohíbe borrar la última activa (409). |

Schemas Pydantic (en el router, como en `routers/workspaces.py`):
`CategoryOut`, `CreateCategoryIn` (slug, name, description), `UpdateCategoryIn`
(campos opcionales).

## TriageConfigService — reglas de negocio

`services/triage_config.py`. Repos hacen SQL; el servicio hace **reglas** y es
testeable sin HTTP (mismo criterio que `WorkspaceService`):

```python
class TriageConfigService:
    async def seed_defaults(session, tenant_id) -> None       # 5 legacy, al crear workspace
    async def list_categories(session, tenant_id, active_only=False) -> list[Category]
    async def create_category(session, tenant_id, slug, name, description) -> Category
    async def update_category(session, tenant_id, category_id, **fields) -> Category
    async def delete_category(session, tenant_id, category_id) -> None
```

Reglas que encapsula (cada una con test):
- **Slug reservado:** `slug == "unknown"` → 422 (colisiona con la categoría implícita del compilador).
- **Slug único por tenant:** duplicado → 409 (además del UNIQUE en DB, chequeo previo para mensaje limpio).
- **Formato de slug:** `^[a-z0-9_]{1,50}$` (estable, seguro para XML/JSON) → 422 si no.
- **Última activa protegida:** no desactivar/borrar si dejaría al tenant con **0 categorías activas** → 409. (Análogo al "último owner" del Plan 21.)
- **Object-level:** toda operación filtra por `tenant_id`; una categoría de otro tenant → 404 (no 403, para no filtrar existencia).

`WorkspaceService.create_team` / la creación del workspace personal llaman a
`seed_defaults` dentro de la misma transacción, para que ningún workspace nazca sin taxonomía.

## Concrete changes

| Archivo | Cambio |
|---|---|
| `email_triage/db/models.py` | + `Category` |
| `alembic/versions/0004_categories.py` | crea `categories` + seed de tenants existentes (idempotente) |
| `email_triage/db/repos/categories.py` | **nuevo** `CategoryRepo`: create, list_for_tenant, get, update, delete, count_active |
| `email_triage/services/triage_config.py` | **nuevo** `TriageConfigService` (reglas + `seed_defaults`) |
| `email_triage/services/workspace.py` | `create_team` siembra defaults; hook para el workspace personal |
| `email_triage/auth/scopes.py` | + `TRIAGE_CONFIGURE` en `ROLE_SCOPES` |
| `email_triage/deps.py` | + `ConfigureTriageDep` |
| `email_triage/routers/workspaces.py` | + endpoints `/categories*` (o router nuevo `routers/categories.py` montado igual) |
| `tests/test_triage_config.py` | servicio (reglas) + endpoints (scopes, IDOR) + seed |
| `docs/features/24-*.md`, `docs/testing/24-*.md` | docs |

> **Nota de naming:** el modelo SQLAlchemy se llama `Category` y vive junto a los demás
> en `db/models.py`. **No** colisiona con `schemas.Category` (el StrEnum) porque están en
> módulos distintos; F1 no toca el StrEnum. En F2, cuando el output type se vuelva dinámico,
> se decide si el StrEnum se retira o se conserva solo para el fallback sin-DB.

## Design decisions

| Decisión | Alternativa | Razón |
|---|---|---|
| Solo tabla `categories` en F1 | crear las 4 tablas de una vez | `prompt_templates`/`examples` están acopladas al compilador (F2/F3); definirlas ya = rework garantizado |
| No tocar `/triage` ni `schemas.Category` | migrar el critical path ahora | F1 debe ser cero-regresión; el enum legacy sigue sirviendo hasta que F2 tenga el compilador probado |
| Seed de 5 legacy por workspace | arrancar con taxonomía vacía | Continuidad de producto; nadie pierde comportamiento actual al migrar |
| `unknown` reservado, no persistido | dejar que el owner lo cree | Es la categoría de escape del compilador (F2); reservarla evita colisión y ambigüedad |
| Categoría de otro tenant → 404 | 403 | No filtrar existencia de recursos ajenos (OWASP) |
| Reutilizar `require_scope` | auth nueva | Ya resuelve membership por `(user,tenant)` → rol + IDOR gratis |

## Risks / Open questions

- **Slug inmutable:** ¿se permite editar el `slug` tras crearlo? **Decisión F1: no**
  (el slug es el valor de clasificación; cambiarlo invalidaría logs/evals históricos).
  Solo `name`/`description`/`is_active`/`sort_order` son editables. Renombrar = crear
  nueva + desactivar vieja.
- **Carrera al desactivar la última activa:** envolver en transacción y re-chequear
  `count_active` dentro; mapear a 409.
- **Interacción con evals existentes:** los datasets en `evals/` asumen las 5 categorías.
  No se tocan en F1 (siguen validando el enum legacy); F3 los parametriza por tenant.
- **`TriageLog.category`** es `String(50)` (no FK) → ya tolera slugs arbitrarios; sin cambios.

## Execution order

1. Modelo `Category` + migración `0004` (schema + seed idempotente) (45 min).
2. `CategoryRepo` (create/list/get/update/delete/count_active) (30 min).
3. `TriageConfigService` + `seed_defaults` + tests de reglas (75 min).
4. Scope `TRIAGE_CONFIGURE` + `ConfigureTriageDep` + wiring del seed en creación de workspace (30 min).
5. Endpoints `/categories*` + schemas (45 min).
6. Tests de endpoints (scopes, IDOR, slug reservado/duplicado, última activa) (60 min).
7. Docs `features/24-*` + `testing/24-*` (30 min).
8. `make check` verde.

## Done when

- [x] `POST /workspaces/{tid}/categories` crea categoría; `member` → 403, `admin`/`owner` → 201
- [x] Slug duplicado → 409; `slug="unknown"` → 422; slug con espacios/guiones/emoji/>50 → 422 (mayúsculas se normalizan)
- [x] `DELETE` de la última categoría activa → 409; de una de dos → 204
- [x] Operar sobre `{tid}` del que no eres miembro → 403; categoría de otro tenant → 404
- [x] Crear un workspace nuevo lo deja con las 5 categorías legacy sembradas
- [x] Migración `0004` con seed idempotente de tenants existentes (verificación manual: [testing 24](../testing/24-triage-studio-categories_testing.md#migration-verification))
- [x] `/triage` **sin cambios** de comportamiento (sigue con el enum legacy) — cero regresión
- [x] `make check` verde; `docs/features/24-*` y `docs/testing/24-*`

> **Ajuste durante ejecución:** el slug se **normaliza** (trim + lowercase) antes de
> validar, así `"UPPER"`/`"  Returns "` → `returns` en vez de 422. Solo formas realmente
> inválidas (espacios internos, guiones, emoji, >50) devuelven 422.
```
