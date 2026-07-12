"""S9 Knowledge — visor mínimo de solo lectura (FastAPI)."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import entities as api_entities
from app.api import graph as api_graph
from app.api import jobs as api_jobs
from app.api import status as api_status
from app.config import get_settings
from app.deps import get_default_workspace, get_provider
from app.jobs_client import get_counts_by_status, get_job, jobs_db_status, list_jobs, serialize_job
from app.providers.base import GraphProvider
from app.serializers import serialize_edge, serialize_node

BASE_DIR = Path(__file__).resolve().parent

# Directorio raíz del repositorio (dos niveles por encima de viewer/app/)
REPO_ROOT = BASE_DIR.parent.parent

app = FastAPI(title="S9 Knowledge Viewer", version="0.2.0")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

app.include_router(api_status.router)
app.include_router(api_entities.router)
app.include_router(api_graph.router)
app.include_router(api_jobs.router)


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


def _list_sources(workspace: str) -> list[dict]:
    reviews_dir = _reviews_dir(workspace)
    if not reviews_dir.exists():
        return []
    sources = []
    for source_dir in sorted(reviews_dir.iterdir()):
        if source_dir.is_dir():
            counters = _source_counters(source_dir)
            sources.append({"source_id": source_dir.name, **counters})
    return sources


# ---------------------------------------------------------------------------
# Rutas HTML
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request, provider: GraphProvider = Depends(get_provider)):
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "provider_name": provider.name,
            "workspace": settings.S9K_DEFAULT_WORKSPACE,
        },
    )


@app.get("/graph", response_class=HTMLResponse)
def graph_view(request: Request):
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "graph.html",
        {
            "workspace": settings.S9K_DEFAULT_WORKSPACE,
            "graph_limit": settings.S9K_GRAPH_LIMIT,
        },
    )


@app.get("/status", response_class=HTMLResponse)
def status_view(request: Request, provider: GraphProvider = Depends(get_provider)):
    status_data = api_status.api_status(provider)
    return templates.TemplateResponse(request, "status.html", {"status": status_data})


@app.get("/entity/{entity_id}", response_class=HTMLResponse)
def entity_view(
    request: Request,
    entity_id: str,
    provider: GraphProvider = Depends(get_provider),
):
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
    settings = get_settings()
    ws = workspace or settings.S9K_DEFAULT_WORKSPACE
    source_dir = _reviews_dir(ws) / source_id

    if not source_dir.exists():
        raise HTTPException(status_code=404, detail=f"Fuente no encontrada: {source_id}")

    counters = _source_counters(source_dir)

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
            "pipeline_files": pipeline_files,
            "review_queue": review_queue,
            "approved_exists": approved_exists,
            "approved_count": approved_count,
            "approved_preview": approved_preview,
        },
    )
