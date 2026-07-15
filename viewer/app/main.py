"""S9 Knowledge — visor mínimo de solo lectura (FastAPI)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import entities as api_entities
from app.api import graph as api_graph
from app.api import jobs as api_jobs
from app.api import status as api_status
from app.auth.config import get_auth_settings
from app.auth.middleware import AuthMiddleware
from app.auth.dependencies import (
    get_current_user,
    require_admin,
    require_api_authenticated_user,
    require_api_role,
    require_authenticated_user,
    require_role,
)
from app.auth.models import User
from app.auth.security import enforce_auth_security
from app.auth import db as auth_db
from app.config import get_settings
from app.deps import get_default_workspace, get_provider
from app.jobs_client import get_counts_by_status, get_job, jobs_db_status, list_jobs, serialize_job
from app.providers.base import GraphProvider
from app.routers import auth as auth_router
from app.routers import admin as admin_router
from app.routers import health_admin as health_router
from app.serializers import serialize_edge, serialize_node

BASE_DIR = Path(__file__).resolve().parent

# Directorio raíz del repositorio (dos niveles por encima de viewer/app/)
REPO_ROOT = BASE_DIR.parent.parent

# Las rutas automáticas /docs, /redoc y /openapi.json se desactivan y se
# sustituyen por rutas propias con control de acceso evaluado en tiempo de
# petición (ver más abajo). Así el gating no depende del valor de configuración
# capturado en el momento del import.
app = FastAPI(
    title="S9 Knowledge Viewer",
    version="0.3.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Middleware de autenticación (no-op cuando S9K_AUTH_ENABLED=false)
app.add_middleware(AuthMiddleware)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# APIs protegidas: viewer+ cuando auth está activa; públicas cuando está off
# (la dependencia es no-op si S9K_AUTH_ENABLED=false).
app.include_router(api_status.router, dependencies=[Depends(require_api_authenticated_user)])
app.include_router(api_entities.router, dependencies=[Depends(require_api_authenticated_user)])
app.include_router(api_graph.router, dependencies=[Depends(require_api_authenticated_user)])
app.include_router(api_jobs.router, dependencies=[Depends(require_api_authenticated_user)])
app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(health_router.router)


# ---------------------------------------------------------------------------
# /docs, /redoc, /openapi.json — control de acceso en tiempo de petición
# ---------------------------------------------------------------------------

def _docs_access(request: Request):
    """Devuelve None si se permite servir la documentación; si no, la respuesta
    de denegación adecuada.

    - auth desactivada → público.
    - auth activada y S9K_AUTH_EXPOSE_DOCS=false → 404 (no existe).
    - auth activada y expose=true → solo admin (401 anónimo / 403 no-admin).
    """
    cfg = get_auth_settings()
    if not cfg.S9K_AUTH_ENABLED:
        return None
    if not cfg.S9K_AUTH_EXPOSE_DOCS:
        raise HTTPException(status_code=404, detail="Not Found")
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="No autenticado")
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Solo admin")
    return None


@app.get("/openapi.json", include_in_schema=False)
def _openapi(request: Request):
    _docs_access(request)
    return JSONResponse(app.openapi())


@app.get("/docs", include_in_schema=False)
def _swagger(request: Request):
    from fastapi.openapi.docs import get_swagger_ui_html
    _docs_access(request)
    return get_swagger_ui_html(openapi_url="/openapi.json", title="S9 Knowledge Viewer — API")


@app.get("/redoc", include_in_schema=False)
def _redoc(request: Request):
    from fastapi.openapi.docs import get_redoc_html
    _docs_access(request)
    return get_redoc_html(openapi_url="/openapi.json", title="S9 Knowledge Viewer — API")


# ---------------------------------------------------------------------------
# Helper: validar seguridad e instalar DB de auth al arrancar si está activada
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _startup_auth() -> None:
    cfg = get_auth_settings()
    # Fail-closed: aborta el arranque si la configuración de auth es insegura
    # (secreto CSRF por defecto/débil, backend de contraseñas no apto).
    enforce_auth_security(cfg)
    if cfg.S9K_AUTH_ENABLED:
        p = Path(cfg.S9K_AUTH_DB_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        auth_db.ensure_migrated(p)


# ---------------------------------------------------------------------------
# Helper: protección de rutas HTML cuando auth está activada
# ---------------------------------------------------------------------------

def _auth_guard(request: Request) -> Optional[User]:
    """
    Cuando S9K_AUTH_ENABLED=true, exige usuario autenticado y lo devuelve.
    Cuando está desactivada, devuelve None (sin restricción).
    No se usa como dependencia directa; cada ruta lo llama explícitamente.
    """
    cfg = get_auth_settings()
    if not cfg.S9K_AUTH_ENABLED:
        return None
    user = getattr(request.state, "user", None)
    return user


def _require_user_or_redirect(request: Request):
    """Para rutas HTML: redirige a /login si auth activada y no autenticado."""
    from fastapi.responses import RedirectResponse as _RR
    cfg = get_auth_settings()
    if not cfg.S9K_AUTH_ENABLED:
        return None
    user = getattr(request.state, "user", None)
    if user is None:
        next_url = str(request.url.path)
        return _RR(url=f"/login?next={next_url}", status_code=302)
    return user


def _require_reviewer_or_redirect(request: Request):
    """Para rutas que requieren reviewer o superior."""
    from fastapi.responses import RedirectResponse as _RR
    cfg = get_auth_settings()
    if not cfg.S9K_AUTH_ENABLED:
        return None
    user = getattr(request.state, "user", None)
    if user is None:
        next_url = str(request.url.path)
        return _RR(url=f"/login?next={next_url}", status_code=302)
    if not user.can_see_reviews():
        return HTMLResponse(
            content=_render_403(request, "Se requiere rol reviewer o admin."),
            status_code=403,
        )
    return user


def _render_403(request: Request, detail: str = "") -> str:
    try:
        return templates.get_template("auth/403.html").render(
            {"request": request, "detail": detail}
        )
    except Exception:
        return f"<h1>403 Acceso denegado</h1><p>{detail}</p>"


# ---------------------------------------------------------------------------
# Helper: lectura de datos de reviews
# ---------------------------------------------------------------------------

PIPELINE_FILE_NAMES = [
    "segments.json",
    "segments.classified.json",
    "candidates.json",
    "validated.json",
    "resolved.json",
    "approved_payload.json",
    "review_queue.json",
    "rejected.json",
    "review.md",
    "quality_report.json",
    "quality_report.md",
]


def _reviews_dir(workspace: str) -> Path:
    return REPO_ROOT / "output" / "reviews" / workspace


def _read_json_safe(path: Path) -> list | dict | None:
    """Lee JSON tolerando ausencia del fichero y errores de parseo."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _count_items(data) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return len(data)
    return 0


