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
    #: M4 (docs/v3/49-multipartida-diseno.md §2.5): `local_override_of` se
    #: une a `calendar_id`/`metadata` en el mismo patron aditivo de M0/M2 --
    #: campo opcional, se omite del documento serializado cuando vale
    #: `None`, el material existente sigue siendo byte-identico.
    OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset(
        {"metadata", "calendar_id", "local_override_of"}
    )

    contract_version: str
    workspace: str
    source_asset_id: str
    source_hash: dict
    provider_trace: list
    produced_by_step: str
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
    state: str
    event_time: Optional[str]
    negated: bool
    collection_id: str
    game_profile: str
    engine_version: str
    ontology_version: str
    evidence_fragment_ids: list
    episode_ids: list
    supersedes: Optional[str]
    superseded_by: Optional[str]
    calendar_id: Optional[str] = None
    #: M4: puntero NO DESTRUCTIVO a la afirmacion de CAPA JUEGO de la que esta
    #: afirmacion (siempre de partida) diverge. A diferencia de `supersedes`/
    #: `superseded_by`, jamas provoca una mutacion en el documento apuntado:
    #: el hecho de capa juego no gana `status`, ni `superseded_by`, ni
    #: `valid_to` por el mero hecho de ser apuntado. Ver docs/v3/49 §2.5 y
    #: "M4 implementado".
    local_override_of: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None

    def is_open_interval(self) -> bool:
        """True si la afirmacion sigue vigente (sin `valid_to`)."""
        return self.valid_to is None
