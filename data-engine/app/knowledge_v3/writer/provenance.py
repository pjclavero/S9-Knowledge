# -*- coding: utf-8 -*-
"""Procedencia PERSISTIDA y NAVEGABLE dentro del grafo.

POR QUE EXISTE
--------------
Hasta aqui el writer escribia `V3Entity`, `V3Assertion` y `V3AppliedOperation`,
y nada mas. La evidencia que sostiene una asercion viajaba como una LISTA DE
IDENTIFICADORES (`evidence_fragment_ids`, estampada por
`executor._provenance`) que no apuntaba a ningun nodo: el literal de esa
evidencia solo existia en el `informe.json` que imprime el CLI de ingesta, un
fichero suelto que ningun componente persiste. Recuperar la fuente de un
conocimiento era, por tanto, seguir una cadena de ids a mano por fuera del
grafo.

Este modulo materializa esa cadena COMO ARISTAS, de modo que el recorrido

    (:V3Source)-[:HAS_EPISODE]->(:V3Episode)-[:HAS_FRAGMENT]->(:V3Evidence)
                                                                    ^
                                          (:V3Assertion)-[:SUPPORTED_BY]-+
                                                 |
                                    [:HAS_SUBJECT|HAS_OBJECT]
                                                 v
                                            (:V3Entity)

se resuelva con una sola consulta Cypher, en las dos direcciones.

QUE NO HACE (y por que)
-----------------------
* **No inventa un segundo modelo.** Los nodos son la proyeccion plana de tres
  contratos ya congelados --`source-asset/v3-internal-v1`,
  `source-episode/v3-internal-v1` y `evidence-fragment/v3-internal-v1`-- y las
  aristas no anaden ninguna referencia nueva: materializan las que esos mismos
  contratos YA declaran como campos (`episode.source_asset_id`,
  `fragment.episode_id`) y la que el writer YA estampa en cada asercion
  (`evidence_fragment_ids`, `subject_entity_id`, `object_entity_id`).
  CARENCIA DECLARADA: ningun contrato congelado nombra estas etiquetas ni
  estos tipos de relacion --el `graph-mutation-plan` solo admite relaciones
  entre entidades--. Se documenta como hueco de contrato, no se disfraza de
  contrato existente (ver docs/v3/54-procedencia-navegable.md).
* **No toca el plan ni su ejecucion.** `execute_plan` sigue siendo la unica
  puerta del conocimiento y su transaccion no cambia. La procedencia se
  escribe en su propia transaccion, DESPUES, y su fallo no puede dejar un
  plan a medias.
* **No abre una via de lectura nueva.** Las tres etiquetas son nuevas y el
  visor (`viewer/app/providers/neo4j_provider.py`) consulta exclusivamente
  `(n:Entity)` y `(n:Entity)-[r]->(m:Entity)`: ninguna de esas consultas
  alcanza un nodo de procedencia. Y los nodos se escriben SIN propiedad
  `visibility`, que es el estado que el motor de politicas trata como DENY.
  Exponer evidencia a un lector final exige una decision de visibilidad que
  NO es de este modulo.

IDENTIDAD DURABLE
-----------------
`(workspace, source_asset_id)`, `(workspace, episode_id)` y
`(workspace, fragment_id)`. El `elementId` de Neo4j no es identidad de nada:
no se guarda, no se devuelve y no se usa para enlazar. Las aristas se crean
emparejando por esas claves, nunca por identificador interno.

IDEMPOTENCIA
------------
Sin `MERGE` (la guardia de `cypher.assert_safe` lo prohibe y con razon: un
MERGE ciego crea o pisa segun el estado del grafo). Cada escritura comprueba
primero la ausencia, con una consulta acotada por la clave durable, y solo
entonces hace `CREATE`. Repetir el volcado no duplica ni nodos ni aristas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from . import codes
from .cypher import LABEL_ASSERTION, LABEL_ENTITY, Query, safe_props
from .errors import WriterAbort

#: Etiquetas de la cadena de procedencia. Nuevas a proposito: ninguna
#: superficie de lectura existente las consulta.
LABEL_SOURCE = "V3Source"
LABEL_EPISODE = "V3Episode"
LABEL_EVIDENCE = "V3Evidence"

#: Tipos de relacion. Cada uno materializa una referencia que ya existia como
#: campo en un contrato congelado; ninguno introduce semantica nueva.
REL_HAS_EPISODE = "HAS_EPISODE"      # source_asset_id de `source-episode`
REL_HAS_FRAGMENT = "HAS_FRAGMENT"    # episode_id de `evidence-fragment`
REL_SUPPORTED_BY = "SUPPORTED_BY"    # evidence_fragment_ids de la asercion
REL_HAS_SUBJECT = "HAS_SUBJECT"      # subject_entity_id de la asercion
REL_HAS_OBJECT = "HAS_OBJECT"        # object_entity_id de la asercion

PROVENANCE_LABELS: tuple[str, ...] = (LABEL_SOURCE, LABEL_EPISODE, LABEL_EVIDENCE)
PROVENANCE_RELATIONS: tuple[str, ...] = (
    REL_HAS_EPISODE, REL_HAS_FRAGMENT, REL_SUPPORTED_BY, REL_HAS_SUBJECT, REL_HAS_OBJECT,
)

#: Campo de identidad durable por etiqueta.
IDENTITY_FIELD: dict[str, str] = {
    LABEL_SOURCE: "source_asset_id",
    LABEL_EPISODE: "episode_id",
    LABEL_EVIDENCE: "fragment_id",
}

#: Propiedades que estampa este modulo y que un documento no puede imponer.
_STAMPED = frozenset({"workspace", "partida_id", "provenance_contract"})


@dataclass
class ProvenanceOutcome:
    """Lo que el volcado escribio DE VERDAD. Cero = ya estaba, no = fallo."""

    nodes_created: dict[str, int] = field(default_factory=dict)
    nodes_reused: dict[str, int] = field(default_factory=dict)
    relations_created: dict[str, int] = field(default_factory=dict)
    relations_reused: dict[str, int] = field(default_factory=dict)
    #: Campos no escalares que Neo4j no admite y que este modulo NO aplano.
    omitted_fields: dict[str, list[str]] = field(default_factory=dict)

    def _bump(self, bucket: dict[str, int], key: str) -> None:
        bucket[key] = bucket.get(key, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes_created": dict(self.nodes_created),
            "nodes_reused": dict(self.nodes_reused),
            "relations_created": dict(self.relations_created),
            "relations_reused": dict(self.relations_reused),
            "omitted_fields": {k: list(v) for k, v in self.omitted_fields.items()},
        }

    @property
    def total_created(self) -> int:
        return sum(self.nodes_created.values()) + sum(self.relations_created.values())


# --- Proyeccion de un documento de contrato a propiedades planas -----------
def _is_hash_block(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and "value" in value
        and any(k in value for k in ("algorithm", "algo"))
    )


def flatten_document(doc: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Documento de contrato -> propiedades escalares + lista de lo omitido.

    Neo4j no guarda mapas anidados. En vez de serializar a JSON --que
    convertiria un dato consultable en una cadena opaca-- se proyecta:

    * escalares y listas de escalares, tal cual y con su nombre del contrato;
    * bloque de hash `{algorithm, value}` -> `<campo>_value` (la unica forma
      util de consultarlo, y la que ya usa el resto del writer con
      `state_hash`);
    * cualquier otra estructura NO se escribe, y su nombre sale en la lista
      de omitidos para que nadie confunda "no esta" con "no lo habia".
    """
    props: dict[str, Any] = {}
    omitted: list[str] = []
    for key in sorted(doc):
        value = doc[key]
        if value is None or key in _STAMPED:
            continue
        if _is_hash_block(value):
            props[f"{key}_value"] = value["value"]
            continue
        if isinstance(value, (str, int, float, bool)):
            props[key] = value
            continue
        if isinstance(value, list) and all(
            isinstance(v, (str, int, float, bool)) for v in value
        ):
            if value:
                props[key] = list(value)
            continue
        omitted.append(key)
    return props, omitted


