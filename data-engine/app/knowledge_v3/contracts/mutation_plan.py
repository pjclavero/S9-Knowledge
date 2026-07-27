# -*- coding: utf-8 -*-
"""`graph-mutation-plan/v3-internal-v1`: UNICA entrada admisible del writer.

Lo que el writer exige y este contrato garantiza (dosier 13.2 y 18.8):

  * `plan_hash`      — sha256 del plan canonico sin ese campo. Detecta cualquier
    manipulacion posterior (workspace, source hash, operacion, decision).
  * `contract_version` — mayor no soportada = rechazo.
  * `workspace`      — aislamiento duro; entra en la firma.
  * `source_hash`    — procedencia; entra en la firma.
  * `local_approval` — `approved`, `decision_hash`, cadena de validadores y
    `approved_by.provider == "local"`. Un plan firmado por un proveedor externo
    es invalido POR CONTRATO, no por politica configurable.
  * `idempotency_key` por operacion, unica dentro del plan.
  * `expires_at`     — un plan caduca.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Optional

from .base import (
    V3Document,
    compute_decision_hash,
    compute_plan_hash,
    seal_plan,
)


class EngineDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT_INVALID = "REJECT_INVALID"
    ABSTAIN = "ABSTAIN"
    REVIEW = "REVIEW"


class MutationOperationType(str, Enum):
    CREATE_ENTITY = "CREATE_ENTITY"
    UPDATE_ENTITY = "UPDATE_ENTITY"
    LINK_EXISTING = "LINK_EXISTING"
    CREATE_ASSERTION = "CREATE_ASSERTION"
    SUPERSEDE_ASSERTION = "SUPERSEDE_ASSERTION"
    PROJECT_RELATION = "PROJECT_RELATION"


@dataclass
class GraphMutationPlan(V3Document):
    """Plan local firmado. El writer no interpreta: solo ejecuta o rechaza."""

    CONTRACT_ID: ClassVar[str] = "graph-mutation-plan/v3-internal-v1"

    contract_version: str
    workspace: str
    source_asset_id: str
    source_hash: dict
    provider_trace: list
    plan_id: str
    plan_hash: dict
    engine_version: str
    ontology_version: str
    game_profile: str
    collection_id: str
    created_at: str
    expires_at: str
    decisions: list
    mutation_operations: list
    local_approval: dict
    metadata: Optional[dict[str, Any]] = None

    # -- Firma -------------------------------------------------------------
    def sealed(self) -> "GraphMutationPlan":
        """Copia del plan con `decision_hash` y `plan_hash` recalculados.

        No muta el objeto original: sellar es producir un plan nuevo.
        """
        return type(self).from_dict(seal_plan(self.to_dict()), validate=False)

    def expected_decision_hash(self) -> dict:
        return compute_decision_hash(self.to_dict())

    def expected_plan_hash(self) -> dict:
        return compute_plan_hash(self.to_dict())

    def signature_is_intact(self) -> bool:
        """True si ambos hashes corresponden al contenido actual del plan."""
        doc = self.to_dict()
        return (
            self.local_approval.get("decision_hash") == compute_decision_hash(doc)
            and self.plan_hash == compute_plan_hash(doc)
        )

    # -- Consultas ---------------------------------------------------------
    @property
    def approved(self) -> bool:
        return bool(self.local_approval.get("approved"))

    def signed_locally(self) -> bool:
        """El firmante debe ser el motor local; jamas ollama ni un externo."""
        return self.local_approval.get("approved_by", {}).get("provider") == "local"

    def idempotency_keys(self) -> list[str]:
        return [o["idempotency_key"] for o in self.mutation_operations]
