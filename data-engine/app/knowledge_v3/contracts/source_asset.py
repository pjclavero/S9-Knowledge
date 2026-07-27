# -*- coding: utf-8 -*-
"""`source-asset/v3-internal-v1`: la fuente original ingerida."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Optional

from .base import V3Document


class SourceKind(str, Enum):
    PDF = "PDF"
    IMAGE = "IMAGE"
    HANDWRITING = "HANDWRITING"
    MAP = "MAP"
    DIAGRAM = "DIAGRAM"
    CHARACTER_SHEET = "CHARACTER_SHEET"
    TABLE = "TABLE"
    AUDIO = "AUDIO"
    VIDEO = "VIDEO"
    YOUTUBE = "YOUTUBE"
    MARKDOWN = "MARKDOWN"
    TEXT = "TEXT"
    WEB = "WEB"
    NOTE = "NOTE"


class PrivacyClass(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    PERSONAL_DATA = "PERSONAL_DATA"
    RESTRICTED = "RESTRICTED"


class CopyrightClass(str, Enum):
    OWN = "OWN"
    LICENSED = "LICENSED"
    COPYRIGHTED = "COPYRIGHTED"
    UNKNOWN = "UNKNOWN"


@dataclass
class SourceAsset(V3Document):
    """Raiz de la procedencia: su `content_hash` es el `source_hash` de la cadena."""

    CONTRACT_ID: ClassVar[str] = "source-asset/v3-internal-v1"

    contract_version: str
    workspace: str
    source_asset_id: str
    source_hash: dict
    provider_trace: list
    produced_by_step: str
    asset_id: str
    collection_id: str
    game_profile: str
    source_kind: str
    mime_type: str
    content_hash: dict
    byte_size: int
    original_name: str
    original_location: str
    created_at: str
    ingested_at: str
    language_hint: Optional[str]
    privacy_class: str
    copyright_class: str
    processing_policy: dict
    metadata: Optional[dict[str, Any]] = None

    def allows_external_providers(self) -> bool:
        """True solo si la politica del asset permite exponerlo a un proveedor remoto."""
        return bool(self.processing_policy.get("allow_external_providers"))
