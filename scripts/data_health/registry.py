"""Registro DECLARATIVO de los campos de DATO del grafo (carril J).

Por qué un registro propio y no `viewer/app/policies/registry.py`
-----------------------------------------------------------------
El registro de M5b modela **dimensiones de autorización**: su vocabulario es
`authority` (quién manda sobre el valor), `revocation` (cómo se retira una
concesión), `missing=DENY/MINIMO/NEUTRO` (qué decide el motor de política si
falta el dato) y dos pruebas obligatorias de comportamiento del motor. Todo eso
sólo tiene sentido si el campo participa en una DECISIÓN de acceso.

La mayoría de los campos que aquí importan —`canonical_name`, `entity_type`,
`description`, `confidence`, `source_document`, `source_hash`,
`extractor_version`, `created_at`, `review_status`— no autorizan nada. No tienen
autoridad ni revocación, y "qué pasa si falta" no es DENY/MINIMO/NEUTRO sino
"el dato está incompleto y hay que decir de qué gravedad". Forzarlos dentro de
`PolicyField` obligaría a inventar `authority="servidor"` y
`revocation=None` para todos ellos, que es ruido, y —más grave— a rellenar
`prueba_negativa`/`prueba_http`, que en M5b son obligatorias y ejercen el motor
de política. Un campo de calidad de datos no tiene motor de política que
ejercer: la prueba se convertiría en decoración, exactamente el fallo que aquel
registro existe para impedir.

Lo que SÍ se reutiliza es el **método**, que es lo transferible: una garantía de
datos tampoco es un campo, es una cadena

    productor → persistencia → serializador → consumidor → semántica de ausencia

y hay que comprobarla en las dos direcciones (campo declarado sin productor
real; campo consumido que nadie declara). Por eso `DataField` conserva la forma
de la cadena y descarta el vocabulario de autorización.

Los campos que sí son de autorización (`workspace`, `visibility`, `scope`,
`partida_id`, `known_by`, `known_from_session`) aparecen aquí SOLO con su faceta
de dato (obligatoriedad y vocabulario) y con `authz=True`, y este comprobador
NO duplica ni reinterpreta su semántica de decisión: la autoridad sobre eso
sigue siendo el registro de M5b, que no se toca.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .report import CRITICAL, WARNING, INFO

#: Qué significa que el campo NO esté presente. Declararlo es obligatorio: la
#: ausencia sin semántica declarada es justo cómo un hueco se lee como "bien".
AUSENCIA_ROMPE = "ROMPE"        # sin él el registro es inutilizable → CRITICAL
AUSENCIA_DEGRADA = "DEGRADA"    # se pierde trazabilidad/calidad → WARNING
AUSENCIA_TOLERADA = "TOLERADA"  # opcional de verdad, y razonado → INFO/nada

_NIVEL_POR_AUSENCIA = {
    AUSENCIA_ROMPE: CRITICAL,
    AUSENCIA_DEGRADA: WARNING,
    AUSENCIA_TOLERADA: INFO,
}


@dataclass(frozen=True)
class DataField:
    """Un campo de dato con su cadena completa declarada."""

    name: str
    #: Módulo que lo ESCRIBE de verdad. Nunca un fixture ni un test (en M5b,
    #: contar un test como productor fue el defecto H1 dentro de la red anti-H1).
    producer: str
    #: Dónde vive de forma persistente.
    storage: str
    #: Qué serializador debe transportarlo hacia el consumidor. `None` = no
    #: viaja en la proyección a propósito (y entonces no se exige).
    serializer: Optional[str]
    #: Quién lo lee. `None` = nadie lo consume todavía (candidato a campo muerto).
    consumer: Optional[str]
    #: Semántica de ausencia declarada.
    ausencia: str
    #: Validador del valor; devuelve None si es válido o un motivo si no.
    validador: Optional[Callable[[object], Optional[str]]] = None
    applies_to: frozenset[str] = field(default_factory=lambda: frozenset({"node"}))
    #: Nombre con el que el productor lo escribe, si difiere (renombrado tácito
    #: = cadena rota en silencio; en M5b fue T1).
    stored_as: Optional[str] = None
    #: True si además es dimensión de autorización: su semántica de decisión la
    #: gobierna `viewer/app/policies/registry.py`, no este comprobador.
    authz: bool = False
    notas: str = ""

    @property
    def nivel_si_falta(self) -> str:
        return _NIVEL_POR_AUSENCIA[self.ausencia]

    @property
    def nombre_en_productor(self) -> str:
        return self.stored_as or self.name


# --- validadores ------------------------------------------------------------

def _no_vacio(v: object) -> Optional[str]:
    if v is None:
        return "ausente"
    if isinstance(v, str) and not v.strip():
        return "cadena vacía"
    return None


def _confianza(v: object) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return f"no numérico: {v!r}"
    if not (0.0 <= float(v) <= 1.0):
        return f"fuera de [0,1]: {v!r}"
    return None


def _entero_no_negativo(v: object) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        return f"no es entero: {v!r}"
    if v < 0:
        return f"negativo: {v!r}"
    return None


def _lista_de_texto(v: object) -> Optional[str]:
    if v is None:
        return None
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        return f"no es lista de cadenas: {v!r}"
    return None


def _en(vocabulario: frozenset[str], etiqueta: str) -> Callable[[object], Optional[str]]:
    def _v(v: object) -> Optional[str]:
        if v is None:
            return None
        if not isinstance(v, str) or v not in vocabulario:
            return f"valor fuera del vocabulario {etiqueta}: {v!r}"
        return None
    return _v


#: Vocabularios. Se cargan del esquema real del motor; si no se puede importar,
#: `VOCABULARIOS_DISPONIBLES` queda a False y las comprobaciones de vocabulario
#: se reportan UNKNOWN (nunca OK).
VOCABULARIOS_DISPONIBLES = True
try:  # pragma: no cover - depende del sys.path de ejecución
    from schemas.rpg_schema import (  # type: ignore
        ALLOWED_NODE_TYPES,
        ALLOWED_RELATION_TYPES,
        ALLOWED_REVIEW_STATUS,
        ALLOWED_VISIBILITY,
        ALLOWED_KNOWLEDGE_LAYER,
    )
except Exception:  # noqa: BLE001
    VOCABULARIOS_DISPONIBLES = False
    ALLOWED_NODE_TYPES = frozenset()
    ALLOWED_RELATION_TYPES = frozenset()
    ALLOWED_REVIEW_STATUS = frozenset()
    ALLOWED_VISIBILITY = frozenset()
    ALLOWED_KNOWLEDGE_LAYER = frozenset()

#: Ámbitos conocidos (multi-partida). `lore` = material de juego compartido;
#: `juego`/`partida` = material de una partida concreta.
AMBITOS_CONOCIDOS = frozenset({"lore", "juego", "partida"})

NODO_Y_REL = frozenset({"node", "relationship"})

CAMPOS: tuple[DataField, ...] = (
    # --- identidad ---------------------------------------------------------
    DataField(
        name="entity_id",
        producer="data-engine/app/knowledge_v3/writer/cypher.py",
        storage="Neo4j (propiedad de :Entity)",
        serializer="viewer/app/providers/neo4j_provider.py::_node_to_dict",
        consumer="data-engine/app/knowledge_v3/writer/cypher.py",
        ausencia=AUSENCIA_ROMPE,
        validador=_no_vacio,
        stored_as="entity_id",
        notas=(
            "Clave de negocio. Duplicarla parte la idempotencia del writer. Se "
            "declara a propósito que DEBE viajar en la proyección: el visor "
            "identifica los nodos por `elementId`, que Neo4j puede reasignar en "
            "una reescritura, así que sin `entity_id` no hay identidad estable "
            "aguas abajo."
        ),
    ),
    DataField(
        name="canonical_name",
        producer="data-engine/app/ingest_rpg.py",
        storage="Neo4j (propiedad de :Entity)",
        serializer="viewer/app/providers/neo4j_provider.py::_node_to_dict",
        consumer="viewer/app/providers/neo4j_provider.py",
        ausencia=AUSENCIA_ROMPE,
        validador=_no_vacio,
        notas="Sin nombre canónico la entidad no es identificable ni deduplicable.",
    ),
    DataField(
        name="entity_type",
        producer="data-engine/app/ingest_rpg.py",
        storage="Neo4j (propiedad + etiqueta)",
        serializer="viewer/app/providers/neo4j_provider.py::_node_to_dict",
        consumer="viewer/app/providers/neo4j_provider.py",
        ausencia=AUSENCIA_ROMPE,
        validador=_en(ALLOWED_NODE_TYPES, "ALLOWED_NODE_TYPES"),
        notas="Un tipo desconocido rompe agrupaciones, filtros y la ontología.",
    ),
    # --- autorización (faceta de dato; la semántica vive en policies/registry) ---
    DataField(
        name="workspace",
        producer="data-engine/app/knowledge_v3/writer/cypher.py",
        storage="Neo4j (propiedad de nodo/relación)",
        serializer="viewer/app/providers/neo4j_provider.py",
        consumer="viewer/app/policies/engine.py",
        ausencia=AUSENCIA_ROMPE,
        validador=_no_vacio,
        applies_to=NODO_Y_REL,
        authz=True,
    ),
    DataField(
        name="visibility",
        producer="data-engine/app/knowledge_v3/writer/visibility.py",
        storage="Neo4j (propiedad de nodo/relación)",
        serializer="viewer/app/providers/neo4j_provider.py",
        consumer="viewer/app/policies/engine.py",
        ausencia=AUSENCIA_ROMPE,
        validador=_en(ALLOWED_VISIBILITY, "ALLOWED_VISIBILITY"),
        applies_to=NODO_Y_REL,
        authz=True,
    ),
    DataField(
        name="scope",
        producer="data-engine/app/knowledge_v3/writer/cypher.py",
        storage="Neo4j (propiedad de nodo/relación)",
        serializer="viewer/app/providers/neo4j_provider.py",
        consumer="viewer/app/policies/engine.py",
        ausencia=AUSENCIA_ROMPE,
        validador=_en(AMBITOS_CONOCIDOS, "AMBITOS_CONOCIDOS"),
        applies_to=NODO_Y_REL,
        authz=True,
    ),
    DataField(
        name="partida_id",
        producer="data-engine/app/knowledge_v3/writer/cypher.py",
        storage="Neo4j (propiedad de nodo/relación)",
        serializer="viewer/app/providers/neo4j_provider.py",
        consumer="viewer/app/policies/engine.py",
        ausencia=AUSENCIA_TOLERADA,
        validador=_no_vacio,
        applies_to=NODO_Y_REL,
        authz=True,
        notas="Obligatorio SOLO en ámbito de partida; se comprueba en D06, no aquí.",
    ),
    DataField(
        name="known_by",
        producer="data-engine/app/knowledge_v3/writer/visibility.py",
        storage="Neo4j (lista en nodo/relación)",
        serializer="viewer/app/providers/neo4j_provider.py",
        consumer="viewer/app/policies/models.py",
        ausencia=AUSENCIA_TOLERADA,
        validador=_lista_de_texto,
        applies_to=NODO_Y_REL,
        authz=True,
    ),
    DataField(
        name="known_from_session",
        producer="data-engine/app/knowledge_v3/writer/visibility.py",
        storage="Neo4j (propiedad de nodo/relación)",
        serializer="viewer/app/providers/neo4j_provider.py",
        consumer="viewer/app/policies/engine.py",
        ausencia=AUSENCIA_DEGRADA,
        validador=_entero_no_negativo,
        applies_to=NODO_Y_REL,
        authz=True,
        notas="Sesión de REVELACIÓN, no de pertenencia (no confundir con session_index).",
    ),
    # --- procedencia y calidad ---------------------------------------------
    DataField(
        name="source_document",
        producer="data-engine/app/ingest_rpg.py",
        storage="Neo4j (propiedad de nodo/relación)",
        serializer="viewer/app/providers/neo4j_provider.py",
        consumer="viewer/app/providers/neo4j_provider.py",
        ausencia=AUSENCIA_DEGRADA,
        validador=_no_vacio,
        applies_to=NODO_Y_REL,
        notas="Procedencia mínima: sin ella un dato no es auditable ni revocable.",
    ),
    DataField(
        name="confidence",
        producer="data-engine/app/ingest_rpg.py",
        storage="Neo4j (propiedad de nodo/relación)",
        serializer="viewer/app/providers/neo4j_provider.py",
        consumer="viewer/app/providers/neo4j_provider.py",
        ausencia=AUSENCIA_DEGRADA,
        validador=_confianza,
        applies_to=NODO_Y_REL,
    ),
    DataField(
        name="review_status",
        producer="data-engine/app/review/approved_writer.py",
        storage="Neo4j (propiedad de nodo/relación)",
        serializer="viewer/app/providers/neo4j_provider.py",
        consumer="viewer/app/providers/neo4j_provider.py",
        ausencia=AUSENCIA_DEGRADA,
        validador=_en(ALLOWED_REVIEW_STATUS, "ALLOWED_REVIEW_STATUS"),
        applies_to=NODO_Y_REL,
    ),
    DataField(
        name="knowledge_layer",
        producer="data-engine/app/ingest_rpg.py",
        storage="Neo4j (propiedad de :Entity)",
        serializer="viewer/app/providers/neo4j_provider.py::_node_to_dict",
        consumer="viewer/app/providers/neo4j_provider.py",
        ausencia=AUSENCIA_TOLERADA,
        validador=_en(ALLOWED_KNOWLEDGE_LAYER, "ALLOWED_KNOWLEDGE_LAYER"),
    ),
    DataField(
        name="source_hash",
        producer="data-engine/app/ingest_rpg.py",
        storage="Neo4j (propiedad de :Entity)",
        serializer="viewer/app/providers/neo4j_provider.py::_node_to_dict",
        consumer=None,
        ausencia=AUSENCIA_TOLERADA,
        notas="Declarado sin consumidor: candidato a campo generado que nadie lee.",
    ),
    DataField(
        name="extractor_version",
        producer="data-engine/app/ingest_rpg.py",
        storage="Neo4j (propiedad de :Entity)",
        serializer="viewer/app/providers/neo4j_provider.py::_node_to_dict",
        consumer=None,
        ausencia=AUSENCIA_TOLERADA,
        notas="Idem: procedencia técnica generada, sin consumidor declarado.",
    ),
    DataField(
        name="created_at",
        producer="data-engine/app/ingest_rpg.py",
        storage="Neo4j (propiedad de :Entity)",
        serializer="viewer/app/providers/neo4j_provider.py::_node_to_dict",
        consumer=None,
        ausencia=AUSENCIA_TOLERADA,
    ),
)

CAMPOS_POR_NOMBRE: dict[str, DataField] = {c.name: c for c in CAMPOS}

#: Vocabulario cerrado por campo. Se usa además para la comprobación de cadena
#: C06: un productor que escribe un literal fuera del vocabulario que el
#: consumidor valida rompe la cadena en el eslabón de la SEMÁNTICA, aunque
#: productor y consumidor pasen sus tests por separado.
VOCABULARIO_POR_CAMPO: dict[str, frozenset[str]] = {
    "visibility": ALLOWED_VISIBILITY,
    "review_status": ALLOWED_REVIEW_STATUS,
    "knowledge_layer": ALLOWED_KNOWLEDGE_LAYER,
    "entity_type": ALLOWED_NODE_TYPES,
    "scope": AMBITOS_CONOCIDOS,
}


def campos_de(elemento: str) -> tuple[DataField, ...]:
    return tuple(c for c in CAMPOS if elemento in c.applies_to)


#: Alias de dataset → nombre canónico del registro. Los fixtures del visor usan
#: la proyección del serializador (`id`, `type`, `label`), no las propiedades de
#: Neo4j. Declarar la traducción es obligatorio: si se dejara implícita, el
#: comprobador diría "falta entity_type" sobre datos correctos, y eso enseña a
#: ignorar el rojo.
ALIAS_DE_PROYECCION: dict[str, str] = {
    "id": "entity_id",
    "type": "entity_type",
    "label": "canonical_name",
}
