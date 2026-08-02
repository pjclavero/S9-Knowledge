# -*- coding: utf-8 -*-
"""Puente ledger -> motor: dos tipos con el mismo nombre y ningun adaptador.

DEFECTO DE SUBSISTEMA QUE ESTE MODULO RODEA (ver docs/v3/11-e2e.md, D-1)
-----------------------------------------------------------------------
Hay DOS clases llamadas `GraphSnapshot` y no son compatibles:

  * `engine/snapshot.py:106`  — Protocol de CONSULTA SEMANTICA. El motor le
    pregunta `entity(id) -> SnapshotEntity`, `assertions_for_pair(a, b)` y
    `assertions_for_subject(id, predicado)`.
  * `ledger/snapshots.py:48`  — dataclass de CONTABILIDAD. Guarda
    `(item_id, version, hash)` por afirmacion y por entidad para el control
    optimista, y su `entity(id)` devuelve un `VersionedItem`.

No existe adaptador entre ambos en el repositorio. Y es peor que una simple
ausencia: el snapshot del ledger tiene `snapshot_id`, `workspace` y `entity()`,
asi que `isinstance(snap, engine.GraphSnapshot)` con un Protocol
`@runtime_checkable` SALE VERDADERO —los Protocol solo comprueban nombres, no
firmas— y el motor lo aceptaria para reventar despues, o peor, para leer un
`VersionedItem` alli donde espera un `SnapshotEntity` con `entity_type`.

`ledger.snapshot()` es ademas la unica fuente legitima del `snapshot_id` que
acaba anclando el `GraphMutationPlan` y que el operador debe declarar al
writer. Asi que la cadena necesita las dos mitades: el id y el hash vienen del
ledger, y el contenido consultable se materializa desde `project()`, que es la
proyeccion semantica que el ledger si publica.

Este modulo no decide nada: copia campos entre dos representaciones del mismo
hecho. Las entidades no salen del ledger (el ledger solo conoce afirmaciones)
sino del catalogo del workspace, que es el estado previo del grafo.
"""
from __future__ import annotations

from typing import Iterable, Optional

from ..engine.snapshot import (
    InMemoryGraphSnapshot,
    SnapshotAssertion,
    SnapshotEntity,
)
from ..ledger.assertions import TemporalLedger
from ..ledger.projection import ProjectedEdge, project


def assertion_from_edge(edge: ProjectedEdge, state_hash: dict) -> SnapshotAssertion:
    """`ProjectedEdge` (ledger) -> `SnapshotAssertion` (motor). Copia, no criterio.

    El hash no se recalcula desde la proyeccion degradada: viene del snapshot
    sellado del ledger, que lo deriva del documento autoritativo completo.
    """
    return SnapshotAssertion(
        assertion_id=edge.assertion_id,
        subject_entity_id=edge.subject_entity_id,
        object_entity_id=edge.object_entity_id,
        predicate=edge.predicate,
        direction=edge.direction,
        negated=edge.negated,
        status=edge.status,
        state=edge.state,
        version=edge.revision,
        valid_from=edge.valid_from,
        valid_to=edge.valid_to,
        confidence=edge.confidence,
        state_hash=dict(state_hash),
    )


def engine_snapshot(
    ledger: TemporalLedger,
    *,
    entities: Iterable[SnapshotEntity] = (),
    as_of: Optional[str] = None,
) -> InMemoryGraphSnapshot:
    """Snapshot consultable por el motor, anclado al `snapshot_id` del ledger.

    `as_of` viaja al ledger tal cual: el corte temporal es suyo, no de aqui.
    `include_negated`/`include_conflicted` se dejan en su valor por defecto
    (ambos True) porque el motor NECESITA ver las negadas y las en conflicto:
    `SnapshotAssertion.blocks_new_claims()` existe precisamente para eso, y
    filtrarlas aqui le escondería al motor los conflictos que debe detectar.
    """
    view = ledger.view(as_of)
    sealed = ledger.snapshot(as_of)
    edges = project(view)
    assertion_hashes = {item.item_id: item.hash for item in sealed.assertions}
    return InMemoryGraphSnapshot.build(
        snapshot_id=sealed.snapshot_id,
        workspace=sealed.workspace,
        entities=entities,
        assertions=[
            assertion_from_edge(e, assertion_hashes[e.assertion_id])
            for e in edges
        ],
    )


def entities_from_catalog(catalog_entries: Iterable[dict]) -> list[SnapshotEntity]:
    """Entidades ya existentes en el grafo, tal y como las declara el catalogo.

    El catalogo es estado previo del mundo, no respuesta: sin el, ninguna
    entidad existe en el snapshot y el motor rechaza todo por
    `ENTITY_NOT_IN_SNAPSHOT`. `version` arranca en 1 y `state_hash` se deriva,
    que es lo que el plan copia a `expected_version`/`expected_hash`.
    """
    out: list[SnapshotEntity] = []
    for entry in catalog_entries:
        if entry.get("provisional"):
            continue
        out.append(
            SnapshotEntity.of(
                entry["entity_id"],
                entry["type"],
                int(entry.get("version", 1)),
            )
        )
    return sorted(out, key=lambda e: e.entity_id)


__all__ = ["assertion_from_edge", "engine_snapshot", "entities_from_catalog"]
