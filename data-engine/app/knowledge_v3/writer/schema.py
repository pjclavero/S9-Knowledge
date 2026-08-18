# -*- coding: utf-8 -*-
"""Esquema mínimo del writer V3.

El bootstrap es explícito: nunca descubre una URI ni abre una conexión. Quien
administra una base inyecta el driver y decide dónde aplicar el esquema.
"""
from __future__ import annotations

from typing import Any

from .cypher import LABEL_APPLIED_OPERATION, LABEL_ASSERTION, LABEL_ENTITY

SCHEMA_VERSION = "writer-v3-2"
APPLIED_OPERATION_CONSTRAINT = "v3_applied_operation_unique"
APPLIED_OPERATION_CONSTRAINT_CYPHER = (
    f"CREATE CONSTRAINT {APPLIED_OPERATION_CONSTRAINT} IF NOT EXISTS "
    f"FOR (op:{LABEL_APPLIED_OPERATION}) "
    "REQUIRE (op.workspace, op.idempotency_key) IS UNIQUE"
)

#: M3 (docs/v3/49 §2.4): INDICE, no constraint de unicidad -- `partida_id`
#: es nullable y compartido por muchos nodos de la misma partida; la
#: unicidad de idempotencia sigue siendo (workspace, idempotency_key), que
#: ya cubre ambito porque `idempotency_key` deriva del plan completo
#: (incluido `scope`, cubierto gratis por `plan_hash`, ver docs/v3/49 §2.2).
ENTITY_PARTIDA_INDEX = "v3_entity_partida_id_index"
ENTITY_PARTIDA_INDEX_CYPHER = (
    f"CREATE INDEX {ENTITY_PARTIDA_INDEX} IF NOT EXISTS "
    f"FOR (n:{LABEL_ENTITY}) ON (n.partida_id)"
)
ASSERTION_PARTIDA_INDEX = "v3_assertion_partida_id_index"
ASSERTION_PARTIDA_INDEX_CYPHER = (
    f"CREATE INDEX {ASSERTION_PARTIDA_INDEX} IF NOT EXISTS "
    f"FOR (n:{LABEL_ASSERTION}) ON (n.partida_id)"
)

# --- UNICIDAD DE LA IDENTIDAD DURABLE (barrera 1 de 2) ---------------------
#
# DE DONDE SALE LA CLAVE (no se fija de memoria: se DERIVA de la regla que el
# writer YA aplica en cada escritura)
# --------------------------------------------------------------------------
# `writer/executor.py::_assert_absent` es la puerta por la que pasan TODAS las
# creaciones (`CREATE_ENTITY` y `CREATE_ASSERTION` la invocan antes de tocar el
# grafo), y dice literalmente:
#
#     "Deliberadamente SIN filtro de partida (`*_any_scope`): la identidad de
#      un `entity_id`/`assertion_id` es unica en todo el workspace, cruzando
#      capa juego y todas sus partidas -- dos ambitos jamas comparten el mismo
#      id."
#
# y lo comprueba con `read_entity_state_any_scope(target_id, workspace)`, que
# es `MATCH (n {entity_id: $id, workspace: $ws})`. La clave del writer es, por
# tanto, **(workspace, entity_id)**. Ni mas ni menos.
#
# POR QUE `partida_id` NO ESTA EN LA CLAVE (correccion de la primera version)
# --------------------------------------------------------------------------
# La primera version de este bloque usaba la terna `(workspace, entity_id,
# partida_id)` apoyandose en `cypher._scoped_match` y en docs/v3/49 §2.5. Las
# dos citas eran malas:
#
# * `_scoped_match` responde a "¿donde opero?" (precondicion de AMBITO de una
#   operacion sobre un objetivo concreto), no a "¿que hace unico a un objeto?".
#   Quien responde lo segundo es `_assert_absent`, y responde otra cosa.
# * §2.5 describe la divergencia local de ASERCIONES (`local_override_of` sobre
#   `fact-assertion`, que NO muta el hecho de capa juego). No describe --ni
#   autoriza-- duplicar NODOS DE ENTIDAD por partida.
#
# La terna era ademas ESTRICTAMENTE MAS LAXA que el writer: admitia que capa
# juego y `partida:Y` compartieran `entity_id`, un estado que `_assert_absent`
# rechaza y que el resolver del visor --que no filtra por `partida_id`-- leeria
# como ambiguo y cerraria en falso. Dos barreras normando cosas distintas.
# Con `(workspace, entity_id)` ambas norman LO MISMO.
#
# Y hay un efecto colateral que importa: las dos propiedades de la clave estan
# SIEMPRE presentes en un nodo direccionable, asi que la restriccion cubre
# tambien la capa juego. La terna no la cubria (Neo4j no aplica una compuesta a
# un nodo al que le falta una propiedad, y el lore se escribe con
# `partida_id: None`, que Neo4j guarda como ausencia).
#
# LO QUE ESTA RESTRICCION SIGUE SIN CUBRIR -- Y POR QUE HAY UNA SEGUNDA BARRERA
# ----------------------------------------------------------------------------
# EL PASADO. Una restriccion impide crear estado invalido desde el instante en
# que existe; no dice nada de lo ya escrito, de una restauracion defectuosa, de
# una importacion anterior ni de un retro-relleno de `entity_id` cuya
# derivacion colisione. Y no es hipotetico: el preflight de solo lectura midio
# que la base real NO TIENE NI UNA restriccion, que `entity_id` no existe alli
# (0/199 nodos) y que `canonical_name` YA colisiona (4 claves, mayor grupo 3,
# 9 nodos). Un retro-relleno derivado del nombre CREARIA la colision. Por eso
# la barrera del resolver (`Neo4jGraphProvider.entity`, fail-closed con 2+) no
# es opcional: es la unica que cubre ese escenario.
ENTITY_DURABLE_IDENTITY_CONSTRAINT = "entity_identidad_durable_unique"
#: OJO A LA ETIQUETA: `:Entity`, no `:V3Entity`. La restriccion tiene que caer
#: sobre la etiqueta que RESUELVE LA URL, y el visor lee `(n:Entity)` en todo
#: su Cypher (`viewer/app/providers/neo4j_provider.py`). Una restriccion sobre
#: `:V3Entity` seria correcta y no protegeria ni una sola URL durable.
ENTITY_DURABLE_IDENTITY_CONSTRAINT_CYPHER = (
    f"CREATE CONSTRAINT {ENTITY_DURABLE_IDENTITY_CONSTRAINT} IF NOT EXISTS "
    "FOR (n:Entity) "
    "REQUIRE (n.workspace, n.entity_id) IS UNIQUE"
)

