# -*- coding: utf-8 -*-
"""`claim-proposal/v3-internal-v1`: afirmacion PROPUESTA por un extractor.

Cualquier proveedor (determinista, Ollama, externo, visual, tablas, eventos,
temporalidad) puede producir un `ClaimProposal`. Ninguno puede convertirlo en
escritura: eso solo lo hace el motor local a traves de un `GraphMutationPlan`.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Optional

from .base import V3Document, producing_step


class EpistemicStatusHint(str, Enum):
    """Pista epistemica del extractor.

    Los cuatro primeros valores son IDENTICOS a
    `relations.contracts.EpistemicStatus`. `VISUAL_INFERRED` es exclusivo de V3
    y NO existe en `relation-candidate/internal-v1`: el adaptador lo degrada.
    """

    ASSERTED = "ASSERTED"
    RUMORED = "RUMORED"
    HYPOTHETICAL = "HYPOTHETICAL"
    INTENDED = "INTENDED"
    VISUAL_INFERRED = "VISUAL_INFERRED"


@dataclass
class ClaimProposal(V3Document):
    """No decide el predicado canonico ni la identidad. Puede abstenerse."""

    CONTRACT_ID: ClassVar[str] = "claim-proposal/v3-internal-v1"

    contract_version: str
    workspace: str
    source_asset_id: str
    source_hash: dict
    provider_trace: list
    produced_by_step: str
    claim_id: str
    episode_id: str
    subject_mentions: list
    relation_phrase: str
    object_mentions: list
    predicate_candidates: list
    direction_candidates: list
    temporal_expressions: list
    negated: bool
    epistemic_cues: list
    epistemic_status_hint: str
    qualifiers: list
    evidence_fragment_ids: list
    confidence: float
    alternatives: list
    abstained: bool
    review_required: bool
    metadata: Optional[dict[str, Any]] = None

    # -- Consultas de conveniencia ----------------------------------------
    def best_predicate(self) -> Optional[str]:
        """Primer predicado candidato (la lista va ordenada por confianza)."""
        return self.predicate_candidates[0]["predicate"] if self.predicate_candidates else None

    def best_direction(self) -> str:
        """Direccion elegida: la primera de la lista.

        La lista esta obligada por contrato a ir en orden canonico (confianza
        descendente, empate por el orden del enum), asi que tomar la primera es
        determinista. `max()` NO lo era: con dos confianzas iguales devolvia la
        que hubiese llegado antes.
        """
        if not self.direction_candidates:
            return "UNDIRECTED"
        return self.direction_candidates[0]["direction"]

    def producing_provider(self) -> dict:
        """Entrada de `provider_trace` senalada por `produced_by_step`.

        Referencia EXPLICITA, no heuristica sobre los nombres de `produced`:
        adivinar el paso productor hacia que una salida externa acabase
        etiquetada como local en cuanto la traza no dijese literalmente "claim".
        """
        return producing_step(self.to_dict())
