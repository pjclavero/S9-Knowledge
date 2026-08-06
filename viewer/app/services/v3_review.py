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

from app.authz.scope import UNRESTRICTED, VisibilityScope
from app.services.v3_glossary_candidates import GlossaryCandidateStore
from app.services.v3_review_store import SQLiteReviewStore

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


class StaleReviewError(ReviewError):
    """The proposal changed after it was rendered to the reviewer."""

    def __init__(self, current: dict[str, Any]):
        super().__init__("STALE_REVIEW: la propuesta cambió; revisa su versión actual")
        self.current = current


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def proposal_hash(proposal: dict[str, Any]) -> str:
    """Hash of canonical proposal content, excluding its self-referential hash."""
    loader_metadata = {
        "proposal_hash",
        "package_origins",
        "available_version_hashes",
        "legacy_proposal_hash",
    }
    return _sha256({key: value for key, value in proposal.items() if key not in loader_metadata})


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


def default_audit_path() -> Path:
    return default_decisions_path().with_name("audit.jsonl")


def default_database_path() -> Path:
    configured = os.environ.get("S9K_V3_REVIEW_DATABASE_PATH")
    if configured:
        return Path(configured)
    return default_decisions_path().with_name("review.sqlite3")


def default_glossary_root() -> Path:
    configured = os.environ.get("S9K_V3_GLOSSARY_CANDIDATES_DIR")
    if configured:
        return Path(configured)
    return default_decisions_path().parent / "glossary-candidates"


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
    """Load and deterministically fold immutable proposal packages.

    Identical versions are deduplicated while retaining every package origin.
    Different hashes for one logical id remain versions; the deterministic
    package order selects one active version without depending on load order.
    """
    if not directory.exists():
        return []
    versions: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReviewError(f"paquete corrupto: {path}") from exc
        documents = raw if isinstance(raw, list) else raw.get("items", [raw])
        if not isinstance(documents, list):
            raise ReviewError(f"paquete inválido: {path}")
        for proposal in documents:
            if not isinstance(proposal, dict):
                raise ReviewError(f"propuesta inválida: {path}")
            identifier = _proposal_id(proposal)
            workspace = _non_empty(proposal.get("workspace"), "workspace")
            _non_empty(proposal.get("source_id"), "source_id")
            _non_empty(proposal.get("episode_id"), "episode_id")
            _evidence_parts(proposal)
            actual_hash = proposal_hash(proposal)
            declared_hash = proposal.get("proposal_hash")
            # Legacy exporters used a different self-hash. Accept it as input,
            # but canonicalise every loaded version at this trust boundary.
            normalized = json.loads(_canonical(proposal))
            normalized["proposal_hash"] = actual_hash
            by_hash = versions.setdefault((workspace, identifier), {})
            existing = by_hash.get(actual_hash)
            if existing is None:
                normalized["package_origins"] = [path.name]
                if declared_hash and declared_hash != actual_hash:
                    normalized["legacy_proposal_hash"] = declared_hash
                by_hash[actual_hash] = normalized
            else:
                existing["package_origins"] = sorted(
                    set(existing.get("package_origins") or ()) | {path.name}
                )
    proposals: list[dict[str, Any]] = []
    for key in sorted(versions):
        by_hash = versions[key]
        # Immutable package names are content-addressed. Lexical selection is
        # stable under reversed directory iteration and process restart.
        active_hash = max(
            by_hash,
            key=lambda digest: (
                max(by_hash[digest].get("package_origins") or ("",)),
                digest,
            ),
        )
        active = by_hash[active_hash]
        active["available_version_hashes"] = sorted(by_hash)
        proposals.append(active)
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


