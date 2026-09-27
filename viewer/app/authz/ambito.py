"""Autoridad ÚNICA del ámbito de una petición de lectura.

LA PROPIEDAD, ENTERA
--------------------
1. El ámbito de una consulta lo decide la **autoridad del servidor**, nunca un
   valor que fabrique el cliente ni el entorno.
2. Cuando esa autoridad **no resuelve**, la respuesta **no puede presentarse
   como un workspace normal y vacío**.

POR QUÉ VIVE AQUÍ Y NO EN CADA ENDPOINT
---------------------------------------
La primera ronda de este corte cerró `/api/graph` y dejó `/api/search`,
`/api/entity-types`, `/api/entities`, `/api/sources`, `/api/quality` y sus
gemelos HTML con el patrón viejo (`workspace or S9K_DEFAULT_WORKSPACE`): la
propiedad era cierta de UN endpoint, no del producto. Un criterio repetido a
mano en trece sitios diverge en el primer cambio; aquí hay uno solo.

`allowed_workspaces` es el ámbito ya resuelto por la autoridad canónica de
`authz/dependencies.py` (perfil de la bóveda, con el entorno como fallback
SÓLO cuando el resolvedor lo decide -- docs/v3/65). Es un **singleton**, o
vacío si la autoridad está sin resolver.

LA EXCEPCIÓN DE `admin_full`, DECLARADA
---------------------------------------
Para `admin_full` el parámetro del cliente es un **SELECTOR**, no una
concesión: un admin ya ve todo (docs/75), así que elegir qué workspace mirar no
le amplía nada. Para cualquier otro rol el parámetro **no se mira**. Está
escrito también en `docs/v3/65-autoridad-canonica-de-workspace.md`, no sólo en
este docstring: una excepción que vive en un comentario no está declarada.
"""
from __future__ import annotations

from fastapi import HTTPException

from app.policies.models import ViewerContext

# Código único del fail-closed. Un endpoint puede envolverlo en la forma de
# error que use su router, pero el ESTADO es el mismo en todos: 409.
CODIGO_SIN_AMBITO = "SCOPE_UNRESOLVED"
MENSAJE_SIN_AMBITO = "No hay un ámbito de workspace determinado para esta sesión."
ESTADO_SIN_AMBITO = 409


def ambito_de_la_peticion(ctx: ViewerContext, solicitado: str | None) -> str | None:
    """El workspace que se consulta de verdad, o ``None`` si no hay ninguno.

    ``None`` es **falta de ámbito**, no "el workspace por defecto está vacío":
    el llamante tiene que distinguirlo, y por eso existe `exigir_ambito`.
    """
    canonicos = ctx.allowed_workspaces
    if ctx.admin_full:
        return solicitado or next(iter(canonicos), None)
    if len(canonicos) != 1:
        # Vacío = autoridad sin resolver. Más de uno no debería ocurrir hoy
        # (`allowed_workspaces` es un singleton por contrato), pero tampoco
        # habría en ese caso UN ámbito único que devolver sin dejar elegir al
        # cliente: se trata igual, sin ámbito.
        return None
    return next(iter(canonicos))


def exigir_ambito(ctx: ViewerContext, solicitado: str | None = None) -> str:
    """El ámbito de la petición, o **409** visible.

    No se responde 200 con la lista vacía: eso es indistinguible de "este
    workspace existe y está vacío", y aquí no hay workspace ninguno que
    consultar. El 409 es lo que permite al cliente -- y a quien mida el
    producto -- distinguir «sin ámbito» de «ámbito vacío».
    """
    ws = ambito_de_la_peticion(ctx, solicitado)
    if ws is None:
        raise HTTPException(status_code=ESTADO_SIN_AMBITO, detail=MENSAJE_SIN_AMBITO)
    return ws


def hay_ambito(ctx: ViewerContext) -> bool:
    """¿Ha resuelto la autoridad algún ámbito para esta sesión?

    Para endpoints que no reciben `workspace` (p. ej. `/api/workspaces`): sin
    ámbito resuelto tampoco pueden presentar una lista vacía como si fuera el
    inventario real del principal.
    """
    return ambito_de_la_peticion(ctx, None) is not None
