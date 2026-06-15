# Walkthrough de estudio — API keys por tenant (estilo Stripe)

> Documento de estudio enfocado a entrevista. Explica **el problema, la teoría
> y la implementación** del esquema de API keys que reemplazó al de bcrypt, de
> modo que puedas reconstruirlo de memoria y defender cada decisión.
>
> Cambios verificados al escribir esto: `uv run pytest` → **52/52** ·
> `uv run pyright` → **0 errores** · `uv run ruff check` → limpio.
>
> Archivos clave: [auth/api_key.py](../email_triage/auth/api_key.py) ·
> [deps.py](../email_triage/deps.py) ·
> [routers/auth.py](../email_triage/routers/auth.py) ·
> [routers/triage.py](../email_triage/routers/triage.py)

---

## 0. El problema en una frase

**Autenticar ≠ identificar.** El sistema anterior contestaba "¿esta key es
válida?" (sí/no) pero no "¿de quién es?". En un SaaS multi-tenant eso es
insuficiente: necesitas saber **qué tenant** hace cada request para atribuir
uso, facturar, aislar datos y limitar por cliente. Arreglar eso, además,
destrabó dos problemas de seguridad y rendimiento que venían de regalo.

---

## 1. Qué estaba mal (el "antes")

```python
# deps.py — versión anterior (resumida)
async def _check_key_against_db(api_key: str) -> bool:
    pairs = await TenantRepo().all_key_hashes(session)   # TODOS los hashes
    for _tenant_id, stored_hash in pairs:                # escaneo lineal
        if await asyncio.to_thread(bcrypt.checkpw, key, stored_hash):
            return True                                  # descarta el tenant_id
    return False
```

Tres defectos encadenados:

1. **Devuelve `bool`, descarta el `tenant_id`.** El `for` *tiene* el
   `_tenant_id` que matchea y lo tira. Consecuencia aguas abajo:
   `persist_triage_log` nunca recibía tenant → **`triage_logs.tenant_id` era
   siempre `NULL`** → la analítica per-tenant (el motivo declarado de la tabla)
   y su índice `ix_triage_logs_tenant_id` eran letra muerta. Esto es **C1**.

2. **O(N·bcrypt): vector de DoS.** Cada key (incluso inválida) recorría
   *todos* los tenants ejecutando bcrypt (~250 ms cada uno). Con 100 tenants,
   una sola key inválida costaba ~25 s de CPU. Un atacante mandando keys
   aleatorias quema CPU **linealmente con tu número de clientes**. Esto es
   **S2**.

3. **bcrypt es la herramienta equivocada para este input.** (la causa raíz —
   **C2**). Ver siguiente sección, es *el* concepto.

---

## 2. El concepto central: por qué bcrypt es correcto para passwords y
## equivocado para API keys

Esta distinción es la que demuestra criterio en una entrevista.

| | Password humana | API key |
|---|---|---|
| Entropía | Baja (~30 bits; "Verano2024!") | Alta (256 bits, aleatoria) |
| Espacio de búsqueda | Pequeño → **se puede fuerza-brutear** | Astronómico → fuerza bruta imposible |
| Defensa necesaria | Hash **lento** (bcrypt/argon2) para que cada intento cueste | Hash **rápido** basta; el coste ya lo pone la entropía |
| ¿Buscable? | No importa (lookup por username) | **Crítico** (el lookup ES la key) |

