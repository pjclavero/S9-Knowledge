#!/usr/bin/env python3
"""CLI de la cola de jobs: create, list, show, counts, retry, cancel.

Convención de imports del repo: `data-engine/app/` es la raíz de sys.path y
los paquetes son top-level (`jobs`, ...). Este archivo hace bootstrap de path
(igual que audio/transcribe_audio.py y cli/media_jobs.py) y se ejecuta como:

    python data-engine/app/cli/jobs.py create --type echo --workspace leyenda \
        --payload '{"message":"test"}'

(El path `app.cli.jobs` / `data_engine.app.cli.jobs` del diseño original no es
importable porque "data-engine" lleva guion; se documenta el equivalente real.)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ── Bootstrap de path: añadir data-engine/app como raíz de imports ────────────
_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from jobs import job_store  # noqa: E402


def _db_path(args) -> str:
    path = job_store.resolve_db_path(getattr(args, "db", None))
    job_store.init_db(path)
    return path


def _truncate(text: str | None, n: int = 40) -> str:
    if not text:
        return "-"
    text = text.replace("\n", " ")
    return text if len(text) <= n else text[: n - 3] + "..."


def _print_table(rows: list[dict]) -> None:
    header = ["id", "type", "workspace", "status", "attempts", "created_at", "error"]
    print(" | ".join(header))
    print("-" * 110)
    for r in rows:
        print(" | ".join([
            str(r.get("job_id", "-"))[:12],
            str(r.get("job_type") or r.get("source_kind") or "-"),
            str(r.get("workspace", "-")),
            str(r.get("status", "-")),
            str(r.get("attempts", 0)),
            str(r.get("created_at", "-")),
            _truncate(r.get("error_message")),
        ]))


def cmd_create(args) -> int:
    db_path = _db_path(args)
    payload = json.loads(args.payload) if args.payload else None
    job_id = job_store.create_job(
        workspace=args.workspace,
        job_type=args.type,
        payload=payload,
        priority=args.priority,
        max_attempts=args.max_attempts,
        db_path=db_path,
    )
    print(f"Job creado: {job_id}")
    return 0


def cmd_list(args) -> int:
    db_path = _db_path(args)
    jobs = job_store.list_jobs(
        status=args.status, workspace=args.workspace, job_type=args.type,
        limit=args.limit, db_path=db_path,
    )
    print(f"Jobs: {len(jobs)}")
    if jobs:
        _print_table(jobs)
    return 0


def cmd_show(args) -> int:
    db_path = _db_path(args)
    job = job_store.get_job(args.id, db_path=db_path)
    if job is None:
        print(f"No se encontró el job '{args.id}'", file=sys.stderr)
        return 1
    print(json.dumps(job, ensure_ascii=False, indent=2))
    return 0


def cmd_counts(args) -> int:
    db_path = _db_path(args)
    counts = job_store.get_counts_by_status(workspace=args.workspace, db_path=db_path)
    if not counts:
        print("Sin jobs registrados.")
        return 0
    for status, n in sorted(counts.items()):
        print(f"{status}: {n}")
    return 0


def cmd_retry(args) -> int:
    db_path = _db_path(args)
    job = job_store.get_job(args.id, db_path=db_path)
    if job is None:
        print(f"No se encontró el job '{args.id}'", file=sys.stderr)
        return 1
    ok = job_store.update_job(
        args.id, status="pending", attempts=0, error_message=None, db_path=db_path,
    )
    print("Job reencolado (pending, attempts=0)." if ok else "No se pudo reencolar.")
    return 0 if ok else 1


def cmd_cancel(args) -> int:
    db_path = _db_path(args)
    ok = job_store.mark_cancelled(args.id, db_path=db_path)
    print("Job cancelado." if ok else "No se encontró el job.")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CLI de la cola de jobs S9 Knowledge (lectura y gestión básica). "
                    "No escribe en Neo4j."
    )
    parser.add_argument("--db", default=None, help="Ruta a jobs.db.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Crear un job (cola genérica).")
    p_create.add_argument("--type", required=True, help="job_type (ej. echo, noop).")
    p_create.add_argument("--workspace", required=True)
    p_create.add_argument("--payload", default=None, help="JSON del payload.")
    p_create.add_argument("--priority", type=int, default=0)
    p_create.add_argument("--max-attempts", type=int, default=3)

    p_list = sub.add_parser("list", help="Listar jobs.")
    p_list.add_argument("--workspace", default=None)
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--type", default=None)
    p_list.add_argument("--limit", type=int, default=50)

    p_show = sub.add_parser("show", help="Mostrar el detalle de un job.")
    p_show.add_argument("--id", required=True)

    p_counts = sub.add_parser("counts", help="Contar jobs por estado.")
    p_counts.add_argument("--workspace", default=None)

    p_retry = sub.add_parser("retry", help="Reencolar un job (vuelve a pending, attempts=0).")
    p_retry.add_argument("--id", required=True)

    p_cancel = sub.add_parser("cancel", help="Cancelar un job.")
    p_cancel.add_argument("--id", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    commands = {
        "create": cmd_create,
        "list": cmd_list,
        "show": cmd_show,
        "counts": cmd_counts,
        "retry": cmd_retry,
        "cancel": cmd_cancel,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
