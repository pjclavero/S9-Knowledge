# -*- coding: utf-8 -*-
"""`SignedView`: la unica lectura del plan que el writer usa para decidir.

POR QUE EXISTE
--------------
El contrato congelado dice (schema de `graph-mutation-plan`, campo
`description`) que `created_at`, `plan_id`, `provider_trace` y `metadata` quedan
FUERA del `decision_hash`: son informativos, y alterarlos no rompe ningun hash.
Cualquier decision de escritura basada en ellos seria manipulable sin dejar
rastro.

Prohibirlo con una nota en la documentacion es confiar en que nadie la lea. Aqui
se prohibe con la estructura: la admision construye un `SignedView` que
sencillamente NO CONTIENE esos cuatro campos, y el gate y el ejecutor solo
reciben el view. No es que no deban leerlos: es que no los tienen.

El documento completo sigue llegando al registro de auditoria — ahi si son
utiles, porque la auditoria describe, no decide.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

#: Campos del plan que NO estan cubiertos por `decision_hash` y que, por tanto,
#: no pueden influir en ninguna decision de escritura.
UNSIGNED_FIELDS = frozenset({"created_at", "plan_id", "provider_trace", "metadata"})


@dataclass(frozen=True)
class SignedView:
    """Proyeccion del plan limitada a lo que la firma cubre."""

    workspace: str
    snapshot_id: str
    contract_version: str
    engine_version: str
    ontology_version: str
    game_profile: str
    collection_id: str
    source_asset_id: str
    source_hash: dict
    expires_at: str
    decisions: tuple
    mutation_operations: tuple
    validator_chain: tuple
    approved: bool
    approved_by: dict
    plan_hash: dict
    decision_hash: dict
    #: M3 (docs/v3/49 §2.4): ambito EFECTIVO del plan, ya resuelto entre la
    #: raiz (`partida_id`) y el bloque `scope` -- la admision ya comprobo que
    #: ambos, si estan presentes a la vez, coinciden (`PLAN_SCOPE_CROSS_
    #: PARTIDA`), asi que aqui basta con preferir `scope.partida_id` cuando
    #: existe. `None` significa capa juego, exactamente como antes de M3.
    partida_id: Optional[str] = None

    @classmethod
    def of(cls, doc: dict[str, Any]) -> "SignedView":
        """Construye el view desde el documento ya validado contra el contrato."""
        approval = doc["local_approval"]
        scope = doc.get("scope")
        scope_partida = scope.get("partida_id") if isinstance(scope, dict) else None
        partida_id = scope_partida if scope_partida is not None else doc.get("partida_id")
        return cls(
            partida_id=partida_id,
            workspace=doc["workspace"],
            snapshot_id=doc["snapshot_id"],
            contract_version=doc["contract_version"],
            engine_version=doc["engine_version"],
            ontology_version=doc["ontology_version"],
            game_profile=doc["game_profile"],
            collection_id=doc["collection_id"],
            source_asset_id=doc["source_asset_id"],
            source_hash=dict(doc["source_hash"]),
            expires_at=doc["expires_at"],
            decisions=tuple(doc["decisions"]),
            mutation_operations=tuple(doc["mutation_operations"]),
            validator_chain=tuple(approval["validator_chain"]),
            approved=bool(approval["approved"]),
            approved_by=dict(approval["approved_by"]),
            plan_hash=dict(doc["plan_hash"]),
            decision_hash=dict(approval["decision_hash"]),
        )

    @property
    def plan_hash_value(self) -> str:
        return self.plan_hash["value"]

    def decision_by_id(self, decision_id: str) -> dict:
        for d in self.decisions:
            if d.get("decision_id") == decision_id:
                return d
        raise KeyError(decision_id)


__all__ = ["SignedView", "UNSIGNED_FIELDS"]
