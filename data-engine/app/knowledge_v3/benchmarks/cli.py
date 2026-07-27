# -*- coding: utf-8 -*-
"""CLI del arnes de benchmarks.

    python -m knowledge_v3.benchmarks.cli splits
    python -m knowledge_v3.benchmarks.cli describe --split dev
    python -m knowledge_v3.benchmarks.cli validate --split dev
    python -m knowledge_v3.benchmarks.cli ablations
    python -m knowledge_v3.benchmarks.cli score --split dev \\
        --predictions salida.json --ablation local_only --format md

No escribe en Neo4j, no llama a proveedores y no ejecuta el pipeline: solo
carga, valida y puntua.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import BENCHMARK_FORMAT_VERSION
from .ablations import ABLATIONS, resolve as resolve_ablation
from .harness import gold_summary, run
from .loader import (
    DatasetError,
    PredictionBundle,
    available_splits,
    load_gold,
    validate_gold,
)
from .matching import MatchConfig
from .report import to_json, to_markdown


def _load(split: str, root: Path | None) -> Any:
    return load_gold(split, root=root)


def cmd_splits(args: argparse.Namespace) -> int:
    for split in available_splits(args.root):
        print(split)
    return 0


def cmd_describe(args: argparse.Namespace) -> int:
    gold = _load(args.split, args.root)
    payload = {
        "benchmark_format_version": BENCHMARK_FORMAT_VERSION,
        "summary": gold_summary(gold),
        "sources": gold.manifest["sources"],
        "phenomena_index": gold.manifest["phenomena_index"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    gold = _load(args.split, args.root)
    try:
        validate_gold(gold)
    except DatasetError as exc:
        print(f"NO CONFORME: {exc}", file=sys.stderr)
        return 1
    total = gold_summary(gold)
    print(
        f"split {args.split}: {total['sources']} fuentes, "
        f"{total['episodes']} episodios, {total['mentions']} menciones, "
        f"{total['claims']} claims, {total['assertions']} afirmaciones — "
        "todo valida contra los contratos congelados"
    )
    return 0


def cmd_ablations(args: argparse.Namespace) -> int:
    for label in sorted(ABLATIONS):
        print(json.dumps(ABLATIONS[label].as_dict(), ensure_ascii=False, sort_keys=True))
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    gold = _load(args.split, args.root)
    if args.predictions == "-":
        pred = PredictionBundle.from_dict(json.load(sys.stdin))
    elif args.predictions == "gold":
        pred = PredictionBundle.from_gold(gold)
    else:
        pred = PredictionBundle.from_path(args.predictions)
    if args.ablation:
        pred.ablation = args.ablation
    config = MatchConfig(
        span_mode=args.span_mode,
        overlap_threshold=args.overlap_threshold,
        claim_key_extra=tuple(args.claim_key_extra or ()),
        fact_key_includes_validity=args.fact_validity,
        symmetric_predicates=gold.symmetric_predicates,
    )
    report = run(gold, pred, config=config, ablation=resolve_ablation(pred.ablation))
    text = to_markdown(report) if args.format == "md" else to_json(report)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="knowledge_v3.benchmarks", description=__doc__)
    parser.add_argument("--root", type=Path, default=None, help="raiz alternativa de datasets/")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("splits", help="lista los splits instalados")
    p.set_defaults(func=cmd_splits)

    p = sub.add_parser("describe", help="composicion del dataset")
    p.add_argument("--split", default="dev")
    p.set_defaults(func=cmd_describe)

    p = sub.add_parser("validate", help="valida el dataset contra los contratos")
    p.add_argument("--split", default="dev")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("ablations", help="lista las ablaciones etiquetadas")
    p.set_defaults(func=cmd_ablations)

    p = sub.add_parser("score", help="puntua una prediccion contra el gold")
    p.add_argument("--split", default="dev")
    p.add_argument(
        "--predictions",
        required=True,
        help="ruta al JSON de predicciones, '-' para stdin, o 'gold' para la prueba de cordura",
    )
    p.add_argument("--ablation", default=None)
    p.add_argument("--span-mode", dest="span_mode", default="exact", choices=("exact", "overlap"))
    p.add_argument("--overlap-threshold", dest="overlap_threshold", type=float, default=0.5)
    p.add_argument(
        "--claim-key-extra",
        dest="claim_key_extra",
        action="append",
        choices=("predicate", "negated", "direction"),
        help="componentes extra de la clave de claim (se registran en el informe)",
    )
    p.add_argument("--fact-validity", dest="fact_validity", action="store_true")
    p.add_argument("--format", default="json", choices=("json", "md"))
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_score)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
