# 48. CI de tests (unit/e2e) + escaneo de seguridad (Level 4)

**Status:** 🚧 implemented (en rama `feat/add_CI_for_testing`, pending human review/merge)
**Estimate:** ~2 hrs
**Depends on:** nada del código de la app. Infra externa: GitHub Actions (ya en uso por Plan 47) y, para Dependabot, que esté habilitado en el repo (lo hace el humano — ver §Setup).
**Tipo:** tooling / CI. No toca la superficie pública (`/triage`, `/triage/stream`, `/health`). Cambia `tests/conftest.py`, `pyproject.toml`, `uv.lock`, `Makefile` y agrega workflows.

> **Nota de rama.** La implementación vive en `feat/add_CI_for_testing` (commits
> `991616f` CI + `e572ac8` bump de deps). Este exec-plan se escribió **después** de
> implementar para dejar registrada la decisión (el protocolo de AGENTS.md §3 pide el
> plan *antes*; acá se documenta retroactivamente porque se saltó ese paso). Si esta rama
> (`feat/frontend_CI`) mergea antes, el doc llega a `main` igual; el número 48 no colisiona
> con nada de la otra rama.

## Intent

Dos objetivos independientes en CI:

1. **Correr los tests en cada push/PR**, separados en **unit** (rápidos, aislados) y
   **e2e** (ejercen la app completa vía `TestClient` o una DB real). Hasta ahora los 260
   tests solo corrían localmente (`make test`); un PR podía romperlos sin señal.
2. **Seguridad "Level 4": escaneo automático de vulnerabilidades + SBOM.** Integrar
   `pip-audit` para atrapar CVEs conocidas antes de producción, generar un **SBOM
   CycloneDX** para trazar cada componente del artefacto desplegado, y **Dependabot** para
   que abra PRs de parches automáticamente.

## Scope

- **Incluido:** workflow de tests (matrix unit/e2e), workflow de seguridad (pip-audit +
  SBOM), `dependabot.yml`, split automático unit/e2e por fixtures, targets de Makefile que
  espejan el CI, y la **remediación de las 10 CVEs** que el primer `pip-audit` encontró.
- **Fuera de alcance:** frontend (→ [Plan 49](49-frontend-ci-testing.md)), coverage
  gates, tests contra Postgres real (los e2e usan SQLite in-memory), firmar/attestar el
  SBOM, y convertir el audit en required check bloqueante (queda a decisión del humano).

## Split unit vs e2e — la decisión de diseño central

El repo tiene 260 tests en 26 archivos, **sin marcadores** y con muchos archivos "mixtos"
(lógica pura + tests que manejan la app). Etiquetar a mano los 26 archivos es frágil y se
desactualiza con cada test nuevo. En su lugar, **auto-marcado por fixture** en
`tests/conftest.py`:

```python
_E2E_FIXTURE_RE = re.compile(r"client$|session$|engine$")

def pytest_collection_modifyitems(items):
    for item in items:
        is_e2e = any(_E2E_FIXTURE_RE.search(n) for n in getattr(item, "fixturenames", ()))
        item.add_marker(pytest.mark.e2e if is_e2e else pytest.mark.unit)
```

Un test es **e2e** si pide (directa o transitivamente) cualquier fixture que termine en
`client` (el `client`/`streaming_client` compartido, o uno local de router como
`auth_client`), `session` o `engine`. Todo lo demás es **unit**. La regla se auto-mantiene:
un test nuevo se clasifica por lo que usa, sin bookkeeping por archivo.

Split resultante (validado corriendo ambos offline): **154 unit** (~7 s) · **106 e2e**
(~19 s). Ambos verdes sin red ni servicios externos (el LLM está mockeado vía
`dependency_overrides`, la DB es `sqlite+aiosqlite:///:memory:`).

Registrado en `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
addopts = "--strict-markers"   # un marker mal escrito es error, no warning
markers = ["unit: ...", "e2e: ..."]
```

## Concrete changes

