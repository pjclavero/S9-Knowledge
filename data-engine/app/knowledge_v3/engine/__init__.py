# -*- coding: utf-8 -*-
"""Motor local de conocimiento S9-Knowledge V3 (subsistema D, dosier §11).

    claims + resoluciones + evidencias + episodios + perfil + snapshot
        -> decisiones (ACCEPT / REJECT_INVALID / ABSTAIN / REVIEW)
        -> FactAssertion
        -> GraphMutationPlan sellado

Es la unica pieza del sistema con autoridad: valida, aprueba, invalida y
autoriza escrituras. Ollama y los proveedores externos entran aqui como
`ExternalSignal` — datos, no decisiones.

Nada de este paquete escribe en Neo4j, llama a un proveedor o mira el reloj.

Documentacion: `docs/v3/05-local-engine.md`.
"""
from __future__ import annotations

from .config import DEFAULT_CONFIG, ENGINE_NAME, ENGINE_VERSION, EngineConfig  # noqa: F401
from .contradiction import ContradictionOutcome, check_contradictions  # noqa: F401
from .decision import ClaimDecision, decide_claim  # noqa: F401
from .engine import EngineResult, LocalKnowledgeEngine  # noqa: F401
from .errors import (  # noqa: F401
    EngineContractGap,
    EngineError,
    EngineInputError,
    EnginePlanError,
)
from .evidence import EvidenceIndex, verify_evidence  # noqa: F401
from .findings import Finding, Severity, decision_for, reason_codes_for  # noqa: F401
from .identity import ResolutionIndex, resolve_identity  # noqa: F401
from .ontology import (  # noqa: F401
    PredicateSpec,
    ProfileIndex,
    canonical_key,
    resolve_direction,
    resolve_predicate,
)
from .planner import PlanContext, build_plan  # noqa: F401
from .signals import ExternalSignal  # noqa: F401
from .shadow import ShadowDecisionRecord, has_semantic_origin  # noqa: F401
from .snapshot import (  # noqa: F401
    GraphSnapshot,
    InMemoryGraphSnapshot,
    Neo4jReadOnlyGraphSnapshot,
    SnapshotAssertion,
    SnapshotEntity,
    empty_snapshot,
)
from .temporal import TemporalOutcome, resolve_temporality  # noqa: F401

__all__ = [
    "ClaimDecision",
    "ContradictionOutcome",
    "DEFAULT_CONFIG",
    "ENGINE_NAME",
    "ENGINE_VERSION",
    "EngineConfig",
    "EngineContractGap",
    "EngineError",
    "EngineInputError",
    "EnginePlanError",
    "EngineResult",
    "EvidenceIndex",
    "ExternalSignal",
    "Finding",
    "GraphSnapshot",
    "InMemoryGraphSnapshot",
    "LocalKnowledgeEngine",
    "Neo4jReadOnlyGraphSnapshot",
    "PlanContext",
    "PredicateSpec",
    "ProfileIndex",
    "ResolutionIndex",
    "Severity",
    "SnapshotAssertion",
    "SnapshotEntity",
    "ShadowDecisionRecord",
    "has_semantic_origin",
    "TemporalOutcome",
    "build_plan",
    "canonical_key",
    "check_contradictions",
    "decide_claim",
    "decision_for",
    "empty_snapshot",
    "reason_codes_for",
    "resolve_direction",
    "resolve_identity",
    "resolve_predicate",
    "resolve_temporality",
    "verify_evidence",
]