**El argumento de un párrafo:** bcrypt es deliberadamente lento (un "work
factor" configurable) para que crackear un password robado cueste millones de
operaciones. Una API key de `secrets.token_urlsafe(32)` tiene 256 bits de
entropía: para adivinarla harías 2²⁵⁶ intentos — más que átomos en el universo
observable. Ralentizar *cada verificación* para frenar un ataque que **ya es
imposible** solo te perjudica a ti (250 ms por request). Y como el hash bcrypt
incluye un salt aleatorio, **no es determinista** → no puedes indexarlo ni
buscar por él, lo que te obliga al escaneo O(N). Para tokens de alta entropía
lo correcto es un hash **rápido y determinista** (sha256): seguro porque el
preimagen es impredecible, y buscable porque es determinista.

> Frase para la entrevista: *"bcrypt protege secretos de baja entropía
> haciéndolos caros de probar; una API key ya es imposible de adivinar por su
> entropía, así que bcrypt solo añade latencia y, peor, rompe la búsqueda. Para
> tokens uso sha256 determinista, que me da lookup O(1) y sigue siendo seguro
> porque no se puede invertir."*

---

## 3. El diseño: keys auto-localizables (estilo Stripe/GitHub)

La idea clave para pasar de O(N) a O(1): **que la key presentada diga a qué fila
ir a buscar**, sin escanear. La key lleva el `tenant_id` en claro:

```
et_<tenant_id>_<secret>
│   │           └── secrets.token_urlsafe(32)  (256 bits, la parte secreta)
│   └── UUID del tenant  (sirve para LOCALIZAR la fila, no es secreto)
└── prefijo de producto (identifica el tipo de credencial)
```

Esto imita a Stripe (`sk_live_...`), GitHub (`ghp_...`), etc. El prefijo
público es una práctica real con beneficios concretos:

- **Lookup O(1):** parseas el `tenant_id`, traes **una** fila, comparas un hash.
- **Detección de secretos filtrados:** un prefijo fijo (`et_`) permite que
  escáneres (GitHub secret scanning, tu propio CI) detecten keys pegadas por
  error en repos.
- **Telemetría/UX:** puedes mostrar/loguear el prefijo sin revelar el secreto.

**Decisión de diseño que sabrás defender:** embeber el `tenant_id` (un UUID)
expone *su propio* id al cliente. Es aceptable (no es secreto), y a cambio te
da el lookup O(1) sin una tabla extra. La alternativa "más opaca" (Stripe) es
un `key_id` aleatorio separado del tenant; lo mencionas como evolución si te
preguntan por minimizar fugas de información.

### El truco de parseo (detalle fino que impresiona)

```python
parts = key.split("_", 2)   # maxsplit=2 → exactamente 3 trozos
```

El alfabeto de `token_urlsafe` incluye `_`, así que el secreto **puede tener
guiones bajos**. ¿Por qué funciona entonces? Porque un **UUID solo usa guiones
(`-`), nunca `_`**. Con `maxsplit=2` obtienes `["et", "<uuid>", "<resto>"]` y el
"resto" es el secreto completo aunque contenga `_`. Es robusto por construcción.

Implementación: [auth/api_key.py](../email_triage/auth/api_key.py).

---

## 4. Verificación: sha256 + comparación en tiempo constante

```python
# auth/api_key.py
def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()

def secret_matches(secret: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(secret), stored_hash)
```

Dos conceptos de entrevista aquí:

**a) ¿Por qué guardar el hash y no la key?** Si te roban la base de datos, los
hashes sha256 no son reversibles (preimagen de 256 bits). Nadie puede
reconstruir las keys desde la DB. Guardar el plaintext sería como guardar
passwords en claro.

**b) ¿Por qué `hmac.compare_digest` y no `==`?** Para evitar **timing
attacks**. Una comparación de strings normal (`==`) hace short-circuit en el
primer byte distinto: cuanto antes difiere, antes retorna. Midiendo esos
nanosegundos un atacante puede ir adivinando el hash byte a byte.
`compare_digest` compara en **tiempo constante** (siempre recorre todo),
eliminando el canal lateral. (En la práctica, aquí comparamos *hashes* de
secretos de alta entropía, así que el riesgo es bajo — pero es el reflejo
correcto y lo van a valorar que lo tengas.)

> Nota: no se usa salt porque el secreto ya es único y de alta entropía. El
> salt sirve para que dos passwords iguales no produzcan el mismo hash y para
> frenar rainbow tables; ninguna de esas preocupaciones aplica a un token
> aleatorio de 256 bits.

---

## 5. El flujo de verificación, paso a paso

[deps.py → `verify_api_key`](../email_triage/deps.py):

```
X-API-Key: et_<uuid>_<secret>
        │
        ├─ ¿sin DATABASE_URL? ──► comparar con settings.api_key (key estática,
        │                          dev/tests) → TenantContext(tenant_id=None)
        │
        ├─ cache hit (sha256(key), TTL 60s) ──► usar tenant_id cacheado
        │
        └─ cache miss ──► _resolve_tenant:
                            1. parse_api_key  → (tenant_id, secret)  [o 403]
                            2. get_by_id(tenant_id)  → 1 fila        [o 403]
                            3. secret_matches(secret, hash)          [o 403]
                            → cachear (tenant_id, now+60s)
        │
        └─► devuelve TenantContext(tenant_id)  →  el handler lo usa
```

El handler de `/triage` ahora recibe el tenant y lo propaga al log:

