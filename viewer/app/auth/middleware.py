"""Middleware de autenticación: inyecta user, session y csrf_raw en request.state."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from pathlib import Path
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.auth import db as auth_db
from app.auth.config import get_auth_settings
from app.auth.sessions import get_valid_session

_CSRF_COOKIE = "_s9k_csrf"


def _get_real_ip(request: Request) -> Optional[str]:
    cfg = get_auth_settings()
    if cfg.S9K_AUTH_TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


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
                            import hmac as _hmac
                            csrf_raw = _hmac.new(
                                cfg.S9K_CSRF_SECRET.encode(),
                                f"csrf:{session.id}:{session.session_hash[:8]}".encode(),
                                hashlib.sha256,
                            ).hexdigest()
                            request.state.csrf_raw = csrf_raw
                except Exception:
                    pass  # No romper la app si auth falla

        response = await call_next(request)
        return response