| File | Change |
|---|---|
| `.github/workflows/tests.yml` | Nuevo. Matrix `suite: [unit, e2e]`, `fail-fast: false`, `astral-sh/setup-uv@v6` con cache, `uv sync --frozen --all-extras`, `uv run pytest -m ${{ matrix.suite }}`. `concurrency` con cancel-in-progress. |
| `.github/workflows/security.yml` | Nuevo. Job `audit` (`uv export` → `uvx pip-audit -r … --strict`) + job `sbom` (`uvx cyclonedx-py requirements` → upload artifact). Triggers: push, PR y **cron semanal** (lunes 06:00 UTC) para CVEs nuevas sobre deps sin cambios. |
| `.github/dependabot.yml` | Nuevo. Ecosistemas `uv` (`/`), `npm` (`/frontend`) y `github-actions` (`/`), semanales, con minor/patch agrupados. |
| `tests/conftest.py` | `import re` + hook `pytest_collection_modifyitems` (auto-marcado). |
| `pyproject.toml` | `addopts = "--strict-markers"` + `markers`. Bumps de deps (ver §Remediación). |
| `Makefile` | Targets `test-unit`, `test-e2e`, `audit`, `sbom` (espejan el CI). |
| `.gitignore` | `sbom.json` (artefacto generado). |
| `tests/test_auth.py`, `tests/test_gmail_connect.py` | Anotación de helpers `-> httpx.Response` → `httpx2.Response` (ver §Remediación). |

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Split unit/e2e por **auto-marcado por fixture** | `pytestmark` por archivo · marcar 26 archivos a mano | Self-maintaining; un test nuevo se clasifica solo por lo que usa. Sin bookkeeping. |
| Matrix `[unit, e2e]` con `fail-fast: false` | Dos jobs escritos a mano · un solo `pytest` | DRY y ambos suites reportan aunque uno falle. |
| **pip-audit** | `safety` | pip-audit integra con `uv export`, sin cuenta/token; base PyPI Advisory + OSV. |
| **CycloneDX** (`cyclonedx-py`) | Syft | Estándar SBOM ampliamente soportado; `cyclonedx-py requirements` consume el export de uv directo. |
| **Dependabot** | Renovate | Nativo de GitHub, sin app externa ni config compleja; suficiente para este repo. |
| `uv export --frozen --no-dev --no-emit-project --no-hashes` como fuente para audit + SBOM | Auditar el venv instalado | Audita el árbol **transitivo** resuelto de prod (no dev), sin el propio paquete, de forma determinística desde `uv.lock`. |
| `pip-audit --strict` (falla el job ante CVE) | Modo reporte-only | Es el punto de "Level 4": frenar vulnerabilidades antes de prod. El humano puede relajarlo si molesta. |
| Cron semanal en el audit | Solo en push/PR | Atrapa CVEs **divulgadas después** contra deps que no cambiaron. |

## Remediación de deps (primer run del audit)

El primer `pip-audit` encontró **10 CVEs en 5 paquetes**. Bumps aplicados (suite completa
+ pyright strict verdes después):

| Paquete | 48.0.0 → | Nota |
|---|---|---|
| cryptography | 50.0.0 | directo |
| starlette | 1.2.0 → 1.3.1 | transitiva (fastapi) |
| python-multipart | 0.0.30 → 0.0.32 | transitiva |
| pydantic-settings | 2.14.1 → 2.15.0 | directo |
| pydantic-ai-slim | 1.104.0 → **1.107.5** | acotado a `<2` |

Dos decisiones no obvias:

- **pydantic-ai acotado a `<2`.** El floor `>=1.106.0` resolvía a **2.31.0** (major nuevo).
  Como los tests **mockean el LLM** y no ejercen `services/llm.py` real, un major podía
  romper en prod sin que el CI lo viera. Se fijó `>=1.106.0,<2` (→ 1.107.5), que ya trae el
  fix del CVE-2026-54249. Revisar migración a v2 por separado.
