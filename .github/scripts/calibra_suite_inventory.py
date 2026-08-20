#!/usr/bin/env python3
"""Calibracion de `check_suite_inventory.py`: tiene que PONERSE ROJO.

Regla del operador: «Una afirmacion no constituye evidencia porque exista un
test verde. La evidencia aparece cuando: sabes que comportamiento afirma;
calibras el mecanismo que lo mide; introduces una violacion; el sistema se pone
rojo; reviertes; vuelve a verde.»

Este arnes NO simula. Escribe los ficheros de verdad —incluidos los tres que el
revisor adversarial del ejercicio RC 1 silencio uno por uno—, ejecuta el gate,
lee el codigo de retorno y restaura. La reversion se verifica por HASH SHA-256
de cada fichero tocado, no por la presencia de una cadena: comprobar que «ya no
esta el `pytestmark`» no demuestra que el fichero haya vuelto a ser el mismo.

    ┌───────────────────────────────────────────────────────────────────────┐
    │  AVISO: ESTE SCRIPT MUTA FICHEROS REALES DEL ARBOL, EN EL SITIO.      │
    │  Borra ficheros de test durante unos segundos por caso. Cualquier     │
    │  otra cosa que lea el repositorio a la vez vera esa mutacion y dara   │
    │  un resultado FALSO. Toma un CERROJO y se niega a arrancar si ya hay  │
    │  otra copia corriendo. Restaura SIEMPRE en `finally`.                 │
    └───────────────────────────────────────────────────────────────────────┘

DOS FAMILIAS DE CASOS
=====================
1. CONTROLES NEGATIVOS. Cada ataque demostrado vivo en el ejercicio RC, mas los
   que el operador exigio: silenciar cada uno de los tres ficheros, borrarlos,
   una caida anormal del recuento, y una dependencia ausente (`jsonschema`,
   `PyYAML`). Todos tienen que salir ROJOS.

   La dependencia ausente NO se finge con una bandera: se bloquea de verdad el
   import mediante un `sitecustomize.py` en `PYTHONPATH` que instala un
   `MetaPathFinder` que rechaza ese modulo. El gate y el pytest que el gate
   lanza lo heredan, asi que el modulo desaparece de la coleccion exactamente
   igual que si no estuviera instalado. Ver `_entorno_sin(paquete)`.

2. ABLACION. Para cada control (A, B, C, D, E) se aplica la mutacion que ese
   control caza y se ejecuta el gate CON ESE CONTROL DESACTIVADO
   (`S9K_INVENTARIO_ABLACION`). El resultado tiene que volverse VERDE. Si sale
   rojo igual, el control no es el que estaba sujetando ese caso; si TODOS los
   casos siguen rojos sin el, el control sobra. Un control que puede
   desaparecer sin que ningun resultado empeore no cuenta como defensa.

Uso:  python3 .github/scripts/calibra_suite_inventory.py
Sale 0 si TODOS los casos dan el veredicto esperado.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / ".github" / "scripts" / "check_suite_inventory.py"
BASE = REPO / ".github" / "suite-inventario.json"

# Los TRES ficheros del ejercicio RC 1, textualmente. No se eligen por bonitos:
# son los que el revisor adversarial silencio uno por uno viendo CI en verde.
PARCIALIDAD = REPO / "viewer" / "tests" / "test_parcialidad_declarada.py"
IDENTIDAD = REPO / "viewer" / "tests" / "test_identidad_durable.py"
CHASIS = REPO / "viewer" / "tests" / "test_chassis_mount_contract.py"
TRES_DEL_RC = (PARCIALIDAD, IDENTIDAD, CHASIS)

# Una suite DELEGADA: sus pruebas solo corren en el job que instala Chromium, y
# ese job las ejecuta por DIRECTORIO. Un fichero menos ahi no baja ningun
# recuento que nadie vigile, asi que su trinquete es de PRESENCIA (C-bis).
NAVEGADOR = REPO / "viewer" / "tests" / "browser" / "test_browser_navigation.py"

# Cualquier fichero que una mutacion pueda tocar. Se salvan enteros y se
# restauran verificando el SHA-256.
AUTHZ_NEO4J = REPO / "viewer" / "tests" / "test_neo4j_integration_authz.py"
# Un modulo del inventario que NO es critico. Hace falta para aislar la ablacion
# de C: ahora que G tiene bandera propia, borrar un modulo CRITICO con C
# ablacionado seguiria saliendo rojo por G, y el caso no demostraria nada.
NO_CRITICO = REPO / "viewer" / "tests" / "test_auth_core.py"
TOCABLES = TRES_DEL_RC + (
    NAVEGADOR,
    NO_CRITICO,
    AUTHZ_NEO4J,
    REPO / ".github" / "workflows" / "ci.yml",
    REPO / ".github" / "suite-bajas.txt",
)

VERDE, ROJO = "VERDE", "ROJO"

CERROJO = (REPO / ".git" / "s9k-calibra-inventario.lock") if (REPO / ".git").is_dir() \
    else Path(tempfile.gettempdir()) / "s9k-calibra-inventario.lock"

SILENCIADOR = (
    "\nimport pytest as _pytest_silenciador  # INYECTADO POR LA CALIBRACION\n"
    "pytestmark = _pytest_silenciador.mark.skip(reason='calibracion')\n"
)


def toma_cerrojo():
    fh = open(CERROJO, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        raise SystemExit(
            f"ERROR: ya hay otra calibracion corriendo ({CERROJO}). Este script "
            f"MUTA y BORRA ficheros de test en el sitio; dos a la vez se pisan y "
            f"producen rojos falsos."
        )
    return fh


def sha(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


# --------------------------------------------------------------------------
# Bloqueo REAL de un paquete (no una bandera que finja su ausencia)
# --------------------------------------------------------------------------

def _entorno_sin(paquete: str) -> tuple[dict, str]:
    """Entorno en el que `paquete` NO se puede importar, de verdad.

    Un `sitecustomize.py` en `PYTHONPATH` instala un `MetaPathFinder` que
    rechaza ese nombre. Lo heredan el gate Y el `pytest` que el gate lanza como
    subproceso, asi que los modulos con `importorskip(paquete)` desaparecen de
    la coleccion igual que si el paquete no estuviera instalado. Es el mismo
    efecto que midio el revisor adversarial desinstalando PyYAML, sin tocar el
    entorno de la maquina.
    """
    tmp = Path(tempfile.mkdtemp(prefix=f"sin-{paquete}-"))
    (tmp / "sitecustomize.py").write_text(
        "import sys\n"
        f"_BLOQUEADO = {paquete!r}\n"
        "class _Veto:\n"
        "    def find_module(self, nombre, ruta=None):\n"
        "        return None\n"
        "    def find_spec(self, nombre, ruta=None, destino=None):\n"
        "        if nombre == _BLOQUEADO or nombre.startswith(_BLOQUEADO + '.'):\n"
        "            raise ModuleNotFoundError(f'bloqueado por la calibracion: {nombre}')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Veto())\n"
        "for _n in [m for m in sys.modules if m == _BLOQUEADO or m.startswith(_BLOQUEADO + '.')]:\n"
        "    del sys.modules[_n]\n",
        encoding="utf-8")
    entorno = dict(os.environ)
    previo = entorno.get("PYTHONPATH", "")
    entorno["PYTHONPATH"] = f"{tmp}{os.pathsep}{previo}" if previo else str(tmp)
    return entorno, str(tmp)


def ejecuta_gate(entorno: dict | None = None) -> tuple[int, str]:
    ent = dict(entorno or os.environ)
    ent["PYTHONDONTWRITEBYTECODE"] = "1"
    p = subprocess.run(
        [sys.executable, str(GATE), "--base-fichero", str(BASE)],
        cwd=REPO, capture_output=True, text=True, timeout=2400, env=ent,
    )
    return p.returncode, p.stdout + p.stderr


# --------------------------------------------------------------------------
# Mutaciones
# --------------------------------------------------------------------------

def m_silencia(ruta: Path):
    def mutacion():
        ruta.write_text(ruta.read_text(encoding="utf-8") + SILENCIADOR, encoding="utf-8")
    return mutacion


def m_borra(ruta: Path):
    def mutacion():
        ruta.unlink()
    return mutacion


def m_skipif_disfrazado():
    """`skipif(True, ...)`: tiene forma de condicional y es un apagado total."""
    PARCIALIDAD.write_text(
        PARCIALIDAD.read_text(encoding="utf-8")
        + "\nimport pytest as _p_cal  # INYECTADO POR LA CALIBRACION\n"
          "pytestmark = _p_cal.mark.skipif(True, reason='calibracion')\n",
        encoding="utf-8")


def m_skipif_condicional():
    """`skipif` sobre una condicion inventada: A1 no lo ve, A2 (trinquete) si."""
    PARCIALIDAD.write_text(
        PARCIALIDAD.read_text(encoding="utf-8")
        + "\nimport os as _os_cal, pytest as _p_cal  # INYECTADO POR LA CALIBRACION\n"
          "pytestmark = _p_cal.mark.skipif(\n"
          "    not _os_cal.environ.get('S9K_UNA_CONDICION_INVENTADA'),\n"
          "    reason='calibracion')\n",
        encoding="utf-8")


def m_caida_de_recuento():
    """Se vacian los tests de un modulo sin borrarlo: el recuento cae.

    No se toca ningun otro modulo, a proposito: asi se demuestra que el
    trinquete es POR MODULO y que anadir tests en otro sitio no lo compensa,
    que es la objecion del operador a un simple minimo N por job.
    """
    lineas = CHASIS.read_text(encoding="utf-8").splitlines(keepends=True)
    salida, saltando = [], False
    quitados = 0
    for linea in lineas:
        if linea.startswith("def test_"):
            if quitados < 5:
                saltando, quitados = True, quitados + 1
                continue
            saltando = False
        elif saltando and (linea.startswith(("def ", "class ", "@")) or
                           (linea.strip() and not linea[0].isspace())):
            saltando = False
        if not saltando:
            salida.append(linea)
    if quitados == 0:
        raise SystemExit("MUTACION IMPOSIBLE: no se encontraron `def test_` en el chasis")
    CHASIS.write_text("".join(salida), encoding="utf-8")


# Ficheros que la calibracion CREA. Se borran en `finally` pasen las cosas
# como pasen: un fichero de calibracion olvidado en `viewer/tests` seria
# basura ejecutandose en CI.
NUEVO_ROTO = REPO / "viewer" / "tests" / "test_calibracion_modulo_que_no_colecciona.py"
NUEVO_SIN_DECLARAR = REPO / "viewer" / "tests" / "test_calibracion_dependencia_no_declarada.py"
# SUP-9 (E3): un directorio de arranque. `sitecustomize.py` lo importa CPython
# por el mero hecho de estar en el path, y ahi dentro cabe el apagado entero
# sin que `ci.yml` mencione ninguna variable prohibida.
DIR_ARRANQUE = REPO / "ci-tools"
ARRANQUE = DIR_ARRANQUE / "sitecustomize.py"

CREADOS = (NUEVO_ROTO, NUEVO_SIN_DECLARAR, ARRANQUE)


def limpia_creados() -> None:
    """Los ficheros que las mutaciones CREAN no se restauran: se borran.

    El directorio de arranque se borra tambien cuando queda vacio: dejarlo
    puesto haria que el caso siguiente arrancara sobre un arbol contaminado, y
    ninguna medida vale sobre un arbol contaminado.
    """
    for f in CREADOS:
        f.unlink(missing_ok=True)
    if DIR_ARRANQUE.is_dir() and not any(DIR_ARRANQUE.iterdir()):
        DIR_ARRANQUE.rmdir()


def m_modulo_no_recolecta():
    """Modulo NUEVO que define tests y no llega a coleccionarse.

    Aisla el control B: como no estaba en la base, C y D no lo miran; no
    silencia nada, asi que A no lo ve; y no usa `importorskip`, asi que E
    tampoco. Si al quitar B esto sale VERDE, B es el unico que lo sujetaba.
    """
    NUEVO_ROTO.write_text(
        "# Creado por calibra_suite_inventory.py; se borra al terminar.\n"
        "raise ImportError('la coleccion de este modulo falla a proposito')\n"
        "\n"
        "def test_que_nunca_se_recolecta():\n"
        "    assert True\n", encoding="utf-8")


def m_dependencia_no_declarada():
    """Modulo NUEVO con `importorskip` de un paquete instalado y NO declarado.

    Aisla el control E (mitad DECLARACION): el paquete importa, asi que el
    modulo SI se recolecta y B no lo ve; no silencia nada (A); es nuevo, asi
    que C y D no lo miran. Lo unico que puede ponerse rojo aqui es E.
    """
    NUEVO_SIN_DECLARAR.write_text(
        "# Creado por calibra_suite_inventory.py; se borra al terminar.\n"
        "import pytest\n"
        # `certifi` esta instalado (llega con `requests`/`httpx`) y NO figura en
        # `viewer/requirements.txt`, que es lo unico que instalan `test-viewer` y
        # `route-map-gate`. Es el caso real: hoy importa, y el dia que deje de
        # llegar por transitividad estas pruebas se vuelven skips verdes.
        "certifi = pytest.importorskip('certifi')\n"
        "\n"
        "def test_usa_una_dependencia_no_declarada():\n"
        "    assert certifi is not None\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# LOS CINCO SUPERVIVIENTES del dictamen NO CONFORME. Cada uno salio VERDE con 0
# errores contra la version anterior del gate. Si alguno vuelve a salir verde,
# esta calibracion falla y se entera todo el mundo.
# ---------------------------------------------------------------------------

CI = REPO / ".github" / "workflows" / "ci.yml"
BAJAS = REPO / ".github" / "suite-bajas.txt"


def m_s1_apagar_test_a_test() -> None:
    """S1: decorar CADA test de la suite critica con `@pytest.mark.skip`.

    El ataque original en otra sintaxis. La coleccion NO cambia (un test con
    `skip` se sigue recolectando), asi que ni A a nivel de modulo ni el
    trinquete de recuento lo veian. Baseline 22 passed -> 0 ejecutados.
    """
    lineas = PARCIALIDAD.read_text(encoding="utf-8").splitlines(keepends=True)
    salida, tocados = [], 0
    for linea in lineas:
        if linea.startswith("def test_") or linea.startswith("class Test"):
            salida.append("@pytest.mark.skip(reason='calibracion S1')\n")
            tocados += 1
        salida.append(linea)
    if tocados == 0:
        raise SystemExit("MUTACION IMPOSIBLE (S1): no hay tests de primer nivel")
    PARCIALIDAD.write_text("".join(salida), encoding="utf-8")


def m_s2_ignore_en_ci() -> None:
    """S2: `--ignore=` de la suite critica en TODAS las invocaciones reales."""
    texto = CI.read_text(encoding="utf-8")
    nuevo_texto = texto.replace(
        "python -m pytest ",
        "python -m pytest --ignore=viewer/tests/test_parcialidad_declarada.py ")
    if nuevo_texto == texto:
        raise SystemExit("MUTACION IMPOSIBLE (S2): no se encontro invocacion")
    CI.write_text(nuevo_texto, encoding="utf-8")


def m_s3_k_en_ci() -> None:
    """S3: `-k 'not parcialidad'` en todas las invocaciones reales."""
    texto = CI.read_text(encoding="utf-8")
    nuevo_texto = texto.replace("python -m pytest ",
                                "python -m pytest -k not_parcialidad ")
    if nuevo_texto == texto:
        raise SystemExit("MUTACION IMPOSIBLE (S3): no se encontro invocacion")
    CI.write_text(nuevo_texto, encoding="utf-8")


def _quita_marcador_critico() -> None:
    texto = PARCIALIDAD.read_text(encoding="utf-8")
    ancla = "pytestmark = pytest.mark.critico"
    if ancla not in texto:
        raise SystemExit("MUTACION IMPOSIBLE (S4): no esta el marcador critico")
    PARCIALIDAD.write_text(
        texto.replace(ancla, "# marcador retirado por la calibracion"),
        encoding="utf-8")


def m_s4_descritificar_en_silencio() -> None:
    """S4: borrar el marcador: los criticos bajan de 20 a 19 sin que nada avise."""
    _quita_marcador_critico()


def m_s5_baja_de_critica_borrando() -> None:
    """S5a: quitar criticidad + declarar baja + borrar el fichero, en UN commit."""
    _quita_marcador_critico()
    BAJAS.write_text(
        BAJAS.read_text(encoding="utf-8")
        + "\nviewer/tests/test_parcialidad_declarada.py\n", encoding="utf-8")
    PARCIALIDAD.unlink()


def m_s5_baja_de_critica_vaciando() -> None:
    """S5b: la misma jugada vaciando el fichero en vez de borrarlo."""
    _quita_marcador_critico()
    BAJAS.write_text(
        BAJAS.read_text(encoding="utf-8")
        + "\nviewer/tests/test_parcialidad_declarada.py\n", encoding="utf-8")
    PARCIALIDAD.write_text("# vaciado por la calibracion\n", encoding="utf-8")


def m_condicion_reescrita() -> None:
    """Menor: reescribir la condicion de un `skipif` ya indultado.

    A2 hace trinquete sobre la PERTENENCIA al conjunto de silenciados, no sobre
    la condicion, asi que sin el control nuevo el modulo quedaba apagado por una
    variable que nadie define y no salia del conjunto.
    """
    ruta = REPO / "viewer" / "tests" / "test_neo4j_integration_authz.py"
    texto = ruta.read_text(encoding="utf-8")
    ancla = "    not URI or not PASSWORD,"
    if ancla not in texto:
        raise SystemExit("MUTACION IMPOSIBLE: no esta la condicion del skipif")
    ruta.write_text(
        texto.replace(ancla, "    not os.environ.get('S9K_JAMAS_DEFINIDA'),"),
        encoding="utf-8")


ADDOPTS = '"--ignore=viewer/tests/test_parcialidad_declarada.py"'


def m_xfail_de_modulo() -> None:
    """X1: `pytestmark = pytest.mark.xfail` en la suite critica.

    EL SUPERVIVIENTE DEL CUARTO DICTAMEN. Diferencial con un defecto inyectado
    de verdad en esta misma suite:

        el defecto SIN xfail  -> 1 failed, 21 passed    EXIT=1  (CI ROJO)
        el MISMO CON xfail    -> 1 xfailed, 21 xpassed  EXIT=0  (CI VERDE)

    Y las DOS capas salian verdes: el reconocedor porque `silenciado()` solo
    modelaba `skip`/`skipif`, y la capa de ejecucion real porque el informe
    JUnit trae las 22 `<testcase>` con `xfail` puesto, asi que `reportadas != 0`.
    Una suite critica que ya no puede fallar con todos los instrumentos en
    verde. `xfail` es PEOR que `skip`: `skip` dice que no se ejecuta; `xfail`
    finge ejecucion y ademas se traga el fallo.
    """
    PARCIALIDAD.write_text(
        PARCIALIDAD.read_text(encoding="utf-8")
        + "\nimport pytest as _pytest_xfail  # INYECTADO POR LA CALIBRACION\n"
          "pytestmark = _pytest_xfail.mark.xfail(reason='infra inestable')\n",
        encoding="utf-8")


def m_xfail_por_decorador() -> None:
    """X2: el mismo apagado test a test, que es como se escribe en la vida real.

    `xfail(reason="infra inestable")` sobre las pruebas que molestan un viernes.
    Ancla distinta de X1 —decoradores, no `pytestmark`— y control distinto
    (`apagados_por_decorador`, no `silenciado`), asi que su rojo es suyo.
    """
    lineas = IDENTIDAD.read_text(encoding="utf-8").splitlines(keepends=True)
    salida, tocados = [], 0
    for linea in lineas:
        if linea.startswith("def test_") or linea.startswith("class Test"):
            salida.append("@pytest.mark.xfail(reason='infra inestable')\n")
            tocados += 1
        salida.append(linea)
    if tocados == 0:
        raise SystemExit("MUTACION IMPOSIBLE (X2): no hay tests de primer nivel")
    IDENTIDAD.write_text("".join(salida), encoding="utf-8")


def m_g1_tee_a_github_env() -> None:
    """G1-bis: escribir en `$GITHUB_ENV` por TUBERIA en vez de por redireccion.

    La lista blanca anterior solo se activaba con `>>`, asi que `tee -a` la
    esquivaba entera. Ancla propia: un paso NUEVO antes del del visor.
    """
    _sustituye_en_ci(
        ANCLA_PASO_VIEWER,
        "      - name: Preparar entorno por tuberia\n        run: |\n"
        f"          printf 'PYTEST_ADD%s\\n' 'OPTS={ADDOPTS}' | tee -a \"$GITHUB_ENV\"\n\n"
        + ANCLA_PASO_VIEWER,
        "G1-tee")


def m_g1_nombre_por_variables() -> None:
    """G1-ter: el nombre armado con DOS variables de shell, sin comillas ni `%s`.

    Ninguna normalizacion de texto puede resolverlo, asi que lo que se prohibe
    es la FORMA. Ancla propia: usa `export`, no `$GITHUB_ENV`, para no apoyarse
    en el rojo de la lista blanca.
    """
    _sustituye_en_ci(
        ANCLA_INVOCACION,
        "          A=PYTEST_ADD; B=OPTS\n"
        f"          export ${{A}}${{B}}={ADDOPTS}\n" + ANCLA_INVOCACION,
        "G1-variables")


def m_prosa_con_invocacion_falsa() -> None:
    """CONTROL POSITIVO: la PROSA no puede mover el censo de invocaciones.

    `derivar_invocaciones()` no saltaba las lineas `#`, asi que un comentario
    que contuviera un token de ruta producia una invocacion FANTASMA y de ahi
    salia una raiz del inventario. Comprobado reescribiendo solo la prosa:
    `raices` cambiaba. Este caso mete un comentario que MENCIONA una invocacion
    con `--ignore` de la suite critica: tiene que salir VERDE, porque un
    comentario no ejecuta nada. Si saliera rojo, el gate estaria leyendo prosa.
    """
    _sustituye_en_ci(
        ANCLA_INVOCACION,
        "          # ejemplo de lo PROHIBIDO, en prosa: python -m pytest "
        f"viewer/tests/ --ignore={{}} tests\n".format(
            "viewer/tests/test_parcialidad_declarada.py")
        + ANCLA_INVOCACION,
        "PROSA")


def m_descritificar_declarado() -> None:
    """Control POSITIVO: descritificar con la suite VIVA y declarandolo.

    Tiene que salir VERDE: retirar la criticidad es legitimo, y es el primero
    de los dos commits que exige retirar una suite critica. Si esto saliera
    rojo, el gate no dejaria ningun camino y acabaria desactivado.
    """
    _quita_marcador_critico()
    BAJAS.write_text(
        BAJAS.read_text(encoding="utf-8")
        + "\ndescritificar: viewer/tests/test_parcialidad_declarada.py\n",
        encoding="utf-8")



# ---------------------------------------------------------------------------
# UN CASO POR SUPERFICIE (SUP-1..SUP-9), CADA UNO CON SU ANCLA PROPIA
# ---------------------------------------------------------------------------
# Exigencia textual del operador: «no confiaria unicamente en "quitar el `^` al
# regex" como demostracion suficiente. La calibracion debe cubrir, como minimo,
# cada sintaxis que realmente usa el repo». Asi que no hay un caso generico de
# "variable prohibida": hay uno por VIA REAL de introducirla, y cada mutacion
# usa un ancla distinta para que ninguna herede el rojo de otra.

# El ancla que el reconocedor viejo NO veia: en este repo TODA invocacion va
# envuelta en `out="$(...)"`, asi que el prefijo `VAR=valor comando` cae dentro
# de una sustitucion de comando y jamas iba tras `^`, `;`, `&&`, `||` ni
# `export `. Es E2, la grave: medido, recolectaba 0 de 22 tests con EXIT=0.
ANCLA_INVOCACION = ('          out="$(python -m pytest viewer/tests/ -v '
                    '--tb=short --no-header 2>&1)"')
ANCLA_JOB_VIEWER = ("  test-viewer:\n"
                    "    name: Viewer Tests\n"
                    "    runs-on: ubuntu-latest\n")
ANCLA_PASO_VIEWER = ("      - name: Run viewer tests\n"
                     "        env:\n"
                     '          S9K_ALLOW_REAL_INGEST: ""\n')
ANCLA_SERVICIO = "          NEO4J_AUTH: neo4j/testtesttest\n"

# Un directorio de arranque: `sitecustomize.py` lo importa CPython por el mero
# hecho de estar en el path, y ahi dentro cabe el apagado entero sin que
# `ci.yml` mencione ninguna variable prohibida. Es E3, el truco del propio
# calibrador puesto del reves.


def _sustituye_en_ci(ancla: str, nuevo: str, etiqueta: str) -> None:
    texto = CI.read_text(encoding="utf-8")
    if ancla not in texto:
        raise SystemExit(f"MUTACION IMPOSIBLE ({etiqueta}): el ancla ya no esta "
                         f"en ci.yml. Un caso que no puede mutar no demuestra "
                         f"nada, y callarlo seria peor.")
    CI.write_text(texto.replace(ancla, nuevo, 1), encoding="utf-8")


def m_sup1_env_workflow() -> None:
    """SUP-1: `env:` a nivel de WORKFLOW: afecta a TODOS los jobs de una vez."""
    texto = CI.read_text(encoding="utf-8")
    if "\njobs:\n" not in texto:
        raise SystemExit("MUTACION IMPOSIBLE (SUP-1): no se encuentra `jobs:`")
    CI.write_text(texto.replace(
        "\njobs:\n", f"\nenv:\n  PYTEST_ADDOPTS: {ADDOPTS}\n\njobs:\n", 1),
        encoding="utf-8")


def m_sup2_env_job() -> None:
    """SUP-2: `env:` del JOB que ejecuta la suite del visor."""
    _sustituye_en_ci(
        ANCLA_JOB_VIEWER,
        ANCLA_JOB_VIEWER + f"    env:\n      PYTEST_ADDOPTS: {ADDOPTS}\n",
        "SUP-2")


def m_sup3_env_paso() -> None:
    """SUP-3: `env:` del PASO que ejecuta la suite."""
    _sustituye_en_ci(
        ANCLA_PASO_VIEWER,
        ANCLA_PASO_VIEWER + f"          PYTEST_ADDOPTS: {ADDOPTS}\n",
        "SUP-3")


def m_sup4_env_container() -> None:
    """SUP-4: `container.env` del job. GitHub lo inyecta en todos sus pasos."""
    _sustituye_en_ci(
        ANCLA_JOB_VIEWER,
        ANCLA_JOB_VIEWER + "    container:\n      image: python:3.13\n"
                           f"      env:\n        PYTEST_ADDOPTS: {ADDOPTS}\n",
        "SUP-4")


def m_sup5_env_servicio() -> None:
    """SUP-5: `services.<id>.env` de un job. Superficie propia de YAML."""
    _sustituye_en_ci(
        ANCLA_SERVICIO,
        ANCLA_SERVICIO + f"          PYTEST_ADDOPTS: {ADDOPTS}\n",
        "SUP-5")


def m_sup6a_prefijo_en_sustitucion() -> None:
    """SUP-6a (E2, la grave): `VAR=valor comando` DENTRO de `out="$(...)"`.

    El comentario del reconocedor viejo decia cubrir el prefijo `VAR=... pytest`
    y no lo cubria: su ancla estaba escrita contra un repo donde la invocacion
    empieza la linea. Aqui NUNCA lo hace.
    """
    _sustituye_en_ci(
        ANCLA_INVOCACION,
        ANCLA_INVOCACION.replace('$(python', f'$(PYTEST_ADDOPTS={ADDOPTS} python'),
        "SUP-6a")


def m_sup6b_export_en_run() -> None:
    """SUP-6b: `export PYTEST_ADDOPTS=` en el mismo `run:` (N12 original)."""
    _sustituye_en_ci(
        ANCLA_INVOCACION,
        f"          export PYTEST_ADDOPTS={ADDOPTS}\n" + ANCLA_INVOCACION,
        "SUP-6b")


def m_sup6c_env_comando() -> None:
    """SUP-6c: `env VAR=valor comando`, la forma que no usa el shell builtin."""
    _sustituye_en_ci(
        ANCLA_INVOCACION,
        ANCLA_INVOCACION.replace(
            '$(python', f'$(env PYTEST_ADDOPTS={ADDOPTS} python'),
        "SUP-6c")


def m_sup7_github_env() -> None:
    """SUP-7 (E1): `echo "VAR=..." >> "$GITHUB_ENV"` en un paso ANTERIOR.

    Es el mecanismo DOCUMENTADO de GitHub para pasar entorno entre pasos: el
    paso siguiente lo hereda. No es un truco, y por eso tiene que enrojecer.
    """
    _sustituye_en_ci(
        ANCLA_PASO_VIEWER,
        "      - name: Preparar entorno\n        run: |\n"
        f'          echo "PYTEST_ADDOPTS={ADDOPTS}" >> "$GITHUB_ENV"\n\n'
        + ANCLA_PASO_VIEWER,
        "SUP-7")


def m_sup8_nombre_construido() -> None:
    """SUP-8: el NOMBRE se construye, asi que ningun control de nombres lo ve.

    Se prohibe la FORMA. Si esto saliera verde, SUP-6 y SUP-7 serian teatro:
    bastaria una variable de shell para no escribir nunca el nombre prohibido.
    """
    _sustituye_en_ci(
        ANCLA_PASO_VIEWER,
        "      - name: Preparar entorno\n        run: |\n"
        "          N=PYTEST_ADDOPTS\n"
        f'          echo "$N={ADDOPTS}" >> "$GITHUB_ENV"\n\n'
        + ANCLA_PASO_VIEWER,
        "SUP-8")


def m_sup9_sitecustomize() -> None:
    """SUP-9 (E3): `sitecustomize.py` en el repo, SIN tocar `ci.yml`.

    Aislado a proposito: no cambia el workflow, asi que su rojo no puede venir
    de ninguna de las otras ocho superficies.
    """
    DIR_ARRANQUE.mkdir(exist_ok=True)
    ARRANQUE.write_text(
        "import os\n"
        'os.environ.setdefault("PYTEST_ADDOPTS", '
        '"--ignore=viewer/tests/test_parcialidad_declarada.py")\n',
        encoding="utf-8")


def m_pythonpath_no_inspeccionable() -> None:
    """`PYTHONPATH` con un valor que este gate NO puede inspeccionar.

    `PYTHONPATH` es LEGAL —`ci.yml` la usa hoy en tres pasos del censo— asi que
    lo que se restringe es el VALOR: si la entrada es dinamica o sale del
    repositorio, nadie puede afirmar que no lleva un `sitecustomize.py`.
    """
    _sustituye_en_ci(
        ANCLA_PASO_VIEWER,
        ANCLA_PASO_VIEWER + '          PYTHONPATH: "$(pwd)/ci-tools"\n',
        "PYTHONPATH")


def m_uses_local() -> None:
    """Accion local: trae su propio `env:` que este gate NO parsea.

    El alcance se declara en el codigo y ademas se hace cumplir: mientras el
    gate no sepa mirar dentro, usarla esta prohibido.
    """
    _sustituye_en_ci(
        ANCLA_PASO_VIEWER,
        "      - name: Accion local\n        uses: ./.github/actions/preparar\n\n"
        + ANCLA_PASO_VIEWER,
        "USES-LOCAL")


def m_control_positivo_entorno() -> None:
    """CONTROL POSITIVO: lo inocuo NO puede enrojecer.

    Un reconocedor sin ancla es ancho, y un gate que se pasa de estricto acaba
    desactivado. Aqui van juntas las formas que MENCIONAN lo prohibido sin
    inyectarlo: un comentario, un `unset`, un nombre que solo CONTIENE el
    prohibido, una variable ajena por `$GITHUB_ENV` y un `PYTHONPATH` legitimo
    dentro del repositorio. Todo esto tiene que salir VERDE.
    """
    _sustituye_en_ci(
        ANCLA_PASO_VIEWER,
        ANCLA_PASO_VIEWER + "          PYTHONPATH: viewer\n",
        "POSITIVO-env")
    _sustituye_en_ci(
        ANCLA_INVOCACION,
        "          # nota: PYTEST_ADDOPTS=--ignore=... esta PROHIBIDO aqui\n"
        "          unset PYTEST_ADDOPTS\n"
        "          MI_PYTEST_ADDOPTS=1\n"
        '          echo "S9K_VARIABLE_INOCUA=1" >> "$GITHUB_ENV"\n'
        + ANCLA_INVOCACION,
        "POSITIVO-run")

CASOS = [
    # (titulo, mutacion, paquete_bloqueado, ablacion, esperado)
    ("estado correcto (control positivo)", None, None, None, VERDE),

    # --- controles negativos exigidos por el operador -------------------
    ("RC-1a: `pytestmark = skip` en test_parcialidad_declarada.py",
     m_silencia(PARCIALIDAD), None, None, ROJO),
    ("RC-1b: `pytestmark = skip` en test_identidad_durable.py",
     m_silencia(IDENTIDAD), None, None, ROJO),
    ("RC-1c: `pytestmark = skip` en test_chassis_mount_contract.py",
     m_silencia(CHASIS), None, None, ROJO),
    ("`skipif(True, ...)`: skip disfrazado de condicional",
     m_skipif_disfrazado, None, None, ROJO),
    ("`skipif` sobre condicion inventada (lo caza el trinquete A2)",
     m_skipif_condicional, None, None, ROJO),
    ("RC-2a: borrar test_parcialidad_declarada.py", m_borra(PARCIALIDAD), None, None, ROJO),
    ("RC-2b: borrar test_identidad_durable.py", m_borra(IDENTIDAD), None, None, ROJO),
    ("RC-2c: borrar test_chassis_mount_contract.py", m_borra(CHASIS), None, None, ROJO),
    ("caida anormal del recuento (5 tests menos en UN modulo)",
     m_caida_de_recuento, None, None, ROJO),
    ("borrar una suite DELEGADA (trinquete de presencia, C-bis)",
     m_borra(NAVEGADOR), None, None, ROJO),

    # --- los cinco supervivientes del dictamen NO CONFORME ---------------
    ("S1: apagar la suite critica TEST A TEST (@pytest.mark.skip x20)",
     m_s1_apagar_test_a_test, None, None, ROJO),
    ("S2: `--ignore=` de la suite critica en las invocaciones de ci.yml",
     m_s2_ignore_en_ci, None, None, ROJO),
    ("S3: `-k` que descarta la suite critica en ci.yml",
     m_s3_k_en_ci, None, None, ROJO),
    ("S4: borrar `pytest.mark.critico` (criticos 20 -> 19 en silencio)",
     m_s4_descritificar_en_silencio, None, None, ROJO),
    ("S5a: descritificar + baja + BORRAR la suite critica en un commit",
     m_s5_baja_de_critica_borrando, None, None, ROJO),
    ("S5b: descritificar + baja + VACIAR la suite critica en un commit",
     m_s5_baja_de_critica_vaciando, None, None, ROJO),
    ("menor: reescribir la condicion de un `skipif` indultado",
     m_condicion_reescrita, None, None, ROJO),
    ("control positivo: descritificar DECLARANDOLO y con la suite viva",
     m_descritificar_declarado, None, None, VERDE),

    # --- filtros POR ENTORNO: UN CASO POR SUPERFICIE REAL ----------------
    # El tercer dictamen NO CONFORME no fue por la LISTA de variables, que era
    # correcta, sino por el ANCLA del reconocedor. Se cierra enumerando las
    # vias, no ensanchando el regex: cada linea de aqui es una superficie
    # distinta con su ancla propia, y ninguna se apoya en el rojo de otra.
    ("SUP-1: `PYTEST_ADDOPTS` en el `env:` del WORKFLOW (todos los jobs)",
     m_sup1_env_workflow, None, None, ROJO),
    ("SUP-2: `PYTEST_ADDOPTS` en el `env:` del JOB",
     m_sup2_env_job, None, None, ROJO),
    ("SUP-3: `PYTEST_ADDOPTS` en el `env:` del PASO",
     m_sup3_env_paso, None, None, ROJO),
    ("SUP-4: `PYTEST_ADDOPTS` en `container.env` del job",
     m_sup4_env_container, None, None, ROJO),
    ("SUP-5: `PYTEST_ADDOPTS` en `services.<id>.env` del job",
     m_sup5_env_servicio, None, None, ROJO),
    ("SUP-6a (E2): `VAR=valor comando` DENTRO de `out=\"$(...)\"`",
     m_sup6a_prefijo_en_sustitucion, None, None, ROJO),
    ("SUP-6b: `export PYTEST_ADDOPTS` dentro del propio `run:`",
     m_sup6b_export_en_run, None, None, ROJO),
    ("SUP-6c: `env VAR=valor comando`",
     m_sup6c_env_comando, None, None, ROJO),
    ("SUP-7 (E1): `echo \"VAR=...\" >> \"$GITHUB_ENV\"` heredado por el paso siguiente",
     m_sup7_github_env, None, None, ROJO),
    ("SUP-8: `$GITHUB_ENV` con el NOMBRE CONSTRUIDO (`$N=...`)",
     m_sup8_nombre_construido, None, None, ROJO),
    ("SUP-9 (E3): `ci-tools/sitecustomize.py` SIN tocar `ci.yml`",
     m_sup9_sitecustomize, None, None, ROJO),
    ("PYTHONPATH con valor dinamico: el gate no puede inspeccionarlo",
     m_pythonpath_no_inspeccionable, None, None, ROJO),
    ("alcance declarado: accion local `uses: ./...` con `env:` no parseado",
     m_uses_local, None, None, ROJO),
    ("control positivo del entorno: comentario, `unset`, nombre que solo "
     "CONTIENE el prohibido, `$GITHUB_ENV` ajeno y `PYTHONPATH` legitimo",
     m_control_positivo_entorno, None, None, VERDE),

    # --- el superviviente del CUARTO dictamen: `xfail` -------------------
    # No es una superficie mas de entorno: es una suite critica que YA NO PUEDE
    # FALLAR, y las dos capas la daban por viva. Va al control A porque `xfail`
    # es un `skip` que ademas finge ejecucion.
    ("X1: `pytestmark = pytest.mark.xfail` en la suite critica",
     m_xfail_de_modulo, None, None, ROJO),
    ("X2: `@pytest.mark.xfail(reason=...)` test a test",
     m_xfail_por_decorador, None, None, ROJO),

    # --- G1 por las dos vias que la lista blanca no gobernaba ------------
    ("G1-bis: `tee -a \"$GITHUB_ENV\"` (tuberia, sin `>>`)",
     m_g1_tee_a_github_env, None, None, ROJO),
    ("G1-ter: nombre armado con dos variables (`${A}${B}=`)",
     m_g1_nombre_por_variables, None, None, ROJO),

    # --- la prosa NO es portante ------------------------------------------
    ("control positivo: un COMENTARIO que menciona `--ignore` de la suite critica",
     m_prosa_con_invocacion_falsa, None, None, VERDE),
    ("RC-3a: `jsonschema` ausente (30+ modulos con importorskip)",
     None, "jsonschema", None, ROJO),
    ("RC-3b: `PyYAML` ausente", None, "yaml", None, ROJO),

    # --- casos que AISLAN un control (previos a su ablacion) ------------
    ("modulo nuevo que no llega a coleccionarse (aisla B)",
     m_modulo_no_recolecta, None, None, ROJO),
    ("dependencia usada y NO declarada en el job (aisla E)",
     m_dependencia_no_declarada, None, None, ROJO),

    # --- ablacion: quitar el control tiene que EMPEORAR el resultado -----
    ("ABLACION A: silenciar con el anti-silenciado quitado",
     m_silencia(PARCIALIDAD), None, "A", VERDE),
    ("ABLACION B: modulo que no colecciona con la anti-desaparicion quitada",
     m_modulo_no_recolecta, None, "B", VERDE),
    ("ABLACION C: borrar un modulo NO critico con el anti-borrado quitado",
     m_borra(NO_CRITICO), None, "C", VERDE),
    ("ABLACION D: caida de recuento con el trinquete de recuento quitado",
     m_caida_de_recuento, None, "D", VERDE),
    ("ABLACION E: dependencia no declarada con el preflight quitado",
     m_dependencia_no_declarada, None, "E", VERDE),
    ("ABLACION F: `--ignore` en ci.yml con el control de filtros quitado",
     m_s2_ignore_en_ci, None, "F", VERDE),
    # H tiene bandera PROPIA, distinta de F: mientras compartieron bandera, un
    # caso de entorno podia estar apoyandose en el rojo del control de
    # ARGUMENTOS. Tres ablaciones, una por familia de superficie (YAML, `run:`
    # y arranque oculto), porque un solo `VERDE` no demuestra que las tres
    # dependan del control.
    ("ABLACION H: SUP-1 (`env:` del workflow) con el control de entorno quitado",
     m_sup1_env_workflow, None, "H", VERDE),
    ("ABLACION H: SUP-6a (prefijo en `$(...)`) con el control de entorno quitado",
     m_sup6a_prefijo_en_sustitucion, None, "H", VERDE),
    ("ABLACION H: SUP-9 (`sitecustomize.py`) con el control de entorno quitado",
     m_sup9_sitecustomize, None, "H", VERDE),
    ("ABLACION H: G1-bis (`tee -a`) con el control de entorno quitado",
     m_g1_tee_a_github_env, None, "H", VERDE),
    ("ABLACION A: `xfail` de modulo con el anti-silenciado quitado",
     m_xfail_de_modulo, None, "A", VERDE),
    ("ABLACION G: descritificar en silencio con el trinquete de criticos quitado",
     m_s4_descritificar_en_silencio, None, "G", VERDE),

    ("restaurado (control positivo final)", None, None, None, VERDE),
]


def main() -> int:
    if not BASE.exists():
        print(f"ERROR: falta {BASE.relative_to(REPO)}; sin base no hay trinquete "
              f"que calibrar. Generalo con `--escribir-inventario`.")
        return 1

    cerrojo = toma_cerrojo()
    print(f"(cerrojo tomado: {CERROJO}; este script MUTA Y BORRA ficheros de "
          f"test en el sitio, no lo ejecutes en paralelo con nada)")

    respaldo = {f: f.read_bytes() for f in TOCABLES}
    hashes = {f: sha(datos) for f, datos in respaldo.items()}
    print("\nSHA-256 de los ficheros tocables ANTES de calibrar:")
    for f, h in hashes.items():
        print(f"  {h}  {f.relative_to(REPO)}")

    filas, fallos, temporales = [], 0, []
    try:
        for titulo, mutacion, bloqueado, ablacion, esperado in CASOS:
            # Estado limpio ANTES de cada caso: el arbol que se mide no puede
            # arrastrar la mutacion del caso anterior.
            for f, datos in respaldo.items():
                f.write_bytes(datos)
            limpia_creados()
            entorno = dict(os.environ)
            entorno.pop("S9K_INVENTARIO_ABLACION", None)
            if bloqueado:
                entorno, tmp = _entorno_sin(bloqueado)
                temporales.append(tmp)
            if ablacion:
                entorno["S9K_INVENTARIO_ABLACION"] = ablacion
            print(f"\n########## {titulo}  (esperado: {esperado})")
            if mutacion is not None:
                mutacion()
            rc, salida = ejecuta_gate(entorno)
            obtenido = VERDE if rc == 0 else ROJO
            print("\n".join(salida.splitlines()[-25:]))
            print(f"RC={rc}  ->  {obtenido}")
            ok = obtenido == esperado
            fallos += 0 if ok else 1
            motivo = "sin errores"
            for linea in salida.splitlines():
                if linea.startswith("::error::"):
                    motivo = linea[len("::error::"):].strip().replace("|", "/")[:110]
                    break
            filas.append((titulo, esperado, rc, obtenido,
                          "OK" if ok else "**DESVIACION**", motivo))
    finally:
        # Restaurar SIEMPRE, tambien ante Ctrl-C: dejar un fichero de test
        # borrado en el arbol seria peor que no haber calibrado.
        for f, datos in respaldo.items():
            f.write_bytes(datos)
        limpia_creados()
        for tmp in temporales:
            subprocess.run(["rm", "-rf", tmp], timeout=30)
        fcntl.flock(cerrojo, fcntl.LOCK_UN)
        cerrojo.close()

    print("\n===== REVERSION VERIFICADA POR SHA-256 =====")
    desvios = 0
    for f, esperado_h in hashes.items():
        real = sha(f.read_bytes())
        marca = "OK" if real == esperado_h else "**NO COINCIDE**"
        desvios += 0 if real == esperado_h else 1
        print(f"  {marca}  {real}  {f.relative_to(REPO)}")
    if desvios:
        print("FALLO: la reversion no devolvio los ficheros a su contenido exacto")
        fallos += desvios

    print("\n\n===== TABLA DE CALIBRACION =====\n")
    print("| Caso | Esperado | RC | Obtenido | Veredicto | Primer error |")
    print("|---|---|---|---|---|---|")
    for fila in filas:
        print("| {} | {} | {} | {} | {} | {} |".format(*fila))

    if fallos:
        print(f"\nCALIBRACION FALLIDA: {fallos} desviacion(es)")
        return 1
    print(f"\nCALIBRACION SUPERADA: {len(filas)}/{len(filas)} casos con el "
          f"veredicto esperado, y los {len(hashes)} ficheros tocados restaurados "
          f"con el MISMO SHA-256")
    return 0


if __name__ == "__main__":
    sys.exit(main())
