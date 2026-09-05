# -*- coding: utf-8 -*-
"""Writer V3: la unica puerta fisica al grafo.

Todo lo demas del sistema —multimodal, extractor, resolucion, motor, ledger,
proveedores— existe para que este modulo solo acepte lo legitimo. Su unica
entrada admisible es un `GraphMutationPlan` sellado por el motor local; no
interpreta, no corrige, no consulta modelos y no arregla planes casi correctos.

Tres capas, en este orden:

    admision (`admission.py`)  — ¿es un plan legitimo, vigente, mio y sobre este
                                 estado? Se evalua siempre.
    gate     (`gate.py`)       — las nueve condiciones que aporta el operador.
                                 Solo bloquean el APPLY.
    ejecucion (`executor.py`)  — una transaccion, todo o nada, con concurrencia
                                 optimista e idempotencia real.

Nada de aqui abre una conexion: el driver se inyecta. No hay credenciales, ni
URI por defecto, ni un solo `import` del paquete de Neo4j.
"""
from __future__ import annotations

from . import codes
from .admission import (
    SUPPORTED_CONTRACT_MAJOR,
    AdmissionContext,
    AdmissionResult,
    admit,
    parse_iso_utc,
    utc_now,
)
from .audit import AuditRecord, AuditSink, InMemoryAuditSink, JsonlAuditSink
from .cypher import ALLOWED_UPDATE_PROPS, RESERVED_PROPS, assert_safe
from .errors import Rejection, WriterAbort, WriterError
from .executor import (
    AppliedOperation,
    ExecutionContext,
    ExecutionOutcome,
    execute_plan,
    simulate_plan,
)
from .gate import (
    DEFAULT_MAX_OPERATIONS,
    ENV_ALLOW_REAL_INGEST,
    ENV_WRITER_WORKSPACE,
    GateResult,
    OperatorRequest,
)
from .gate import evaluate as evaluate_gate
from .idempotency import AppliedKeyStore, InMemoryAppliedKeys, JsonlAppliedKeys
from .provenance import (
    PROVENANCE_LABELS,
    PROVENANCE_RELATIONS,
    ProvenanceOutcome,
    persist_provenance,
    trace,
    trace_query,
)
from .reads import VisibleAssertion, list_visible_assertions
from .rollback import RollbackDocument, RollbackInstruction, build_rollback
from .schema import (
    APPLIED_OPERATION_CONSTRAINT,
    APPLIED_OPERATION_CONSTRAINT_CYPHER,
    ASSERTION_PARTIDA_INDEX,
    ASSERTION_PARTIDA_INDEX_CYPHER,
    ENTITY_PARTIDA_INDEX,
    ENTITY_PARTIDA_INDEX_CYPHER,
    SCHEMA_VERSION,
    bootstrap_writer_schema,
)
from .view import UNSIGNED_FIELDS, SignedView
from .writer import (
    MODE_APPLY,
    MODE_DRY_RUN,
    OUTCOME_ABORTED,
    OUTCOME_APPLIED,
    OUTCOME_ATTEMPTED,
    OUTCOME_BLOCKED,
    OUTCOME_REJECTED,
    OUTCOME_SIMULATED,
    GraphWriter,
    WriteResult,
)

__all__ = [
    "codes",
    # admision
    "AdmissionContext",
    "AdmissionResult",
    "admit",
    "parse_iso_utc",
    "utc_now",
    "SUPPORTED_CONTRACT_MAJOR",
    # vista firmada
    "SignedView",
    "UNSIGNED_FIELDS",
    # gate
    "OperatorRequest",
    "GateResult",
    "evaluate_gate",
    "ENV_ALLOW_REAL_INGEST",
    "ENV_WRITER_WORKSPACE",
    "DEFAULT_MAX_OPERATIONS",
    # ejecucion
    "AppliedOperation",
    "ExecutionContext",
    "ExecutionOutcome",
    "execute_plan",
    "simulate_plan",
    "assert_safe",
    "ALLOWED_UPDATE_PROPS",
    "RESERVED_PROPS",
    "APPLIED_OPERATION_CONSTRAINT",
    "APPLIED_OPERATION_CONSTRAINT_CYPHER",
    "ENTITY_PARTIDA_INDEX",
    "ENTITY_PARTIDA_INDEX_CYPHER",
    "ASSERTION_PARTIDA_INDEX",
    "ASSERTION_PARTIDA_INDEX_CYPHER",
    "SCHEMA_VERSION",
    "bootstrap_writer_schema",
    # idempotencia
    "AppliedKeyStore",
    "InMemoryAppliedKeys",
    "JsonlAppliedKeys",
    # procedencia navegable (docs/v3/54)
    "PROVENANCE_LABELS",
    "PROVENANCE_RELATIONS",
    "ProvenanceOutcome",
    "persist_provenance",
    "trace",
    "trace_query",
    # lecturas (M4: enmascarado de supersesion local)
    "VisibleAssertion",
    "list_visible_assertions",
    # auditoria
    "AuditRecord",
    "AuditSink",
    "InMemoryAuditSink",
    "JsonlAuditSink",
    # rollback
    "RollbackDocument",
    "RollbackInstruction",
    "build_rollback",
    # errores
    "Rejection",
    "WriterError",
    "WriterAbort",
    # orquestacion
    "GraphWriter",
    "WriteResult",
    "MODE_APPLY",
    "MODE_DRY_RUN",
    "OUTCOME_ATTEMPTED",
    "OUTCOME_APPLIED",
    "OUTCOME_SIMULATED",
    "OUTCOME_REJECTED",
    "OUTCOME_BLOCKED",
    "OUTCOME_ABORTED",
]
