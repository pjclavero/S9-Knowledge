# -*- coding: utf-8 -*-
"""Gate de operador: nueve condiciones, todas obligatorias.

Es el equivalente V3 de `review/controlled_ingest/policy.py`, adaptado a un plan
sellado. La forma se conserva porque funciona: **si falta UNA sola condicion, no
se escribe**. El gate no escribe nada ni consulta el grafo; solo decide si una
escritura real estaria permitida.

Diferencia de fondo con el V1: alli el permiso lo daba el estado del plan de
revision; aqui el plan ya viene sellado y la admision lo ha juzgado, asi que el
gate se ocupa solo de lo que aporta el OPERADOR — su identidad, su confirmacion
del hash, su declaracion doble del workspace, el permiso del entorno y el limite
de volumen.

El dry-run no pasa por aqui: es el modo por defecto y no toca el driver. El gate
existe para el APPLY, y por eso «no se pidio APPLY» es una de las nueve
condiciones y no una rama aparte.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from . import codes
from .errors import Rejection
from .view import SignedView

#: Permiso del entorno. Vale exactamente "1"; cualquier otra cosa es un no.
ENV_ALLOW_REAL_INGEST = "S9K_ALLOW_REAL_INGEST"
#: Segunda declaracion del workspace, independiente del argumento de la CLI.
ENV_WRITER_WORKSPACE = "S9K_WRITER_WORKSPACE"

#: Limite de operaciones por plan si nadie configura otro.
DEFAULT_MAX_OPERATIONS = 200

_OPERATOR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


@dataclass
class OperatorRequest:
    """Lo que aporta el operador. Todo explicito, nada por defecto peligroso."""

    #: `False` = dry-run. La escritura real exige ponerlo a True A MANO.
    apply: bool = False
    operator_id: Optional[str] = None
    #: Workspace declarado como argumento (la otra declaracion va en el entorno).
    workspace: Optional[str] = None
    #: Hash del plan que el operador dice estar autorizando (valor sha256 hex o
    #: el bloque {algorithm, value} entero).
    expected_plan_hash: Any = None
    max_operations: int = DEFAULT_MAX_OPERATIONS
    #: Snapshot vigente que el operador declara (testigo externo, R2).
    current_snapshot_id: Optional[str] = None
    env: Optional[dict[str, str]] = None


@dataclass
class GateResult:
    rejections: list[Rejection] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return not self.rejections

    @property
    def codes(self) -> list[str]:
        return [r.code for r in self.rejections]


def _reject(out: list[Rejection], code: str, message: str, **detail: Any) -> None:
    out.append(Rejection(code=code, message=message, detail=detail))


def _hash_value(confirmed: Any) -> Optional[str]:
    """Normaliza la confirmacion del operador a un valor hex, o None."""
    if isinstance(confirmed, str):
        return confirmed.strip().lower() or None
    if isinstance(confirmed, dict):
        value = confirmed.get("value")
        return value.strip().lower() if isinstance(value, str) and value.strip() else None
    return None


def evaluate(
    view: SignedView,
    req: OperatorRequest,
    *,
    audit_available: bool,
) -> GateResult:
    """Evalua las nueve condiciones. `allowed` solo si se cumplen TODAS."""
    env = req.env if req.env is not None else dict(os.environ)
    rejections: list[Rejection] = []

    # 1. Permiso del entorno.
    if env.get(ENV_ALLOW_REAL_INGEST) != "1":
        _reject(
            rejections,
            codes.GATE_ENV_NOT_ALLOWED,
            f"{ENV_ALLOW_REAL_INGEST} no vale '1'",
            value=env.get(ENV_ALLOW_REAL_INGEST),
        )

    # 2. APPLY explicito. El modo por defecto es dry-run.
    if req.apply is not True:
        _reject(
            rejections,
            codes.GATE_APPLY_NOT_REQUESTED,
            "no se pidio APPLY: el modo por defecto es dry-run",
        )

    # 3-4. Identidad del operador: presente y con forma admisible.
    if not req.operator_id:
        _reject(rejections, codes.GATE_OPERATOR_MISSING, "operator_id ausente")
    elif not _OPERATOR_ID.match(req.operator_id):
        _reject(
            rejections,
            codes.GATE_OPERATOR_INVALID,
            "operator_id con forma no admisible",
            operator_id=req.operator_id,
        )

    # 5. Confirmacion explicita del hash del plan. El operador tiene que escribir
    #    el hash que cree estar autorizando; si el plan cambio, no coincide.
    confirmed = _hash_value(req.expected_plan_hash)
    if confirmed is None:
        _reject(
            rejections,
            codes.GATE_PLAN_HASH_NOT_CONFIRMED,
            "el operador no confirmo el plan_hash",
        )
    elif confirmed != view.plan_hash_value:
        _reject(
            rejections,
            codes.GATE_PLAN_HASH_NOT_CONFIRMED,
            "el plan_hash confirmado no es el del plan",
            confirmed=confirmed,
            actual=view.plan_hash_value,
        )

    # 6. Limite de operaciones por plan.
    limit = req.max_operations
    if not isinstance(limit, int) or limit < 1 or len(view.mutation_operations) > limit:
        _reject(
            rejections,
            codes.GATE_OPERATION_LIMIT_EXCEEDED,
            "el plan supera el limite de operaciones autorizado",
            operations=len(view.mutation_operations),
            limit=limit,
        )

    # 7-8. Workspace declarado DOS veces y coincidente. Una sola declaracion es
    #      un dedo resbalando; dos que coinciden es una intencion.
    env_workspace = env.get(ENV_WRITER_WORKSPACE)
    if not env_workspace:
        _reject(
            rejections,
            codes.GATE_WORKSPACE_NOT_DECLARED,
            f"{ENV_WRITER_WORKSPACE} ausente: el workspace no se declaro dos veces",
        )
    elif not req.workspace or env_workspace != req.workspace:
        _reject(
            rejections,
            codes.GATE_WORKSPACE_DECLARATION_MISMATCH,
            "el workspace del entorno y el del argumento no coinciden",
            env=env_workspace,
            argument=req.workspace,
        )

    # 9. Registro de auditoria utilizable. Sin rastro no se escribe.
    if not audit_available:
        _reject(
            rejections,
            codes.GATE_AUDIT_UNAVAILABLE,
            "no hay registro de auditoria utilizable",
        )

    return GateResult(rejections=rejections)


__all__ = [
    "OperatorRequest",
    "GateResult",
    "evaluate",
    "ENV_ALLOW_REAL_INGEST",
    "ENV_WRITER_WORKSPACE",
    "DEFAULT_MAX_OPERATIONS",
]
