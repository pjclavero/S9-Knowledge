#!/usr/bin/env python3
"""Worker genérico de la cola de jobs (Fase v0.2.4 "jobs worker and jobs panel").

Reclama jobs 'pending' de job_store, los despacha a un handler según
`job_type`, y marca el resultado (complete/failed/skipped). Los handlers
reales de multimedia (media_probe, audio_extract, transcribe, ...) se
añadirán en fases futuras; aquí solo hay handlers de prueba (`noop`, `echo`)
para validar el pipeline de la cola sin tocar datos reales.

NO escribe en Neo4j. NO procesa PDFs ni fuentes reales.

Ejecución manual:
    python data-engine/app/jobs/worker.py --once --limit 1
    python data-engine/app/jobs/worker.py --loop --sleep-seconds 5
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from pathlib import Path

# ── Bootstrap de path: data-engine/app como raíz de imports (top-level) ───────
_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from jobs import job_store  # noqa: E402

log = logging.getLogger("jobs.worker")


class JobHandlerError(RuntimeError):
    """Error controlado de un handler; el worker lo captura y marca failed."""


# ── Handlers de prueba ─────────────────────────────────────────────────────
def handle_noop(payload: dict) -> dict:
    """No hace nada; sirve para probar la cola end-to-end."""
    return {"ok": True, "handler": "noop"}


def handle_echo(payload: dict) -> dict:
    """Devuelve el payload recibido tal cual, como result."""
    return {"echo": payload}


HANDLERS = {
    "noop": handle_noop,
    "echo": handle_echo,
}


def dispatch(job: dict) -> dict:
    """Ejecuta el handler correspondiente a job['job_type']. Lanza JobHandlerError
    si no hay handler registrado (el llamador decide si eso es 'skipped' o 'failed').
    """
    job_type = job.get("job_type")
    handler = HANDLERS.get(job_type)
    if handler is None:
        raise JobHandlerError(f"job_type '{job_type}' no tiene handler implementado todavía")

    payload = {}
    if job.get("payload_json"):
        import json

        try:
            payload = json.loads(job["payload_json"])
        except (TypeError, ValueError) as exc:
            raise JobHandlerError(f"payload_json inválido: {exc}") from exc

    return handler(payload)


def process_one(worker_id: str, job_types: list | None, workspace: str | None,
                db_path: str) -> bool:
    """Reclama y procesa un job. Devuelve True si procesó alguno, False si no había."""
    job = job_store.claim_next_job(worker_id, job_types=job_types, workspace=workspace,
                                   db_path=db_path)
    if job is None:
        return False

    job_id = job["job_id"]
    job_type = job.get("job_type")
    log.info("Job reclamado: %s (job_type=%s, workspace=%s)", job_id, job_type, job["workspace"])

    try:
        result = dispatch(job)
    except JobHandlerError as exc:
        # job_type sin implementar (o payload roto): no es un fallo transitorio,
        # no tiene sentido reintentar. Se marca 'skipped' con mensaje claro.
        job_store.mark_skipped(job_id, message=str(exc), db_path=db_path)
        log.warning("Job omitido (%s): %s", job_id, exc)
        return True
    except Exception as exc:  # noqa: BLE001 - cualquier excepción del handler → failed
        job_store.mark_failed(job_id, error_message=str(exc), retry=True, db_path=db_path)
        log.exception("Job fallido (%s)", job_id)
        return True

    job_store.mark_complete(job_id, result=result, db_path=db_path)
    log.info("Job completado: %s", job_id)
    return True


def run(
    worker_id: str,
    once: bool = True,
    limit: int = 1,
    sleep_seconds: int = 5,
    job_type: str | None = None,
    workspace: str | None = None,
    dry_run: bool = False,
    stale_timeout_seconds: int | None = None,
    db_path: str | None = None,
) -> int:
    """Bucle principal del worker. Devuelve el número de jobs procesados."""
    db_path = job_store.resolve_db_path(db_path)
    job_store.init_db(db_path)
    job_types = [job_type] if job_type else None

    if stale_timeout_seconds:
        released = job_store.release_stale_jobs(stale_timeout_seconds, db_path=db_path)
        if released:
            log.info("Jobs 'running' liberados por inactividad: %s", released)

    if dry_run:
        pending = job_store.list_jobs(status="pending", job_type=job_type, workspace=workspace,
                                      limit=limit, db_path=db_path)
        for j in pending:
            log.info("[dry-run] Procesaría: %s (job_type=%s)", j["job_id"], j.get("job_type"))
        return len(pending)

    processed = 0
    if once or limit:
        for _ in range(limit if limit else 1):
            if not process_one(worker_id, job_types, workspace, db_path):
                break
            processed += 1
        return processed

    # --loop sin límite: modo continuo (opcional), hasta Ctrl+C.
    while True:
        did_work = process_one(worker_id, job_types, workspace, db_path)
        if not did_work:
            time.sleep(sleep_seconds)
        processed += 1 if did_work else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Worker genérico de la cola de jobs S9 Knowledge. "
                    "No escribe en Neo4j; solo procesa handlers de prueba (noop/echo) "
                    "por ahora."
    )
    parser.add_argument("--once", action="store_true",
                        help="Procesar hasta --limit jobs y salir (por defecto).")
    parser.add_argument("--loop", action="store_true",
                        help="Modo continuo: sigue reclamando jobs hasta Ctrl+C, "
                             "durmiendo --sleep-seconds cuando no hay trabajo.")
    parser.add_argument("--limit", type=int, default=1, help="Máximo de jobs a procesar (--once).")
    parser.add_argument("--sleep-seconds", type=int, default=5,
                        help="Segundos de espera entre sondeos en --loop.")
    parser.add_argument("--worker-id", default=None, help="Identificador del worker.")
    parser.add_argument("--job-type", default=None, help="Filtrar por tipo de job.")
    parser.add_argument("--workspace", default=None, help="Filtrar por workspace.")
    parser.add_argument("--dry-run", action="store_true",
                        help="No reclama ni modifica jobs; solo muestra qué haría.")
    parser.add_argument("--release-stale-seconds", type=int, default=None,
                        help="Si se indica, libera jobs 'running' bloqueados desde hace "
                             "más de N segundos antes de procesar.")
    parser.add_argument("--db", default=None,
                        help="Ruta a jobs.db (por defecto: S9K_JOBS_DB o el default del módulo).")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    worker_id = args.worker_id or f"worker-{uuid.uuid4().hex[:8]}"
    once = args.once or not args.loop  # por defecto: comportamiento --once

    processed = run(
        worker_id,
        once=once,
        limit=args.limit,
        sleep_seconds=args.sleep_seconds,
        job_type=args.job_type,
        workspace=args.workspace,
        dry_run=args.dry_run,
        stale_timeout_seconds=args.release_stale_seconds,
        db_path=args.db,
    )
    tag = "[dry-run] " if args.dry_run else ""
    print(f"{tag}Jobs procesados: {processed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
