# Walkthrough de estudio — SQLAlchemy 2.x async (con este repo)

> Documento de estudio enfocado a entrevista. Aprende SQLAlchemy **leyendo el
> código real de este proyecto**: engine, sesión, modelos, queries,
> transacciones, relaciones (y la trampa del lazy-loading en async), Alembic y
> tests. Cada concepto apunta a un archivo concreto.
>
> Archivos: [db/base.py](../email_triage/db/base.py) ·
> [db/engine.py](../email_triage/db/engine.py) ·
> [db/models.py](../email_triage/db/models.py) ·
> [db/repos/](../email_triage/db/repos/) · [alembic/](../alembic/)

---

## 0. El mapa: cuatro capas

```
create_async_engine ──▶ async_sessionmaker ──▶ AsyncSession ──▶ ORM models
   (pool de conexiones)    (fábrica de sesiones)   (unit of work)   (tablas)
        engine.py                engine.py            repos/         models.py
```

- **Engine:** gestiona el pool de conexiones a Postgres. Uno por proceso.
- **Session:** una "unidad de trabajo" — acumula cambios y los manda en una
  transacción. Una por request (o por operación).
- **Models:** clases Python mapeadas a tablas (Declarative).
- **Repos:** aíslan el SQL; los handlers nunca escriben `select(...)`.

SQLAlchemy tiene dos niveles: **Core** (SQL expression language) y **ORM**
(objetos mapeados). Este repo usa el ORM, pero las queries 2.0 (`select(...)`)
son en realidad Core usado desde el ORM — por eso se sienten "SQL-like".

---

## 1. El engine y el pool — [db/engine.py](../email_triage/db/engine.py)

```python
_engine = create_async_engine(
    url,
    pool_size=5,         # conexiones mantenidas abiertas
    max_overflow=10,     # extra bajo demanda (pico = 15)
    pool_pre_ping=True,  # "SELECT 1" antes de usar → descarta conexiones muertas
    echo=False,          # True = loguea todo el SQL (útil para aprender)
)
```

Conceptos:

- **Pool de conexiones:** abrir una conexión TCP+auth a Postgres es caro
  (~ms). El pool las reutiliza. `pool_size=5` + `max_overflow=10` = hasta 15
  concurrentes; si pides más, esperas. Esto **debe** dimensionarse junto con los
  workers de gunicorn y el límite de conexiones de Postgres (Neon free ~100).
- **`pool_pre_ping`:** las DBs cloud cierran conexiones inactivas; sin el ping,
  la primera query tras una pausa fallaría con "connection closed". El ping
  detecta y reemplaza la conexión muerta de forma transparente.
- **Un engine por proceso:** crear engines es caro y cada uno tiene su pool. Por
  eso es un **global** (`_engine`), creado una vez en el lifespan
  ([main.py](../email_triage/main.py)) y dispuesto al apagar (`close_db` →
  `engine.dispose()`).
- **`create_async_engine` vs `create_engine`:** la variante async usa un driver
  async (asyncpg) y devuelve `AsyncEngine`/`AsyncSession`. Todo I/O se hace con
  `await`.

