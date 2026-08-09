"""CLI del comprobador de salud de datos y contratos (carril J). READ-ONLY.

    python -m scripts.data_health.cli --fixture tests/fixtures/e2e_rpg_graph.json
    python -m scripts.data_health.cli --modo cadena
    S9K_HEALTH_NEO4J_URI=bolt://localhost:7687 python -m scripts.data_health.cli

Códigos de salida: 0 sólo si no hay CRITICAL, ni UNKNOWN, ni fallo interno;
1 CRITICAL; 2 UNKNOWN; 3 fallo interno del propio comprobador.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
# el esquema del motor vive aquí y se importa como top-level (ver conftest raíz)
_DE = REPO_ROOT / "data-engine" / "app"
if _DE.is_dir() and str(_DE) not in sys.path:
    sys.path.insert(0, str(_DE))

from scripts.data_health import checks_chain, checks_dataset  # noqa: E402
from scripts.data_health.dataset import DatasetError, load_from_env_or_path  # noqa: E402
from scripts.data_health.report import (  # noqa: E402
    EXIT_INTERNAL_ERROR,
    Report,
)


def construir_informe(fixture: str | None, modo: str) -> Report:
    rep = Report()
    if modo in ("todo", "datos"):
        ds = load_from_env_or_path(fixture)
        f, ejecutadas = checks_dataset.ejecutar(ds)
        rep.extend(f)
        rep.checks_run.extend(ejecutadas)
    if modo in ("todo", "cadena"):
        f, ejecutadas = checks_chain.ejecutar(REPO_ROOT)
        rep.extend(f)
        rep.checks_run.extend(ejecutadas)
    return rep


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Salud de datos y contratos (READ-ONLY)")
    p.add_argument("--fixture", help="dataset JSON con 'nodes'/'edges'")
    p.add_argument("--modo", choices=("todo", "datos", "cadena"), default="todo")
    p.add_argument("--formato", choices=("texto", "json"), default="texto")
    args = p.parse_args(argv)

    try:
        rep = construir_informe(args.fixture, args.modo)
    except DatasetError as exc:
        # No poder cargar el dataset NO es "no hay problemas".
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_INTERNAL_ERROR
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        print("ERROR: fallo interno del comprobador", file=sys.stderr)
        return EXIT_INTERNAL_ERROR

    print(rep.to_json() if args.formato == "json" else rep.to_text())
    return rep.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
