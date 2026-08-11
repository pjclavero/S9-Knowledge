#!/usr/bin/env python3
"""Calibracion de `check_env_reproducibility.py`.

Regla del operador: una afirmacion no es evidencia porque exista un verde. Lo
es cuando se sabe QUE comportamiento se afirma, se CALIBRA el mecanismo que lo
mide, se INTRODUCE la violacion, el sistema se pone ROJO, se REVIERTE y vuelve
a VERDE. Este fichero es esa calibracion, y se ejecuta en CI en cada corrida:
un gate cuyo mecanismo de medida no se prueba puede llevar meses sin poder
ponerse rojo y nadie lo notaria, que es exactamente el fallo que persigue.

Metodo: se construye un repositorio SINTETICO minimo en un directorio
temporal, con su `ci.yml`, sus requirements y sus tests. El comprobador se
apunta a el con `S9K_ENV_REPRO_ROOT`. Se verifica primero que ese repositorio
sale VERDE (si no, cualquier rojo posterior no probaria nada), y despues, para
cada regla, se introduce UNA violacion, se exige ROJO con el mensaje
correspondiente, se revierte y se exige VERDE de nuevo.

No toca el repositorio real ni la red.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
CHECKER = AQUI / "check_env_reproducibility.py"

# Dependencia real y ya instalada en cualquier entorno de este repositorio
# (la usan los gates de contratos). Se usa como sujeto de las mutaciones de
# version para que el escenario base pueda ser verde de verdad.
SUJETO = "jsonschema"

CI_BASE = """\
name: CI sintetico
on:
  push:
    branches:
      - '**'
jobs:
  test-graph-js:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v7
        with:
          python-version: '3.13'
      - uses: actions/setup-node@v4
      - name: node
        run: |
          python3 .github/scripts/check_env_reproducibility.py runtimes --require node
          python -m pytest viewer/tests/test_graph.py
          # guardia antisalto
          echo skipped
  test-login-browser:
    runs-on: ubuntu-latest
    steps:
      - name: chromium
        run: |
          python -m playwright install --with-deps chromium
          python3 .github/scripts/check_env_reproducibility.py runtimes --require chromium
          python -m pytest tests/browser
          echo skipped
"""

TEST_NODE = """\
import shutil
import pytest

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node no disponible")
def test_algo():
    assert NODE
"""

CONFTEST_BROWSER = """\
import pytest

pytest.importorskip("playwright.sync_api", reason="Playwright no instalado")
"""

TEST_BROWSER = """\
def test_login():
    assert True