def _scoped(scope: "VisibilityScope | None") -> "VisibilityScope":
    """Ámbito efectivo del llamador (sin ámbito explícito = interno, sin filtro).

    Las rutas HTTP siempre inyectan el ámbito de la petición. El corpus de
    propuestas V3 usa `workspace` como etiqueta del corpus, no como workspace
    del visor, por lo que aquí aplica la barrera de partida (ver
    ``app.authz.scope``).
    """
    return (scope or UNRESTRICTED).partida_only()


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
        self.database_path = (
            default_database_path()
            if self.decisions_path == default_decisions_path()
            else self.decisions_path.with_suffix(".sqlite3")
        )
        self.store = SQLiteReviewStore(self.database_path)
        # Kept only as a testable boundary: this service must never dereference it.
        self._graph_driver = graph_driver

    def workspaces(self, scope: "VisibilityScope | None" = None) -> tuple[str, ...]:
        """Workspaces con al menos una propuesta VISIBLE en el ámbito."""
        allowed = _scoped(scope)
        return tuple(sorted({
            str(item["workspace"])
            for item in load_proposals(self.proposals_dir)
            if allowed.allows(item)
        }))

    def glossary_candidates(self, workspace: str,
                            scope: "VisibilityScope | None" = None) -> list[dict[str, Any]]:
        self.store.project_outbox(workspace, _now())
        allowed = _scoped(scope)
        return [c for c in self.store.candidates(workspace) if allowed.allows(c)]

    def queue(
        self,
        workspace: str,
        *,
        source_id: str | None = None,
        engine_decision: str | None = None,
        include_decided: bool = False,
        scope: "VisibilityScope | None" = None,
    ) -> QueueView:
        workspace = _non_empty(workspace, "workspace")
        history = self.store.decisions()
        active = _active_decisions(history)
        allowed = _scoped(scope)
        # El ámbito se aplica ANTES de contar: `total` y `remaining` tampoco
        # deben delatar propuestas de otra partida.
        all_workspace = [
            proposal for proposal in load_proposals(self.proposals_dir)
            if proposal["workspace"] == workspace and allowed.allows(proposal)
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
            "proposal_hash": proposal_hash(proposal),
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
        expected_proposal_hash: str | None = None,
        scope: "VisibilityScope | None" = None,
    ) -> dict[str, Any]:
        if human_decision not in VALID_HUMAN_DECISIONS:
            raise ReviewError(f"human_decision inválida: {human_decision}")
        request_id = _non_empty(request_id, "request_id")
        reviewer = _non_empty(reviewer, "reviewer")
        workspace = _non_empty(workspace, "workspace")

        with _lock_for(self.decisions_path):
            history = self.store.decisions()
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
                    and _scoped(scope).allows(item)
                ),
                None,
            )
            if proposal is None:
                raise ReviewError("propuesta inexistente en el workspace seleccionado")
            actual_proposal_hash = proposal_hash(proposal)
            # None is retained for programmatic backwards compatibility. The HTML
            # route always supplies the hash the reviewer actually saw.
            expected = expected_proposal_hash or actual_proposal_hash
            if expected != actual_proposal_hash:
                self._audit_stale(
                    proposal=proposal, reviewer=reviewer, request_id=request_id,
                    human_decision=human_decision, expected=expected,
                    actual=actual_proposal_hash,
                )
                raise StaleReviewError(self.present(proposal))
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
                "proposal_id": proposal_id,
                "proposal": json.loads(_canonical(proposal)),
                "expected_proposal_hash": expected,
                "actual_proposal_hash": actual_proposal_hash,
                "engine_decision": json.loads(_canonical(engine_decision)),
                "effective_decision": engine_decision.get("effective_decision"),
                "shadow_decision": engine_decision.get("shadow_decision"),
                "human_decision": human_decision,
                "correction": correction or {},
                "rationale": rationale.strip(),
                "ontology_version": (
                    proposal.get("ontology_version")
                    or (proposal.get("ontology") or {}).get("version")
                ),
                "engine_version": proposal.get("engine_version"),
                "prompt_version": proposal.get("prompt_version"),
                "supersedes_decision_id": supersedes_decision_id,
                "previous_hash": history[-1]["record_hash"] if history else None,
            }
            record["record_hash"] = _sha256(record)
            outbox = self._glossary_outbox_payload(record, proposal)
            stored, created = self.store.append_decision_and_outbox(record, outbox)
            if not created:
                if (
                    stored["workspace"] != workspace
                    or stored["proposal"]["proposal_id"] != proposal_id
                    or stored["reviewer"] != reviewer
                    or stored["human_decision"] != human_decision
                ):
                    raise ReviewError("request_id reutilizado con otra decisión")
                return stored
            # JSONL remains a compatibility/audit export, never the authority.
            self.decisions_path.parent.mkdir(parents=True, exist_ok=True)
            with self.decisions_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(_canonical(record) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self.store.project_outbox(workspace, _now())
            return stored

    def _audit_stale(self, *, proposal: dict[str, Any], reviewer: str, request_id: str,
                     human_decision: str, expected: str, actual: str) -> None:
        path = default_audit_path() if self.decisions_path == default_decisions_path() else (
            self.decisions_path.with_name("audit.jsonl")
        )
        event = {
            "event": "STALE_REVIEW", "timestamp": _now(), "request_id": request_id,
            "reviewer": reviewer, "workspace": proposal["workspace"],
            "source_id": proposal["source_id"], "episode_id": proposal["episode_id"],
            "proposal_id": _proposal_id(proposal),
            "expected_proposal_hash": expected, "actual_proposal_hash": actual,
            "human_decision": human_decision,
        }
        self.store.audit_stale(event)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _glossary_outbox_payload(
        self, record: dict[str, Any], proposal: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Only explicit human fields can produce candidates; rejections cannot."""
        if record["human_decision"] == "REJECT":
            return None
        correction = record["correction"]
        mapping = [
            ("subject_canonical_name", "CANONICAL_TERM_CANDIDATE", "subject"),
            ("object_canonical_name", "CANONICAL_TERM_CANDIDATE", "object"),
            ("subject_alias", "ALIAS_CANDIDATE", "subject"),
            ("object_alias", "ALIAS_CANDIDATE", "object"),
            ("spoken_form", "SPOKEN_FORM_CANDIDATE", "subject"),
            ("suggested_entity_type", "ENTITY_TYPE_CANDIDATE", "subject"),
            ("misrecognition", "KNOWN_MISRECOGNITION_CANDIDATE", "subject"),
        ]
        claim = proposal.get("proposal") or {}
        provenance = proposal.get("provenance") or {}
        candidates: list[dict[str, Any]] = []
        for field, candidate_type, canonical_field in mapping:
            value = str(correction.get(field) or "").strip()
            if not value:
                continue
            # An OCR/ASR correction is a known misrecognition, never an alias.
            canonical = str(claim.get(canonical_field) or value)
            resolved = (proposal.get("resolution") or {}).get(canonical_field)
            semantic_key = [
                record["workspace"], candidate_type,
                " ".join(canonical.casefold().split()),
                " ".join(value.casefold().split()), resolved,
            ]
            candidate_id = f"glossary:{_sha256(semantic_key)}"
            candidate = {
                "candidate_id": candidate_id,
                "candidate_type": candidate_type,
                "status": "PROPOSED",
                "workspace": record["workspace"],
                "canonical_value": canonical,
                "candidate_value": value,
                "entity_type": correction.get("suggested_entity_type"),
                "resolved_entity_id": resolved,
                "source_ids": [record["source_id"]],
                "episode_ids": [record["episode_id"]],
                "evidence": [proposal.get("evidence") or {}],
                "occurrence_count": 1,
                "source_count": 1,
                "origin": {
                    "human_decision_ids": [record["decision_id"]],
                    "proposal_ids": [record["proposal_id"]],
                    "extractors": provenance.get("extractors", []),
                    "providers": provenance.get("providers", []),
                },
                "confidence": None,
                "reason_codes": ["EXPLICIT_HUMAN_CORRECTION"],
                "created_at": record["timestamp"],
            }
            # Un candidato heredado de material de partida sigue siendo de esa
            # partida: se estampa para que el ámbito lo filtre igual que a la
            # propuesta de la que nace. Sin partida = capa juego (no se añade
            # la clave, para no alterar los documentos ya existentes).
            partida_id = proposal.get("partida_id")
            if partida_id:
                candidate["partida_id"] = partida_id
            candidates.append(candidate)
        return {"candidates": candidates} if candidates else None

    def undo_last(self, *, workspace: str, reviewer: str, request_id: str,
                  scope: "VisibilityScope | None" = None) -> dict[str, Any]:
        with _lock_for(self.decisions_path):
            history = self.store.decisions()
            allowed = _scoped(scope)
            active = [
                record for record in _active_decisions(history).values()
                if record["workspace"] == workspace and allowed.allows(record["proposal"])
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
                scope=scope,
            )
