# -*- coding: utf-8 -*-
"""Esquema mínimo del writer V3.

El bootstrap es explícito: nunca descubre una URI ni abre una conexión. Quien
administra una base inyecta el driver y decide dónde aplicar el esquema.
"""
from __future__ import annotations

from typing import Any

from .cypher import LABEL_APPLIED_OPERATION, LABEL_ASSERTION, LABEL_ENTITY

SCHEMA_VERSION = "writer-v3-1"
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


def bootstrap_writer_schema(driver: Any) -> None:
    """Crea de forma idempotente las restricciones e indices requeridos."""
    with driver.session() as session:
        session.run(APPLIED_OPERATION_CONSTRAINT_CYPHER).consume()
        session.run(ENTITY_PARTIDA_INDEX_CYPHER).consume()
        session.run(ASSERTION_PARTIDA_INDEX_CYPHER).consume()


__all__ = [
    "APPLIED_OPERATION_CONSTRAINT",
    "APPLIED_OPERATION_CONSTRAINT_CYPHER",
    "ENTITY_PARTIDA_INDEX",
    "ENTITY_PARTIDA_INDEX_CYPHER",
    "ASSERTION_PARTIDA_INDEX",
    "ASSERTION_PARTIDA_INDEX_CYPHER",
    "SCHEMA_VERSION",
    "bootstrap_writer_schema",
]
