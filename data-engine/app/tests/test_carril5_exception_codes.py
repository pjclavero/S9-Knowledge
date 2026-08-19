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

#: Modulos de producto sellados por el carril. Fuente unica en `carril5_deuda`:
#: dos listas separadas acabarian divergiendo y el censo mediria otra cosa que
#: la deuda declarada.
SOURCES = list(carril5_deuda.MODULOS_SELLADOS)

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


def _todas_las_llamadas_coded(raiz: Path):
    """`(fichero, linea, nodo)` de TODA llamada a `coded(...)` bajo `raiz`."""
    for path in sorted(raiz.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "coded"):
                yield str(path.relative_to(_APP)), n.lineno, n


def test_ningun_coded_del_data_engine_lleva_un_codigo_inventado():
    """MENOR CERRADO. `coded()` acepta cualquier cadena no vacia, y la guarda
    AST anterior solo miraba los 6 ficheros sellados: bastaba sellar un `raise`
    en cualquier OTRO modulo con `coded(exc, "LO_QUE_SEA")` para tener un codigo
    fuera de registro sin que nada se quejase.

    Ahora el barrido es TODO `data-engine/app/`, tests incluidos. Se admiten dos
    formas y ninguna mas: una constante de registro, o el parametro de una
    funcion del propio instrumento (donde el codigo llega de fuera y lo valida
    quien lo pasa).
    """
    conocidos = _registry_values()
    ofensores = []
    for rel, lineno, call in _todas_las_llamadas_coded(_APP):
        if len(call.args) != 2:
            ofensores.append(f"{rel}:{lineno}: coded() espera (exc, codigo)")
            continue
        node = call.args[1]
        if isinstance(node, ast.Attribute):
            reg = REGISTRIES_BY_NAME.get(getattr(node.value, "id", None))
            if reg is None or getattr(reg, node.attr, None) not in conocidos:
                ofensores.append(f"{rel}:{lineno}: {ast.unparse(node)} no es de registro")
        elif isinstance(node, ast.Name):
            continue  # variable: `coded(exc, code)` dentro del propio helper
        else:
            ofensores.append(
                f"{rel}:{lineno}: codigo {ast.unparse(node)!r} no es constante de registro")
    assert not ofensores, "codigos fuera de registro:\n  " + "\n  ".join(ofensores)


