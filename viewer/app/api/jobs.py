"""Endpoints de solo lectura sobre la cola de jobs (data-engine/job_store).

No crean, cancelan, reintentan ni borran jobs. Si jobs.db no existe o no es
legible, responden de forma amable (ok: false) en vez de romper.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.jobs_client import get_counts_by_status, get_job, jobs_db_status, list_jobs, serialize_job

router = APIRouter()


@router.get("/api/jobs")
def api_jobs(
    workspace: str | None = Query(default=None),
    status: str | None = Query(default=None),
    job_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
):
    status_info = jobs_db_status()
    if not status_info["ok"]:
        return {"ok": False, "error": status_info["error"]}

    jobs = list_jobs(workspace=workspace, status=status, job_type=job_type, limit=limit)
    return {"ok": True, "jobs": [serialize_job(j) for j in jobs]}


@router.get("/api/jobs/counts")
def api_jobs_counts(workspace: str | None = Query(default=None)):
    status_info = jobs_db_status()
    if not status_info["ok"]:
        return {"ok": False, "error": status_info["error"]}

    return {"ok": True, "counts": get_counts_by_status(workspace=workspace)}


@router.get("/api/jobs/{job_id}")
def api_job_detail(job_id: str):
    status_info = jobs_db_status()
    if not status_info["ok"]:
        return {"ok": False, "error": status_info["error"]}

    job = get_job(job_id)
    if job is None:
        return {"ok": False, "error": "job_not_found"}
    return {"ok": True, "job": serialize_job(job)}
