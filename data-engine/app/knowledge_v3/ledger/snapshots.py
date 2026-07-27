# -*- coding: utf-8 -*-
"""`GraphSnapshot`: ancla consistente del estado del conocimiento.

Es lo que el motor cita en `graph-mutation-plan/v3-internal-v1.snapshot_id` y lo
que da sentido a `expected_version`/`expected_hash`: sin un ancla, «la version
esperada» es una afirmacion sobre un grafo que ya nadie sabe cual era, y dos
planes concurrentes no se pueden ordenar.

`snapshot_id` es el HASH DEL CONTENIDO, no un contador ni una fecha:

    snapshot:sha256:<64 hex de sha256(canonical_json(contenido))>

Consecuencia deliberada: dos snapshots con el mismo estado tienen el MISMO id
aunque se tomen en momentos distintos. Es lo correcto para concurrencia
optimista — si nada ha cambiado, el plan sigue siendo aplicable — y por eso
`as_of` es metadato del snapshot y no entra en el hash.

Las versiones por entidad cubren afirmaciones VIVAS Y NO VIVAS. Si una
supersesion no moviera la version de la entidad, un plan calculado antes de esa
supersesion pasaria el control optimista y escribiria sobre un estado que ya no
existe: exactamente el fallo que la concurrencia optimista debe impedir.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..contracts import canonical_json, sha256_hash
from .temporal import LedgerView

SNAPSHOT_ID_PREFIX = "snapshot:sha256:"


@dataclass(frozen=True)
class VersionedItem:
    """Version y hash de un elemento del snapshot (entidad o afirmacion)."""

    item_id: str
    version: int
    hash: dict

    def as_expected(self) -> Tuple[int, dict]:
        """Par `(expected_version, expected_hash)` para el plan de mutacion."""
        return self.version, dict(self.hash)


@dataclass(frozen=True)
class GraphSnapshot:
    """Estado materializado y sellado del ledger."""

    snapshot_id: str
    workspace: str
    as_of: Optional[str]
    content_hash: dict
    assertions: Tuple[VersionedItem, ...]
    entities: Tuple[VersionedItem, ...]
    live_assertion_ids: Tuple[str, ...]
    conflicted_assertion_ids: Tuple[str, ...]

    # -- Consulta ----------------------------------------------------------
    def assertion(self, assertion_id: str) -> Optional[VersionedItem]:
        for item in self.assertions:
            if item.item_id == assertion_id:
                return item
        return None

    def entity(self, entity_id: str) -> Optional[VersionedItem]:
        for item in self.entities:
            if item.item_id == entity_id:
                return item
        return None

    def expected_for_entity(self, entity_id: str) -> Tuple[Optional[int], Optional[dict]]:
        """`(expected_version, expected_hash)` de una entidad.

        `(None, None)` si la entidad no existe en el snapshot: es exactamente lo
        que el contrato exige declarar en una operacion de creacion.
        """
        item = self.entity(entity_id)
        return item.as_expected() if item else (None, None)

    def expected_for_assertion(self, assertion_id: str) -> Tuple[Optional[int], Optional[dict]]:
        item = self.assertion(assertion_id)
        return item.as_expected() if item else (None, None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "workspace": self.workspace,
            "as_of": self.as_of,
            "content_hash": dict(self.content_hash),
            "assertions": [
                {"assertion_id": i.item_id, "version": i.version, "hash": dict(i.hash)}
                for i in self.assertions
            ],
            "entities": [
                {"entity_id": i.item_id, "version": i.version, "hash": dict(i.hash)}
                for i in self.entities
            ],
            "live_assertion_ids": list(self.live_assertion_ids),
            "conflicted_assertion_ids": list(self.conflicted_assertion_ids),
        }


def build_snapshot(view: LedgerView, *, workspace: str) -> GraphSnapshot:
    """Materializa un `GraphSnapshot` determinista a partir de una vista.

    Determinismo: todo va ordenado por identificador y serializado con
    `canonical_json`. Dos ledgers con el mismo contenido producen el mismo
    `snapshot_id` aunque las entradas se hayan escrito en ficheros distintos.
    """
    records = view.records()

    assertions: List[VersionedItem] = [
        VersionedItem(
            item_id=r.assertion_id,
            version=r.revision,
            hash=sha256_hash(r.document),
        )
        for r in records
    ]

    # Version de entidad = suma de revisiones de las afirmaciones que la tocan.
    # Cualquier operacion sobre cualquiera de ellas la incrementa, que es la
    # propiedad que necesita el control optimista.
    per_entity: Dict[str, List[Tuple[str, int, str]]] = {}
    for r in records:
        for key in ("subject_entity_id", "object_entity_id"):
            eid = r.document[key]
            per_entity.setdefault(eid, []).append(
                (r.assertion_id, r.revision, str(r.document["status"]))
            )

    entities: List[VersionedItem] = []
    for eid in sorted(per_entity):
        rows = sorted(per_entity[eid])
        entities.append(
            VersionedItem(
                item_id=eid,
                version=sum(rev for _, rev, _ in rows),
                hash=sha256_hash([list(row) for row in rows]),
            )
        )

    content = {
        "workspace": workspace,
        "assertions": [
            {"assertion_id": i.item_id, "version": i.version, "hash": i.hash}
            for i in assertions
        ],
        "entities": [
            {"entity_id": i.item_id, "version": i.version, "hash": i.hash}
            for i in entities
        ],
    }
    content_hash = sha256_hash(content)
    return GraphSnapshot(
        snapshot_id=SNAPSHOT_ID_PREFIX + content_hash["value"],
        workspace=workspace,
        as_of=view.as_of,
        content_hash=content_hash,
        assertions=tuple(assertions),
        entities=tuple(entities),
        live_assertion_ids=tuple(r.assertion_id for r in view.live()),
        conflicted_assertion_ids=tuple(r.assertion_id for r in view.conflicted()),
    )


def snapshot_content_json(snapshot: GraphSnapshot) -> str:
    """JSON canonico del snapshot. Util para diagnosticar dos ids distintos."""
    return canonical_json(snapshot.to_dict())


__all__ = [
    "SNAPSHOT_ID_PREFIX",
    "GraphSnapshot",
    "VersionedItem",
    "build_snapshot",
    "snapshot_content_json",
]
