"""Instrumentación de medida: envoltorio contador sobre un ``GraphProvider``.

Se interpone ENTRE la cadena de autorización y la fuente de datos: el visor
resuelve ``get_provider`` a este contador y ``PolicyFilteredProvider`` lo
envuelve como envolvería al proveedor real. Así medimos, por petición HTTP:

  * cuántas llamadas hace la aplicación a la fuente de datos (proxy directo del
    número de consultas a Neo4j: cada método del proveedor Neo4j ejecuta entre
    1 y N ``session.run``),
  * cuántas filas materializa (proxy del volumen leído de la base),
  * el desglose por método.

El contador NO modifica resultados ni se salta ninguna validación: delega todo.
"""
from __future__ import annotations

import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.providers.base import GraphProvider

_METODOS = (
    "is_connected", "workspaces", "counts", "entity_types", "search", "graph",
    "entity", "relations_for_entity", "list_entities", "list_sources",
    "source_detail", "quality_metrics",
)


@dataclass
class Muestra:
    """Contadores de una única petición."""
    llamadas: Counter = field(default_factory=Counter)
    filas: Counter = field(default_factory=Counter)

    @property
    def total_llamadas(self) -> int:
        return sum(self.llamadas.values())

    @property
    def total_filas(self) -> int:
        return sum(self.filas.values())


def _contar_filas(resultado: Any) -> int:
    if isinstance(resultado, list):
        return len(resultado)
    if isinstance(resultado, tuple):
        return sum(_contar_filas(x) for x in resultado)
    if isinstance(resultado, dict):
        return 1
    if resultado is None:
        return 0
    return 1


class CountingProvider(GraphProvider):
    """Proxy transparente que cuenta llamadas y filas por método."""

    def __init__(self, base: GraphProvider):
        self._base = base
        self._lock = threading.Lock()
        self.actual = Muestra()

    # -- control de la medida -------------------------------------------------
    def reset(self) -> None:
        with self._lock:
            self.actual = Muestra()

    def snapshot(self) -> Muestra:
        with self._lock:
            return Muestra(Counter(self.actual.llamadas), Counter(self.actual.filas))

    @property
    def name(self) -> str:  # identidad del proveedor real
        return self._base.name

    def _registrar(self, metodo: str, resultado: Any) -> Any:
        with self._lock:
            self.actual.llamadas[metodo] += 1
            self.actual.filas[metodo] += _contar_filas(resultado)
        return resultado


def _hacer_metodo(nombre: str):
    def _metodo(self: CountingProvider, *args: Any, **kwargs: Any) -> Any:
        return self._registrar(nombre, getattr(self._base, nombre)(*args, **kwargs))

    _metodo.__name__ = nombre
    return _metodo


for _n in _METODOS:
    setattr(CountingProvider, _n, _hacer_metodo(_n))

# Los métodos se instalan después de crear la clase, así que ABCMeta ya calculó
# `__abstractmethods__` y seguiría considerándola abstracta. Se recalcula: si
# alguno faltara de verdad, este conjunto quedaría NO vacío y la instanciación
# volvería a fallar (no es un "silenciar el error", es rehacer la comprobación).
CountingProvider.__abstractmethods__ = frozenset(
    nombre for nombre in getattr(GraphProvider, "__abstractmethods__", ())
    if getattr(CountingProvider, nombre, None) is getattr(GraphProvider, nombre, None)
)
