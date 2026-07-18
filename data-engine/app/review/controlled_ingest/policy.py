"""Gate de APPLY: politica de ingesta controlada.

APPLY solo se permite si se cumplen SIMULTANEAMENTE todas las condiciones. Si
falta UNA sola, el resultado es BLOCKED. AUTO_APPROVABLE es solo recomendacion y
jamas basta: la revision humana sigue siendo obligatoria. Este gate NO escribe;
solo decide si un APPLY estaria permitido.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from .hashing import hash_block

_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")

# Variable de entorno que debe estar explicitamente en "true".
ENV_ALLOW_REAL_INGEST = "S9K_ALLOW_REAL_INGEST"


@dataclass
class ApplyRequest:
    mode: str  # se exige "APPLY"
    plan_doc: dict[str, Any]
    expected_plan_hash: dict[str, str]
    expected_review_hash: dict[str, str]
    operator_id: str | None
    production_env: bool  # entorno productivo explicito
    cli_confirmed: bool  # confirmacion explicita de la CLI
    env: dict[str, str] | None = None  # por defecto os.environ


@dataclass
class ApplyGate:
    allowed: bool
    blocked_reasons: list[str] = field(default_factory=list)


def _valid_operator(op: str | None) -> bool:
    return bool(op) and bool(_STABLE_ID.match(op or ""))


def evaluate_apply(req: ApplyRequest) -> ApplyGate:
    """Evalua todas las condiciones. Devuelve allowed=True solo si TODAS se cumplen."""
    env = req.env if req.env is not None else dict(os.environ)
    reasons: list[str] = []

    # 1. modo APPLY explicito.
    if req.mode != "APPLY":
        reasons.append(f"mode debe ser APPLY (recibido {req.mode!r})")

    plan = req.plan_doc
    auth = plan.get("authorization", {})

    # 2. authorization.granted == true.
    if auth.get("granted") is not True:
        reasons.append("authorization.granted != true")

    # 3. operator_id valido (en la peticion y en la autorizacion del plan).
    if not _valid_operator(req.operator_id):
        reasons.append("operator_id ausente o invalido")
    elif auth.get("operator_id") not in (None, req.operator_id):
        reasons.append("operator_id no coincide con la autorizacion del plan")

    # 4. hash de plan exacto.
    actual_plan_hash = hash_block(plan)
    if req.expected_plan_hash != actual_plan_hash:
        reasons.append("hash de plan no coincide (plan alterado o desactualizado)")

    # 5. hash de review exacto.
    if plan.get("review_hash") != req.expected_review_hash:
        reasons.append("hash de review no coincide")

    # 6. S9K_ALLOW_REAL_INGEST == "true".
    if env.get(ENV_ALLOW_REAL_INGEST) != "true":
        reasons.append(f"{ENV_ALLOW_REAL_INGEST} no es 'true'")

    # 7. entorno productivo explicito.
    if req.production_env is not True:
        reasons.append("entorno productivo no confirmado explicitamente")

    # 8. confirmacion explicita de la CLI.
    if req.cli_confirmed is not True:
        reasons.append("confirmacion de CLI ausente")

    # 9. el plan debe estar listo (sin conflictos abiertos).
    if plan.get("status") != "READY_TO_APPLY":
        reasons.append(f"status del plan != READY_TO_APPLY ({plan.get('status')!r})")
    if plan.get("conflicts"):
        reasons.append("el plan tiene conflictos abiertos")

    return ApplyGate(allowed=not reasons, blocked_reasons=reasons)


__all__ = ["ApplyRequest", "ApplyGate", "evaluate_apply", "ENV_ALLOW_REAL_INGEST"]
