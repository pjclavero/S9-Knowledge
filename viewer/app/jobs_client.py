"""Puente de solo lectura hacia job_store (data-engine) para el panel /jobs.

Añade data-engine/app/ (no data-engine/) a sys.path e importa el paquete
top-level `jobs.job_store` — la misma convención que usan
data-engine/app/cli/jobs.py y data-engine/app/jobs/worker.py. Importante:
NO se usa el patrón "data-engine/ + app.jobs.job_store" (como app/labels.py),
porque el propio visor ya tiene un paquete `app` (viewer/app/); una vez que
`sys.modules['app']` queda ligado al `app` del visor, `from app.jobs import
job_store` fallaría silenciosamente (ModuleNotFoundError camuflado por el
except). Importar el paquete top-level `jobs` evita esa colisión de nombres.

Si data-engine no está disponible, todas las funciones degradan a una
respuesta "jobs_db_not_found" / lista vacía, sin romper el resto del visor
(el panel /jobs es opcional, /graph no depende de esto).

Es un puente de SOLO LECTURA: nunca crea, cancela, reintenta ni borra jobs
desde el visor. Esas acciones quedan para la CLI (data-engine/app/cli/jobs.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from app.config import get_settings


def serialize_job(job: dict) -> dict[str, Any]:
    """Decodifica payload_json/result_json a dict y expone `type` unificado
    (job_type de la cola genérica, o source_kind del modo de ingesta histórico)."""
    job = dict(job)
    for key in ("payload_json", "result_json"):
        raw = job.get(key)
        if raw:
            try:
                job[key.replace("_json", "")] = json.loads(raw)
            except (TypeError, ValueError):
                job[key.replace("_json", "")] = None
        else:
            job[key.replace("_json", "")] = None
    job["type"] = job.get("job_type") or job.get("source_kind") or ""
    return job


def _load_job_store():
    """Import perezoso de data-engine/app/jobs/job_store.py. Devuelve el módulo o None."""
    data_engine_app_dir = Path(__file__).resolve().parents[2] / "data-engine" / "app"
    if str(data_engine_app_dir) not in sys.path:
        sys.path.insert(0, str(data_engine_app_dir))
    try:
        from jobs import job_store  # type: ignore

        return job_store
    except Exception:
        return None


def _resolve_db_path() -> str | None:
    settings = get_settings()
    job_store = _load_job_store()
    if job_store is None:
        return None
    configured = settings.S9K_JOBS_DB or None
    return job_store.resolve_db_path(configured)


def jobs_db_status() -> dict[str, Any]:
    """Comprueba si la DB de jobs existe y es legible, sin lanzar excepción."""
    job_store = _load_job_store()
    if job_store is None:
        return {"ok": False, "error": "jobs_db_not_found", "reason": "job_store no disponible"}

    db_path = _resolve_db_path()
    if not db_path or not Path(db_path).is_file():
        return {"ok": False, "error": "jobs_db_not_found", "db_path": db_path}

    return {"ok": True, "db_path": db_path}


def list_jobs(workspace: str | None = None, status: str | None = None,
             job_type: str | None = None, limit: int = 100) -> list[dict]:
    status_info = jobs_db_status()
    if not status_info["ok"]:
        return []
    job_store = _load_job_store()
    return job_store.list_jobs(
        status=status, workspace=workspace, job_type=job_type,
        limit=limit, db_path=status_info["db_path"],
    )


def get_job(job_id: str) -> dict | None:
    status_info = jobs_db_status()
    if not status_info["ok"]:
        return None
    job_store = _load_job_store()
    return job_store.get_job(job_id, db_path=status_info["db_path"])


def get_counts_by_status(workspace: str | None = None) -> dict[str, int]:
    status_info = jobs_db_status()
    if not status_info["ok"]:
        return {}
    job_store = _load_job_store()
    return job_store.get_counts_by_status(workspace=workspace, db_path=status_info["db_path"])