def test_ninguna_excepcion_declara_el_sello_como_atributo_de_clase():
    """MENOR CERRADO. `code_of()` leia con `getattr`, que recorre la MRO: una
    clase con `s9k_code` DE CLASE haria pasar por sellada una instancia que
    nadie sello. `code_of()` ya lee el diccionario de instancia; esto comprueba
    ademas que nadie introduzca esa clase.
    """
    culpables = []
    for path in sorted(_APP.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if not isinstance(n, ast.ClassDef):
                continue
            for stmt in n.body:
                dianas = (stmt.targets if isinstance(stmt, ast.Assign)
                          else [stmt.target] if isinstance(stmt, ast.AnnAssign) else [])
                if any(isinstance(t, ast.Name) and t.id == CODE_ATTR for t in dianas):
                    culpables.append(f"{path.relative_to(_APP)}:{stmt.lineno} {n.name}")
    assert not culpables, (
        f"{CODE_ATTR} como atributo de CLASE en: {culpables}. El sello debe "
        "significar 'este raise concreto puso el codigo'.")


def test_code_of_no_hereda_el_sello_de_la_clase():
    """Control positivo del menor anterior: una clase que declare el sello no
    debe sellar a sus instancias."""

    class _Impostora(Exception):
        pass

    setattr(_Impostora, CODE_ATTR, WriterCodes.PREFLIGHT_UNSAFE)
    assert code_of(_Impostora("nadie me sello")) is None
    assert code_of(coded(_Impostora("a mi si"), WriterCodes.PACKAGE_REJECTED)) == \
        WriterCodes.PACKAGE_REJECTED


# --------------------------------------------------------------------------
# Las pruebas en alcance ya no miden redaccion
# --------------------------------------------------------------------------
IN_SCOPE_TESTS = [
    "tests/test_knowledge_v3_ledger.py",
    "tests/test_knowledge_v3_ledger_mutation.py",
    "tests/test_safe_writer.py",
    "tests/test_supersede_review.py",
    "tests/test_use_existing.py",
    "tests/test_carril5_anclas_rc.py",
]


@pytest.mark.parametrize("rel", IN_SCOPE_TESTS)
def test_ninguna_prueba_en_alcance_vuelve_a_medir_subcadenas(rel):
    """Regresion: si alguien reintroduce una comprobacion por subcadena en un
    fichero que sostiene garantias RC, esto se pone rojo.

    MENOR CERRADO: antes solo miraba `pytest.raises(..., match=...)`. Un
    `"literal" in str(exc)` nuevo --la otra mitad EXACTA del inventario, 50 de
    177 en la base-- entraba sin que nada chistase. Se reutiliza el detector
    entregado en vez de reimplementarlo aqui: dos copias del mismo criterio
    acaban divergiendo y una de las dos deja de morder.
    """
    inventario = carril5_deuda.censo_inventario("data-engine")
    clave = f"data-engine/app/{rel}"
    hallazgos = inventario["por_fichero"].get(clave, {})
    ofensores = (hallazgos.get("estricto_match", [])
                 + hallazgos.get("estricto_in_str", []))
    assert not ofensores, (
        f"{rel}: comprobaciones por subcadena en las lineas {sorted(ofensores)}. "
        "En estos ficheros se mide CONDUCTA: usa `raises_code(tipo, codigo)`.")


# --------------------------------------------------------------------------
# Las cifras se DERIVAN de un censo; declararlas mal se pone rojo
# --------------------------------------------------------------------------
def test_el_numero_de_raises_sellados_es_el_declarado():
    sellados = sum(len(_coded_calls(_APP / rel)) for rel in SOURCES)
    assert sellados == carril5_deuda.SITIOS_SELLADOS


def test_el_reparto_con_ancla_sin_ancla_se_mide_no_se_declara():
    """LA PRUEBA QUE FALTABA.

    Antes solo `SITIOS_SELLADOS` estaba fijado por censo. `SITIOS_CON_ANCLA` y
    `SIN_ANCLA_MEDIDA` eran parametros libres: bastaba con que sumasen 71. Se
    demostro poniendo `SITIOS_CON_ANCLA = 71` y `SIN_ANCLA_MEDIDA = 0` --la
    deuda entera borrada de un plumazo-- y la suite seguia verde (21 passed).
    Ahora cada mitad se compara contra el censo.
    """
    censo = carril5_deuda.censo_anclas()
    assert censo["sellados"] == carril5_deuda.SITIOS_SELLADOS
    assert censo["con_ancla"] == carril5_deuda.SITIOS_CON_ANCLA
    assert censo["sin_ancla"] == carril5_deuda.SIN_ANCLA_MEDIDA
    assert (carril5_deuda.SITIOS_CON_ANCLA + carril5_deuda.SIN_ANCLA_MEDIDA
            == carril5_deuda.SITIOS_SELLADOS)


def test_los_sitios_sin_ancla_estan_nombrados_uno_a_uno():
    """Un numero no es una declaracion. La entrega anterior decia "31 sin ancla"
    y en el repo no habia manera de saber CUALES: solo existia el 31."""
    censo = carril5_deuda.censo_anclas()
    assert list(carril5_deuda.SIN_ANCLA_NOMINAL) == censo["nominal_sin_ancla"], (
        "la lista nominal no coincide con la medida.\n"
        "  medida:    " + "\n             ".join(censo["nominal_sin_ancla"]))


def test_el_inventario_actual_es_el_declarado():
    """Cifra TOTAL, no muestra: censo AST completo del ambito `data-engine`."""
    c = carril5_deuda.censo_inventario("data-engine")
    assert c["estricto"]["total"] == carril5_deuda.INVENTARIO_ACTUAL_ESTRICTO
    assert c["estricto"]["match"] == carril5_deuda.INVENTARIO_ACTUAL_ESTRICTO_MATCH
    assert c["estricto"]["in_str"] == carril5_deuda.INVENTARIO_ACTUAL_ESTRICTO_IN_STR
    assert c["amplio"]["total"] == carril5_deuda.INVENTARIO_ACTUAL_AMPLIO


def _hay_ref(ref: str) -> bool:
    import subprocess
    raiz = _APP.parents[1]
    return subprocess.run(["git", "-C", str(raiz), "cat-file", "-e", ref + "^{commit}"],
                          capture_output=True).returncode == 0


def test_el_inventario_de_la_base_y_la_conversion_cuadran():
    """Comprobacion cruzada, derivada: convertidas = base - actual + guardas.

        177 - 127 + 2 = 52        (total ESTRICTO)
        127 -  52 + 2 = 77        (solo `match=`)

    Se omite --y se dice-- si el arbol no tiene el commit base: en un clon
    superficial la medida no existe, y fingirla seria peor que no darla.
    """
    if not _hay_ref("aaf9695"):
        pytest.skip("aaf9695 no esta en este arbol (clon superficial)")
    b = carril5_deuda.censo_inventario("data-engine", "aaf9695")
    assert b["estricto"]["total"] == carril5_deuda.INVENTARIO_BASE_ESTRICTO
    assert b["estricto"]["match"] == carril5_deuda.INVENTARIO_BASE_ESTRICTO_MATCH
    assert b["amplio"]["total"] == carril5_deuda.INVENTARIO_BASE_AMPLIO
    assert (carril5_deuda.INVENTARIO_BASE_ESTRICTO
            - carril5_deuda.INVENTARIO_ACTUAL_ESTRICTO
            + carril5_deuda.GUARDAS_NUEVAS == carril5_deuda.CONVERTIDAS)
    assert (carril5_deuda.INVENTARIO_BASE_ESTRICTO_MATCH
            - carril5_deuda.CONVERTIDAS
            + carril5_deuda.GUARDAS_NUEVAS
            == carril5_deuda.INVENTARIO_ACTUAL_ESTRICTO_MATCH)


def test_la_deuda_por_familias_suma_el_censo_y_no_deja_huerfanos():
    """Las cuatro cifras de familia eran enteros libres. Ahora las deriva el
    censo, y las familias particionan: la suma TIENE que dar el total."""
    censo = carril5_deuda.censo_inventario("data-engine")
    conteo = carril5_deuda.deuda_por_familia(censo)
    assert sum(conteo.values()) == censo["estricto"]["total"]
    assert set(conteo) == {f for f, _, _ in carril5_deuda.DEUDA_FUERA_DE_ALCANCE}
