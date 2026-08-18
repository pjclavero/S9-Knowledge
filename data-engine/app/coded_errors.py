# -*- coding: utf-8 -*-
"""Codigos estables de excepcion para el data-engine (carril 5 de V3.1).

Motivo
------
Hasta `aaf9695` las garantias RC del data-engine (unicidad e identidad durable
del ledger, append-only, no-escritura del writer, supersesion, fail-closed) se
comprobaban en los tests por SUBCADENA del mensaje. Eso mide REDACCION, no
conducta: reescribir un mensaje sin tocar el comportamiento pone rojas las
pruebas, y una excepcion de conducta distinta con mensaje parecido pasa.

Contrato
--------
- El codigo vive en el atributo `s9k_code` de la instancia de excepcion.
- El codigo NUNCA se deriva del mensaje ni se reconstruye por cadena: se pasa
  explicitamente en el punto de `raise`. `code_of()` no mira `str(exc)`.
- El nombre del atributo NO es `code`: `SystemExit.code` ya significa el estado
  de salida del proceso y sobrescribirlo cambiaria la conducta del CLI.
- Un codigo es estable: se puede renombrar el mensaje, traducirlo o reordenarlo
  sin tocar el codigo; cambiar el codigo es un cambio de contrato.
"""
from __future__ import annotations

from typing import Optional, TypeVar

CODE_ATTR = "s9k_code"

E = TypeVar("E", bound=BaseException)


def coded(exc: E, code: str) -> E:
    """Sella `exc` con el codigo estable `code` y la devuelve.

    Uso: ``raise coded(RuntimeError("mensaje libre"), Codes.ALGO)``.
    """
    if not isinstance(code, str) or not code:
        raise ValueError("coded(): el codigo debe ser una cadena no vacia")
    setattr(exc, CODE_ATTR, code)
    return exc


def code_of(exc: BaseException) -> Optional[str]:
    """Codigo estable de `exc`, o None si no lo lleva.

    Deliberadamente NO inspecciona `str(exc)`: si el codigo se dedujese del
    texto, seguiriamos midiendo redaccion.
    """
    value = getattr(exc, CODE_ATTR, None)
    return value if isinstance(value, str) and value else None


class CodedError(Exception):
    """Excepcion que nace con codigo estable."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        coded(self, code)


__all__ = ["CODE_ATTR", "CodedError", "code_of", "coded"]
