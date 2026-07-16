"""Interfaz común para proveedores de datos de grafo (mock / Neo4j).

Todos los métodos devuelven diccionarios "crudos" (mismas claves que
``examples/sample_graph.json``); la traducción a datos humanos la hace
``app/serializers.py`` en la capa de API. Los proveedores son de solo
lectura: ninguno debe escribir en su fuente de datos.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class GraphProvider(ABC):
    name: str = "base"

    @abstractmethod
    def is_connected(self) -> bool:
        """True si la fuente de datos subyacente está disponible."""

    @abstractmethod
    def workspaces(self) -> list[str]:
        ...

    @abstractmethod
    def counts(self, workspace: str | None = None) -> tuple[int, int]:
        """Devuelve (num_nodos, num_relaciones) del workspace (o global si None)."""

    @abstractmethod
    def entity_types(self, workspace: str) -> list[dict[str, Any]]:
        """Lista de {entity_type, count} para el workspace."""

    @abstractmethod
    def search(self, workspace: str, q: str, limit: int = 50) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def graph(
        self,
        workspace: str,
        limit: int = 300,
        entity_type: str | None = None,
        q: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Devuelve (nodos, relaciones) filtrados, sin duplicados."""

    @abstractmethod
    def entity(self, entity_id: str) -> dict[str, Any] | None:
        """Nodo completo por id, o None si no existe."""

    @abstractmethod
    def relations_for_entity(
        self, entity_id: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Devuelve (relaciones_salientes, relaciones_entrantes) de un nodo."""

    @abstractmethod
    def list_entities(
        self,
        workspace: str,
        *,
        q: str = "",
        entity_type: str | None = None,
        source_kind: str | None = None,
        review_status: str | None = None,
        visibility: str | None = None,
        quality_status: str | None = None,
        min_confidence: float | None = None,
        sort: str = "canonical_name",
        order: str = "asc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Devuelve (items, total) con paginación real en la fuente de datos.

        *No* carga todos los nodos en memoria: empuja SKIP/LIMIT al proveedor.
        """

    @abstractmethod
    def list_sources(self, workspace: str) -> list[dict[str, Any]]:
        """Lista de fuentes/documentos del workspace con metadatos básicos."""

    @abstractmethod
    def source_detail(self, workspace: str, source_id: str) -> dict[str, Any] | None:
        """Metadatos de una fuente concreta, o None si no existe."""

    @abstractmethod
    def quality_metrics(self, workspace: str | None = None) -> dict[str, Any]:
        """Métricas de calidad de solo lectura (counts, distribuciones, gaps)."""
