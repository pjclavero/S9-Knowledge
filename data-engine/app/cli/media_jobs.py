#!/usr/bin/env python3
"""CLI del pipeline multimedia: scan, list, worker, show.

Convención de imports del repo: `data-engine/app/` es la raíz de sys.path y los
paquetes son top-level (`media`, `jobs`, ...). Por eso este archivo hace un
bootstrap de path (igual que audio/transcribe_audio.py) y se ejecuta como:

    python data-engine/app/cli/media_jobs.py scan --workspace leyenda

Alternativamente, con `data-engine/app` en PYTHONPATH:

    python -m cli.media_jobs scan --workspace leyenda

(El path `data_engine.app.cli` del diseño original no es importable porque
"data-engine" lleva guion; se documenta el equivalente real.)
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# ── Bootstrap de path: añadir data-engine/app como raíz de imports ────────────
_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from media.config import MediaConfig  # noqa: E402
from media.models import STATUS_PENDING  # noqa: E402
from media.scanner import scan  # noqa: E402
from media.store import MediaJobStore  # noqa: E402
from media.worker import run_worker  # noqa: E402


def _setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _make_bridge(config: MediaConfig):
    """Crea el bridge a job_store solo si está activado por configuración."""
    if not config.jobstore_bridge:
        return None
    try:
        from media.job_store_bridge import JobStoreBridge

        return JobStoreBridge()
    except Exception:  # noqa: BLE001 - el bridge nunca debe romper la CLI
        return None


def _print_table(rows: list[dict]) -> None:
    header = ["source_id", "kind", "status", "filename", "duration", "error"]
    print(" | ".join(header))
    print("-" * 90)
    for r in rows:
        dur = r.get("duration_seconds")
        dur_s = f"{dur:.0f}s" if isinstance(dur, (int, float)) else "-"
        err = (r.get("error_message") or "").replace("\n", " ")
        if len(err) > 40:
            err = err[:37] + "..."
        print(" | ".join([
            str(r.get("source_id", "-")),
            str(r.get("source_kind", "-")),
            str(r.get("status", "-")),
            str(r.get("original_filename", "-")),
            dur_s,
            err or "-",
        ]))


def cmd_scan(args, config: MediaConfig) -> int:
    store = MediaJobStore(config.output_dir)
    bridge = _make_bridge(config)
    result = scan(config, args.workspace, store=store, dry_run=args.dry_run, bridge=bridge)
    tag = "[dry-run] " if result.dry_run else ""
    print(f"{tag}Nuevos jobs: {len(result.created)} | "
          f"ya existentes: {len(result.skipped_existing)} | "
          f"ignorados: {len(result.ignored_files)}")
    if result.created:
        _print_table([s.to_dict() for s in result.created])
    return 0


def cmd_list(args, config: MediaConfig) -> int:
    store = MediaJobStore(config.output_dir)
    sources = store.list(args.workspace, status=args.status)
    print(f"Jobs en workspace '{args.workspace}'"
          + (f" con estado '{args.status}'" if args.status else "")
          + f": {len(sources)}")
    if sources:
        _print_table([s.to_dict() for s in sources])
    return 0


def cmd_worker(args, config: MediaConfig) -> int:
    store = MediaJobStore(config.output_dir)
    bridge = _make_bridge(config)
    result = run_worker(
        config,
        args.workspace,
        limit=args.limit,
        source_id=args.source_id,
        dry_run=args.dry_run,
        store=store,
        bridge=bridge,
    )
    tag = "[dry-run] " if result.dry_run else ""
    print(f"{tag}Procesados: {len(result.processed)} | "
          f"fallidos: {len(result.failed)} | omitidos: {len(result.skipped)}")
    if result.processed:
        print("  OK:", ", ".join(result.processed))
    if result.failed:
        print("  FALLIDOS:", ", ".join(result.failed))
    return 0


def cmd_show(args, config: MediaConfig) -> int:
    store = MediaJobStore(config.output_dir)
    source = store.get(args.workspace, args.source_id)
    if source is None:
        print(f"No se encontró la fuente '{args.source_id}' en workspace '{args.workspace}'",
              file=sys.stderr)
        return 1
    import json as _json

    print(_json.dumps(source.to_dict(), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pipeline multimedia S9 Knowledge (scan/list/worker/show). "
                    "No escribe en Neo4j: genera fuentes revisables."
    )
    parser.add_argument("--verbose", action="store_true", help="Log detallado.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Escanear staging y crear jobs pendientes.")
    p_scan.add_argument("--workspace", default=None)
    p_scan.add_argument("--dry-run", action="store_true")

    p_list = sub.add_parser("list", help="Listar jobs registrados.")
    p_list.add_argument("--workspace", default=None)
    p_list.add_argument("--status", default=None)

    p_worker = sub.add_parser("worker", help="Procesar jobs pendientes.")
    p_worker.add_argument("--workspace", default=None)
    p_worker.add_argument("--limit", type=int, default=1)
    p_worker.add_argument("--source-id", default=None)
    p_worker.add_argument("--dry-run", action="store_true")
    p_worker.add_argument("--once", action="store_true",
                          help="Procesar como mucho un lote y salir (equivale a no-daemon).")

    p_show = sub.add_parser("show", help="Mostrar el detalle de una fuente.")
    p_show.add_argument("--workspace", default=None)
    p_show.add_argument("--source-id", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))

    config = MediaConfig.from_env()
    # El workspace de la CLI tiene prioridad sobre el default de entorno.
    if getattr(args, "workspace", None):
        workspace = args.workspace
    else:
        workspace = config.default_workspace
    args.workspace = workspace

    if args.command == "scan":
        return cmd_scan(args, config)
    if args.command == "list":
        return cmd_list(args, config)
    if args.command == "worker":
        return cmd_worker(args, config)
    if args.command == "show":
        return cmd_show(args, config)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
