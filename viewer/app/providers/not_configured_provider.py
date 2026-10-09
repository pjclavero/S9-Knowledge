"""Proveedor «no configurado»: el estado honesto cuando no hay fuente real.

PR-2 del programa USABLE-V1 (segunda falsa confirmación de producto, justo
detrás de PR-1). El defecto medido: `S9K_GRAPH_PROVIDER` no declarado en una
instalación caía en `mock` EN SILENCIO, y una instalación recién hecha
mostraba 11 entidades inventadas en `/entities` y dos fuentes inventadas en
`/sources`, sin ninguna marca de que eran muestra. El administrador veía
datos de ejemplo y creía que era su conocimiento.

Decisión del operador (cerrada, no se reinterpreta aquí):

    proveedor real no configurado -> ESTADO VACÍO Y HONESTO
    mock                          -> SÓLO con modo DEMO explícito, marcado

Esta clase es el lado "vacío y honesto": de fábrica, SIN editar nada, el
visor no debe servir ni un dato mock como si fuera producto. Cada método
devuelve el valor vacío de su tipo — nunca inventa, nunca lanza, nunca se
disfraza de error 500: una instalación sin proveedor no está rota, está sin
configurar (ver `app.providers.classify_provider_declaration`).
"""
from __future__ import annotations

from typing import Any

from app.providers.base import GraphProvider

#: Mensaje humano único. Sin nombrar ninguna variable `S9K_*`: la persona que
#: lee esto en una pantalla no tiene por qué saber cómo se llama la variable
#: de entorno, sólo qué hacer (pedir a quien administra que conecte una
#: fuente real, o encender el modo de demostración si sólo quiere probar).
MENSAJE_NO_CONFIGURADO = (
    "Base de conocimiento todavía no configurada. Pide a quien administra "
    "esta instalación que conecte una fuente de conocimiento real, o activa "
    "el modo de demostración si sólo quieres ver cómo funciona el visor."
)


class NotConfiguredGraphProvider(GraphProvider):
    """Ningún dato, nunca. Ni inventado ni de error: vacío por diseño."""

    name = "not_configured"

    def is_connected(self) -> bool:
        return False

    def workspaces(self) -> list[str]:
        return []

    def counts(self, workspace: str | None = None) -> tuple[int, int]:
        return (0, 0)

    def entity_types(self, workspace: str) -> list[dict[str, Any]]:
        return []

    def search(self, workspace: str, q: str, limit: int = 50) -> list[dict[str, Any]]:
        return []

    def graph(
        self,
        workspace: str,
        limit: int = 300,
        entity_type: str | None = None,
        q: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return [], []

    def entity(
        self, entity_id: str, *, workspaces: frozenset[str] | None = None
    ) -> dict[str, Any] | None:
        return None

    def relations_for_entity(
        self, entity_id: str, *, workspaces: frozenset[str] | None = None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return [], []

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
        return [], 0

    def list_sources(self, workspace: str) -> list[dict[str, Any]]:
        return []

    def source_detail(self, workspace: str, source_id: str) -> dict[str, Any] | None:
        return None

    def quality_metrics(self, workspace: str | None = None) -> dict[str, Any]:
        return {
            "workspace": workspace,
            "total_entities": 0,
            "total_relations": 0,
            "by_entity_type": {},
            "by_workspace": {},
            "by_review_status": {},
            "by_visibility": {},
            "confidence_distribution": {
                "high_gte_0_8": 0,
                "mid_gte_0_5": 0,
                "low_lt_0_5": 0,
                "no_value": 0,
            },
            "data_gaps": {
                "no_source_document": 0,
                "no_description": 0,
                "no_entity_type": 0,
            },
        }

    def list_assertions(
        self, workspace: str, *, subject_entity_id: str | None = None
    ) -> list[dict[str, Any]]:
        return []


__all__ = ["NotConfiguredGraphProvider", "MENSAJE_NO_CONFIGURADO"]
