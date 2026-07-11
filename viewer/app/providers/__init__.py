"""Fábrica de proveedores de grafo, seleccionada por S9K_GRAPH_PROVIDER."""
from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.providers.base import GraphProvider
from app.providers.mock_provider import MockGraphProvider


def build_provider(settings: Settings) -> GraphProvider:
    if settings.S9K_GRAPH_PROVIDER == "neo4j":
        from app.providers.neo4j_provider import Neo4jGraphProvider

        return Neo4jGraphProvider(
            uri=settings.S9K_NEO4J_URI,
            user=settings.S9K_NEO4J_USER,
            password=settings.neo4j_password,
        )

    sample_path = Path(settings.S9K_SAMPLE_GRAPH_PATH)
    if not sample_path.is_absolute():
        sample_path = Path(__file__).resolve().parents[2] / sample_path
    return MockGraphProvider(sample_path)


__all__ = ["build_provider", "GraphProvider"]
