# -*- coding: utf-8 -*-
"""Puente al validador REAL de los contratos congelados `v3-internal-v1`.

El arnes no reimplementa ninguna validacion: importa el mismo modulo
``contracts/knowledge-v3/v1/validator.py`` que usan el gate de contratos y los
modelos Python. Si el gold dejase de cumplir el contrato, el fallo sale del
validador de verdad, no de una copia local que podria divergir.
"""
from __future__ import annotations

from typing import Any

from knowledge_v3.contracts.base import schema_validator as _V

ContractV3Error = _V.ContractV3Error
canonical_json = _V.canonical_json
sha256_hash = _V.sha256_hash
seal_plan = _V.seal_plan
compute_idempotency_key = _V.compute_idempotency_key
CONTRACT_SCHEMAS = _V.CONTRACT_SCHEMAS

#: Version de contrato que emite el dataset gold.
CONTRACT_VERSION = "1.0.0"


def validate_document(doc: dict[str, Any]) -> None:
    """Valida un documento contra el contrato congelado. Lanza en caso de fallo."""
    _V.validate_document(doc)


def is_valid(doc: dict[str, Any]) -> bool:
    return _V.is_valid(doc)


__all__ = [
    "CONTRACT_SCHEMAS",
    "CONTRACT_VERSION",
    "ContractV3Error",
    "canonical_json",
    "compute_idempotency_key",
    "is_valid",
    "seal_plan",
    "sha256_hash",
    "validate_document",
]
