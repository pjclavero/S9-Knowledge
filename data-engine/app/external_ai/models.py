# -*- coding: utf-8 -*-
"""Modelos de datos del subsistema de IA externa (Fase A).

Contratos compartidos por proveedores, prompts, parser, consenso y calibración.
Todo es serializable a dict (to_dict) para persistir en output/ (fuera de Git).
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# Decisiones permitidas de un revisor de modelo.
VALID_DECISIONS = ("accept", "edit", "use_existing", "reject", "uncertain")
# Tipos de entidad permitidos (esquema S9 Knowledge).
ALLOWED_ENTITY_TYPES = ("Character", "Location", "Faction", "Object", "Event", "Concept")

# Estados del motor de consenso (Fase A: no existe AUTO_APPROVED).
STRONG_CONSENSUS = "STRONG_CONSENSUS"
PARTIAL_CONSENSUS = "PARTIAL_CONSENSUS"
MODEL_CONFLICT = "MODEL_CONFLICT"
INVALID_RESPONSES = "INVALID_RESPONSES"
HUMAN_REQUIRED = "HUMAN_REQUIRED"
CONSENSUS_STATES = (STRONG_CONSENSUS, PARTIAL_CONSENSUS, MODEL_CONFLICT,
                    INVALID_RESPONSES, HUMAN_REQUIRED)


@dataclass
class ReviewItem:
    """Un candidato local a revisar por los modelos externos (sanitizado)."""
    candidate_id: str
    kind: str                      # entity | relation
    name: Optional[str]
    entity_type: Optional[str]
    evidence: str
    local_confidence: float
    segment_text: str              # texto original sanitizado del segmento
    neo4j_matches: list = field(default_factory=list)  # coincidencias sanitizadas

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReviewBatchRequest:
    """Lote de revisión enviado a un modelo (ya sanitizado, sin datos privados)."""
    workspace: str
    source_id: str                 # anonimizado
    items: list                    # list[ReviewItem]
    allowed_types: tuple = ALLOWED_ENTITY_TYPES
    glossary: list = field(default_factory=list)   # términos canónicos mínimos
    schema_version: str = "1.0"
    prompt_version: str = "1.0"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["items"] = [i.to_dict() if isinstance(i, ReviewItem) else i for i in self.items]
        return d


@dataclass
class ModelReviewDecision:
    """Decisión de un modelo sobre un candidato (respuesta validada)."""
    candidate_id: str
    decision: str                  # accept|edit|use_existing|reject|uncertain
    canonical_name: Optional[str] = None
    entity_type: Optional[str] = None
    matched_existing: Optional[str] = None
    evidence: str = ""
    confidence: float = 0.0
    reason_codes: list = field(default_factory=list)
    explanation: str = ""
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ModelReviewResponse:
    """Respuesta completa de un modelo/revisor sobre un lote."""
    provider: str
    model: str
    reviewer_role: str             # reviewer_a | reviewer_b | adjudicator
    decisions: list                # list[ModelReviewDecision]
    prompt_version: str = "1.0"
    request_hash: str = ""
    response_hash: str = ""
    latency_ms: int = 0
    token_usage: Optional[TokenUsage] = None
    validation_errors: list = field(default_factory=list)
    raw_response_path: Optional[str] = None   # ruta local (fuera de Git)

    @property
    def valid(self) -> bool:
        return not self.validation_errors and bool(self.decisions)

    def by_candidate(self) -> dict:
        return {d.candidate_id: d for d in self.decisions}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["valid"] = self.valid
        return d


@dataclass
class ProviderHealth:
    provider: str
    ok: bool
    models_available: list = field(default_factory=list)
    detail: str = ""
    latency_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ConsensusResult:
    """Resultado del motor de consenso para un candidato. shadow_recommendation
    NUNCA es una decisión productiva."""
    candidate_id: str
    state: str                     # uno de CONSENSUS_STATES
    shadow_recommendation: str     # accept|edit|use_existing|reject|uncertain|human
    reviewer_a: Optional[dict] = None
    reviewer_b: Optional[dict] = None
    adjudication: Optional[dict] = None
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
