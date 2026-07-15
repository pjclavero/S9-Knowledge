"""Rutas de consulta de SOLO LECTURA: listado paginado de entidades y fuentes.

No aprueba, edita, fusiona ni ingiere; no añade acciones POST sobre datos;
0 escrituras en Neo4j. Reutiliza el proveedor de grafo (lectura) y las
dependencias de autorización de auth.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.config import get_auth_settings
from app.auth.dependencies import require_api_authenticated_user
from app.config import get_settings
from app.deps import get_default_workspace, get_provider
from app.providers.base import GraphProvider
from app.serializers import serialize_node

_ROLE_RANK = {"admin": 3, "reviewer": 2, "viewer": 1}


async def html_guard(request: Request):
    """Rutas HTML: público con auth off; anónimo con auth on -> 302 /login."""
    if not get_auth_settings().S9K_AUTH_ENABLED:
        return None
    user = getattr(request.state, "user", None)
    if user is None:
        return RedirectResponse(url=f"/login?next={request.url.path}", status_code=302)
    return user


def html_role_guard(role: str):
    async def _guard(request: Request):
        if not get_auth_settings().S9K_AUTH_ENABLED:
            return None
        user = getattr(request.state, "user", None)
        if user is None:
            return RedirectResponse(url=f"/login?next={request.url.path}", status_code=302)
        if _ROLE_RANK.get(user.role, 0) < _ROLE_RANK.get(role, 0):
            raise HTTPException(status_code=403, detail="Acceso denegado")
        return user
    return _guard

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

# Cota superior de nodos que se traen del proveedor antes de paginar en memoria.
# (La paginación empujada al proveedor queda como optimización de seguimiento.)
_FETCH_CAP = 500
_MAX_PAGE = 100


def _collect(provider: GraphProvider, workspace: str, q: str) -> list[dict]:
    if q.strip():
        raw = provider.search(workspace, q, limit=_FETCH_CAP)
    else:
        nodes, _edges = provider.graph(workspace, limit=_FETCH_CAP)
        raw = nodes
    return [serialize_node(n) for n in raw]


def _paginate(items: list[dict], entity_type: Optional[str], limit: int, offset: int) -> dict:
    if entity_type:
        items = [it for it in items if it.get("type") == entity_type]
    total = len(items)
    page = items[offset:offset + limit]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total,
        "items": page,
    }


# ---------------------------------------------------------------------------
# API: listado paginado y filtrado (viewer+)
# ---------------------------------------------------------------------------

@router.get("/api/entities")
def api_entities(
    workspace: str = Query(default=None),
    q: str = Query(default=""),
    entity_type: Optional[str] = Query(default=None),
    limit: int = Query(default=25, ge=1, le=_MAX_PAGE),
    offset: int = Query(default=0, ge=0),
    provider: GraphProvider = Depends(get_provider),
    _=Depends(require_api_authenticated_user),
):
    ws = workspace or get_default_workspace()
    result = _paginate(_collect(provider, ws, q), entity_type, limit, offset)
    result.update({"workspace": ws, "query": q, "entity_type": entity_type})
    return result


# ---------------------------------------------------------------------------
# HTML: página de entidades con filtros y paginación (viewer+)
# ---------------------------------------------------------------------------

@router.get("/entities", response_class=HTMLResponse)
def entities_page(
    request: Request,
    workspace: str | None = None,
    q: str = "",
    entity_type: str | None = None,
    limit: int = 25,
    offset: int = 0,
    provider: GraphProvider = Depends(get_provider),
    user=Depends(html_guard),
):
    if isinstance(user, RedirectResponse):
        return user
    settings = get_settings()
    ws = workspace or settings.S9K_DEFAULT_WORKSPACE
    limit = max(1, min(limit, _MAX_PAGE))
    offset = max(0, offset)
    page = _paginate(_collect(provider, ws, q), entity_type, limit, offset)
    types = provider.entity_types(ws)
    return templates.TemplateResponse(
        request,
        "entities.html",
        {
            "workspace": ws,
            "q": q,
            "entity_type": entity_type or "",
            "types": types,
            "page": page,
            "auth_user": user,
        },
    )


# ---------------------------------------------------------------------------
# HTML: fuentes (reviewer+) — solo lectura del estado de revisión
# ---------------------------------------------------------------------------

def _reviews_dir(workspace: str) -> Path:
    return REPO_ROOT / "output" / "reviews" / workspace


def _list_sources(workspace: str) -> list[dict]:
    d = _reviews_dir(workspace)
    if not d.exists():
        return []
    out = []
    for sub in sorted(p for p in d.iterdir() if p.is_dir()):
        approved = (sub / "approved_payload.json").exists()
        out.append({"source_id": sub.name, "has_approved": approved})
    return out


@router.get("/sources", response_class=HTMLResponse)
def sources_page(
    request: Request,
    workspace: str | None = None,
    user=Depends(html_role_guard("reviewer")),
):
    if isinstance(user, RedirectResponse):
        return user
    settings = get_settings()
    ws = workspace or settings.S9K_DEFAULT_WORKSPACE
    return templates.TemplateResponse(
        request, "sources.html",
        {"workspace": ws, "sources": _list_sources(ws), "auth_user": user},
    )
