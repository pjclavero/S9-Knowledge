"""GET /api/graph — nodos y relaciones del workspace, listos para vis-network."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.deps import get_default_workspace, get_graph_limit, get_provider
from app.providers.base import GraphProvider
from app.serializers import serialize_graph

router = APIRouter()


@router.get("/api/graph")
def api_graph(
    workspace: str = Query(default=None),
    limit: int = Query(default=None, ge=1, le=2000),
    entity_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    provider: GraphProvider = Depends(get_provider),
):
    workspace = workspace or get_default_workspace()
    limit = limit or get_graph_limit()
    nodes, edges = provider.graph(workspace, limit=limit, entity_type=entity_type, q=q)
    return serialize_graph(workspace, nodes, edges)
