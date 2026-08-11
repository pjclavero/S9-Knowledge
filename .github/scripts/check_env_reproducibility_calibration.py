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
import re
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
        with:
          node-version: '20'
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


def bloque_job(texto: str, nombre: str) -> str:
    """Extrae el bloque de un job, para poder copiarlo a un fragmento."""
    inicio = texto.index(f"  {nombre}:\n")
    resto = texto[inicio + 1:]
    siguiente = re.search(r"^  [A-Za-z0-9_-]+:\s*$", resto, re.M)
    fin = inicio + 1 + siguiente.start() if siguiente else len(texto)
    return texto[inicio:fin]


def construye(raiz: Path) -> None:
    """Repositorio sintetico que DEBE salir verde."""
    escribe(raiz / ".github" / "workflows" / "ci.yml", CI_BASE)
    # Fragmento FIEL al job de ci.yml: es el estado que debe salir verde.
    escribe(
        raiz / ".github" / "ci-fragments" / "frag.yml",
        "# copia canonica de restitucion\n" + bloque_job(CI_BASE, "test-graph-js"),
    )
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


def corre(raiz: Path, *args: str, path_extra: str = "") -> tuple[int, str]:
    entorno = dict(os.environ, S9K_ENV_REPRO_ROOT=str(raiz))
    if path_extra:
        entorno["PATH"] = path_extra + os.pathsep + entorno.get("PATH", "")
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


def calibra_version_de_runtime(c: "Calibracion") -> None:
    """Un runtime PRESENTE pero de version equivocada tiene que ponerse ROJO.

    Comprobar solo la presencia era una asimetria: para los paquetes de Python
    se exigia version y para los runtimes no, bajo la tesis «lo declarado tiene
    que ser lo ejecutado». Un `node` v18 al frente del PATH pasaba en verde con
    `node-version: '20'` declarado, y la version se llegaba a imprimir sin
    compararla con nada.
    """
    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp) / "repo"
        construye(raiz)
        falso = Path(tmp) / "bin"
        falso.mkdir()

        def instala_node(version: str) -> None:
            binario = falso / "node"
            binario.write_text(f'#!/bin/sh\necho "v{version}"\n', encoding="utf-8")
            binario.chmod(0o755)

        # Base: el `node` falso declara la MISMA version que el ci.yml sintetico.
        instala_node("20.11.0")
        rc0, out0 = corre(raiz, "runtimes", "--require", "node", path_extra=str(falso))
        if rc0 != 0:
            c.fallos.append(f"[runtime con version correcta] deberia ser verde.\n{out0}")
            return

        instala_node("18.0.0")
        rc1, out1 = corre(raiz, "runtimes", "--require", "node", path_extra=str(falso))
        if rc1 == 0:
            c.fallos.append(
                f"[runtime con version equivocada] node v18 con `node-version: "
                f"'20'` declarado NO se detecta: pasa en verde.\n{out1}"
            )
        elif "DIVERGENCIA de version" not in out1:
            c.fallos.append(f"[runtime con version equivocada] mensaje inesperado.\n{out1}")

        instala_node("20.11.0")
        rc2, out2 = corre(raiz, "runtimes", "--require", "node", path_extra=str(falso))
        if rc2 != 0:
            c.fallos.append(f"[runtime con version equivocada] no vuelve a verde.\n{out2}")
        c.filas.append(
            (
                "runtime PRESENTE con version equivocada (node 18 vs 20 declarado)",
                f"ROJO (rc={rc1})" if rc1 != 0 else f"VERDE (rc={rc1}) <-- NO DETECTA",
                f"vuelve a VERDE (rc={rc2})" if rc2 == 0 else f"rc={rc2}",
            )
        )

        # N2: la comprobacion de version NO puede degradar a solo-presencia en
        # silencio. Se deja `node` v18 en el PATH —version equivocada— y se
        # rompe la LEGIBILIDAD de la declaracion: si el gate degradase, esos
        # v18 pasarian en verde. Tiene que ponerse rojo por la declaracion.
        ci_path = raiz / ".github" / "workflows" / "ci.yml"
        original = ci_path.read_text(encoding="utf-8")
        instala_node("18.0.0")
        for etiqueta, mutado, senal in (
            (
                "N2: `node-version` no literal (${{ env.NODE_V }})",
                original.replace("node-version: '20'", "node-version: ${{ env.NODE_V }}"),
                "NO literal",
            ),
            (
                "N2: dos `node-version` distintos en ci.yml",
                original.replace(
                    "  test-login-browser:",
                    "  otro-job-con-node:\n"
                    "    runs-on: ubuntu-latest\n"
                    "    steps:\n"
                    "      - uses: actions/setup-node@v4\n"
                    "        with:\n"
                    "          node-version: '18'\n"
                    "  test-login-browser:",
                ),
                "VARIAS versiones distintas",
            ),
        ):
            escribe(ci_path, mutado)
            rc, out = corre(raiz, "runtimes", "--require", "node", path_extra=str(falso))
            ok = rc != 0 and senal in out
            if not ok:
                c.fallos.append(
                    f"[{etiqueta}] la degradacion silenciosa NO se detecta "
                    f"(rc={rc}); se esperaba rojo mencionando `{senal}`.\n{out}"
                )
            escribe(ci_path, original)
            instala_node("20.11.0")
            rc_v, _ = corre(raiz, "runtimes", "--require", "node", path_extra=str(falso))
            instala_node("18.0.0")
            c.filas.append(
                (
                    etiqueta,
                    f"ROJO (rc={rc})" if ok else f"rc={rc} <-- NO DETECTA",
                    f"vuelve a VERDE (rc={rc_v})" if rc_v == 0 else f"rc={rc_v}",
                )
            )
        escribe(ci_path, original)


