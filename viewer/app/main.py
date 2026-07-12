"""S9 Knowledge — visor mínimo de solo lectura (FastAPI)."""
from __future__ import annotations

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

app = FastAPI(title="S9 Knowledge Viewer", version="0.2.0")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

app.include_router(api_status.router)
app.include_router(api_entities.router)
app.include_router(api_graph.router)
app.include_router(api_jobs.router)


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