#: Gemela para la superficie de ESCRITURA del writer V3. Hoy el visor no lee
#: `:V3Entity`, asi que ninguna URL durable depende de ella; se declara igual
#: para que la superficie que el writer si crea no quede sin barrera el dia
#: que el visor la lea.
V3_ENTITY_DURABLE_IDENTITY_CONSTRAINT = "v3_entity_identidad_durable_unique"
V3_ENTITY_DURABLE_IDENTITY_CONSTRAINT_CYPHER = (
    f"CREATE CONSTRAINT {V3_ENTITY_DURABLE_IDENTITY_CONSTRAINT} IF NOT EXISTS "
    f"FOR (n:{LABEL_ENTITY}) "
    "REQUIRE (n.workspace, n.entity_id) IS UNIQUE"
)

#: Aserciones: la MISMA regla de `_assert_absent`, que no distingue entre
#: `entity_id` y `assertion_id`, con el campo de identidad que les toca.
V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT = "v3_assertion_identidad_durable_unique"
V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT_CYPHER = (
    f"CREATE CONSTRAINT {V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT} IF NOT EXISTS "
    f"FOR (n:{LABEL_ASSERTION}) "
    "REQUIRE (n.workspace, n.assertion_id) IS UNIQUE"
)

#: Las tres, en el orden en que se aplican. Tenerlas en UNA lista es lo que
#: permite que el arnes de calibracion y la suite las recorran sin copiar la
#: definicion: una sola fuente normativa, no dos que puedan divergir.
DURABLE_IDENTITY_CONSTRAINTS: tuple[tuple[str, str, str, str], ...] = (
    # (nombre, etiqueta, campo de identidad, DDL)
    ("entity", "Entity", "entity_id", ENTITY_DURABLE_IDENTITY_CONSTRAINT_CYPHER),
    (LABEL_ENTITY, LABEL_ENTITY, "entity_id", V3_ENTITY_DURABLE_IDENTITY_CONSTRAINT_CYPHER),
    (LABEL_ASSERTION, LABEL_ASSERTION, "assertion_id",
     V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT_CYPHER),
)


def bootstrap_writer_schema(driver: Any) -> None:
    """Crea de forma idempotente las restricciones e indices requeridos."""
    with driver.session() as session:
        session.run(APPLIED_OPERATION_CONSTRAINT_CYPHER).consume()
        session.run(ENTITY_PARTIDA_INDEX_CYPHER).consume()
        session.run(ASSERTION_PARTIDA_INDEX_CYPHER).consume()
        for _, _, _, ddl in DURABLE_IDENTITY_CONSTRAINTS:
            session.run(ddl).consume()


__all__ = [
    "APPLIED_OPERATION_CONSTRAINT",
    "DURABLE_IDENTITY_CONSTRAINTS",
    "ENTITY_DURABLE_IDENTITY_CONSTRAINT",
    "ENTITY_DURABLE_IDENTITY_CONSTRAINT_CYPHER",
    "V3_ENTITY_DURABLE_IDENTITY_CONSTRAINT",
    "V3_ENTITY_DURABLE_IDENTITY_CONSTRAINT_CYPHER",
    "V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT",
    "V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT_CYPHER",
    "APPLIED_OPERATION_CONSTRAINT_CYPHER",
    "ENTITY_PARTIDA_INDEX",
    "ENTITY_PARTIDA_INDEX_CYPHER",
    "ASSERTION_PARTIDA_INDEX",
    "ASSERTION_PARTIDA_INDEX_CYPHER",
    "SCHEMA_VERSION",
    "bootstrap_writer_schema",
]
