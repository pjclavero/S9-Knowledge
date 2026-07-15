# 44 · Autenticación del visor S9 Knowledge

Implementado en la rama `feat/viewer-auth-foundation` (julio 2026).

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
│   │   ├── csrf.py         — Tokens CSRF por sesión
│   │   ├── audit.py        — Tipos de evento + helper log()
│   │   ├── identity.py     — OperatorIdentity para fase futura
│   │   ├── middleware.py   — AuthMiddleware (inyecta user/session)
│   │   └── dependencies.py — Dependencias FastAPI (get_current_user, etc.)
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
│   ├── test_auth_core.py   — 18 tests: passwords, sesiones, CSRF, DB
│   └── test_auth_routes.py — 22 tests: rutas, roles, auditoría, seguridad
└── state/
    └── auth.db             — Creado automáticamente (no en git)
```