def _node_props(
    doc: dict[str, Any], contract_id: str, workspace: str, partida_id: Optional[str]
) -> tuple[dict[str, Any], list[str]]:
    props, omitted = flatten_document(doc)
    props = safe_props(props)  # misma whitelist de nombres que el resto del writer
    props["workspace"] = workspace
    props["partida_id"] = partida_id
    props["provenance_contract"] = contract_id
    return props, omitted


# --- Consultas -------------------------------------------------------------
def _scoped(label: str, id_value: str, workspace: str, partida_id: Optional[str]) -> Query:
    """Existencia de un nodo de procedencia por su clave durable."""
    field_name = IDENTITY_FIELD[label]
    params: dict[str, Any] = {"id": id_value, "ws": workspace}
    if partida_id is None:
        pattern = (
            f"MATCH (n:{label} {{{field_name}: $id, workspace: $ws}}) "
            "WHERE n.partida_id IS NULL"
        )
    else:
        params["partida_id"] = partida_id
        pattern = (
            f"MATCH (n:{label} "
            f"{{{field_name}: $id, workspace: $ws, partida_id: $partida_id}})"
        )
    return Query(f"{pattern} RETURN n.{field_name} AS id LIMIT 1", params)


def create_provenance_node(label: str, props: dict[str, Any]) -> Query:
    """CREATE-only, como toda creacion del writer. Sin MERGE y sin `SET n = $x`."""
    if label not in IDENTITY_FIELD:
        raise WriterAbort(
            codes.EXEC_UNSUPPORTED_PAYLOAD,
            f"etiqueta de procedencia no admisible: {label!r}",
            {"label": label},
        )
    field_name = IDENTITY_FIELD[label]
    return Query(
        f"CREATE (n:{label} $props) RETURN n.{field_name} AS id", {"props": props}
    )


