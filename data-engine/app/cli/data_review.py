"""CLI del pipeline de revisión S9 Knowledge.

Uso:
  python data-engine/app/cli/data_review.py <subcomando> [opciones]

Subcomandos:
  segment         Segmenta la transcripción
  classify        Clasifica los segmentos
  extract         Extrae candidatos [--extractor {heuristic,llm,hybrid}]
  validate        Valida candidatos contra el schema RPG
  resolve         Resuelve entidades contra Neo4j (solo lectura)
  decide          Decide auto_approve/needs_review/auto_reject
  run             Ejecuta el pipeline completo (--dry-run obligatorio) [--extractor ...]
  ingest-approved Ingesta aprobada en Neo4j (--dry-run obligatorio / S9K_ALLOW_REAL_INGEST)
  summary         Muestra resumen del estado del pipeline
  audit-graph     Audita calidad del grafo Neo4j (solo lectura)
  quality-report  Genera informe de calidad sobre outputs existentes
"""
from __future__ import annotations
import argparse
import json
import logging
import os
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
    mode = getattr(args, "extractor", None)
    # Pasar extractor como env si se especifica
    if mode:
        os.environ["S9K_REVIEW_EXTRACTOR"] = mode
        log.info("Extractor seleccionado: %s (S9K_REVIEW_EXTRACTOR=%s)", mode, mode)
    # El paso extract aislado (usado por el benchmark) DEBE honrar el extractor
    # solicitado. extractor.run() es solo heurístico; para llm/hybrid delegamos
    # en el dispatch del pipeline (heurístico + LLM Ollama, con degradación
    # explícita si Ollama no responde).
    if mode in ("llm", "hybrid"):
        from review.pipeline import _run_extract_step
        in_path = (
            _REPO_ROOT / "output" / "reviews" / args.workspace / args.source_id
            / "segments.classified.json"
        )
        if not in_path.exists():
            raise FileNotFoundError(f"segments.classified.json no encontrado: {in_path}")
        with in_path.open(encoding="utf-8") as f:
            classified = json.load(f)
        _run_extract_step(args.workspace, args.source_id, _REPO_ROOT, mode, classified)
        print(f"OK: {in_path.parent / 'candidates.json'}")
    else:
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

    # Pasar extractor como env si se especifica
    if getattr(args, "extractor", None):
        os.environ["S9K_REVIEW_EXTRACTOR"] = args.extractor
        log.info("Extractor seleccionado: %s (S9K_REVIEW_EXTRACTOR=%s)", args.extractor, args.extractor)

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
        # El módulo revisa S9K_ALLOW_REAL_INGEST internamente; el CLI informa antes
        allow_real = os.environ.get("S9K_ALLOW_REAL_INGEST", "").strip().lower()
        if allow_real != "true":
            print(ingest_approved._ENV_GUARD_ABORT_MSG)
            sys.exit(1)

    try:
        result = ingest_approved.run(args.workspace, args.source_id, _REPO_ROOT, dry_run=args.dry_run)
        print(f"\nCompletado: {result}")
    except (RuntimeError, ValueError) as e:
        print(f"\n{e}")
        sys.exit(1)


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

    # Mostrar decision_reasons agregados si existen en decisions.json
    decisions_path = (
        _REPO_ROOT / "output" / "reviews" / args.workspace / args.source_id / "decisions.json"
    )
    if decisions_path.exists():
        try:
            decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
            reasons_agg: dict[str, int] = {}
            for d in decisions:
                for r in d.get("decision_reason", []):
                    reasons_agg[r] = reasons_agg.get(r, 0) + 1
            if reasons_agg:
                print(f"\n  Decision reasons agregados:")
                for r, count in sorted(reasons_agg.items(), key=lambda x: -x[1])[:10]:
                    print(f"    [{count:3d}] {r}")
        except Exception as e:
            log.debug("No se pudieron leer decision_reasons: %s", e)


def cmd_audit_graph(args):
    from review.audit_graph import run as audit_run
    md_path = audit_run(args.workspace, _REPO_ROOT)
    print(f"OK: {md_path}")
    print(md_path.read_text(encoding="utf-8")[:2000])


def cmd_quality_report(args):
    from review.quality_report import generate
    try:
        md_path = generate(args.workspace, args.source_id, _REPO_ROOT)
        print(f"OK: {md_path}")
        print()
        print(md_path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)


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

    def _add_extractor(p):
        p.add_argument(
            "--extractor",
            choices=["heuristic", "llm", "hybrid"],
            default=None,
            help="Extractor a usar (setea S9K_REVIEW_EXTRACTOR; el pipeline lo lee)",
        )

    # segment
    p = sub.add_parser("segment", help="Segmenta la transcripción")
    _add_common(p)

    # classify
    p = sub.add_parser("classify", help="Clasifica segmentos")
    _add_common(p)

    # extract
    p = sub.add_parser("extract", help="Extrae candidatos")
    _add_common(p)
    _add_extractor(p)

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
    _add_extractor(p)

    # ingest-approved
    p = sub.add_parser(
        "ingest-approved",
        help="Ingesta aprobada (--dry-run obligatorio / S9K_ALLOW_REAL_INGEST=true para escritura real)"
    )
    _add_common(p)
    _add_dry_run(p)

    # summary
    p = sub.add_parser("summary", help="Resumen del estado del pipeline")
    _add_common(p)

    # audit-graph
    p = sub.add_parser("audit-graph", help="Audita calidad del grafo Neo4j (solo lectura)")
    p.add_argument("--workspace", required=True, help="Nombre del workspace")

    # quality-report
    p = sub.add_parser("quality-report", help="Genera informe de calidad sobre outputs existentes")
    _add_common(p)

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
        "quality-report": cmd_quality_report,
    }
    fn = dispatch.get(args.cmd)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
