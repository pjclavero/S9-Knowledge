# -*- coding: utf-8 -*-
"""`evidence-fragment/v3-internal-v1`: anclaje literal de evidencia."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Optional

from .base import V3Document

#: Tipos identicos a media/multimedia_contract.MediaType. No se duplican
#: semanticas: OCR literal e interpretacion visual siguen siendo distintos.
MEDIA_TYPES = (
    "EMBEDDED_TEXT",
    "ASR_TEXT",
    "OCR_TEXT",
    "IMAGE_DESCRIPTION",
    "TABLE",
    "MAP",
    "DIAGRAM",
    "CHARACTER_SHEET",
    "CAPTION",
    "UNKNOWN_VISUAL",
)


@dataclass
class EvidenceFragment(V3Document):
    """Offsets, bbox y timecodes los pone el sistema local, nunca un proveedor."""

    CONTRACT_ID: ClassVar[str] = "evidence-fragment/v3-internal-v1"

    contract_version: str
    workspace: str
    source_asset_id: str
    source_hash: dict
    provider_trace: list
    fragment_id: str
    episode_id: str
    literal_text: str
    normalized_text: str
    start: int
    end: int
    bbox: Optional[dict]
    time_start: Optional[float]
    time_end: Optional[float]
    frame_id: Optional[str]
    page: Optional[int]
    media_type: str
    confidence: float
    metadata: Optional[dict[str, Any]] = None
