"""generate_examples.py — regenera `examples/valid` y `examples/invalid` de
`knowledge-visibility/v1` desde `kv_fixtures.py`.

Uso:
    python contracts/knowledge-visibility/v1/tests/generate_examples.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kv_fixtures as fixtures  # noqa: E402

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent / "examples"


def render(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def expected_files() -> dict[Path, str]:
    out: dict[Path, str] = {}
    for name, build in fixtures.VALID_BUILDERS.items():
        out[EXAMPLES / "valid" / f"{name}.json"] = render(build())
    for name, build in fixtures.INVALID_BUILDERS.items():
        out[EXAMPLES / "invalid" / f"{name}.json"] = render(build())
    return out


def main() -> int:
    for path, content in expected_files().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"escrito {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
