# 44 · Autenticación del visor S9 Knowledge

Implementado en la rama `feat/viewer-auth-foundation-clean` (julio 2026).

---

## Resumen

Esta fase añade al visor S9 Knowledge un sistema completo de autenticación y autorización basado en sesiones server-side con usuarios locales. El sistema es **opt-in**: cuando `S9K_AUTH_ENABLED=false` (valor por defecto), el visor se comporta exactamente igual que antes.

La fase NO habilita aprobación, edición, ingesta ni escritura en Neo4j.

---

## Arquitectura

```
Browser → Cookie s9k_session → AuthMiddleware → request.state.user/session
                                   ↓
                              SQLite auth.db
                         (users, sessions, audit_events)
```

- **Almacenamiento**: SQLite en `viewer/state/auth.db` (configurable por `S9K_AUTH_DB_PATH`)
- **Hash de contraseña**: Argon2id (argon2-cffi) → bcrypt → PBKDF2-SHA256 (fallback dev)
- **Sesiones**: Token CSPRNG (`secrets.token_urlsafe(32)`), solo SHA-256 en DB
- **CSRF**: Token por sesión derivado con HMAC-SHA256, comparación con `hmac.compare_digest`
- **Cookies**: `HttpOnly=true`, `Secure=true`, `SameSite=Lax`

---

## Endurecimiento de seguridad (Fase A4)

Sobre la base anterior se aplicó un endurecimiento *fail-closed*:

- **Protección de todas las APIs.** `/api/status`, `/api/workspaces`, `/api/entity-types`, `/api/search`, `/api/entity/{id}`, `/api/graph`, `/api/jobs*` exigen sesión (viewer+) mediante las dependencias centrales `get_current_api_user`, `require_api_authenticated_user` y `require_api_role`. Comportamiento: API anónima → **401 JSON**; rol insuficiente → **403 JSON**; HTML anónimo → **302 /login**. Con `S9K_AUTH_ENABLED=false` las dependencias son no-op (APIs públicas, sin cambios).
- **CSRF de login real.** Token firmado (`HMAC-SHA256`), temporal (caduca a la hora) y ligado al navegador por *double-submit cookie* (`_s9k_login_csrf`). Un token vacío, inventado, caducado o que no coincide con la cookie es rechazado con 403. Se aplica también a logout, cambio de contraseña y acciones de administración (CSRF por sesión).
- **Validación de arranque.** Con `S9K_AUTH_ENABLED=true`, `enforce_auth_security()` aborta el arranque si el secreto CSRF está vacío, es el valor por defecto, es corto (<32) o de baja entropía; y si el backend de contraseñas no es Argon2id ni bcrypt (PBKDF2-dev prohibido en producción). No se genera un secreto silenciosamente.
- **Backend de contraseñas.** Argon2id (preferido) o bcrypt (compatibilidad). PBKDF2-SHA256 queda solo para dev/CI y **bloquea el arranque** cuando auth está activa.
- **Middleware fail-closed.** Ante cualquier fallo del backend de auth (DB, sesión, migración, cookie) el usuario queda **no autenticado** y las rutas protegidas deniegan el acceso; se registra por *logging* estructurado y sanitizado (sin token, cookie, hash ni secreto).
- **/docs, /redoc y OpenAPI.** No se registran por defecto. Con `S9K_AUTH_EXPOSE_DOCS=true` y auth activa, solo el rol **admin** puede verlos (anónimo → 401, no-admin → 403); las APIs anónimas siguen devolviendo 401.
- **Cookies y proxy.** En producción `HttpOnly`/`Secure`/`SameSite=Lax`; el acceso productivo se hace por HTTPS a través del reverse proxy. `X-Forwarded-*` solo se atiende con `S9K_AUTH_TRUST_PROXY_HEADERS=true`.

**Generación del secreto CSRF** (no commitear el valor):

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

---

## Variables de configuración

