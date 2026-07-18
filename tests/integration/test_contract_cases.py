"""test_contract_cases.py — casos de contrato del flujo review/ingest v1.

Construye documentos a partir de los ejemplos válidos y comprueba, vía el
`validator.py` compartido, las invariantes de negocio exigidas por RC6:

  - Control optimista / stale hash (expected_candidate_hash obligatorio y
    coherente; generación obsoleta rechazada).
  - Supersesión (estados SUPERSEDED admitidos donde el catálogo los define).
  - Idempotencia (operation_id / idempotency_key únicos por plan).
  - EXTERNAL_AI_SHADOW no puede auto-aprobar (solo DEFER).
  - Autorización imposible sin operador (operator_id/authorized_at/hash).
  - APPLY PARTIAL prohibido sin rollback transaccional demostrado.

Todo es de solo lectura sobre el contrato: no se modifica ningún esquema.
"""
from __future__ import annotations

import copy

import pytest

from support import contracts

pytestmark = [pytest.mark.integration, pytest.mark.contract]

V = contracts.validator


# --------------------------------------------------------------------------- #
# Control optimista / stale hash
# --------------------------------------------------------------------------- #
def test_decision_requires_expected_candidate_hash() -> None:
    doc = contracts.load_example("decision_approve")
    assert V.is_valid(doc)
    doc.pop("expected_candidate_hash")
    assert not V.is_valid(doc), "una decisión sin expected_candidate_hash debe rechazarse"


def test_decision_expected_hash_must_declare_algorithm() -> None:
    doc = contracts.load_example("decision_approve")
    doc["expected_candidate_hash"] = {"value": "a" * 64}  # sin algorithm
    assert not V.is_valid(doc)


def test_stale_generation_rejected() -> None:
    """El ejemplo inválido de generación obsoleta debe seguir siendo rechazado."""
    doc = contracts.load_json(contracts.INVALID_DIR / "decision_old_generation.json")
    with pytest.raises(contracts.ContractError):
        V.validate_document(doc)


# --------------------------------------------------------------------------- #
# Supersesión
# --------------------------------------------------------------------------- #
def test_plan_superseded_status_is_valid() -> None:
    doc = contracts.load_example("ingest_plan_ready")
    doc["status"] = "SUPERSEDED"
    assert V.is_valid(doc), "SUPERSEDED es un estado válido del plan"


def test_summary_superseded_status_is_valid() -> None:
    doc = contracts.load_example("source_summary_conflicts")
    # Un resumen supersedido: sin bloqueos pendientes y no listo para planificar.
    doc.update({
        "status": "SUPERSEDED",
        "pending": 0,
        "conflicts": 0,
        "deferred": 0,
        "approved": doc["candidates_total"],
        "ready_to_plan": False,
        "blocking_reasons": [],
    })
    assert V.is_valid(doc)


def test_audit_generation_superseded_event_is_valid() -> None:
    doc = contracts.load_json(contracts.VALID_DIR / "audit_event.json")
    doc["event_type"] = "GENERATION_SUPERSEDED"
    assert V.is_valid(doc)


def test_unknown_plan_status_rejected() -> None:
    doc = contracts.load_example("ingest_plan_ready")
    doc["status"] = "TOTALLY_NEW_STATE"
    assert not V.is_valid(doc)


# --------------------------------------------------------------------------- #
# Idempotencia / determinismo
# --------------------------------------------------------------------------- #
def _plan_with_two_ops():
    doc = contracts.load_example("ingest_plan_ready")
    op1 = doc["operations"][0]
    op2 = copy.deepcopy(op1)
    op2["operation_id"] = "op_002"
    op2["idempotency_key"] = "idem_002"
    op2["candidate_id"] = "cand_002"
    doc["operations"] = [op1, op2]
    return doc


def test_two_distinct_operations_ok() -> None:
    assert V.is_valid(_plan_with_two_ops())


def test_duplicate_operation_id_rejected() -> None:
    doc = _plan_with_two_ops()
    doc["operations"][1]["operation_id"] = doc["operations"][0]["operation_id"]
    assert not V.is_valid(doc)


