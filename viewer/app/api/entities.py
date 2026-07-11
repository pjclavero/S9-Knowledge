"""Endpoints de entidades: workspaces, tipos, búsqueda y ficha por id."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_default_workspace, get_provider
from app.providers.base import GraphProvider
from app.serializers import serialize_edge, serialize_node

router = APIRouter()


@router.get("/api/workspaces")
def api_workspaces(provider: GraphProvider = Depends(get_provider)):
    return {"workspaces": provider.workspaces()}


@router.get("/api/entity-types")
def api_entity_types(
    workspace: str = Query(default=None),
    provider: GraphProvider = Depends(get_provider),
):
    workspace = workspace or get_default_workspace()
    return {"workspace": workspace, "entity_types": provider.entity_types(workspace)}


@router.get("/api/search")
def api_search(
    q: str = Query(default=""),
    workspace: str = Query(default=None),
    provider: GraphProvider = Depends(get_provider),
):
    workspace = workspace or get_default_workspace()
    if not q.strip():
        return {"workspace": workspace, "query": q, "results": []}
    raw = provider.search(workspace, q)
    return {
        "workspace": workspace,
        "query": q,
        "results": [serialize_node(n) for n in raw],
    }


@router.get("/api/entity/{entity_id}")
def api_entity(entity_id: str, provider: GraphProvider = Depends(get_provider)):
    node = provider.entity(entity_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Entidad no encontrada")

    outgoing, incoming = provider.relations_for_entity(entity_id)

    def _with_other_end(edge: dict, other_id_key: str) -> dict:
        serialized = serialize_edge(edge)
        other_node = provider.entity(edge.get(other_id_key))
        serialized["other_entity"] = serialize_node(other_node) if other_node else None
        return serialized

    return {
        "entity": serialize_node(node),
        "outgoing": [_with_other_end(e, "to") for e in outgoing],
        "incoming": [_with_other_end(e, "from") for e in incoming],
    }
