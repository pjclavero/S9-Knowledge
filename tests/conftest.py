"""conftest.py del árbol de tests del EQUIPO D (QA/E2E).

Ámbito: se aplica a `tests/e2e/` y `tests/integration/` (propiedad exclusiva del
EQUIPO D). NO afecta a `data-engine/app/tests`, `viewer/tests` ni `deploy/tests`,
que conservan su propio conftest y lógica (RESTRICCIÓN: no tocar tests ni lógica
de otros equipos).

Responsabilidades:
  1. Activar el CORTAFUEGOS DE PRODUCCIÓN (tests/support/prod_block.py) para toda
     la sesión: cualquier conexión a los hosts/IP productivos aborta el test.
  2. Poner `tests/` en sys.path para importar `support.*`.
  3. Registrar los markers propios (e2e, integration, contract, prod_block).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS_ROOT = Path(__file__).resolve().parent
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from support import prod_block  # noqa: E402

# Se instala en import del conftest -> cubre TODA la sesión, incluidos los E2E
# con navegador, antes de que cualquier fixture pueda abrir una conexión.
prod_block.install()


def pytest_configure(config: pytest.Config) -> None:
    for marker in (
        "e2e: prueba end-to-end (depende de A/B/C; puede estar skip/xfail en fase 1)",
        "integration: prueba de integración/contrato con dobles y fixtures locales",
        "contract: valida documentos contra el contrato compartido review/ingest v1",
        "prod_block: verifica el cortafuegos de red hacia producción",
    ):
        config.addinivalue_line("markers", marker)


@pytest.fixture(scope="session")
def prod_block_active() -> bool:
    """Confirma que el cortafuegos está instalado (para tests que lo requieran)."""
    return prod_block._INSTALLED


@pytest.fixture
def contract_validator():
    """Módulo validator del contrato review/ingest v1 (solo lectura)."""
    from support import contracts

    return contracts.validator
