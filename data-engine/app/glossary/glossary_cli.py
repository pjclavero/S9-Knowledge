"""CLI del glosario L5A.

Comandos:
  build   -- ejecuta extractores y puebla la DB
  stats   -- muestra estadísticas del workspace
  search  -- busca un término con el matcher
  export  -- genera initial_prompt.txt, hotwords.txt, glossary.json

Uso (desde la raíz del repo, con el venv):
  python data-engine/app/glossary/glossary_cli.py build --workspace leyenda --from-seed --from-neo4j --from-markdown
  python data-engine/app/glossary/glossary_cli.py stats --workspace leyenda
  python data-engine/app/glossary/glossary_cli.py search --workspace leyenda --query "tosi rambo"
  python data-engine/app/glossary/glossary_cli.py export --workspace leyenda --context "..." --limit 250 --output output/transcriptions/glossary-test/glossary.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Bootstrap de sys.path: data-engine/app debe estar en el path
_GLOSSARY_DIR = Path(__file__).resolve().parent
_APP_DIR = _GLOSSARY_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

_REPO_ROOT = _APP_DIR.parents[1]  # data-engine/app -> data-engine -> repo

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("glossary.cli")


def _get_store(db_path: str | None = None):
    from glossary.glossary_store import GlossaryStore
    if db_path:
        return GlossaryStore(db_path)
    return GlossaryStore()


def cmd_build(args: argparse.Namespace) -> int:
    from glossary.glossary_builder import GlossaryBuilder

    store = _get_store(args.db)
    builder = GlossaryBuilder(store)
    result = builder.build(
        workspace=args.workspace,
        from_seed=args.from_seed,
        from_neo4j=args.from_neo4j,
        from_markdown=args.from_markdown,
    )
    print(f"Build completado: workspace={result.workspace}")
    print(f"  seed:     {result.seed_count}")
    print(f"  neo4j:    {result.neo4j_count}")
    print(f"  markdown: {result.markdown_count}")
    print(f"  total upserted: {result.total_upserted}")
    if result.errors:
        print(f"  errores: {len(result.errors)}")
        for e in result.errors:
            print(f"    - {e}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    store = _get_store(args.db)
    stats = store.stats(args.workspace)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from glossary.glossary_matcher import GlossaryMatcher
    from glossary.glossary_store import GlossaryStore

    store = _get_store(args.db)
    matcher = GlossaryMatcher(store, args.workspace)
    results = matcher.search(args.query, limit=args.limit)
    if not results:
        print(f"No se encontraron resultados para: {args.query!r}")
        return 0
    print(f"Resultados para {args.query!r} ({len(results)} encontrados):")
    for r in results:
        t = r.term
        print(
            f"  [{r.match_type}] {t.canonical_term!r}"
            f" (score={r.score:.3f}, priority={t.priority:.3f},"
            f" type={t.term_type}, matched={r.matched_value!r})"
        )
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from glossary.glossary_exporter import GlossaryExporter

    store = _get_store(args.db)
    exporter = GlossaryExporter(store)

    # Determinar output_dir
    if args.output:
        # Si termina en .json, el directorio es el padre
        out_path = Path(args.output)
        if out_path.suffix == ".json":
            output_dir = out_path.parent
        else:
            output_dir = out_path
    else:
        output_dir = _REPO_ROOT / "output" / "transcriptions" / "glossary-test"

    paths = exporter.export(
        workspace=args.workspace,
        output_dir=output_dir,
        context=args.context,
        max_terms=args.limit,
        max_prompt_chars=args.max_prompt_chars,
    )
    print("Export generado:")
    for name, p in paths.items():
        size = p.stat().st_size if p.exists() else 0
        print(f"  {name}: {p} ({size} bytes)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="glossary_cli",
        description="CLI del glosario L5A",
    )
    parser.add_argument("--db", default=None, help="Ruta explicita a glossary.db")
    sub = parser.add_subparsers(dest="command", required=True)

    # build
    p_build = sub.add_parser("build", help="Ejecuta extractores y puebla la DB")
    p_build.add_argument("--workspace", required=True)
    p_build.add_argument("--from-seed", action="store_true", default=False)
    p_build.add_argument("--from-neo4j", action="store_true", default=False)
    p_build.add_argument("--from-markdown", action="store_true", default=False)

    # stats
    p_stats = sub.add_parser("stats", help="Estadisticas del workspace")
    p_stats.add_argument("--workspace", required=True)

    # search
    p_search = sub.add_parser("search", help="Busca un termino")
    p_search.add_argument("--workspace", required=True)
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=10)

    # export
    p_export = sub.add_parser("export", help="Genera ficheros de export para Whisper")
    p_export.add_argument("--workspace", required=True)
    p_export.add_argument("--context", default=None, help="Contexto del initial_prompt")
    p_export.add_argument("--limit", type=int, default=250)
    p_export.add_argument("--output", default=None, help="Dir o ruta .json de salida")
    p_export.add_argument("--max-prompt-chars", type=int, default=224, dest="max_prompt_chars")

    args = parser.parse_args()

    dispatch = {
        "build": cmd_build,
        "stats": cmd_stats,
        "search": cmd_search,
        "export": cmd_export,
    }
    fn = dispatch.get(args.command)
    if fn is None:
        parser.print_help()
        return 1
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
