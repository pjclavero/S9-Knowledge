"""Ayuda de mantenimiento: imprime un borrador del mapa desde la app real.

NO se ejecuta en la suite. Se usa a mano cuando la puerta enrojece por una
ruta nueva: genera el esqueleto de la entrada y el humano rellena rol, estados
y errores. Uso:  python3 viewer/tests/route_contract/_generate.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

VIEWER_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(VIEWER_ROOT))
sys.path.insert(0, str(VIEWER_ROOT.parent / "data-engine" / "app"))

from tests.route_contract import inventory  # noqa: E402


def main() -> None:
    from app.main import app

    rows = {}
    for r in inventory.registered_routes(app):
        rows[r.key] = {
            "endpoint": r.endpoint,
            "tests": sorted(inventory.test_files_mentioning(r.path)),
        }
    print(json.dumps(rows, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
