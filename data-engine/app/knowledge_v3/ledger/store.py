# -*- coding: utf-8 -*-
"""Almacenamiento del ledger: interfaz abstracta + dos implementaciones.

El ledger es una ESTRUCTURA LOGICA. Su respaldo en Neo4j (proyeccion de
`FactAssertion` y `SUPERSEDED_BY`) es asunto del writer y de la integracion, no
de este subsistema: aqui no se importa ningun driver de base de datos ni se
abre ninguna conexion. Un ledger que supiera de Neo4j no podria probarse sin
Neo4j, y entonces la garantia de append-only dependeria de un servidor.

Dos implementaciones:

- `InMemoryLedgerStore`: para el motor y para los tests.
- `JsonlLedgerStore`: fichero JSONL append-only, una entrada por linea en JSON
  canonico. Solo se abre en modo `"a"`. No hay ningun metodo que reescriba,
  trunque ni borre; anadir uno seria romper el invariante del subsistema.

Ambos devuelven COPIAS PROFUNDAS de los documentos: quien lee una afirmacion no
puede alterar lo almacenado por descuido, y las pruebas de mutacion lo
comprueban.
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator, List, Sequence

from .entries import LedgerEntry, copy_entry


class LedgerStore(ABC):
    """Almacen append-only de entradas de ledger.

    Contrato: `append` recibe entradas con `seq` estrictamente consecutivo desde
    0. No existe `update`, `delete` ni `truncate`. Lo que entra, se queda.
    """

    @abstractmethod
    def append(self, entry: LedgerEntry) -> None:
        """Anade una entrada al final. Nunca sobrescribe."""

    @abstractmethod
    def read_all(self) -> List[LedgerEntry]:
        """Todas las entradas en orden de `seq`, como copias independientes."""

    def __len__(self) -> int:
        return len(self.read_all())

    def __iter__(self) -> Iterator[LedgerEntry]:
        return iter(self.read_all())

    def last(self) -> LedgerEntry | None:
        entries = self.read_all()
        return entries[-1] if entries else None

    # -- Utilidad comun ----------------------------------------------------
    @staticmethod
    def _check_seq(entry: LedgerEntry, expected_seq: int) -> None:
        if entry.seq != expected_seq:
            raise ValueError(
                f"seq {entry.seq} fuera de orden: el almacen espera {expected_seq}. "
                "Un ledger con huecos o saltos no es una cadena."
            )


class InMemoryLedgerStore(LedgerStore):
    """Almacen en memoria. Guarda y devuelve copias profundas."""

    def __init__(self, entries: Sequence[LedgerEntry] = ()) -> None:
        self._entries: List[LedgerEntry] = []
        for e in entries:
            self.append(e)

    def append(self, entry: LedgerEntry) -> None:
        self._check_seq(entry, len(self._entries))
        # Copia del documento: si el llamante conserva la referencia y la muta
        # despues, el ledger no puede cambiar bajo los pies de nadie.
        self._entries.append(copy_entry(entry))

    def read_all(self) -> List[LedgerEntry]:
        return [copy_entry(e) for e in self._entries]


class JsonlLedgerStore(LedgerStore):
    """Fichero JSONL append-only y determinista.

    Cada linea es el JSON canonico de una entrada. El fichero se abre SIEMPRE en
    modo `"a"`; no existe ninguna ruta de codigo que lo abra en `"w"` ni en
    `"r+"`. El `flush` + `fsync` opcional evita que una caida deje media entrada
    escrita sin que la verificacion de cadena lo note (la notaria: la linea
    truncada no parsea).
    """

    def __init__(self, path: "str | os.PathLike[str]", *, fsync: bool = False) -> None:
        self.path = Path(path)
        self._fsync = fsync
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: LedgerEntry) -> None:
        self._check_seq(entry, len(self.read_all()))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(entry.to_json())
            fh.write("\n")
            fh.flush()
            if self._fsync:
                os.fsync(fh.fileno())

    def read_all(self) -> List[LedgerEntry]:
        if not self.path.exists():
            return []
        out: List[LedgerEntry] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh):
                line = raw.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"{self.path}:{lineno + 1}: linea de ledger ilegible: {exc}"
                    ) from exc
                out.append(LedgerEntry.from_dict(data))
        return out


__all__ = ["InMemoryLedgerStore", "JsonlLedgerStore", "LedgerStore"]
