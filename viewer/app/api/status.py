"""GET /api/status — estado del visor y del proveedor de datos."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.authz.dependencies import get_filtered_provider
from app.providers.base import GraphProvider

router = APIRouter()


@router.get("/api/status")
def api_status(provider: GraphProvider = Depends(get_filtered_provider)):
    try:
        connected = provider.is_connected()
        workspaces = provider.workspaces() if connected else []
        nodes, relationships = provider.counts() if connected else (0, 0)
        return {
            "ok": True,
            "provider": provider.name,
            "neo4j_connected": connected if provider.name == "neo4j" else False,
            "workspaces": workspaces,
            "nodes": nodes,
            "relationships": relationships,
        }
    except Exception as exc:  # nunca romper la web por un fallo del proveedor
        return {
            "ok": False,
            "provider": provider.name,
            "neo4j_connected": False,
            "workspaces": [],
            "nodes": 0,
            "relationships": 0,
            "error": str(exc),
        }
