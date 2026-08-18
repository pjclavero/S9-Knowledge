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
# DE DONDE SALE LA CLAVE (no se fija de memoria, se DERIVA)
# ---------------------------------------------------------
# La identidad de almacenamiento de este writer es explicita y esta escrita en
# `cypher._scoped_match`: un objeto se localiza por `{id_field, workspace,
# partida_id}` -- "MATCH exacto de un nodo en SU propio ambito declarado (...)
# Nunca un comodin". Esa terna, y no otra, es la clave de unicidad: es la que
# el propio writer usa para decidir si una operacion opera sobre un objetivo
# concreto. Anadir dimensiones la haria mas laxa que el writer; quitarlas
# prohibiria un estado que el diseno multipartida declara legitimo (la misma
# entidad derivada existiendo en la capa juego y en una partida, docs/v3/49
# §2.5: el lore no se muta, la partida diverge en su propio ambito).
#
# `entity_id` ya lleva el `workspace` dentro (`resolution/provisional.py`
# deriva `sha256(workspace \x1f superficie \x1f tipo)`), pero eso es una
# propiedad de UNA funcion de derivacion, no del contrato: hay identificadores
# AUTORADOS en los contratos (`"entity:daiki"`) que no pasan por ella. El
# `workspace` viaja en la clave de forma explicita para no depender de eso.
#
# LO QUE ESTA RESTRICCION NO CUBRE -- Y POR QUE HAY UNA SEGUNDA BARRERA
# ---------------------------------------------------------------------
# 1. NULOS. Neo4j no aplica una restriccion compuesta a un nodo al que le
#    falte alguna de las propiedades, y la capa juego se escribe justo asi
#    (`scope_props` devuelve `partida_id: None`, que Neo4j guarda como
#    ausencia). Es decir: esta barrera protege de verdad la capa de partida y
#    NO protege la capa juego. No se disimula, se MIDE
#    (`test_la_restriccion_NO_cubre_la_capa_juego`).
# 2. EL PASADO. Una restriccion impide crear estado invalido a partir de que
#    existe; no dice nada de lo ya escrito, de una restauracion defectuosa, de
#    una importacion anterior ni de un retro-relleno de `entity_id` cuya
#    derivacion colisione. El preflight de solo lectura contra la base real
#    lo dejo claro: hoy `entity_id` NO EXISTE alli, y la clave natural mas
#    cercana (`canonical_name`) YA colisiona.
# Las dos lagunas son la razon de que la barrera del resolver
# (`Neo4jGraphProvider.entity`, fail-closed con 2+) no sea opcional.
ENTITY_DURABLE_IDENTITY_CONSTRAINT = "entity_identidad_durable_unique"
#: OJO A LA ETIQUETA: `:Entity`, no `:V3Entity`. La restriccion tiene que caer
#: sobre la etiqueta que RESUELVE LA URL, y el visor lee `(n:Entity)` en todo
#: su Cypher (`viewer/app/providers/neo4j_provider.py`). Una restriccion sobre
#: `:V3Entity` seria correcta y no protegeria ni una sola URL durable.
ENTITY_DURABLE_IDENTITY_CONSTRAINT_CYPHER = (
    f"CREATE CONSTRAINT {ENTITY_DURABLE_IDENTITY_CONSTRAINT} IF NOT EXISTS "
    "FOR (n:Entity) "
    "REQUIRE (n.workspace, n.entity_id, n.partida_id) IS UNIQUE"
)

#: Gemela para la superficie de ESCRITURA del writer V3. Hoy el visor no lee
#: `:V3Entity`, asi que ninguna URL durable depende de ella; se declara igual
#: para que la superficie que el writer si crea no quede sin barrera el dia
#: que el visor la lea.
V3_ENTITY_DURABLE_IDENTITY_CONSTRAINT = "v3_entity_identidad_durable_unique"
V3_ENTITY_DURABLE_IDENTITY_CONSTRAINT_CYPHER = (
    f"CREATE CONSTRAINT {V3_ENTITY_DURABLE_IDENTITY_CONSTRAINT} IF NOT EXISTS "
    f"FOR (n:{LABEL_ENTITY}) "
    "REQUIRE (n.workspace, n.entity_id, n.partida_id) IS UNIQUE"
)

#: Aserciones: mismo contrato, mismo `_scoped_match`, otro campo de identidad.
V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT = "v3_assertion_identidad_durable_unique"
V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT_CYPHER = (
    f"CREATE CONSTRAINT {V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT} IF NOT EXISTS "
    f"FOR (n:{LABEL_ASSERTION}) "
    "REQUIRE (n.workspace, n.assertion_id, n.partida_id) IS UNIQUE"
)

#: Las tres, en el orden en que se aplican. Tenerlas en UNA lista es lo que
#: permite que el arnes de calibracion las recorra sin copiar la definicion:
#: una sola fuente normativa, no dos que puedan divergir.
DURABLE_IDENTITY_CONSTRAINTS: tuple[tuple[str, str, str, str], ...] = (
    # (nombre, etiqueta, campo de identidad, DDL)
    ("entity", "Entity", "entity_id", ENTITY_DURABLE_IDENTITY_CONSTRAINT_CYPHER),
    (LABEL_ENTITY, LABEL_ENTITY, "entity_id", V3_ENTITY_DURABLE_IDENTITY_CONSTRAINT_CYPHER),
    (LABEL_ASSERTION, LABEL_ASSERTION, "assertion_id", V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT_CYPHER),
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
