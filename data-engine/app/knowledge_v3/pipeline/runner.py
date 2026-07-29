# -*- coding: utf-8 -*-
"""Corre la cadena sobre un split y la puntua con el arnes existente.

    export PYTHONPATH=data-engine/app
    python -m knowledge_v3.pipeline.runner --split dev --ablation local_only
    python -m knowledge_v3.pipeline.runner --split dev --ablation nominal --ollama
    python -m knowledge_v3.pipeline.runner --split dev --all-ablations --out-dir docs/v3/measurements

Este modulo NO puntua nada por su cuenta: ejecuta la cadena, serializa la
salida con `pipeline.bundle.to_bundle` y se la pasa a `benchmarks.harness.run`
y a `benchmarks.report`. Los numeros salen del arnes que ya existe, con sus
reglas (denominador cero = `null`, metrica emparejada siempre con su cobertura
y su variante estricta).

El writer va SIEMPRE en dry-run: este modulo no admite `--apply` y no construye
ningun driver. No hay bandera que lo cambie, a proposito.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..benchmarks.ablations import labels as ablation_labels
from ..benchmarks.harness import run as score
from ..benchmarks.loader import load_gold
from ..benchmarks.matching import MatchConfig
from ..benchmarks.report import to_json, to_markdown
from .bundle import to_bundle
from .config import PipelineConfig
from .errors import PipelineError
from .pipeline import KnowledgePipeline
from .sources import (
    cases_from_gold,
    catalog_entries,
    entity_catalog,
    profile_of,
    workspace_lexicon,
)
from .bridge import entities_from_catalog

#: Instante inyectado de la corrida. Es DATO: la cadena no llama al reloj, y
#: fijarlo aqui es lo que hace que dos corridas del mismo split sean
#: comparables byte a byte.
RUN_NOW = "2026-07-27T12:00:00Z"

#: Ablaciones que este runner sabe ejecutar. `gold_identity` queda fuera a
#: proposito: es la prueba de cordura del arnes contra si mismo, no una corrida
#: del sistema, y el propio 08-benchmarks.md dice que no debe aparecer en
#: ninguna tabla de resultados.
RUNNABLE = tuple(l for l in ablation_labels() if l != "gold_identity")


def _frozen_clock(moment: str):
    parsed = datetime.fromisoformat(moment.replace("Z", "+00:00")).astimezone(timezone.utc)
    return lambda: parsed


def build_config(
    gold,
    *,
    ablation: str,
    workspace: str,
    ollama_client: Any = None,
    external_port: Any = None,
    visual_provider: Any = None,
) -> PipelineConfig:
    """Configuracion de la corrida, con la ablacion ya aplicada."""
    profile = profile_of(gold, "generic")
    profiles = {pid: profile_of(gold, pid) for pid in gold.profiles}
    base = PipelineConfig(
        workspace=workspace,
        collection_id=f"collection:{gold.split}",
        profile=profile,
        now=RUN_NOW,
        ingested_at=RUN_NOW,
        catalog=entity_catalog(gold, workspace),
        lexicon=workspace_lexicon(gold, profile),
        ollama_client=ollama_client,
        external_port=external_port,
        visual_provider=visual_provider,
        writer_clock=_frozen_clock(RUN_NOW),
        ablation=ablation,
    )
    return base.for_ablation(ablation, profiles=profiles)


def run_one(
    gold,
    ablation: str,
    *,
    workspace: str,
    entry: str = "episodes",
    ollama_client: Any = None,
    external_port: Any = None,
    run_id: Optional[str] = None,
    engine_isolated: bool = False,
) -> tuple[dict, Any]:
    """Una corrida + su informe. Devuelve `(report, pipeline_result)`.

    `engine_isolated` fuerza entidades Y claims gold a la vez. Hace falta
    porque las ablaciones `gold_claims_to_engine` y `gold_entities_to_engine`
    NO aislan el motor por separado (11-e2e.md, defecto D-7): un claim gold
    apunta a menciones gold, y si las resoluciones son reales el motor no
    encuentra a que entidad corresponden. La combinacion queda declarada en el
    informe, no escondida.
    """
    config = build_config(
        gold,
        ablation=ablation,
        workspace=workspace,
        ollama_client=ollama_client,
        external_port=external_port,
    )
    if engine_isolated:
        config = dataclasses.replace(config, entity_source="gold", claim_source="gold")
    pipeline = KnowledgePipeline(config)
    entities = entities_from_catalog(catalog_entries(gold))
    result = pipeline.run(cases_from_gold(gold, entry=entry), catalog_entities=entities)
    bundle = to_bundle(
        result,
        split=gold.split,
        run_id=run_id or f"{gold.split}-{ablation}",
        ablation=ablation,
        extra_metadata={"entry": entry, "engine_isolated": engine_isolated},
    )
    report = score(
        gold,
        bundle,
        config=MatchConfig(symmetric_predicates=gold.symmetric_predicates),
        ablation=ablation,
    )
    return report, result


def write_reports(report: dict, out_dir: Path, stem: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    json_path = out_dir / f"{stem}.json"
    json_path.write_text(to_json(report), encoding="utf-8")
    paths.append(json_path)
    md_path = out_dir / f"{stem}.md"
    md_path.write_text(to_markdown(report), encoding="utf-8")
    paths.append(md_path)
    return paths


def _ollama_client(url: Optional[str], model: Optional[str], timeout: float):
    from ..extraction.ollama_client import OllamaClient, OllamaConfig

    overrides: dict[str, Any] = {"timeout": timeout}
    if url:
        overrides["url"] = url
    if model:
        overrides["model"] = model
    return OllamaClient(config=OllamaConfig.from_env(**overrides))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ejecuta la cadena V3 sobre un split y la puntua con el arnes."
    )
    parser.add_argument("--split", default="dev")
    parser.add_argument("--workspace", default=None, help="por defecto: bench-<split>")
    parser.add_argument("--ablation", default="local_only")
    parser.add_argument("--all-ablations", action="store_true")
    parser.add_argument("--entry", choices=("episodes", "raw"), default="episodes")
    parser.add_argument("--ollama", action="store_true", help="usa Ollama de verdad")
    parser.add_argument("--ollama-url", default=None)
    parser.add_argument("--ollama-model", default=None)
    parser.add_argument("--ollama-timeout", type=float, default=300.0)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument(
        "--engine-isolated",
        action="store_true",
        help="entidades Y claims gold a la vez: aisla el motor de verdad (D-7)",
    )
    parser.add_argument("--stem-suffix", default="", help="sufijo del fichero de salida")
    parser.add_argument("--format", choices=("json", "md", "both"), default="both")
    args = parser.parse_args(argv)

    gold = load_gold(args.split)
    workspace = args.workspace or f"bench-{args.split}"
    client = (
        _ollama_client(args.ollama_url, args.ollama_model, args.ollama_timeout)
        if args.ollama
        else None
    )

    ablations = RUNNABLE if args.all_ablations else (args.ablation,)
    out_dir = Path(args.out_dir) if args.out_dir else None

    for label in ablations:
        try:
            report, _ = run_one(
                gold,
                label,
                workspace=workspace,
                entry=args.entry,
                ollama_client=client,
                engine_isolated=args.engine_isolated,
            )
        except PipelineError as exc:
            print(f"[{label}] NO EJECUTADA: {exc}", file=sys.stderr)
            continue
        if out_dir:
            stem = f"{args.split}-{label}{args.stem_suffix}"
            paths = write_reports(report, out_dir, stem)
            print(f"[{label}] " + " ".join(str(p) for p in paths))
        elif args.format == "json":
            print(to_json(report))
        elif args.format == "md":
            print(to_markdown(report))
        else:
            print(to_markdown(report))
            print(json.dumps({"ablation": label}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