def _source_counters(source_dir: Path) -> dict:
    approved = _count_items(_read_json_safe(source_dir / "approved_payload.json"))
    pending = _count_items(_read_json_safe(source_dir / "review_queue.json"))
    rejected = _count_items(_read_json_safe(source_dir / "rejected.json"))
    return {"approved": approved, "pending": pending, "rejected": rejected}


def _extract_package_meta(source_dir: Path) -> dict:
    """Extrae metadatos del paquete: origin, producer, model si existen."""
    meta: dict = {}

    # Intentar leer desde pipeline_state.json (campo 'package' o 'meta')
    pipeline_state = _read_json_safe(source_dir / "pipeline_state.json")
    if isinstance(pipeline_state, dict):
        pkg = pipeline_state.get("package") or pipeline_state.get("meta") or {}
        if isinstance(pkg, dict):
            for field in ("origin", "producer", "model", "external_confidence",
                          "local_confidence", "decision_reason"):
                if field in pkg:
                    meta[field] = pkg[field]
        # También puede estar en nivel raíz
        for field in ("origin", "producer", "model"):
            if field in pipeline_state and field not in meta:
                meta[field] = pipeline_state[field]

    # Intentar leer desde candidates.json (primer ítem, campos de paquete)
    if not meta.get("origin"):
        candidates = _read_json_safe(source_dir / "candidates.json")
        if isinstance(candidates, list) and candidates:
            first = candidates[0]
            if isinstance(first, dict):
                for field in ("origin", "producer", "model"):
                    if field in first and field not in meta:
                        meta[field] = first[field]

    return meta


