"""Endpoints de entidades: workspaces, tipos, búsqueda y ficha por id."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.authz.ambito import exigir_ambito, hay_ambito
from app.authz.dependencies import get_filtered_provider, get_visibility_scope
from app.authz.scope import VisibilityScope
from app.providers.base import GraphProvider
from app.serializers import serialize_edge, serialize_node

router = APIRouter()


@router.get("/api/workspaces")
def api_workspaces(
    provider: GraphProvider = Depends(get_filtered_provider),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    # Sin ámbito resuelto, `provider.workspaces()` devolvería `[]` -- y una
    # lista vacía aquí se lee como "este principal no tiene ningún workspace",
    # que es una afirmación sobre el inventario. No lo es: es que la autoridad
    # no ha resuelto nada. Mismo criterio que el resto del producto: 409.
    if not hay_ambito(scope.ctx):
        exigir_ambito(scope.ctx)
    return {"workspaces": provider.workspaces()}


@router.get("/api/entity-types")
def api_entity_types(
    workspace: str = Query(default=None),
    provider: GraphProvider = Depends(get_filtered_provider),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    # Antes: `workspace or get_default_workspace()`. El ámbito lo elegía el
    # cliente, y con la autoridad sin resolver salía el valor del ENTORNO.
    ws = exigir_ambito(scope.ctx, workspace)
    return {"workspace": ws, "entity_types": provider.entity_types(ws)}


@router.get("/api/search")
def api_search(
    q: str = Query(default=""),
    workspace: str = Query(default=None),
    provider: GraphProvider = Depends(get_filtered_provider),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    ws = exigir_ambito(scope.ctx, workspace)
    if not q.strip():
        return {"workspace": ws, "query": q, "results": []}
    raw = provider.search(ws, q)
    return {
        "workspace": ws,
        "query": q,
        "results": [serialize_node(n) for n in raw],
    }


@router.get("/api/entity/{entity_id}")
def api_entity(entity_id: str, provider: GraphProvider = Depends(get_filtered_provider)):
    # Esta ruta no recibe `workspace`: el acotado sale de `_scope_workspaces()`
    # dentro del proveedor filtrado, que ya era el camino correcto.
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
