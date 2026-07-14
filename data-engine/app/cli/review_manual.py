# -*- coding: utf-8 -*-
"""CLI mínima de revisión humana manual (Prioridad 2.1 / preparación de ingesta).

Permite a un operador registrar decisiones sobre los candidatos de la
`review_queue` (approve/reject/edit/use-existing) SIN escribir en Neo4j.

Garantías:
  - Registro **append-only** en `manual_review_log.jsonl` (no sobrescribe).
  - Genera `approved_payload.reviewed.json` con procedencia de revisión humana
    (review_status=approved, reviewed_by=manual-cli:<op>, reviewed_at, review_action).
  - Conserva el `approved_payload.json` automático (no lo pisa).
  - Nunca toca Neo4j ni activa S9K_ALLOW_REAL_INGEST.

Uso:
  python data-engine/app/cli/review_manual.py \\
      --workspace leyenda --source-id <sid> --candidate-id <cid> \\
      --action approve --operator ana --reason "correcta"
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ACTIONS = ("approve", "reject", "edit", "use-existing")
_APPROVING_ACTIONS = {"approve", "edit", "use-existing"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _review_dir(repo_root: Path, workspace: str, source_id: str) -> Path:
    return repo_root / "output" / "reviews" / workspace / source_id


def _load_decisions(repo_root: Path, workspace: str, source_id: str) -> list:
    p = _review_dir(repo_root, workspace, source_id) / "decisions.json"
    if not p.exists():
        raise FileNotFoundError(f"decisions.json no encontrado: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _find_candidate(decisions: list, candidate_id: str) -> dict | None:
    for d in decisions:
        if d.get("candidate_id") == candidate_id:
            return d.get("candidate", {})
    return None


def record_decision(repo_root: Path, workspace: str, source_id: str, candidate_id: str,
                    action: str, operator: str, reason: str = "",
                    new_value: dict | None = None) -> dict:
    """Registra una decisión manual (append-only) y regenera el payload revisado."""
    if action not in _ACTIONS:
        raise ValueError(f"acción inválida '{action}'. Válidas: {_ACTIONS}")
    if not operator or not operator.strip():
        raise ValueError("operador obligatorio")

    decisions = _load_decisions(repo_root, workspace, source_id)
    cand = _find_candidate(decisions, candidate_id)
    if cand is None:
        raise ValueError(f"candidate_id '{candidate_id}' no está en decisions.json")

    rdir = _review_dir(repo_root, workspace, source_id)
    rdir.mkdir(parents=True, exist_ok=True)

    old_value = {k: cand.get(k) for k in ("name", "entity_type", "from_entity",
                                          "to_entity", "relation_type")}
    entry = {
        "source_id": source_id,
        "candidate_id": candidate_id,
        "action": action,
        "operator": operator,
        "reviewed_by": f"manual-cli:{operator}",
        "reviewed_at": _now(),
        "old_value": old_value,
        "new_value": new_value or {},
        "reason": reason,
    }
    # append-only
    with (rdir / "manual_review_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    payload = build_reviewed_payload(repo_root, workspace, source_id)
    return {"entry": entry, "approved_in_payload": len(payload["approved"])}


def _read_log(rdir: Path) -> list:
    p = rdir / "manual_review_log.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def build_reviewed_payload(repo_root: Path, workspace: str, source_id: str) -> dict:
    """Reconstruye approved_payload.reviewed.json a partir del log append-only.
    Gana la última decisión por candidate_id. Solo entran acciones aprobatorias."""
    decisions = _load_decisions(repo_root, workspace, source_id)
    rdir = _review_dir(repo_root, workspace, source_id)
    log_entries = _read_log(rdir)

    latest: dict[str, dict] = {}
    for e in log_entries:
        latest[e["candidate_id"]] = e  # el orden append preserva la última

    approved = []
    for cid, e in latest.items():
        if e["action"] not in _APPROVING_ACTIONS:
            continue
        cand = _find_candidate(decisions, cid) or {}
        item = dict(cand)
        # aplica edición si la hubo
        for k, v in (e.get("new_value") or {}).items():
            if v is not None:
                item[k] = v
        item["review_status"] = "approved"
        item["reviewed_by"] = e["reviewed_by"]
        item["reviewed_at"] = e["reviewed_at"]
        item["review_action"] = e["action"]
        item["review_operator"] = e["operator"]
        approved.append(item)

    payload = {
        "metadata": {
            "workspace": workspace, "source_id": source_id, "schema_version": "1.0",
            "origin": "local", "generated_at": _now(),
            "total_approved": len(approved), "review_policy": "full_human_review",
        },
        "approved": approved,
    }
    (rdir / "approved_payload.reviewed.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main():
    ap = argparse.ArgumentParser(description="Revisión humana manual (sin escritura en Neo4j)")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--source-id", required=True, dest="source_id")
    ap.add_argument("--candidate-id", required=True, dest="candidate_id")
    ap.add_argument("--action", required=True, choices=_ACTIONS)
    ap.add_argument("--operator", required=True)
    ap.add_argument("--reason", default="")
    ap.add_argument("--set-name", dest="set_name", default=None)
    ap.add_argument("--set-type", dest="set_type", default=None)
    ap.add_argument("--repo-root", dest="repo_root", default=None)
    args = ap.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[3]
    new_value = {}
    if args.set_name:
        new_value["name"] = args.set_name
    if args.set_type:
        new_value["entity_type"] = args.set_type

    result = record_decision(repo_root, args.workspace, args.source_id, args.candidate_id,
                             args.action, args.operator, args.reason, new_value or None)
    print(f"OK: {args.action} por manual-cli:{args.operator} sobre {args.candidate_id}")
    print(f"  approved_payload.reviewed.json: {result['approved_in_payload']} candidatos")


if __name__ == "__main__":
    main()