def _extract_quality_report(source_dir: Path) -> dict:
    """Extrae info del quality_report si existe (json o md)."""
    qr: dict = {"json_exists": False, "md_exists": False, "summary": None}
    json_path = source_dir / "quality_report.json"
    md_path = source_dir / "quality_report.md"
    qr["json_exists"] = json_path.exists()
    qr["md_exists"] = md_path.exists()

    if qr["json_exists"]:
        data = _read_json_safe(json_path)
        if isinstance(data, dict):
            # Extrae campos de resumen conocidos
            for field in ("score", "summary", "total", "issues", "warnings"):
                if field in data:
                    qr[field] = data[field]
            # Fallback: preview de las primeras claves
            if "summary" not in qr:
                qr["summary"] = {k: v for k, v in list(data.items())[:5]}
    elif qr["md_exists"]:
        try:
            text = md_path.read_text(encoding="utf-8")
            # Extracto: primeras 400 chars
            qr["md_preview"] = text[:400].strip()
        except Exception:
            pass
    return qr


def _list_sources(workspace: str) -> list[dict]:
    reviews_dir = _reviews_dir(workspace)
    if not reviews_dir.exists():
        return []
    sources = []
    for source_dir in sorted(reviews_dir.iterdir()):
        if source_dir.is_dir():
            counters = _source_counters(source_dir)
            pkg_meta = _extract_package_meta(source_dir)
            sources.append({
                "source_id": source_dir.name,
                **counters,
                "origin": pkg_meta.get("origin"),
            })
    return sources


# ---------------------------------------------------------------------------
# Rutas HTML
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request, provider: GraphProvider = Depends(get_provider)):
    guard = _require_user_or_redirect(request)
    if guard is not None and not isinstance(guard, User):
        return guard
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "provider_name": provider.name,
            "workspace": settings.S9K_DEFAULT_WORKSPACE,
            "auth_user": guard,
        },
    )


@app.get("/graph", response_class=HTMLResponse)
def graph_view(request: Request):
    guard = _require_user_or_redirect(request)
    if guard is not None and not isinstance(guard, User):
        return guard
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "graph.html",
        {
            "workspace": settings.S9K_DEFAULT_WORKSPACE,
            "graph_limit": settings.S9K_GRAPH_LIMIT,
            "auth_user": guard,
        },
    )


@app.get("/status", response_class=HTMLResponse)
def status_view(request: Request, provider: GraphProvider = Depends(get_provider)):
    guard = _require_user_or_redirect(request)
    if guard is not None and not isinstance(guard, User):
        return guard
    status_data = api_status.api_status(provider)
    return templates.TemplateResponse(request, "status.html", {"status": status_data, "auth_user": guard})


