"""GET /api/graph — nodos y relaciones del workspace, listos para vis-network."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.authz.dependencies import get_filtered_provider
from app.deps import get_default_workspace, get_graph_limit
from app.graph_view import SIN_TOPE, vista_truncada
from app.providers.base import GraphProvider
from app.serializers import serialize_graph

router = APIRouter()


@router.get("/api/graph")
def api_graph(
    workspace: str = Query(default=None),
    limit: int = Query(default=None, ge=1, le=2000),
    entity_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    provider: GraphProvider = Depends(get_filtered_provider),
):
    workspace = workspace or get_default_workspace()
    limit = limit or get_graph_limit()
    # Se pide SIN TOPE y se recorta aquí. No es un rodeo: es la única forma de
    # saber cuánto se ha dejado fuera. El proveedor filtrado ya materializa el
    # conjunto completo en cada llamada, así que no añade una pasada nueva, y
    # lo que llega aquí está YA autorizado: los totales publicados cuentan
    # elementos visibles para QUIEN PREGUNTA, nunca elementos de la base.
    todos_nodos, todas_relaciones = provider.graph(
        workspace, limit=SIN_TOPE, entity_type=entity_type, q=q
    )
    nodes, edges, view = vista_truncada(todos_nodos, todas_relaciones, limit)
    return serialize_graph(workspace, nodes, edges, view=view)
