"""Dependencias FastAPI de autorización de contenido (visibilidad RPG).

Exponen:
  - ``get_visibility_context``: construye el ViewerContext de la petición.
  - ``get_filtered_provider`` : envuelve el provider base con la política.
  - ``get_visibility_scope``  : ámbito (workspace+partida) para material que no
                                proviene del GraphProvider (revisión, jobs).

Se apoya en el provider base (``app.deps.get_provider``) y en la identidad ya
inyectada por el middleware de auth en ``request.state.user``. Con auth
desactivada el contexto es ``admin_full`` (visor abierto heredado).

La partida activa de la sesión se RE-VERIFICA en cada petición contra
``partida_access`` (M5a): revocar el acceso surte efecto en la siguiente
petición, no en el próximo login.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import Depends, Request

from app.auth.config import get_auth_settings
from app.authz.context import build_viewer_context
from app.authz.filtered_provider import PolicyFilteredProvider
from app.authz.scope import VisibilityScope
from app.config import get_settings
from app.deps import get_provider
from app.policies.models import ViewerContext
from app.providers.base import GraphProvider


def _still_has_access(user, partida_id: str) -> bool:
    """¿Sigue vigente el acceso del usuario a esa partida, AHORA MISMO?

    Una consulta a auth.db por petición (SQLite local, con índice único sobre
    ``user_id, workspace, partida_id``): coste asumible a cambio de que una
    revocación tenga efecto inmediato sobre las sesiones ya abiertas.

    Un admin no tiene asignaciones propias, pero tampoco puede activar una
    partida inventada: se admite cualquier partida que exista en la tabla.
    """
    from app.auth import db as auth_db

    workspace = get_settings().S9K_DEFAULT_WORKSPACE
    if not workspace or not isinstance(workspace, str) or not workspace.strip():
        # Fail-closed: sin workspace efectivo determinable, no se concede acceso.
        return False

    db_path = Path(get_auth_settings().S9K_AUTH_DB_PATH)
    if not db_path.exists():
        return False
    try:
        with auth_db.get_conn(db_path) as conn:
            if getattr(user, "is_admin", None) is not None and user.is_admin():
                return auth_db.partida_exists(conn, partida_id)
            return partida_id in auth_db.user_allowed_partidas(conn, user.id, workspace=workspace)
    except Exception:
        # Fail-closed: si no se puede comprobar el acceso, no se concede.
        return False


def _clear_active_partida(session) -> None:
    from app.auth import db as auth_db

    db_path = Path(get_auth_settings().S9K_AUTH_DB_PATH)
    try:
        with auth_db.get_conn(db_path) as conn:
            auth_db.set_session_active_partida(conn, session.id, None)
    except Exception:
        pass  # el contexto ya degradó a capa juego; la limpieza es best-effort
    try:
        session.active_partida = None
    except Exception:
        pass


def _effective_active_partida(request: Request) -> Optional[str]:
    """Partida activa REALMENTE vigente para esta petición.

    Devuelve None (capa juego) si no hay ninguna seleccionada, si el valor
    almacenado está en blanco, o si el acceso fue revocado desde que se
    seleccionó. En ese último caso limpia además ``sessions.active_partida``
    para que la degradación sea persistente y no haya que repetir la consulta.
    """
    session = getattr(request.state, "session", None)
    raw = getattr(session, "active_partida", None) if session is not None else None
    if raw is None:
        return None
    partida_id = raw.strip() if isinstance(raw, str) else raw
    if not partida_id:
        return None

    user = getattr(request.state, "user", None)
    if user is None:
        return None
    if _still_has_access(user, partida_id):
        return partida_id

    _clear_active_partida(session)
    return None


def get_visibility_context(request: Request) -> ViewerContext:
    settings = get_settings()
    auth_enabled = get_auth_settings().S9K_AUTH_ENABLED
    user = getattr(request.state, "user", None)
    role = getattr(user, "role", None) if user is not None else None
    active_partida = _effective_active_partida(request) if auth_enabled else None
    return build_viewer_context(
        role=role,
        auth_enabled=auth_enabled,
        default_workspace=settings.S9K_DEFAULT_WORKSPACE,
        active_partida=active_partida,
    )


def get_filtered_provider(
    request: Request,
    base: GraphProvider = Depends(get_provider),
) -> GraphProvider:
    ctx = get_visibility_context(request)
    return PolicyFilteredProvider(base, ctx)


def get_visibility_scope(request: Request) -> VisibilityScope:
    """Ámbito visible para material fuera del grafo (revisión, glosario, jobs)."""
    return VisibilityScope(get_visibility_context(request))
