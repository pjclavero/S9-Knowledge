"""Middleware de autenticación: inyecta user, session y csrf_raw en request.state."""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from pathlib import Path
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, RedirectResponse, Response

from app.auth import db as auth_db
from app.auth.config import get_auth_settings
from app.auth.sessions import get_valid_session

log = logging.getLogger("s9k.auth.middleware")

_CSRF_COOKIE = "_s9k_csrf"

# Rutas permitidas mientras must_change_password=true. Todo lo demas queda
# cerrado hasta que el usuario fije su contrasena definitiva.
#
# Vive en el middleware, no en cada guarda de ruta: una obligacion que hay que
# recordar aplicar en cada endpoint nuevo acaba olvidandose. Antes la marca solo
# dirigia la redireccion posterior al login, asi que bastaba teclear /entities
# para saltarsela.
CHANGE_PASSWORD_PATH = "/account/change-password"
_MUST_CHANGE_ALLOWED_EXACT = frozenset({
    CHANGE_PASSWORD_PATH,
    "/logout",
    "/login",          # permitido para no encerrar al usuario en un bucle
    "/favicon.ico",
})
_MUST_CHANGE_ALLOWED_PREFIXES = ("/static/",)


def _must_change_allows(path: str) -> bool:
    return (path in _MUST_CHANGE_ALLOWED_EXACT
            or path.startswith(_MUST_CHANGE_ALLOWED_PREFIXES))


def _get_real_ip(request: Request) -> Optional[str]:
    cfg = get_auth_settings()
    if cfg.S9K_AUTH_TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _must_change_password_response(request: Request) -> Optional[Response]:
    """Corta la peticion si el usuario aun no ha fijado su contrasena.

    Devuelve None si la ruta esta permitida. Las APIs reciben 403 JSON en vez de
    una redireccion: un cliente que espera JSON no sabe seguir un 302 a HTML.
    """
    path = request.url.path
    if _must_change_allows(path):
        return None
    if path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
        return JSONResponse(
            status_code=403,
            content={"detail": "Debes cambiar tu contraseña antes de continuar.",
                     "change_password_url": CHANGE_PASSWORD_PATH},
        )
    return RedirectResponse(url=CHANGE_PASSWORD_PATH, status_code=302)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Para cada petición:
    - Lee la cookie de sesión.
    - Valida el token y carga usuario.
    - Inyecta en request.state: user, session, csrf_raw (o None/vacío si no autenticado).
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        cfg = get_auth_settings()
        request.state.user = None
        request.state.session = None
        request.state.csrf_raw = ""

        if cfg.S9K_AUTH_ENABLED:
            token = request.cookies.get(cfg.S9K_SESSION_COOKIE_NAME)
            if token:
                db_path = Path(cfg.S9K_AUTH_DB_PATH)
                db_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    auth_db.ensure_migrated(db_path)
                    with auth_db.get_conn(db_path) as conn:
                        result = get_valid_session(conn, token)
                        if result is not None:
                            session, user = result
                            request.state.user = user
                            request.state.session = session
                            # Token CSRF: derivado del session_hash para no requerir DB
                            csrf_raw = hmac.new(
                                cfg.S9K_CSRF_SECRET.encode(),
                                f"csrf:{session.id}:{session.session_hash[:8]}".encode(),
                                hashlib.sha256,
                            ).hexdigest()
                            request.state.csrf_raw = csrf_raw
                except Exception as exc:
                    # Fail-closed: ante cualquier fallo de auth (DB, sesión,
                    # migración, cookie) el usuario queda NO autenticado y las
                    # rutas protegidas denegarán el acceso. Log sanitizado: sin
                    # token, cookie, hash ni secreto; solo tipo de excepción.
                    request.state.user = None
                    request.state.session = None
                    request.state.csrf_raw = ""
                    log.error(
                        "Fallo en el backend de autenticación (%s): acceso tratado "
                        "como anónimo (fail-closed).",
                        type(exc).__name__,
                    )

        user = request.state.user
        if user is not None and user.must_change_password:
            blocked = _must_change_password_response(request)
            if blocked is not None:
                return blocked

        response = await call_next(request)
        return response
