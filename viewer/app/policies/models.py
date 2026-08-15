"""Modelos del motor de política de visibilidad.

`ViewerContext` reúne las ONCE dimensiones de política:

    allowed_workspaces, active_character, max_visible_session, can_view_secret,
    can_view_future, can_view_reference, can_view_lore, party_membership,
    character_knowledge, session_public, admin_full

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


# --- Tri-estado de una dimensión de autorización (M5b-C, 7ª ronda) ----------
# `None` estaba significando TRES cosas a la vez en `max_visible_session`:
#   (a) "no hay partida activa, el tope no aplica",
#   (b) "la concesión no declara tope" (fila migrada con NULL),
#   (c) "no se pudo leer la concesión".
# Y el motor las trataba a las tres igual --`if ctx.max_visible_session is not
# None:`--, es decir, saltándose la regla entera. Un `None` con tres
# significados dentro de un `if` es, literalmente, una barrera que se apaga
# sola en el caso que menos se controla.
#
# A partir de aquí cada dimensión tiene tres estados DISTINGUIBLES:
VALOR = "VALUE"                       # valor válido: se aplica
NO_APLICABLE = "NOT_APPLICABLE"       # declarado explícitamente como no aplicable
AUSENTE_O_INVALIDO = "MISSING_INVALID"  # ausencia inesperada o valor inválido -> DENY


class _NoAplica:
    """Centinela para el estado NOT_APPLICABLE.

    No es `None` a propósito: un centinela propio no se puede confundir con
    "no me llegó nada", que es justo la confusión que hubo que romper. Es
    falsy para que un `if tope:` accidental tampoco lo lea como un valor.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - sólo para mensajes
        return "<no aplica>"

    def __bool__(self) -> bool:
        return False


#: Única instancia; se compara con `is`.
NO_APLICA = _NoAplica()


def estado_de_entero_no_negativo(valor: Any) -> str:
    """Clasifica una dimensión numérica de autorización en su tri-estado.

    `bool` es subclase de `int` y no es un número de sesión: `True` no puede
    colarse como tope 1.
    """
    if valor is NO_APLICA:
        return NO_APLICABLE
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
        return AUSENTE_O_INVALIDO
    return VALOR


def estado_de_identificador(valor: Any) -> str:
    """Tri-estado de una dimensión textual (p.ej. `active_character`)."""
    if valor is NO_APLICA:
        return NO_APLICABLE
    if not isinstance(valor, str) or not valor.strip():
        return AUSENTE_O_INVALIDO
    return VALOR


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
    # Tri-estado (ver `estado_de_entero_no_negativo`):
    #   int        -> VALOR: tope declarado por la concesión del servidor.
    #   NO_APLICA  -> NOT_APPLICABLE: no hay partida activa; el contenido de
    #                 partida ya está fuera de alcance por la regla 2b, así que
    #                 el tope no tiene nada que acotar. Es un estado DECLARADO.
    #   None/otro  -> MISSING_INVALID: no se pudo determinar. DENIEGA el
    #                 contenido de partida. Nunca significa "sin tope".
    max_visible_session: Any = None
    can_view_secret: bool = False
    can_view_future: bool = False
    can_view_reference: bool = False
    # LORE-ANÓNIMO-DENEGADO. Llave de la CAPA JUEGO (`scope=juego`): el lore
    # compartido del workspace. Existe porque hasta aquí la capa juego no tenía
    # llave ninguna -- se entregaba a cualquiera que superase workspace, y un
    # contexto anónimo supera workspace porque el workspace por defecto del
    # despliegue entra en `allowed_workspaces`. El efecto medido era que con
    # `S9K_AUTH_ENABLED` ausente/false el lore `player` salía en lista, contaba
    # y su ficha respondía 200 con el texto completo (docs/77 §3, docs/78 §3).
    #
    # La ausencia de partida NO puede seguir siendo la concesión: sería una vía
    # permisiva implícita justo donde ya se decidió que «auth desactivada ≠
    # acceso total». Por eso la capa juego pasa a exigir una llave POSITIVA, y
    # el valor por defecto es no conceder: una dimensión booleana de concesión
    # no puede fallar abierta si su defecto es `False`.
    #
    # Si algún día se quiere lore público, se concede aquí explícitamente y con
    # sus pruebas propias; no se recupera como fallback del sistema.
    can_view_lore: bool = False
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
        # Tri-estado tambien aqui: sin personaje LEGIBLE no se concede
        # conocimiento individual. `None`, cadena vacia, espacios o un tipo
        # inesperado son todos "no hay personaje", y ninguno puede conceder.
        if estado_de_identificador(self.active_character) != VALOR:
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
