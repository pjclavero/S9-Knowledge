# -*- coding: utf-8 -*-
"""Rollback: lo que se deshace despues del commit.

Hay dos cosas distintas que la palabra «rollback» suele mezclar, y aqui NO se
mezclan:

* **Aborto a mitad** — lo resuelve la transaccion: si algo falla, no se escribe
  nada. No hace falta deshacer, porque no se hizo. Lo cubre `executor.py`.
* **Deshacer un plan YA confirmado** — eso ya no es transaccional: hay datos en
  el grafo. Esto es lo que genera este modulo.

Y lo genera como INSTRUCCIONES, no como ejecucion. El writer no borra por su
cuenta lo que escribio: deshacer es una decision de operador, y ademas las
instrucciones inversas incluyen borrados, que es exactamente lo que este
subsistema tiene prohibido hacer sin plan. Lo que sale de aqui es un documento
que un operador lee, aprueba y aplica — o convierte en un plan inverso que el
motor local vuelva a sellar.

Limite dicho sin adornos: el rollback de un cierre de vigencia solo puede
restaurar `version` y `state_hash`, que es lo que el writer leyo antes de
escribir. Las propiedades previas que no leyo no las puede devolver. Restaurar
un estado completo exigiria leerlo entero antes de cada cierre, y eso no esta
hecho.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .executor import AppliedOperation
from .view import SignedView


@dataclass
class RollbackInstruction:
    """Una accion inversa. Descriptiva: nadie la ejecuta automaticamente."""

    operation_id: str
    action: str  # DELETE_NODE | DELETE_RELATIONSHIP | RESTORE_PROPERTIES
    target_id: str | None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "action": self.action,
            "target_id": self.target_id,
            "detail": dict(self.detail),
        }


@dataclass
class RollbackDocument:
    workspace: str
    snapshot_id: str
    plan_hash: str
    instructions: list[RollbackInstruction] = field(default_factory=list)
    unrecoverable: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "snapshot_id": self.snapshot_id,
            "plan_hash": self.plan_hash,
            "instructions": [i.to_dict() for i in self.instructions],
            "unrecoverable": list(self.unrecoverable),
        }


def build_rollback(
    view: SignedView, applied: Iterable[AppliedOperation]
) -> RollbackDocument:
    """Instrucciones para deshacer lo que ESTE writer escribio, en orden inverso.

    Orden inverso a proposito: las aristas se borran antes que los nodos que
    unen, o el borrado del nodo tropieza con la arista.
    """
    doc = RollbackDocument(
        workspace=view.workspace,
        snapshot_id=view.snapshot_id,
        plan_hash=view.plan_hash_value,
    )
    for op in reversed(list(applied)):
        if op.kind == "NODE":
            doc.instructions.append(
                RollbackInstruction(
                    operation_id=op.operation_id,
                    action="DELETE_NODE",
                    target_id=op.target_id,
                    detail={
                        "created_id": op.created_id,
                        "workspace": view.workspace,
                        "idempotency_key": op.idempotency_key,
                    },
                )
            )
        elif op.kind == "RELATIONSHIP":
            doc.instructions.append(
                RollbackInstruction(
                    operation_id=op.operation_id,
                    action="DELETE_RELATIONSHIP",
                    target_id=op.created_id,
                    detail={
                        "subject": op.target_id,
                        "workspace": view.workspace,
                        "idempotency_key": op.idempotency_key,
                    },
                )
            )
        elif op.kind == "PROPERTIES":
            doc.instructions.append(
                RollbackInstruction(
                    operation_id=op.operation_id,
                    action="RESTORE_PROPERTIES",
                    target_id=op.target_id,
                    detail={
                        "restore": op.previous_state or {},
                        "changed": dict(op.changed_props),
                        "workspace": view.workspace,
                        "idempotency_key": op.idempotency_key,
                    },
                )
            )
            missing = sorted(set(op.changed_props) - set(op.previous_state or {}))
            if missing:
                doc.unrecoverable.append(
                    f"{op.operation_id}: no se leyo el valor previo de {missing}"
                )
        else:  # SIMULATED u otro: no escribio nada, no hay nada que deshacer.
            continue
    return doc


__all__ = ["RollbackInstruction", "RollbackDocument", "build_rollback"]
