"""Ayuda de pruebas: comprobar EXCEPCIÓN POR TIPO + CÓDIGO, no por texto.

V3.1, carril 3. Una comprobación `pytest.raises(X, match="algún texto")` mide
la REDACCIÓN del mensaje: se pone roja si se reescribe el texto sin tocar la
conducta, y se queda verde si otra rama del código lanza el mismo tipo con un
mensaje parecido. Donde la excepción sostiene una garantía del RC, la prueba
usa `raises_code`, que exige tipo y código estable.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest


@contextmanager
def raises_code(exc_type, code: str):
    """Como `pytest.raises(exc_type)`, pero además exige `exc.code == code`."""
    with pytest.raises(exc_type) as excinfo:
        yield excinfo
    actual = getattr(excinfo.value, "code", None)
    assert actual == code, (
        f"se esperaba {exc_type.__name__} con code={code!r} y llegó code={actual!r} "
        f"({excinfo.value!r}). El código es el contrato; el mensaje no."
    )
