# -*- coding: utf-8 -*-
"""Paquete `relations` del data-engine.

Contiene UNICAMENTE el contrato interno `relation-candidate/internal-v1`
(modelo + validadores + serializacion determinista). No implementa extractor,
prompts, Ollama, NVIDIA, ensemble, autoaprobacion ni escritura en Neo4j: esos
subsistemas viven en otros modulos (external_ai, external_processing, ...) y
este paquete solo REFERENCIA sus estados canonicos de consenso.
"""
from __future__ import annotations

from relations.contracts import (
    SCHEMA_VERSION,
    DOCUMENT_TYPE,
    Direction,
    ExtractionMethod,
    EpistemicStatus,
    CANONICAL_CONSENSUS_STATES,
    REFLEXIVE_PREDICATES,
    RelationCandidate,
    RelationContractError,
    normalize_predicate,
)

__all__ = [
    "SCHEMA_VERSION",
    "DOCUMENT_TYPE",
    "Direction",
    "ExtractionMethod",
    "EpistemicStatus",
    "CANONICAL_CONSENSUS_STATES",
    "REFLEXIVE_PREDICATES",
    "RelationCandidate",
    "RelationContractError",
    "normalize_predicate",
]
