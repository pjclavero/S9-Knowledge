# -*- coding: utf-8 -*-
"""`GraphWriter`: la unica puerta fisica al grafo.

Orden de evaluacion, y el orden importa:

    admision  ->  gate de operador  ->  ejecucion
    (siempre)     (solo si APPLY)      (dry-run o transaccion)

* La **admision** se ejecuta siempre, tambien en dry-run: un plan inadmisible no
  se simula, porque un informe de simulacion es lo que un operador lee antes de
  autorizar y darselo a un plan invalido seria prestarle credibilidad.
* El **gate** solo bloquea el APPLY. El dry-run es seguro por construccion —
  literalmente no recibe el driver — asi que no necesita permiso.
* La **ejecucion** es transaccional. Si aborta, no queda nada escrito.

TODO intento deja linea en el registro de auditoria: aceptado, rechazado,
bloqueado o abortado. Un writer que solo audita los exitos no sirve para
averiguar qué pasó.

Un writer, un workspace (R3 del ledger). El workspace se fija en el constructor
y no se puede cambiar en una peticion: el aislamiento no es un parametro.

El driver se INYECTA y puede ser `None` si solo se va a simular. Este modulo no
importa `neo4j` ni conoce ninguna URL o credencial.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import codes
from .admission import AdmissionContext, admit, utc_now
from .audit import AuditRecord, AuditSink, InMemoryAuditSink
from .errors import Rejection, WriterAbort, WriterError
from .executor import ExecutionContext, ExecutionOutcome, execute_plan, simulate_plan
from .gate import DEFAULT_MAX_OPERATIONS, OperatorRequest, evaluate
from .idempotency import AppliedKeyStore, InMemoryAppliedKeys
from .rollback import RollbackDocument, build_rollback
from .view import SignedView

#: Resultados posibles de un intento. Entran en el registro de auditoria.
OUTCOME_APPLIED = "APPLIED"
OUTCOME_SIMULATED = "SIMULATED"
OUTCOME_REJECTED = "REJECTED"  # la admision dijo que no
OUTCOME_BLOCKED = "BLOCKED"  # el gate dijo que no
OUTCOME_ABORTED = "ABORTED"  # empezo y se revirtio entera

MODE_DRY_RUN = "DRY_RUN"
MODE_APPLY = "APPLY"


@dataclass
class WriteResult:
    outcome: str
    mode: str
    rejections: list[Rejection] = field(default_factory=list)
    applied_operations: int = 0
    noop_operations: int = 0
    created_ids: list[str] = field(default_factory=list)
    rollback: Optional[RollbackDocument] = None
    audit_record: Optional[dict[str, Any]] = None

    @property
    def ok(self) -> bool:
        return self.outcome in (OUTCOME_APPLIED, OUTCOME_SIMULATED)

    @property
    def codes(self) -> list[str]:
        return [r.code for r in self.rejections]

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "mode": self.mode,
            "rejections": [r.to_dict() for r in self.rejections],
            "applied_operations": self.applied_operations,
            "noop_operations": self.noop_operations,
            "created_ids": list(self.created_ids),
            "rollback": self.rollback.to_dict() if self.rollback else None,
        }


class GraphWriter:
    """Escritor de UN workspace. Un writer por workspace, sin excepciones."""

    def __init__(
        self,
        *,
        workspace: str,
        driver: Any = None,
        audit: Optional[AuditSink] = None,
        applied_keys: Optional[AppliedKeyStore] = None,
        clock: Callable[[], datetime] = utc_now,
        max_operations: int = DEFAULT_MAX_OPERATIONS,
    ):
        if not workspace:
            raise ValueError("un writer necesita workspace: no hay writer 'global'")
        self.workspace = workspace
        self.driver = driver
        self.audit = audit if audit is not None else InMemoryAuditSink()
        self.applied_keys = applied_keys if applied_keys is not None else InMemoryAppliedKeys()
        self.clock = clock
        self.max_operations = max_operations

    # -- Auditoria ---------------------------------------------------------
    def _now_iso(self) -> str:
        now = self.clock()
        if now.tzinfo is None:  # pragma: no cover - reloj mal inyectado
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _audit(
        self,
        outcome: str,
        mode: str,
        req: OperatorRequest,
        plan_doc: dict,
        rejections: list[Rejection],
        *,
        applied: int = 0,
        noop: int = 0,
        created_ids: Optional[list[str]] = None,
        detail: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """Deja constancia del intento. Nunca decide nada; solo describe.

        Aqui SI se leen `plan_id` y demas campos informativos: la prohibicion del
        contrato es sobre decisiones de escritura, y esto no lo es.
        """
        record = AuditRecord(
            timestamp=self._now_iso(),
            outcome=outcome,
            mode=mode,
            workspace=self.workspace,
            operator_id=req.operator_id,
            plan_hash=(plan_doc.get("plan_hash") or {}).get("value")
            if isinstance(plan_doc, dict)
            else None,
            snapshot_id=plan_doc.get("snapshot_id") if isinstance(plan_doc, dict) else None,
            plan_id=plan_doc.get("plan_id") if isinstance(plan_doc, dict) else None,
            rejections=[r.to_dict() for r in rejections],
            applied_operations=applied,
            noop_operations=noop,
            created_ids=list(created_ids or []),
            detail=detail or {},
        )
        try:
            self.audit.append(record)
        except Exception:  # pragma: no cover - el sink real ya se comprobo antes
            return record.to_dict()
        return record.to_dict()

    # -- Puerta ------------------------------------------------------------
    def write(self, plan_doc: dict[str, Any], req: OperatorRequest) -> WriteResult:
        """Unico metodo publico de escritura. Fail-closed en cada paso."""
        mode = MODE_APPLY if req.apply is True else MODE_DRY_RUN

        # 1. Admision. Siempre, y antes que nada.
        ctx = AdmissionContext(
            workspace=self.workspace,
            current_snapshot_id=req.current_snapshot_id,
            clock=self.clock,
        )
        admission = admit(plan_doc, ctx)
        if not admission.admitted:
            record = self._audit(
                OUTCOME_REJECTED, mode, req, plan_doc, admission.rejections
            )
            return WriteResult(
                outcome=OUTCOME_REJECTED,
                mode=mode,
                rejections=admission.rejections,
                audit_record=record,
            )
        view: SignedView = admission.view  # type: ignore[assignment]

        # 2. Gate de operador: nueve condiciones, solo para APPLY.
        if mode == MODE_APPLY:
            limit = req.max_operations if req.max_operations is not None else self.max_operations
            gate_req = OperatorRequest(
                apply=req.apply,
                operator_id=req.operator_id,
                workspace=req.workspace,
                expected_plan_hash=req.expected_plan_hash,
                max_operations=limit,
                current_snapshot_id=req.current_snapshot_id,
                env=req.env,
            )
            available = False
            try:
                available = bool(self.audit.available())
            except Exception:  # pragma: no cover - sink roto = no disponible
                available = False
            gate = evaluate(view, gate_req, audit_available=available)
            # R3: aunque el gate mire el entorno y el argumento, el workspace que
            # manda es el del writer. Coincide por construccion con el del plan
            # (la admision ya lo comprobo), y esta comparacion cierra el triangulo.
            if req.workspace and req.workspace != self.workspace:
                gate.rejections.append(
                    Rejection(
                        code=codes.GATE_WORKSPACE_DECLARATION_MISMATCH,
                        message="el workspace declarado no es el de este writer",
                        detail={"argument": req.workspace, "writer": self.workspace},
                    )
                )
            if not gate.allowed:
                record = self._audit(
                    OUTCOME_BLOCKED, mode, req, plan_doc, gate.rejections
                )
                return WriteResult(
                    outcome=OUTCOME_BLOCKED,
                    mode=mode,
                    rejections=gate.rejections,
                    audit_record=record,
                )

        exec_ctx = ExecutionContext(
            operator_id=req.operator_id or "",
            written_at=self._now_iso(),
            applied_keys=self.applied_keys,
        )

        # 3a. Dry-run: no recibe el driver, luego no puede tocarlo.
        if mode == MODE_DRY_RUN:
            outcome: ExecutionOutcome = simulate_plan(view, exec_ctx)
            record = self._audit(
                OUTCOME_SIMULATED,
                mode,
                req,
                plan_doc,
                [],
                applied=len(outcome.applied),
                noop=len(outcome.noop_keys),
            )
            return WriteResult(
                outcome=OUTCOME_SIMULATED,
                mode=mode,
                applied_operations=len(outcome.applied),
                noop_operations=len(outcome.noop_keys),
                audit_record=record,
            )

        # 3b. APPLY: una transaccion, todo o nada.
        if self.driver is None:
            rejection = Rejection(
                code=codes.EXEC_DRIVER_FAILURE,
                message="APPLY sin driver inyectado: este writer no abre conexiones por su cuenta",
            )
            record = self._audit(OUTCOME_ABORTED, mode, req, plan_doc, [rejection])
            return WriteResult(
                outcome=OUTCOME_ABORTED,
                mode=mode,
                rejections=[rejection],
                audit_record=record,
            )
        try:
            outcome = execute_plan(self.driver, view, exec_ctx)
        except WriterError as exc:
            rejection = exc.as_rejection()
            record = self._audit(OUTCOME_ABORTED, mode, req, plan_doc, [rejection])
            return WriteResult(
                outcome=OUTCOME_ABORTED,
                mode=mode,
                rejections=[rejection],
                audit_record=record,
            )
        except Exception as exc:  # el driver puede fallar de formas que no controlamos
            rejection = Rejection(
                code=codes.EXEC_DRIVER_FAILURE,
                message=f"la transaccion se revirtio: {exc}",
            )
            record = self._audit(OUTCOME_ABORTED, mode, req, plan_doc, [rejection])
            return WriteResult(
                outcome=OUTCOME_ABORTED,
                mode=mode,
                rejections=[rejection],
                audit_record=record,
            )

        rollback = build_rollback(view, outcome.applied)
        record = self._audit(
            OUTCOME_APPLIED,
            mode,
            req,
            plan_doc,
            [],
            applied=len(outcome.applied),
            noop=len(outcome.noop_keys),
            created_ids=outcome.created_ids,
            detail={"rollback": rollback.to_dict()},
        )
        return WriteResult(
            outcome=OUTCOME_APPLIED,
            mode=mode,
            applied_operations=len(outcome.applied),
            noop_operations=len(outcome.noop_keys),
            created_ids=outcome.created_ids,
            rollback=rollback,
            audit_record=record,
        )


__all__ = [
    "GraphWriter",
    "WriteResult",
    "OUTCOME_APPLIED",
    "OUTCOME_SIMULATED",
    "OUTCOME_REJECTED",
    "OUTCOME_BLOCKED",
    "OUTCOME_ABORTED",
    "MODE_APPLY",
    "MODE_DRY_RUN",
]