```python
# routers/triage.py
async def triage(..., tenant: TenantDep, ...):
    ...
    background_tasks.add_task(persist_triage_log, ..., tenant.tenant_id)
```

Con eso, **C1 queda cerrado**: `triage_logs.tenant_id` se llena de verdad y la
analítica per-tenant existe.

### El `TenantContext` y el modo sin DB

```python
@dataclass(frozen=True)
class TenantContext:
    tenant_id: uuid.UUID | None   # None en el fallback estático (dev/tests)
```

Devolver un objeto (no un `bool` ni un `UUID` pelado) es la misma idea que el
`SessionContext` del flujo JWT: transporta identidad para que el resto del
código no tenga que volver a consultarla. El `tenant_id` opcional preserva el
modo "sin DB" que usan los tests (key estática compartida, sin tenant real).

---

## 6. Cache e invalidación (el detalle que separa junior de senior)

```python
_key_cache: dict[str, tuple[uuid.UUID | None, float]] = {}  # sha256(key) → (tenant_id, exp)
_KEY_CACHE_TTL = 60.0
_KEY_CACHE_MAX = 10_000
```

- **Por qué cachear:** aunque sha256 es rápido, evitas el round-trip a la DB en
  cada request. Se cachea el *resultado de verificación* (el `tenant_id`), no
  datos mutables del tenant — el `tenant_id` de una key **nunca cambia**, así
  que cachearlo es seguro.
- **Invalidación en rotación (arregla S4):** al rotar la key, la vieja debe
  dejar de funcionar. Por eso `rotate_key` llama a `invalidate_api_key_cache()`.
  **Caveat honesto que debes mencionar:** el cache es **por proceso**; con N
  workers de gunicorn hay N caches, y una key rotada puede sobrevivir hasta el
  TTL en otros workers. La solución de producción es un store compartido
  (Redis) → revocación instantánea en toda la flota. *Saber nombrar la
  limitación vale más que ocultarla.*
- **Cota de memoria (mitiga parte de S2):** un atacante podría mandar muchas
  keys de formato válido pero tenant inexistente para inflar el cache. El
  `_KEY_CACHE_MAX` lo acota groseramente; un **LRU** real (`functools.lru_cache`
  o `cachetools.TTLCache`) sería la elección de producción — lo dices como
  mejora.

---

## 7. Emisión de keys — y un efecto colateral bonito

Como sha256 es instantáneo (vs. ~250 ms de bcrypt), la emisión de la key se
**simplifica**: el código anterior pre-computaba el hash bcrypt *fuera* de la
transacción para no tener el pool bloqueado 250 ms. Con sha256 eso ya no hace
falta — la key se emite dentro de la fase de escritura, justo cuando ya existe
el `tenant.id` que se embebe en ella:

```python
# routers/auth.py — signup (y análogo en callback y rotate-key)
tenant = await TenantRepo().create_personal(session, workspace_name)  # flush → id
plaintext_key, key_hash = issue_api_key(tenant.id)
tenant.api_key_hash = key_hash
```

Nota: el **password** sí sigue con bcrypt y fuera de la transacción — porque un
password *sí* es de baja entropía y *sí* necesita el hash lento. Ese contraste
(bcrypt para password, sha256 para key, en el mismo archivo) es justo lo que
demuestra que entiendes *por qué* cada uno.

### ¿Hace falta migración de DB?

No hay cambio de esquema: `api_key_hash` es `TEXT` y el sha256 hex (64 chars)
cabe igual. Pero **las keys emitidas con el esquema bcrypt anterior dejan de ser
válidas** (no se pueden convertir sin el plaintext). Como no hay usuarios reales
aún, basta con re-emitir (`/auth/rotate-key`). En un sistema con tráfico harías
una migración **dual-read**: aceptar ambos formatos durante una ventana,
re-emitir keys, y luego retirar el camino viejo.

---

## 8. Preguntas típicas de entrevista (y respuestas)

**P: ¿Por qué no un JWT como API key para máquinas?**
Un JWT es *self-contained* y no revocable sin una blocklist; para una
credencial de larga vida que el cliente guarda, quieres poder **revocarla al
instante** (rotación). Una key opaca con lookup en DB se revoca borrando/rotando
la fila. JWT brilla para sesiones cortas de usuario (lo que sí usamos en
`/auth/login`), no para credenciales de servicio persistentes.

