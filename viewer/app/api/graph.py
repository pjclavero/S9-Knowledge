"""GET /api/graph — nodos y relaciones del workspace, listos para vis-network."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.authz.dependencies import get_filtered_provider, get_visibility_scope
from app.authz.scope import VisibilityScope
from app.deps import get_graph_limit
from app.graph_view import SIN_TOPE, vista_truncada
from app.providers.base import GraphProvider
from app.serializers import serialize_graph

router = APIRouter()


def _ambito_de_la_peticion(scope: VisibilityScope, solicitado: str | None) -> str | None:
    """El workspace que se consulta de verdad. Lo decide la autoridad del
    servidor, nunca el parámetro que fabrique el cliente.

    ``allowed_workspaces`` es el ámbito ya resuelto por la autoridad canónica
    en ``authz/dependencies.py`` (perfil, con el entorno como fallback SOLO
    cuando el resolvedor lo decide así) -- singleton, o vacío si la autoridad
    está sin resolver.

    Para ``admin_full`` el parámetro del cliente sigue siendo un SELECTOR, no
    una concesión: un admin ya ve todo (docs/75), así que elegir qué workspace
    mirar no amplía nada que no tuviera. Para cualquier otro rol, el parámetro
    NO SE MIRA para decidir el ámbito -- solo lo que la autoridad ya resolvió
    cuenta -- y esto es justo lo que cierra el corte: antes ``workspace or
    get_default_workspace()`` aceptaba el valor del cliente tal cual, sin
    comparar nada contra la autoridad.

    Devuelve ``None`` cuando no hay ningún workspace que ofrecer: ni siquiera
    ``admin_full`` recibe uno inventado por este resolvedor. El llamante trata
    ``None`` como FALTA DE ÁMBITO, no como "el workspace por defecto está
    vacío".
    """
    canonicos = scope.ctx.allowed_workspaces
    if scope.ctx.admin_full:
        canonico = next(iter(canonicos), None)
        return solicitado or canonico
    if len(canonicos) != 1:
        # Vacío = autoridad sin resolver. Más de uno no debería ocurrir hoy
        # (`allowed_workspaces` es un singleton por contrato), pero tampoco
        # hay en ese caso UN ámbito único que devolver sin elegir por el
        # cliente, así que se trata igual: sin ámbito.
        return None
    return next(iter(canonicos))


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
            detail="No hay un ámbito de workspace determinado para esta sesión.",
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
