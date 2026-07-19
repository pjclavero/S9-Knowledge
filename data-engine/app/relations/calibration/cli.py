# -*- coding: utf-8 -*-
"""CLI del probe de calibracion Ollama en modo sombra.

Uso (endpoint SIEMPRE explicito; no hay default productivo):

    python -m relations.calibration.cli \
        --endpoint http://localhost:11434/v1 \
        --model qwen2.5:7b \
        --repetitions 3 \
        --out /ruta/informe.json

El endpoint puede tomarse tambien de la variable de entorno S9K_OLLAMA_BASE_URL,
pero NUNCA se asume un valor por defecto: si no hay endpoint, el probe FALLA
CERRADO sin tocar red.

Este CLI SOLO escribe el fichero de informe indicado por `--out` (artefacto de
calibracion). NUNCA escribe en Neo4j ni toca infraestructura productiva.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from relations.calibration.ollama_shadow_probe import run_probe


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="relations.calibration.cli",
        description="Probe de calibracion del LLM local (Ollama) en modo sombra.",
    )
    p.add_argument(
        "--endpoint",
        default=os.environ.get("S9K_OLLAMA_BASE_URL"),
        help="URL OpenAI-compatible EXPLICITA, p.ej. http://localhost:11434/v1. "
        "Sin este valor (ni S9K_OLLAMA_BASE_URL) el probe falla cerrado.",
    )
    p.add_argument("--model", default=os.environ.get("S9K_OLLAMA_MODEL", "qwen2.5:7b"))
    p.add_argument("--repetitions", type=int, default=3)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--max-retries", type=int, default=1)
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Ruta de salida del informe JSON (artefacto). Si se omite, se imprime a stdout.",
    )
    p.add_argument(
        "--no-redact-endpoint",
        action="store_true",
        help="No ofuscar el host del endpoint en el informe (por defecto SE ofusca).",
    )
    return p


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.endpoint:
        print(
            "ERROR: endpoint ausente. Pase --endpoint o defina S9K_OLLAMA_BASE_URL. "
            "No existe endpoint por defecto (fallo cerrado).",
            file=sys.stderr,
        )
        return 2

    report = run_probe(
        endpoint=args.endpoint,
        model=args.model,
        repetitions=args.repetitions,
        timeout=args.timeout,
        max_retries=args.max_retries,
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