"""


def escribe(ruta: Path, texto: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")


def construye(raiz: Path) -> None:
    """Repositorio sintetico que DEBE salir verde."""
    escribe(raiz / ".github" / "workflows" / "ci.yml", CI_BASE)
    escribe(raiz / "viewer" / "requirements.txt", f"{SUJETO}>=4.0,<5.0\n")
    escribe(raiz / "data-engine" / "requirements.lock", f"{SUJETO}==4.26.0\n")
    escribe(raiz / "data-engine" / "requirements.in", f"{SUJETO}\n")
    escribe(raiz / "docs" / "guia.md", f"Se usa `{SUJETO}==4.26.0`.\n")
    escribe(
        raiz / "deploy" / "scripts" / "preflight.sh",
        'if [ "${py_minor}" -ge 13 ]; then ok; fi\n',
    )
    escribe(raiz / "viewer" / "app" / "modulo.py", f"import {SUJETO}\n")
    escribe(raiz / "data-engine" / "app" / "motor.py", f"import {SUJETO}\n")
    escribe(raiz / "viewer" / "tests" / "test_graph.py", TEST_NODE)
    escribe(raiz / "viewer" / "tests" / "browser" / "conftest.py", CONFTEST_BROWSER)
    escribe(raiz / "viewer" / "tests" / "browser" / "test_login.py", TEST_BROWSER)


def corre(raiz: Path, *args: str) -> tuple[int, str]:
    entorno = dict(os.environ, S9K_ENV_REPRO_ROOT=str(raiz))
    r = subprocess.run(
        [sys.executable, str(CHECKER), *args],
        capture_output=True, text=True, env=entorno, timeout=300,
    )
    return r.returncode, r.stdout + r.stderr


class Calibracion:
    def __init__(self) -> None:
        self.fallos: list[str] = []
        self.filas: list[tuple[str, str, str]] = []

    def caso(self, nombre: str, mutar, args=("all",), espera_rojo=True, senal="") -> None:
        """Verde base -> mutacion -> rojo -> revertir -> verde."""
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp) / "repo"
            construye(raiz)

            rc0, out0 = corre(raiz, *args)
            if rc0 != 0:
                self.fallos.append(
                    f"[{nombre}] el escenario BASE no es verde (rc={rc0}); un rojo "
                    f"posterior no probaria nada.\n{out0}"
                )
                return

            mutar(raiz)
            rc1, out1 = corre(raiz, *args)

            if espera_rojo:
                ok_rc = rc1 != 0
                etiqueta_rojo = f"ROJO (rc={rc1})" if ok_rc else f"VERDE (rc={rc1}) <-- NO DETECTA"
            else:
                ok_rc = rc1 == 0 and "::warning::" in out1
                etiqueta_rojo = (
                    f"VERDE con AVISO (rc={rc1})" if ok_rc else f"sin aviso (rc={rc1}) <-- NO SENALA"
                )
            if not ok_rc:
                self.fallos.append(f"[{nombre}] la mutacion NO se detecta.\n{out1}")
            if senal and senal not in out1:
                self.fallos.append(
                    f"[{nombre}] se detecta algo, pero el mensaje no menciona "
                    f"`{senal}`: el gate podria estar fallando por otra causa.\n{out1}"
                )

            # Revertir de verdad: reescribir no basta, porque una mutacion
            # puede AÑADIR un fichero. Se borra el arbol y se reconstruye.
            shutil.rmtree(raiz)
            construye(raiz)
            rc2, out2 = corre(raiz, *args)
            if rc2 != 0:
                self.fallos.append(
                    f"[{nombre}] tras revertir NO vuelve a verde (rc={rc2}); el "
                    f"gate estaria fallando por algo que no es la mutacion.\n{out2}"
                )
            self.filas.append(
                (nombre, etiqueta_rojo, f"vuelve a VERDE (rc={rc2})" if rc2 == 0 else f"rc={rc2}")
            )


def main() -> int:
    c = Calibracion()

    def m_version(raiz: Path) -> None:
        escribe(raiz / "viewer" / "requirements.txt", f"{SUJETO}>=99.0,<100.0\n")

    def m_lock_sin_fijar(raiz: Path) -> None:
        escribe(raiz / "data-engine" / "requirements.lock", f"{SUJETO}>=4.0\n")

    def m_sin_cota(raiz: Path) -> None:
        escribe(raiz / "viewer" / "requirements.txt", f"{SUJETO}>=4.0\n")

    def m_no_declarada(raiz: Path) -> None:
        escribe(raiz / "viewer" / "app" / "extra.py", "import httpx\n")

    def m_node_sin_job(raiz: Path) -> None:
        ci = (raiz / ".github" / "workflows" / "ci.yml").read_text()
        escribe(
            raiz / ".github" / "workflows" / "ci.yml",
            ci.replace("      - uses: actions/setup-node@v4\n", ""),
        )

    def m_chromium_sin_job(raiz: Path) -> None:
        ci = (raiz / ".github" / "workflows" / "ci.yml").read_text()
        escribe(
            raiz / ".github" / "workflows" / "ci.yml",
            ci.replace("python -m playwright install --with-deps chromium", "true"),
        )

    def m_sin_guardia_antisalto(raiz: Path) -> None:
        ci = (raiz / ".github" / "workflows" / "ci.yml").read_text()
        escribe(
            raiz / ".github" / "workflows" / "ci.yml",
            ci.replace("echo skipped", "echo ok"),
        )

    def m_sin_require(raiz: Path) -> None:
        ci = (raiz / ".github" / "workflows" / "ci.yml").read_text()
        escribe(
            raiz / ".github" / "workflows" / "ci.yml",
            ci.replace(
                "python3 .github/scripts/check_env_reproducibility.py runtimes --require node\n",
                "",
            ).replace(
                "python3 .github/scripts/check_env_reproducibility.py runtimes --require chromium\n",
                "",
            ),
        )

    def m_test_nuevo_con_node(raiz: Path) -> None:
        # Un fichero NUEVO que se auto-omite por falta de Node y que ningun job
        # ejecuta por nombre. Es la prueba de que el gate se DERIVA del arbol y
        # no de una lista escrita a mano: manana esto pasa sin avisar a nadie.
        escribe(raiz / "viewer" / "tests" / "test_inventado_manana.py", TEST_NODE)

    # --- divergencias que dejo documentadas el carril I -------------------
    def m_lock_huerfano(raiz: Path) -> None:
        # D5: un pin que no se alcanza desde el `.in` ni por dependencia de
        # nada declarado alli. Es el caso real de `pytest` en el lock del motor.
        escribe(
            raiz / "data-engine" / "requirements.lock",
            f"{SUJETO}==4.26.0\nhttpx==0.28.1\n",
        )

    def m_raiz_sin_pin(raiz: Path) -> None:
        # D5, la otra direccion: el `.in` declara algo que el lock no fija.
        escribe(raiz / "data-engine" / "requirements.in", f"{SUJETO}\nhttpx\n")

    def m_docs_derivadas(raiz: Path) -> None:
        # D7: la documentacion afirma una version que el lock contradice.
        escribe(raiz / "docs" / "guia.md", f"Se usa `{SUJETO}==1.2.3`.\n")

    def m_preflight_por_debajo(raiz: Path) -> None:
        # D6: se acepta desplegar sobre un interprete que CI nunca ejercita.
        escribe(
            raiz / "deploy" / "scripts" / "preflight.sh",
            'if [ "${py_minor}" -ge 11 ]; then ok; fi\n',
        )

    c.caso("version declarada != instalada", m_version, senal="DIVERGENCIA")
    c.caso("D5: pin huerfano en el .lock", m_lock_huerfano, senal="no se alcanzan")
    c.caso("D5: raiz del .in sin fijar en el .lock", m_raiz_sin_pin, senal="NO aparecen fijados")
    c.caso(
        "D7: documentacion que contradice al lock",
        m_docs_derivadas,
        espera_rojo=False,
        senal="ha derivado",
    )
    c.caso(
        "D6: preflight acepta un interprete que CI no prueba",
        m_preflight_por_debajo,
        espera_rojo=False,
        senal="nunca se ha probado",
    )
    c.caso("lock sin fijar (`==`)", m_lock_sin_fijar, senal="no esta FIJADO")
    c.caso(
        "declarada sin cota superior -> SENALADA",
        m_sin_cota,
        espera_rojo=False,
        senal="COTA SUPERIOR",
    )
    c.caso(
        "declarada sin cota superior -> ROJA con --strict-pinning",
        m_sin_cota,
        args=("all", "--strict-pinning"),
        senal="COTA SUPERIOR",
    )
    c.caso("dependencia usada y NO declarada", m_no_declarada, senal="NO esta declarado")
    c.caso("Node: ningun job lo aprovisiona", m_node_sin_job, senal="node")
    c.caso("Chromium: ningun job lo aprovisiona", m_chromium_sin_job, senal="chromium")
    c.caso("guardia antisalto retirada de ci.yml", m_sin_guardia_antisalto, senal="skipped")
    c.caso("paso `runtimes --require` retirado de ci.yml", m_sin_require, senal="--require")
    c.caso("test NUEVO que depende de Node sin job propio", m_test_nuevo_con_node, senal="Node".lower())

    print("\n=== CALIBRACION: mutacion -> resultado -> reversion ===")
    ancho = max(len(f[0]) for f in c.filas)
    for nombre, rojo, verde in c.filas:
        print(f"  {nombre.ljust(ancho)} | {rojo} | {verde}")

    if c.fallos:
        print("\n=== FALLOS DE CALIBRACION ===")
        for f in c.fallos:
            print(f"::error::{f}")
        print(f"\nFALLO: {len(c.fallos)} regla(s) sin calibrar")
        return 1
    print(f"\nOK: {len(c.filas)} reglas calibradas (rojo con la violacion, verde sin ella)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
