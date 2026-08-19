#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibración: mentir en una cifra del carril 5 tiene que ponerse ROJO.

La entrega anterior afirmaba que una prueba «impide que la cifra mienta». No lo
impedía: sólo `SITIOS_SELLADOS` estaba fijado por censo AST. Se pudo declarar
`SITIOS_CON_ANCLA = 71` y `SIN_ANCLA_MEDIDA = 0` --borrando la deuda entera-- y
la suite siguió verde, y lo mismo con `INVENTARIO_ESTRICTO_DATA_ENGINE = 9999`.

Este arnés vuelve a intentar exactamente esas mentiras contra el módulo de hoy.
Cada una debe poner ROJA al menos una prueba. Si alguna sigue verde, la cifra
sigue siendo un parámetro libre y la afirmación seguiría siendo falsa.

Método: una mutación por vez, sobre el árbol real, con reversión verificada por
SHA-256 (se aborta antes de empezar si el árbol no está limpio de sorpresas, y
se restaura pase lo que pase).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "data-engine" / "app"
DEUDA = APP / "tests" / "carril5_deuda.py"
PRUEBA = "tests/test_carril5_exception_codes.py"

#: (nombre, [(constante, valor mentiroso), ...]) — las mentiras que ANTES colaban.
MENTIRAS = [
    ("la deuda entera borrada",
     [("SITIOS_CON_ANCLA", "71"), ("SIN_ANCLA_MEDIDA", "0")]),
    ("inventario inventado",
     [("INVENTARIO_ACTUAL_ESTRICTO", "9999")]),
    ("reparto del inventario falseado",
     [("INVENTARIO_ACTUAL_ESTRICTO_MATCH", "1")]),
    ("inventario de la base falseado",
     [("INVENTARIO_BASE_ESTRICTO", "9999")]),
    ("sitios sellados falseados",
     [("SITIOS_SELLADOS", "70"), ("SITIOS_CON_ANCLA", "48")]),
    ("conversion falseada",
     [("CONVERTIDAS", "999")]),
]

#: La lista nominal no es una constante de una línea, así que se falsea aparte:
#: se borra UNA entrada. Un número puede cuadrar por casualidad; una lista no.
BORRAR_UNA_LINEA_NOMINAL = (
    '    "review/supersede_review.py:336 SupersedeCodes.SCHEMA_INVALID_OUTPUT",\n')


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mentir(texto: str, constante: str, valor: str) -> str:
    patron = re.compile(rf"^{re.escape(constante)} = .+$", re.M)
    nuevo, n = patron.subn(f"{constante} = {valor}", texto, count=1)
    assert n == 1, f"no encontrada la constante {constante}"
    return nuevo


def purgar_pycache() -> None:
    for d in APP.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def correr() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "--no-header", "--tb=no", "-rf", "--color=no", PRUEBA],
        cwd=APP, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def main() -> int:
    original = DEUDA.read_bytes()
    hash_original = sha256(DEUDA)
    informe = {"fichero": str(DEUDA.relative_to(REPO)),
               "sha256_original": hash_original, "resultados": []}
    try:
        for nombre, cambios in MENTIRAS:
            texto = original.decode("utf-8")
            for constante, valor in cambios:
                texto = mentir(texto, constante, valor)
            DEUDA.write_bytes(texto.encode("utf-8"))
            purgar_pycache()
            rc, salida = correr()
            rojas = sorted({ln.split(" ")[1] for ln in salida.splitlines()
                            if ln.startswith("FAILED") and len(ln.split(" ")) > 1})
            informe["resultados"].append({
                "mentira": nombre,
                "cambios": cambios,
                "sha256_mutado": sha256(DEUDA),
                "returncode": rc,
                "rojas": rojas,
                "detectada": rc != 0,
            })
            DEUDA.write_bytes(original)
            assert sha256(DEUDA) == hash_original, "reversion fallida"

        # La lista nominal, falseada borrando una entrada.
        texto = original.decode("utf-8")
        assert BORRAR_UNA_LINEA_NOMINAL in texto, "la entrada a borrar ya no existe"
        DEUDA.write_bytes(texto.replace(BORRAR_UNA_LINEA_NOMINAL, "", 1).encode("utf-8"))
        purgar_pycache()
        rc, salida = correr()
        rojas = sorted({ln.split(" ")[1] for ln in salida.splitlines()
                        if ln.startswith("FAILED") and len(ln.split(" ")) > 1})
        informe["resultados"].append({
            "mentira": "lista nominal recortada (una entrada borrada)",
            "cambios": [("SIN_ANCLA_NOMINAL", "-1 entrada")],
            "sha256_mutado": sha256(DEUDA),
            "returncode": rc,
            "rojas": rojas,
            "detectada": rc != 0,
        })
        DEUDA.write_bytes(original)
        assert sha256(DEUDA) == hash_original, "reversion fallida"
    finally:
        DEUDA.write_bytes(original)
        purgar_pycache()

    informe["sha256_final"] = sha256(DEUDA)
    informe["arbol_intacto"] = informe["sha256_final"] == hash_original
    informe["veredicto"] = ("TODAS LAS MENTIRAS ENROJECEN"
                            if all(r["detectada"] for r in informe["resultados"])
                            else "HAY CIFRAS QUE SIGUEN SIENDO PARAMETROS LIBRES")
    print(json.dumps(informe, indent=1, ensure_ascii=False))
    return 0 if all(r["detectada"] for r in informe["resultados"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