LIB_SH = AQUI.parents[1] / "deploy" / "scripts" / "lib.sh"

GUION_FINGERPRINT = """
set -u
export S9K_CHECKSUM_ALGO=sha256
# shellcheck disable=SC1090
. "{lib}"
caso() {{
  create_manifest "$2" "rel-x" "abc123" "test" >/dev/null 2>&1
  python3 -c "import json;m=json.load(open('$2/manifest.json'));print('$1', m.get('dependency_fingerprint_source'), m.get('dependency_fingerprint'))"
}}
T="$1"
caso SIN_NADA "$T/a"
printf 'fastapi>=1,<2\\n' > "$T/b/viewer/requirements.txt"; caso SOLO_RANGOS "$T/b"
printf 'fastapi>=1,<2\\n' > "$T/c/viewer/requirements.txt"
mkdir -p "$T/c/viewer/.venv/bin"
printf '#!/bin/sh\\nexit 0\\n' > "$T/c/viewer/.venv/bin/pip"; chmod +x "$T/c/viewer/.venv/bin/pip"; caso PIP_VACIO "$T/c"
printf 'fastapi>=1,<2\\n' > "$T/d/viewer/requirements.txt"
mkdir -p "$T/d/viewer/.venv/bin"
printf '#!/bin/sh\\necho "otracosa==1.0"\\n' > "$T/d/viewer/.venv/bin/pip"; chmod +x "$T/d/viewer/.venv/bin/pip"; caso PIP_SIN_LO_DECLARADO "$T/d"
printf 'fastapi>=1,<2\\n' > "$T/e/viewer/requirements.txt"
mkdir -p "$T/e/viewer/.venv/bin"
printf '#!/bin/sh\\necho "fastapi==0.141.1"\\n' > "$T/e/viewer/.venv/bin/pip"; chmod +x "$T/e/viewer/.venv/bin/pip"; caso VENV_SANO "$T/e"
printf 'fastapi>=1,<2\\n' > "$T/f/viewer/requirements.txt"
mkdir -p "$T/f/viewer/.venv/bin"
printf '#!/bin/sh\\necho "fastapi-extra==1.0"\\n' > "$T/f/viewer/.venv/bin/pip"; chmod +x "$T/f/viewer/.venv/bin/pip"; caso PIP_PREFIJO_COLISION "$T/f"
"""

# sha256 de la cadena vacia. Es el valor que `pip freeze` vacio producia
# ETIQUETADO como resuelto: un fingerprint que no identifica nada y que dos
# despliegues rotos compartirian, leyendose como «mismas dependencias».
SHA_VACIO = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

