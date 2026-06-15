# Walkthrough de estudio — OAuth2 + OIDC con Google

> Documento de estudio enfocado a entrevista. Explica el **Authorization Code
> Flow con PKCE**, qué es un `id_token` y por qué se valida como se valida, y
> los arreglos que cerraron el flujo (S1, S8, C4, C7, B2).
>
> Verificado: `uv run pytest` → **55/55** · `uv run pyright` → **0 errores** ·
> `uv run ruff check` → limpio.
>
> Archivos: [routers/auth.py](../email_triage/routers/auth.py) ·
> [auth/pkce.py](../email_triage/auth/pkce.py) ·
> [auth/state.py](../email_triage/auth/state.py) ·
> [db/repos/users.py](../email_triage/db/repos/users.py)

---

## 0. El mapa mental: tres tokens distintos

Confundirlos es el error #1 en entrevistas de OAuth. Sepáralos:

| Token | Lo emite | Para qué | Quién lo valida |
|---|---|---|---|
| **authorization code** | Google (en la redirección) | un vale de un solo uso, corto, que se canjea por tokens | tu backend (lo canjea) |
| **id_token** (OIDC) | Google (JWT RS256) | **autenticación**: "quién es el usuario" (sub, email, name) | **tu backend** (este doc) |
| **access_token** | Google | autorización para llamar APIs de Google | las APIs de Google |
| **(tu) JWT de sesión** | **tu** backend (HS256) | tu propia sesión de usuario | tu backend en cada request |

OAuth2 es un framework de **autorización**; **OpenID Connect (OIDC)** es la capa
de **autenticación** que añade el `id_token` encima de OAuth2. Aquí solo nos
importa autenticar (saber quién es), así que el protagonista es el `id_token`.
El `access_token` de Google no lo usamos (no llamamos a Gmail/Drive).

---

## 1. El flujo completo (Authorization Code + PKCE)

```
Navegador                 Tu backend (FastAPI)            Google
   |                           |                            |
   |-- GET /auth/login ------->|                            |
   |                           | code_verifier = random     |
   |                           | code_challenge = S256(cv)  |
   |                           | state = random             |
   |                           | cookie firmada = {cv, st}  |
   |<-- 302 a accounts.google.com?client_id&redirect_uri&   |
   |        scope&state&code_challenge&method=S256 ---------|
   |                           |                            |
   |-- el usuario da consentimiento ------------------->    |
   |<-- 302 a /auth/callback?code=XXX&state=YYY ------------|
   |                           |                            |
   |-- GET /auth/callback ---->|                            |
   |                           | 1. state(YYY) == cookie.st? (CSRF)
   |                           | 2. POST /token  code + code_verifier -->|
   |                           |<-- {id_token (JWT), access_token} -------|
   |                           | 3. GET /certs (JWKS) ------------------->|
   |                           |<-- claves públicas RSA -----------------|
   |                           | 4. verificar id_token:
   |                           |    firma RS256 + iss + aud + exp
   |                           | 5. upsert User/Tenant
   |                           | 6. emitir TU JWT de sesión
   |<-- 302 a {frontend}/#token=<jwt> --|                   |
```

Implementación: `GET /auth/login` y `GET /auth/callback` en
[routers/auth.py](../email_triage/routers/auth.py).

---

## 2. PKCE — qué ataque para (y por qué existe)

PKCE = *Proof Key for Code Exchange* (RFC 7636). [auth/pkce.py](../email_triage/auth/pkce.py):

```python
def generate_code_verifier() -> str:        # secreto efímero, 43-128 chars
    return secrets.token_urlsafe(64)

def code_challenge(verifier: str) -> str:   # se envía a Google
    return base64url(sha256(verifier))       # sin padding
```

**El ataque sin PKCE:** en el flujo clásico, el `authorization code` viaja por
la URL de redirección. En un cliente público (SPA, móvil) un atacante que
intercepte ese code (malware, un esquema de URL secuestrado en móvil) podría
canjearlo por tokens. PKCE lo impide así:

- Generas un secreto aleatorio `code_verifier` y mandas a Google solo su
  **hash** (`code_challenge`). El hash es público, no sirve para nada por sí
  solo (no se puede invertir).
- Al canjear el code, mandas el `code_verifier` **original**. Google verifica
  `sha256(verifier) == challenge` guardado.
