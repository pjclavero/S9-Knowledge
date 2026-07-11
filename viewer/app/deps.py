"""Dependencias FastAPI compartidas: settings y proveedor de grafo (singleton)."""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.providers import GraphProvider, build_provider


@lru_cache
def get_provider() -> GraphProvider:
    return build_provider(get_settings())


def get_default_workspace() -> str:
    return get_settings().S9K_DEFAULT_WORKSPACE


def get_graph_limit() -> int:
    return get_settings().S9K_GRAPH_LIMIT
