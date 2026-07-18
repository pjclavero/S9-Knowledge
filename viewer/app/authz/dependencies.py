"""Dependencias FastAPI de autorización de contenido (visibilidad RPG).

Exponen:
  - ``get_visibility_context``: construye el ViewerContext de la petición.
  - ``get_filtered_provider`` : envuelve el provider base con la política.

Se apoya en el provider base (``app.deps.get_provider``) y en la identidad ya
inyectada por el middleware de auth en ``request.state.user``. Con auth
desactivada el contexto es ``admin_full`` (visor abierto heredado).
"""
from __future__ import annotations

from fastapi import Depends, Request

from app.auth.config import get_auth_settings
from app.authz.context import build_viewer_context
from app.authz.filtered_provider import PolicyFilteredProvider
from app.config import get_settings
from app.deps import get_provider
from app.policies.models import ViewerContext
from app.providers.base import GraphProvider


def get_visibility_context(request: Request) -> ViewerContext:
    settings = get_settings()
    auth_enabled = get_auth_settings().S9K_AUTH_ENABLED
    user = getattr(request.state, "user", None)
    role = getattr(user, "role", None) if user is not None else None
    return build_viewer_context(
        role=role,
        auth_enabled=auth_enabled,
        default_workspace=settings.S9K_DEFAULT_WORKSPACE,
    )


def get_filtered_provider(
    request: Request,
    base: GraphProvider = Depends(get_provider),
) -> GraphProvider:
    ctx = get_visibility_context(request)
    return PolicyFilteredProvider(base, ctx)
