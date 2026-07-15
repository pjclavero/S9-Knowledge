"""Rutas de autenticación: login, logout, cuenta, cambio de contraseña."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import audit, db as auth_db
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
from app.auth.passwords import hash_password, needs_rehash, validate_password, verify_password
from app.auth.sessions import cookie_kwargs, create_session, revoke_session_by_token

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_db_path() -> Path:
    cfg = get_auth_settings()
    p = Path(cfg.S9K_AUTH_DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _safe_next(next_url: Optional[str]) -> str:
    """Anti open-redirect: solo acepta rutas relativas internas."""
    if not next_url:
        return "/"
    parsed = urlparse(next_url)
    # Rechazar si tiene esquema o netloc (URL absoluta)
    if parsed.scheme or parsed.netloc:
        return "/"
    # Debe empezar por /
    if not next_url.startswith("/"):
        return "/"
    return next_url


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
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    next: str = Form(default="/"),
):
    cfg = get_auth_settings()
    db_path = _get_db_path()
    auth_db.ensure_migrated(db_path)

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

    # Guardar nueva contraseña y revocar sesiones
    new_hash = hash_password(new_password)
    db_path = _get_db_path()
    with auth_db.get_conn(db_path) as conn:
        auth_db.update_user(conn, user.id,
                            password_hash=new_hash,
                            must_change_password=False)
        auth_db.revoke_sessions_for_user(conn, user.id)
        audit.log(conn, audit.PASSWORD_CHANGED, "success",
                  user_id=user.id, username_snapshot=user.username)

    response = RedirectResponse(url="/login?message=password_changed", status_code=302)
    response.delete_cookie(cfg.S9K_SESSION_COOKIE_NAME, path="/")
    return response
