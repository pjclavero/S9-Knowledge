# -*- coding: utf-8 -*-
"""Runner del arnes unificado de la puerta 6 (programa de factividad composicional, B0).

Mide el corpus de DESARROLLO (100 frases congeladas, `dev-synthetic`) y el
corpus de GENERALIZACION COMPOSICIONAL (42 frases nuevas de B0) con la misma
disciplina de integridad que usa `scripts/gate4/measure.py`, y escribe el
informe JSON+MD.

Uso (desde la raiz del repo):

    PYTHONPATH=data-engine/app python3 scripts/gate6/measure.py \
        --out-dir artifacts/gate6-program --out-name b0-baseline
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from knowledge_v3.eval.gate6_harness import measure_gate6_program, to_markdown


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Puerta 6 (B0): arnes unificado.")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--out-name", default="gate6-program")
    args = parser.parse_args(argv)

    report = measure_gate6_program()
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
