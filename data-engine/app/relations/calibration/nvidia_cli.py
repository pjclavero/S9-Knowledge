# -*- coding: utf-8 -*-
"""CLI del probe de calibracion NVIDIA NIM en modo sombra.

Uso (la API key se lee del entorno via registry; NUNCA se pasa por linea de comando):

    export S9K_NVIDIA_ENABLED=true
    export S9K_NVIDIA_API_KEY=...        # desde un EnvironmentFile privado (0600)
    export S9K_NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
    python -m relations.calibration.nvidia_cli \
        --model meta/llama-3.1-70b-instruct \
        --repetitions 2 \
        --out /ruta/informe.json

Sin `S9K_NVIDIA_API_KEY` en el entorno, el probe FALLA CERRADO sin tocar red.
Este CLI SOLO escribe el fichero indicado por `--out` (artefacto). Nunca escribe
en Neo4j ni toca infraestructura productiva. La clave nunca se imprime.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from relations.calibration.nvidia_shadow_probe import run_probe


def _default_model() -> str:
    models = os.environ.get("S9K_NVIDIA_REVIEW_MODELS", "").split(",")
    for m in models:
        if m.strip():
            return m.strip()
    return "meta/llama-3.1-70b-instruct"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="relations.calibration.nvidia_cli",
        description="Probe de calibracion del proveedor NVIDIA NIM en modo sombra.",
    )
    p.add_argument("--model", default=_default_model())
    p.add_argument("--repetitions", type=int, default=3)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument(
        "--no-redact-endpoint",
        action="store_true",
        help="No ofuscar el host del endpoint en el informe (por defecto SE ofusca).",
    )
    return p


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_probe(
        model=args.model,
        repetitions=args.repetitions,
        redact_endpoint=not args.no_redact_endpoint,
    )
    text = report.to_json()
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"Informe escrito en {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
