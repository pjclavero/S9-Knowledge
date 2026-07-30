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
#: `ATTEMPTED` solo existe como LINEA de auditoria, nunca como resultado: se
#: escribe antes de tocar el grafo para que un APPLY que se cae de formas que
#: nadie previo —la maquina, el proceso— deje igualmente constancia de que se
#: intento.
OUTCOME_ATTEMPTED = "ATTEMPTED"
OUTCOME_APPLIED = "APPLIED"
OUTCOME_SIMULATED = "SIMULATED"
OUTCOME_REJECTED = "REJECTED"  # la admision dijo que no
OUTCOME_BLOCKED = "BLOCKED"  # el gate dijo que no
OUTCOME_ABORTED = "ABORTED"  # empezo y se revirtio entera

MODE_DRY_RUN = "DRY_RUN"
MODE_APPLY = "APPLY"


def _unsigned_field(plan_doc: Any, name: str) -> Any:
    """Lee un campo informativo del documento SIN poder fallar.

    «Todo intento deja linea» no admite excepciones porque un campo venga mal
    formado: un documento que no es un dict, o un `plan_id` que resulta ser una
    lista, no pueden dejar el intento sin auditar.
    """
    if not isinstance(plan_doc, dict):
        return None
    value = plan_doc.get(name)
    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        return value
    return repr(value)  # pragma: no cover - tipo exotico: se describe, no se pierde