- Un atacante que robe el code **no tiene el verifier** → el canje falla.

> Frase: *"PKCE liga el authorization code a quien inició el flujo: solo quien
> conoce el code_verifier original puede canjear el code, así un code robado es
> inútil. Por eso el flujo implícito está deprecado (RFC 9700) y PKCE es el
> estándar para todos los clientes."*

`S256` (hash) vs `plain` (mandar el verifier tal cual): siempre `S256` — si
mandas el verifier en claro en el challenge, no hay secreto.

---

## 3. State — protección CSRF (y el bug C7 que arreglamos)

El parámetro `state` evita **CSRF en el login**: un atacante podría intentar que
tu navegador complete *su* flujo de login (forzándote a iniciar sesión en su
cuenta). Generas un `state` aleatorio, lo guardas, lo mandas a Google, y al
volver verificas que el `state` recibido coincide con el guardado.

**Decisión de diseño:** el `state` (y el `code_verifier`) se guardan en una
**cookie firmada** con `itsdangerous`, no en DB ni en memoria. Eso hace la
verificación **stateless** → funciona con N workers de gunicorn sin store
compartido. La cookie es de vida corta (5 min) y `HttpOnly`.

[auth/state.py](../email_triage/auth/state.py):

```python
def generate_pkce_cookie(secret, code_verifier) -> tuple[str, str]:
    state_token = secrets.token_urlsafe(16)
    payload = {"cv": code_verifier, "st": state_token}
    return _signer(secret).dumps(payload), state_token   # (cookie, state)
```

**El bug C7 (arreglado):** antes, `generate_pkce_cookie` devolvía solo la
cookie; el endpoint *des-firmaba su propia cookie recién creada* para recuperar
el `state`, con un fallback peligroso: si esa des-firma fallaba, mandaba a
Google un `state` **distinto** del de la cookie → el callback fallaría siempre
con "State mismatch", lejos de la causa real. El fix: la función devuelve
`(cookie, state)` directamente. Lección de entrevista: **una función que genera
un valor debe devolverlo, no obligar al llamador a re-derivarlo.**

---

## 4. La parte crítica: validar el id_token (S1)

Aquí estaba el agujero de seguridad principal. El `id_token` es un **JWT firmado
por Google con RS256** (clave privada de Google; tú verificas con su clave
pública). El código anterior **solo verificaba la firma**:

```python
google_token = joserfc_jwt.decode(id_token, key_set)   # ❌ solo firma
claims = google_token.claims
```

OIDC exige verificar **cuatro** cosas. Verificar solo la firma es insuficiente:

| Verificación | Qué impide si falta |
|---|---|
| **firma** (RS256 con JWKS de Google) | tokens forjados por terceros |
| **`iss`** == issuer de Google | aceptar tokens de otro emisor |
| **`aud`** == tu `client_id` | **token de otra app** reutilizado contra la tuya (confused deputy) |
| **`exp`** no caducado | reutilizar un token viejo robado |
| **algoritmo** pineado a `RS256` | **alg-confusion**: token con `alg:none` o HS256 usando la clave pública como secreto |

El fix ([auth.py](../email_triage/routers/auth.py)):

```python
google_token = joserfc_jwt.decode(id_token, key_set, algorithms=["RS256"])
claims_registry = joserfc_jwt.JWTClaimsRegistry(
    iss={"essential": True, "values": _GOOGLE_ISSUERS},
    aud={"essential": True, "value": settings.google_client_id},
    exp={"essential": True},
    sub={"essential": True},
)
claims_registry.validate(google_token.claims)
```

**Por qué pinear `algorithms=["RS256"]` es crítico** (pregunta clásica): si no
restringes el algoritmo, un atacante presenta un token con el header
`alg: none` (sin firma) o `alg: HS256` y firma con la *clave pública de Google*
(que es… pública) como si fuera un secreto HMAC. La librería, al no tener un
allow-list, intentaría verificar con ese algoritmo y aceptaría el token. Pinear
el algoritmo cierra esa familia de ataques (CVE clásicos de varias libs JWT).

### JWKS — de dónde sale la clave pública

