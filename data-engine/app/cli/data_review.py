"""CLI del pipeline de revisión S9 Knowledge.

Uso:
  python data-engine/app/cli/data_review.py <subcomando> [opciones]

Subcomandos:
  segment         Segmenta la transcripción
  classify        Clasifica los segmentos
  extract         Extrae candidatos
  validate        Valida candidatos contra el schema RPG
  resolve         Resuelve entidades contra Neo4j (solo lectura)
  decide          Decide auto_approve/needs_review/auto_reject
  run             Ejecuta el pipeline completo (--dry-run obligatorio)
  ingest-approved Ingesta aprobada en Neo4j (--dry-run obligatorio en esta fase)
  summary         Muestra resumen del estado del pipeline
  audit-graph     Audita calidad del grafo Neo4j (solo lectura)
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
from pathlib import Path

# Bootstrap sys.path
_CLI_DIR = Path(__file__).resolve().parent
_APP_DIR = _CLI_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

# Repo root: data-engine/app/cli → data-engine/app → data-engine → repo
_REPO_ROOT = _APP_DIR.parents[1]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("data_review")


def cmd_segment(args):
    from review import segmenter
    path = segmenter.run(args.workspace, args.source_id, _REPO_ROOT)
    print(f"OK: {path}")


def cmd_classify(args):
    from review import classifier
    path = classifier.run(args.workspace, args.source_id, _REPO_ROOT)
    print(f"OK: {path}")


def cmd_extract(args):
    from review import extractor
    path = extractor.run(args.workspace, args.source_id, _REPO_ROOT)
    print(f"OK: {path}")


def cmd_validate(args):
    from review import validator
    path = validator.run(args.workspace, args.source_id, _REPO_ROOT)
    print(f"OK: {path}")


def cmd_resolve(args):
    from review import resolver
    path = resolver.run(args.workspace, args.source_id, _REPO_ROOT)
    print(f"OK: {path}")


def cmd_decide(args):
    from review import auto_decider
    path = auto_decider.run(args.workspace, args.source_id, _REPO_ROOT)
    print(f"OK: {path}")


def cmd_run(args):
    from review.pipeline import run_pipeline
    if not args.dry_run:
        print("ERROR: --dry-run es obligatorio en esta fase. Usa: --dry-run")
        sys.exit(1)

    result = run_pipeline(args.workspace, args.source_id, _REPO_ROOT, dry_run=True)
    summary = result.get("summary", {})

    print(f"\n=== Pipeline completado ===")
    print(f"  Workspace:     {args.workspace}")
    print(f"  Source ID:     {args.source_id}")
    print(f"  Auto-aprobados:  {summary.get('auto_approve', 0)}")
    print(f"  Pendientes:      {summary.get('needs_review', 0)}")
    print(f"  Rechazados:      {summary.get('auto_reject', 0)}")
    print(f"  Total:           {summary.get('total', 0)}")
    print()

    out_dir = _REPO_ROOT / "output" / "reviews" / args.workspace / args.source_id
    print(f"Outputs en: {out_dir}")
    for f in sorted(out_dir.iterdir()) if out_dir.exists() else []:
        print(f"  {f.name}")


def cmd_ingest_approved(args):
    from review import ingest_approved
    if not args.dry_run:
        print(_DRY_RUN_ABORT_MSG)
        sys.exit(1)
    result = ingest_approved.run(args.workspace, args.source_id, _REPO_ROOT, dry_run=True)
    print(f"\nDRY-RUN completado: {result}")


_DRY_RUN_ABORT_MSG = (
    "ABORTADO: ingest-approved requiere autorización explícita. "
    "Usa --dry-run para simular sin escribir en Neo4j. "
    "Para escritura real, obtén autorización explícita del administrador."
)


def cmd_summary(args):
    from review.review_store import ReviewStore
    store = ReviewStore(_REPO_ROOT)
    state = store.get_state(args.workspace, args.source_id)
    if not state:
        print(f"Sin estado para {args.workspace}/{args.source_id}")
        return
    print(f"\n=== Estado del pipeline: {args.workspace}/{args.source_id} ===")
    for step, info in state.items():
        print(f"  {step:20s}: {info.get('status')} @ {info.get('updated_at', '')[:19]}")
        details = info.get("details", {})
        if details:
            for k, v in details.items():
                print(f"    {k}: {v}")


def cmd_audit_graph(args):
    from review.audit_graph import run as audit_run
    md_path = audit_run(args.workspace, _REPO_ROOT)
    print(f"OK: {md_path}")
    print(md_path.read_text(encoding="utf-8")[:2000])


def main():
    parser = argparse.ArgumentParser(
        description="Pipeline de revisión S9 Knowledge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # Argumentos comunes
    def _add_common(p):
        p.add_argument("--workspace", required=True, help="Nombre del workspace")
        p.add_argument("--source-id", required=True, dest="source_id", help="ID del source")

    def _add_dry_run(p):
        p.add_argument("--dry-run", action="store_true", dest="dry_run", help="Simular sin escribir")

    # segment
    p = sub.add_parser("segment", help="Segmenta la transcripción")
    _add_common(p)

    # classify
    p = sub.add_parser("classify", help="Clasifica segmentos")
    _add_common(p)

    # extract
    p = sub.add_parser("extract", help="Extrae candidatos")
    _add_common(p)

    # validate
    p = sub.add_parser("validate", help="Valida candidatos")
    _add_common(p)

    # resolve
    p = sub.add_parser("resolve", help="Resuelve entidades en Neo4j (solo lectura)")
    _add_common(p)

    # decide
    p = sub.add_parser("decide", help="Decide auto_approve/needs_review/auto_reject")
    _add_common(p)

    # run
    p = sub.add_parser("run", help="Ejecuta pipeline completo (--dry-run obligatorio)")
    _add_common(p)
    _add_dry_run(p)

    # ingest-approved
    p = sub.add_parser("ingest-approved", help="Ingesta aprobada (--dry-run obligatorio en esta fase)")
    _add_common(p)
    _add_dry_run(p)

    # summary
    p = sub.add_parser("summary", help="Resumen del estado del pipeline")
    _add_common(p)

    # audit-graph
    p = sub.add_parser("audit-graph", help="Audita calidad del grafo Neo4j (solo lectura)")
    p.add_argument("--workspace", required=True, help="Nombre del workspace")

    args = parser.parse_args()

    dispatch = {
        "segment": cmd_segment,
        "classify": cmd_classify,
        "extract": cmd_extract,
        "validate": cmd_validate,
        "resolve": cmd_resolve,
        "decide": cmd_decide,
        "run": cmd_run,
        "ingest-approved": cmd_ingest_approved,
        "summary": cmd_summary,
        "audit-graph": cmd_audit_graph,
    }
    fn = dispatch.get(args.cmd)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
