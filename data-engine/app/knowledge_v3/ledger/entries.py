# -*- coding: utf-8 -*-
"""Entrada del ledger: el eslabon inmutable de la cadena de custodia.

Una entrada NUNCA se modifica. Un cambio de estado de una afirmacion no reescribe
la entrada anterior: anade una nueva entrada con la REVISION siguiente del mismo
`assertion_id`. La entrada vieja sigue ahi, legible y hasheada, para siempre.

Cada entrada encadena la anterior por `prev_hash`, como un log de bloques: editar
una entrada antigua invalida su `entry_hash` y, con el, el `prev_hash` de todas
las posteriores. No hay forma de retocar el pasado sin recalcular el ledger
entero, y `verify_chain()` lo detecta de todos modos porque recalcula desde el
genesis.

`entry_hash` NO se calcula en la serializacion: es un dato de la entrada,
calculado una sola vez al crearla, con `canonical_json` (bytes estables).
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from ..contracts import canonical_json

#: `prev_hash` de la primera entrada. No es un hash real: es el ancla del
#: genesis, y por eso es reconocible a simple vista.
GENESIS_HASH = "0" * 64


class LedgerOperation(str, Enum):
    """Las CINCO operaciones del ledger. Conjunto cerrado.

    No existe UPDATE ni DELETE, y esa ausencia es el diseno: cualquier cambio
    se expresa como una de estas cinco, todas ellas aditivas.
    """

    ASSERT = "ASSERT"
    CONFIRM = "CONFIRM"
    SUPERSEDE = "SUPERSEDE"
    CONTRADICT = "CONTRADICT"
    RETRACT = "RETRACT"


@dataclass(frozen=True)
class LedgerEntry:
    """Un eslabon del ledger.

    `assertion` es el documento `fact-assertion/v3-internal-v1` COMPLETO tal y
    como queda tras esta operacion. Se guarda entero, no como delta: un delta
    obliga a reconstruir para leer, y una reconstruccion con un bug reescribe la
    historia en silencio.

    `revision` es el numero de version de ESE `assertion_id` (1 = primera). Es
    la version que alimenta la concurrencia optimista del `GraphMutationPlan`.
    """

    seq: int
    entry_id: str
    operation: str
    recorded_at: str
    workspace: str
    assertion_id: str
    revision: int
    assertion: dict
    related_assertion_ids: tuple
    reason_code: str
    prev_hash: str
    entry_hash: str

    # -- Serializacion -----------------------------------------------------
    def body(self) -> dict[str, Any]:
        """Cuerpo hasheable: todo menos el propio `entry_hash`."""
        return {
            "seq": self.seq,
            "entry_id": self.entry_id,
            "operation": self.operation,
            "recorded_at": self.recorded_at,
            "workspace": self.workspace,
            "assertion_id": self.assertion_id,
            "revision": self.revision,
            "assertion": self.assertion,
            "related_assertion_ids": list(self.related_assertion_ids),
            "reason_code": self.reason_code,
            "prev_hash": self.prev_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        out = self.body()
        out["entry_hash"] = self.entry_hash
        return out

    def to_json(self) -> str:
        """Linea JSONL canonica: claves ordenadas, estable byte a byte."""
        return canonical_json(self.to_dict())

    def computed_hash(self) -> str:
        return compute_entry_hash(self.body())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LedgerEntry":
        known = {
            "seq", "entry_id", "operation", "recorded_at", "workspace",
            "assertion_id", "revision", "assertion", "related_assertion_ids",
            "reason_code", "prev_hash", "entry_hash",
        }
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"campos desconocidos en la entrada: {sorted(unknown)}")
        missing = known - set(data)
        if missing:
            raise ValueError(f"faltan campos en la entrada: {sorted(missing)}")
        return cls(
            seq=int(data["seq"]),
            entry_id=str(data["entry_id"]),
            operation=str(data["operation"]),
            recorded_at=str(data["recorded_at"]),
            workspace=str(data["workspace"]),
            assertion_id=str(data["assertion_id"]),
            revision=int(data["revision"]),
            assertion=data["assertion"],
            related_assertion_ids=tuple(data["related_assertion_ids"]),
            reason_code=str(data["reason_code"]),
            prev_hash=str(data["prev_hash"]),
            entry_hash=str(data["entry_hash"]),
        )


def copy_entry(entry: LedgerEntry) -> LedgerEntry:
    """Copia independiente de una entrada, con el documento clonado a fondo.

    `LedgerEntry` es `frozen`, pero eso solo congela las REFERENCIAS: el dict
    `assertion` sigue siendo mutable. Compartir ese dict entre el almacen, la
    cache y el valor devuelto convierte la inmutabilidad en una promesa vacia —
    quien reciba la entrada puede reescribir el pasado del ledger sin tocar
    ningun hash, porque el hash ya estaba calculado.

    Por eso toda entrada cruza cualquier frontera (almacen, cache, retorno) como
    COPIA.
    """
    return LedgerEntry(
        seq=entry.seq,
        entry_id=entry.entry_id,
        operation=entry.operation,
        recorded_at=entry.recorded_at,
        workspace=entry.workspace,
        assertion_id=entry.assertion_id,
        revision=entry.revision,
        assertion=deepcopy(entry.assertion),
        related_assertion_ids=tuple(entry.related_assertion_ids),
        reason_code=entry.reason_code,
        prev_hash=entry.prev_hash,
        entry_hash=entry.entry_hash,
    )


def compute_entry_hash(body: dict[str, Any]) -> str:
    """sha256 del JSON canonico del cuerpo de la entrada (sin `entry_hash`)."""
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def entry_id_for(workspace: str, seq: int) -> str:
    """Identificador determinista de entrada. Cumple `stable_id` del contrato."""
    return f"ledger:{workspace}:{seq:08d}"


def make_entry(
    *,
    seq: int,
    operation: "LedgerOperation | str",
    recorded_at: str,
    workspace: str,
    assertion: dict,
    revision: int,
    reason_code: str,
    prev_hash: str,
    related_assertion_ids: Optional[tuple] = None,
) -> LedgerEntry:
    """Construye una entrada sellada. Funcion pura: sin reloj y sin E/S."""
    op = operation.value if isinstance(operation, LedgerOperation) else str(operation)
    related = tuple(related_assertion_ids or ())
    body = {
        "seq": seq,
        "entry_id": entry_id_for(workspace, seq),
        "operation": op,
        "recorded_at": recorded_at,
        "workspace": workspace,
        "assertion_id": assertion["assertion_id"],
        "revision": revision,
        "assertion": assertion,
        "related_assertion_ids": list(related),
        "reason_code": reason_code,
        "prev_hash": prev_hash,
    }
    return LedgerEntry(
        seq=seq,
        entry_id=body["entry_id"],
        operation=op,
        recorded_at=recorded_at,
        workspace=workspace,
        assertion_id=assertion["assertion_id"],
        revision=revision,
        assertion=assertion,
        related_assertion_ids=related,
        reason_code=reason_code,
        prev_hash=prev_hash,
        entry_hash=compute_entry_hash(body),
    )


__all__ = [
    "GENESIS_HASH",
    "LedgerEntry",
    "LedgerOperation",
    "compute_entry_hash",
    "copy_entry",
    "entry_id_for",
    "make_entry",
]
