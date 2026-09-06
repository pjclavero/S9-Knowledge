# -*- coding: utf-8 -*-
"""Lecturas de solo consulta sobre el grafo que escribe el writer V3.

POR QUE EXISTE (M4, docs/v3/49-multipartida-diseno.md §2.5)
-------------------------------------------------------------
El resto de `writer/` esta orientado a MUTAR: `admission.py` juzga un plan,
`executor.py` lo aplica, y ninguno de los dos necesita nunca listar mas de un
nodo a la vez (`_single`, concurrencia optimista sobre UN objetivo). La
supersesion LOCAL (`local_override_of`) introduce, por primera vez en este
subsistema, una pregunta que SI es de listado: "que aserciones ve esta
partida, una vez aplicado el enmascarado". El visor (`viewer/app/`,
M5a/M5b del mismo diseno) sera el consumidor real de esta pregunta en
produccion, pero M5 no existe todavia -- este modulo es el lugar HOY donde el
enmascarado se puede demostrar, con Neo4j real o con un driver de pruebas,
sin esperar a que el visor entienda `partida_id`.

Deliberadamente NO lo usa `execute_plan` ni `admission.py`: es una lectura de
diagnostico/verificacion, no una decision de escritura. Cuando M5 llegue, el
provider del visor puede reusar `cypher.list_visible_assertions_query`
directamente (misma disciplina de M3: el filtrado de ambito vive en Cypher,
nunca en Python) en vez de esta funcion, que aqui existe sobre todo para
tener una API de la que colgar los tests de M4.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from . import cypher


@dataclass(frozen=True)
class VisibleAssertion:
    """Una fila de `list_visible_assertions`: identidad + propiedades del nodo."""

    assertion_id: str
    props: dict[str, Any]


def _row_get(row: Any, name: str) -> Any:
    """Lee un campo de una fila del driver sin asumir su clase concreta."""
    if isinstance(row, dict):
        return row.get(name)
    try:
        return row[name]
    except (KeyError, TypeError, IndexError):
        return getattr(row, name, None)


def list_visible_assertions(
    driver: Any,
    workspace: str,
    partida_id: Optional[str],
    *,
    subject_entity_id: Optional[str] = None,
) -> list[VisibleAssertion]:
    """Aserciones visibles desde `partida_id`, con el enmascarado de M4 aplicado.

    `driver` se inyecta, igual que en `executor.py`: este modulo no importa
    `neo4j` ni abre ninguna conexion por si mismo. Se espera un objeto con
    `.session()` que a su vez soporte `.run(cypher, params)` devolviendo un
    iterable de filas (protocolo estandar del driver oficial; los tests usan
    un driver falso que lo respeta).
    """
    query = cypher.list_visible_assertions_query(
        workspace, partida_id, subject_entity_id=subject_entity_id
    )
    with driver.session() as session:
        rows = list(session.run(query.cypher, query.params))
    out: list[VisibleAssertion] = []
    for row in rows:
        assertion_id = _row_get(row, "assertion_id")
        props = dict(_row_get(row, "props") or {})
        out.append(VisibleAssertion(assertion_id=assertion_id, props=props))
    return out


@dataclass(frozen=True)
class GraphEntity:
    """Una entidad OBSERVADA en el grafo. Nada de esto se deriva ni se rellena.

    `version` y `state_hash` son los del nodo. Pueden venir a `None` — el
    writer no los escribe al crear — y esa ausencia se PROPAGA en vez de
    sustituirse por un valor plausible: quien construya un plan con un
    `expected_hash` inventado descubrira la mentira en el executor, y para
    entonces ya habra abortado una transaccion en produccion.
    """

    entity_id: str
    entity_type: Optional[str]
    name: Optional[str]
    version: Optional[int]
    state_hash: Optional[str]
    partida_id: Optional[str]
    status: Optional[str]
    labels: tuple[str, ...] = ()


def list_entities(
    driver: Any,
    workspace: str,
    partida_id: Optional[str] = None,
) -> list[GraphEntity]:
    """Entidades que EXISTEN en el grafo, en el ambito de lectura declarado.

    Es la lectura que le faltaba a este subsistema y la que une las dos
    mitades del producto: hasta ahora el catalogo del resolutor salia de un
    FICHERO y el grafo del writer era otro mundo, sin nada que los
    contrastase. Con esto, "que entidades ya existen" se OBSERVA.

    `driver` se inyecta, igual que en `list_visible_assertions`: este modulo
    no importa `neo4j` ni abre conexiones. Un fallo del driver se PROPAGA:
    degradar en silencio a "no hay ninguna" convertiria una caida de Neo4j en
    una avalancha de altas de entidades, que es exactamente el accidente que
    este carril existe para no cometer.
    """
    query = cypher.list_entities_query(workspace, partida_id)
    with driver.session() as session:
        rows = list(session.run(query.cypher, query.params))
    out: list[GraphEntity] = []
    for row in rows:
        etiquetas = _row_get(row, "labels") or ()
        version = _row_get(row, "version")
        out.append(
            GraphEntity(
                entity_id=_row_get(row, "entity_id"),
                entity_type=_row_get(row, "entity_type"),
                name=_row_get(row, "name"),
                version=int(version) if version is not None else None,
                state_hash=_row_get(row, "state_hash"),
                partida_id=_row_get(row, "partida_id"),
                status=_row_get(row, "status"),
                labels=tuple(etiquetas),
            )
        )
    return out


def locate_entity(driver: Any, entity_id: str) -> list[str]:
    """Workspaces en los que consta `entity_id`. Lista vacia = no consta."""
    query = cypher.locate_entity_query(entity_id)
    with driver.session() as session:
        rows = list(session.run(query.cypher, query.params))
    return [_row_get(row, "workspace") for row in rows]


__all__ = [
    "VisibleAssertion",
    "GraphEntity",
    "list_visible_assertions",
    "list_entities",
    "locate_entity",
]
