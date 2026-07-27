# -*- coding: utf-8 -*-
"""`source-episode/v3-internal-v1`: trozo direccionable de una fuente."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Optional

from .base import V3Document


class Modality(str, Enum):
    TEXT = "TEXT"
    OCR_TEXT = "OCR_TEXT"
    HTR_TEXT = "HTR_TEXT"
    ASR_TEXT = "ASR_TEXT"
    IMAGE = "IMAGE"
    TABLE = "TABLE"
    DIAGRAM = "DIAGRAM"
    MAP = "MAP"
    VIDEO_FRAME = "VIDEO_FRAME"
    SPEAKER_TURN = "SPEAKER_TURN"
    MESSAGE = "MESSAGE"


@dataclass
class SourceEpisode(V3Document):
    """Pagina, seccion, escena, intervalo, turno, frame, region, tabla o mensaje."""

    CONTRACT_ID: ClassVar[str] = "source-episode/v3-internal-v1"

    contract_version: str
    workspace: str
    source_asset_id: str
    source_hash: dict
    provider_trace: list
    episode_id: str
    asset_id: str
    sequence: int
    modality: str
    text: Optional[str]
    page: Optional[int]
    bbox: Optional[dict]
    time_start: Optional[float]
    time_end: Optional[float]
    previous_episode_id: Optional[str]
    next_episode_id: Optional[str]
    quality: dict
    content_hash: dict
    metadata: Optional[dict[str, Any]] = None
