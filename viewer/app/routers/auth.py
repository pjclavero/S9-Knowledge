"""Rutas de autenticación: login, logout, cuenta, cambio de contraseña."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import audit, bootstrap, db as auth_db
from app.auth.config import get_auth_settings
from app.auth.csrf import (
    LOGIN_CSRF_COOKIE,
    LOGIN_CSRF_MAX_AGE,
    get_csrf_token_for_session,
    issue_login_csrf,
    validate_csrf,
    validate_login_csrf,
)
from app.auth.dependencies import get_current_user, require_authenticated_user
from app.auth.models import User
from app.auth.next_url import ruta_interna_o_defecto
from app.auth.passwords import hash_password, needs_rehash, validate_password, verify_password
from app.auth.sessions import cookie_kwargs, create_session, revoke_session_by_token

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_db_path() -> Path:
    # Sin mkdir: el visor no crea rutas ni bases en silencio. La existencia de
    # la DB se garantiza en el arranque (enforce_auth_security) y la creación
    # legítima es la CLI de provisión.
    cfg = get_auth_settings()
    return Path(cfg.S9K_AUTH_DB_PATH)


def _safe_next(next_url: Optional[str]) -> str:
    """Anti open-redirect: sólo rutas internas inequívocas.

    La decisión vive entera en ``app.auth.next_url``, autoridad única y por
    COMPONENTES. Aquí no se replica criterio: duplicarlo fue justamente lo que
    dejó dos validadores divergentes (este y el de ``/partida/select``).
    """
    return ruta_interna_o_defecto(next_url)


def _hash_ip(ip: Optional[str]) -> Optional[str]:
    if ip is None:
        return None
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


def _hash_ua(ua: Optional[str]) -> Optional[str]:
    if ua is None:
        return None
    return hashlib.sha256(ua.encode()).hexdigest()[:16]


def _get_ip(request: Request) -> Optional[str]:
    cfg = get_auth_settings()
    if cfg.S9K_AUTH_TRUST_PROXY_HEADERS:
        fwd = request.headers.get("X-Forwarded-For")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else None



# ---------------------------------------------------------------------------
# Bootstrap pendiente: el login NO finge «credenciales incorrectas»
# ---------------------------------------------------------------------------

def _bootstrap_pendiente() -> bool:
    """True si esta instalacion aun no ha creado su primer administrador.

    Un fallo de almacenamiento devuelve False a proposito: el login sigue su
    camino normal (y fallara cerrado por si mismo). Lo que NO se hace es
    mandar a nadie a la configuracion inicial porque la base no se deja leer:
    eso convertiria un disco roto en una invitacion a crear un administrador.
    """
    db_path = _get_db_path()
    if not db_path.exists():
        # La base desaparecio con el proceso vivo. NO se consulta el estado:
        # `estado_instalacion` migra —es decir, CREA— y eso convertiria un
        # borrado en caliente en una «primera instalacion» con la puerta de
        # bootstrap abierta. El login sigue su camino y falla cerrado por si
        # mismo, que es la conducta que ya tenia.
        return False
    try:
        return not bootstrap.estado_instalacion(db_path).completado
    except bootstrap.BootstrapStorageError:
        import logging
        logging.getLogger("s9k.auth").error(
            "[%s] estado de instalacion indeterminado durante el login",
            bootstrap.AUTH_STORE_UNAVAILABLE,
        )
        return False


# ---------------------------------------------------------------------------
# GET /login
# ---------------------------------------------------------------------------

def _login_cookie_kwargs(cfg) -> dict:
    """Atributos de la cookie CSRF de login (mismos flags de seguridad)."""
    return {
        "key": LOGIN_CSRF_COOKIE,
        "max_age": LOGIN_CSRF_MAX_AGE,
        "httponly": cfg.S9K_SESSION_HTTPONLY,
        "secure": cfg.S9K_SESSION_SECURE,
        "samesite": cfg.S9K_SESSION_SAMESITE,
        "path": "/",
    }


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    next: Optional[str] = None,
    error: Optional[str] = None,
    message: Optional[str] = None,
):
    cfg = get_auth_settings()
    # Instalacion sin primer administrador: aqui no hay ninguna credencial que
    # acertar. Se conduce EXPLICITAMENTE a la configuracion inicial.
    if cfg.S9K_AUTH_ENABLED and _bootstrap_pendiente():
        return RedirectResponse(url="/setup/admin", status_code=303)
    token = issue_login_csrf(cfg.S9K_CSRF_SECRET)
    response = templates.TemplateResponse(
        request,
        "auth/login.html",
        {
            "next": _safe_next(next),
            "error": error,
            "message": message,
            "csrf_token": token,
        },
    )
    response.set_cookie(value=token, **_login_cookie_kwargs(cfg))
    return response


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------

@router.post("/login")
async def login_submit(
    request: Request,
    # Mismo criterio que `/setup/admin`, y por la misma razon medida: un campo
    # `Form(...)` obligatorio que falta produce un 422/400 de validacion ANTES
    # de que corra ninguna guarda, asi que la comprobacion de estado --«esta
    # instalacion no tiene primer administrador»-- no llegaria a ejecutarse y
    # el operador recibiria un error de formulario en vez de la pantalla de
    # configuracion inicial. Lo que falte se responde abajo, con su mensaje.
    username: str = Form(default=""),
    password: str = Form(default=""),
    csrf_token: str = Form(default=""),
    next: str = Form(default="/"),
):
    cfg = get_auth_settings()
    # Mismo criterio que el GET, comprobado otra vez en el servidor: sin primer
    # administrador, responder «Usuario o contrasena incorrectos» seria mentir
    # sobre la causa y dejar al operador probando credenciales que no existen.
    if cfg.S9K_AUTH_ENABLED and _bootstrap_pendiente():
        return RedirectResponse(url="/setup/admin", status_code=303)
    db_path = _get_db_path()
    # Fail-closed sin recrear: si la DB desapareció en caliente, el login
    # falla; ensure_migrated (via sqlite3.connect) crearía una base vacía.
    if not db_path.exists():
        import logging
        logging.getLogger("s9k.auth").error(
            "auth DB ausente en tiempo de petición: login denegado (fail-closed)."
        )
        return RedirectResponse(url="/login?error=auth_unavailable", status_code=303)
    auth_db.ensure_migrated(db_path)

    # El username admite normalización exterior (los teclados móviles añaden un
    # espacio final tras el autocompletado: 's9admin ' fallaba). El password NO
    # se toca jamás: es la secuencia exacta introducida por el usuario.
    username = username.strip()

    ip = _get_ip(request)
    ua = request.headers.get("user-agent")
    ip_hash = _hash_ip(ip)
    ua_hash = _hash_ua(ua)

    def _login_error(error: str, status_code: int):
        """Reemite un token CSRF fresco y su cookie en cada respuesta de error."""
        fresh = issue_login_csrf(cfg.S9K_CSRF_SECRET)
        resp = templates.TemplateResponse(
            request, "auth/login.html",
            {"error": error, "next": _safe_next(next), "csrf_token": fresh},
            status_code=status_code,
        )
        resp.set_cookie(value=fresh, **_login_cookie_kwargs(cfg))
        return resp

    # Formulario incompleto: repinta la pagina con su mensaje, como antes.
    # Antes lo producia el manejador de RequestValidationError de `main.py`,
    # que ya no se dispara porque los campos dejaron de ser obligatorios para
    # que la guarda de bootstrap corra primero. La conducta observable --400 y
    # `campos_incompletos`-- es la misma; lo que cambia es QUIEN la decide.
    if not username or not password:
        return _login_error("campos_incompletos", 400)

    # CSRF de login real: token firmado + temporal + double-submit contra cookie.
    cookie_token = request.cookies.get(LOGIN_CSRF_COOKIE)
    if not validate_login_csrf(csrf_token, cookie_token, secret=cfg.S9K_CSRF_SECRET):
        return _login_error("csrf_invalid", 403)

    with auth_db.get_conn(db_path) as conn:
        user = auth_db.get_user_by_username(conn, username)

        if user is None:
            # Ejecutar hash igualmente para evitar timing attack
            hash_password("dummy-timing-defense")
            audit.log(conn, audit.LOGIN_FAILURE, "failure",
                      username_snapshot=username, ip_hash=ip_hash,
                      user_agent_hash=ua_hash)
            return _login_error("invalid_credentials", 401)

        # Comprobar bloqueo
        if user.is_locked():
            audit.log(conn, audit.ACCOUNT_LOCKED, "failure",
                      user_id=user.id, username_snapshot=user.username,
                      ip_hash=ip_hash, user_agent_hash=ua_hash)
            return _login_error("invalid_credentials", 401)

        # Verificar contraseña
        if not verify_password(password, user.password_hash):
            new_count = user.failed_login_count + 1
            locked_until = None
            if new_count >= cfg.S9K_AUTH_MAX_FAILED_ATTEMPTS:
                from datetime import datetime, timedelta, timezone
                locked_until = (
                    datetime.now(timezone.utc).replace(tzinfo=None)
                    + timedelta(minutes=cfg.S9K_AUTH_LOCK_MINUTES)
                ).isoformat()
                audit.log(conn, audit.ACCOUNT_LOCKED, "failure",
                          user_id=user.id, username_snapshot=user.username,
                          ip_hash=ip_hash, user_agent_hash=ua_hash)
            auth_db.update_user(conn, user.id,
                                failed_login_count=new_count,
                                locked_until=locked_until)
            audit.log(conn, audit.LOGIN_FAILURE, "failure",
                      user_id=user.id, username_snapshot=user.username,
                      ip_hash=ip_hash, user_agent_hash=ua_hash)
            return _login_error("invalid_credentials", 401)

        if not user.is_active:
            audit.log(conn, audit.LOGIN_FAILURE, "failure",
                      user_id=user.id, username_snapshot=user.username,
                      ip_hash=ip_hash, user_agent_hash=ua_hash)
            return _login_error("invalid_credentials", 401)

        # Rehash si es necesario
        if needs_rehash(user.password_hash):
            new_hash = hash_password(password)
            auth_db.update_user(conn, user.id, password_hash=new_hash)

        # Resetear intentos fallidos
        from datetime import datetime, timezone
        auth_db.update_user(conn, user.id,
                            failed_login_count=0,
                            locked_until="",
                            last_login_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat())

        # Revocar sesiones anteriores (rotación)
        auth_db.revoke_sessions_for_user(conn, user.id)

        # Crear nueva sesión
        token, session = create_session(conn, user, ip=ip, user_agent=ua)

        audit.log(conn, audit.LOGIN_SUCCESS, "success",
                  user_id=user.id, username_snapshot=user.username,
                  ip_hash=ip_hash, user_agent_hash=ua_hash)

    redirect_to = _safe_next(next)
    if user.must_change_password:
        redirect_to = "/account/change-password"

    response = RedirectResponse(url=redirect_to, status_code=302)
    ck = cookie_kwargs()
    response.set_cookie(value=token, **ck)
    # El token CSRF de login ya se consumió: eliminar su cookie.
    response.delete_cookie(LOGIN_CSRF_COOKIE, path="/")
    return response


# ---------------------------------------------------------------------------
# POST /logout
# ---------------------------------------------------------------------------

@router.post("/logout")
async def logout(
    request: Request,
    csrf_token: str = Form(...),
    user: Optional[User] = Depends(get_current_user),
):
    cfg = get_auth_settings()
    token = request.cookies.get(cfg.S9K_SESSION_COOKIE_NAME)
    session = getattr(request.state, "session", None)

    # Validar CSRF contra sesión activa
    if session and user:
        raw_csrf = getattr(request.state, "csrf_raw", "")
        if not validate_csrf(csrf_token, session.id, raw_csrf, secret=cfg.S9K_CSRF_SECRET):
            from fastapi.responses import Response
            return Response(status_code=403, content="CSRF inválido")

    if token:
        db_path = _get_db_path()
        with auth_db.get_conn(db_path) as conn:
            revoke_session_by_token(conn, token)
            if user:
                audit.log(conn, audit.LOGOUT, "success",
                          user_id=user.id, username_snapshot=user.username)

    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(cfg.S9K_SESSION_COOKIE_NAME, path="/")
    return response


# ---------------------------------------------------------------------------
# GET /account
# ---------------------------------------------------------------------------

@router.get("/account", response_class=HTMLResponse)
async def account_page(
    request: Request,
    user: User = Depends(require_authenticated_user),
):
    if isinstance(user, RedirectResponse):
        return user
    session = getattr(request.state, "session", None)
    cfg = get_auth_settings()
    csrf_raw = getattr(request.state, "csrf_raw", "")
    csrf_tok = get_csrf_token_for_session(
        session.id if session else 0, csrf_raw, secret=cfg.S9K_CSRF_SECRET
    )
    return templates.TemplateResponse(
        request,
        "auth/account.html",
        {"user": user, "csrf_token": csrf_tok},
    )


# ---------------------------------------------------------------------------
# GET /account/change-password
# ---------------------------------------------------------------------------

@router.get("/account/change-password", response_class=HTMLResponse)
async def change_password_page(
    request: Request,
    user: User = Depends(require_authenticated_user),
):
    if isinstance(user, RedirectResponse):
        return user
    session = getattr(request.state, "session", None)
    cfg = get_auth_settings()
    csrf_raw = getattr(request.state, "csrf_raw", "")
    csrf_tok = get_csrf_token_for_session(
        session.id if session else 0, csrf_raw, secret=cfg.S9K_CSRF_SECRET
    )
    return templates.TemplateResponse(
        request,
        "auth/change_password.html",
        {"user": user, "csrf_token": csrf_tok, "errors": []},
    )


# ---------------------------------------------------------------------------
# POST /account/change-password
# ---------------------------------------------------------------------------

@router.post("/account/change-password")
async def change_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    csrf_token: str = Form(...),
    user: User = Depends(require_authenticated_user),
):
    if isinstance(user, RedirectResponse):
        return user

    cfg = get_auth_settings()
    session = getattr(request.state, "session", None)
    csrf_raw = getattr(request.state, "csrf_raw", "")

    # Validar CSRF
    if not validate_csrf(csrf_token, session.id if session else 0, csrf_raw,
                         secret=cfg.S9K_CSRF_SECRET):
        return templates.TemplateResponse(
            request, "auth/change_password.html",
            {"user": user, "csrf_token": csrf_token, "errors": ["CSRF inválido"]},
            status_code=403,
        )

    errors: list[str] = []

    # Verificar contraseña actual
    if not verify_password(current_password, user.password_hash):
        errors.append("La contraseña actual es incorrecta.")

    # Validar nueva
    if new_password != confirm_password:
        errors.append("Las contraseñas nuevas no coinciden.")

    # Una temporal repetida no es un cambio: dejaria la cuenta con la credencial
    # que se entrego por un canal de reparto, que es justo lo que hay que retirar.
    if new_password == current_password:
        errors.append("La contraseña nueva debe ser distinta de la actual.")

    errors += validate_password(new_password, user.username)

    if errors:
        csrf_tok = get_csrf_token_for_session(
            session.id if session else 0, csrf_raw, secret=cfg.S9K_CSRF_SECRET
        )
        return templates.TemplateResponse(
            request, "auth/change_password.html",
            {"user": user, "csrf_token": csrf_tok, "errors": errors},
            status_code=400,
        )

    # Guardar la nueva contraseña, limpiar el bloqueo y rotar la sesión.
    new_hash = hash_password(new_password)
    db_path = _get_db_path()
    with auth_db.get_conn(db_path) as conn:
        auth_db.update_user(conn, user.id,
                            password_hash=new_hash,
                            must_change_password=False,
                            # Quien acaba de demostrar que conoce la contraseña
                            # actual no arrastra el bloqueo de intentos previos.
                            failed_login_count=0,
                            locked_until="")
        # Primero se invalidan TODAS las sesiones (incluida la actual, que se
        # emitio con la credencial temporal) y despues se emite una nueva: asi el
        # usuario sigue dentro, pero con una sesion que no existia antes.
        auth_db.revoke_sessions_for_user(conn, user.id)
        token, _session = create_session(
            conn, user, ip=_get_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        audit.log(conn, audit.PASSWORD_CHANGED, "success",
                  user_id=user.id, username_snapshot=user.username,
                  metadata={"changed_by": "self", "session_rotated": True})

    # Verificación post-commit desde una conexión NUEVA: si el hash persistido
    # no verifica la contraseña aún en memoria, el cambio NO se declara exitoso
    # y la sesión recién emitida se revoca. (El plaintext nunca se registra.)
    if not auth_db.verify_persisted_password(db_path, user.id, new_password):
        with auth_db.get_conn(db_path) as conn:
            auth_db.revoke_sessions_for_user(conn, user.id)
            audit.log(conn, audit.PASSWORD_CHANGED, "failure",
                      user_id=user.id, username_snapshot=user.username,
                      metadata={"reason": "post-commit-verification-failed"})
        return templates.TemplateResponse(
            request, "auth/change_password.html",
            {"user": user, "csrf_token": csrf_token,
             "errors": ["El cambio no pudo verificarse en disco. Inténtalo de nuevo."]},
            status_code=500,
        )

    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(value=token, **cookie_kwargs())
    return response
