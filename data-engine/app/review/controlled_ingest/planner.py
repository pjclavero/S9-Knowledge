"""Constructor de ingest-plan-v1 DETERMINISTA.

Dado un conjunto de candidatos con su estado final, produce un plan reproducible:
operaciones ordenadas por operation_id, idempotency_key unica y derivada del
contenido, relations_enabled=false en v1 (0 relaciones). Crear el plan NO
autoriza aplicarlo: authorization.granted queda en false.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .candidate_builder import SourceContext
from .hashing import hash_block, short_id

# Estados que generan una operacion de creacion en el grafo.
_CREATE_STATUSES = {"APPROVED", "EDITED"}
_DEFER_STATUSES = {"DEFERRED", "PENDING", "REQUIRES_REVIEW", "AUTO_APPROVABLE"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class PlanItem:
    candidate_doc: dict[str, Any]
    final_status: str


def build_plan(
    ctx: SourceContext,
    *,
    review_document_id: str,
    review_hash: dict[str, str],
    items: list[PlanItem],
    relations_enabled: bool = False,
) -> dict[str, Any]:
    """Construye ingest-plan-v1 determinista. En v1 relations_enabled=false."""
    if relations_enabled:
        raise ValueError("relations_enabled=true no soportado en v1 (motor)")

    # Orden estable por candidate_id: el plan no depende del orden de entrada.
    ordered = sorted(items, key=lambda it: it.candidate_doc["candidate_id"])

    operations: list[dict[str, Any]] = []
    deferred_items: list[str] = []
    conflicts: list[dict[str, Any]] = []
    warnings: list[str] = []

    would_create = would_update = would_link_existing = 0

    op_index = 0
    for it in ordered:
        cand = it.candidate_doc
        cid = cand["candidate_id"]
        status = it.final_status
        is_relation = cand.get("candidate_kind") == "RELATION"

        if is_relation:
            # Relaciones deshabilitadas en v1: se difieren, nunca se planifican.
            deferred_items.append(cid)
            warnings.append(f"{cid}: relacion diferida (relations_enabled=false)")
            continue

        if status == "CONFLICT":
            conflicts.append({"candidate_id": cid, "reason": "conflicto abierto sin resolver"})
            continue
        if status == "REJECTED":
            continue
        if status in _DEFER_STATUSES:
            deferred_items.append(cid)
            if status in ("PENDING", "REQUIRES_REVIEW"):
                warnings.append(f"{cid}: pendiente de revision, no planificable")
            continue

        if status == "USE_EXISTING":
            target = None
            matches = cand.get("existing_matches") or []
            if matches:
                target = matches[0]["entity_id"]
            operations.append(_op(ctx, op_index, cid, "LINK_EXISTING",
                                  "WOULD_LINK_EXISTING", cand, target))
            would_link_existing += 1
            op_index += 1
            continue

        if status in _CREATE_STATUSES:
            operations.append(_op(ctx, op_index, cid, "CREATE_ENTITY",
                                  "WOULD_CREATE", cand, None))
            would_create += 1
            op_index += 1
            continue

        # Estado inesperado: se difiere de forma conservadora.
        deferred_items.append(cid)
        warnings.append(f"{cid}: estado {status!r} no planificable, diferido")

    has_blockers = bool(conflicts) or any("pendiente" in w for w in warnings)
    if operations and not has_blockers:
        status = "READY_TO_APPLY"
    elif has_blockers:
        status = "BLOCKED"
    else:
        status = "DRAFT"

    plan_id = short_id("plan", ctx.source_id, ctx.review_generation, review_hash["value"])

    doc: dict[str, Any] = {
        "schema_version": "1.0.0",
        "document_type": "ingest-plan",
        "document_id": f"ingest-plan_{plan_id}",
        "created_at": _now_iso(),
        "workspace": ctx.workspace,
        "source_id": ctx.source_id,
        "source_hash": ctx.source_hash(),
        "review_generation": ctx.review_generation,
        "producer": ctx.producer(),
        "provenance": ctx.provenance(),
        "plan_id": plan_id,
        "plan_version": "1.0.0",
        "review_document_id": review_document_id,
        "review_hash": review_hash,
        "created_by": ctx.producer(),
        "status": status,
        "relations_enabled": False,
        "preconditions": [
            {"precondition_id": "pre_review_hash", "kind": "REVIEW_HASH_MATCHES",
             "expected": review_hash["value"]},
            {"precondition_id": "pre_source_hash", "kind": "SOURCE_HASH_MATCHES",
             "expected": ctx.source_hash_value},
            {"precondition_id": "pre_generation", "kind": "GENERATION_MATCHES",
             "expected": str(ctx.review_generation)},
            {"precondition_id": "pre_no_conflicts", "kind": "NO_OPEN_CONFLICTS",
             "expected": "0"},
            {"precondition_id": "pre_provenance", "kind": "PROVENANCE_PRESENT",
             "expected": "true"},
        ],
        "operations": operations,
        "deferred_items": deferred_items,
        "conflicts": conflicts,
        "warnings": warnings,
        "summary": {
            "would_create": would_create,
            "would_update": would_update,
            "would_link_existing": would_link_existing,
            "deferred": len(deferred_items),
            "conflicts": len(conflicts),
            "relations": 0,
        },
        "authorization": {"required": True, "granted": False},
    }
    return doc


def _op(ctx: SourceContext, index: int, candidate_id: str, op_type: str,
        expected_state: str, cand: dict[str, Any], target: str | None) -> dict[str, Any]:
    idem = short_id("idem", ctx.workspace, ctx.source_id, ctx.review_generation,
                    candidate_id, op_type)
    payload = {
        "canonical_name": cand.get("canonical_name"),
        "entity_type": cand.get("entity_type"),
        "attributes": cand.get("attributes", {}),
    }
    return {
        "operation_id": f"op_{index:04d}",
        "operation_type": op_type,
        "candidate_id": candidate_id,
        "target_entity_id": target,
        "payload": payload,
        "provenance": ctx.provenance(),
        "expected_state": expected_state,
        "idempotency_key": idem,
    }


def plan_hash(plan_doc: dict[str, Any]) -> dict[str, str]:
    """Hash canonico del plan para el gate de APPLY (comparacion exacta)."""
    return hash_block(plan_doc)


__all__ = ["build_plan", "PlanItem", "plan_hash"]
