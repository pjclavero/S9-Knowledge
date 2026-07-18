"""Ejecutor de ingest-plan en DRY_RUN (0 escrituras) -> ingest-plan-result-v1.

El DRY_RUN NUNCA escribe: no recibe ni invoca ningun escritor de Neo4j. Los
conteos neo4j_before/neo4j_after son identicos por construccion, evidenciando
cero mutaciones. APPLY real queda fuera del alcance de v1 (ver policy.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .candidate_builder import SourceContext

# expected_state del plan -> resultado de operacion en DRY_RUN.
_EXPECTED_TO_RESULT = {
    "WOULD_CREATE": "WOULD_CREATE",
    "WOULD_UPDATE": "WOULD_CREATE",
    "WOULD_LINK_EXISTING": "SKIPPED",
    "DEFERRED": "SKIPPED",
    "NO_OP": "SKIPPED",
    "CONFLICT_EXISTING": "CONFLICT",
    "AMBIGUOUS": "CONFLICT",
    "BLOCKED": "SKIPPED",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dry_run(
    ctx: SourceContext,
    plan_doc: dict[str, Any],
    *,
    graph_baseline: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Ejecuta el plan en DRY_RUN. Devuelve ingest-plan-result-v1 (0 escrituras)."""
    baseline = dict(graph_baseline or {"nodes": 0, "relationships": 0})
    started = _now_iso()

    op_results: list[dict[str, Any]] = []
    counts = {"would_create": 0, "created": 0, "skipped": 0,
              "conflict": 0, "failed": 0, "rolled_back": 0}

    for op in plan_doc["operations"]:
        result = _EXPECTED_TO_RESULT.get(op["expected_state"], "SKIPPED")
        op_results.append({
            "operation_id": op["operation_id"],
            "result": result,
            "target_entity_id": op.get("target_entity_id"),
            "detail": "simulacion DRY_RUN, sin escritura",
        })
        if result == "WOULD_CREATE":
            counts["would_create"] += 1
        elif result == "SKIPPED":
            counts["skipped"] += 1
        elif result == "CONFLICT":
            counts["conflict"] += 1

    doc: dict[str, Any] = {
        "schema_version": "1.0.0",
        "document_type": "ingest-plan-result",
        "document_id": f"ingest-plan-result_{plan_doc['plan_id']}_dryrun",
        "created_at": _now_iso(),
        "workspace": ctx.workspace,
        "source_id": ctx.source_id,
        "source_hash": ctx.source_hash(),
        "review_generation": ctx.review_generation,
        "producer": ctx.producer(),
        "provenance": ctx.provenance(),
        "execution_id": f"exec_{plan_doc['plan_id']}_dryrun",
        "plan_id": plan_doc["plan_id"],
        "mode": "DRY_RUN",
        "started_at": started,
        "finished_at": _now_iso(),
        "status": "SUCCEEDED",
        "operations": op_results,
        "summary": counts,
        # 0 escrituras: el estado del grafo no cambia.
        "neo4j_before": dict(baseline),
        "neo4j_after": dict(baseline),
        "errors": [],
        "warnings": [],
    }
    return doc


def blocked_result(
    ctx: SourceContext,
    plan_doc: dict[str, Any],
    reasons: list[str],
) -> dict[str, Any]:
    """Resultado BLOCKED de un APPLY denegado por el gate (0 escrituras)."""
    baseline = {"nodes": 0, "relationships": 0}
    now = _now_iso()
    return {
        "schema_version": "1.0.0",
        "document_type": "ingest-plan-result",
        "document_id": f"ingest-plan-result_{plan_doc['plan_id']}_blocked",
        "created_at": now,
        "workspace": ctx.workspace,
        "source_id": ctx.source_id,
        "source_hash": ctx.source_hash(),
        "review_generation": ctx.review_generation,
        "producer": ctx.producer(),
        "provenance": ctx.provenance(),
        "execution_id": f"exec_{plan_doc['plan_id']}_blocked",
        "plan_id": plan_doc["plan_id"],
        "mode": "APPLY",
        "started_at": now,
        "finished_at": now,
        "status": "BLOCKED",
        "operations": [],
        "summary": {"would_create": 0, "created": 0, "skipped": 0,
                    "conflict": 0, "failed": 0, "rolled_back": 0},
        "neo4j_before": dict(baseline),
        "neo4j_after": dict(baseline),
        "errors": [],
        "warnings": ["APPLY BLOQUEADO por politica de ingesta controlada: " + "; ".join(reasons)],
    }


__all__ = ["dry_run", "blocked_result"]
