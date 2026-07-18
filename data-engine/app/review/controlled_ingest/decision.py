"""Consumidor de review-decision-v1 con control optimista.

Aplica la accion de una decision al estado de un candidato, pero SOLO si el
``expected_candidate_hash`` de la decision coincide con el hash actual del
candidato almacenado. Si no coincide, la decision esta obsoleta (STALE) y se
reporta un CONFLICT: el motor no sobrescribe una generacion que ha cambiado.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .candidate_builder import candidate_hash

# Mapea la accion de revision al estado final del candidato (contrato v1).
_ACTION_TO_STATUS = {
    "APPROVE": "APPROVED",
    "EDIT": "EDITED",
    "USE_EXISTING": "USE_EXISTING",
    "DEFER": "DEFERRED",
    "REJECT": "REJECTED",
    "RESOLVE_CONFLICT": "APPROVED",
}

OUTCOME_APPLIED = "APPLIED"
OUTCOME_CONFLICT = "CONFLICT"  # hash obsoleto -> STALE


@dataclass
class DecisionOutcome:
    outcome: str  # APPLIED | CONFLICT
    candidate_id: str
    new_status: str | None
    reason: str


def apply_decision(current_candidate_doc: dict[str, Any], decision_doc: dict[str, Any]) -> DecisionOutcome:
    """Aplica ``decision_doc`` sobre ``current_candidate_doc`` con control optimista.

    Devuelve APPLIED con el nuevo estado, o CONFLICT (STALE) si el hash esperado
    no coincide con el estado actual del candidato.
    """
    cand_id = current_candidate_doc["candidate_id"]
    dec_cand_id = decision_doc["candidate_id"]
    if dec_cand_id != cand_id:
        return DecisionOutcome(OUTCOME_CONFLICT, cand_id, None,
                               f"decision apunta a candidate_id {dec_cand_id!r} != {cand_id!r}")

    expected = decision_doc["expected_candidate_hash"]
    actual = candidate_hash(current_candidate_doc)
    if expected != actual:
        return DecisionOutcome(
            OUTCOME_CONFLICT, cand_id, None,
            "expected_candidate_hash no coincide con el candidato actual (STALE)",
        )

    action = decision_doc["action"]
    new_status = _ACTION_TO_STATUS[action]
    return DecisionOutcome(OUTCOME_APPLIED, cand_id, new_status, f"accion {action} aplicada")


__all__ = ["apply_decision", "DecisionOutcome", "OUTCOME_APPLIED", "OUTCOME_CONFLICT"]
