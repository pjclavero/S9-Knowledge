#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI de procesamiento externo por rafaga (Fase B1).

Uso:
    python data-engine/app/cli/burst.py plan     --workspace W --source PATH [--mode auto] [--dry-run]
    python data-engine/app/cli/burst.py dispatch --batch-id UUID --provider mock [--dry-run]
    python data-engine/app/cli/burst.py status   --batch-id UUID
    python data-engine/app/cli/burst.py retry    --batch-id UUID --job-id ID
    python data-engine/app/cli/burst.py cancel   --batch-id UUID
    python data-engine/app/cli/burst.py validate --batch-id UUID
    python data-engine/app/cli/burst.py merge    --batch-id UUID
    python data-engine/app/cli/burst.py report   --batch-id UUID

En esta fase: --dry-run obligatorio para proveedores reales.
Mock puede ejecutar sin --dry-run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

# Ajustar PYTHONPATH para imports relativos
_HERE = Path(__file__).resolve().parent
_APP_DIR = _HERE.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

_REPO_ROOT = _APP_DIR.parent.parent


def _sha256_path(path: str) -> str:
    """SHA256 del contenido del archivo o del path si no existe."""
    p = Path(path)
    if p.exists() and p.is_file():
        return hashlib.sha256(p.read_bytes()).hexdigest()
    return hashlib.sha256(path.encode()).hexdigest()


def _detect_mime(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
        ".mp4": "video/mp4", ".mkv": "video/x-matroska",
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif",
        ".txt": "text/plain", ".md": "text/markdown",
    }.get(ext, "application/octet-stream")


def _file_size(path: str) -> int:
    p = Path(path)
    return p.stat().st_size if p.exists() else 0


# ── Subcomando: plan ──────────────────────────────────────────────────────────