def _identity_of(label: str) -> str:
    if label in IDENTITY_FIELD:
        return IDENTITY_FIELD[label]
    if label == LABEL_ENTITY:
        return "entity_id"
    if label == LABEL_ASSERTION:
        return "assertion_id"
    raise WriterAbort(  # pragma: no cover - defensa, no camino
        codes.EXEC_UNSUPPORTED_PAYLOAD,
        f"etiqueta sin identidad durable conocida: {label!r}",
        {"label": label},
    )


def relation_exists(
    from_label: str, from_id: str, rel: str, to_label: str, to_id: str,
    workspace: str,
) -> Query:
    a_field, b_field = _identity_of(from_label), _identity_of(to_label)
    return Query(
        f"MATCH (a:{from_label} {{{a_field}: $a, workspace: $ws}})"
        f"-[r:{rel}]->(b:{to_label} {{{b_field}: $b, workspace: $ws}}) "
        "RETURN 1 AS existe LIMIT 1",
        {"a": from_id, "b": to_id, "ws": workspace},
    )


def create_provenance_relation(
    from_label: str, from_id: str, rel: str, to_label: str, to_id: str,
    workspace: str, partida_id: Optional[str],
) -> Query:
    """Arista entre dos nodos que YA existen. Nunca los crea.

    Ambos extremos se exigen del MISMO workspace y visibles desde el ambito
    (capa juego + la propia partida, nunca otra): mismo criterio que
    `cypher.create_relation` aplica a los extremos de una relacion de
    conocimiento.
    """
    a_field, b_field = _identity_of(from_label), _identity_of(to_label)
    params: dict[str, Any] = {"a": from_id, "b": to_id, "ws": workspace}
    if partida_id is None:
        cond = "a.partida_id IS NULL AND b.partida_id IS NULL"
    else:
        params["partida_id"] = partida_id
        cond = (
            "(a.partida_id IS NULL OR a.partida_id = $partida_id) AND "
            "(b.partida_id IS NULL OR b.partida_id = $partida_id)"
        )
    return Query(
        f"MATCH (a:{from_label} {{{a_field}: $a, workspace: $ws}}) "
        f"MATCH (b:{to_label} {{{b_field}: $b, workspace: $ws}}) "
        f"WHERE {cond} "
        f"CREATE (a)-[:{rel}]->(b) "
        f"RETURN a.{a_field} AS id",
        params,
    )


# --- Ejecucion -------------------------------------------------------------
def _run(tx: Any, query: Query) -> list[Any]:
    return list(tx.run(query.cypher, query.params))


def _ensure_node(
    tx: Any, out: ProvenanceOutcome, label: str, doc: dict[str, Any],
    contract_id: str, workspace: str, partida_id: Optional[str],
) -> Optional[str]:
    node_id = doc.get(IDENTITY_FIELD[label])
    if not node_id:
        raise WriterAbort(
            codes.EXEC_UNSUPPORTED_PAYLOAD,
            f"documento de procedencia sin {IDENTITY_FIELD[label]!r}",
            {"label": label},
        )
    if _run(tx, _scoped(label, node_id, workspace, partida_id)):
        out._bump(out.nodes_reused, label)
        return node_id
    props, omitted = _node_props(doc, contract_id, workspace, partida_id)
    if omitted:
        conocidos = out.omitted_fields.setdefault(label, [])
        for name in omitted:
            if name not in conocidos:
                conocidos.append(name)
    _run(tx, create_provenance_node(label, props))
    out._bump(out.nodes_created, label)
    return node_id


