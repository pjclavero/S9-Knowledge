# -*- coding: utf-8 -*-
"""`fact-assertion/v3-internal-v1`: unidad autoritativa del ledger temporal."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Optional

from .base import V3Document


class AssertionStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ASSERTED = "ASSERTED"
    CONFIRMED = "CONFIRMED"
    LIMITED = "LIMITED"
    SUPERSEDED = "SUPERSEDED"
    CONTRADICTED = "CONTRADICTED"
    RETRACTED = "RETRACTED"


@dataclass
class FactAssertion(V3Document):
    """La arista directa del grafo es una proyeccion; la verdad vive aqui."""

    CONTRACT_ID: ClassVar[str] = "fact-assertion/v3-internal-v1"
    OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({"metadata", "negated"})

    contract_version: str
    workspace: str
    source_asset_id: str
    source_hash: dict
    provider_trace: list
    assertion_id: str
    subject_entity_id: str
    object_entity_id: str
    predicate: str
    direction: str
    valid_from: Optional[str]
    valid_to: Optional[str]
    recorded_at: str
    epistemic_status: str
    confidence: float
    status: str
    collection_id: str
    game_profile: str
    engine_version: str
    ontology_version: str
    evidence_fragment_ids: list
    episode_ids: list
    supersedes: Optional[str]
    superseded_by: Optional[str]
    negated: Optional[bool] = None
    metadata: Optional[dict[str, Any]] = None

    def is_open_interval(self) -> bool:
        """True si la afirmacion sigue vigente (sin `valid_to`)."""
        return self.valid_to is None