**`_parse_url`** ([engine.py:15](../email_triage/db/engine.py)) traduce la
sintaxis libpq (`?sslmode=require`, la que dan Neon/Render) al kwarg que entiende
asyncpg (`ssl="require"`). Detalle real: asyncpg no entiende `sslmode` como
query param — de ahí el parseo manual. (Interview: "¿por qué tu connection
string difiere entre psql y la app?" → driver distinto, params distintos.)

---

## 2. La sesión — el corazón del ORM

```python
# engine.py
_session_factory = async_sessionmaker(
    bind=_engine,
    class_=AsyncSession,
    expire_on_commit=False,   # ← clave en async, ver abajo
)
```

La **Session** implementa el patrón *Unit of Work* + *Identity Map*:

- **Unit of Work:** no escribes a la DB campo a campo. Modificas objetos Python
  (`tenant.api_key_hash = ...`), los acumulas, y la sesión calcula el SQL
  mínimo y lo manda junta en `flush`/`commit`.
- **Identity Map:** dentro de una sesión, una fila con un PK dado = **un único
  objeto Python**. Si pides dos veces el mismo `User`, obtienes la misma
  instancia (caché de sesión).

### `expire_on_commit=False` — el ajuste que evita un bug en async

Por defecto, tras `commit()` SQLAlchemy **expira** todos los objetos: el
siguiente acceso a cualquier atributo dispara un *reload* (un SELECT). En código
**sync** eso es transparente. En **async** es un desastre: ese reload implícito
es un I/O que ocurre fuera de un `await` → lanza `MissingGreenlet`. Poniendo
`expire_on_commit=False`, los objetos conservan sus valores tras el commit y
puedes leerlos sin tocar la DB. Por eso, p.ej., el callback de auth puede hacer
`return CallbackResponse(email=user.email, ...)` después de cerrar la
transacción. **Esto es una pregunta clásica de SQLAlchemy async.**

---

## 3. Los modelos — [db/models.py](../email_triage/db/models.py)

Estilo Declarative 2.0 con tipado:

```python
class Base(DeclarativeBase): pass           # base.py — metadata compartida

class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    memberships: Mapped[list[Membership]] = relationship(back_populates="user")
```

Qué enseña cada pieza:

- **`Mapped[X]` + `mapped_column(...)`:** el tipo Python (`Mapped[str]`) lo lee
  el type checker; `mapped_column` define la columna SQL. **`Mapped[str | None]`
  ↔ `nullable=True`** — el `| None` y el `nullable` deben concordar (pyright en
  estricto lo vigila).
- **`default` vs `server_default`** (¡pregunta de entrevista!):
  - `default=uuid.uuid4` → **Python-side**: SQLAlchemy llama la función al hacer
    flush y manda el valor en el INSERT. Por eso `tenant.id` existe **después de
    `flush()`**, no antes (lo usamos así para las API keys).
  - `server_default=func.now()` → **DB-side**: genera `DEFAULT now()` en el DDL;
    lo pone Postgres. `created_at` lo usa así (la verdad del tiempo es del
    servidor, no del cliente).
  - `onupdate=func.now()` en `updated_at` → SQLAlchemy lo setea en cada UPDATE.
- **`ForeignKey` + `ondelete`:** en `Membership`
  ([models.py:65](../email_triage/db/models.py)),
  `ForeignKey("users.id", ondelete="CASCADE")` → borrar un user borra sus
  memberships **en la DB** (no en la app). Es DDL.
- **PK compuesta:** `Membership` tiene `primary_key=True` en `user_id` **y**
  `tenant_id` → clave compuesta = many-to-many con payload (`role`). No hay
  columna `id`.
- **`relationship(back_populates=...)`:** define la navegación ORM
  (`user.memberships` ↔ `membership.user`). **Ojo:** declararla no la carga;
  ver §5.
- **Tipos:** `Uuid`, `String(n)`, `Text`, `Boolean`, `DateTime(timezone=True)`,
  `Float`, `Integer`, `SmallInteger`. `DateTime(timezone=True)` → `TIMESTAMPTZ`
  (siempre con tz en Postgres, evita el infierno de naive datetimes).

---

## 4. Queries 2.0 — `select()` + `scalar`/`scalars`

El estilo moderno (2.0) es uniforme: construyes un `select()` y lo ejecutas.

```python
# repos/users.py
async def get_by_email(self, session, email) -> User | None:
    return await session.scalar(select(User).where(User.email == email))
```

- **`select(User).where(User.email == email)`:** `User.email == email` no compara
  en Python — construye una **expresión SQL** (`users.email = :email`). Esa es la
  magia de Core: los atributos de columna sobrecargan los operadores.
- **`session.scalar(stmt)`** → la **primera columna de la primera fila** (aquí, un
  `User` o `None`). Ideal para "traer uno".
- **`session.scalars(stmt)`** → un iterable de la primera columna; `.all()` →
  lista. Para "traer varios".
- **`session.get(User, pk)`** ([deps.py:166](../email_triage/deps.py)) → atajo
  para **buscar por PK** que además **mira el identity map primero** (puede
  evitar el SELECT si ya está en sesión). Úsalo cuando tienes el PK; `select`
  cuando filtras por otra cosa.

`scalar` vs `execute`: `execute(stmt)` devuelve `Result` con filas/tuplas
(útil al seleccionar varias columnas); `scalar(s)` es el atajo cuando
seleccionas una entidad/columna. Este repo casi siempre quiere entidades →
`scalar(s)`.

---

## 5. Relaciones y la TRAMPA del lazy-loading en async ⚠️

Este es **el** tema async de SQLAlchemy y el repo lo resuelve de la forma
correcta… evitándolo.

Los modelos **declaran** relaciones (`Tenant.memberships`, `User.memberships`),
pero búscalas en el código de runtime: **nunca se accede a ellas**. Todo se
consulta explícito (`UserRepo().get_membership(session, user_id)` hace su propio
`select(Membership).where(...)`).

¿Por qué? Porque en **async**, acceder a una relación no cargada
(`tenant.memberships`) dispararía un **lazy load**: un SELECT implícito. En sync
eso "just works"; en async **lanza `MissingGreenlet`** porque el I/O ocurre
fuera de un `await`. Tienes tres salidas:

1. **Eager loading explícito:** `select(Tenant).options(selectinload(Tenant.memberships))`
   → carga las memberships en una segunda query (o `joinedload` con un JOIN).
2. **`AsyncAttrs` / `await obj.awaitable_attrs.memberships`** → carga bajo demanda
   pero con `await`.
3. **No navegar relaciones; hacer queries explícitas** ← lo que hace este repo.

La opción 3 es deliberada y defendible: queries predecibles, sin N+1 sorpresa,
sin sustos de greenlet. **Interview gold:** *"¿qué pasa si accedes a una
relación lazy en SQLAlchemy async?"* → `MissingGreenlet`; lo evitas con
`selectinload`/`joinedload` o consultando explícito.

> **N+1:** si cargas 100 tenants y luego, en un loop, accedes a
> `tenant.memberships` de cada uno, son 1 + 100 queries. `selectinload` lo
> convierte en 2 queries (una para tenants, otra `WHERE tenant_id IN (...)`).

---

## 6. Transacciones, `flush` vs `commit` — [repos/](../email_triage/db/repos/)

```python
# auth.py — escritura
async with factory() as session, session.begin():
    user = await UserRepo().create_with_password(session, ...)   # session.add + flush
    tenant = await TenantRepo().create_personal(session, ...)    # flush → tenant.id existe
    plaintext_key, key_hash = issue_api_key(tenant.id)
    tenant.api_key_hash = key_hash
    await TenantRepo().add_member(session, user.id, tenant.id, "owner")
# ← al salir del `with` sin excepción: COMMIT. Con excepción: ROLLBACK.
```

- **`session.add(obj)`:** marca el objeto como "pendiente de insertar" (aún no
  hay SQL).
- **`flush()`:** **manda el INSERT/UPDATE a la DB dentro de la transacción**, pero
  **no hace commit**. Efecto clave: rellena los defaults Python-side y los PKs.
  Por eso `create_personal` hace `flush()` y *luego* `tenant.id` ya existe — el
  truco que usan las API keys.
- **`commit()`:** confirma la transacción (persistente, visible a otros). Aquí lo
  hace implícitamente `async with session.begin()` al salir.
- **`session.begin()`:** abre una transacción explícita; el bloque hace
  **commit al éxito, rollback ante excepción**. Es el patrón de escritura.
- **Lecturas** (`get_by_email`, etc.): usan solo `async with factory() as
  session:` sin `begin()` — SQLAlchemy auto-inicia una transacción de lectura y
  la sesión se cierra al salir. No hace falta commit para leer.

Mental model: **flush = "escribe a la DB pero aún puedo deshacer"; commit =
"hazlo permanente".** flush para obtener IDs / validar constraints antes de
seguir; commit para cerrar.

---

## 7. El patrón Repository — [db/repos/](../email_triage/db/repos/)

Cada repo es una clase con métodos que encapsulan queries
(`UserRepo.get_by_email`, `TenantRepo.create_personal`). Por qué importa:

- **Los handlers no saben SQL.** `routers/auth.py` llama
  `UserRepo().get_by_email(session, email)`, no `select(User)...`. Cambias el
  esquema en un solo sitio.
- **La sesión se inyecta** al método (no la crea el repo). Así la *transacción*
  la controla el llamador (puede agrupar varias operaciones de varios repos en
  una sola transacción — justo lo que hace signup).
- **Testeable:** en los tests de auth se mockean los repos enteros; en los de DB
  se usan contra una DB real (sqlite). Ver §9.

`persist_triage_log` / `persist_eval_run` añaden un matiz: son **fire-and-forget**
con su propia sesión y `try/except` que traga la excepción — la persistencia
nunca rompe la respuesta al usuario, y es no-op si no hay DB.

---

## 8. Alembic — migraciones — [alembic/](../alembic/)

El ORM describe el estado *deseado*; Alembic lleva la DB de un estado a otro.

- **`env.py`** ([alembic/env.py](../alembic/env.py)) está cableado para **async**:
  `create_async_engine` + `connection.run_sync(_run_sync_migrations)`. ¿Por qué
  `run_sync`? El motor de migraciones de Alembic es síncrono; `run_sync` lo corre
  dentro de la conexión async tendiendo el puente. Importa `Base.metadata` para
  que el autogenerate sepa el estado deseado.
- **Autogenerate:** `alembic revision --autogenerate -m "..."` compara
  `Base.metadata` (tus modelos) con la DB y **propone** el diff (create_table,
  add_column…). Genera la `0001`.
- **Lo que autogenerate NO detecta bien** (interview): renombres de columna (los
  ve como drop+add), cambios de tipo sutiles, constraints con nombre, datos.
  **Siempre revisa la migración generada.**
- **Migración de datos a mano:** la `0002`
  ([alembic/versions/0002](../alembic/versions/0002_users_and_tenants.py)) es el
  ejemplo de oro: separa User de Tenant **preservando los UUIDs** (para no romper
  el FK de `triage_logs`) con `op.execute("INSERT ... SELECT ...")` en SQL crudo.
  Patrón: añadir columnas *nullable* → backfill con SQL → poner `NOT NULL`. El
  `downgrade` lanza `NotImplementedError` — decisión honesta (restaurar backup).
- **`op.*`:** `create_table`, `add_column`, `alter_column`, `create_unique_constraint`,
  `execute` — la API imperativa de DDL.

Flujo: `make db-revision MSG="..."` (genera) → revisar → `make db-migrate`
(aplica `alembic upgrade head`).

---

## 9. Tests — DB real en memoria — [tests/conftest.py](../tests/conftest.py)

```python
@pytest.fixture()
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)   # crea el esquema desde los modelos
    factory = async_sessionmaker(bind=engine, ...)
    db_engine_module._session_factory = factory          # inyecta en el global
    async with factory() as session:
        yield session
    ...
```

Conceptos:

- **sqlite `:memory:` + `aiosqlite`:** DB real (no mock) pero efímera y rapidísima.
  Los tests de `test_db.py` ejercitan SQL de verdad sin Postgres.
- **`Base.metadata.create_all`:** crea todas las tablas desde los modelos (sin
  Alembic) — perfecto para tests. En prod usas Alembic; en tests, `create_all`.
- **Diferencias de dialecto (gotcha):** sqlite **no fuerza FKs** por defecto, así
  que en un test puedes insertar `triage_logs.tenant_id` sin un tenant real
  (lo aprovechamos en `test_insert_triage_log`). Postgres sí los forzaría →
  algunos bugs solo aparecen en prod. Tenlo presente.

---

## 10. Preguntas típicas de entrevista

**P: ¿`flush` vs `commit`?**
flush manda el SQL a la DB dentro de la transacción (rellena PKs, valida
constraints) pero es reversible; commit confirma y cierra la transacción.

**P: ¿Qué hace `expire_on_commit=False` y por qué en async?**
Evita que los objetos se expiren tras commit; sin él, leer un atributo tras el
commit dispara un reload implícito que en async revienta con `MissingGreenlet`.

**P: ¿Qué pasa al acceder a una relación lazy en async?**
Lanza `MissingGreenlet`. Se resuelve con `selectinload`/`joinedload` (eager) o
`await obj.awaitable_attrs.x`, o consultando explícito.

**P: ¿`default` vs `server_default`?**
default = Python-side (al flush); server_default = DDL `DEFAULT` (lo pone la DB).
created_at usa server_default; el UUID id usa default.

**P: ¿Por qué un solo engine y muchas sesiones?**
El engine posee el pool de conexiones (caro, global, uno por proceso); la sesión
es una unidad de trabajo barata y de vida corta (una por request).

**P: ¿`session.get` vs `select().where(PK==...)`?**
`get` busca por PK y consulta primero el identity map (puede evitar el SELECT);
`select` es para filtrar por cualquier criterio.

**P: ¿Qué no detecta el autogenerate de Alembic?**
Renombres (los ve como drop+add), datos, algunos cambios de tipo/constraint.
Siempre revisar.

**P: ¿N+1 y cómo lo evitas?**
Acceder a una relación por fila en un loop = 1+N queries; `selectinload` lo
colapsa a 2 (una con `IN (...)`).

---

## 11. Ejercicios prácticos (para aprender haciendo, en este repo)

Ordenados de menor a mayor. Tras cada uno: `make check`.

1. **Ver el SQL:** pon `echo=True` en `create_async_engine`
   ([engine.py:32](../email_triage/db/engine.py)), corre `uv run pytest
   tests/test_db.py -s` y lee el SQL que emite cada `flush`/`commit`.
2. **Una query nueva:** añade `TriageLogRepo.count_by_category(session, tenant_id)`
   que devuelva `dict[str, int]` usando `select(TriageLog.category,
   func.count()).where(...).group_by(TriageLog.category)`. Test con `db_session`.
3. **Eager loading:** escribe `select(Tenant).options(selectinload(Tenant.memberships))`
   en un test y observa (con `echo=True`) las dos queries vs el `MissingGreenlet`
   si accedes a `.memberships` sin el `selectinload`.
4. **Una columna + migración:** añade `TriageLog.locale: Mapped[str | None]`,
   corre `make db-revision MSG="add locale"`, **lee** la migración generada, y
   `make db-migrate` contra tu DB local (`make db-up` primero).
5. **Una transacción que falla:** en un test, dentro de `session.begin()`, inserta
   y luego lanza una excepción; verifica que **nada** quedó persistido (rollback).

---

## 12. Cómo encaja con el resto

- La inyección de la sesión vía el factory global se conecta con el lifespan de
  FastAPI ([main.py](../email_triage/main.py)) y los deps.
- El patrón repo + transacción explícita es lo que permite el flujo signup
  (User + Tenant + Membership atómicos) — ver
  [WALKTHROUGH-api-keys.md](WALKTHROUGH-api-keys.md) §7.
- La migración `0002` es la pieza que el [WALKTHROUGH.md](WALKTHROUGH.md) §2.13
  resalta como ejemplo de data-migration que preserva FKs.
