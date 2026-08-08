"""Registro DECLARATIVO de las dimensiones de autorización (M5b-C).

Este módulo es la referencia autoritativa del modelo de autorización, y existe
por una razón concreta: cinco dictámenes independientes consecutivos
encontraron la misma forma de fallo, nunca la misma línea de código.

    se implementa una barrera
      → se prueba el componente
        → queda verde
          → otro tramo de la cadena no transporta / no produce / no aplica
            → la barrera es decorativa o falla abierta

Los casos reales, para que no se lea como una abstracción:

  H1  el serializador de Neo4j descartaba `partida_id`: el aislamiento entre
      partidas no se evaluaba NUNCA sobre datos reales, con 675 tests verdes.
  H2  `_rel_to_dict` no llevaba `visibility`: toda relación era inválida.
  T1  el motor leía `party` / `is_public` / `session_index` y NINGÚN escritor
      los producía. Dos reglas enteras evaluándose sobre campos inexistentes.
  H-A `max_visible_session` tenía columna, lector y pruebas, y ningún escritor.
  H-B un valor corrupto se degradaba a `None`, que significaba "sin tope": el
      dato ilegible ABRÍA la barrera.

La conclusión operativa es que **una dimensión de autorización no es un campo:
es una cadena**. Autoridad → productor → persistencia → transporte → contexto →
consumidor, más una respuesta declarada a "¿y si falta?" y "¿y si es inválido?".
Un solo eslabón roto la convierte en decoración, y ninguna prueba de componente
lo detecta porque cada componente, por separado, está bien.

Declarar la cadena aquí permite comprobarla en las DOS direcciones (ver
`tests/test_registro_de_autorizacion.py`):

    el motor consulta un campo  → debe estar declarado, y el provider debe
                                  transportarlo
    el registro declara un campo → deben existir productor, consumidor y prueba
                                  de ausencia/invalidez

Sustituye a la red anterior, que buscaba el nombre del campo por todo el
repositorio con `grep`. Aquella falló dos veces: contaba ficheros de prueba como
"productor real" (el defecto de H1 dentro de la red contra H1) y se conformaba
con una mención en un comentario o en una lista de prohibición.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


#: Qué hacer cuando el dato NO está. Nunca "lo más permisivo": esa fue la
#: inferencia que hubo que arrancar del ámbito (M5c) y del tope de sesión (H-B).
DENY = "DENY"                  # sin el dato no se puede autorizar
MINIMO = "MINIMO_PRIVILEGIO"   # se aplica el valor más restrictivo (p.ej. 0)
NEUTRO = "NEUTRO"              # su ausencia no cambia la decisión, y está razonado


@dataclass(frozen=True)
class PolicyField:
    """Una dimensión de autorización, con su cadena completa declarada."""

    name: str
    #: Quién tiene la ÚLTIMA palabra sobre el valor. "servidor" significa que el
    #: cliente no puede influir en él por ningún camino.
    authority: str
    #: Módulo/ruta que lo ESCRIBE. Nunca un fixture ni un test.
    producer: str
    #: Dónde vive de forma persistente.
    storage: str
    #: Quién lo consume para decidir.
    consumer: str
    #: Qué ocurre si falta, y qué ocurre si está pero es inválido.
    missing: str
    malformed: str
    #: Cómo se retira. `None` = la dimensión no se revoca (es del dato, no de
    #: una concesión).
    revocation: Optional[str] = None
    #: ¿Viaja en la proyección del provider? Las dimensiones del CONTEXTO no
    #: son campos de nodo: esa distinción es justo la que dejó pasar H-A.
    in_projection: bool = True
    applies_to: frozenset[str] = field(default_factory=lambda: frozenset({"node", "relationship"}))
    #: Sólo obligatorio bajo estos ámbitos (vacío = siempre).
    required_for_scopes: frozenset[str] = field(default_factory=frozenset)
    #: Nombre con el que el PRODUCTOR lo escribe, cuando no coincide con el
    #: nombre de la dimensión. Declararlo es obligatorio: un campo que se
    #: escribe con un nombre y se lee con otro es exactamente T1 --el motor leía
    #: `session_index` mientras la ingesta escribía `known_from_session`--, y un
    #: renombrado tácito rompe la cadena sin que nada se ponga rojo.
    stored_as: Optional[str] = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Dimensiones del DATO: viajan en el nodo/relación y las escribe la ingesta.
# ---------------------------------------------------------------------------

CAMPOS_DEL_DATO: tuple[PolicyField, ...] = (
    PolicyField(
        name="workspace",
        authority="servidor",
        producer="data-engine/app/knowledge_v3/writer/cypher.py",
        storage="Neo4j (propiedad de nodo/relación)",
        consumer="policies/engine.py + acotado en el propio Cypher",
        missing=DENY,
        malformed=DENY,
        revocation="inmediata (se recalcula en cada petición)",
        notes=(
            "El workspace efectivo del LECTOR sale del servidor, nunca de un "
            "parámetro de la petición. Doble barrera: acotado en Cypher y "
            "comprobado después por la política."
        ),
    ),
    PolicyField(
        name="scope",
        authority="contrato V3",
        producer="data-engine/app/knowledge_v3/writer/visibility.py (scope_props)",
        storage="Neo4j",
        consumer="policies/engine.py",
        missing=DENY,
        malformed=DENY,
        notes=(
            "Declaración POSITIVA (`juego`|`partida`). Antes se infería de la "
            "ausencia de `partida_id`, lo que hacía indistinguible un dato "
            "compartido a propósito de uno que perdió su ámbito."
        ),
    ),
    PolicyField(
        name="partida_id",
        authority="contrato V3",
        producer="data-engine/app/knowledge_v3/writer/visibility.py (scope_props)",
        storage="Neo4j",
        consumer="policies/engine.py",
        missing=DENY,
        malformed=DENY,
        required_for_scopes=frozenset({"partida"}),
        notes=(
            "Obligatorio bajo `scope=partida`; PROHIBIDO bajo `scope=juego` "
            "(un dato que dice ser de todos y de una a la vez se resolvería "
            "hacia lo más abierto)."
        ),
    ),
    PolicyField(
        name="visibility",
        authority="contrato V3",
        producer="data-engine/app/knowledge_v3/writer/visibility.py (stamp)",
        storage="Neo4j",
        consumer="policies/engine.py",
        missing=DENY,
        malformed=DENY,
        revocation="explícita (`deny`, que es terminal incluso para admin)",
        notes="Vocabulario cerrado: player|narrator|secret|reference|deny.",
    ),
    PolicyField(
        name="known_by",
        authority="concesiones de conocimiento",
        producer="data-engine/app/knowledge_v3/writer/visibility.py (stamp)",
        storage="Neo4j",
        consumer="policies/models.py (known_by_of) + engine.py",
        missing=NEUTRO,
        malformed=DENY,
        revocation="por concesión",
        notes=(
            "Ausente es el estado normal de casi todo el grafo, así que su "
            "ausencia es NEUTRA y está razonada. Malformado deniega el nodo "
            "entero: no se repara solo, porque una reparación que adivina "
            "dentro de una decisión de autorización puede ampliar permisos."
        ),
    ),
    PolicyField(
        name="known_by_characters",
        authority="concesiones de conocimiento",
        producer="data-engine/app/ingest_rpg.py",
        storage="Neo4j",
        consumer="policies/models.py (known_by_of)",
        missing=NEUTRO,
        malformed=DENY,
        revocation="por concesión",
        notes=(
            "Segundo nombre del mismo dato, escrito por la ingesta de rol en "
            "los nodos `:Entity` que el visor lee de verdad. Estuvo leído por "
            "el motor y NO transportado por la proyección (G3)."
        ),
    ),
    PolicyField(
        name="known_from_session",
        authority="concesiones de conocimiento",
        producer="data-engine/app/knowledge_v3/writer/visibility.py (revelacion_props)",
        storage="Neo4j",
        consumer="policies/engine.py",
        missing=DENY,
        malformed=DENY,
        required_for_scopes=frozenset({"partida"}),
        notes=(
            "Desde qué sesión puede REVELARSE, no a qué episodio pertenece "
            "(`session_index`). El writer rechaza contenido de partida que no "
            "la declare, antes de llegar a Neo4j."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Dimensiones del CONTEXTO: no son campos de nodo. La distinción importa porque
# la primera red anti-reincidencia sólo miraba campos de nodo, y por eso no
# habría detectado H-A (su propio docstring lo admitía).
# ---------------------------------------------------------------------------

CAMPOS_DEL_CONTEXTO: tuple[PolicyField, ...] = (
    PolicyField(
        name="max_visible_session",
        authority="servidor (concesión de partida)",
        producer="viewer/app/auth/db.py (grant_partida_access) + routers/admin.py",
        storage="auth.db, tabla partida_access (esquema v3)",
        consumer="policies/engine.py vía authz/dependencies.py",
        missing=MINIMO,
        malformed=MINIMO,
        revocation="inmediata (se relee de la concesión en cada petición)",
        in_projection=False,
        applies_to=frozenset(),
        notes=(
            "Sin tope declarado el tope es 0. `NULL` NO significa 'sin tope': "
            "esa lectura dejaba la barrera apagada para toda concesión anterior "
            "a la migración, que son justo las que motivaron el hallazgo. Ver "
            "futuro exige `can_view_future` explícito."
        ),
    ),
    PolicyField(
        name="active_character",
        authority="servidor (concesión de partida)",
        producer="viewer/app/auth/db.py (grant_partida_access) + routers/admin.py",
        storage="auth.db, partida_access.character_id",
        consumer="policies/models.py (ViewerContext.knows)",
        missing=MINIMO,
        malformed=MINIMO,
        revocation="inmediata; reconceder declara el estado completo",
        stored_as="character_id",
        in_projection=False,
        applies_to=frozenset(),
        notes=(
            "Sin personaje no se concede conocimiento individual. Salta la "
            "regla de NIVEL, así que una concesión que no se puede revocar ni "
            "se ve en el panel es un bypass invisible."
        ),
    ),
    PolicyField(
        name="allowed_partida_ids",
        authority="servidor (partida activa reverificada)",
        producer="viewer/app/routers/partida.py + auth/db.py",
        storage="auth.db (partida_access + sessions.active_partida)",
        consumer="policies/engine.py",
        missing=MINIMO,
        malformed=MINIMO,
        revocation="inmediata: se reverifica contra partida_access en cada petición",
        stored_as="partida_id",
        in_projection=False,
        applies_to=frozenset(),
    ),
    PolicyField(
        name="can_view_future",
        authority="servidor (rol)",
        producer="viewer/app/authz/context.py",
        storage="derivado del rol, no persistido como dato de contenido",
        consumer="policies/engine.py",
        missing=MINIMO,
        malformed=MINIMO,
        revocation="inmediata (cambio de rol)",
        in_projection=False,
        applies_to=frozenset(),
        notes="Única vía positiva para ver material no revelado.",
    ),
    PolicyField(
        name="can_view_secret",
        authority="servidor (rol)",
        producer="viewer/app/authz/context.py",
        storage="derivado del rol",
        consumer="policies/engine.py",
        missing=MINIMO,
        malformed=MINIMO,
        revocation="inmediata (cambio de rol)",
        in_projection=False,
        applies_to=frozenset(),
    ),
    PolicyField(
        name="allowed_workspaces",
        authority="servidor",
        producer="viewer/app/authz/context.py (desde configuración del servidor)",
        storage="configuración del despliegue",
        consumer="policies/engine.py + neo4j_provider (acotado en Cypher)",
        missing=MINIMO,
        malformed=MINIMO,
        revocation="inmediata",
        in_projection=False,
        applies_to=frozenset(),
    ),
)


TODOS: tuple[PolicyField, ...] = CAMPOS_DEL_DATO + CAMPOS_DEL_CONTEXTO

POR_NOMBRE: dict[str, PolicyField] = {c.name: c for c in TODOS}

#: Dimensiones RETIRADAS. Se declaran para que no vuelvan por la puerta de
#: atrás: si alguien las reintroduce en el motor, el registro no las reconoce y
#: la comprobación bidireccional se pone roja.
RETIRADAS: dict[str, str] = {
    "party": (
        "T1: era una ACL dinámica. Pertenecer al grupo daba acceso a todo lo "
        "que ese grupo supo alguna vez, y quien se incorpora en la sesión 20 no "
        "conoce el secreto de la 3. La party pasa a ser fuente de concesiones."
    ),
    "is_public": "T1: acompañaba a la ACL de party; deja de ser autoritativo.",
    "session_index": (
        "T2: sustituido por `known_from_session`. Decía a qué episodio "
        "pertenece algo, no desde cuándo puede revelarse; ningún escritor lo "
        "producía y la regla se evaluaba sobre un campo inexistente."
    ),
}
