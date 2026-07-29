# -*- coding: utf-8 -*-
"""Proyeccion del ledger a aristas directas.

Regla del dosier (12.1), literal: *la fuente autoritativa sigue siendo
`FactAssertion`*. La arista directa `(A)-[PREDICATE]->(B)` es una PROYECCION de
conveniencia para consultar y para pintar el grafo; nunca es la verdad. Por eso
toda arista proyectada arrastra su `assertion_id`, su revision y sus ejes
temporales: quien la lea puede volver siempre a la afirmacion que la sostiene.

Este modulo no escribe en Neo4j. Produce estructuras planas; materializarlas es
trabajo del writer, y solo a traves de un `GraphMutationPlan` firmado.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .temporal import LedgerView
from .timeline import in_validity_interval


@dataclass(frozen=True)
class ProjectedEdge:
    """Arista derivada de una afirmacion viva. Copia degradada, no autoridad."""

    subject_entity_id: str
    predicate: str
    object_entity_id: str
    direction: str
    assertion_id: str
    revision: int
    status: str
    epistemic_status: str
    confidence: float
    negated: bool
    valid_from: Optional[str]
    valid_to: Optional[str]
    event_time: Optional[str]
    state: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subject_entity_id": self.subject_entity_id,
            "predicate": self.predicate,
            "object_entity_id": self.object_entity_id,
            "direction": self.direction,
            "assertion_id": self.assertion_id,
            "revision": self.revision,
            "status": self.status,
            "epistemic_status": self.epistemic_status,
            "confidence": self.confidence,
            "negated": self.negated,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "event_time": self.event_time,
            "state": self.state,
        }


def project(
    view: LedgerView,
    *,
    world_time: Optional[str] = None,
    include_negated: bool = True,
    include_conflicted: bool = True,
    include_unknown_start: bool = False,
) -> List[ProjectedEdge]:
    """Proyecta las afirmaciones vivas de una vista a aristas.

    `include_negated` por defecto es True: una negacion («X NO es miembro de Y»)
    es conocimiento, y filtrarla en silencio haria que el grafo pareciese
    ignorar el hecho en vez de afirmar lo contrario. Quien pinte el grafo decide
    como representarla, pero la recibe.

    `include_conflicted` tambien por defecto True, por el mismo motivo: ocultar
    un conflicto no lo resuelve, lo esconde.
    """
    edges: List[ProjectedEdge] = []
    for rec in view.live():
        doc = rec.stored_document
        if not include_negated and doc["negated"]:
            continue
        if not include_conflicted and doc["status"] == "CONTRADICTED":
            continue
        if world_time is not None and not in_validity_interval(
            world_time,
            doc.get("valid_from"),
            doc.get("valid_to"),
            include_unknown_start=include_unknown_start,
        ):
            continue
        edges.append(
            ProjectedEdge(
                subject_entity_id=doc["subject_entity_id"],
                predicate=doc["predicate"],
                object_entity_id=doc["object_entity_id"],
                direction=doc["direction"],
                assertion_id=doc["assertion_id"],
                revision=rec.revision,
                status=doc["status"],
                epistemic_status=doc["epistemic_status"],
                confidence=doc["confidence"],
                negated=doc["negated"],
                valid_from=doc.get("valid_from"),
                valid_to=doc.get("valid_to"),
                event_time=doc.get("event_time"),
                state=doc["state"],
            )
        )
    edges.sort(
        key=lambda e: (e.subject_entity_id, e.predicate, e.object_entity_id, e.assertion_id)
    )
    return edges


__all__ = ["ProjectedEdge", "project"]
