"""GET /api/status — estado del visor y del proveedor de datos."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.authz.dependencies import get_filtered_provider, get_visibility_scope
from app.authz.scope import VisibilityScope
from app.providers.base import GraphProvider

router = APIRouter()

#: Lo que ve quien no es administrador cuando el proveedor falla (D6).
PROVIDER_ERROR_CODE = "GRAPH_PROVIDER_ERROR"
PROVIDER_ERROR_MESSAGE = (
    "No se ha podido consultar el proveedor de datos. El detalle técnico queda "
    "registrado en el servidor. Avisa a quien administra el servicio e indícale "
    "este código."
)


@router.get("/api/status")
def api_status(
    provider: GraphProvider = Depends(get_filtered_provider),
    scope: VisibilityScope | None = Depends(get_visibility_scope),
):
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
        # D6: `str(exc)` del proveedor puede llevar host y puerto del grafo.
        # Detalle sólo para administración; el resto, código estable + frase.
        # `scope=None` (llamada interna sin decir quién pregunta) = redactado.
        detalle = scope is not None and scope.sees_operational_detail
        return {
            "ok": False,
            "provider": provider.name,
            "neo4j_connected": False,
            "workspaces": [],
            "nodes": 0,
            "relationships": 0,
            "error": str(exc) if detalle else PROVIDER_ERROR_CODE,
            "error_public": {"code": PROVIDER_ERROR_CODE, "message": PROVIDER_ERROR_MESSAGE},
        }
