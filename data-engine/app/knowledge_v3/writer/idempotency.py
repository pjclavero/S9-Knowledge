# -*- coding: utf-8 -*-
"""Almacen de claves de idempotencia YA APLICADAS.

La idempotencia del contrato es una promesa sobre la CLAVE: la misma operacion
logica calculada en dos planes distintos produce la misma
`idempotency_key`. Cumplirla exige recordar cuales se aplicaron ya, y recordarlo
FUERA del proceso — si el registro vive en memoria, reiniciar el writer convierte
un replay en una doble escritura.

De ahi las dos implementaciones: `InMemoryAppliedKeys` para pruebas y
`JsonlAppliedKeys` para uso real, ambas detras del mismo Protocol para que el
writer no sepa cual tiene.

Registrar se hace DESPUES del commit, nunca antes: si la transaccion se aborta,
la clave no debe quedar marcada como aplicada o la operacion se perderia para
siempre.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol


class AppliedKeyStore(Protocol):
    def is_applied(self, key: str) -> bool: ...

    def record(self, key: str, entry: dict[str, Any]) -> None: ...

    def get(self, key: str) -> Optional[dict[str, Any]]: ...


@dataclass
class InMemoryAppliedKeys:
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)

    def is_applied(self, key: str) -> bool:
        return key in self.entries

    def record(self, key: str, entry: dict[str, Any]) -> None:
        self.entries.setdefault(key, dict(entry))

    def get(self, key: str) -> Optional[dict[str, Any]]:
        entry = self.entries.get(key)
        return dict(entry) if entry is not None else None


class JsonlAppliedKeys:
    """Almacen persistente append-only.

    Guarda ademas el `snapshot_id` del plan que aplico cada clave: eso es el
    testigo externo del requisito R2 del ledger — el `snapshot_id` de un plan
    aplicado queda registrado FUERA del fichero del ledger, que es lo unico que
    delata un truncado del final o la sustitucion del ultimo eslabon.
    """

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._cache: dict[str, dict[str, Any]] | None = None

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._cache is None:
            cache: dict[str, dict[str, Any]] = {}
            if self.path.exists():
                with self.path.open(encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        entry = json.loads(line)
                        cache.setdefault(entry["idempotency_key"], entry)
            self._cache = cache
        return self._cache

    def is_applied(self, key: str) -> bool:
        return key in self._load()

    def record(self, key: str, entry: dict[str, Any]) -> None:
        cache = self._load()
        if key in cache:
            return
        row = dict(entry)
        row["idempotency_key"] = key
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            fh.write("\n")
        cache[key] = row

    def get(self, key: str) -> Optional[dict[str, Any]]:
        entry = self._load().get(key)
        return dict(entry) if entry is not None else None


__all__ = ["AppliedKeyStore", "InMemoryAppliedKeys", "JsonlAppliedKeys"]
