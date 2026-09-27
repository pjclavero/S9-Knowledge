"""GET /api/graph — nodos y relaciones del workspace, listos para vis-network."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.authz.ambito import MENSAJE_SIN_AMBITO, ambito_de_la_peticion
from app.authz.dependencies import get_filtered_provider, get_visibility_scope
from app.authz.scope import VisibilityScope
from app.deps import get_graph_limit
from app.graph_view import SIN_TOPE, vista_truncada
from app.providers.base import GraphProvider
from app.serializers import serialize_graph

router = APIRouter()


def _ambito_de_la_peticion(scope: VisibilityScope, solicitado: str | None) -> str | None:
    """El workspace que se consulta de verdad. Delega en la autoridad ÚNICA.

    La lógica vivía aquí, dentro de este endpoint, y eso era el defecto de la
    primera ronda: la propiedad quedaba cerrada para `/api/graph` y abierta
    para el resto del producto. Ahora vive en `app.authz.ambito`, que es lo que
    usan también `api/entities.py` y `routers/readonly.py`. Este envoltorio se
    conserva porque hay pruebas que lo invocan por nombre.
    """
    return ambito_de_la_peticion(scope.ctx, solicitado)


@router.get("/api/graph")
def api_graph(
    workspace: str = Query(default=None),
    limit: int = Query(default=None, ge=1, le=2000),
    entity_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    provider: GraphProvider = Depends(get_filtered_provider),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    limit = limit or get_graph_limit()
    ws = _ambito_de_la_peticion(scope, workspace)
    if ws is None:
        # FAIL-CLOSED VISIBLE. No se responde 200 con `nodes: []`: eso es
        # indistinguible de "este workspace existe y está vacío", y aquí no
        # hay workspace ninguno que consultar. Un 409 con causa propia es lo
        # que permite al cliente (y a quien mida el producto) distinguir "sin
        # ámbito" de "ámbito vacío".
        raise HTTPException(
            status_code=409,
            detail=MENSAJE_SIN_AMBITO,
        )
    # Se pide SIN TOPE y se recorta aquí. No es un rodeo: es la única forma de
    # saber cuánto se ha dejado fuera. El proveedor filtrado ya materializa el
    # conjunto completo en cada llamada, así que no añade una pasada nueva, y
    # lo que llega aquí está YA autorizado: los totales publicados cuentan
    # elementos visibles para QUIEN PREGUNTA, nunca elementos de la base.
    todos_nodos, todas_relaciones = provider.graph(
        ws, limit=SIN_TOPE, entity_type=entity_type, q=q
    )
    nodes, edges, view = vista_truncada(todos_nodos, todas_relaciones, limit)
    return serialize_graph(ws, nodes, edges, view=view)