def test_duplicate_idempotency_key_rejected() -> None:
    doc = _plan_with_two_ops()
    doc["operations"][1]["idempotency_key"] = doc["operations"][0]["idempotency_key"]
    assert not V.is_valid(doc)


def test_relation_op_requires_relations_enabled() -> None:
    doc = contracts.load_example("ingest_plan_ready")
    doc["relations_enabled"] = False
    doc["operations"][0]["operation_type"] = "CREATE_RELATION"
    assert not V.is_valid(doc)


# --------------------------------------------------------------------------- #
# EXTERNAL_AI_SHADOW no vinculante
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("action", ["APPROVE", "EDIT", "USE_EXISTING", "REJECT", "RESOLVE_CONFLICT"])
def test_shadow_ai_cannot_take_binding_action(action: str) -> None:
    doc = contracts.load_example("decision_defer_shadow")
    doc["action"] = action
    assert not V.is_valid(doc), f"EXTERNAL_AI_SHADOW no puede emitir {action}"


def test_shadow_ai_defer_is_allowed() -> None:
    doc = contracts.load_example("decision_defer_shadow")
    assert doc["reviewer_type"] == "EXTERNAL_AI_SHADOW"
    assert doc["action"] == "DEFER"
    assert V.is_valid(doc)


def test_human_can_approve() -> None:
    doc = contracts.load_example("decision_approve")
    assert doc["reviewer_type"] == "HUMAN"
    assert V.is_valid(doc)


# --------------------------------------------------------------------------- #
# Autorización separada del plan
# --------------------------------------------------------------------------- #
def test_authorization_granted_requires_operator_fields() -> None:
    doc = contracts.load_example("ingest_plan_ready")
    doc["authorization"] = {"required": True, "granted": True}  # sin operator_id/…
    assert not V.is_valid(doc)


def test_authorization_granted_with_full_operator_ok() -> None:
    doc = contracts.load_example("ingest_plan_ready")
    doc["authorization"] = {
        "required": True,
        "granted": True,
        "operator_id": "operador_demo",
        "authorized_at": "2026-01-01T00:20:00Z",
        "authorization_hash": {"algorithm": "sha256", "value": "c" * 64},
    }
    assert V.is_valid(doc)


def test_plan_creation_does_not_grant_authorization() -> None:
    """El plan READY_TO_APPLY del ejemplo llega con granted=false por diseño."""
    doc = contracts.load_example("ingest_plan_ready")
    assert doc["status"] == "READY_TO_APPLY"
    assert doc["authorization"]["granted"] is False


# --------------------------------------------------------------------------- #
# APPLY PARTIAL sin rollback
# --------------------------------------------------------------------------- #
def test_apply_partial_without_rollback_rejected() -> None:
    doc = contracts.load_example("dry_run_success")
    doc["mode"] = "APPLY"
    doc["status"] = "PARTIAL"
    doc.pop("transactional_rollback_demonstrated", None)
    assert not V.is_valid(doc)


def test_apply_partial_with_rollback_demonstrated_ok() -> None:
    doc = contracts.load_example("dry_run_success")
    doc["mode"] = "APPLY"
    doc["status"] = "PARTIAL"
    doc["transactional_rollback_demonstrated"] = True
    doc["summary"]["created"] = 1
    doc["summary"]["rolled_back"] = 1
    assert V.is_valid(doc)


def test_dry_run_cannot_create() -> None:
    doc = contracts.load_example("dry_run_success")
    doc["summary"]["created"] = 1
    assert not V.is_valid(doc)


# --------------------------------------------------------------------------- #
# Forward-compat / secretos
# --------------------------------------------------------------------------- #
def test_unknown_major_version_rejected() -> None:
    doc = contracts.load_example("candidate_new")
    doc["schema_version"] = "2.0.0"
    assert not V.is_valid(doc)


def test_secret_in_metadata_rejected() -> None:
    doc = contracts.load_json(contracts.VALID_DIR / "audit_event.json")
    doc["metadata"] = {"authorization": "Bearer x"}
    assert not V.is_valid(doc)
