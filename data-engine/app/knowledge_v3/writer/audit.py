# -*- coding: utf-8 -*-
"""Registro de auditoria append-only del writer (JSONL).

Se registra TODO intento: aceptado, rechazado en admision, bloqueado por el
gate, abortado a mitad. Un log que solo guarda los exitos no es auditoria, es
propaganda.

Append-only de verdad: se abre siempre en modo `"a"` y no hay ninguna funcion
que reescriba, trunque ni borre. No es a prueba de un atacante con permiso de
escritura sobre el fichero — no lo finge —; es a prueba del propio writer.

Aqui SI aparecen los campos que el `SignedView` niega al resto del writer
—`created_at`, `plan_id`, `provider_trace`, `metadata`— y aparecen de verdad, en
el bloque `unsigned` de cada linea. Esa es justamente la justificacion del
`SignedView`: describir sin decidir. Si la auditoria tampoco los conservara, el
argumento seria «no los usamos» en vez de «los usamos solo para contar lo que
paso», y se perderia la unica traza de que un plan venia con una
`provider_trace` sospechosa.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol


@dataclass
class AuditRecord:
    """Una linea del registro. Todo lo necesario para reconstruir un intento."""

    timestamp: str
    outcome: str  # ATTEMPTED | APPLIED | SIMULATED | REJECTED | BLOCKED | ABORTED
    mode: str  # DRY_RUN | APPLY
    workspace: Optional[str]
    operator_id: Optional[str]
    plan_hash: Optional[str]
    snapshot_id: Optional[str]
    plan_id: Optional[str] = None
    rejections: list[dict[str, Any]] = field(default_factory=list)
    applied_operations: int = 0
    noop_operations: int = 0
    created_ids: list[str] = field(default_factory=list)
    #: Los campos que el contrato deja fuera del `decision_hash`. Se guardan
    #: para poder contar lo que paso, jamas para decidir nada.
    unsigned: dict[str, Any] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "outcome": self.outcome,
            "mode": self.mode,
            "workspace": self.workspace,
            "operator_id": self.operator_id,
            "plan_hash": self.plan_hash,
            "snapshot_id": self.snapshot_id,
            "plan_id": self.plan_id,
            "rejections": self.rejections,
            "applied_operations": self.applied_operations,
            "noop_operations": self.noop_operations,
            "created_ids": self.created_ids,
            "unsigned": self.unsigned,
            "detail": self.detail,
        }


class AuditSink(Protocol):
    """Destino del registro. Inyectable: en tests, en memoria."""

    def available(self) -> bool: ...

    def append(self, record: AuditRecord) -> None: ...

    def read_all(self) -> list[dict[str, Any]]: ...


@dataclass
class InMemoryAuditSink:
    """Sink de pruebas. Guarda en una lista; `available` configurable."""

    records: list[dict[str, Any]] = field(default_factory=list)
    _available: bool = True

    def available(self) -> bool:
        return self._available

    def append(self, record: AuditRecord) -> None:
        self.records.append(record.to_dict())

    def read_all(self) -> list[dict[str, Any]]:
        return list(self.records)


class JsonlAuditSink:
    """Sink real: una linea JSON por intento, en modo append."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)

    def available(self) -> bool:
        """True si el directorio existe (o se puede crear) y se puede escribir."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        if self.path.exists():
            return os.access(self.path, os.W_OK)
        return os.access(self.path.parent, os.W_OK)

    def append(self, record: AuditRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True))
            fh.write("\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out


__all__ = ["AuditRecord", "AuditSink", "InMemoryAuditSink", "JsonlAuditSink"]
