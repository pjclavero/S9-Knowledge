# -*- coding: utf-8 -*-
"""conftest.py de la suite Q — OLA 2B Lote 2 (tests/wave2b).

Este conftest NO duplica el cortafuegos de produccion: `tests/conftest.py`
(directorio ancestro) ya instala `support.prod_block` para toda la sesion, por
lo que `tests/wave2b/` lo hereda automaticamente (cualquier conexion a un host
productivo aborta el test).

OLA 2B (integrada): los modulos de relaciones de los Lotes 1+2 ya estan
fusionados en main. Estos tests importan y ejercitan las IMPLEMENTACIONES
REALES:

  - `relations.syntax`               (adaptador sintactico)
  - `relations.local_llm_shadow`     (evaluador LLM local, modo sombra)
  - `relations.external_ai_shadow`   (evaluador IA externa, modo sombra)
  - `relations.consensus_adapter`    (consenso de relaciones)
  - `relations.observability`        (trazabilidad/redaccion)

Para importarlas se pone `data-engine/app` en sys.path (mismo patron que
`data-engine/app/tests/conftest.py` y `tests/wave2/conftest.py`), lo que expone
`relations` y `external_ai` como paquetes de primer nivel (sin colisionar con el
paquete `app` del viewer). Q NO modifica producto: solo lo importa y comprueba
sus invariantes, incluidos MUTATION checks que ejercitan el comportamiento real.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# tests/wave2b/conftest.py -> parents[2] = repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_ENGINE_APP = REPO_ROOT / "data-engine" / "app"
if _DATA_ENGINE_APP.is_dir() and str(_DATA_ENGINE_APP) not in sys.path:
    sys.path.insert(0, str(_DATA_ENGINE_APP))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "mutation: comprueba que relajar una regla/logica del modulo REAL romperia "
        "el test (la regla es load-bearing / la mutacion es capturada)",
    )


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def prod_firewall_active() -> bool:
    """True si el cortafuegos de produccion heredado de tests/conftest.py esta activo."""
    try:
        from support import prod_block
    except Exception:  # pragma: no cover - defensivo
        return False
    return bool(getattr(prod_block, "_INSTALLED", False))
