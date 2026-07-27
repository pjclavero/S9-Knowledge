# -*- coding: utf-8 -*-
"""`entity-mention/v3-internal-v1`: mencion de entidad dentro de un episodio."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Optional

from .base import V3Document


@dataclass
class EntityMention(V3Document):
    """Propone tipos y correferencias; NO decide identidad (eso es EntityResolution)."""

    CONTRACT_ID: ClassVar[str] = "entity-mention/v3-internal-v1"

    contract_version: str
    workspace: str
    source_asset_id: str
    source_hash: dict
    provider_trace: list
    produced_by_step: str
    mention_id: str
    episode_id: str
    surface: str
    normalized_surface: str
    start: int
    end: int
    bbox: Optional[dict]
    time_start: Optional[float]
    time_end: Optional[float]
    type_candidates: list
    confidence: float
    coreference_candidates: list
    evidence_fragment_ids: list
    metadata: Optional[dict[str, Any]] = None

    def best_type(self) -> Optional[str]:
        """Tipo mas probable, o None si la mencion no se atreve a tipar."""
        if not self.type_candidates:
            return None
        return max(self.type_candidates, key=lambda c: c["confidence"])["type"]
