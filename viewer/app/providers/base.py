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
    def entity(
        self, entity_id: str, *, workspaces: frozenset[str] | None = None
    ) -> dict[str, Any] | None:
        """Nodo completo por id, o None si no existe.

        ``workspaces`` acota la consulta a los workspaces autorizados del
        servidor —nunca a uno enviado por el cliente—. Es defensa en
        profundidad: el filtro de política se aplica después de todos modos,
        pero una búsqueda global por identificador es una frontera de seguridad
        incorrecta aunque luego se filtre. ``None`` = sin acotar (admin).
        """

    @abstractmethod
    def relations_for_entity(
        self, entity_id: str, *, workspaces: frozenset[str] | None = None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Devuelve (relaciones_salientes, relaciones_entrantes) de un nodo.

        ``workspaces`` acota igual que en ``entity()``. No esta para filtrar
        las aristas --de eso ya se encarga la politica-- sino para que la
        comprobacion de UNICIDAD del ancla se haga sobre EL MISMO conjunto que
        uso el resolver. Con dos ambitos distintos, una barrera puede declarar
        ambiguo lo que la otra resolvio sin problema.
        """

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

    # -- Hechos (aserciones) de una entidad -----------------------------------
    # NO es `@abstractmethod` a proposito, y la excepcion se razona aqui porque
    # el resto de la interfaz SI lo es: convertirlo en abstracto romperia de
    # golpe a todos los proveedores ya escritos (incluidos los falsos de las
    # suites), y un carril de LECTURA no puede exigir que cada proveedor se
    # reescriba para poder desplegarse.
    #
    # El defecto es la lista VACIA, y eso es deliberado en direccion segura:
    # un proveedor que no sepa leer hechos no entrega ninguno. "No se puede
    # leer" se degrada a "no hay nada que enseñar", nunca a "enseñalo todo".
    # La pantalla distingue las dos cosas (dice "sin hechos visibles"), pero
    # ningun hecho se filtra por esta via.
    def list_assertions(
        self, workspace: str, *, subject_entity_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Hechos (`:V3Assertion`) cuyo SUJETO es esa entidad, sin filtrar.

        Devuelve diccionarios crudos. El acotado por ambito de lectura y el
        enmascarado de divergencias locales (`local_override_of`, M4) NO se
        hacen aqui: los aplica `PolicyFilteredProvider`, que es el unico punto
        por el que la aplicacion obtiene datos (docs/v3/49 §2.5 punto 4).
        """
        return []
