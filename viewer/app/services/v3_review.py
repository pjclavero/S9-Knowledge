"""Local, append-only review queue for Knowledge V3 proposals.

The service deliberately has no dependency on Neo4j, the V3 engine or the
writer.  Human decisions are durable input for a later, separately gated
process; they are never mutation plans.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VALID_HUMAN_DECISIONS = frozenset({"APPROVE", "REJECT", "CORRECT"})
VALID_ENGINE_DECISIONS = frozenset({"ACCEPT", "REVIEW", "ABSTAIN", "REJECT_INVALID"})

REASON_LABELS = {
    "AMBIGUOUS_PREDICATE": "Hay más de un predicado plausible.",
    "AMBIGUOUS_DIRECTION": "La dirección de la relación no es concluyente.",
    "LOW_CONFIDENCE": "La confianza no alcanza el umbral de aprobación.",
    "MISSING_EVIDENCE": "La evidencia disponible no basta para aprobar.",
    "NEGATION_REQUIRES_REVIEW": "La negación necesita revisión humana.",
    "ONTOLOGY_MISMATCH": "La relación no encaja con la ontología aplicable.",
    "REVIEW_REQUIRED": "La propuesta requiere confirmación humana.",
}

_LOCKS: dict[Path, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class ReviewError(ValueError):
    """Invalid proposal, decision or append-only history."""


class HistoryIntegrityError(ReviewError):
    """The JSONL decision history is malformed or its hash chain is broken."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _lock_for(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(resolved, threading.RLock())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _non_empty(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ReviewError(f"falta {field}")
    return text


def _proposal_id(proposal: dict[str, Any]) -> str:
    return _non_empty(
        proposal.get("proposal_id") or proposal.get("claim_id") or proposal.get("decision_id"),
        "proposal_id",
    )