ESPERADO_FINGERPRINT = {
    "SIN_NADA": ("none", "unknown"),
    "SOLO_RANGOS": ("declared-ranges", None),
    "PIP_VACIO": ("unresolved", "unknown"),
    "PIP_SIN_LO_DECLARADO": ("unresolved", "unknown"),
    "VENV_SANO": ("resolved:pip-freeze", None),
    # N4d: `fastapi-extra==1.0` NO satisface el requisito de `fastapi`. Con
    # `-` dentro de la clase del separador, un venv sin `fastapi` se etiquetaba
    # `resolved:pip-freeze`: la huella afirmaba identificar unas dependencias
    # que no estaban.
    "PIP_PREFIJO_COLISION": ("unresolved", "unknown"),
}


def calibra_fingerprint(c: "Calibracion") -> None:
    """`dependency_fingerprint` no puede afirmar mas de lo que sabe (D2).

    Los cinco caminos de `create_manifest`, ejecutados de verdad contra
    `lib.sh`. El caso critico es `PIP_VACIO`: un pip que sale 0 sin salida
    daba el sha256 de la cadena vacia etiquetado `resolved:pip-freeze`, que es
    el MISMO defecto que D2 venia a cerrar.
    """
    if not LIB_SH.exists():
        return
    # `create_manifest` ya no acepta un literal de esquema: lee la version del
    # codigo de la propia release y ABORTA si no esta (carril I). Una release
    # sintetica sin esos fuentes no es una release, asi que se plantan con la
    # ayuda que ese mismo carril publico, en vez de duplicar su logica aqui.
    sys.path.insert(0, str(AQUI.parents[1] / "deploy" / "tests"))
    try:
        from schema_source_fixture import plant_schema_sources  # type: ignore
    except ImportError as exc:  # pragma: no cover
        c.fallos.append(f"[fingerprint] no se pudo cargar schema_source_fixture: {exc}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        for sub in "abcdef":
            plant_schema_sources(Path(tmp) / sub)
        guion = Path(tmp) / "fp.sh"
        guion.write_text(GUION_FINGERPRINT.format(lib=LIB_SH), encoding="utf-8")
        r = subprocess.run(
            ["bash", str(guion), tmp], capture_output=True, text=True, timeout=300
        )
        observado = {}
        for linea in r.stdout.splitlines():
            piezas = linea.split()
            if len(piezas) >= 3:
                observado[piezas[0]] = (piezas[1], piezas[2])
        for nombre, (src_esperado, hash_esperado) in ESPERADO_FINGERPRINT.items():
            if nombre not in observado:
                c.fallos.append(f"[fingerprint {nombre}] no se ejecuto.\n{r.stdout}{r.stderr}")
                continue
            src, valor = observado[nombre]
            ok = src == src_esperado and (hash_esperado is None or valor == hash_esperado)
            if ok and SHA_VACIO in valor:
                ok = False
                valor += " (!! sha256 de la cadena vacia)"
            if not ok:
                c.fallos.append(
                    f"[fingerprint {nombre}] esperado source={src_esperado} "
                    f"hash={hash_esperado or '<cualquiera no vacio>'}, "
                    f"observado source={src} hash={valor}"
                )
            c.filas.append(
                (
                    f"D2 fingerprint: {nombre.lower().replace('_', ' ')}",
                    f"source={src}",
                    "correcto" if ok else "<-- INCORRECTO",
                )
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

    def m_fragmento_derivado(raiz: Path) -> None:
        # El fragmento pierde un paso que ci.yml SI tiene. Quien restituya
        # desde el se queda sin ese paso, en silencio.
        frag = raiz / ".github" / "ci-fragments" / "frag.yml"
        texto = frag.read_text(encoding="utf-8")
        escribe(
            frag,
            texto.replace(
                "          python3 .github/scripts/check_env_reproducibility.py runtimes --require node\n",
                "",
            ),
        )

    c.caso("version declarada != instalada", m_version, senal="DIVERGENCIA")
    c.caso(
        "fragmento de CI que ha derivado de ci.yml",
        m_fragmento_derivado,
        senal="perdera pasos en silencio",
    )
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

    calibra_version_de_runtime(c)
    calibra_fingerprint(c)

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
