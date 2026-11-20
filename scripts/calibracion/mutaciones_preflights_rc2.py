#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibrador de RC2-01 / RC2-03 / RC2-04: cada correccion tiene que saber ponerse roja.

Uso (desde un arbol LIMPIO; las mutaciones se revierten con `git checkout --`):

    python3 scripts/calibracion/mutaciones_preflights_rc2.py

Cada mutacion revierte UNA decision de las correcciones y exige que la suite falle con el
PREFIJO propio de la causa (primera linea del mensaje del test), no con un `repr` de pytest.
Un control nulo (tocar un comentario) tiene que seguir VERDE: si no, el instrumento no sirve.
Salida 0 = todas las mutaciones cazadas con su prefijo.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

PREFLIGHT_SH = "deploy/scripts/preflight.sh"
PREFLIGHT_PY = "deploy/scripts/preflight_ensayo_rc.py"
T_SH = "deploy/tests/test_preflight_rc2_01_state_root.py"
T_PY = "deploy/tests/test_preflight_ensayo_rc_visor_y_boveda.py"


@dataclass(frozen=True)
class Mutacion:
    nombre: str
    fichero: str
    viejo: str
    nuevo: str
    suites: tuple
    #: Prefijos aceptables: el fallo tiene que contener AL MENOS UNO. `None` = control nulo.
    prefijos: tuple | None


CONTROL_NULO = Mutacion(
    "CONTROL NULO: tocar un comentario no cambia nada",
    PREFLIGHT_SH,
    "# RC2-01: en una máquina LIMPIA",
    "# RC2-01 (comentario tocado por el calibrador): en una máquina LIMPIA",
    (T_SH,), None)

_CARGA = ("RC2-03: EL PREFLIGHT NO CARGA EL CATALOGO", "RC2-03: SIN DEPENDENCIAS NO NOMBRA EL INTERPRETE",
          "RC2-03: SIN DEPENDENCIAS NO SALE PENDIENTE")

MUTACIONES = [
    Mutacion("RC2-03 · el catalogo se carga sin preparar el visor de la release",
             PREFLIGHT_PY,
             '    _preparar_visor(raiz)\n    return _cargar(\n        "_s9k_sources_catalog"',
             '    return _cargar(\n        "_s9k_sources_catalog"',
             (T_PY,), _CARGA),
    Mutacion("RC2-03 · el visor ya no se pone en sys.path",
             PREFLIGHT_PY, "        sys.path.append(str(visor))", "        pass",
             (T_PY,), _CARGA),
    Mutacion("RC2-03 · el PENDIENTE deja de nombrar el interprete",
             PREFLIGHT_PY, 'f"el interprete {sys.executable} no puede', 'f"el interprete no puede',
             (T_PY,), ("RC2-03: SIN DEPENDENCIAS NO NOMBRA EL INTERPRETE",)),
    Mutacion("RC2-04 · fuentes.pobladas vuelve a pasar solo S9K_INGEST_SOURCES_DIR",
             PREFLIGHT_PY, "        fuentes = catalogo.listar_fuentes(env)",
             '        fuentes = catalogo.listar_fuentes('
             '{"S9K_INGEST_SOURCES_DIR": env.get("S9K_INGEST_SOURCES_DIR", "")})',
             (T_PY,), ("RC2-04: FALSO ROJO CON BOVEDA DECLARADA",)),
    Mutacion("RC2-04 · la declaracion vuelve a ser solo S9K_INGEST_SOURCES_DIR",
             PREFLIGHT_PY, "        declarada = catalogo.ubicacion_declarada(env)",
             '        declarada = bool(env.get("S9K_INGEST_SOURCES_DIR"))',
             (T_PY,), ("RC2-04: LA BOVEDA SOLA NO CUENTA COMO DECLARACION",)),
    Mutacion("RC2-01 · la maquina limpia vuelve a bloquear",
             PREFLIGHT_SH, 'avso "directorio de estado no existe aún:',
             'bloq "directorio de estado no existe aún:',
             (T_SH,), ("RC2-01: LA MAQUINA LIMPIA SIGUE BLOQUEADA",)),
    Mutacion("RC2-01 · la instalacion previa deja de bloquear",
             PREFLIGHT_SH, 'if [ "${instalacion_previa}" -eq 1 ]; then', "if false; then",
             (T_SH,), ("RC2-01: INSTALACION PREVIA SIN STATE ROOT NO BLOQUEA",)),
    Mutacion("RC2-01 · un state root que no es directorio deja de bloquear",
             PREFLIGHT_SH,
             'if [ -e "${S9K_STATE_ROOT}" ] || [ -L "${S9K_STATE_ROOT}" ]; then',
             "if false; then",
             (T_SH,), ("RC2-01: UN STATE ROOT QUE NO ES DIRECTORIO NO BLOQUEA",)),
]


def _leer(ruta: str) -> str:
    return (REPO / ruta).read_text(encoding="utf-8")


def _limpio() -> bool:
    r = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--untracked-files=no"],
                       capture_output=True, text=True, check=True)
    return not r.stdout.strip()


def _correr(suites: tuple) -> tuple:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", *suites, "-q", "-p", "no:randomly", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=str(REPO), capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def _con_mutacion(m: Mutacion) -> tuple:
    original = _leer(m.fichero)
    if m.viejo not in original:
        return 2, "ANCLA PERDIDA: el texto a mutar ya no esta en %s" % m.fichero
    (REPO / m.fichero).write_text(original.replace(m.viejo, m.nuevo, 1), encoding="utf-8")
    try:
        return _correr(m.suites)
    finally:
        subprocess.run(["git", "-C", str(REPO), "checkout", "--", m.fichero], check=True)
        if _leer(m.fichero) != original:
            raise SystemExit("RESTAURACION FALLIDA en %s: revisa el arbol a mano" % m.fichero)


def main() -> int:
    if not _limpio():
        print("ARBOL SUCIO: commitea antes (las mutaciones se revierten con git checkout --).")
        return 2
    rc, salida = _con_mutacion(CONTROL_NULO)
    if rc != 0:
        print("CONTROL NULO ROJO: el instrumento no sirve.\n" + salida[-2000:])
        return 2
    print("control nulo verde")
    fallos = 0
    for m in MUTACIONES:
        rc, salida = _con_mutacion(m)
        cazada = rc not in (0, 2) and any(p in salida for p in m.prefijos)
        print("%s  %s" % ("CAZADA " if cazada else "ESCAPA ", m.nombre))
        if not cazada:
            fallos += 1
            print("   rc=%s, esperado alguno de %s\n%s" % (rc, m.prefijos, salida[-1200:]))
    print("\n%d mutaciones, %d escapan" % (len(MUTACIONES), fallos))
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
