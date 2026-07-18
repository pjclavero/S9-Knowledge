"""Modelos del motor de política de visibilidad.

`ViewerContext` reúne las DIEZ dimensiones de política del slice RC6 E2:

    allowed_workspaces, active_character, max_visible_session, can_view_secret,
    can_view_future, can_view_reference, party_membership, character_knowledge,
    session_public, admin_full

Es inmutable (``frozen=True``) para que una decisión nunca dependa de estado
mutable compartido entre peticiones.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# --- Niveles de visibilidad de un nodo/relación (campo `visibility`) ---------
PLAYER = "player"        # conocimiento de jugador: base
NARRATOR = "narrator"    # capa del narrador/GM: requiere permiso elevado
SECRET = "secret"        # secreto de trama: oculto salvo permiso explícito
REFERENCE = "reference"  # material de reglas/manual: requiere can_view_reference

ALL_LEVELS = (PLAYER, NARRATOR, SECRET, REFERENCE)


@dataclass(frozen=True)
class ViewerContext:
    """Contexto de autorización del espectador para una petición.

    Todas las dimensiones son explícitas: el motor NO consulta roles ni sesiones
    por su cuenta; ``app.authz.context`` traduce (rol, personaje activo) a este
    contexto antes de invocar el motor.
    """

    role: str = "anonymous"  # admin | reviewer | viewer | anonymous
    allowed_workspaces: frozenset[str] = field(default_factory=frozenset)
    active_character: Optional[str] = None
    max_visible_session: Optional[int] = None  # None => sin tope de sesión
    can_view_secret: bool = False
    can_view_future: bool = False
    can_view_reference: bool = False
    party_membership: frozenset[str] = field(default_factory=frozenset)
    # IDs de nodo que el personaje activo conoce (character_knowledge precomputado).
    character_knowledge: frozenset[str] = field(default_factory=frozenset)
    session_public: bool = False  # puede ver contenido marcado como público
    admin_full: bool = False      # ve absolutamente todo (bypass total)
    # Metadatos de simulación "ver como personaje" (solo lectura / auditado).
    simulated: bool = False

    def knows(self, node: dict[str, Any]) -> bool:
        """True si el personaje activo conoce explícitamente este nodo.

        Se comprueba tanto ``character_knowledge`` (IDs precomputados) como el
        campo ``known_by`` del propio nodo (lista de personajes que lo conocen).
        """
        if self.active_character is None:
            return False
        nid = node.get("id")
        if nid is not None and nid in self.character_knowledge:
            return True
        known_by = node.get("known_by") or node.get("known_by_characters") or []
        return self.active_character in known_by


@dataclass(frozen=True)
class VisibilityDecision:
    """Resultado de evaluar la política sobre un nodo/relación."""

    visible: bool
    reason: str

    def __bool__(self) -> bool:  # permite `if decision:`
        return self.visible
