"""Dataclasses del pipeline de revisión S9 Knowledge.

Segment       — bloque de transcripción (3-5 min)
Candidate     — entidad/relación/evento extraído
ValidationResult — resultado de validación del candidato
ResolutionResult — resultado de búsqueda en Neo4j
Decision      — decisión final del auto_decider
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ── Segment ───────────────────────────────────────────────────────────────────

@dataclass
class Segment:
    segment_id: str           # <source_id>_seg_0001
    source_id: str
    source_kind: str          # audio | video | markdown
    workspace: str
    timestamp_start: str      # HH:MM:SS
    timestamp_end: str        # HH:MM:SS
    text: str
    lines: list[str] = field(default_factory=list)  # líneas originales con timestamps

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Segment":
        return cls(**d)


# ── Candidate ─────────────────────────────────────────────────────────────────

@dataclass
class Candidate:
    candidate_id: str
    source_id: str
    segment_id: str
    workspace: str
    kind: str                 # entity | relation | event | location | object | rumor | session_fact
    # Para entidades/localizaciones/objetos
    name: Optional[str] = None
    entity_type: Optional[str] = None   # Character, Location, Faction, …
    # Para relaciones
    from_entity: Optional[str] = None
    to_entity: Optional[str] = None
    from_type: Optional[str] = None
    to_type: Optional[str] = None
    relation_type: Optional[str] = None
    # Para eventos
    event_description: Optional[str] = None
    # Metadatos comunes
    confidence: float = 0.5
    evidence: str = ""
    timestamp_start: str = ""
    timestamp_end: str = ""
    source_kind: str = "audio"
    status: str = "pending"   # pending | approved | rejected | needs_review

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Candidate":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── ValidationResult ──────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    candidate_id: str
    valid: str                # valid | invalid | dubious
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ValidationResult":
        return cls(**d)


# ── ResolutionResult ──────────────────────────────────────────────────────────

@dataclass
class ResolutionResult:
    candidate_id: str
    action: str               # use_existing | create_new | needs_review | reject
    matched_canonical: Optional[str] = None
    match_score: float = 0.0
    match_type: str = "none"  # exact | alias | normalized | fuzzy | none
    alternatives: list[str] = field(default_factory=list)
    reason: str = ""
    neo4j_available: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ResolutionResult":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Decision ──────────────────────────────────────────────────────────────────

@dataclass
class Decision:
    candidate_id: str
    decision: str             # auto_approve | needs_review | auto_reject
    reason: str = ""
    # Snapshot de los datos para el payload final
    candidate: Optional[dict] = None
    validation: Optional[dict] = None
    resolution: Optional[dict] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Decision":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