`GET https://www.googleapis.com/oauth2/v3/certs` devuelve el *JSON Web Key Set*:
las claves públicas RSA de Google (rotan periódicamente). El header del
`id_token` trae un `kid` (key id) que indica cuál usar. `KeySet.import_key_set`
+ `decode` hacen el match `kid`→clave y verifican la firma. En producción
cachearías el JWKS (respeta `Cache-Control`) en vez de pedirlo en cada callback.

---

## 5. Vinculación de cuentas (C4) y `email_verified` (S8)

**El bug C4 (arreglado):** si alguien hacía signup con password y luego entraba
con "Continue with Google" usando el mismo email, el código solo buscaba por
`google_sub` (no lo encontraba) → intentaba `INSERT` con email duplicado →
`IntegrityError` → **500**.

El fix, en la fase de lectura del callback:

```
buscar por google_sub
  └─ no existe → buscar por email
        ├─ existe y email_verified → VINCULAR (set google_sub en esa cuenta)
        ├─ existe y NO verificado  → 409 (no vincular: riesgo de takeover)
        └─ no existe               → crear usuario nuevo
```

**Por qué `email_verified` es una compuerta de seguridad (S8), no un adorno:**
si vinculas una identidad de Google a una cuenta existente confiando en un email
que Google **no** ha verificado, un atacante podría crear una cuenta Google con
el email de la víctima (sin verificarlo) y, al hacer login, quedar vinculado a
la cuenta real → **account takeover**. Por eso:

- Solo vinculamos si `email_verified` es `true`.
- Al crear usuarios nuevos, guardamos el valor **real** del claim (antes se
  hardcodeaba `True` — eso es S8).
- Google a veces manda `email_verified` como bool y a veces como string
  `"true"`; lo normalizamos.

```python
raw = claims.get("email_verified", False)
email_verified = raw is True or str(raw).lower() == "true"
```

---

## 6. La respuesta: navegador vs API (B2)

El callback lo dispara **el navegador** (viene de la redirección de Google), que
no sabe qué hacer con un JSON. Pero un cliente API (Postman) sí quiere JSON. La
solución detecta el `Accept`:

```python
def _is_browser(request) -> bool:
    return "text/html" in request.headers.get("accept", "")
```

- **Navegador** → `302` a `{frontend_url}/#token=<jwt>`. El frontend lee
  `window.location.hash` y guarda el token.
- **API client** → `CallbackResponse` JSON (compatible hacia atrás).

**Por qué el fragmento (`#`) y no un query param (`?token=`):** el fragmento de
URL **nunca se envía al servidor**, así que el JWT no aparece en los access logs
del servidor, ni en el `Referer` que el navegador manda a terceros. Es la misma
razón por la que el viejo *implicit flow* usaba el fragmento.

> Caveat honesto: poner el token en el fragmento sigue dejándolo en el historial
> del navegador. Para máxima seguridad se usaría un intercambio por `postMessage`
> o una cookie `HttpOnly` puesta por el backend. Para esta SPA con JWT en
> `localStorage`, el fragmento es coherente con el diseño.

---

## 7. Flags de la cookie PKCE — qué significa cada uno

```python
redirect.set_cookie(
    key="pkce_state", value=...,
    httponly=True,        # JS no puede leerla → mitiga robo por XSS
    samesite="lax",       # no se manda en requests cross-site (CSRF)…
    secure=is_prod,       # …solo por HTTPS en prod (en dev permite HTTP)
    max_age=300,          # vive 5 min: solo el round-trip del login
)
```

**¿Por qué `SameSite=Lax` y no `Strict`?** `Strict` no manda la cookie en
navegaciones cross-site de nivel superior — y la vuelta desde Google
(`accounts.google.com` → tu `/auth/callback`) es exactamente eso. Con `Strict`
la cookie no llegaría y el login fallaría siempre. `Lax` permite el envío en
navegaciones GET de nivel superior, que es justo lo que necesitamos, sin abrir
CSRF en POST.

---

## 8. Preguntas típicas de entrevista

**P: ¿Diferencia entre OAuth2 y OpenID Connect?**
OAuth2 es autorización (delegar acceso a recursos). OIDC es una capa encima que
añade autenticación con el `id_token` (un JWT con la identidad). "OAuth2 te deja
*hacer* cosas en nombre del usuario; OIDC te dice *quién es* el usuario."