| Variable | Por defecto | Descripción |
|----------|-------------|-------------|
| `S9K_AUTH_ENABLED` | `false` | Activar autenticación |
| `S9K_AUTH_DB_PATH` | `viewer/state/auth.db` | Ruta de la DB SQLite |
| `S9K_SESSION_COOKIE_NAME` | `s9k_session` | Nombre de la cookie |
| `S9K_SESSION_TTL_HOURS` | `12` | Duración máxima de sesión |
| `S9K_SESSION_IDLE_MINUTES` | `60` | Tiempo de inactividad |
| `S9K_SESSION_SECURE` | `true` | Cookie Secure (poner false en dev local) |
| `S9K_SESSION_SAMESITE` | `lax` | Cookie SameSite |
| `S9K_AUTH_MAX_FAILED_ATTEMPTS` | `5` | Intentos antes de bloqueo |
| `S9K_AUTH_LOCK_MINUTES` | `15` | Duración del bloqueo |
| `S9K_AUTH_EXPOSE_DOCS` | `false` | Exponer /docs y /redoc |
| `S9K_CSRF_SECRET` | *(debe cambiarse)* | Secreto para tokens CSRF |

---

## Roles y matriz de permisos

| Ruta | admin | reviewer | viewer | anónimo |
|------|-------|----------|--------|---------|
| `/login` | Sí | Sí | Sí | Sí |
| `/logout` | Sí | Sí | Sí | No |
| `/` | Sí | Sí | Sí | No → /login |
| `/graph` | Sí | Sí | Sí | No → /login |
| `/jobs` | Sí | Sí | Sí | No → /login |
| `/reviews` | Sí | Sí | **No → 403** | No → /login |
| `/api/status` | Sí | Sí | Sí | No → 401 |
| `/admin/users` | **Sí** | No → 403 | No → 403 | No → /login |
| `/admin/audit` | **Sí** | No → 403 | No → 403 | No → /login |
| `/docs`, `/redoc` | Configurable | Configurable | No | No |

**Nota**: Cuando `S9K_AUTH_ENABLED=false`, todas las rutas conservan su comportamiento anterior sin restricciones.

---

## Primer arranque: crear administrador

Antes de activar la autenticación, se debe crear al menos un administrador por CLI:

```bash
# En VM105, con el entorno virtual activado
cd /opt/knowledge-services/viewer  # o donde esté el repo
python -m viewer.app.cli.auth create-admin
```

Se pedirán username, display name y contraseña de forma interactiva.
La contraseña NUNCA se pasa como argumento de línea de comandos.

---

## Activación en producción

1. Crear el administrador (ver arriba).
2. Configurar `.env` con `S9K_AUTH_ENABLED=true`.
3. Establecer un `S9K_CSRF_SECRET` aleatorio (p.ej. `openssl rand -hex 32`).
4. Reiniciar el servicio `s9-knowledge-viewer.service`.

> La barrera Basic Auth de nginx en VM104 puede mantenerse como doble barrera durante
> la transición. Plan de retirada: una vez verificado el login propio con múltiples
> usuarios, se puede eliminar el `auth_basic` de nginx.

---

## Comandos CLI disponibles

```bash
python -m viewer.app.cli.auth <comando>
```

| Comando | Descripción |
|---------|-------------|
| `create-admin` | Crea el primer administrador |
| `create-user` | Crea usuario con rol especificado |
| `list-users` | Lista todos los usuarios |
| `set-password` | Cambia contraseña (por getpass) |
| `set-role` | Cambia el rol de un usuario |
| `enable-user` | Activa un usuario desactivado |
| `disable-user` | Desactiva un usuario (no elimina) |
| `unlock-user` | Desbloquea cuenta tras intentos fallidos |
| `revoke-sessions` | Revoca todas las sesiones activas |
| `cleanup-sessions` | Elimina sesiones expiradas de la DB |
| `status` | Muestra estado del sistema auth |

