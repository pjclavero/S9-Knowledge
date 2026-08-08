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

DENY = "deny"            # estado terminal (M5b): nunca visible por la vía normal

ALL_LEVELS = (PLAYER, NARRATOR, SECRET, REFERENCE)
#: Vocabulario COMPLETO admisible en la propiedad `visibility` de un nodo.
#: Cualquier otro valor --incluida su ausencia-- es dato invalido, no un nivel
#: mas permisivo. Debe coincidir con `VisibilityLevel` del contrato
#: `contracts/knowledge-visibility/v1`.
ALL_STORED_LEVELS = ALL_LEVELS + (DENY,)

# --- Ámbito del dato (campo `scope`) ----------------------------------------
# M5c: declaración POSITIVA de ámbito. Antes se infería "sin `partida_id` =
# lore compartido", y esa inferencia hacía indistinguibles dos cosas que no lo
# son: un dato deliberadamente compartido entre partidas y un dato al que se le
# perdió el ámbito por el camino (o que nunca lo tuvo). Para una decisión de
# autorización esa ambigüedad es inaceptable, así que el ámbito se declara.
SCOPE_GAME = "juego"        # lore compartido: visible desde cualquier partida del workspace
SCOPE_PARTIDA = "partida"   # material privado de una partida: exige `partida_id`
ALL_SCOPES = (SCOPE_GAME, SCOPE_PARTIDA)


def known_by_of(node: dict[str, Any]) -> tuple[tuple[str, ...], bool]:
    """Lee `known_by` de un nodo. Devuelve ``(personajes, es_válido)``.

    Ausente o ``None`` es válido y significa "nadie lo conoce explícitamente",
    no "dato corrupto": es el estado normal de casi todo el grafo.

    Cualquier otra forma es dato inválido y **no se corrige sola**. Convertir
    ``"PJ01"`` en ``["PJ01"]`` sería una reparación automática dentro de una
    decisión de autorización, y una reparación que adivina puede ampliar
    permisos. Nótese además que ``"PJ01" in "companeros_de_PJ01"`` es cierto
    para una cadena y que ``x in {...}`` mira las claves de un dict: sin tipar,
    la pertenencia significa cosas distintas según el tipo que llegue.

    Se leen DOS campos porque hay dos escritores: `known_by` (writer V3) y
    `known_by_characters` (`ingest_rpg`, que produce los nodos `:Entity` que el
    visor lee de verdad). Ambos DEBEN estar declarados en la proyección del
    proveedor: el respaldo estuvo un tiempo leyendo un campo que el serializador
    no transportaba, es decir, exactamente el defecto de H1 pero dentro de la
    red puesta para impedirlo. Un campo que el motor lee y la proyección no
    lleva es una barrera apagada en silencio, dé el resultado que dé.
    """
    raw = node.get("known_by")
    if raw is None:
        raw = node.get("known_by_characters")
    if raw is None:
        return (), True
    if not isinstance(raw, (list, tuple)):
        return (), False
    if not all(isinstance(x, str) and x.strip() for x in raw):
        return (), False
    return tuple(raw), True


@dataclass(frozen=True)
class ViewerContext:
    """Contexto de autorización del espectador para una petición.

    Todas las dimensiones son explícitas: el motor NO consulta roles ni sesiones
    por su cuenta; ``app.authz.context`` traduce (rol, personaje activo) a este
    contexto antes de invocar el motor.
    """

    role: str = "anonymous"  # admin | reviewer | viewer | anonymous
    allowed_workspaces: frozenset[str] = field(default_factory=frozenset)
    # M5a — aislamiento entre partidas (docs/v3/49-multipartida-diseno.md §2.6).
    # Partida activa de la sesión y conjunto de partidas que esa partida activa
    # autoriza a ver (en la práctica, un único elemento: la propia partida
    # activa, o vacío si no hay ninguna seleccionada -> solo capa juego).
    active_partida: Optional[str] = None
    allowed_partida_ids: frozenset[str] = field(default_factory=frozenset)
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

        Un ``known_by`` malformado NO concede conocimiento: devuelve ``False``.
        Quien necesite distinguir "no conoce" de "el dato está corrupto" debe
        usar :func:`known_by_of`; el motor lo hace para denegar el nodo entero.
        """
        if self.active_character is None:
            return False
        # `id` entra en un `in` contra un frozenset: una lista daba
        # `TypeError: unhashable type`. Era el ÚNICO campo que el motor consume
        # sin tipar, y precisamente el que la red inversa descartaba a mano por
        # considerarlo "identidad, no autorización". Se consume dentro de una
        # decisión de autorización, así que se tipa como todos los demás.
        nid = node.get("id")
        if isinstance(nid, str) and nid in self.character_knowledge:
            return True
        known_by, valido = known_by_of(node)
        if not valido:
            return False
        return self.active_character in known_by


@dataclass(frozen=True)
class VisibilityDecision:
    """Resultado de evaluar la política sobre un nodo/relación."""

    visible: bool
    reason: str

    def __bool__(self) -> bool:  # permite `if decision:`
        return self.visible