**P: ¿Por qué Authorization Code y no Implicit?**
El implícito devolvía el access_token directo en el fragmento de la URL —
expuesto, sin posibilidad de PKCE, deprecado por RFC 9700. El code flow mantiene
los tokens en el canal servidor-a-servidor del token exchange (TLS + client
secret) y permite PKCE.

**P: ¿Por qué validar `aud` si la firma ya es válida?**
La firma solo prueba que Google lo emitió, no **para quién**. Sin chequear `aud`,
un token legítimamente emitido para *otra* aplicación (otra `client_id`) sería
aceptado por la tuya — un "confused deputy". `aud == tu client_id` ata el token a
tu app.

**P: ¿Qué es alg-confusion y cómo lo evitas?**
Un atacante cambia el `alg` del header a `none` (sin firma) o a `HS256` y firma
con la clave pública de Google (que es pública) tratándola como secreto HMAC. Lo
evitas pineando `algorithms=["RS256"]` en el decode.

**P: ¿Por qué tu propio JWT (HS256) en vez de reusar el de Google?**
El id_token de Google es para autenticar *una vez* en el login. Para tus
sesiones emites tu propio JWT corto (30 min) firmado con tu secreto: controlas
expiración, claims y rotación sin depender de Google en cada request.

**P: ¿Cómo manejas el logout si el JWT es stateless?**
No se invalida server-side sin una blocklist; el cliente descarta el token y
expira en ≤30 min. Revocación real (Redis blocklist) es trabajo futuro. Es el
tradeoff consciente de JWT stateless.

**P: ¿Qué pasa si rotan las claves de Google (JWKS)?**
El `kid` del token apunta a la clave correcta; al pedir el JWKS obtienes las
vigentes. Con caché, ante un `kid` desconocido refrescas el JWKS.

---

## 9. Guía de reproducción

### Setup en Google Cloud Console (una vez)
1. Proyecto en console.cloud.google.com → habilitar Google Identity.
2. Crear **OAuth 2.0 Client ID** tipo "Web application".
3. Redirect URIs: `http://localhost:8000/auth/callback` (dev) y el de prod.
4. Pantalla de consentimiento: scopes `openid email profile`, añadir test users.
5. Copiar `client_id` y `client_secret` al `.env`.

### Código
1. **PKCE** ([auth/pkce.py](../email_triage/auth/pkce.py)): `generate_code_verifier`,
   `code_challenge` (S256). Testeable solo (`test_pkce_*`).
2. **State/cookie** ([auth/state.py](../email_triage/auth/state.py)): firma
   `{cv, st}` con itsdangerous; devuelve `(cookie, state)`.
3. **`GET /auth/login`**: genera verifier+challenge+cookie, redirige a Google con
   `code_challenge`, `state`, `scope`, `access_type=online`.
4. **`GET /auth/callback`**: verifica state → token exchange (POST con
   `code_verifier`) → JWKS → **decode con `algorithms=["RS256"]` + validar
   iss/aud/exp** → upsert con vinculación por email verificado → emitir tu JWT →
   redirect navegador o JSON.
5. **Tests** ([tests/test_auth.py](../tests/test_auth.py)): mockea `httpx` y
   `joserfc_jwt.decode`, pero deja correr la validación de claims real. Cubre:
   state mismatch (400), creación en primer login (200), **aud incorrecto (401)**,
   **token caducado (401)**, **vinculación Google↔password**.

### Checklist mental
- [ ] Sé distinguir authorization code / id_token / access_token / mi JWT.
- [ ] Sé qué ataque para PKCE y por qué S256.
- [ ] Sé por qué `state` va en cookie firmada (stateless multi-worker).
- [ ] Sé las 4 validaciones del id_token y por qué cada una.
- [ ] Sé explicar alg-confusion y el pin de RS256.
- [ ] Sé por qué `email_verified` es una compuerta de seguridad para vincular.
- [ ] Sé por qué el token vuelve en el fragmento de URL y no en query.

---

## 10. Pendiente menor (B5)

El botón **Authorize** de Swagger no funciona: `OAuth2PasswordBearer` hace que
Swagger mande `username`/`password` como **form-data**, pero `POST /auth/login`
espera **JSON** → 422. No afecta a la app real (el frontend manda JSON). Opciones
si se quiere cerrar: aceptar ambos formatos, o un endpoint `/auth/token` aparte
con `OAuth2PasswordRequestForm` solo para Swagger. Documentado, no bloqueante.
