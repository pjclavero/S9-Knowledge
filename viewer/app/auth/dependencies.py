"""Dependencias FastAPI para autenticación y autorización."""
from __future__ import annotations

from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.auth.config import get_auth_settings
from app.auth.models import User


def _is_browser_request(request: Request) -> bool:
    """Detecta si la petición viene de un navegador (Accept: text/html)."""
    accept = request.headers.get("accept", "")
    return "text/html" in accept


async def get_current_user(request: Request) -> Optional[User]:
    """
    Devuelve el usuario autenticado si existe en request.state,
    o None si no hay sesión (o auth desactivada).
    """
    return getattr(request.state, "user", None)


async def require_authenticated_user(
    request: Request,
    user: Optional[User] = Depends(get_current_user),
) -> User:
    """
    Exige usuario autenticado.
    - Navegador sin sesión → 302 a /login?next=<ruta>
    - API sin sesión → 401 JSON
    """
    if user is None:
        if _is_browser_request(request):
            next_url = str(request.url.path)
            return RedirectResponse(url=f"/login?next={next_url}", status_code=302)
        raise HTTPException(status_code=401, detail="No autenticado")
    return user


def require_role(role: str) -> Callable:
    """
    Devuelve una dependencia FastAPI que exige el rol indicado.
    Roles: admin > reviewer > viewer
    """
    _role_hierarchy = {"admin": 3, "reviewer": 2, "viewer": 1}

    async def _check(
        request: Request,
        user: User = Depends(require_authenticated_user),
    ) -> User:
        if isinstance(user, RedirectResponse):
            return user
        user_level = _role_hierarchy.get(user.role, 0)
        required_level = _role_hierarchy.get(role, 0)
        if user_level < required_level:
            raise HTTPException(status_code=403, detail="Acceso denegado")
        return user

    return _check


async def require_admin(
    request: Request,
    user: User = Depends(require_authenticated_user),
) -> User:
    """Exige rol admin."""
    if isinstance(user, RedirectResponse):
        return user
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Acceso denegado: se requiere rol admin")
    return user


# ---------------------------------------------------------------------------
# Dependencias de API (JSON): SIEMPRE 401/403 JSON, nunca redirección HTML.
# No-op cuando S9K_AUTH_ENABLED=false (comportamiento público sin cambios).
# ---------------------------------------------------------------------------

_ROLE_HIERARCHY = {"admin": 3, "reviewer": 2, "viewer": 1}


async def get_current_api_user(request: Request) -> Optional[User]:
    """Usuario autenticado para rutas de API, o None (auth off o sin sesión)."""
    return getattr(request.state, "user", None)


async def require_api_authenticated_user(
    request: Request,
    user: Optional[User] = Depends(get_current_api_user),
) -> Optional[User]:
    """Exige sesión válida en rutas de API.

    - auth desactivada  → permite (devuelve None).
    - auth activada, sin sesión → 401 JSON.
    """
    if not get_auth_settings().S9K_AUTH_ENABLED:
        return None
    if user is None:
        raise HTTPException(status_code=401, detail="No autenticado")
    return user


def require_api_role(role: str) -> Callable:
    """Dependencia de API que exige un rol mínimo (jerarquía admin>reviewer>viewer).

    - auth desactivada  → permite.
    - auth activada, sin sesión → 401 JSON.
    - auth activada, rol insuficiente → 403 JSON.
    """
    async def _check(
        request: Request,
        user: Optional[User] = Depends(get_current_api_user),
    ) -> Optional[User]:
        if not get_auth_settings().S9K_AUTH_ENABLED:
            return None
        if user is None:
            raise HTTPException(status_code=401, detail="No autenticado")
        if _ROLE_HIERARCHY.get(user.role, 0) < _ROLE_HIERARCHY.get(role, 0):
            raise HTTPException(status_code=403, detail="Acceso denegado")
        return user

    return _check
