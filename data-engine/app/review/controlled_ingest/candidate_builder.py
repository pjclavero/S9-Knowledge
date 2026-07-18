"""Productor de review-candidate-v1 a partir de segmentos del motor.

Toma como base el modelo de extraccion existente (``review.models.Candidate``,
producido por ``review.extractor``) y lo proyecta al contrato v1. El motor no
decide por si mismo: propone un estado (por defecto REQUIRES_REVIEW) y sus
razones de politica; AUTO_APPROVABLE es SOLO recomendacion y nunca se convierte
automaticamente en APPROVED.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .hashing import hash_block

# Vocabulario controlado de razones de politica (la confianza NO basta por si sola).
REASON_NEW_ENTITY = "NEW_ENTITY"
REASON_RELATION_UNSUPPORTED = "RELATION_UNSUPPORTED"
REASON_EXISTING_MATCH = "EXISTING_MATCH_FOUND"
REASON_WEAK_TERM = "WEAK_TERM"
REASON_GLOSSARY_MATCH = "GLOSSARY_MATCH"

_ENTITY_KINDS = {"entity", "location", "object", "event", "rumor", "session_fact"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class SourceContext:
    """Contexto inmutable de la fuente en revision (todo anonimizable)."""

    workspace: str
    source_id: str
    source_hash_value: str  # 64 hex
    review_generation: int
    pipeline_version: str = "0.3.0"
    producer_name: str = "s9k-data-engine"
    producer_version: str = "0.3.0"

    def source_hash(self) -> dict[str, str]:
        return {"algorithm": "sha256", "value": self.source_hash_value}

    def producer(self) -> dict[str, Any]:
        return {
            "kind": "ENGINE",
            "name": self.producer_name,
            "version": self.producer_version,
            "model": None,
        }

    def provenance(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_hash": self.source_hash(),
            "review_generation": self.review_generation,
            "pipeline_version": self.pipeline_version,
            "producer": self.producer(),
        }


@dataclass
class EngineCandidate:
    """Vista minima y anonimizable de un candidato del extractor del motor.

    Refleja los campos de ``review.models.Candidate`` que el contrato necesita.
    ``from_engine`` permite convertir directamente un ``Candidate`` real.
    """

    candidate_id: str
    segment_id: str
    kind: str  # entity | relation | location | object | ...
    name: str
    entity_type: str
    confidence: float
    evidence: str
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    existing_matches: list[dict[str, Any]] = field(default_factory=list)
    location: Optional[dict[str, Any]] = None

    @classmethod
    def from_engine(cls, cand: Any, location: Optional[dict[str, Any]] = None) -> "EngineCandidate":
        return cls(
            candidate_id=cand.candidate_id,
            segment_id=cand.segment_id,
            kind=cand.kind,
            name=cand.name or (cand.relation_type or "UNKNOWN"),
            entity_type=cand.entity_type or "Entity",
            confidence=float(cand.confidence),
            evidence=cand.evidence or "",
            aliases=list(getattr(cand, "aliases", []) or []),
            description=getattr(cand, "description", "") or "",
            attributes=dict(getattr(cand, "attributes", {}) or {}),
            existing_matches=[],
            location=location,
        )


def _default_location() -> dict[str, Any]:
    return {"kind": "OFFSET_RANGE", "offset_start": 0, "offset_end": 0}


def build_candidate(ctx: SourceContext, ec: EngineCandidate) -> dict[str, Any]:
    """Construye un documento review-candidate-v1 (no validado aqui)."""
    location = ec.location or _default_location()
    candidate_kind = "RELATION" if ec.kind == "relation" else "ENTITY"

    policy_reasons: list[str] = []
    if candidate_kind == "RELATION":
        policy_reasons.append(REASON_RELATION_UNSUPPORTED)
    if ec.existing_matches:
        policy_reasons.append(REASON_EXISTING_MATCH)
    else:
        policy_reasons.append(REASON_NEW_ENTITY)
    if ec.attributes.get("weak"):
        policy_reasons.append(REASON_WEAK_TERM)

    # El motor propone; la revision humana sigue siendo obligatoria. Nunca
    # proponemos APPROVED automaticamente.
    proposed_status = "REQUIRES_REVIEW"

    quote = (ec.evidence or ec.name or "").strip()[:2000] or ec.name

    doc: dict[str, Any] = {
        "schema_version": "1.0.0",
        "document_type": "review-candidate",
        "document_id": f"review-candidate_{ec.candidate_id}",
        "created_at": _now_iso(),
        "workspace": ctx.workspace,
        "source_id": ctx.source_id,
        "source_hash": ctx.source_hash(),
        "review_generation": ctx.review_generation,
        "producer": ctx.producer(),
        "provenance": ctx.provenance(),
        "candidate_id": ec.candidate_id,
        "segment_id": ec.segment_id,
        "candidate_kind": candidate_kind,
        "entity_type": ec.entity_type,
        "canonical_name": ec.name,
        "display_name": ec.name,
        "aliases": sorted(set(ec.aliases)),
        "description": ec.description,
        "attributes": {k: v for k, v in ec.attributes.items() if k != "weak"},
        "confidence": max(0.0, min(1.0, ec.confidence)),
        "evidence": [
            {
                "evidence_id": f"ev_{ec.candidate_id}",
                "quote": quote,
                "location": location,
            }
        ],
        "source_location": location,
        "existing_matches": ec.existing_matches,
        "proposed_status": proposed_status,
        "policy_reasons": policy_reasons,
        "requires_review": True,
        "created_by": ctx.producer(),
    }
    return doc


def candidate_hash(candidate_doc: dict[str, Any]) -> dict[str, str]:
    """Hash canonico del candidato para control optimista de decisiones."""
    return hash_block(candidate_doc)


__all__ = [
    "SourceContext",
    "EngineCandidate",
    "build_candidate",
    "candidate_hash",
    "REASON_NEW_ENTITY",
    "REASON_RELATION_UNSUPPORTED",
    "REASON_EXISTING_MATCH",
]
