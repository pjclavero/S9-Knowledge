# -*- coding: utf-8 -*-
"""Contratos internos versionados de S9-Knowledge V3 (familia `v3-internal-v1`).

Nueve contratos, un solo envelope comun y un solo validador. Los JSON Schema
viven en `contracts/knowledge-v3/v1/` (compartidos por motor y visor, igual que
los de review/ingest v1); aqui viven los modelos Python que los envuelven.

Envelope comun obligatorio en los nueve:

    contract_id · contract_version · workspace · source_asset_id ·
    source_hash · provider_trace

`relation-candidate/internal-v1` (`relations/contracts.py`) NO se toca: para
llegar a el existe `knowledge_v3.adapters.relation_candidate_v1`.
"""
from __future__ import annotations

from .base import (  # noqa: F401
    CONTRACT_FAMILY,
    CONTRACT_VERSION,
    CONTRACTS_DIR,
    Provider,
    V3ContractError,
    V3Document,
    canonical_json,
    compute_decision_hash,
    compute_idempotency_key,
    compute_plan_hash,
    find_step,
    parse_document,
    producing_step,
    provider_step,
    seal_plan,
    sha256_hash,
)
from .assertion import AssertionStatus, FactAssertion  # noqa: F401
from .claim import ClaimProposal, EpistemicStatusHint  # noqa: F401
from .episode import Modality, SourceEpisode  # noqa: F401
from .evidence import MEDIA_TYPES, EvidenceFragment  # noqa: F401
from .game_profile import GameProfile  # noqa: F401
from .mention import EntityMention  # noqa: F401
from .mutation_plan import (  # noqa: F401
    EngineDecision,
    GraphMutationPlan,
    MutationOperationType,
)
from .resolution import EntityResolution, ResolutionAction  # noqa: F401
from .source_asset import CopyrightClass, PrivacyClass, SourceAsset, SourceKind  # noqa: F401

#: Despacho `contract_id` -> clase. Fuente unica para `parse_document`.
CONTRACT_CLASSES: dict[str, type[V3Document]] = {
    SourceAsset.CONTRACT_ID: SourceAsset,
    SourceEpisode.CONTRACT_ID: SourceEpisode,
    EvidenceFragment.CONTRACT_ID: EvidenceFragment,
    EntityMention.CONTRACT_ID: EntityMention,
    ClaimProposal.CONTRACT_ID: ClaimProposal,
    EntityResolution.CONTRACT_ID: EntityResolution,
    FactAssertion.CONTRACT_ID: FactAssertion,
    GraphMutationPlan.CONTRACT_ID: GraphMutationPlan,
    GameProfile.CONTRACT_ID: GameProfile,
}

__all__ = [
    "CONTRACT_CLASSES",
    "CONTRACT_FAMILY",
    "CONTRACT_VERSION",
    "CONTRACTS_DIR",
    "MEDIA_TYPES",
    "AssertionStatus",
    "ClaimProposal",
    "CopyrightClass",
    "EngineDecision",
    "EntityMention",
    "EntityResolution",
    "EpistemicStatusHint",
    "EvidenceFragment",
    "FactAssertion",
    "GameProfile",
    "GraphMutationPlan",
    "Modality",
    "MutationOperationType",
    "PrivacyClass",
    "Provider",
    "ResolutionAction",
    "SourceAsset",
    "SourceEpisode",
    "SourceKind",
    "V3ContractError",
    "V3Document",
    "canonical_json",
    "compute_decision_hash",
    "compute_idempotency_key",
    "compute_plan_hash",
    "find_step",
    "parse_document",
    "producing_step",
    "provider_step",
    "seal_plan",
    "sha256_hash",
]
