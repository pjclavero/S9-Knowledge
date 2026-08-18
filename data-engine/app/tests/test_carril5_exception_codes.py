# -*- coding: utf-8 -*-
"""Guardas del carril 5: el codigo es estable y NO sale del mensaje.

Estas pruebas defienden el propio instrumento. Sin ellas, alguien podria
"arreglar" un fallo derivando el codigo del texto y volveriamos a medir
redaccion sin enterarnos.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from coded_errors import CODE_ATTR, CodedError, code_of, coded  # noqa: E402
from knowledge_v3.ledger.codes import LedgerCodes  # noqa: E402
from review.codes import PreflightFindings, SupersedeCodes, WriterCodes  # noqa: E402
from tests import carril5_deuda  # noqa: E402
from tests.exception_codes import raises_code  # noqa: E402

#: Modulos de producto sellados por el carril.
SOURCES = [
    "knowledge_v3/ledger/assertions.py",
    "knowledge_v3/ledger/supersession.py",
    "knowledge_v3/ledger/store.py",
    "knowledge_v3/ledger/entries.py",
    "review/ingest_approved.py",
    "review/supersede_review.py",
]

REGISTRIES = (LedgerCodes, PreflightFindings, SupersedeCodes, WriterCodes)


def _registry_values() -> set[str]:
    out = set()
    for reg in REGISTRIES:
        for name, value in vars(reg).items():
            if not name.startswith("_") and isinstance(value, str):
                out.add(value)
    return out


def _coded_calls(path: Path):
    raw = path.read_bytes()
    tree = ast.parse(raw.decode("utf-8"), str(path))
    return [n.exc for n in ast.walk(tree)
            if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
            and isinstance(n.exc.func, ast.Name) and n.exc.func.id == "coded"]


# --------------------------------------------------------------------------
# El codigo no se deriva del mensaje
# --------------------------------------------------------------------------
def test_code_of_no_lee_el_mensaje():
    """Una excepcion cuyo TEXTO contiene un codigo, pero sin sellar, no tiene
    codigo. Si `code_of` lo dedujese del texto, esta prueba se pondria roja."""
    exc = ValueError(f"esto menciona {LedgerCodes.ASSERTION_ALREADY_EXISTS} en el texto")
    assert code_of(exc) is None


def test_el_codigo_vive_en_un_atributo_no_en_el_texto():
    exc = coded(RuntimeError("da igual lo que ponga"), WriterCodes.PREFLIGHT_UNSAFE)
    assert getattr(exc, CODE_ATTR) == WriterCodes.PREFLIGHT_UNSAFE
    assert code_of(exc) == WriterCodes.PREFLIGHT_UNSAFE
    exc.args = ("mensaje completamente distinto",)
    assert code_of(exc) == WriterCodes.PREFLIGHT_UNSAFE


def test_el_atributo_no_pisa_systemexit_code():
    """`SystemExit.code` es el estado de salida del proceso: sellarlo ahi
    cambiaria la conducta del CLI."""
    assert CODE_ATTR != "code"
    exc = coded(SystemExit("abortado"), SupersedeCodes.CHECKSUM_MISMATCH)
    assert exc.code == "abortado"
    assert code_of(exc) == SupersedeCodes.CHECKSUM_MISMATCH


# --------------------------------------------------------------------------
# El instrumento discrimina de verdad
# --------------------------------------------------------------------------
def test_raises_code_falla_si_el_codigo_no_coincide():
    with pytest.raises(AssertionError, match="codigo de excepcion inesperado"):
        with raises_code(ValueError, WriterCodes.PREFLIGHT_UNSAFE):
            raise coded(ValueError("x"), WriterCodes.PACKAGE_REJECTED)


def test_raises_code_falla_si_la_excepcion_no_tiene_codigo():
    with pytest.raises(AssertionError, match="codigo de excepcion inesperado"):
        with raises_code(ValueError, WriterCodes.PREFLIGHT_UNSAFE):
            raise ValueError(WriterCodes.PREFLIGHT_UNSAFE)  # el texto no vale


def test_raises_code_sigue_exigiendo_el_tipo():
    with pytest.raises(TypeError):
        with raises_code(ValueError, WriterCodes.PREFLIGHT_UNSAFE):
            raise coded(TypeError("otro tipo"), WriterCodes.PREFLIGHT_UNSAFE)


def test_coded_error_nace_con_codigo():
    exc = CodedError("mensaje", LedgerCodes.IMPOSSIBLE_HISTORY)
    assert code_of(exc) == LedgerCodes.IMPOSSIBLE_HISTORY


# --------------------------------------------------------------------------
# Los codigos son constantes de registro, unicos, y nunca literales sueltos
# --------------------------------------------------------------------------
def test_los_codigos_son_unicos():
    valores = []
    for reg in REGISTRIES:
        valores += [v for k, v in vars(reg).items()
                    if not k.startswith("_") and isinstance(v, str)]
    duplicados = {v for v in valores if valores.count(v) > 1}
    assert not duplicados, f"codigos repetidos entre registros: {sorted(duplicados)}"


@pytest.mark.parametrize("rel", SOURCES)
def test_todo_raise_sellado_usa_una_constante_del_registro(rel):
    """Ningun `coded(...)` puede llevar un literal: un literal invita a
    copiarlo del mensaje, que es justo lo que este carril prohibe."""
    conocidos = _registry_values()
    for call in _coded_calls(_APP / rel):
        assert len(call.args) == 2, f"{rel}:{call.lineno}: coded() espera (exc, codigo)"
        node = call.args[1]
        assert isinstance(node, ast.Attribute), (
            f"{rel}:{call.lineno}: el codigo debe ser una constante del registro, "
            f"no {ast.unparse(node)!r}"
        )
        assert getattr(REGISTRIES_BY_NAME[node.value.id], node.attr) in conocidos


REGISTRIES_BY_NAME = {r.__name__: r for r in REGISTRIES}


# --------------------------------------------------------------------------
# Las pruebas en alcance ya no miden redaccion
# --------------------------------------------------------------------------
IN_SCOPE_TESTS = [
    "tests/test_knowledge_v3_ledger.py",
    "tests/test_knowledge_v3_ledger_mutation.py",
    "tests/test_safe_writer.py",
    "tests/test_supersede_review.py",
    "tests/test_use_existing.py",
]


@pytest.mark.parametrize("rel", IN_SCOPE_TESTS)
def test_ninguna_prueba_en_alcance_vuelve_a_medir_subcadenas(rel):
    """Regresion: si alguien reintroduce `pytest.raises(..., match=...)` en un
    fichero que sostiene garantias RC, esto se pone rojo."""
    tree = ast.parse((_APP / rel).read_text(encoding="utf-8"), rel)
    ofensores = []
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and ast.unparse(n.func).endswith("raises")
                and any(kw.arg == "match" for kw in n.keywords)):
            ofensores.append(n.lineno)
    assert not ofensores, f"{rel}: comprobaciones por subcadena en {ofensores}"


def test_la_deuda_declarada_cuadra_con_lo_convertido():
    total_fuera = sum(item[2] for item in carril5_deuda.DEUDA_FUERA_DE_ALCANCE)
    assert carril5_deuda.CONVERTIDAS + total_fuera == carril5_deuda.INVENTARIO_TOTAL
    assert (carril5_deuda.INVENTARIO_MATCH + carril5_deuda.INVENTARIO_IN_STR
            == carril5_deuda.INVENTARIO_TOTAL)
    assert (carril5_deuda.SITIOS_CON_ANCLA + carril5_deuda.SIN_ANCLA_MEDIDA
            == carril5_deuda.SITIOS_SELLADOS)


def test_el_numero_de_raises_sellados_es_el_declarado():
    sellados = sum(len(_coded_calls(_APP / rel)) for rel in SOURCES)
    assert sellados == carril5_deuda.SITIOS_SELLADOS