def cmd_plan(args: argparse.Namespace) -> None:
    from external_processing.manifests import BatchFile
    from external_processing.models import ProcessingMode
    from external_processing.planner import BurstPlanner

    if not args.dry_run and args.provider != "mock":
        print("ERROR: --dry-run es obligatorio para proveedores reales.", file=sys.stderr)
        sys.exit(1)

    source_path = args.source
    source_hash = _sha256_path(source_path)
    mime = _detect_mime(source_path)
    size = _file_size(source_path)

    # Crear BatchFile con metadata basica
    bf = BatchFile(
        private_path=str(Path(source_path).resolve()),
        sanitized_name=Path(source_path).name,
        mime_type=mime,
        size_bytes=size,
        file_hash=source_hash,
    )
    # Heuristicas de duracion/paginas basadas en size para demo
    if "audio" in mime or "video" in mime:
        bf = bf.copy(update={"duration_seconds": size / 16000.0})  # estimacion gruesa
    elif "pdf" in mime:
        bf = bf.copy(update={"pages": max(1, size // 50000)})
    elif "image" in mime:
        bf = bf.copy(update={"image_count": 1})

    mode_str = getattr(args, "mode", "auto")
    try:
        mode = ProcessingMode(mode_str)
    except ValueError:
        mode = ProcessingMode.AUTO

    planner = BurstPlanner(_REPO_ROOT)
    plan = planner.plan(
        workspace=args.workspace,
        source_id=Path(source_path).stem,
        source_path=str(source_path),
        source_hash=source_hash,
        files=[bf],
        mode_override=mode,
        provider=getattr(args, "provider", "mock"),
        dry_run=args.dry_run,
    )

    explanation = planner.explain(plan)
    print(json.dumps(explanation, ensure_ascii=False, indent=2))
    print(f"\nbatch_id: {plan.batch_id}")
    print(f"Jobs planificados: {len(plan.jobs)}")
    print(f"Mode: {plan.selected_mode.value}")
    print(f"Reason: {plan.reason_codes}")

    # Guardar plan para uso posterior
    state_dir = _REPO_ROOT / "state" / "burst_plans"
    state_dir.mkdir(parents=True, exist_ok=True)
    plan_path = state_dir / f"{plan.batch_id}.json"
    plan_path.write_text(
        json.dumps({
            "batch_id": plan.batch_id,
            "workspace": plan.workspace,
            "source_id": plan.source_id,
            "source_path": plan.source_path,
            "source_hash": plan.source_hash,
            "selected_mode": plan.selected_mode.value,
            "reason_codes": plan.reason_codes,
            "jobs": [j.dict() for j in plan.jobs],
            "dry_run": plan.dry_run,
        }, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8"
    )
    print(f"\nPlan guardado en: {plan_path}")


# ── Subcomando: dispatch ──────────────────────────────────────────────────────

def cmd_dispatch(args: argparse.Namespace) -> None:
    from external_processing.dispatcher import BurstDispatcher
    from external_processing.models import ProcessingJob, ProcessingMode
    from external_processing.providers.mock import MockExternalProcessingProvider

    if args.provider != "mock" and not args.dry_run:
        print("ERROR: --dry-run es obligatorio para proveedores reales.", file=sys.stderr)
        sys.exit(1)

    # Cargar plan
    plan_path = _REPO_ROOT / "state" / "burst_plans" / f"{args.batch_id}.json"
    if not plan_path.exists():
        print(f"ERROR: plan no encontrado: {plan_path}", file=sys.stderr)
        sys.exit(1)

    plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
    jobs = [ProcessingJob(**j) for j in plan_data.get("jobs", [])]

    # Seleccionar proveedor
    if args.provider == "mock":
        provider = MockExternalProcessingProvider(scenario="success")
    else:
        print(f"ERROR: proveedor {args.provider!r} no disponible en Fase B1. Use 'mock'.", file=sys.stderr)
        sys.exit(1)

    dispatcher = BurstDispatcher(
        provider=provider,
        dry_run=args.dry_run,
        base_backoff=0.1,  # rapido en CLI
    )

    start = time.time()
    results = dispatcher.dispatch_batch(jobs)
    elapsed = time.time() - start

    completed = sum(1 for j in results if j.status.value in ("ready", "completed"))
    failed = sum(1 for j in results if "failed" in j.status.value)

    print(f"\nDispatch completado en {elapsed:.2f}s")
    print(f"Jobs: {len(results)} | Completados: {completed} | Fallidos: {failed}")
    print(f"Reintentos: {dispatcher.total_retries} | Cache hits: {dispatcher.total_cache_hits}")

    # Guardar resultados
    results_path = _REPO_ROOT / "state" / "burst_plans" / f"{args.batch_id}_results.json"
    results_path.write_text(
        json.dumps({"jobs": [j.dict() for j in results]}, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8"
    )
    print(f"Resultados guardados en: {results_path}")


# ── Subcomando: status ────────────────────────────────────────────────────────

def cmd_status(args: argparse.Namespace) -> None:
    results_path = _REPO_ROOT / "state" / "burst_plans" / f"{args.batch_id}_results.json"
    plan_path = _REPO_ROOT / "state" / "burst_plans" / f"{args.batch_id}.json"

    if results_path.exists():
        data = json.loads(results_path.read_text(encoding="utf-8"))
        jobs = data.get("jobs", [])
        by_status: dict = {}
        for j in jobs:
            s = j.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
        print(f"batch_id: {args.batch_id}")
        print(f"Status por tipo: {json.dumps(by_status, indent=2)}")
    elif plan_path.exists():
        data = json.loads(plan_path.read_text(encoding="utf-8"))
        print(f"batch_id: {args.batch_id}")
        print(f"Estado: PLANIFICADO (sin dispatch aun)")
        print(f"Jobs en plan: {len(data.get('jobs', []))}")
    else:
        print(f"ERROR: batch {args.batch_id} no encontrado.", file=sys.stderr)
        sys.exit(1)


# ── Subcomando: retry ─────────────────────────────────────────────────────────

def cmd_retry(args: argparse.Namespace) -> None:
    print(f"Retry del job {args.job_id} en batch {args.batch_id}")
    print("(Fase B1: retry manual no implementado en CLI; usar dispatch de nuevo)")


# ── Subcomando: cancel ────────────────────────────────────────────────────────

def cmd_cancel(args: argparse.Namespace) -> None:
    # Marcar en estado para que futuros dispatches lo respeten
    cancel_path = _REPO_ROOT / "state" / "burst_plans" / f"{args.batch_id}_cancelled"
    cancel_path.write_text("cancelled", encoding="utf-8")
    print(f"Batch {args.batch_id} marcado como cancelado.")


# ── Subcomando: validate ──────────────────────────────────────────────────────

def cmd_validate(args: argparse.Namespace) -> None:
    from external_processing.models import ProcessingJob
    from external_processing.result_validator import validate_batch

    results_path = _REPO_ROOT / "state" / "burst_plans" / f"{args.batch_id}_results.json"
    if not results_path.exists():
        print(f"ERROR: resultados no encontrados para {args.batch_id}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(results_path.read_text(encoding="utf-8"))
    jobs = [ProcessingJob(**j) for j in data.get("jobs", [])]

    validated, vrs = validate_batch(jobs)

    valid_count = sum(1 for vr in vrs if vr.valid)
    invalid_count = sum(1 for vr in vrs if not vr.valid)

    print(f"Validacion de batch {args.batch_id}:")
    print(f"  Validos: {valid_count} | Invalidos: {invalid_count}")
    for vr in vrs:
        if vr.errors:
            print(f"  Errores: {vr.errors}")

    # Guardar jobs validados
    results_path.write_text(
        json.dumps({"jobs": [j.dict() for j in validated]}, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8"
    )


# ── Subcomando: merge ─────────────────────────────────────────────────────────

def cmd_merge(args: argparse.Namespace) -> None:
    from external_processing.models import ProcessingJob, ExternalTaskType
    from external_processing.result_merger import merge_batch_results

    results_path = _REPO_ROOT / "state" / "burst_plans" / f"{args.batch_id}_results.json"
    plan_path = _REPO_ROOT / "state" / "burst_plans" / f"{args.batch_id}.json"

    if not results_path.exists() or not plan_path.exists():
        print(f"ERROR: datos no encontrados para {args.batch_id}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(results_path.read_text(encoding="utf-8"))
    plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
    jobs = [ProcessingJob(**j) for j in data.get("jobs", [])]

    # Detectar tipo de tarea dominante
    task_types = [j.task_type for j in jobs]
    dominant = max(set(task_types), key=task_types.count) if task_types else ExternalTaskType.TRANSCRIBE_AUDIO

    merged = merge_batch_results(
        batch_id=args.batch_id,
        workspace=plan_data.get("workspace", ""),
        source_id=plan_data.get("source_id", ""),
        source_hash=plan_data.get("source_hash", ""),
        task_type=dominant,
        jobs=jobs,
    )

    print(f"Merge completado: {merged.status}")
    print(f"Segmentos: {len(merged.segments)} | Gaps: {len(merged.gaps_detected)}")
    print(f"Jobs completados: {merged.completed_jobs}/{merged.total_jobs}")

    merge_path = _REPO_ROOT / "state" / "burst_plans" / f"{args.batch_id}_merged.json"
    merge_path.write_text(
        json.dumps(merged.dict(), ensure_ascii=False, default=str, indent=2),
        encoding="utf-8"
    )
    print(f"Resultado guardado en: {merge_path}")


# ── Subcomando: report ────────────────────────────────────────────────────────

def cmd_report(args: argparse.Namespace) -> None:
    state_dir = _REPO_ROOT / "state" / "burst_plans"
    merged_path = state_dir / f"{args.batch_id}_merged.json"
    results_path = state_dir / f"{args.batch_id}_results.json"
    plan_path = state_dir / f"{args.batch_id}.json"

    report = {"batch_id": args.batch_id}

    if plan_path.exists():
        plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
        report["workspace"] = plan_data.get("workspace")
        report["mode"] = plan_data.get("selected_mode")
        report["planned_jobs"] = len(plan_data.get("jobs", []))

    if results_path.exists():
        data = json.loads(results_path.read_text(encoding="utf-8"))
        jobs = data.get("jobs", [])
        by_status: dict = {}
        for j in jobs:
            s = j.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
        report["jobs_by_status"] = by_status

    if merged_path.exists():
        merged = json.loads(merged_path.read_text(encoding="utf-8"))
        report["merge_status"] = merged.get("status")
        report["segments"] = len(merged.get("segments", []))
        report["gaps"] = len(merged.get("gaps_detected", []))

    print(json.dumps(report, ensure_ascii=False, indent=2))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="S9K Burst Processing CLI (Fase B1)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # plan
    p_plan = sub.add_parser("plan", help="Planificar procesamiento de una fuente")
    p_plan.add_argument("--workspace", required=True)
    p_plan.add_argument("--source", required=True)
    p_plan.add_argument("--mode", default="auto")
    p_plan.add_argument("--provider", default="mock")
    p_plan.add_argument("--dry-run", action="store_true", default=True)

    # dispatch
    p_dispatch = sub.add_parser("dispatch", help="Ejecutar jobs de un batch")
    p_dispatch.add_argument("--batch-id", required=True)
    p_dispatch.add_argument("--provider", default="mock")
    p_dispatch.add_argument("--dry-run", action="store_true", default=False)

    # status
    p_status = sub.add_parser("status", help="Estado de un batch")
    p_status.add_argument("--batch-id", required=True)

    # retry
    p_retry = sub.add_parser("retry", help="Reintentar un job especifico")
    p_retry.add_argument("--batch-id", required=True)
    p_retry.add_argument("--job-id", required=True)

    # cancel
    p_cancel = sub.add_parser("cancel", help="Cancelar un batch")
    p_cancel.add_argument("--batch-id", required=True)

    # validate
    p_validate = sub.add_parser("validate", help="Validar resultados de un batch")
    p_validate.add_argument("--batch-id", required=True)

    # merge
    p_merge = sub.add_parser("merge", help="Fusionar resultados de un batch")
    p_merge.add_argument("--batch-id", required=True)

    # report
    p_report = sub.add_parser("report", help="Informe final de un batch")
    p_report.add_argument("--batch-id", required=True)

    args = parser.parse_args()

    commands = {
        "plan": cmd_plan,
        "dispatch": cmd_dispatch,
        "status": cmd_status,
        "retry": cmd_retry,
        "cancel": cmd_cancel,
        "validate": cmd_validate,
        "merge": cmd_merge,
        "report": cmd_report,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
