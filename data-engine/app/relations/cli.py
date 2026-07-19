# -*- coding: utf-8 -*-
"""CLI DRY-RUN del pipeline de relaciones (`relations.cli`).

Ejecuta `relations.pipeline.run_pipeline` sobre un fichero de entrada JSON y
escribe el resultado en un fichero de salida (o stdout). Es una envoltura fina y
NO destructiva:

  * DRY-RUN obligatorio: no hay ningun flag de escritura/apply/persistencia. El
    pipeline nunca toca Neo4j, ni red, ni bases de datos productivas.
  * Entrada y salida EXPLICITAS (`--input`, `--output`); nunca sobrescribe sin
    que el operador lo indique.
  * SIN credenciales por argumento y SIN endpoint productivo por defecto: los
    proveedores en sombra quedan deshabilitados salvo que se activen, y aun asi
    fallan cerrado sin transporte inyectado (no disponible desde esta CLI).
  * Limites configurables por argumento.
  * Codigo de salida: 0 si la ejecucion termina, 2 en error de uso/entrada.

No toca la CLI global del proyecto.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from relations.pipeline import PipelineConfig, PipelineError, run_pipeline, to_json, to_jsonl


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="relations.cli",
        description="Pipeline de extraccion de relaciones en DRY-RUN (sin escritura, sin red).",
    )
    p.add_argument("--input", "-i", required=True, help="Ruta del JSON de entrada (payload del pipeline).")
    p.add_argument("--output", "-o", default=None, help="Ruta del fichero de salida (por defecto: stdout).")
    p.add_argument("--format", choices=("json", "jsonl"), default="json", help="Formato de salida.")
    p.add_argument("--max-pairs-per-segment", type=int, default=None, help="Limite de pares por segmento.")
    p.add_argument("--max-entities-per-segment", type=int, default=None, help="Limite de entidades por segmento.")
    p.add_argument("--max-segments-per-doc", type=int, default=None, help="Limite de segmentos por documento.")
    p.add_argument("--max-text-chars", type=int, default=None, help="Limite de caracteres por segmento.")
    p.add_argument(
        "--context-mode",
        choices=("sentence", "paragraph", "segment", "distance"),
        default=None,
        help="Modo de contexto del emparejamiento.",
    )
    return p


def _config_overrides(args: argparse.Namespace, base: Optional[dict]) -> PipelineConfig:
    data = dict(base or {})
    if args.max_pairs_per_segment is not None:
        data["max_pairs_per_segment"] = args.max_pairs_per_segment
    if args.max_entities_per_segment is not None:
        data["max_entities_per_segment"] = args.max_entities_per_segment
    if args.max_segments_per_doc is not None:
        data["max_segments_per_doc"] = args.max_segments_per_doc
    if args.max_text_chars is not None:
        data["max_text_chars"] = args.max_text_chars
    if args.context_mode is not None:
        data["context_mode"] = args.context_mode
    # Los proveedores en sombra NO se habilitan desde la CLI (sin transporte real).
    from relations.pipeline import config_from_dict

    return config_from_dict(data)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        with open(args.input, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error leyendo la entrada: {exc}\n")

    try:
        config = _config_overrides(args, payload.get("config") if isinstance(payload, dict) else None)
        # La config ya se resolvio: evitamos que run_pipeline la vuelva a leer del payload.
        result = run_pipeline(payload, config=config)
    except PipelineError as exc:
        parser.exit(2, f"error del pipeline: {exc}\n")
    except Exception as exc:  # noqa: BLE001 - error de entrada no controlado
        parser.exit(2, f"error inesperado: {type(exc).__name__}: {exc}\n")

    text = to_jsonl(result) if args.format == "jsonl" else to_json(result)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