def _ensure_relation(
    tx: Any, out: ProvenanceOutcome, from_label: str, from_id: Optional[str], rel: str,
    to_label: str, to_id: Optional[str], workspace: str, partida_id: Optional[str],
) -> bool:
    if not from_id or not to_id:
        return False
    if _run(tx, relation_exists(from_label, from_id, rel, to_label, to_id, workspace)):
        out._bump(out.relations_reused, rel)
        return False
    rows = _run(tx, create_provenance_relation(
        from_label, from_id, rel, to_label, to_id, workspace, partida_id
    ))
    if not rows:
        # Un extremo no existe o esta en otro ambito. No es un fallo del
        # volcado: es procedencia que no se puede enlazar, y se cuenta como
        # NO creada en vez de fingirse escrita.
        return False
    out._bump(out.relations_created, rel)
    return True


#: Las aserciones a enlazar se leen del propio grafo: sus `evidence_fragment_ids`,
#: `subject_entity_id` y `object_entity_id` los estampo el writer, no un payload.
def _assertions_query(workspace: str, assertion_ids: list[str]) -> Query:
    where = ["n.workspace = $ws"]
    params: dict[str, Any] = {"ws": workspace}
    if assertion_ids:
        where.append("n.assertion_id IN $ids")
        params["ids"] = assertion_ids
    return Query(
        f"MATCH (n:{LABEL_ASSERTION}) WHERE {' AND '.join(where)} "
        "RETURN n.assertion_id AS assertion_id, "
        "n.evidence_fragment_ids AS evidencia, "
        "n.subject_entity_id AS subject_entity_id, "
        "n.object_entity_id AS object_entity_id, "
        "n.partida_id AS partida_id ORDER BY n.assertion_id",
        params,
    )


def _row(record: Any, name: str) -> Any:
    if isinstance(record, dict):
        return record.get(name)
    try:
        return record[name]
    except (KeyError, TypeError, IndexError):
        return getattr(record, name, None)


def link_assertions_tx(
    tx: Any,
    *,
    workspace: str,
    assertion_ids: Iterable[str] = (),
    out: Optional[ProvenanceOutcome] = None,
) -> ProvenanceOutcome:
    """`SUPPORTED_BY` / `HAS_SUBJECT` / `HAS_OBJECT` desde cada asercion.

    El ambito de cada arista es el de LA ASERCION, leido del grafo, no un
    parametro de la llamada: asi una asercion de partida no puede quedar
    enlazada bajo el ambito de otra por un descuido de quien invoca.
    """
    out = out or ProvenanceOutcome()
    ids = [a for a in assertion_ids if a]
    for record in _run(tx, _assertions_query(workspace, ids)):
        assertion_id = _row(record, "assertion_id")
        ambito = _row(record, "partida_id")
        for fragment_id in list(_row(record, "evidencia") or []):
            _ensure_relation(tx, out, LABEL_ASSERTION, assertion_id, REL_SUPPORTED_BY,
                             LABEL_EVIDENCE, fragment_id, workspace, ambito)
        for rel, campo in ((REL_HAS_SUBJECT, "subject_entity_id"),
                           (REL_HAS_OBJECT, "object_entity_id")):
            _ensure_relation(tx, out, LABEL_ASSERTION, assertion_id, rel,
                             LABEL_ENTITY, _row(record, campo), workspace, ambito)
    return out


def persist_provenance_tx(
    tx: Any,
    *,
    workspace: str,
    partida_id: Optional[str] = None,
    source_asset: Optional[dict[str, Any]] = None,
    episodes: Iterable[dict[str, Any]] = (),
    fragments: Iterable[dict[str, Any]] = (),
    assertion_ids: Iterable[str] = (),
    out: Optional[ProvenanceOutcome] = None,
) -> ProvenanceOutcome:
    """Todo el volcado dentro de UNA transaccion que inyecta quien llama."""
    out = out or ProvenanceOutcome()
    if source_asset:
        _ensure_node(tx, out, LABEL_SOURCE, source_asset,
                     "source-asset/v3-internal-v1", workspace, partida_id)
    for episode in episodes:
        _ensure_node(tx, out, LABEL_EPISODE, episode,
                     "source-episode/v3-internal-v1", workspace, partida_id)
        _ensure_relation(tx, out, LABEL_SOURCE, episode.get("source_asset_id"),
                         REL_HAS_EPISODE, LABEL_EPISODE, episode.get("episode_id"),
                         workspace, partida_id)
    for fragment in fragments:
        _ensure_node(tx, out, LABEL_EVIDENCE, fragment,
                     "evidence-fragment/v3-internal-v1", workspace, partida_id)
        _ensure_relation(tx, out, LABEL_EPISODE, fragment.get("episode_id"),
                         REL_HAS_FRAGMENT, LABEL_EVIDENCE, fragment.get("fragment_id"),
                         workspace, partida_id)
    link_assertions_tx(tx, workspace=workspace, assertion_ids=assertion_ids, out=out)
    return out


