# -*- coding: utf-8 -*-
"""Errores del normalizador multimodal.

Un unico tipo de error, con `reason_code` enumerable. Nada de texto libre como
unica senal: el motor y los tests agregan por codigo, no por prosa.
"""
from __future__ import annotations

from ..contracts import V3ContractError


class NormalizationError(V3ContractError):
    """Una fuente no se puede normalizar a documentos `v3-internal-v1`.

    Hereda de `V3ContractError` porque quien consume el normalizador ya captura
    esa jerarquia: no le anadimos una segunda que tenga que conocer.
    """

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code
        self.message = message


#: Codigos de fallo del normalizador. Estables y enumerables (mismo criterio que
#: `reason_code` del contrato: MAYUSCULAS con guion bajo).
EMPTY_SOURCE = "EMPTY_SOURCE"
CORRUPT_SOURCE = "CORRUPT_SOURCE"
UNSUPPORTED_SOURCE_KIND = "UNSUPPORTED_SOURCE_KIND"
UNDECODABLE_TEXT = "UNDECODABLE_TEXT"
MISSING_PAYLOAD = "MISSING_PAYLOAD"
INCONSISTENT_POLICY = "INCONSISTENT_POLICY"
ANCHOR_MISMATCH = "ANCHOR_MISMATCH"
NO_CONTENT_EXTRACTED = "NO_CONTENT_EXTRACTED"
DUPLICATE_ADAPTER = "DUPLICATE_ADAPTER"
PROVIDER_CONFIDENCE_OUT_OF_RANGE = "PROVIDER_CONFIDENCE_OUT_OF_RANGE"
EXTERNAL_PROVIDER_NOT_ALLOWED = "EXTERNAL_PROVIDER_NOT_ALLOWED"
