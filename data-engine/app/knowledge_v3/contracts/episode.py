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
    produced_by_step: str
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
    # `speaker`, `turn` y `table` NO estan en `required` del JSON Schema
    # congelado (source-episode-v3.schema.json): son opcionales de verdad y
    # solo tienen sentido en modalidades con diarizacion o en TABLE. Hasta
    # ahora se declaraban SIN valor por defecto, asi que `_optional_names()`
    # no los veia y `from_dict` los exigia: un episodio de texto plano valido
    # segun el contrato publicado era rechazado por el modelo Python. El
    # defecto estaba registrado como GATE4-03.
    #
    # Llevan default=None pero NO entran en `OMIT_IF_NONE`: el schema los
    # declara nullable (`anyOf` con `"type": "null"`), asi que seguir
    # emitiendo la clave con `null` es valido y deja `to_dict()` byte a byte
    # igual que antes. Esto solo relaja la LECTURA, no cambia la escritura.
    speaker: Optional[dict] = None
    turn: Optional[int] = None
    table: Optional[dict] = None
    metadata: Optional[dict[str, Any]] = None