def _evidence_parts(proposal: dict[str, Any]) -> tuple[str, str, str]:
    episode_text = str(proposal.get("episode_text") or "")
    evidence = proposal.get("evidence") or {}
    try:
        start = int(evidence["start"])
        end = int(evidence["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewError("evidence.start y evidence.end son obligatorios") from exc
    if start < 0 or end < start or end > len(episode_text):
        raise ReviewError("offsets de evidencia fuera del episodio")
    literal = episode_text[start:end]
    declared = evidence.get("literal_text")
    if declared is not None and declared != literal:
        raise ReviewError("evidence.literal_text no coincide con los offsets")
    return episode_text[:start], literal, episode_text[end:]


def reason_label(code: str) -> str:
    """Return a human explanation, preserving unknown codes verbatim."""
    return REASON_LABELS.get(code, code)


def default_proposals_dir() -> Path:
    configured = os.environ.get("S9K_V3_REVIEW_PROPOSALS_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "output" / "reviews-v3" / "proposals"


def default_decisions_path() -> Path:
    configured = os.environ.get("S9K_V3_REVIEW_DECISIONS_PATH")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "output" / "reviews-v3" / "decisions.jsonl"


def _candidate_views(
    explicit: Any,
    reconciled: Any,
    value_key: str,
) -> list[dict[str, Any]]:
    source = explicit if isinstance(explicit, list) and explicit else reconciled
    if not isinstance(source, list):
        return []
    views: list[dict[str, Any]] = []
    for candidate in source:
        if not isinstance(candidate, dict):
            continue
        origin = candidate.get("origin") if isinstance(candidate.get("origin"), dict) else {}
        value = candidate.get("value") or candidate.get(value_key)
        if not value:
            continue
        views.append({
            "value": str(value),
            "confidence": candidate.get("confidence"),
            "extractor": (
                candidate.get("extractor")
                or candidate.get("provider")
                or origin.get("name")
                or origin.get("provider")
            ),
            "proposal_id": candidate.get("proposal_id"),
        })
    return views


def load_proposals(directory: Path) -> list[dict[str, Any]]:
    """Load proposal packages without crossing the selected workspace later."""
    if not directory.exists():
        return []
    proposals: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        documents = raw if isinstance(raw, list) else raw.get("items", [raw])
        if not isinstance(documents, list):
            raise ReviewError(f"paquete inválido: {path}")
        for proposal in documents:
            if not isinstance(proposal, dict):
                raise ReviewError(f"propuesta inválida: {path}")
            identifier = _proposal_id(proposal)
            if identifier in seen:
                raise ReviewError(f"proposal_id duplicado: {identifier}")
            _non_empty(proposal.get("workspace"), "workspace")
            _non_empty(proposal.get("source_id"), "source_id")
            _non_empty(proposal.get("episode_id"), "episode_id")
            _evidence_parts(proposal)
            seen.add(identifier)
            proposals.append(proposal)
    return proposals


def _validate_history(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    previous_hash: str | None = None
    decision_ids: set[str] = set()
    request_ids: set[str] = set()
    for line_number, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise HistoryIntegrityError(f"entrada {line_number} no es un objeto")
        body = {key: value for key, value in record.items() if key != "record_hash"}
        if record.get("previous_hash") != previous_hash:
            raise HistoryIntegrityError(f"cadena rota en entrada {line_number}")
        if record.get("record_hash") != _sha256(body):
            raise HistoryIntegrityError(f"hash inválido en entrada {line_number}")
        decision_id = _non_empty(record.get("decision_id"), "decision_id")
        request_id = _non_empty(record.get("request_id"), "request_id")
        if decision_id in decision_ids or request_id in request_ids:
            raise HistoryIntegrityError(f"identificador duplicado en entrada {line_number}")
        decision_ids.add(decision_id)
        request_ids.add(request_id)
        previous_hash = record["record_hash"]
        validated.append(record)
    return validated


def read_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise HistoryIntegrityError(f"JSON inválido en entrada {line_number}") from exc
    return _validate_history(records)


def _active_decisions(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}
    superseded: set[str] = set()
    for record in records:
        supersedes = record.get("supersedes_decision_id")
        if supersedes:
            superseded.add(supersedes)
        active[record["proposal"]["proposal_id"]] = record
    return {
        proposal_id: record
        for proposal_id, record in active.items()
        if record["decision_id"] not in superseded
        and not record.get("correction", {}).get("undo")
    }


@dataclass(frozen=True)
class QueueView:
    items: list[dict[str, Any]]
    remaining: int
    total: int
    sources: tuple[str, ...]
    decisions: tuple[str, ...]


class ReviewService:
    """Workspace-scoped queue and append-only decision ledger."""

    def __init__(
        self,
        proposals_dir: Path | None = None,
        decisions_path: Path | None = None,
        *,
        graph_driver: Any = None,
    ) -> None:
        self.proposals_dir = proposals_dir or default_proposals_dir()
        self.decisions_path = decisions_path or default_decisions_path()
        # Kept only as a testable boundary: this service must never dereference it.
        self._graph_driver = graph_driver

    def workspaces(self) -> tuple[str, ...]:
        return tuple(sorted({str(item["workspace"]) for item in load_proposals(self.proposals_dir)}))

    def queue(
        self,
        workspace: str,
        *,
        source_id: str | None = None,
        engine_decision: str | None = None,
        include_decided: bool = False,
    ) -> QueueView:
        workspace = _non_empty(workspace, "workspace")
        history = read_history(self.decisions_path)
        active = _active_decisions(history)
        all_workspace = [
            proposal for proposal in load_proposals(self.proposals_dir)
            if proposal["workspace"] == workspace
        ]
        sources = tuple(sorted({str(item["source_id"]) for item in all_workspace}))
        decisions = tuple(sorted({
            str((item.get("engine_decision") or {}).get("decision") or "UNKNOWN")
            for item in all_workspace
        }))
        filtered = [
            proposal for proposal in all_workspace
            if (not source_id or proposal["source_id"] == source_id)
            and (
                not engine_decision
                or (proposal.get("engine_decision") or {}).get("decision") == engine_decision
            )
            and (include_decided or _proposal_id(proposal) not in active)
        ]
        filtered.sort(key=lambda item: (
            str(item.get("source_id", "")),
            str(item.get("episode_id", "")),
            _proposal_id(item),
        ))
        items = [self.present(proposal, active.get(_proposal_id(proposal))) for proposal in filtered]
        remaining = sum(_proposal_id(item) not in active for item in all_workspace)
        return QueueView(
            items=items,
            remaining=remaining,
            total=len(all_workspace),
            sources=sources,
            decisions=decisions,
        )

    def present(
        self,
        proposal: dict[str, Any],
        active_decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        before, literal, after = _evidence_parts(proposal)
        engine = proposal.get("engine_decision") or {}
        metadata = proposal.get("metadata") or {}
        reconciliation = metadata.get("reconciliation") or {}
        alternatives = proposal.get("alternatives") or reconciliation.get("alternatives") or {}
        predicate_alternatives = _candidate_views(
            alternatives.get("predicates", []),
            reconciliation.get("predicate_candidate_origins", []),
            "predicate",
        )
        direction_alternatives = _candidate_views(
            alternatives.get("directions", []),
            reconciliation.get("direction_candidate_origins", []),
            "direction",
        )
        return {
            **proposal,
            "proposal_id": _proposal_id(proposal),
            "evidence_before": before,
            "evidence_literal": literal,
            "evidence_after": after,
            "reason_explanations": [
                {"code": str(code), "label": reason_label(str(code))}
                for code in engine.get("reason_codes", [])
            ],
            "predicate_alternatives": predicate_alternatives,
            "direction_alternatives": direction_alternatives,
            "active_decision": active_decision,
        }

    def record(
        self,
        *,
        proposal_id: str,
        workspace: str,
        reviewer: str,
        human_decision: str,
        request_id: str,
        rationale: str = "",
        correction: dict[str, Any] | None = None,
        supersedes_decision_id: str | None = None,
    ) -> dict[str, Any]:
        if human_decision not in VALID_HUMAN_DECISIONS:
            raise ReviewError(f"human_decision inválida: {human_decision}")
        request_id = _non_empty(request_id, "request_id")
        reviewer = _non_empty(reviewer, "reviewer")
        workspace = _non_empty(workspace, "workspace")

        with _lock_for(self.decisions_path):
            history = read_history(self.decisions_path)
            for existing in history:
                if existing["request_id"] == request_id:
                    if (
                        existing["workspace"] != workspace
                        or existing["proposal"]["proposal_id"] != proposal_id
                        or existing["reviewer"] != reviewer
                        or existing["human_decision"] != human_decision
                    ):
                        raise ReviewError("request_id reutilizado con otra decisión")
                    return existing
            proposal = next(
                (
                    item for item in load_proposals(self.proposals_dir)
                    if _proposal_id(item) == proposal_id and item["workspace"] == workspace
                ),
                None,
            )
            if proposal is None:
                raise ReviewError("propuesta inexistente en el workspace seleccionado")
            if supersedes_decision_id and not any(
                item["decision_id"] == supersedes_decision_id
                and item["workspace"] == workspace
                and item["proposal"]["proposal_id"] == proposal_id
                for item in history
            ):
                raise ReviewError("la decisión supersedida no pertenece a esta propuesta y workspace")

            engine_decision = proposal.get("engine_decision") or {}
            record: dict[str, Any] = {
                "decision_id": f"human:{uuid.uuid4()}",
                "request_id": request_id,
                "timestamp": _now(),
                "reviewer": reviewer,
                "workspace": workspace,
                "source_id": proposal["source_id"],
                "episode_id": proposal["episode_id"],
                "proposal": json.loads(_canonical(proposal)),
                "engine_decision": json.loads(_canonical(engine_decision)),
                "human_decision": human_decision,
                "correction": correction or {},
                "rationale": rationale.strip(),
                "ontology_version": (
                    proposal.get("ontology_version")
                    or (proposal.get("ontology") or {}).get("version")
                ),
                "engine_version": proposal.get("engine_version"),
                "supersedes_decision_id": supersedes_decision_id,
                "previous_hash": history[-1]["record_hash"] if history else None,
            }
            record["record_hash"] = _sha256(record)
            self.decisions_path.parent.mkdir(parents=True, exist_ok=True)
            with self.decisions_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(_canonical(record) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return record

    def undo_last(self, *, workspace: str, reviewer: str, request_id: str) -> dict[str, Any]:
        with _lock_for(self.decisions_path):
            history = read_history(self.decisions_path)
            active = [
                record for record in _active_decisions(history).values()
                if record["workspace"] == workspace
            ]
            if not active:
                raise ReviewError("no hay una decisión activa que deshacer")
            latest = max(active, key=lambda record: (record["timestamp"], record["decision_id"]))
            return self.record(
                proposal_id=latest["proposal"]["proposal_id"],
                workspace=workspace,
                reviewer=reviewer,
                human_decision="CORRECT",
                request_id=request_id,
                rationale="Deshacer última decisión",
                correction={"undo": True, "restores": "PENDING"},
                supersedes_decision_id=latest["decision_id"],
            )
