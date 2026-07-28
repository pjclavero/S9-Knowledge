# -*- coding: utf-8 -*-
"""Ejecucion del plan: todo o nada, con concurrencia optimista e idempotencia.

Tres invariantes, y ninguna es negociable:

1. **Transaccional.** Una sola transaccion para el plan entero. Cualquier fallo
   —driver, precondicion, payload— la aborta completa. No existe «se aplicaron
   3 de 5»: un plan a medias deja el grafo en un estado que ningun snapshot
   describe.
2. **Concurrencia optimista.** Cada operacion que toca algo existente comprueba
   `expected_version` y `expected_hash` contra lo que hay AHORA. Un solo
   desajuste aborta el plan entero, no solo esa operacion: si el grafo se movio
   bajo el plan, el resto de operaciones tampoco se calcularon sobre este
   estado.
3. **Idempotencia real.** Una `idempotency_key` ya registrada como aplicada es
   un no-op CONTABILIZADO, y ni siquiera llega al driver. Reaplicar el mismo
   plan no escribe dos veces.

El driver se INYECTA. Este modulo no importa `neo4j`, no lee variables de
conexion y no tiene ninguna URL por defecto.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from . import codes, cypher
from .errors import WriterAbort
from .idempotency import AppliedKeyStore
from .view import SignedView

_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

CREATING_TYPES = frozenset({"CREATE_ENTITY", "CREATE_ASSERTION"})
RELATION_TYPES = frozenset({"LINK_EXISTING", "PROJECT_RELATION"})
#: Operaciones que cierran una vigencia. Exigen `reason_code` (R1 del ledger).
CLOSING_TYPES = frozenset({"UPDATE_ENTITY", "SUPERSEDE_ASSERTION"})
SUPPORTED_TYPES = CREATING_TYPES | RELATION_TYPES | CLOSING_TYPES


@dataclass
class AppliedOperation:
    """Lo que una operacion escribio de verdad. Base del rollback."""

    operation_id: str
    operation_type: str
    idempotency_key: str
    kind: str  # NODE | RELATIONSHIP | PROPERTIES
    created_id: Optional[str] = None
    target_id: Optional[str] = None
    previous_state: Optional[dict[str, Any]] = None
    changed_props: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "idempotency_key": self.idempotency_key,
            "kind": self.kind,
            "created_id": self.created_id,
            "target_id": self.target_id,
            "previous_state": self.previous_state,
            "changed_props": dict(self.changed_props),
        }


@dataclass
class ExecutionContext:
    """Contexto de una ejecucion concreta. Nada de esto sale del plan."""

    operator_id: str
    written_at: str
    applied_keys: AppliedKeyStore


@dataclass
class ExecutionOutcome:
    applied: list[AppliedOperation] = field(default_factory=list)
    noop_keys: list[str] = field(default_factory=list)

    @property
    def created_ids(self) -> list[str]:
        return [a.created_id for a in self.applied if a.created_id]


# --- Utilidades de lectura del driver -------------------------------------
def _field(record: Any, name: str) -> Any:
    """Lee un campo de un registro del driver sin asumir su clase concreta."""
    if record is None:
        return None
    if isinstance(record, dict):
        return record.get(name)
    try:
        return record[name]
    except (KeyError, TypeError, IndexError):
        return getattr(record, name, None)


def _single(tx: Any, query: cypher.Query) -> Any:
    """Ejecuta y devuelve el unico registro, o None. Traduce fallos del driver."""
    try:
        result = tx.run(query.cypher, query.params)
        return result.single() if result is not None else None
    except WriterAbort:
        raise
    except Exception as exc:
        raise WriterAbort(
            codes.EXEC_DRIVER_FAILURE,
            f"el driver fallo ejecutando la consulta: {exc}",
            {"cypher": query.cypher},
        ) from exc


# --- Precondiciones -------------------------------------------------------
def _check_expected_state(tx: Any, op: dict, workspace: str, target_id: str, is_assertion: bool) -> dict:
    """Concurrencia optimista. Un desajuste aborta el PLAN, no la operacion."""
    reader = cypher.read_assertion_state if is_assertion else cypher.read_entity_state
    record = _single(tx, reader(target_id, workspace))
    if record is None:
        raise WriterAbort(
            codes.EXEC_TARGET_MISSING,
            f"la operacion {op['operation_id']} apunta a {target_id!r}, que no existe",
            {"operation_id": op["operation_id"], "target_id": target_id},
        )
    version = _field(record, "version")
    state_hash = _field(record, "state_hash")
    if version != op["expected_version"]:
        raise WriterAbort(
            codes.EXEC_VERSION_MISMATCH,
            "la version leida no es la esperada: el grafo se movio bajo el plan",
            {
                "operation_id": op["operation_id"],
                "target_id": target_id,
                "expected_version": op["expected_version"],
                "actual_version": version,
            },
        )
    expected_hash = (op.get("expected_hash") or {}).get("value")
    if expected_hash is not None and state_hash != expected_hash:
        raise WriterAbort(
            codes.EXEC_HASH_MISMATCH,
            "el hash de estado leido no es el esperado",
            {
                "operation_id": op["operation_id"],
                "target_id": target_id,
                "expected_hash": expected_hash,
                "actual_hash": state_hash,
            },
        )
    return {"version": version, "state_hash": state_hash}


def _assert_absent(tx: Any, op: dict, workspace: str, target_id: str, is_assertion: bool) -> None:
    """CREATE-only estricto: crear algo que ya existe es un conflicto, no un update."""
    reader = cypher.read_assertion_state if is_assertion else cypher.read_entity_state
    if _single(tx, reader(target_id, workspace)) is not None:
        raise WriterAbort(
            codes.EXEC_TARGET_ALREADY_EXISTS,
            f"la operacion {op['operation_id']} crea {target_id!r}, que ya existe",
            {"operation_id": op["operation_id"], "target_id": target_id},
        )


def _require(value: Any, op: dict, what: str) -> Any:
    if not value:
        raise WriterAbort(
            codes.EXEC_UNSUPPORTED_PAYLOAD,
            f"la operacion {op['operation_id']} ({op['operation_type']}) exige {what}",
            {"operation_id": op["operation_id"], "missing": what},
        )
    return value


def _reason_code(op: dict) -> str:
    """R1: el motivo viaja al grafo o no se escribe.

    El contrato congelado de `fact-assertion` no tiene campo de motivo, asi que
    `COPYRIGHT_TAKEDOWN` y `EXTRACTION_ERROR` dejarian el mismo nodo. El ledger
    lo puso por escrito como requisito de integracion: el writer transporta el
    `reason_code` del payload, y si no viene, no cierra nada.
    """
    value = (op.get("payload") or {}).get("reason_code")
    if not isinstance(value, str) or not _REASON_CODE.match(value):
        raise WriterAbort(
            codes.EXEC_REASON_CODE_MISSING,
            f"la operacion {op['operation_id']} cierra una vigencia sin reason_code valido "
            "(R1 del ledger): sin el, el grafo no distingue un takedown de un error",
            {"operation_id": op["operation_id"], "reason_code": value},
        )
    return value


# --- Procedencia ----------------------------------------------------------
def _provenance(view: SignedView, op: dict, ctx: ExecutionContext) -> dict[str, Any]:
    """Lo que el writer estampa el mismo en todo lo que escribe.

    `written_snapshot_id` es el testigo externo de R2 dentro del propio grafo;
    `reason_codes` transporta las razones de la decision (R1).
    """
    decision = view.decision_by_id(op["decision_id"])
    return {
        "workspace": view.workspace,
        "version": 0,
        "written_snapshot_id": view.snapshot_id,
        "written_by_plan_hash": view.plan_hash_value,
        "written_by_operator": ctx.operator_id,
        "written_at": ctx.written_at,
        "idempotency_key": op["idempotency_key"],
        "decision_id": op["decision_id"],
        "reason_codes": list(decision.get("reason_codes") or []),
        "evidence_fragment_ids": list(op.get("evidence_fragment_ids") or []),
        "source_asset_id": view.source_asset_id,
        "collection_id": view.collection_id,
        "engine_version": view.engine_version,
        "ontology_version": view.ontology_version,
        "game_profile": view.game_profile,
    }


# --- Una operacion --------------------------------------------------------
def execute_operation(
    tx: Any, op: dict, view: SignedView, ctx: ExecutionContext
) -> AppliedOperation:
    op_type = op["operation_type"]
    if op_type not in SUPPORTED_TYPES:
        raise WriterAbort(
            codes.EXEC_UNSUPPORTED_OPERATION,
            f"tipo de operacion no soportado: {op_type}",
            {"operation_id": op["operation_id"], "operation_type": op_type},
        )
    ws = view.workspace
    payload = dict(op.get("payload") or {})
    props = cypher.safe_props(payload)
    prov = _provenance(view, op, ctx)

    if op_type == "CREATE_ENTITY":
        entity_id = _require(op.get("target_entity_id"), op, "target_entity_id")
        _assert_absent(tx, op, ws, entity_id, is_assertion=False)
        label = payload.get("entity_type")
        record = _single(
            tx, cypher.create_entity(entity_id, ws, label, {**props, **prov})
        )
        return AppliedOperation(
            operation_id=op["operation_id"],
            operation_type=op_type,
            idempotency_key=op["idempotency_key"],
            kind="NODE",
            created_id=_field(record, "id") or entity_id,
            target_id=entity_id,
        )

    if op_type == "CREATE_ASSERTION":
        assertion_id = _require(op.get("assertion_id"), op, "assertion_id")
        _assert_absent(tx, op, ws, assertion_id, is_assertion=True)
        record = _single(
            tx, cypher.create_assertion(assertion_id, ws, {**props, **prov})
        )
        return AppliedOperation(
            operation_id=op["operation_id"],
            operation_type=op_type,
            idempotency_key=op["idempotency_key"],
            kind="NODE",
            created_id=_field(record, "id") or assertion_id,
            target_id=assertion_id,
        )

    if op_type in RELATION_TYPES:
        subject = _require(payload.get("subject_entity_id"), op, "payload.subject_entity_id")
        obj = _require(payload.get("object_entity_id"), op, "payload.object_entity_id")
        predicate = _require(payload.get("predicate"), op, "payload.predicate")
        target = op.get("target_entity_id") or subject
        previous = _check_expected_state(tx, op, ws, target, is_assertion=False)
        rel_props = {k: v for k, v in props.items() if k != "predicate"}
        record = _single(
            tx, cypher.create_relation(predicate, subject, obj, ws, {**rel_props, **prov})
        )
        return AppliedOperation(
            operation_id=op["operation_id"],
            operation_type=op_type,
            idempotency_key=op["idempotency_key"],
            kind="RELATIONSHIP",
            created_id=_field(record, "id"),
            target_id=target,
            previous_state=previous,
        )

    # Cierre de vigencia: UPDATE_ENTITY / SUPERSEDE_ASSERTION.
    is_assertion = op_type == "SUPERSEDE_ASSERTION"
    target = _require(
        op.get("assertion_id") if is_assertion else op.get("target_entity_id"),
        op,
        "assertion_id" if is_assertion else "target_entity_id",
    )
    reason = _reason_code(op)
    previous = _check_expected_state(tx, op, ws, target, is_assertion=is_assertion)
    changed = {
        k: v for k, v in props.items() if k in cypher.ALLOWED_UPDATE_PROPS and k != "version"
    }
    changed["reason_code"] = reason
    changed["version"] = int(op["expected_version"]) + 1
    changed["updated_at"] = ctx.written_at
    writer_fn = (
        cypher.close_assertion_validity if is_assertion else cypher.close_entity_validity
    )
    _single(tx, writer_fn(target, ws, changed))
    return AppliedOperation(
        operation_id=op["operation_id"],
        operation_type=op_type,
        idempotency_key=op["idempotency_key"],
        kind="PROPERTIES",
        target_id=target,
        previous_state=previous,
        changed_props=changed,
    )


# --- El plan entero -------------------------------------------------------
def execute_plan(driver: Any, view: SignedView, ctx: ExecutionContext) -> ExecutionOutcome:
    """Aplica el plan en UNA transaccion. Cualquier fallo la revierte entera.

    Las claves de idempotencia se registran DESPUES del commit: marcarlas antes
    perderia para siempre una operacion que la transaccion acabo revirtiendo.
    """
    outcome = ExecutionOutcome()
    pending: list[AppliedOperation] = []

    try:
        session_cm = driver.session()
    except Exception as exc:
        raise WriterAbort(
            codes.EXEC_DRIVER_FAILURE, f"no se pudo abrir la sesion: {exc}"
        ) from exc

    with session_cm as session:
        try:
            tx = session.begin_transaction()
        except Exception as exc:
            raise WriterAbort(
                codes.EXEC_DRIVER_FAILURE, f"no se pudo abrir la transaccion: {exc}"
            ) from exc
        try:
            for op in view.mutation_operations:
                key = op["idempotency_key"]
                if ctx.applied_keys.is_applied(key):
                    # No-op contabilizado: no llega al driver, no escribe dos veces.
                    outcome.noop_keys.append(key)
                    continue
                pending.append(execute_operation(tx, op, view, ctx))
            tx.commit()
        except Exception:
            try:
                tx.rollback()
            except Exception:  # pragma: no cover - rollback del rollback
                pass
            raise

    for applied in pending:
        ctx.applied_keys.record(
            applied.idempotency_key,
            {
                "workspace": view.workspace,
                "snapshot_id": view.snapshot_id,
                "plan_hash": view.plan_hash_value,
                "operation_id": applied.operation_id,
                "operation_type": applied.operation_type,
                "target_id": applied.target_id,
                "created_id": applied.created_id,
                "applied_at": ctx.written_at,
                "operator_id": ctx.operator_id,
            },
        )
    outcome.applied = pending
    return outcome


def simulate_plan(view: SignedView, ctx: ExecutionContext) -> ExecutionOutcome:
    """Dry-run: clasifica sin tocar el driver.

    No recibe driver. No puede tocarlo aunque quisiera: no lo tiene.
    """
    outcome = ExecutionOutcome()
    for op in view.mutation_operations:
        key = op["idempotency_key"]
        if ctx.applied_keys.is_applied(key):
            outcome.noop_keys.append(key)
            continue
        outcome.applied.append(
            AppliedOperation(
                operation_id=op["operation_id"],
                operation_type=op["operation_type"],
                idempotency_key=key,
                kind="SIMULATED",
                target_id=op.get("target_entity_id") or op.get("assertion_id"),
            )
        )
    return outcome


__all__ = [
    "AppliedOperation",
    "ExecutionContext",
    "ExecutionOutcome",
    "execute_operation",
    "execute_plan",
    "simulate_plan",
    "SUPPORTED_TYPES",
]
