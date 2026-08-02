# -*- coding: utf-8 -*-
"""Runner del arnes unificado de la puerta 4 (programa de cobertura, B0).

Mide el corpus de DESARROLLO (split `negation`, cadena E2E completa) y el de
GENERALIZACION (B0, clasificador de negacion) con la misma disciplina de
integridad, y escribe el informe JSON+MD.

Uso (desde la raiz del repo, tal y como pide el runner original):

    PYTHONPATH=data-engine/app python3 scripts/gate4/measure.py \
        --out-dir artifacts/gate4-program --out-name b0-baseline
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from knowledge_v3.eval.harness import measure_gate4_program, to_markdown


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Puerta 4 (B0): arnes unificado.")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--out-name", default="gate4-program")
    args = parser.parse_args(argv)

    report = measure_gate4_program()
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    markdown = to_markdown(report)

    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{args.out_name}.json").write_text(payload, encoding="utf-8")
        (out / f"{args.out_name}.md").write_text(markdown, encoding="utf-8")
        print(f"escrito en {out}/{args.out_name}.{{json,md}}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
