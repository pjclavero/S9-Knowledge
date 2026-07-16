"""Rutas de consulta de SOLO LECTURA: listado paginado de entidades y fuentes,
fichas de entidad, detalle de fuente, panel de calidad.

Contratos:
  /entities, /entities/{id}, /api/entities, /api/entities/{id}  → viewer+
  /sources, /sources/{id}, /api/sources, /api/sources/{id}      → reviewer+
  /quality, /api/quality                                          → reviewer+

0 escrituras en Neo4j. Todos los métodos son GET/HEAD/OPTIONS.
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.config import get_auth_settings
from app.auth.dependencies import require_api_role, require_api_authenticated_user
from app.config import get_settings
from app.deps import get_default_workspace, get_provider
from app.providers.base import GraphProvider
from app.serializers import serialize_edge, serialize_node

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ---------------------------------------------------------------------------
# Guardias HTML
# ---------------------------------------------------------------------------

def html_guard(request: Request):
    """viewer+: público con auth off; anónimo con auth on -> 302 /login."""
    if not get_auth_settings().S9K_AUTH_ENABLED:
        return None
    user = getattr(request.state, "user", None)
    if user is None:
        return RedirectResponse(url=f"/login?next={request.url.path}", status_code=302)
    return user


def html_role_guard(role: str):
    """reviewer+: público con auth off; 302 /login si anónimo; 403 si rol insuficiente."""
    _rank = {"admin": 3, "reviewer": 2, "viewer": 1}

    async def _guard(request: Request):
        if not get_auth_settings().S9K_AUTH_ENABLED:
            return None
        user = getattr(request.state, "user", None)
        if user is None:
            return RedirectResponse(url=f"/login?next={request.url.path}", status_code=302)
        if _rank.get(user.role, 0) < _rank.get(role, 0):
            raise HTTPException(status_code=403, detail="Acceso denegado")
        return user

    return _guard


# ---------------------------------------------------------------------------
# Helpers de paginación y validación
# ---------------------------------------------------------------------------

_VALID_ORDERS = {"asc", "desc"}
_VALID_SORTS = {"canonical_name", "entity_type", "confidence", "review_status", "created_at"}

_WRITE_TOKENS_RE = re.compile(
    r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP|LOAD\s+CSV|FOREACH)\b",
    re.IGNORECASE,
)


def _build_pagination(total: int, limit: int, offset: int) -> dict:
    return {
        "limit": limit,
        "offset": offset,
        "total": total,
        "has_next": offset + limit < total,
        "has_previous": offset > 0,
    }


def _validate_query_params(
    q: str,
    limit: int,
    offset: int,
    sort: str,
    order: str,
    settings,
) -> tuple[str, int, int, str, str]:
    """Valida y normaliza parámetros de listado. Lanza HTTPException 400 si inválidos."""
    if len(q) > settings.S9K_VIEWER_MAX_SEARCH_LENGTH:
        raise HTTPException(status_code=400, detail="Parámetro 'q' demasiado largo")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset debe ser >= 0")
    if sort not in _VALID_SORTS:
        sort = "canonical_name"  # allowlist silenciosa (no error, se normaliza)
    if order not in _VALID_ORDERS:
        raise HTTPException(status_code=400, detail="order debe ser 'asc' o 'desc'")
    limit = max(1, min(limit, settings.S9K_VIEWER_MAX_PAGE_SIZE))
    return q, limit, offset, sort, order


router = APIRouter()

# ---------------------------------------------------------------------------
# API /api/entities — listado paginado (viewer+)
# ---------------------------------------------------------------------------

@router.get("/api/entities")
def api_entities(
    workspace: Optional[str] = Query(default=None),
    q: str = Query(default=""),
    entity_type: Optional[str] = Query(default=None),
    source_kind: Optional[str] = Query(default=None),
    review_status: Optional[str] = Query(default=None),
    visibility: Optional[str] = Query(default=None),
    quality_status: Optional[str] = Query(default=None),
    min_confidence: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    sort: str = Query(default="canonical_name"),
    order: str = Query(default="asc"),
    limit: int = Query(default=None),
    offset: int = Query(default=0, ge=0),
    provider: GraphProvider = Depends(get_provider),
    _=Depends(require_api_authenticated_user),
):
    settings = get_settings()
    if limit is None:
        limit = settings.S9K_VIEWER_DEFAULT_PAGE_SIZE
    q, limit, offset, sort, order = _validate_query_params(q, limit, offset, sort, order, settings)
    ws = workspace or settings.S9K_DEFAULT_WORKSPACE

    try:
        items, total = provider.list_entities(
            ws,
            q=q,
            entity_type=entity_type,
            source_kind=source_kind,
            review_status=review_status,
            visibility=visibility,
            quality_status=quality_status,
            min_confidence=min_confidence,
            sort=sort,
            order=order,
            limit=limit,
            offset=offset,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail={"error": {"code": "QUERY_TIMEOUT", "message": "Consulta excedió el tiempo límite"}})
    except Exception:
        raise HTTPException(status_code=503, detail={"error": {"code": "PROVIDER_UNAVAILABLE", "message": "Fuente de datos no disponible"}})

    serialized = [serialize_node(n) for n in items]
    return {
        "items": serialized,
        "pagination": _build_pagination(total, limit, offset),
        "filters": {
            "workspace": ws,
            "q": q,
            "entity_type": entity_type,
            "source_kind": source_kind,
            "review_status": review_status,
            "visibility": visibility,
            "quality_status": quality_status,
            "min_confidence": min_confidence,
            "sort": sort,
            "order": order,
        },
    }


# ---------------------------------------------------------------------------
# API /api/entities/{entity_id} — ficha de entidad (viewer+)
# ---------------------------------------------------------------------------

@router.get("/api/entities/{entity_id}")
def api_entity_detail(
    entity_id: str,
    provider: GraphProvider = Depends(get_provider),
    _=Depends(require_api_authenticated_user),
):
    try:
        node = provider.entity(entity_id)
    except Exception:
        raise HTTPException(status_code=503, detail={"error": {"code": "PROVIDER_UNAVAILABLE", "message": "Fuente de datos no disponible"}})

    if node is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "ENTITY_NOT_FOUND", "message": "Entidad no encontrada"}},
        )

    try:
        outgoing, incoming = provider.relations_for_entity(entity_id)
    except Exception:
        outgoing, incoming = [], []

    def _with_other(edge: dict, other_key: str) -> dict:
        s = serialize_edge(edge)
        try:
            other = provider.entity(edge.get(other_key))
            s["other_entity"] = serialize_node(other) if other else None
        except Exception:
            s["other_entity"] = None
        return s

    return {
        "entity": serialize_node(node),
        "outgoing": [_with_other(e, "to") for e in outgoing],
        "incoming": [_with_other(e, "from") for e in incoming],
    }


# ---------------------------------------------------------------------------
# HTML /entities — listado (viewer+)
# ---------------------------------------------------------------------------

@router.get("/entities", response_class=HTMLResponse)
def entities_page(
    request: Request,
    workspace: Optional[str] = None,
    q: str = "",
    entity_type: Optional[str] = None,
    source_kind: Optional[str] = None,
    review_status: Optional[str] = None,
    min_confidence: Optional[float] = None,
    sort: str = "canonical_name",
    order: str = "asc",
    limit: Optional[int] = None,
    offset: int = 0,
    provider: GraphProvider = Depends(get_provider),
    user=Depends(html_guard),
):
    if isinstance(user, RedirectResponse):
        return user
    settings = get_settings()
    if limit is None:
        limit = settings.S9K_VIEWER_DEFAULT_PAGE_SIZE
    q, limit, offset, sort, order = _validate_query_params(q, limit, offset, sort, order, settings)
    ws = workspace or settings.S9K_DEFAULT_WORKSPACE

    try:
        items, total = provider.list_entities(
            ws,
            q=q,
            entity_type=entity_type,
            source_kind=source_kind,
            review_status=review_status,
            min_confidence=min_confidence,
            sort=sort,
            order=order,
            limit=limit,
            offset=offset,
        )
    except Exception:
        items, total = [], 0

    serialized = [serialize_node(n) for n in items]
    pagination = _build_pagination(total, limit, offset)
    types = provider.entity_types(ws)

    return templates.TemplateResponse(
        request,
        "entities.html",
        {
            "workspace": ws,
            "q": q,
            "entity_type": entity_type or "",
            "types": types,
            "page": {**pagination, "items": serialized},
            "auth_user": user,
            "sort": sort,
            "order": order,
            "limit": limit,
        },
    )


# ---------------------------------------------------------------------------
# HTML /entities/{entity_id} — ficha de entidad (viewer+)
# ---------------------------------------------------------------------------

@router.get("/entities/{entity_id}", response_class=HTMLResponse)
def entity_detail_page(
    request: Request,
    entity_id: str,
    provider: GraphProvider = Depends(get_provider),
    user=Depends(html_guard),
):
    if isinstance(user, RedirectResponse):
        return user

    try:
        node = provider.entity(entity_id)
    except Exception:
        return templates.TemplateResponse(
            request, "error.html",
            {"code": 503, "message": "Fuente de datos no disponible", "auth_user": user},
            status_code=503,
        )

    if node is None:
        return templates.TemplateResponse(
            request, "error.html",
            {"code": 404, "message": "Entidad no encontrada", "auth_user": user},
            status_code=404,
        )

    try:
        outgoing, incoming = provider.relations_for_entity(entity_id)
    except Exception:
        outgoing, incoming = [], []

    def _with_other(edge: dict, other_key: str) -> dict:
        s = serialize_edge(edge)
        try:
            other = provider.entity(edge.get(other_key))
            s["other_entity"] = serialize_node(other) if other else None
        except Exception:
            s["other_entity"] = None
        return s

    return templates.TemplateResponse(
        request,
        "entity_detail.html",
        {
            "entity": serialize_node(node),
            "outgoing": [_with_other(e, "to") for e in outgoing],
            "incoming": [_with_other(e, "from") for e in incoming],
            "auth_user": user,
        },
    )


# ---------------------------------------------------------------------------
# API /api/sources — listado de fuentes (reviewer+)
# ---------------------------------------------------------------------------

@router.get("/api/sources")
def api_sources(
    workspace: Optional[str] = Query(default=None),
    provider: GraphProvider = Depends(get_provider),
    _=Depends(require_api_role("reviewer")),
):
    settings = get_settings()
    ws = workspace or settings.S9K_DEFAULT_WORKSPACE
    try:
        sources = provider.list_sources(ws)
    except Exception:
        raise HTTPException(status_code=503, detail={"error": {"code": "PROVIDER_UNAVAILABLE", "message": "Fuente de datos no disponible"}})
    return {"workspace": ws, "sources": sources}


# ---------------------------------------------------------------------------
# API /api/sources/{source_id} — detalle de fuente (reviewer+)
# ---------------------------------------------------------------------------

@router.get("/api/sources/{source_id}")
def api_source_detail(
    source_id: str,
    workspace: Optional[str] = Query(default=None),
    provider: GraphProvider = Depends(get_provider),
    _=Depends(require_api_role("reviewer")),
):
    settings = get_settings()
    ws = workspace or settings.S9K_DEFAULT_WORKSPACE
    try:
        detail = provider.source_detail(ws, source_id)
    except Exception:
        raise HTTPException(status_code=503, detail={"error": {"code": "PROVIDER_UNAVAILABLE", "message": "Fuente de datos no disponible"}})

    if detail is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "SOURCE_NOT_FOUND", "message": "Fuente no encontrada"}},
        )
    return detail


# ---------------------------------------------------------------------------
# HTML /sources — listado de fuentes (reviewer+)
# ---------------------------------------------------------------------------

@router.get("/sources", response_class=HTMLResponse)
def sources_page(
    request: Request,
    workspace: Optional[str] = None,
    user=Depends(html_role_guard("reviewer")),
):
    if isinstance(user, RedirectResponse):
        return user
    settings = get_settings()
    ws = workspace or settings.S9K_DEFAULT_WORKSPACE
    provider = get_provider()
    try:
        sources = provider.list_sources(ws)
    except Exception:
        sources = []
    return templates.TemplateResponse(
        request, "sources.html",
        {"workspace": ws, "sources": sources, "auth_user": user},
    )


# ---------------------------------------------------------------------------
# HTML /sources/{source_id} — detalle de fuente (reviewer+)
# ---------------------------------------------------------------------------

@router.get("/sources/{source_id}", response_class=HTMLResponse)
def source_detail_page(
    request: Request,
    source_id: str,
    workspace: Optional[str] = None,
    user=Depends(html_role_guard("reviewer")),
):
    if isinstance(user, RedirectResponse):
        return user
    settings = get_settings()
    ws = workspace or settings.S9K_DEFAULT_WORKSPACE
    provider = get_provider()

    try:
        detail = provider.source_detail(ws, source_id)
    except Exception:
        return templates.TemplateResponse(
            request, "error.html",
            {"code": 503, "message": "Fuente de datos no disponible", "auth_user": user},
            status_code=503,
        )

    if detail is None:
        return templates.TemplateResponse(
            request, "error.html",
            {"code": 404, "message": "Fuente no encontrada", "auth_user": user},
            status_code=404,
        )

    return templates.TemplateResponse(
        request, "source_detail.html",
        {"workspace": ws, "source": detail, "auth_user": user},
    )


# ---------------------------------------------------------------------------
# API /api/quality — métricas de calidad (reviewer+)
# ---------------------------------------------------------------------------

@router.get("/api/quality")
def api_quality(
    workspace: Optional[str] = Query(default=None),
    provider: GraphProvider = Depends(get_provider),
    _=Depends(require_api_role("reviewer")),
):
    settings = get_settings()
    ws = workspace or settings.S9K_DEFAULT_WORKSPACE
    try:
        metrics = provider.quality_metrics(ws)
    except Exception:
        raise HTTPException(status_code=503, detail={"error": {"code": "PROVIDER_UNAVAILABLE", "message": "Fuente de datos no disponible"}})
    return metrics


# ---------------------------------------------------------------------------
# HTML /quality — panel de calidad (reviewer+)
# ---------------------------------------------------------------------------

@router.get("/quality", response_class=HTMLResponse)
def quality_page(
    request: Request,
    workspace: Optional[str] = None,
    user=Depends(html_role_guard("reviewer")),
):
    if isinstance(user, RedirectResponse):
        return user
    settings = get_settings()
    ws = workspace or settings.S9K_DEFAULT_WORKSPACE
    provider = get_provider()
    try:
        metrics = provider.quality_metrics(ws)
    except Exception:
        metrics = {}
    return templates.TemplateResponse(
        request, "quality.html",
        {"workspace": ws, "metrics": metrics, "auth_user": user},
    )
