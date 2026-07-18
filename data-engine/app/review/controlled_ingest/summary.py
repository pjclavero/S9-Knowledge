"""Constructor de review-source-summary-v1 con conteos coherentes.

Los conteos por estado DEBEN sumar candidates_total (lo revalida el validador de
contratos). ready_to_plan solo puede ser true si no hay conflictos ni pendientes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from .candidate_builder import SourceContext

# Estado de candidato (contrato) -> bucket del resumen.
_STATUS_TO_BUCKET = {
    "PENDING": "pending",
    "REQUIRES_REVIEW": "pending",
    "AUTO_APPROVABLE": "auto_approvable",
    "APPROVED": "approved",
    "EDITED": "edited",
    "USE_EXISTING": "use_existing",
    "DEFERRED": "deferred",
    "CONFLICT": "conflicts",
    "REJECTED": "rejected",
}

_BUCKETS = ["pending", "auto_approvable", "approved", "edited", "use_existing",
            "deferred", "conflicts", "rejected"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_summary(
    ctx: SourceContext,
    *,
    source_kind: str,
    source_document: str,
    segments_total: int,
    segments_reviewed: int,
    statuses: Iterable[str],
) -> dict[str, Any]:
    """Construye review-source-summary-v1 a partir de los estados finales."""
    counts = {b: 0 for b in _BUCKETS}
    total = 0
    for st in statuses:
        bucket = _STATUS_TO_BUCKET[st]
        counts[bucket] += 1
        total += 1

    blocking: list[str] = []
    if counts["conflicts"] > 0:
        blocking.append("OPEN_CONFLICTS")
    if counts["pending"] > 0:
        blocking.append("PENDING_REVIEW")
    ready_to_plan = counts["conflicts"] == 0 and counts["pending"] == 0

    if not ready_to_plan:
        status = "BLOCKED" if counts["conflicts"] > 0 else "IN_REVIEW"
    else:
        status = "READY"

    doc: dict[str, Any] = {
        "schema_version": "1.0.0",
        "document_type": "review-source-summary",
        "document_id": f"review-source-summary_{ctx.source_id}_g{ctx.review_generation}",
        "created_at": _now_iso(),
        "workspace": ctx.workspace,
        "source_id": ctx.source_id,
        "source_hash": ctx.source_hash(),
        "review_generation": ctx.review_generation,
        "producer": ctx.producer(),
        "provenance": ctx.provenance(),
        "source_kind": source_kind,
        "source_document": source_document,
        "status": status,
        "segments_total": segments_total,
        "segments_reviewed": segments_reviewed,
        "candidates_total": total,
        "pending": counts["pending"],
        "auto_approvable": counts["auto_approvable"],
        "approved": counts["approved"],
        "edited": counts["edited"],
        "use_existing": counts["use_existing"],
        "deferred": counts["deferred"],
        "conflicts": counts["conflicts"],
        "rejected": counts["rejected"],
        "ready_to_plan": ready_to_plan,
        "blocking_reasons": blocking,
        "updated_at": _now_iso(),
    }
    return doc


__all__ = ["build_summary"]