- **httpx2 en dos tests.** starlette ≥1.3.1 (mínimo que exige el CVE) migró su `TestClient`
  a `httpx2` (`import httpx2 as httpx` interno). Eso rompía pyright strict en dos helpers
  anotados `-> httpx.Response`. Se corrigió la anotación a `httpx2.Response` (lo que
  `TestClient` realmente devuelve ahora) en `test_auth.py` y `test_gmail_connect.py`, con un
  comentario que explica el porqué. El código de la app sigue en httpx (v1).

## Risks / Open questions

- **`pydantic-ai` congelado en 1.x.** Deuda técnica consciente: la migración a v2 necesita
  su propio esfuerzo (y cubrir `services/llm.py`, que hoy los tests mockean).
- **`httpx2` es transitional.** Si el ecosistema lo renombra a httpx v2, las anotaciones
  `httpx2.Response` habrá que revisitarlas.
- **e2e sobre SQLite, no Postgres.** Rápido y sin infra, pero no cubre comportamiento
  específico de asyncpg/Postgres. Aceptable para este nivel; un job con service-container de
  Postgres queda como mejora futura.
- **Audit como required check.** Hoy falla el job pero no bloquea el merge salvo que se
  configure como required. Decisión del humano.

## Actualización — Dependabot: version-updates → security-only

Al mergear a `main`, `dependabot.yml` (version-updates) hizo su primera corrida y abrió ~13
PRs actualizando **toda** dependencia con versión más nueva, hubiera o no vulnerabilidad
(TypeScript 7, @types/node 26, structlog 26, etc.). Eso es higiene de deps, **no** seguridad,
y no era lo pedido (Level 4 = *detectar y parchear vulnerabilidades*, no "actualizar todo").

**Decisión (con el humano): quitar `dependabot.yml`** y quedarse con el enfoque puramente de
seguridad, cero ruido:
- **Detección:** `security.yml` (pip-audit) marca en rojo cualquier PR con un CVE conocido.
- **Parcheo automático:** *Dependabot **security** updates* (setting del repo, no un YAML) abre
  PR **solo** cuando hay una vulnerabilidad con fix — independiente de `dependabot.yml`.

Al mergear la remoción, Dependabot **cierra solo** los PRs de version-updates que había abierto.

## Setup (humano — el agente no puede)

1. Habilitar **Dependabot alerts** + **Dependabot security updates** en el repo
   (Settings → Code security). Eso cubre el parcheo de vulnerabilidades sin `dependabot.yml`.
2. Cerrar (o dejar que Dependabot auto-cierre al mergear esta rama) los PRs de version-updates
   ya abiertos — no son CVEs.
3. (Opcional) Marcar `tests` y `security/audit` como **required status checks** en la
   protección de rama de `main`.

## Testing

- **Estático (hecho):** los 3 YAML parsean OK; `uv export` produce el árbol transitivo;
  `pip-audit` y `cyclonedx-py` corren localmente vía `uvx`.
- **Funcional (hecho local):** `uv run pytest -m unit` → 154 passed; `-m e2e` → 106 passed;
  `pip-audit` post-bump → *No known vulnerabilities found*; SBOM → CycloneDX 1.6, 98 componentes; `pyright` → 0 errores.
- **Post-merge (humano):** verificar que los checks aparecen en un PR y que el artifact
  `sbom-cyclonedx` queda adjunto al run de seguridad.

## Done when

- [x] `tests.yml`, `security.yml`, `dependabot.yml` creados y parseando.
- [x] Split unit/e2e auto-marcado; ambos suites verdes offline.
- [x] `pip-audit` sin vulnerabilidades tras la remediación.
- [ ] `docs/features/48-*.md` + `docs/testing/48-*_testing.md` (post-merge).
- [x] Dependabot repensado: version-updates removido; queda pip-audit + Dependabot **security** updates (ver §Actualización).
- [ ] Humano habilita Dependabot security updates y (opcional) required checks.