@app.get("/entity/{entity_id}", response_class=HTMLResponse)
def entity_view(
    request: Request,
    entity_id: str,
    provider: GraphProvider = Depends(get_provider),
):
    guard = _require_user_or_redirect(request)
    if guard is not None and not isinstance(guard, User):
        return guard
    node = provider.entity(entity_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Entidad no encontrada")

    outgoing, incoming = provider.relations_for_entity(entity_id)

    def _with_other_end(edge: dict, other_id_key: str) -> dict:
        serialized = serialize_edge(edge)
        other_node = provider.entity(edge.get(other_id_key))
        serialized["other_entity"] = serialize_node(other_node) if other_node else None
        return serialized

    return templates.TemplateResponse(
        request,
        "entity.html",
        {
            "entity": serialize_node(node),
            "outgoing": [_with_other_end(e, "to") for e in outgoing],
            "incoming": [_with_other_end(e, "from") for e in incoming],
        },
    )


@app.get("/jobs", response_class=HTMLResponse)
def jobs_view(
    request: Request,
    workspace: str | None = None,
    status: str | None = None,
    job_type: str | None = None,
):
    guard = _require_user_or_redirect(request)
    if guard is not None and not isinstance(guard, User):
        return guard
    status_info = jobs_db_status()
    counts = get_counts_by_status(workspace=workspace) if status_info["ok"] else {}
    jobs = (
        [serialize_job(j) for j in list_jobs(workspace=workspace, status=status, job_type=job_type)]
        if status_info["ok"]
        else []
    )
    return templates.TemplateResponse(
        request,
        "jobs.html",
        {
            "status": status_info,
            "counts": counts,
            "jobs": jobs,
            "filters": {"workspace": workspace, "status": status, "job_type": job_type},
        },
    )


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail_view(request: Request, job_id: str):
    guard = _require_user_or_redirect(request)
    if guard is not None and not isinstance(guard, User):
        return guard
    status_info = jobs_db_status()
    raw_job = get_job(job_id) if status_info["ok"] else None
    job = serialize_job(raw_job) if raw_job is not None else None
    error = None if status_info["ok"] else status_info["error"]
    if status_info["ok"] and job is None:
        error = "job_not_found"
    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {"job": job, "error": error},
    )


@app.get("/reviews", response_class=HTMLResponse)
def reviews_view(request: Request, workspace: str | None = None):
    guard = _require_reviewer_or_redirect(request)
    if guard is not None and not isinstance(guard, User):
        return guard
    settings = get_settings()
    ws = workspace or settings.S9K_DEFAULT_WORKSPACE
    sources = _list_sources(ws)
    return templates.TemplateResponse(
        request,
        "reviews.html",
        {"workspace": ws, "sources": sources},
    )


@app.get("/reviews/{source_id}", response_class=HTMLResponse)
def reviews_detail_view(request: Request, source_id: str, workspace: str | None = None):
    guard = _require_reviewer_or_redirect(request)
    if guard is not None and not isinstance(guard, User):
        return guard
    settings = get_settings()
    ws = workspace or settings.S9K_DEFAULT_WORKSPACE
    source_dir = _reviews_dir(ws) / source_id

    if not source_dir.exists():
        raise HTTPException(status_code=404, detail=f"Fuente no encontrada: {source_id}")

    counters = _source_counters(source_dir)

    # Metadatos del paquete
    pkg_meta = _extract_package_meta(source_dir)

    # Quality report
    quality_report = _extract_quality_report(source_dir)

    # Pipeline files state
    pipeline_files = [
        {"name": fname, "path": str(source_dir / fname), "exists": (source_dir / fname).exists()}
        for fname in PIPELINE_FILE_NAMES
    ]

    # Review queue (pending items)
    rq_data = _read_json_safe(source_dir / "review_queue.json")
    review_queue: list[dict] = []
    if isinstance(rq_data, list):
        review_queue = rq_data
    elif isinstance(rq_data, dict):
        # Accept {items: [...]} or flat dict
        review_queue = rq_data.get("items", list(rq_data.values()))

    # Approved payload preview
    approved_path = source_dir / "approved_payload.json"
    approved_exists = approved_path.exists()
    approved_data = _read_json_safe(approved_path) if approved_exists else None
    approved_count = _count_items(approved_data)
    if isinstance(approved_data, list):
        preview_data = approved_data[:3]
    elif isinstance(approved_data, dict):
        preview_data = dict(list(approved_data.items())[:3])
    else:
        preview_data = {}
    approved_preview = json.dumps(preview_data, ensure_ascii=False, indent=2) if approved_data else ""

    return templates.TemplateResponse(
        request,
        "reviews_detail.html",
        {
            "workspace": ws,
            "source_id": source_id,
            "counters": counters,
            "pkg_meta": pkg_meta,
            "quality_report": quality_report,
            "pipeline_files": pipeline_files,
            "review_queue": review_queue,
            "approved_exists": approved_exists,
            "approved_count": approved_count,
            "approved_preview": approved_preview,
        },
    )
