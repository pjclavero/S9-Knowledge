"""Endpoints de solo lectura sobre la cola de jobs (data-engine/job_store).

No crean, cancelan, reintentan ni borran jobs. Si jobs.db no existe o no es
legible, responden de forma amable (ok: false) en vez de romper.

Aislamiento (M5a): un job pertenece a un workspace y, si lo declara, a una
partida. Estas rutas aplican el MISMO ámbito que el resto del visor
(``get_visibility_scope``): lo que no es visible no se lista, no se cuenta y no
se puede consultar por id. Además, el detalle operativo (payload con rutas de
fichero del servidor, resultado, mensaje de error) se recorta para quien no es
admin.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.authz.dependencies import get_visibility_scope
from app.authz.scope import VisibilityScope
from app.jobs_client import jobs_db_status, scoped_counts, scoped_job, scoped_jobs

router = APIRouter()


@router.get("/api/jobs")
def api_jobs(
    workspace: str | None = Query(default=None),
    status: str | None = Query(default=None),
    job_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    status_info = jobs_db_status()
    if not status_info["ok"]:
        return {"ok": False, "error": status_info["error"]}

    jobs = scoped_jobs(scope, workspace=workspace, status=status,
                       job_type=job_type, limit=limit)
    return {"ok": True, "jobs": jobs}


@router.get("/api/jobs/counts")
def api_jobs_counts(
    workspace: str | None = Query(default=None),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    status_info = jobs_db_status()
    if not status_info["ok"]:
        return {"ok": False, "error": status_info["error"]}

    return {"ok": True, "counts": scoped_counts(scope, workspace=workspace)}


@router.get("/api/jobs/{job_id}")
def api_job_detail(
    job_id: str,
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    status_info = jobs_db_status()
    if not status_info["ok"]:
        return {"ok": False, "error": status_info["error"]}

    job = scoped_job(scope, job_id)
    if job is None:
        # Fuera de ámbito e inexistente se responden igual: no se revela la
        # existencia de un job de otra partida/workspace.
        return {"ok": False, "error": "job_not_found"}
    return {"ok": True, "job": job}
