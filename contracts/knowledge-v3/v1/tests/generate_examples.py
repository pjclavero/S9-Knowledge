"""
generate_examples.py — regenera `examples/valid` y `examples/invalid` desde
`fixtures.py`.

Los ejemplos NO se editan a mano: se generan. `test_contracts_v3.py` comprueba
que lo que hay en disco coincide byte a byte con lo que produce este script, de
modo que un ejemplo no puede quedarse obsoleto respecto al contrato.

Uso:
    python contracts/knowledge-v3/v1/tests/generate_examples.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import v3_fixtures as fixtures  # noqa: E402  (carga el validador con nombre unico)

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent / "examples"


def render(doc: dict) -> str:
    """Ejemplos legibles: indentados, claves ordenadas, salto final."""
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def expected_files() -> dict[Path, str]:
    out: dict[Path, str] = {}
    for name, build in fixtures.VALID_BUILDERS.items():
        out[EXAMPLES / "valid" / f"{name}.json"] = render(build())
    for name, build in fixtures.INVALID_BUILDERS.items():
        out[EXAMPLES / "invalid" / f"{name}.json"] = render(build())
    return out


def main() -> int:
    written = 0
    for path, content in expected_files().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
            written += 1
    print(f"ejemplos escritos/actualizados: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