**P: ¿No es peligroso meter el `tenant_id` en la key?**
El `tenant_id` no es un secreto — es el id del propio dueño de la key. Lo
secreto es la parte `<secret>`. A cambio obtienes lookup O(1) sin tabla extra.
Si quisiera minimizar fuga de info, usaría un `key_id` aleatorio separado
(modelo Stripe) a costa de una columna/índice más.

**P: ¿Qué pasa si te roban la base de datos?**
Solo hay sha256 de secretos de alta entropía: irreversibles. El atacante no
recupera ninguna key utilizable. (Compáralo con guardar plaintext o con un
cifrado reversible, que sí serían catastróficos.)

**P: ¿Cómo escalas el rate-limit por tenant ahora?**
Antes solo podías limitar por IP (no sabías el tenant). Ahora que
`verify_api_key` devuelve el tenant, puedes cambiar la `key_func` de slowapi
para limitar por `tenant_id` — cuotas por cliente/plan en vez de por IP. Es la
puerta que abre haber resuelto la identidad.

**P: ¿Constant-time comparison de verdad importa aquí?**
Es defensa en profundidad: comparamos hashes de secretos de alta entropía, así
que el riesgo práctico de timing es bajo, pero `hmac.compare_digest` es gratis y
es el hábito correcto. Donde *sí* es crítico es comparando secretos de baja
entropía directamente.

**P: ¿Cómo soportarías rotación sin downtime?**
Permitir N keys activas por tenant (tabla `api_keys` con varias filas en vez de
una columna), emitir la nueva, dar una ventana de gracia, revocar la vieja.
Hoy es 1 key por tenant (columna `api_key_hash`); evolucionar a tabla es el
siguiente paso natural.

---

## 9. Guía de reproducción (de cero)

1. **El módulo de keys** ([auth/api_key.py](../email_triage/auth/api_key.py)):
   `issue_api_key`, `hash_secret`, `parse_api_key`, `secret_matches`. Empieza
   aquí: es puro, sin DB, testeable al instante. Escribe primero los tests
   ([tests/test_api_key.py](../tests/test_api_key.py)): round-trip, rechazo de
   keys malformadas, rechazo de secreto incorrecto.

2. **`verify_api_key`** ([deps.py](../email_triage/deps.py)): que devuelva
   `TenantContext` en vez de `None`/`bool`. Implementa los tres caminos: sin DB
   (key estática), cache hit, cache miss → `_resolve_tenant` (parse → get_by_id
   → secret_matches). Añade `invalidate_api_key_cache`.

3. **Propagar identidad**: `TenantDep` en el handler de `/triage`
   ([triage.py](../email_triage/routers/triage.py)); añade el parámetro
   `tenant_id` a `insert_log` y `persist_triage_log`
   ([db/repos/triage.py](../email_triage/db/repos/triage.py)).

4. **Emisión**: en signup/callback/rotate-key
   ([auth.py](../email_triage/routers/auth.py)), crea el tenant → `issue_api_key(tenant.id)`
   → set hash. Quita el pre-cómputo bcrypt de la key (mantén el del password).
   En rotate, llama a `invalidate_api_key_cache()`.

5. **Limpieza**: borra `all_key_hashes` del `TenantRepo` y `_check_key_against_db`
   de deps — ya nadie escanea.

6. **Verifica**: `make check` (ruff + format + pyright + pytest). Apunta a que
   los tests de `/triage` (key estática) sigan verdes y añade cobertura del
   camino con DB.

### Checklist mental de "¿lo entendí?"

- [ ] Sé explicar por qué bcrypt frena passwords pero estorba en tokens.
- [ ] Sé por qué el escaneo era O(N) y por qué el prefijo lo vuelve O(1).
- [ ] Sé por qué sha256 sin salt es seguro para un token de 256 bits.
- [ ] Sé por qué `compare_digest` y no `==`.
- [ ] Sé el caveat del cache por-worker y cuál es el fix (Redis).
- [ ] Sé qué desbloquea tener el `tenant_id` (atribución, rate-limit por tenant,
      aislamiento de datos).

---

## 10. Qué falta (entra en Track 1, OAuth2 Google)

Esto cierra C1/S2/C2/S4. Lo que sigue (orden acordado 3→2→**1**): terminar
OAuth2 con Google de forma correcta — validar el `id_token` (iss/aud/exp), el
redirect del callback al frontend, `email_verified`, y vincular cuentas
Google/password. Ese tendrá su propio documento de estudio.
