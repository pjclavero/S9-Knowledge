# -*- coding: utf-8 -*-
"""Generacion determinista del dataset gold en disco.

Los ficheros de ``datasets/dev`` estan versionados en el repositorio, pero se
generan desde aqui. Un test comprueba que regenerarlos produce EXACTAMENTE los
mismos bytes: asi el dataset no puede derivar de su autoria sin que el gate se
ponga rojo, que es el mismo mecanismo que usan los ejemplos de contratos.

Uso:  python -m knowledge_v3.benchmarks.authoring.build [--check]
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .. import BENCHMARK_FORMAT_VERSION
from .catalog import entity_catalog, game_profile_gold, game_profile_narrow
from .common import DATASET_VERSION, SourceGold
from .sources_multimodal import build_ocr, build_table, build_transcript
from .sources_text import build_kestrel, build_leyenda, build_mareas

SPLIT = "dev"
DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets"

#: Constructores de fuente, en orden estable.
BUILDERS = (
    build_leyenda,
    build_mareas,
    build_kestrel,
    build_table,
    build_transcript,
    build_ocr,
)

#: Fichero -> atributo de `SourceGold`. El orden es el de la cadena gold.
SOURCE_FILES = (
    ("source_asset", None),
    ("episodes", "episodes"),
    ("fragments", "fragments"),
    ("mentions", "mentions"),
    ("resolutions", "resolutions"),
    ("claims", "claims"),
    ("assertions", "assertions"),
    ("plans", "plans"),
    ("negatives", "negatives"),
)


def dumps(obj: Any) -> str:
    """Serializacion estable en disco: indentada, ordenada y con salto final."""
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _wrap(kind: str, source: SourceGold | None, documents: list[Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "benchmark_file": kind,
        "split": SPLIT,
        "dataset_version": DATASET_VERSION,
        "format_version": BENCHMARK_FORMAT_VERSION,
        "documents": documents,
    }
    if source is not None:
        payload["source_id"] = source.source_id
        payload["world"] = source.world
    return payload


def _phenomena(source: SourceGold) -> list[str]:
    seen: set[str] = set()
    for ep in source.episodes:
        seen.update(ep["metadata"].get("phenomena") or [])
    for c in source.claims:
        seen.update(c["metadata"].get("phenomena") or [])
    for a in source.assertions:
        seen.update(a["metadata"].get("phenomena") or [])
    for n in source.negatives:
        seen.add(n["kind"])
    return sorted(seen)


def _counts(source: SourceGold) -> dict[str, int]:
    extractor_claims = [
        c
        for c in source.claims
        if c["metadata"].get("role", "EXTRACTOR_AND_ENGINE") == "EXTRACTOR_AND_ENGINE"
    ]
    return {
        "episodes": len(source.episodes),
        "fragments": len(source.fragments),
        "mentions": len(source.mentions),
        "resolutions": len(source.resolutions),
        "claims": len(source.claims),
        "claims_extractor_gold": len(extractor_claims),
        "assertions": len(source.assertions),
        "plans": len(source.plans),
        "decisions": sum(len(p["decisions"]) for p in source.plans),
        "operations": sum(len(p["mutation_operations"]) for p in source.plans),
        "negatives": len(source.negatives),
    }


def build_dataset() -> dict[str, str]:
    """Construye el dataset completo. Devuelve {ruta relativa: contenido}."""
    sources = [b() for b in BUILDERS]
    files: dict[str, str] = {}

    files[f"{SPLIT}/catalog/entities.json"] = dumps(entity_catalog())
    files[f"{SPLIT}/catalog/game_profile_generic.json"] = dumps(
        _wrap("game_profile", None, [game_profile_gold()])
    )
    files[f"{SPLIT}/catalog/game_profile_narrow.json"] = dumps(
        _wrap("game_profile", None, [game_profile_narrow()])
    )

    manifest_sources = []
    for src in sources:
        base = f"{SPLIT}/sources/{src.source_id}"
        for kind, attr in SOURCE_FILES:
            documents = [src.asset] if attr is None else getattr(src, attr)
            files[f"{base}/{kind}.json"] = dumps(_wrap(kind, src, documents))
        files[f"{base}/reference_text.json"] = dumps(
            _wrap(
                "reference_text",
                src,
                [
                    {"episode_id": eid, "text": text}
                    for eid, text in sorted(src.reference_text.items())
                ],
            )
        )
        manifest_sources.append(
            {
                "source_id": src.source_id,
                "world": src.world,
                "title": src.title,
                "description": src.description,
                "source_kind": src.asset["source_kind"],
                "collection_id": src.collection_id,
                "modalities": sorted({e["modality"] for e in src.episodes}),
                "counts": _counts(src),
                "phenomena": _phenomena(src),
            }
        )

    totals: dict[str, int] = {}
    for entry in manifest_sources:
        for k, v in entry["counts"].items():
            totals[k] = totals.get(k, 0) + v

    phenomena_index: dict[str, list[str]] = {}
    for entry in manifest_sources:
        for ph in entry["phenomena"]:
            phenomena_index.setdefault(ph, []).append(entry["source_id"])

    manifest = {
        "benchmark_file": "manifest",
        "split": SPLIT,
        "dataset_version": DATASET_VERSION,
        "format_version": BENCHMARK_FORMAT_VERSION,
        "purpose": (
            "Dataset gold de DESARROLLO. No es held-out: quien implementa puede "
            "verlo. El held-out lo prepara un equipo independiente y se instala "
            "como split hermano sin tocar el arnes."
        ),
        "catalog_files": [
            "catalog/entities.json",
            "catalog/game_profile_generic.json",
            "catalog/game_profile_narrow.json",
        ],
        "sources": manifest_sources,
        "totals": totals,
        "phenomena_index": {k: sorted(v) for k, v in sorted(phenomena_index.items())},
        "file_hashes": {
            path: hashlib.sha256(content.encode("utf-8")).hexdigest()
            for path, content in sorted(files.items())
        },
    }
    files[f"{SPLIT}/manifest.json"] = dumps(manifest)
    return files


def write_dataset(root: Path | None = None) -> list[Path]:
    root = root or DATASETS_DIR
    written = []
    for rel, content in sorted(build_dataset().items()):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def check_dataset(root: Path | None = None) -> list[str]:
    """Devuelve la lista de ficheros que han derivado respecto a la autoria."""
    root = root or DATASETS_DIR
    drift = []
    for rel, content in sorted(build_dataset().items()):
        path = root / rel
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            drift.append(rel)
    return drift


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--check" in argv:
        drift = check_dataset()
        if drift:
            print("dataset derivado respecto a la autoria:")
            for rel in drift:
                print(f"  {rel}")
            return 1
        print("dataset al dia")
        return 0
    paths = write_dataset()
    print(f"escritos {len(paths)} ficheros en {DATASETS_DIR}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
