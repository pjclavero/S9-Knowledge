"""Construcción del ViewerContext a partir de la identidad y el rol.

Mapa rol -> capacidades (slice inicial; ampliable con datos reales de personaje):

  admin     : admin_full (ve todo).
  reviewer  : ve player/narrator/reference y sesiones futuras (necesita revisar),
              PERO no secretos RPG ajenos salvo permiso explícito.
  viewer    : sólo conocimiento permitido: player + reference; nada de secreto,
              narrator ni futuro; acotado a su party y a lo que su personaje sabe.
  anonymous : no ve contenido protegido; sólo lo público de sesiones publicadas.

IMPORTANTE compatibilidad: con S9K_AUTH_ENABLED=false el visor es público
(comportamiento heredado). En ese caso se devuelve un contexto `admin_full`
para no alterar el visor abierto existente; la aplicación real de la política
se activa cuando la autenticación está encendida.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from app.policies.models import (
    NO_APLICA,
    NO_APLICABLE,
    VALOR,
    ViewerContext,
    estado_de_entero_no_negativo,
)


def _ws_set(workspaces: Iterable[str]) -> frozenset[str]:
    return frozenset(w for w in workspaces if w)


def _tope_minimo(valor: Any) -> Any:
    """Tope de sesión del anónimo: mínimo privilegio, conservando el tri-estado.

    Un valor legible se respeta; ``NO_APLICA`` (declarado: sin partida activa)
    se conserva porque es un estado, no un hueco; cualquier otra cosa --incluido
    ``None``-- se convierte en 0. El anónimo nunca tiene partida activa, así que
    en la práctica no ve contenido de partida por ninguna de las tres vías.
    """
    estado = estado_de_entero_no_negativo(valor)
    if estado == VALOR:
        return valor
    if estado == NO_APLICABLE:
        return NO_APLICA
    return 0


def build_viewer_context(
    *,
    role: Optional[str],
    auth_enabled: bool,
    default_workspace: str,
    allowed_workspaces: Optional[Iterable[str]] = None,
    active_character: Optional[str] = None,
    max_visible_session: Any = None,
    party_membership: Optional[Iterable[str]] = None,
    character_knowledge: Optional[Iterable[str]] = None,
    simulated: bool = False,
    active_partida: Optional[str] = None,
) -> ViewerContext:
    """Traduce identidad + parámetros de campaña a un ViewerContext inmutable.

    ``active_partida``: partida seleccionada por el usuario en la sesión (M5a,
    docs/v3/49 §2.6). Solo la partida activa entra en ``allowed_partida_ids``
    -- un usuario con varias partidas asignadas ve, en cada momento, la que
    tiene activa (más la capa juego compartida), nunca varias a la vez. Sin
    partida activa -> solo capa juego.
    """

    workspaces = _ws_set(allowed_workspaces or [default_workspace])
    parties = frozenset(party_membership or [])
    knowledge = frozenset(character_knowledge or [])
    # Una partida en blanco ("" / espacios) NO es una partida: se normaliza a
    # None (capa juego) para que nunca entre en allowed_partida_ids y no pueda
    # actuar como comodín frente a datos con partida_id="" (M5a P1).
    if isinstance(active_partida, str) and not active_partida.strip():
        active_partida = None
    partidas = frozenset({active_partida}) if active_partida else frozenset()

    # Visor abierto (auth desactivada): comportamiento heredado = todo visible.
    # La simulación "ver como personaje" NUNCA usa este atajo.
    if not auth_enabled and not simulated:
        return ViewerContext(
            role="public",
            allowed_workspaces=workspaces,
            admin_full=True,
            session_public=True,
        )

    role = (role or "anonymous").lower()

    if role == "admin" and not simulated:
        return ViewerContext(
            role="admin",
            allowed_workspaces=workspaces,
            active_partida=active_partida,
            allowed_partida_ids=partidas,
            admin_full=True,
            session_public=True,
            can_view_secret=True,
            can_view_future=True,
            can_view_reference=True,
        )

    if role == "reviewer":
        return ViewerContext(
            role="reviewer",
            allowed_workspaces=workspaces,
            active_partida=active_partida,
            allowed_partida_ids=partidas,
            active_character=active_character,
            max_visible_session=max_visible_session,
            can_view_secret=False,       # no secretos RPG ajenos salvo permiso
            can_view_future=True,        # revisa material aún no publicado
            can_view_reference=True,
            party_membership=parties,
            character_knowledge=knowledge,
            session_public=True,
            simulated=simulated,
        )

    if role == "viewer":
        return ViewerContext(
            role="viewer",
            allowed_workspaces=workspaces,
            active_partida=active_partida,
            allowed_partida_ids=partidas,
            active_character=active_character,
            max_visible_session=max_visible_session,
            can_view_secret=False,
            can_view_future=False,
            can_view_reference=True,
            party_membership=parties,
            character_knowledge=knowledge,
            session_public=True,
            simulated=simulated,
        )

    # Anónimo / rol desconocido: mínimo privilegio. Sólo lo público de sesiones
    # ya publicadas; sin secretos, narrador, futuro ni referencia. Nunca tiene
    # partida activa: el anónimo solo ve la capa juego.
    return ViewerContext(
        role="anonymous",
        allowed_workspaces=workspaces,
        active_partida=None,
        allowed_partida_ids=frozenset(),
        active_character=None,
        max_visible_session=_tope_minimo(max_visible_session),
        can_view_secret=False,
        can_view_future=False,
        can_view_reference=False,
        party_membership=frozenset(),
        character_knowledge=frozenset(),
        session_public=True,
        simulated=simulated,
    )


def context_for_simulated_character(
    *,
    default_workspace: str,
    allowed_workspaces: Optional[Iterable[str]],
    active_character: str,
    max_visible_session: Any,
    party_membership: Optional[Iterable[str]],
    character_knowledge: Optional[Iterable[str]],
) -> ViewerContext:
    """Contexto que un admin usa para 'ver como' un personaje jugador concreto.

    Aplica exactamente las mismas restricciones que un ``viewer`` encarnando a
    ese personaje: admin_full queda DESACTIVADO. Es de solo lectura y se audita.
    """
    return build_viewer_context(
        role="viewer",
        auth_enabled=True,
        default_workspace=default_workspace,
        allowed_workspaces=allowed_workspaces,
        active_character=active_character,
        max_visible_session=max_visible_session,
        party_membership=party_membership,
        character_knowledge=character_knowledge,
        simulated=True,
    )
