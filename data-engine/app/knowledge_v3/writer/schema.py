# -*- coding: utf-8 -*-
"""Esquema mínimo del writer V3.

El bootstrap es explícito: nunca descubre una URI ni abre una conexión. Quien
administra una base inyecta el driver y decide dónde aplicar el esquema.
"""
from __future__ import annotations

from typing import Any

from .cypher import LABEL_APPLIED_OPERATION

SCHEMA_VERSION = "writer-v3-1"
APPLIED_OPERATION_CONSTRAINT = "v3_applied_operation_unique"
APPLIED_OPERATION_CONSTRAINT_CYPHER = (
    f"CREATE CONSTRAINT {APPLIED_OPERATION_CONSTRAINT} IF NOT EXISTS "
    f"FOR (op:{LABEL_APPLIED_OPERATION}) "
    "REQUIRE (op.workspace, op.idempotency_key) IS UNIQUE"
)


def bootstrap_writer_schema(driver: Any) -> None:
    """Crea de forma idempotente las restricciones requeridas por el writer."""
    with driver.session() as session:
        session.run(APPLIED_OPERATION_CONSTRAINT_CYPHER).consume()


__all__ = [
    "APPLIED_OPERATION_CONSTRAINT",
    "APPLIED_OPERATION_CONSTRAINT_CYPHER",
    "SCHEMA_VERSION",
    "bootstrap_writer_schema",
]
