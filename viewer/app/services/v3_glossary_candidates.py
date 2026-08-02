"""Human-originated, workspace-scoped glossary candidates (never applied)."""
from __future__ import annotations

import hashlib
import json
import os
import unicodedata
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TYPES = frozenset({
    "CANONICAL_TERM_CANDIDATE", "ALIAS_CANDIDATE", "SPOKEN_FORM_CANDIDATE",
    "ENTITY_TYPE_CANDIDATE", "KNOWN_MISRECOGNITION_CANDIDATE",
})
_LOCKS: dict[Path, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock(path: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(path.resolve(), threading.RLock())


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _norm(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class GlossaryCandidateStore:
    """Materialized JSONL set plus append-only audit; no lexicon mutation API."""

    def __init__(self, root: Path):
        self.root = root

    def _paths(self, workspace: str) -> tuple[Path, Path]:
        safe = hashlib.sha256(workspace.encode()).hexdigest()[:16]
        directory = self.root / safe
        return directory / "candidates.jsonl", directory / "audit.jsonl"

    def list(self, workspace: str) -> list[dict[str, Any]]:
        candidates, _ = self._paths(workspace)
        if not candidates.exists():
            return []
        latest = {}
        for line in candidates.read_text(encoding="utf-8").splitlines():
            if line:
                item = json.loads(line)
                latest[item["candidate_id"]] = item
        return sorted(latest.values(), key=lambda item: item["candidate_id"])

    def propose(self, *, workspace: str, candidate_type: str, canonical_value: str,
                candidate_value: str, entity_type: str | None, resolved_entity_id: str | None,
                source_id: str, episode_id: str, evidence: dict[str, Any],
                decision_id: str, proposal_id: str, confidence: float | None = None,
                reason_codes: list[str] | None = None, provenance: dict[str, Any] | None = None
                ) -> dict[str, Any]:
        if candidate_type not in TYPES:
            raise ValueError("candidate_type inválido")
        semantic_key = [workspace, candidate_type, _norm(canonical_value),
                        _norm(candidate_value), resolved_entity_id]
        candidate_id = f"glossary:{_hash(semantic_key)}"
        candidates_path, audit_path = self._paths(workspace)
        with _lock(candidates_path):
            current = {item["candidate_id"]: item for item in self.list(workspace)}
            existing = current.get(candidate_id)
            if existing:
                item = existing
                item["occurrence_count"] += 1
                item["source_ids"] = sorted(set(item["source_ids"]) | {source_id})
                item["episode_ids"] = sorted(set(item["episode_ids"]) | {episode_id})
                item["evidence"] = sorted(item["evidence"] + [evidence], key=_canonical)
                item["source_count"] = len(item["source_ids"])
                item["origin"]["human_decision_ids"] = sorted(
                    set(item["origin"]["human_decision_ids"]) | {decision_id})
                item["origin"]["proposal_ids"] = sorted(
                    set(item["origin"]["proposal_ids"]) | {proposal_id})
            else:
                origin = provenance or {}
                item = {
                "candidate_id": candidate_id, "candidate_type": candidate_type,
                "status": "PROPOSED", "workspace": workspace,
                "canonical_value": canonical_value, "candidate_value": candidate_value,
                "entity_type": entity_type, "resolved_entity_id": resolved_entity_id,
                "source_ids": [source_id], "episode_ids": [episode_id],
                "evidence": [evidence], "occurrence_count": 1, "source_count": 1,
                "origin": {"human_decision_ids": [decision_id], "proposal_ids": [proposal_id],
                           "extractors": origin.get("extractors", []),
                           "providers": origin.get("providers", [])},
                "confidence": confidence, "reason_codes": reason_codes or [],
                "created_at": _now(),
                }
            hash_body = {
                k: v for k, v in item.items() if k not in {"created_at", "candidate_hash"}
            }
            item["candidate_hash"] = _hash(hash_body)
            candidates_path.parent.mkdir(parents=True, exist_ok=True)
            # Full canonical snapshots are appended. Older versions remain
            # immutable; list() folds by deterministic candidate_id on restart.
            with candidates_path.open("a", encoding="utf-8") as handle:
                handle.write(_canonical(item) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            audit = {"timestamp": _now(), "event": "CANDIDATE_PROPOSED",
                     "candidate_id": candidate_id, "candidate_hash": item["candidate_hash"],
                     "decision_id": decision_id}
            with audit_path.open("a", encoding="utf-8") as handle:
                handle.write(_canonical(audit) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return item
