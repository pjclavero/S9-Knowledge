"""Generador de outputs del pipeline de revisión.

Produce:
  approved_payload.json — candidatos auto_approve
  review_queue.json     — candidatos needs_review
  rejected.json         — candidatos auto_reject
  review.md             — SOLO lo dudoso + resumen de contadores
"""
from __future__ import annotations
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review.models import Decision

log = logging.getLogger(__name__)


def _build_neo4j_payload(d: Decision) -> dict:
    """Construye el payload listo para ingest en Neo4j."""
    c = d.candidate or {}
    rr = d.resolution or {}
    vr = d.validation or {}
    return {
        "candidate_id": c.get("candidate_id", d.candidate_id),
        "kind": c.get("kind", "entity"),
        "name": c.get("name"),
        "entity_type": c.get("entity_type"),
        "from_entity": c.get("from_entity"),
        "to_entity": c.get("to_entity"),
        "relation_type": c.get("relation_type"),
        "event_description": c.get("event_description"),
        "confidence": c.get("confidence", 0.0),
        "evidence": c.get("evidence", ""),
        # Provenance
        "source_id": c.get("source_id", ""),
        "source_kind": c.get("source_kind", "audio"),
        "source_document": c.get("source_id", ""),
        "source_timestamp_start": c.get("timestamp_start", ""),
        "source_timestamp_end": c.get("timestamp_end", ""),
        "workspace": c.get("workspace", ""),
        # Metadatos de review
        "review_status": "auto_approved",
        "knowledge_layer": "transcript",
        "visibility": "player",
        # Resolución
        "resolver_action": rr.get("action", ""),
        "matched_canonical": rr.get("matched_canonical"),
    }


def write_outputs(
    decisions: list[Decision],
    out_dir: Path,
    workspace: str,
    source_id: str,
) -> dict[str, int]:
    """Escribe todos los outputs y retorna contadores."""
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    approved: list[dict] = []
    review_queue: list[dict] = []
    rejected: list[dict] = []

    for d in decisions:
        if d.decision == "auto_approve":
            approved.append(_build_neo4j_payload(d))
        elif d.decision == "needs_review":
            review_queue.append(d.to_dict())
        else:
            rejected.append(d.to_dict())

    # approved_payload.json
    payload = {
        "metadata": {
            "workspace": workspace,
            "source_id": source_id,
            "generated_at": now,
            "total_approved": len(approved),
        },
        "approved": approved,
    }
    (out_dir / "approved_payload.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # review_queue.json
    (out_dir / "review_queue.json").write_text(
        json.dumps(review_queue, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # rejected.json
    (out_dir / "rejected.json").write_text(
        json.dumps(rejected, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # review.md — SOLO pendientes
    _write_review_md(out_dir, workspace, source_id, now, approved, review_queue, rejected)

    counts = {
        "auto_approve": len(approved),
        "needs_review": len(review_queue),
        "auto_reject": len(rejected),
        "total": len(decisions),
    }
    log.info(
        "Writer: auto_approve=%d, needs_review=%d, auto_reject=%d",
        len(approved), len(review_queue), len(rejected),
    )
    return counts


def _write_review_md(
    out_dir: Path,
    workspace: str,
    source_id: str,
    generated_at: str,
    approved: list[dict],
    review_queue: list[dict],
    rejected: list[dict],
):
    lines = [
        f"# Revisión — {workspace} / {source_id}",
        f"",
        f"Generado: {generated_at}",
        f"",
        f"## Resumen",
        f"",
        f"| Estado | Cantidad |",
        f"|--------|----------|",
        f"| Auto-aprobados | {len(approved)} |",
        f"| Pendientes de revisión | {len(review_queue)} |",
        f"| Rechazados automáticamente | {len(rejected)} |",
        f"| **Total candidatos** | **{len(approved)+len(review_queue)+len(rejected)}** |",
        f"",
    ]

    if review_queue:
        lines += [
            "## Pendientes de revisión humana",
            "",
            "> Solo se muestran aquí los candidatos dudosos. Los auto-aprobados y rechazados no requieren atención.",
            "",
        ]
        for i, d in enumerate(review_queue, 1):
            c = d.get("candidate") or {}
            rr = d.get("resolution") or {}
            vr = d.get("validation") or {}
            kind = c.get("kind", "?")
            if kind == "entity":
                desc = f"**{c.get('name', '?')}** ({c.get('entity_type', '?')})"
            elif kind == "relation":
                desc = f"{c.get('from_entity', '?')} → `{c.get('relation_type', '?')}` → {c.get('to_entity', '?')}"
            else:
                desc = c.get("event_description", "?")[:80]

            lines += [
                f"### {i}. {desc}",
                f"",
                f"- **Razón**: {d.get('reason', '')}",
                f"- **Confidence**: {c.get('confidence', 0):.2f}",
                f"- **Resolver**: {rr.get('action', '?')} — {rr.get('reason', '')}",
                f"- **Validación**: {vr.get('valid', '?')} — {'; '.join(vr.get('issues', []) + vr.get('warnings', []))}",
                f"- **Evidence**: {str(c.get('evidence', ''))[:150]}",
                f"- **Segmento**: {c.get('timestamp_start', '?')} – {c.get('timestamp_end', '?')}",
                f"",
            ]
    else:
        lines += ["## Pendientes de revisión humana", "", "Ninguno. Todo fue auto-aprobado o auto-rechazado.", ""]

    (out_dir / "review.md").write_text("\n".join(lines), encoding="utf-8")


def run(workspace: str, source_id: str, repo_root: Path) -> dict[str, int]:
    """Entry point: lee decisions.json y escribe outputs."""
    in_path = repo_root / "output" / "reviews" / workspace / source_id / "decisions.json"
    if not in_path.exists():
        raise FileNotFoundError(f"decisions.json no encontrado: {in_path}")

    with in_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    decisions = [Decision.from_dict(d) for d in raw]

    out_dir = repo_root / "output" / "reviews" / workspace / source_id
    return write_outputs(decisions, out_dir, workspace, source_id)