def persist_provenance(
    driver: Any,
    *,
    workspace: str,
    partida_id: Optional[str] = None,
    source_asset: Optional[dict[str, Any]] = None,
    episodes: Iterable[dict[str, Any]] = (),
    fragments: Iterable[dict[str, Any]] = (),
    assertion_ids: Iterable[str] = (),
) -> ProvenanceOutcome:
    """Volcado completo. El driver se INYECTA: aqui no se importa `neo4j`."""
    episodios = list(episodes)
    fragmentos = list(fragments)
    aserciones = list(assertion_ids)
    with driver.session() as session:
        if hasattr(session, "execute_write"):
            return session.execute_write(
                lambda tx: persist_provenance_tx(
                    tx, workspace=workspace, partida_id=partida_id,
                    source_asset=source_asset, episodes=episodios,
                    fragments=fragmentos, assertion_ids=aserciones,
                )
            )
        return persist_provenance_tx(  # pragma: no cover - drivers de prueba
            session, workspace=workspace, partida_id=partida_id,
            source_asset=source_asset, episodes=episodios,
            fragments=fragmentos, assertion_ids=aserciones,
        )


# --- Lectura del recorrido -------------------------------------------------
def trace_query(workspace: str, assertion_id: str) -> Query:
    """El recorrido completo, en UNA consulta y por el CAMINO, no por ids.

    Cada tramo es un patron encadenado sobre la MISMA fila: no hay dos `MATCH`
    independientes, asi que no puede producirse el producto cartesiano que
    devolveria filas sin relacion entre si (o cero filas) y pareceria medir.
    """
    return Query(
        f"MATCH (a:{LABEL_ASSERTION} {{assertion_id: $id, workspace: $ws}})"
        f"-[:{REL_SUPPORTED_BY}]->(ev:{LABEL_EVIDENCE})"
        f"<-[:{REL_HAS_FRAGMENT}]-(ep:{LABEL_EPISODE})"
        f"<-[:{REL_HAS_EPISODE}]-(src:{LABEL_SOURCE}) "
        "RETURN a.assertion_id AS assertion_id, a.predicate AS predicate, "
        "ev.fragment_id AS fragment_id, ev.literal_text AS literal, "
        "ep.episode_id AS episode_id, ep.sequence AS episode_sequence, "
        "src.source_asset_id AS source_asset_id, "
        "src.original_name AS source_name "
        "ORDER BY ev.fragment_id",
        {"id": assertion_id, "ws": workspace},
    )


TRACE_KEYS = (
    "assertion_id", "predicate", "fragment_id", "literal", "episode_id",
    "episode_sequence", "source_asset_id", "source_name",
)


def trace(driver: Any, workspace: str, assertion_id: str) -> list[dict[str, Any]]:
    """Filas del recorrido. Vacio = no hay procedencia navegable, no "no hay"."""
    query = trace_query(workspace, assertion_id)
    with driver.session() as session:
        rows = list(session.run(query.cypher, query.params))
    return [{k: _row(r, k) for k in TRACE_KEYS} for r in rows]


__all__ = [
    "LABEL_SOURCE",
    "LABEL_EPISODE",
    "LABEL_EVIDENCE",
    "PROVENANCE_LABELS",
    "PROVENANCE_RELATIONS",
    "REL_HAS_EPISODE",
    "REL_HAS_FRAGMENT",
    "REL_SUPPORTED_BY",
    "REL_HAS_SUBJECT",
    "REL_HAS_OBJECT",
    "IDENTITY_FIELD",
    "TRACE_KEYS",
    "ProvenanceOutcome",
    "flatten_document",
    "persist_provenance",
    "persist_provenance_tx",
    "link_assertions_tx",
    "trace",
    "trace_query",
]
