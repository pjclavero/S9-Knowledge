# -*- coding: utf-8 -*-
"""Errores del ledger temporal.

Una jerarquia unica (`LedgerError`) para que quien captura no tenga que conocer
tres arboles distintos. `V3ContractError` (contratos congelados) NO se envuelve:
si un documento incumple el contrato, el error del contrato debe llegar intacto
a quien lo produjo.
"""
from __future__ import annotations


class LedgerError(Exception):
    """Operacion invalida sobre el ledger temporal."""


class LedgerTransitionError(LedgerError):
    """Transicion de `status` fuera de la matriz legal (matriz CERRADA)."""


class LedgerIntegrityError(LedgerError):
    """La cadena de custodia no verifica: una entrada fue alterada o falta."""


class LedgerWorkspaceError(LedgerError):
    """Aislamiento duro de workspace: ningun documento cruza de boveda."""


__all__ = [
    "LedgerError",
    "LedgerIntegrityError",
    "LedgerTransitionError",
    "LedgerWorkspaceError",
]
