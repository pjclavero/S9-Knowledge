"""conftest.py de la suite Q — OLA 2A (tests/wave2).

Este conftest NO duplica el cortafuegos de producción: `tests/conftest.py`
(directorio ancestro) ya instala `support.prod_block` para toda la sesión, por
lo que `tests/wave2/` lo hereda automáticamente. Aquí solo:

  1. Registramos el marker `mutation` (cada test de mutación comprueba que
     RELAJAR una regla del contrato haría PASAR un documento que la regla estricta
     rechaza; es decir, la regla es load-bearing).
  2. Exponemos una fixture `prod_firewall_active` para que los tests puedan
     afirmar la invariante de seguridad "los tests Q no tocan producción".

RESTRICCIÓN de Q: estos tests son autocontenidos. Los contratos reales de A1/B2/B3
viven en ramas paralelas AÚN NO fusionadas; por eso definimos validadores de
REFERENCIA mínimos dentro de cada módulo de test que codifican las REGLAS
esperadas de `docs/coordination/contract-proposals.md`. En la integración, los
contratos reales deberán cumplir estas mismas invariantes.
"""
from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "mutation: comprueba que relajar una regla del contrato rompería el test "
        "(la regla es load-bearing / la mutación es capturada)",
    )


@pytest.fixture(scope="session")
def prod_firewall_active() -> bool:
    """True si el cortafuegos de producción heredado de tests/conftest.py está activo."""
    try:
        from support import prod_block
    except Exception:  # pragma: no cover - defensivo
        return False
    return bool(getattr(prod_block, "_INSTALLED", False))
