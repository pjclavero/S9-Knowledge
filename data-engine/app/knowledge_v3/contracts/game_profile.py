# -*- coding: utf-8 -*-
"""`game-profile/v3-internal-v1`: ontologia local por juego.

En V3 inicial todos los workspaces usan `generic`. La arquitectura ya carga
`core ontology + perfil + glosario del workspace`; el adaptador aprendido queda
declarado pero deshabilitado por contrato.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Optional

from .base import V3Document


@dataclass
class GameProfile(V3Document):
    """Un perfil restringe y ordena; en v1 no inventa tipos fuera del catalogo."""

    CONTRACT_ID: ClassVar[str] = "game-profile/v3-internal-v1"
    OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({"metadata", "learned_adapter"})

    contract_version: str
    workspace: str
    source_asset_id: str
    source_hash: dict
    provider_trace: list
    profile_id: str
    profile_version: str
    core_ontology_version: str
    entity_types: list
    predicates: list
    aliases: list
    titles: list
    factions: list
    calendars: list
    identity_rules: list
    ambiguous_terms: list
    source_priorities: list
    evaluation_examples: list
    learned_adapter: Optional[dict] = None
    metadata: Optional[dict[str, Any]] = None

    def predicate_names(self) -> list[str]:
        return [p["predicate"] for p in self.predicates]

    def allows(self, predicate: str, subject_type: str, object_type: str) -> bool:
        """Comprueba dominio/rango de un predicado contra el perfil."""
        for p in self.predicates:
            if p["predicate"] == predicate:
                return subject_type in p["domain"] and object_type in p["range"]
        return False
