# -*- coding: utf-8 -*-
"""Errores del motor local.

Tres clases, con una frontera deliberada:

* `EngineInputError` — la ENTRADA no cumple los contratos congelados o mezcla
  workspaces/assets. No es una decision: el motor se niega a decidir. Se
  reporta como bloqueo, nunca se degrada a `REJECT_INVALID` (que es una
  decision sobre un claim bien formado).
* `EnginePlanError` — el plan construido por el motor no supera su propia
  cadena de validadores. Un plan que no se puede aprobar se devuelve SIN
  aprobar; un plan que ni siquiera valida contra el contrato es un fallo del
  motor y se lanza.
* `EngineContractGap` — un campo o regla que el motor necesita y el contrato
  CONGELADO no ofrece. Existe para que un hueco de contrato se reporte como
  hueco y no se parchee en silencio.
"""
from __future__ import annotations


class EngineError(Exception):
    """Raiz de los errores del motor local."""


class EngineInputError(EngineError):
    """La entrada no es procesable: contrato invalido o lote heterogeneo."""


class EnginePlanError(EngineError):
    """El plan construido no valida contra el contrato congelado."""


class EngineContractGap(EngineError):
    """El contrato congelado no ofrece algo que el motor necesita."""
