# -*- coding: utf-8 -*-
"""Instrumento del carril 5: comprobar TIPO + CODIGO, nunca redaccion.

Por que no se reutiliza `viewer/tests/exception_codes.py` (carril 3)
-------------------------------------------------------------------
Se intento. No encaja por dos motivos, no por gusto:

1. En `aaf9695` ese modulo **no existe todavia** (llega con el PR #198, aun sin
   fusionar): importarlo desde `data-engine` ataria este carril a un arbol que
   la rama no tiene, y el import fallaria en CI.
2. Los `sys.path` de los dos arboles son disjuntos: los tests del data-engine
   insertan `data-engine/app` como raiz y los del visor insertan `viewer`. Un
   import cruzado obligaria a manipular `sys.path` desde un test, que es
   exactamente la clase de acoplamiento que hace que un carril rompa al otro.

Lo que SI se comparte es el CONTRATO, no el fichero: mismo nombre de funcion
(`raises_code`), misma firma `(tipo, codigo)`, misma semantica (tipo Y codigo,
y el codigo leido de un atributo, jamas del mensaje). Cuando el PR #198 este en
`main`, unificar ambos modulos es un cambio mecanico de una linea de import.
Deuda declarada aqui a proposito, no en silencio.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Type

import pytest

_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from coded_errors import CODE_ATTR, code_of  # noqa: E402


class _CodeCatcher:
    """Envoltorio de `pytest.raises` que ademas exige el codigo estable."""

    def __init__(self, expected_type, expected_code: str) -> None:
        self._expected_type = expected_type
        self._expected_code = expected_code
        self._ctx = pytest.raises(expected_type)
        self.excinfo: Any = None

    def __enter__(self) -> "_CodeCatcher":
        self.excinfo = self._ctx.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        handled = self._ctx.__exit__(exc_type, exc, tb)
        if not handled:
            return handled
        got = code_of(self.excinfo.value)
        if got != self._expected_code:
            raise AssertionError(
                "codigo de excepcion inesperado: se esperaba "
                f"{self._expected_code!r} y se obtuvo {got!r} "
                f"(tipo {type(self.excinfo.value).__name__}). "
                "Este control mide CONDUCTA: el mensaje es irrelevante, el "
                f"atributo {CODE_ATTR!r} no lo es."
            )
        return True

    # Compatibilidad con el uso habitual de `pytest.raises`
    @property
    def value(self):
        return self.excinfo.value

    @property
    def type(self):
        return self.excinfo.type


def raises_code(expected_type: Type[BaseException], expected_code: str) -> _CodeCatcher:
    """Contexto: exige que se levante `expected_type` CON `expected_code`.

    Falla si el tipo no coincide (lo hace `pytest.raises`) o si el codigo no
    coincide, incluido el caso de excepcion sin codigo (`None`).
    """
    if not isinstance(expected_code, str) or not expected_code:
        raise ValueError("raises_code(): el codigo esperado debe ser cadena no vacia")
    return _CodeCatcher(expected_type, expected_code)


def assert_code(exc: BaseException, expected_code: str) -> None:
    """Version imperativa, para excepciones ya capturadas."""
    got = code_of(exc)
    assert got == expected_code, (
        f"codigo de excepcion inesperado: {got!r} != {expected_code!r}"
    )


__all__ = ["assert_code", "raises_code"]
