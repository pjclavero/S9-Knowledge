"""contracts.py — acceso de solo lectura al contrato compartido review/ingest v1.

Importa el `validator.py` ÚNICO de `contracts/review-ingest/v1/` sin duplicar ni
modificar los esquemas (RESTRICCIÓN: contracts/** es de solo consumo). Expone:

  - validator: el módulo del contrato (validate_document, is_valid, ContractError).
  - CONTRACT_DIR / VALID_DIR / INVALID_DIR: rutas a esquemas y ejemplos.
  - load_example(name): carga un ejemplo válido por nombre de fichero (sin .json).
  - REPO_ROOT: raíz del repositorio.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DIR = REPO_ROOT / "contracts" / "review-ingest" / "v1"
VALID_DIR = CONTRACT_DIR / "examples" / "valid"
INVALID_DIR = CONTRACT_DIR / "examples" / "invalid"


def _load_validator() -> ModuleType:
    """Carga el validator del contrato como módulo aislado 'contract_validator_v1'.

    Se usa un nombre de módulo propio para no colisionar con otros 'validator'
    que pudieran existir en el árbol de tests o del motor.
    """
    if "contract_validator_v1" in sys.modules:
        return sys.modules["contract_validator_v1"]
    # El validator hace `SCHEMA_DIR = Path(__file__).parent`, así que basta con
    # cargarlo desde su ubicación real para que encuentre los .schema.json.
    if str(CONTRACT_DIR) not in sys.path:
        sys.path.insert(0, str(CONTRACT_DIR))
    spec = importlib.util.spec_from_file_location(
        "contract_validator_v1", CONTRACT_DIR / "validator.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["contract_validator_v1"] = module
    spec.loader.exec_module(module)
    return module


validator = _load_validator()
ContractError = validator.ContractError


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_example(name: str) -> dict[str, Any]:
    """Carga un ejemplo VÁLIDO del contrato por nombre (sin extensión)."""
    return load_json(VALID_DIR / f"{name}.json")
