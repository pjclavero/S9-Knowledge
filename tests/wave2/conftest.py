"""conftest.py de la suite Q — OLA 2A (tests/wave2).

Este conftest NO duplica el cortafuegos de producción: `tests/conftest.py`
(directorio ancestro) ya instala `support.prod_block` para toda la sesión, por
lo que `tests/wave2/` lo hereda automáticamente.

FASE 2 (integrada): los contratos reales de A1/B2/B3 ya están fusionados en main.
Estos tests importan y ejercitan las IMPLEMENTACIONES REALES:

  - `relations.contracts`            (data-engine/app/relations)
  - `export_import.contract`         (data-engine/app/export_import)
  - `media.multimedia_contract`      (data-engine/app/media)
  - `.github/dependabot.yml`         (configuración real de supply chain)

Para importarlas se pone `data-engine/app` en sys.path (mismo patrón que
`data-engine/app/tests/conftest.py`), lo que expone `relations`, `export_import`,
`media` y `external_ai` como paquetes de primer nivel (sin colisionar con el
paquete `app` del viewer). Q NO modifica producto: solo lo importa y comprueba
sus invariantes de seguridad, incluidos MUTATION checks que ejercitan el
comportamiento real.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# tests/wave2/conftest.py -> parents[2] = repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_ENGINE_APP = REPO_ROOT / "data-engine" / "app"
if _DATA_ENGINE_APP.is_dir() and str(_DATA_ENGINE_APP) not in sys.path:
    sys.path.insert(0, str(_DATA_ENGINE_APP))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "mutation: comprueba que relajar una regla del contrato REAL rompería el "
        "test (la regla es load-bearing / la mutación es capturada)",
    )


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def prod_firewall_active() -> bool:
    """True si el cortafuegos de producción heredado de tests/conftest.py está activo."""
    try:
        from support import prod_block
    except Exception:  # pragma: no cover - defensivo
        return False
    return bool(getattr(prod_block, "_INSTALLED", False))
