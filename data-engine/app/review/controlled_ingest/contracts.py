"""Adaptador del motor a los contratos review/ingest v1.

Este modulo NO duplica ni modifica los contratos: importa el validador UNICO
publicado en ``contracts/review-ingest/v1/validator.py`` y reexpone
``validate_document`` / ``ContractError`` para el resto del motor.

El validador se carga por ruta con un nombre de modulo aislado para no colisionar
con ``review.validator`` (validador RPG interno del motor).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

# data-engine/app/review/controlled_ingest/contracts.py
#   parents[0]=controlled_ingest [1]=review [2]=app [3]=data-engine [4]=repo
_REPO_ROOT = Path(__file__).resolve().parents[4]
_CONTRACTS_DIR = _REPO_ROOT / "contracts" / "review-ingest" / "v1"
_VALIDATOR_PATH = _CONTRACTS_DIR / "validator.py"

_MODULE_NAME = "s9k_contracts_review_ingest_v1_validator"


def _load_validator() -> ModuleType:
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    if not _VALIDATOR_PATH.is_file():
        raise RuntimeError(
            f"No se encuentra el validador de contratos v1 en {_VALIDATOR_PATH}. "
            "El motor consume los contratos publicados; no los duplica."
        )
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, _VALIDATOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


_validator = _load_validator()

# Reexportacion de la superficie publica del contrato (sin modificarlo).
ContractError = _validator.ContractError
CONTRACTS_DIR = _CONTRACTS_DIR


def validate_document(doc: dict[str, Any]) -> None:
    """Valida ``doc`` contra el contrato v1. Lanza ``ContractError`` si no cumple."""
    _validator.validate_document(doc)


def is_valid(doc: dict[str, Any]) -> bool:
    return _validator.is_valid(doc)


__all__ = ["validate_document", "is_valid", "ContractError", "CONTRACTS_DIR"]
