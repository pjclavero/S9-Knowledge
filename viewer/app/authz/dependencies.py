"""Dependencias FastAPI de autorización de contenido (visibilidad RPG).

Exponen:
  - ``get_visibility_context``: construye el ViewerContext de la petición.
  - ``get_filtered_provider`` : envuelve el provider base con la política.
  - ``get_visibility_scope``  : ámbito (workspace+partida) para material que no
                                proviene del GraphProvider (revisión, jobs).

Se apoya en el provider base (``app.deps.get_provider``) y en la identidad ya
inyectada por el middleware de auth en ``request.state.user``.

Con auth DESACTIVADA el contexto es ANÓNIMO: mínimo privilegio. Esta línea decía
lo contrario --"el contexto es ``admin_full`` (visor abierto heredado)"-- y
siguió diciéndolo después de que P0-AUTH cerrase esa vía, que es la peor clase
de comentario obsoleto: describe una concesión de autoridad, en el módulo que
construye el contexto, y quien lo leyera montaría su banco de medida sobre una
premisa falsa. Sin autenticación no hay principal, luego no hay autoridad.

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
from app.policies.models import NO_APLICA, ViewerContext
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
    # T2: la progresión de campaña sale del SERVIDOR (la concesión de partida),
    # no de la petición. Antes no la poblaba nadie: `max_visible_session` era
    # siempre None, así que la regla de sesión futura no se evaluaba jamás, y
    # `active_character` tampoco, con lo que `knows()` devolvía siempre False y
    # todo el mecanismo `known_by` era inerte en producción.
    tope, personaje = _progresion_de_campana(request, active_partida)
    return build_viewer_context(
        role=role,
        auth_enabled=auth_enabled,
        default_workspace=settings.S9K_DEFAULT_WORKSPACE,
        active_partida=active_partida,
        max_visible_session=tope,
        active_character=personaje,
    )


def _progresion_de_campana(
    request: Request, partida_id: Optional[str]
) -> tuple[object, Optional[str]]:
    """``(max_visible_session, character_id)`` de la concesión vigente.

    El tope se devuelve en TRI-ESTADO (7ª ronda): un entero, ``NO_APLICA``, o
    ``0``. Nunca ``None`` "sin tope": esa lectura dejaba a un usuario
    autenticado SIN partida activa menos restringido que un anónimo, que sí
    recibía 0. Un permiso que crece al quitarle contexto al lector es un fallo
    abierto por definición.
    """
    if not partida_id:
        # Sin partida activa el contenido de partida ya está fuera de alcance
        # (regla 2b: `allowed_partida_ids` vacío). El tope NO APLICA, y se
        # declara como tal en vez de devolver un `None` que el motor leía como
        # "sin tope".
        return NO_APLICA, None
    user = getattr(request.state, "user", None)
    if user is None or getattr(user, "id", None) is None:
        return 0, None
    from app.auth import db as auth_db

    workspace = get_settings().S9K_DEFAULT_WORKSPACE
    db_path = Path(get_auth_settings().S9K_AUTH_DB_PATH)
    if not db_path.exists():
        return 0, None
    try:
        with auth_db.get_conn(db_path) as conn:
            return auth_db.partida_progress(conn, user.id, workspace, partida_id)
    except Exception:
        # Si no se puede leer la progresión se aplica el tope más restrictivo.
        # Devolver `None` aquí "para no inventar un tope" inventaba el más
        # permisivo de todos, que es el error de sentido que ya se corrigió un
        # nivel más abajo: no poder comprobar algo nunca concede.
        return 0, None


def get_filtered_provider(
    request: Request,
    base: GraphProvider = Depends(get_provider),
) -> GraphProvider:
    ctx = get_visibility_context(request)
    return PolicyFilteredProvider(base, ctx)


def get_visibility_scope(request: Request) -> VisibilityScope:
    """Ámbito visible para material fuera del grafo (revisión, glosario, jobs)."""
    return VisibilityScope(get_visibility_context(request))
