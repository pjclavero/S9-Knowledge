"""El verificador también se verifica.

`raises_code` es el instrumento con el que este carril sostiene garantías del
RC. Un instrumento que puede aprobar sin comprobar nada es exactamente el
defecto que estamos erradicando, así que aquí se le ponen sus propios
negativos: tiene que REHUSAR el caso degenerado, no tragarlo.
"""
from __future__ import annotations

import pytest

from exception_codes import raises_code


class _ConCodigo(ValueError):
    code = "CODIGO_A"


class _ConVarios(RuntimeError):
    codes = ("CODIGO_B", "CODIGO_C")


class _SinNada(RuntimeError):
    pass


def test_positivo_codigo_unico():
    with raises_code(_ConCodigo, "CODIGO_A"):
        raise _ConCodigo("el texto da igual")


def test_positivo_pertenencia_en_codes():
    """La forma de `AuthSecurityError`: varias causas a la vez."""
    with raises_code(_ConVarios, "CODIGO_C"):
        raise _ConVarios("el texto da igual")


def test_negativo_codigo_distinto_enrojece():
    with pytest.raises(AssertionError):
        with raises_code(_ConCodigo, "CODIGO_Z"):
            raise _ConCodigo("x")


def test_negativo_codigo_ausente_de_codes_enrojece():
    with pytest.raises(AssertionError):
        with raises_code(_ConVarios, "CODIGO_Z"):
            raise _ConVarios("x")


def test_negativo_None_no_es_un_codigo():
    """El caso degenerado: `getattr(exc, "code", None) == None` habría pasado
    en silencio. El instrumento debe rehusar ANTES de ejecutar el bloque."""
    ejecutado = []
    with pytest.raises(AssertionError):
        with raises_code(_ConCodigo, None):
            ejecutado.append(True)
            raise _ConCodigo("x")
    assert ejecutado == [], "rehusar tarde no es rehusar: el bloque no debe correr"


def test_negativo_excepcion_sin_codigo_estable_enrojece():
    """Una excepción que no expone `code` ni `codes` no puede sostener una
    garantía por código: el instrumento lo dice, no lo aprueba."""
    with pytest.raises(AssertionError):
        with raises_code(_SinNada, "CODIGO_A"):
            raise _SinNada("x")


def test_negativo_no_lanzar_nada_sigue_enrojeciendo():
    """Contrapeso: que el instrumento no se haya vuelto tan estricto que
    apruebe por no llegar nunca a comprobar."""
    with pytest.raises(BaseException) as exc:
        with raises_code(_ConCodigo, "CODIGO_A"):
            pass
    assert "DID NOT RAISE" in str(exc.value)


class _CodesComoCadena(RuntimeError):
    """El caso degenerado del OTRO lado: `codes` no es una secuencia de
    códigos sino una CADENA. `code in varios` sobre una cadena no comprueba
    pertenencia: comprueba SUBCADENA, que es justo la aprobación por parecido
    que este carril erradica."""

    codes = "CSRF_SECRET_TOO_SHORT_Y_MAS"


def test_negativo_codes_como_cadena_enrojece():
    """`raises_code(X, "CSRF")` NO puede aprobar contra `codes="CSRF_..."`.

    Sin el `assert not isinstance(varios, str)`, la rama de pertenencia
    degenera en `"CSRF" in "CSRF_SECRET_TOO_SHORT_Y_MAS"` -> True, y el
    instrumento sella un prefijo como si fuera un código. Hoy ninguna
    excepción del producto expone `codes` como cadena (`AuthSecurityError`
    la construye siempre con `tuple(...)`), así que esto no es un
    superviviente: es la puerta cerrada antes de que alguien la abra.
    """
    with pytest.raises(AssertionError):
        with raises_code(_CodesComoCadena, "CSRF"):
            raise _CodesComoCadena("x")


def test_negativo_codes_cadena_exacta_tampoco_aprueba():
    """Ni siquiera con el texto completo: una cadena no es una secuencia de
    códigos, y aprobar ahí sería aprobar por forma equivocada."""
    with pytest.raises(AssertionError):
        with raises_code(_CodesComoCadena, "CSRF_SECRET_TOO_SHORT_Y_MAS"):
            raise _CodesComoCadena("x")