---

## Auditoría

La tabla `audit_events` registra en append-only:

- `LOGIN_SUCCESS`, `LOGIN_FAILURE`, `ACCOUNT_LOCKED`
- `LOGOUT`, `SESSION_EXPIRED`
- `PASSWORD_CHANGED`
- `USER_CREATED`, `USER_UPDATED`, `USER_DISABLED`, `USER_ENABLED`
- `ROLE_CHANGED`, `SESSIONS_REVOKED`
- `ACCESS_DENIED`

Los campos sensibles (IP, user-agent) se almacenan como prefijos SHA-256 de 16 caracteres.
La auditoría es visible en `/admin/audit` con filtros y paginación.

---

## Seguridad: mitigaciones implementadas

| Amenaza | Mitigación |
|---------|-----------|
| Contraseñas en claro | Argon2id en producción, PBKDF2 en fallback dev |
| Tokens en claro | Solo SHA-256 del token en DB; el token sale solo en la cookie |
| CSRF | Token HMAC-SHA256 por sesión en campo hidden; `hmac.compare_digest` |
| Session fixation | Rotación de sesión en cada login |
| Enumeración de usuarios | Mensaje de error genérico para usuario/contraseña |
| Fuerza bruta | Bloqueo temporal tras N intentos fallidos |
| Open redirect | Validación de `next` contra URLs absolutas |
| XSS en auditoría | Escaping Jinja2 (`| e`) en todos los campos de usuario |
| IPs en DB | Solo prefijo SHA-256 (no IP completa) |

---

## Limitaciones de esta fase

- No hay recuperación de contraseña por email (se hace por CLI).
- No hay autenticación multifactor.
- No hay soporte para OIDC/OAuth2 externo.
- La identidad del operador aún no está conectada a `review_manual.py` ni al writer
  (esto es trabajo de una fase futura: `reviewed_by` y `reviewed_at`).
- La limpieza de sesiones expiradas es manual (CLI `cleanup-sessions`) o hay que
  añadir una tarea cron.

---

## Estructura de archivos

```
viewer/
├── app/
│   ├── auth/
│   │   ├── config.py       — Variables de entorno de auth
│   │   ├── models.py       — Dataclasses: User, Session, AuditEvent
│   │   ├── db.py           — SQLite + migraciones versionadas
│   │   ├── passwords.py    — Argon2id / bcrypt / PBKDF2
│   │   ├── sessions.py     — Crear, validar, revocar sesiones
│   │   ├── csrf.py         — CSRF por sesión + CSRF de login firmado/temporal
│   │   ├── audit.py        — Tipos de evento + helper log()
│   │   ├── security.py     — enforce_auth_security(): validación de arranque
│   │   ├── identity.py     — OperatorIdentity para fase futura
│   │   ├── middleware.py   — AuthMiddleware (inyecta user/session, fail-closed)
│   │   └── dependencies.py — Dependencias FastAPI (HTML + API: 401/403 JSON)
│   ├── routers/
│   │   ├── auth.py         — /login, /logout, /account, /account/change-password
│   │   └── admin.py        — /admin/users, /admin/audit
│   ├── cli/
│   │   └── auth.py         — CLI administrativa
│   └── templates/
│       └── auth/
│           ├── login.html
│           ├── account.html
│           ├── change_password.html
│           ├── 403.html
│           └── admin/
│               ├── users.html
│               ├── user_detail.html
│               └── audit.html
├── tests/
│   ├── test_auth_core.py      — 18 tests: passwords, sesiones, CSRF, DB
│   ├── test_auth_routes.py    — 22 tests: rutas, roles, auditoría, seguridad
│   └── test_auth_hardening.py — 38 tests: APIs 401/403, CSRF login, arranque, fail-closed, /docs, aislamiento
└── state/
    └── auth.db             — Creado automáticamente (no en git)
```