def _hash_value_of(plan_doc: Any) -> Optional[str]:
    """`plan_hash.value` si de verdad es un bloque de hash; si no, su repr.

    Un `plan_hash` que sea la cadena `"no-es-un-bloque"` es truthy y no tiene
    `.get`: leerlo a la ligera reventaria con `AttributeError` justo en el
    camino de auditoria, dejando el intento sin codigo y sin linea.
    """
    if not isinstance(plan_doc, dict):
        return None
    block = plan_doc.get("plan_hash")
    if isinstance(block, dict):
        value = block.get("value")
        return value if isinstance(value, str) else None
    if block is None:
        return None
    return repr(block)


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
        driver_factory: Optional[Callable[[], Any]] = None,
        audit: Optional[AuditSink] = None,
        applied_keys: Optional[AppliedKeyStore] = None,
        clock: Callable[[], datetime] = utc_now,
        max_operations: int = DEFAULT_MAX_OPERATIONS,
    ):
        """`driver_factory` se invoca DESPUES del gate, nunca antes.

        Abrir la conexion al construir el writer significaria usar credenciales
        y ocupar una sesion para un APPLY que el gate todavia puede bloquear.
        Quien ya tenga un driver puede seguir pasandolo por `driver`.
        """
        if not workspace:
            raise ValueError("un writer necesita workspace: no hay writer 'global'")
        self.workspace = workspace
        self.driver = driver
        self.driver_factory = driver_factory
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
        plan_doc: Any,
        rejections: list[Rejection],
        *,
        applied: int = 0,
        noop: int = 0,
        created_ids: Optional[list[str]] = None,
        detail: Optional[dict[str, Any]] = None,
    ) -> tuple[dict[str, Any], Optional[Rejection]]:
        """Deja constancia del intento y dice si lo consiguio.

        Devuelve `(registro, fallo)`. El segundo elemento no es `None` cuando el
        sink dijo estar disponible y `append` fallo igualmente: quien escribio
        sin dejar rastro tiene que enterarse.

        Aqui SI se leen los campos informativos que el `SignedView` niega al
        resto del writer, y van al bloque `unsigned`: la auditoria describe, no
        decide.

        Todo lo que se lee del documento pasa por `_unsigned_field`, que jamas
        lanza. Un `plan_hash` que no sea un bloque, un documento que no sea un
        dict o un `plan_id` que sea una lista no pueden dejar un intento sin su
        linea: «todo intento deja rastro» no admite excepciones por un campo mal
        formado.
        """
        record = AuditRecord(
            timestamp=self._now_iso(),
            outcome=outcome,
            mode=mode,
            workspace=self.workspace,
            operator_id=req.operator_id,
            plan_hash=_hash_value_of(plan_doc),
            snapshot_id=_unsigned_field(plan_doc, "snapshot_id"),
            plan_id=_unsigned_field(plan_doc, "plan_id"),
            rejections=[r.to_dict() for r in rejections],
            applied_operations=applied,
            noop_operations=noop,
            created_ids=list(created_ids or []),
            unsigned={
                "created_at": _unsigned_field(plan_doc, "created_at"),
                "plan_id": _unsigned_field(plan_doc, "plan_id"),
                "provider_trace": _unsigned_field(plan_doc, "provider_trace"),
                "metadata": _unsigned_field(plan_doc, "metadata"),
            },
            detail=detail or {},
        )
        try:
            self.audit.append(record)
        except Exception as exc:
            return record.to_dict(), Rejection(
                code=codes.AUDIT_APPEND_FAILED,
                message=f"el registro de auditoria se declaro disponible pero fallo al escribir: {exc}",
                detail={"outcome": outcome},
            )
        return record.to_dict(), None

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
            return self._finish(
                OUTCOME_REJECTED, mode, req, plan_doc, admission.rejections
            )
        view: SignedView = admission.view  # type: ignore[assignment]

        # 2. Gate de operador: nueve condiciones, solo para APPLY.
        if mode == MODE_APPLY:
            gate_req = OperatorRequest(
                apply=req.apply,
                operator_id=req.operator_id,
                workspace=req.workspace,
                expected_plan_hash=req.expected_plan_hash,
                max_operations=self._effective_limit(req.max_operations),
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
                return self._finish(OUTCOME_BLOCKED, mode, req, plan_doc, gate.rejections)

        exec_ctx = ExecutionContext(
            operator_id=req.operator_id or "",
            written_at=self._now_iso(),
            applied_keys=self.applied_keys,
        )

        # 3a. Dry-run: no recibe el driver, luego no puede tocarlo.
        if mode == MODE_DRY_RUN:
            try:
                outcome: ExecutionOutcome = simulate_plan(view, exec_ctx)
            except WriterError as exc:
                return self._finish(
                    OUTCOME_ABORTED, mode, req, plan_doc, [exc.as_rejection()]
                )
            return self._finish(
                OUTCOME_SIMULATED,
                mode,
                req,
                plan_doc,
                [],
                applied=len(outcome.applied),
                noop=len(outcome.noop_keys),
            )

        # 3b. Rastro ANTES de escribir. La condicion 9 del gate garantiza que el
        #     sink SE DECLARA disponible, no que funcione: un sink que promete y
        #     falla dejaria una escritura real sin una sola linea. Si esta no
        #     entra, no se escribe — es la misma regla de siempre, aplicada al
        #     unico momento en que todavia se puede obedecer.
        _, attempt_failure = self._audit(
            OUTCOME_ATTEMPTED,
            mode,
            req,
            plan_doc,
            [],
            detail={"operations": len(view.mutation_operations)},
        )
        if attempt_failure is not None:
            blocked = Rejection(
                code=codes.GATE_AUDIT_UNAVAILABLE,
                message="el registro de auditoria fallo al anotar el intento; sin rastro no se escribe",
                detail={"error": attempt_failure.message},
            )
            return WriteResult(
                outcome=OUTCOME_BLOCKED, mode=mode, rejections=[blocked]
            )

        # 3c. APPLY: una transaccion, todo o nada.
        driver, driver_failure = self._resolve_driver()
        if driver_failure is not None:
            return self._finish(OUTCOME_ABORTED, mode, req, plan_doc, [driver_failure])
        try:
            outcome = execute_plan(driver, view, exec_ctx)
        except WriterError as exc:
            return self._finish(OUTCOME_ABORTED, mode, req, plan_doc, [exc.as_rejection()])
        except Exception as exc:  # el driver puede fallar de formas que no controlamos
            rejection = Rejection(
                code=codes.EXEC_DRIVER_FAILURE,
                message=f"la transaccion se revirtio: {exc}",
            )
            return self._finish(OUTCOME_ABORTED, mode, req, plan_doc, [rejection])

        rollback = build_rollback(view, outcome.applied)
        return self._finish(
            OUTCOME_APPLIED,
            mode,
            req,
            plan_doc,
            [],
            applied=len(outcome.applied),
            noop=len(outcome.noop_keys),
            created_ids=outcome.created_ids,
            rollback=rollback,
            detail={"rollback": rollback.to_dict()},
        )

    # -- Piezas de `write` -------------------------------------------------
    def _effective_limit(self, requested: Optional[int]) -> Any:
        """El limite que de verdad aplica: el MENOR de los dos declarados.

        El del writer es politica del despliegue y el de la peticion es del
        operador; ninguno puede relajar al otro, asi que manda el mas estrecho.
        Que `OperatorRequest.max_operations` valga `None` por defecto es lo que
        permite distinguir «el operador no opina» de «el operador pide 200», y
        sin esa distincion el limite del writer seria decorativo.
        """
        if requested is None:
            return self.max_operations
        if isinstance(requested, bool) or not isinstance(requested, int):
            return requested  # que lo rechace el gate, con su codigo
        if isinstance(self.max_operations, int) and not isinstance(self.max_operations, bool):
            return min(requested, self.max_operations)
        return requested  # pragma: no cover - writer mal construido

    def _resolve_driver(self) -> tuple[Any, Optional[Rejection]]:
        """Obtiene el driver DESPUES del gate. Antes seria abrir sin permiso."""
        if self.driver is not None:
            return self.driver, None
        if self.driver_factory is None:
            return None, Rejection(
                code=codes.EXEC_DRIVER_FAILURE,
                message="APPLY sin driver inyectado: este writer no abre conexiones por su cuenta",
            )
        try:
            driver = self.driver_factory()
        except Exception as exc:
            return None, Rejection(
                code=codes.EXEC_DRIVER_FAILURE,
                message=f"la fabrica de driver fallo: {exc}",
            )
        if driver is None:
            return None, Rejection(
                code=codes.EXEC_DRIVER_FAILURE,
                message="la fabrica de driver no devolvio ningun driver",
            )
        return driver, None

    def _finish(
        self,
        outcome: str,
        mode: str,
        req: OperatorRequest,
        plan_doc: Any,
        rejections: list[Rejection],
        *,
        applied: int = 0,
        noop: int = 0,
        created_ids: Optional[list[str]] = None,
        rollback: Optional[RollbackDocument] = None,
        detail: Optional[dict[str, Any]] = None,
    ) -> WriteResult:
        """Audita el desenlace y lo devuelve.

        Si el sink prometio estar disponible y luego fallo, el fallo VIAJA en el
        resultado: un APPLY que se aplico sin dejar su linea sigue aplicado, y el
        operador tiene que enterarse de que el rastro no esta.
        """
        record, failure = self._audit(
            outcome,
            mode,
            req,
            plan_doc,
            rejections,
            applied=applied,
            noop=noop,
            created_ids=created_ids,
            detail=detail,
        )
        todas = list(rejections)
        if failure is not None:
            todas.append(failure)
        return WriteResult(
            outcome=outcome,
            mode=mode,
            rejections=todas,
            applied_operations=applied,
            noop_operations=noop,
            created_ids=list(created_ids or []),
            rollback=rollback,
            audit_record=record,
        )


__all__ = [
    "GraphWriter",
    "WriteResult",
    "OUTCOME_ATTEMPTED",
    "OUTCOME_APPLIED",
    "OUTCOME_SIMULATED",
    "OUTCOME_REJECTED",
    "OUTCOME_BLOCKED",
    "OUTCOME_ABORTED",
    "MODE_APPLY",
    "MODE_DRY_RUN",
]
