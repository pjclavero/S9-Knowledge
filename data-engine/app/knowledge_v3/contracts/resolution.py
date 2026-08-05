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
    #: M2 (docs/v3/49-multipartida-diseno.md): `partida_id` opcional, mismo
    #: criterio aditivo que M0 (base.py) — sin bump de contract_version.
    OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({"metadata", "split_groups", "partida_id"})

    contract_version: str
    workspace: str
    source_asset_id: str
    source_hash: dict
    provider_trace: list
    produced_by_step: str
    resolution_id: str
    mention_ids: list
    candidate_entity_ids: list
    selected_entity_id: Optional[str]
    assigned_entity_id: Optional[str]
    action: str
    entity_type: Optional[str]
    confidence: float
    evidence: list
    reason_codes: list
    game_profile: str
    split_groups: Optional[list] = None
    metadata: Optional[dict[str, Any]] = None
    partida_id: Optional[str] = None

    def is_provisional(self) -> bool:
        return self.action == ResolutionAction.CREATE_PROVISIONAL.value

    def entity_id(self) -> Optional[str]:
        """Identidad fijada por esta resolucion, o None si no fija ninguna.

        `LINK_EXISTING` devuelve la entidad enlazada; `CREATE_NEW` y
        `CREATE_PROVISIONAL` devuelven el id ASIGNADO por el resolutor — quien
        crea la identidad es quien la nombra, no una convencion de cadena
        inventada aguas abajo. `SPLIT` y `REVIEW` devuelven None.
        """
        return self.selected_entity_id or self.assigned_entity_id
