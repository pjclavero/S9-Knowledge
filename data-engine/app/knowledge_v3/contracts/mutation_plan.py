# -*- coding: utf-8 -*-
"""`graph-mutation-plan/v3-internal-v1`: UNICA entrada admisible del writer.

VERIFICABLE, NO CONFIABLE
-------------------------
`plan_hash` y `decision_hash` son sha256 SIN clave. Detectan manipulacion
accidental, ediciones parciales y desincronizacion entre firma y contenido —
que es la clase de fallo que de verdad ocurre— pero **no autentican al
firmante**: quien pueda reescribir el documento puede volver a sellarlo. Que
`approved_by.provider` sea `const: "local"` invalida un plan que se declare
firmado por Ollama o por un externo, pero no impide que alguien con acceso de
escritura se declare local.

La garantia real hoy es la cadena de custodia: el plan no sale del proceso
local. Para autenticacion criptografica se han RESERVADO ya
`local_approval.signature` y `local_approval.key_id`, opcionales y sin usar, de
modo que anadir firma no exija romper un contrato congelado.

Lo que el writer exige y este contrato SI garantiza (dosier 13.2 y 18.8):

  * `plan_hash`       — sha256 del plan canonico sin ese campo.
  * `decision_hash`   — cubre tambien `approved`, `approved_by`,
    `validator_chain` y `expires_at`: todo lo que el writer consume para
    decidir si aplica.
  * `contract_version` — mayor no soportada = rechazo.
  * `workspace` y `source_hash` — aislamiento y procedencia; entran en el hash.
  * `snapshot_id`     — ancla del estado sobre el que se calculo el plan.
  * `idempotency_key` — DERIVADA de (workspace + snapshot + identidad logica de
    la operacion), no inventada: la misma operacion en dos planes lleva la
    misma clave y el segundo apply es un no-op.
  * `expected_version` / `expected_hash` por operacion — concurrencia optimista.
  * `expires_at`      — un plan caduca.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Optional

from .base import (
    V3Document,
    compute_decision_hash,
    compute_idempotency_key,
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
    #: M0 (docs/v3/49-multipartida-diseno.md §2.2): `partida_id` y `scope`
    #: son opcionales y se omiten del documento serializado cuando valen
    #: `None`, igual que `metadata` — el material existente sigue siendo
    #: byte-identico.
    #:
    #: VERIFICACION DEL HASH (no asumida): `partida_id`/`scope` SI entran en
    #: `plan_hash` gratis (cubre el documento completo salvo el propio
    #: `plan_hash`). NO entran en `local_approval.decision_hash`:
    #: `DECISION_HASH_FIELDS` (validator.py) es una lista CURADA y cerrada
    #: de campos, no "todo el documento" — anadir claves ahi habria
    #: cambiado el `decision_hash` esperado de todo plan gold/held-out ya
    #: sellado (`plan.get(k)` para una clave nueva mete `None` en el cuerpo
    #: de planes que nunca declararon `partida_id`), rompiendo datasets que
    #: este bloque tiene prohibido tocar. Revertido deliberadamente: el
    #: agujero (dos planes que solo difieren en ambito comparten
    #: `decision_hash`) queda documentado y pendiente de M3, no cerrado en
    #: M0. Ver docs/v3/49-multipartida-diseno.md, seccion "M0 implementado".
    #:
    #: DECISION DE M3 (docs/v3/49 §9, "M3 implementado"): con
    #: `PLAN_SCOPE_CROSS_PARTIDA` ya implementado en `writer/admission.py`
    #: existe el consumidor real que la politica exigia, pero el hueco de
    #: `decision_hash` se deja ABIERTO deliberadamente (verificado: ningun
    #: plan de los datasets congelados declara `partida_id`/`scope` hoy, el
    #: riesgo real es cero). Ver `validator.py`, junto a
    #: `DECISION_HASH_FIELDS`, para la justificacion completa.
    OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({"metadata", "partida_id", "scope"})

    contract_version: str
    workspace: str
    source_asset_id: str
    source_hash: dict
    provider_trace: list
    produced_by_step: str
    plan_id: str
    plan_hash: dict
    snapshot_id: str
    engine_version: str
    ontology_version: str
    game_profile: str
    collection_id: str
    created_at: str
    expires_at: str
    decisions: list
    mutation_operations: list
    local_approval: dict
    #: M0: ambito de partida (nullable) y bloque de ambito declarado del
    #: plan (docs/v3/49-multipartida-diseno.md §2.2). El chequeo de
    #: admision que rechaza cruces de ambito (`PLAN_SCOPE_CROSS_PARTIDA`)
    #: es de M3, no de este bloque: aqui el campo solo viaja y queda
    #: cubierto por la firma.
    partida_id: Optional[str] = None
    scope: Optional[dict] = None
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
        """El firmante DECLARADO es el motor local.

        Es una comprobacion de coherencia, no de autenticidad: sin
        `signature`/`key_id` nadie puede demostrar quien lo escribio.
        """
        return self.local_approval.get("approved_by", {}).get("provider") == "local"

    def is_authenticated(self) -> bool:
        """True solo si el plan lleva firma criptografica y su identificador.

        Hoy devuelve False siempre: los campos estan reservados y sin usar. Se
        expone para que ningun consumidor confunda "hash correcto" con "firmado".
        """
        return bool(self.local_approval.get("signature")) and bool(
            self.local_approval.get("key_id")
        )

    def expected_idempotency_keys(self) -> list[str]:
        """Claves derivadas de las operaciones, para contrastarlas con las declaradas."""
        doc = self.to_dict()
        return [compute_idempotency_key(doc, o) for o in self.mutation_operations]

    def idempotency_keys(self) -> list[str]:
        return [o["idempotency_key"] for o in self.mutation_operations]
