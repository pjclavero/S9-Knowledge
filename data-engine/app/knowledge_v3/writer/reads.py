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


__all__ = ["VisibleAssertion", "list_visible_assertions"]
