# -*- coding: utf-8 -*-
"""`entity-resolution/v3-internal-v1`: decision de identidad sobre menciones."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Optional

from .base import V3Document


class ResolutionAction(str, Enum):
    LINK_EXISTING = "LINK_EXISTING"
    CREATE_PROVISIONAL = "CREATE_PROVISIONAL"
    CREATE_NEW = "CREATE_NEW"
    SPLIT = "SPLIT"
    REVIEW = "REVIEW"


@dataclass
class EntityResolution(V3Document):
    """`CREATE_PROVISIONAL` evita fabricar nodos definitivos por errores de ASR/OCR."""

    CONTRACT_ID: ClassVar[str] = "entity-resolution/v3-internal-v1"
    OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset(
        {"metadata", "entity_type", "split_groups"}
    )

    contract_version: str
    workspace: str
    source_asset_id: str
    source_hash: dict
    provider_trace: list
    resolution_id: str
    mention_ids: list
    candidate_entity_ids: list
    selected_entity_id: Optional[str]
    action: str
    confidence: float
    evidence: list
    reason_codes: list
    game_profile: str
    entity_type: Optional[str] = None
    split_groups: Optional[list] = None
    metadata: Optional[dict[str, Any]] = None

    def is_provisional(self) -> bool:
        return self.action == ResolutionAction.CREATE_PROVISIONAL.value
