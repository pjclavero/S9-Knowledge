"""Review Console V2 — rutas HTML de SOLO LECTURA sobre la cola de revisión V3.

No hay ningún método POST aquí, a propósito: esta consola inspecciona, no
decide. Las decisiones siguen viviendo en ``/v3/review`` (router ``v3_review``),
que es el único sitio que escribe en el ledger.

El ámbito de visibilidad se obtiene con ``get_visibility_scope`` y se pasa tal
cual a ``ReviewService.queue``: la política de M5b se aplica aguas arriba y
este módulo no la reinterpreta.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.authz.dependencies import get_visibility_scope
from app.authz.scope import VisibilityScope
from app.services import review_console_v2 as console
from app.services.v3_review import ReviewError, ReviewService

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter(prefix="/console", tags=["v3-review-console"])


def _service() -> ReviewService:
    return ReviewService()


def _guard(request: Request):
    """Mismo control de acceso que la cola de revisión, sin duplicar reglas."""
    from app.routers.v3_review import _guard as review_guard

    return review_guard(request)


def _load(request: Request, workspace: str | None, scope: VisibilityScope):
    """Cola visible del workspace elegido, ya filtrada por ámbito aguas arriba."""
    service = _service()
    workspaces = service.workspaces(scope=scope)
    selected = workspace or (workspaces[0] if len(workspaces) == 1 else None)
    if selected and selected not in workspaces:
        raise HTTPException(status_code=404, detail="Workspace no encontrado")
    if not selected:
        return workspaces, None, []
    view = service.queue(selected, include_decided=True, scope=scope)
    return workspaces, selected, view.items


def _spec(**kwargs):
    try:
        return console.parse_filters(**kwargs)
    except console.ReviewConsoleV2Error as exc:
        # Mensaje del propio validador: describe el parámetro, nunca rutas ni trazas.
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def console_list(
    request: Request,
    workspace: str | None = Query(default=None),
    decision: str | None = Query(default=None),
    reason_code: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    extractor: str | None = Query(default=None),
    q: str | None = Query(default=None),
    disagreements_only: bool = Query(default=False),
    low_confidence_only: bool = Query(default=False),
    low_confidence_threshold: float | None = Query(default=None),
    min_confidence: float | None = Query(default=None),
    max_confidence: float | None = Query(default=None),
    include_decided: bool = Query(default=False),
    sort: str = Query(default="priority"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=console.DEFAULT_PAGE_SIZE, ge=1, le=200),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    guard = _guard(request)
    if isinstance(guard, (RedirectResponse, HTMLResponse)):
        return guard
    if sort not in console.SORTS:
        raise HTTPException(status_code=400, detail="Orden no soportado")
    spec = _spec(
        decision=decision, reason_code=reason_code, provider=provider, extractor=extractor,
        query=q, disagreements_only=disagreements_only, low_confidence_only=low_confidence_only,
        low_confidence_threshold=low_confidence_threshold, min_confidence=min_confidence,
        max_confidence=max_confidence, include_decided=include_decided,
    )
    try:
        workspaces, selected, items = _load(request, workspace, scope)
    except ReviewError as exc:
        # Paquete de propuestas corrupto o ilegible: se dice qué pasa, sin volcar rutas.
        return templates.TemplateResponse(
            request, "review_console_v2.html",
            {
                "auth_user": guard, "workspaces": [], "workspace": workspace, "view": None,
                "error": "No se pudo leer el paquete de propuestas: revisa la exportación del motor.",
                "error_detail": type(exc).__name__,
            },
            status_code=503,
        )
    view = console.build_view(items, spec, sort=sort, page=page, page_size=page_size)
    return templates.TemplateResponse(
        request, "review_console_v2.html",
        {
            "auth_user": guard,
            "workspaces": workspaces,
            "workspace": selected,
            "view": view,
            "spec": spec,
            "sort": sort,
            "page_sizes": console.PAGE_SIZES,
            "error": None,
        },
    )


@router.get("/item/{proposal_id}", response_class=HTMLResponse)
def console_item(
    request: Request,
    proposal_id: str,
    workspace: str | None = Query(default=None),
    decision: str | None = Query(default=None),
    reason_code: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    extractor: str | None = Query(default=None),
    q: str | None = Query(default=None),
    disagreements_only: bool = Query(default=False),
    low_confidence_only: bool = Query(default=False),
    low_confidence_threshold: float | None = Query(default=None),
    min_confidence: float | None = Query(default=None),
    max_confidence: float | None = Query(default=None),
    include_decided: bool = Query(default=True),
    sort: str = Query(default="priority"),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    """Ficha completa + navegación anterior/siguiente dentro del orden filtrado."""
    guard = _guard(request)
    if isinstance(guard, (RedirectResponse, HTMLResponse)):
        return guard
    if sort not in console.SORTS:
        raise HTTPException(status_code=400, detail="Orden no soportado")
    spec = _spec(
        decision=decision, reason_code=reason_code, provider=provider, extractor=extractor,
        query=q, disagreements_only=disagreements_only, low_confidence_only=low_confidence_only,
        low_confidence_threshold=low_confidence_threshold, min_confidence=min_confidence,
        max_confidence=max_confidence, include_decided=include_decided,
    )
    workspaces, selected, items = _load(request, workspace, scope)
    view = console.build_view(items, spec, sort=sort, page=1, page_size=10 ** 6)
    previous, current, following, position = console.neighbours(view.rows_all, proposal_id)
    if current is None:
        # Fuera de ámbito, inexistente o excluido por el filtro: no se distingue,
        # igual que hace el resto del visor.
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")
    return templates.TemplateResponse(
        request, "review_console_v2_item.html",
        {
            "auth_user": guard,
            "workspaces": workspaces,
            "workspace": selected,
            "row": current,
            "explanation": console.review_explanation(current),
            "previous": previous,
            "next": following,
            "position": position,
            "total": view.filtered_total,
            "spec": spec,
            "sort": sort,
        },
    )
