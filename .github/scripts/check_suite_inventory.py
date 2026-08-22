#!/usr/bin/env python3
"""Anti-desaparicion de suites criticas y preflight de dependencias.

POR QUE EXISTE
==============
El ejercicio RC 1 fallo. Un revisor adversarial demostro DOS verdes falsos
sobre este mismo repositorio, los dos VIVOS:

  1. SILENCIAR UN FICHERO DE GATE ENTERO DEJA TODO VERDE. Puso
     `pytestmark = pytest.mark.skip(...)` en
     `viewer/tests/test_parcialidad_declarada.py`, en
     `viewer/tests/test_identidad_durable.py` y en
     `viewer/tests/test_chassis_mount_contract.py`, uno por uno, y CI siguio
     verde (1554 / 1565 / 1488 passed). La unica guardia que existia era
     `grep -qE '[0-9]+ passed'`: comprueba que se ejecuto ALGO, jamas que se
     ejecuto LO QUE TENIA QUE EJECUTARSE.

  2. UNA DEPENDENCIA AUSENTE CONVIERTE PRUEBAS EN SKIPS VERDES. Sin `PyYAML`,
     293 -> 215 passed, y desaparecian en silencio la politica anti-automerge
     de `dependabot.yml` y la consistencia de documentacion. Con `jsonschema`
     ausente, 30+ modulos con `pytest.importorskip` NUNCA pueden ponerse rojos.

Comprobado aqui, no supuesto (`pytest --collect-only -q` sobre un directorio
sintetico de tres ficheros):

  - un modulo con `pytestmark = skip` SIGUE apareciendo en la coleccion con
    todos sus tests -> el recuento de COLECCION no lo delata; hace falta leer
    el AST del modulo;
  - un modulo con `pytest.importorskip("lo_que_no_esta")` DESAPARECE de la
    coleccion sin error, sin aviso y sin una sola linea en la salida -> el
    recuento de coleccion SI lo delata, y es exactamente la misma senal que
    produce un fichero borrado.

DE DONDE SALE LA LISTA DE MODULOS (no es una lista documental)
=============================================================
La condicion del operador es explicita: la lista de suites obligatorias no
puede mantenerse a mano, porque eso recrea el problema de las viejas listas
blancas —el mismo que `check_ci_config.py` documenta haber sufrido tres veces
con `on.push.branches`—. Aqui NADA se escribe a mano. Hay cinco fuentes, todas
EJECUTABLES, y todas crecen solas:

  F1. LO QUE EL JOB INVOCA DE VERDAD. `ci.yml` se parsea con `yaml.safe_load`
      (no con regex) y de cada `run:` se extraen las invocaciones reales de
      pytest, con sus rutas y su `cd`. Si una invocacion no lleva rutas, las
      rutas son las de `pytest.ini:testpaths`, que es lo que ese mismo pytest
      recorreria. Ver `derivar_invocaciones()`.

  F2. LA COLECCION REAL. Sobre esas raices se ejecuta `pytest --collect-only`.
      El inventario es lo que pytest dice haber recolectado, no lo que un
      documento afirma. Ver `inventario_recolectado()`.

  F3. EL ARNES DE CALIBRACION QUE USA LA SUITE COMO INSTRUMENTO. Se parsea con
      AST (no con grep) cada calibrador de `scripts/calibrar_*.py`,
      `scripts/calibracion/**` y `artifacts/**/calibrar.py`, y toda constante
      de modulo cuyo valor resuelva a un fichero de test EXISTENTE marca ese
      modulo como CRITICO. Razon: si el instrumento de una calibracion se
      silencia, la calibracion certifica el vacio. Ver
      `criticos_por_calibrador()`.

  F4. EL MARCADOR EN EL PROPIO TEST. `pytest.mark.critico` a nivel de modulo,
      registrado en `pytest.ini`. Es el enganche para una suite que sea
      critica sin que ningun calibrador la nombre todavia. Se lee por AST.
      Ver `criticos_por_marcador()`.

  F5. EL TRINQUETE. Todo modulo que ESTUVO en el inventario de la base de
      comparacion (`git merge-base HEAD origin/main`) tiene que seguir en el
      inventario de HEAD. Esta es la fuente que hace que la proteccion crezca
      SOLA: un modulo nuevo entra en el inventario en cuanto se mergea, y
      desde ese momento no puede desaparecer. No hay nada que anadir a mano
      nunca. Es el mismo mecanismo que G17 en `scripts/route_map/gate.py`.

QUE COMPRUEBA
=============
  A. ANTI-SILENCIADO (AST). Ningun modulo del inventario puede estar apagado a
     nivel de modulo (`pytestmark` con `skip`/`skipif`,
     `pytest.skip(allow_module_level=True)`). ROJO. Cubre el ataque 1 para
     TODOS los modulos, presentes y futuros, sin lista ninguna.

  B. ANTI-DESAPARICION. Todo `test_*.py` que EXISTE en el arbol bajo una raiz
     invocada tiene que aparecer en la coleccion con >=1 test. Un
     `importorskip` insatisfecho, un error de coleccion o un modulo vaciado se
     ponen ROJOS aqui. Cubre el ataque 2.

  C. ANTI-BORRADO (trinquete F5). Un modulo del inventario de la base que ya
     no esta en el de HEAD es ROJO. Una baja DELIBERADA se declara en
     `.github/suite-bajas.txt`, que es una lista de EXCEPCIONES —visible en el
     diff, que es justo el efecto que se busca— y NO una lista de
     protecciones. Un modulo CRITICO (F3/F4) no se puede dar de baja por ahi:
     para eso hay que quitarle antes el calibrador o el marcador, y eso se ve.

  D. TRINQUETE DE RECUENTO. Por modulo y global, contra la base. Es
     COMPLEMENTARIO, no la garantia: por modulo, anadir tests irrelevantes en
     otro sitio no compensa una caida aqui, que es la objecion exacta del
     operador a un simple minimo N por job.

  E. PREFLIGHT DE DEPENDENCIAS. Todo `pytest.importorskip("X")` de los modulos
     invocados tiene que poder importarse en el entorno del job. Si no, ROJO
     ANTES de aceptar el job, en vez de N pruebas menos en silencio. Los
     ficheros que dependen de herramientas EXTERNAS ya modeladas en
     `check_ci_config.HERRAMIENTAS` (Node, Chromium/Playwright) quedan
     DELEGADOS en ese gate, que exige un job que las instale, los ejecute por
     nombre y falle si ve `skipped`. Delegar no es eximir: la delegacion se
     DERIVA llamando a `check_ci_config.ficheros_con_skip_critico()` y a
     `comprueba_skips_criticos()`, asi que si ese gate deja de cubrirlos, esto
     se pone rojo tambien.

ABLACION
========
`S9K_INVENTARIO_ABLACION=A|B|C|D|E|F|G|H` desactiva UN control (H son los
filtros por VARIABLE DE ENTORNO, SUP-1..SUP-9). Existe para que
`calibra_suite_inventory.py` demuestre que quitar cada control hace que una
mutacion que estaba ROJA vuelva a VERDE. Un control que puede desaparecer sin
que ningun resultado cambie no es un control. Fuera de la calibracion no se
usa, y el gate lo GRITA en la salida para que no pueda dejarse puesto.

DEPENDENCIA: PyYAML. Deliberada, misma razon que en `check_ci_config.py`.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print(
        "::error::falta PyYAML y este gate parsea `ci.yml` de verdad. Es "
        "exactamente el fallo que persigue: una dependencia ausente NO puede "
        "degradarse a una comprobacion parcial."
    )
    sys.exit(1)

REPO = Path(__file__).resolve().parents[2]
CI = REPO / ".github" / "workflows" / "ci.yml"
PYTEST_INI = REPO / "pytest.ini"
BAJAS = REPO / ".github" / "suite-bajas.txt"
INVENTARIO = REPO / ".github" / "suite-inventario.json"

sys.path.insert(0, str(REPO / ".github" / "scripts"))

ABLACION = os.environ.get("S9K_INVENTARIO_ABLACION", "").strip().upper()

# Igual que en `check_ci_config.py`: invocar pytest no es instalarlo.
RE_INVOCA_PYTEST = re.compile(r"(python[0-9.]*\s+-m\s+pytest|(?<![\w./\"'-])pytest\s)")
RE_INSTALA = re.compile(r"\bpip\s+install\b|\buv\s+pip\b")
RE_CD = re.compile(r"(?:^|;|&&)\s*cd\s+([^\s;&|]+)")

# Opciones de pytest que consumen el token siguiente. Sin esto, `-p mi_plugin`
# dejaria `mi_plugin` colandose como si fuera una ruta.
OPCIONES_CON_VALOR = {"-p", "-k", "-m", "-n", "--tb", "--rootdir", "-o",
                      "--deselect", "--ignore"}

TOLERANCIA_GLOBAL = 0.02  # 2%: por debajo es ruido de un rename, no una caida


# --------------------------------------------------------------------------
# F1: lo que el job invoca de verdad
# --------------------------------------------------------------------------

def testpaths_de_pytest_ini() -> list[str]:
    """`testpaths` es configuracion EJECUTABLE: lo que pytest recorreria."""
    if not PYTEST_INI.exists():
        return []
    for linea in PYTEST_INI.read_text(encoding="utf-8").splitlines():
        if linea.strip().startswith("testpaths"):
            return linea.split("=", 1)[1].split()
    return []


def _banderas_de_linea(linea: str) -> list[str]:
    """Las OPCIONES de una invocacion de pytest, que antes se tiraban.

    `_rutas_de_linea` las descartaba para no confundirlas con rutas y ahi
    moria la vigilancia: `--ignore` y `-k` viajaban en esas opciones. Ahora se
    recogen para que `comprueba_filtros_de_exclusion` pueda mirarlas.
    """
    pos = linea.find("pytest")
    if pos < 0:
        return []
    banderas = []
    for bruto in linea[pos + len("pytest"):].split():
        token = bruto.strip("\"'")
        if token.startswith("-") and token not in ("-", "--"):
            banderas.append(token)
    return banderas


def _rutas_de_linea(linea: str, cwd: Path) -> list[str]:
    """Argumentos posicionales de una invocacion de pytest que son rutas reales.

    NO se usa `shlex`: estas lineas viven dentro de `out="$(... 2>&1)"` y
    `shlex` las parte mal. Se toma lo que va DESPUES de `pytest` y se descartan
    opciones, sustituciones de shell y redirecciones. Lo que sobrevive tiene
    que EXISTIR en disco para contar como ruta: asi un token raro no puede
    inventarse una raiz, y una raiz renombrada deja de encontrarse, que es la
    senal correcta y no un silencio.
    """
    pos = linea.find("pytest")
    if pos < 0:
        return []
    resto = linea[pos + len("pytest"):]
    rutas: list[str] = []
    saltar = False
    for bruto in resto.split():
        if saltar:
            saltar = False
            continue
        token = bruto.strip("\"'")
        if token.startswith("-"):
            if token in OPCIONES_CON_VALOR:
                saltar = True
            continue
        if not token or any(c in token for c in "$><|)(&;"):
            continue
        if (cwd / token.split("::")[0]).exists():
            rutas.append(token)
    return rutas


def derivar_invocaciones() -> list[dict]:
    """(job, paso, cwd, raices) de CADA invocacion real de pytest en `ci.yml`.

    Esta es la fuente canonica de «que suites esta obligado a ejecutar este
    CI»: no un documento, sino los comandos que los jobs ejecutan.
    """
    datos = yaml.safe_load(CI.read_text(encoding="utf-8"))
    salida = []
    for job_id, job in (datos.get("jobs") or {}).items():
        for paso in (job or {}).get("steps") or []:
            if not isinstance(paso, dict) or not isinstance(paso.get("run"), str):
                continue
            cwd = REPO
            for linea in paso["run"].splitlines():
                # Los COMENTARIOS no invocan nada. Sin esta linea, la PROSA era
                # portante: un comentario que contuviera el token `tests`
                # producia una invocacion fantasma, y de esa invocacion salia
                # una raiz del inventario. Comprobado reescribiendo SOLO la
                # prosa de `ci.yml`: `raices` cambiaba. Era inocuo y del lado
                # seguro —sobraban raices, no faltaban—, pero es exactamente la
                # clase de defecto que persigue este carril: una lista DERIVADA
                # que depende de algo que nadie considera portante.
                if linea.lstrip().startswith("#"):
                    continue
                m = RE_CD.search(linea)
                if m:
                    candidato = (cwd / m.group(1)).resolve()
                    if candidato.is_dir():
                        cwd = candidato
                if not RE_INVOCA_PYTEST.search(linea) or RE_INSTALA.search(linea):
                    continue
                raices = _rutas_de_linea(linea, cwd)
                cwd_efectivo = cwd
                if not raices:
                    # Sin rutas explicitas manda `testpaths`, que es lo que ese
                    # mismo pytest recorreria. No es una suposicion.
                    raices = testpaths_de_pytest_ini()
                    cwd_efectivo = REPO
                salida.append({
                    "job": job_id,
                    "paso": str(paso.get("name") or "(sin nombre)"),
                    "cwd": cwd_efectivo.relative_to(REPO).as_posix() or ".",
                    "raices": raices,
                    "banderas": _banderas_de_linea(linea),
                })
    return salida


# Banderas que EXCLUYEN parte de lo que la invocacion recorre. Prohibidas en
# los jobs vigilados, y la prohibicion nace de dos supervivientes MEDIDOS:
#
#   `--ignore=viewer/tests/test_parcialidad_declarada.py` en las 4 invocaciones
#   reales de `ci.yml`  -> el gate salio VERDE.
#   `-k 'not parcialidad'`                                -> VERDE tambien.
#
# La causa raiz es exacta y merece quedar escrita: `derivar_invocaciones()`
# saca las RAICES que el job recorre y despues el gate construye SU PROPIO
# argv. Los filtros del job se descartaban. F1 medía qué RECORRE el job, no qué
# EXCLUYE, que es literalmente la familia de fallo que este fichero cierra.
#
# Se PROHIBEN en vez de replicarse. Replicarlas dejaria al gate midiendo el
# recorte y certificandolo como si fuera la suite; prohibirlas obliga a que un
# job requerido ejecute TODO lo que recorre. Es el mismo patron que la
# autoguardia de `--sin-base`, que ya existia y funcionaba.
#
# `-p` NO esta aqui: carga un plugin, no recorta nada (`route-map-gate` lo
# necesita para la sonda). `--tb`, `-q`, `-v` y `--no-header` tampoco tocan qué
# se ejecuta.
BANDERAS_QUE_EXCLUYEN = (
    "--ignore", "--ignore-glob", "--deselect", "-k", "-m",
    "--lf", "--last-failed", "--ff", "--failed-first", "--sw", "--stepwise",
    "--co",
)


# Variables de entorno que inyectan OPCIONES de pytest sin tocar la linea de
# comandos. Prohibidas en `ci.yml` alla donde aparezcan.
#
# ESTO ES UN SUPERVIVIENTE MEDIDO, y de los caros: el control F prohibia
# `--ignore` y `-k` en los ARGUMENTOS, y `PYTEST_ADDOPTS` mete exactamente esas
# mismas opciones POR ENTORNO. Tres variantes salieron VERDES con 0 errores:
#
#   N4  `PYTEST_ADDOPTS: "--ignore=..."` en el `env:` de un job.
#   N5  las mismas lineas a nivel de WORKFLOW, encima de `jobs:`, que afecta a
#       TODOS los jobs de una vez.
#   N12 `export PYTEST_ADDOPTS=...` DENTRO del mismo bloque `run:` que el
#       control F ya parseaba.
#
# Consecuencia medida: `pytest viewer/tests/` pasa de recolectar 22 tests de
# `test_parcialidad_declarada.py` a recolectar CERO. Y hay un detalle que
# conviene no olvidar: la invocacion por RUTA EXPLICITA no lo delata; la
# invocacion por DIRECTORIO —la que usan `test-viewer`, `test-combined` y
# `route-map-gate`— si.
#
# Causa raiz: `_banderas_de_linea()` lee los ARGUMENTOS de la invocacion, y
# esto viaja por otra puerta. Es la familia de S2/S3 otra vez, asi que se cierra
# igual: PROHIBIR, no replicar. Replicarlo dejaria al gate midiendo el recorte y
# certificandolo como si fuera la suite.
#
# `PYTEST_DISABLE_PLUGIN_AUTOLOAD` va en la misma lista por la misma razon y no
# por simetria: apaga los plugins que se cargan solos, y una suite que dependa
# de uno de ellos desaparece o se auto-omite sin que cambie ni un argumento.
# Hoy `ci.yml` no usa ninguna de las dos, asi que la prohibicion nace sin
# excepciones; una exencion que hoy no hace falta es la rendija por la que
# manana entra el apagado.
# ---------------------------------------------------------------------------
# ENUMERACION DE SUPERFICIES (control F-env)
# ---------------------------------------------------------------------------
# El reconocedor anterior fue atravesado por un revisor independiente con dos
# formas triviales, ambas con EXIT=0 y cero errores. La causa no fue la LISTA
# de variables --era correcta-- sino el ANCLA del reconocedor: exigia que el
# nombre fuese tras inicio de linea, `;`, `&&`, `||` o `export `.
#
#   E2  out="$(PYTEST_ADDOPTS=--ignore=... python -m pytest viewer/tests/ ...)"
#       El comentario del propio codigo decia cubrir `VAR=... pytest ...` como
#       PREFIJO y no lo cubria, porque en ESTE repo toda invocacion va envuelta
#       en `out="$(...)"` (el idioma que el propio autor documento en
#       `_rutas_de_linea`). El ancla estaba escrita contra otro repo.
#       Medido: recolecta 0 de los 22 tests de `test_parcialidad_declarada.py`.
#   E1  `echo "PYTEST_ADDOPTS=..." >> $GITHUB_ENV` en un paso anterior del
#       mismo job: el siguiente lo HEREDA. Es el mecanismo DOCUMENTADO de
#       GitHub, no un truco.
#   E3  `PYTHONPATH: ci-tools` + `ci-tools/sitecustomize.py` que hace
#       `os.environ.setdefault("PYTEST_ADDOPTS", ...)`. Es el truco del propio
#       calibrador, del reves.
#
# Ensanchar el regex habria tapado E1 y E2 de una vez, y eso es exactamente lo
# que el operador rechazo como demostracion: «no es tener un regex mas ancho;
# es que cada via real de introducir una variable prohibida tenga un control
# negativo permanente». Asi que las superficies se ENUMERAN, y cada una tiene
# su caso en `calibra_suite_inventory.py` con su ancla propia:
#
#   SUP-1  `env:` del WORKFLOW           (afecta a TODOS los jobs)
#   SUP-2  `env:` del JOB
#   SUP-3  `env:` del PASO
#   SUP-4  `jobs.<id>.container.env`     (el contenedor del job)
#   SUP-5  `jobs.<id>.services.<s>.env`  (contenedores de servicio)
#   SUP-6  asignacion DENTRO del `run:`, en CUALQUIER posicion de la linea:
#          `VAR=v cmd`, `export VAR=v`, `env VAR=v cmd`, `VAR=v; cmd`,
#          y --la que fallaba-- `out="$(VAR=v cmd)"`.
#   SUP-7  `echo "VAR=v" >> "$GITHUB_ENV"` y variantes (printf, heredoc):
#          es SUP-6 en otra sintaxis, y el mismo reconocedor sin ancla la ve.
#   SUP-8  escritura a `$GITHUB_ENV` con el NOMBRE CONSTRUIDO
#          (`N=PYTEST_ADDOPTS; echo "$N=..." >> $GITHUB_ENV`): ningun regex
#          sobre nombres literales puede verla, asi que se prohibe la forma.
#   SUP-9  `sitecustomize.py` / `usercustomize.py` en el arbol del repo: Python
#          los importa SOLO por estar en el path, sin que ninguna variable
#          prohibida aparezca en `ci.yml`. Es E3.
#   SUP-10 `container.options` / `services.<id>.options` con `-e VAR=v`: el
#          paso-through documentado a `docker create`. Lo heredan TODOS los
#          pasos del job sin tocar ningun `env:`. Es G2.
#   SUP-11 `uses:` a nivel de JOB (workflow reutilizable local): trae su propio
#          `env:` y sus propios pasos. Es G3, el mismo agujero que ya estaba
#          cerrado en el paso, un nivel mas arriba.
#
# ADVERTENCIA QUE NO SE PUEDE BORRAR: esta enumeracion se ha quedado corta
# TRES veces seguidas, y cada vez el hueco fue una superficie que GitHub o
# Docker documentan y aqui nadie habia mirado. La superficie de CAUSAS es
# ABIERTA. Por eso desde esta ronda estos once controles NO son la unica linea:
# `check_ejecucion_real.py` compara, modulo a modulo, lo que el job EJECUTO de
# verdad (`--junitxml`) contra el inventario, y enrojece SIN IMPORTAR POR QUE
# desaparecio una suite. Estos SUP se quedan como defensa en profundidad —una
# capa que mira la causa avisa antes y dice QUE se rompio—, pero la garantia
# ya no depende de haberlos enumerado todos.
#
# ALCANCE DECLARADO --lo que esta politica NO cubre, dicho explicitamente en
# vez de callado:
#   * `defaults:` de GitHub NO admite `env:`. No es una superficie; aun asi se
#     comprueba que no aparezca uno, para que no lo sea en silencio manana.
#   * Acciones compuestas y workflows reutilizables locales (`uses: ./...`)
#     traen su propio `env:` que este gate no parsea. Hoy `ci.yml` no usa
#     ninguno: se prohibe usarlos hasta que el gate sepa mirarlos, en vez de
#     dejar la puerta entornada.
#   * Los `secrets`/`vars` de la organizacion y las variables del RUNNER no se
#     ven desde el repositorio. Quedan FUERA de esta garantia, y se dice aqui.
VARIABLES_QUE_FILTRAN = (
    "PYTEST_ADDOPTS",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    "PYTEST_PLUGINS",
)

# `PYTHONPATH` no se puede PROHIBIR y decir la verdad: `ci.yml` la usa HOY en
# tres pasos legitimos del censo de rutas (`PYTHONPATH: scripts:viewer` y
# `PYTHONPATH: scripts`). Prohibirla pondria el CI en rojo por un uso correcto,
# que es la forma mas rapida de que un gate acabe desactivado. Lo que la hace
# peligrosa es concreto y se ataca concreto: un directorio del path puede
# llevar un `sitecustomize.py` que inyecte lo prohibido desde dentro (E3). Asi
# que la variable es LEGAL y su VALOR es lo que se restringe.
VARIABLES_CON_POLITICA_DE_VALOR = ("PYTHONPATH",)

VARIABLES_VIGILADAS = VARIABLES_QUE_FILTRAN + VARIABLES_CON_POLITICA_DE_VALOR

# Los dos nombres que CPython importa por el mero hecho de estar en el path.
FICHEROS_DE_ARRANQUE = ("sitecustomize.py", "usercustomize.py")

# SIN ANCLA, a proposito: el nombre cuenta DONDEQUIERA que aparezca en la
# linea. `\b` sigue impidiendo el falso positivo de `MI_PYTEST_ADDOPTS=`, que
# es otro nombre y no esta en la lista.
RE_ASIGNA_ENTORNO = re.compile(r"\b([A-Z_][A-Z0-9_]*)\s*=")

# Escritura al fichero que GitHub convierte en entorno del PASO SIGUIENTE.
# TODA mencion del fichero, no solo la REDIRECCION. La version anterior exigia
# `>>`, y por eso cuatro variantes con TUBERIA salieron verdes de punta a punta:
#   printf 'PYTEST_ADD%sOPTS=...\n' '' | tee -a "$GITHUB_ENV"
#   printf 'PYTEST_ADD%s\n' 'OPTS=...'  | tee -a "$GITHUB_ENV"
#   echo "PYTEST_ADD$(echo)OPTS=..."     | tee -a "$GITHUB_ENV"
#   A=PYTEST_ADD; B=OPTS; echo "${A}${B}=..." | tee -a "$GITHUB_ENV"
# `tee -a` escribe igual que `>>` y la lista blanca ni se activaba. Lo que
# importa no es el operador: es que ese fichero se convierte en el entorno del
# paso SIGUIENTE, asi que cualquier forma de escribir en el esta gobernada.
RE_GITHUB_ENV = re.compile(r"\$\{?GITHUB_ENV\}?")
# G1: `RE_NOMBRE_CONSTRUIDO` exigia un `$`, y un revisor lo esquivo SIN `$`:
#   echo "PYTEST_ADD""OPTS=--ignore=..." >> $GITHUB_ENV     -> EXIT=0
# Las comillas vacias no son un `$`, y `RE_ASIGNA_ENTORNO` solo veia `OPTS=`.
# La linea emite literalmente el nombre prohibido. `printf 'PYTEST_ADD%s'
# 'OPTS=...'` es la misma familia. Prohibir "construir con `$`" solo obligaba a
# construir con dos comillas: teatro un caracter mas alla.
#
# Se invierte la polaridad: en vez de enumerar las formas MALAS de construir un
# nombre —que son infinitas— se pone en lista blanca la UNICA forma que este
# gate puede verificar, y todo lo demas es rojo. Fail-closed.
RE_ECHO_LITERAL_A_GITHUB_ENV = re.compile(
    r"""^\s*echo\s+(?P<c>["']?)(?P<carga>[A-Za-z_][A-Za-z0-9_]*=[^"'$`%\\]*)(?P=c)"""
    r"""\s*>>\s*"?\$\{?GITHUB_ENV\}?"?\s*$""")

# Cualquier par de comillas, para volver a leer la linea SIN ellas. Asi
# `PYTEST_ADD""OPTS=` se lee tambien como `PYTEST_ADDOPTS=` y lo caza el
# reconocedor de nombres de SUP-6/7, no solo la lista blanca de arriba.
RE_COMILLAS = re.compile(r"[\"']")

# Lo que el shell COLAPSA al construir una palabra: comillas vacias, `%s` de
# `printf`, `$(...)`, `${VAR}` y `$VAR`. La relectura sin comillas sola no
# bastaba —solo rejuntaba nombres partidos con comillas— y un `%s`, un `$()` o
# dos variables metian un caracter que no es de nombre. Se prueban VARIAS
# normalizaciones y basta que UNA revele un nombre prohibido.
RE_SUSTITUCION = re.compile(r"\$\([^)]*\)|\$\{\w+\}|\$\w+|%[sd]")

# Un nombre de variable CONSTRUIDO con expansiones, en cualquier asignacion del
# `run:`: `${A}${B}=v`, `$X=v`. Sin espacio antes del `=`, que es lo que
# distingue una asignacion de shell de una comparacion `[ "$x" = "y" ]`.
RE_ASIGNA_NOMBRE_CONSTRUIDO = re.compile(
    r"(?:^|[\s;&|(])((?:\$\{?\w+\}?|[A-Za-z_][A-Za-z0-9_]*){2,})=")


def _env_de(nodo) -> dict:
    valor = nodo.get("env") if isinstance(nodo, dict) else None
    return valor if isinstance(valor, dict) else {}


def _politica_de_pythonpath(valor: str, donde: str) -> list[str]:
    """`PYTHONPATH` es legal; sus entradas no pueden ser un arranque oculto."""
    errores = []
    for entrada in str(valor).split(os.pathsep):
        entrada = entrada.strip().strip("\"'")
        if not entrada:
            continue
        if "$" in entrada or entrada.startswith("/") or ".." in entrada.split("/"):
            errores.append(
                f"PYTHONPATH NO INSPECCIONABLE: la entrada `{entrada}` de "
                f"`PYTHONPATH` en {donde} es dinamica o sale del repositorio, "
                f"asi que este gate NO puede comprobar si lleva un "
                f"`sitecustomize.py`. Un path que no se puede inspeccionar no "
                f"se puede certificar."
            )
            continue
        directorio = REPO / entrada
        for arranque in FICHEROS_DE_ARRANQUE:
            if (directorio / arranque).exists():
                errores.append(
                    f"ARRANQUE OCULTO: `PYTHONPATH` en {donde} incluye "
                    f"`{entrada}`, que contiene `{arranque}`. Python lo importa "
                    f"solo por estar en el path, y ahi dentro un "
                    f"`os.environ.setdefault('PYTEST_ADDOPTS', ...)` apaga la "
                    f"suite sin que ninguna variable prohibida aparezca en "
                    f"`ci.yml`. Es el truco del propio calibrador, del reves."
                )
    return errores


def _revisa_env(env: dict, donde: str) -> list[str]:
    """SUP-1..SUP-5: un mapa `env:` de YAML, venga del nivel que venga."""
    errores = []
    for clave, valor in (env or {}).items():
        nombre = str(clave).strip().upper()
        if nombre in VARIABLES_QUE_FILTRAN:
            errores.append(
                f"FILTRO DE EXCLUSION POR ENTORNO: `{clave}` definida en "
                f"{donde}. Inyecta opciones de pytest SIN tocar la linea de "
                f"comandos, asi que la prohibicion de `--ignore`/`-k` sobre "
                f"los argumentos no la ve. Medido: con ella puesta, "
                f"`pytest viewer/tests/` recolecta 0 tests de una suite que "
                f"tenia 22, y la invocacion por directorio no lo delata."
            )
        elif nombre in VARIABLES_CON_POLITICA_DE_VALOR:
            errores.extend(_politica_de_pythonpath(valor, donde))
    return errores




# G2: `container.env` y `services.<id>.env` estaban enumerados y `options` no.
# `options` es el paso-through DOCUMENTADO a `docker create`, asi que `-e VAR=v`
# ahi dentro inyecta entorno en TODOS los pasos del job sin tocar ningun `env:`.
# Medido por un revisor independiente: EXIT=0.
RE_OPCION_ENV_DOCKER = re.compile(
    r"(?:^|\s)(?:-e|--env)(?:=|\s+)\"?'?([A-Za-z_][A-Za-z0-9_]*)")


def _revisa_options(opciones, donde: str) -> list[str]:
    """G2: `-e VAR=valor` dentro de `options:` de un container o un service."""
    if not isinstance(opciones, str):
        return []
    errores = []
    for m in RE_OPCION_ENV_DOCKER.finditer(opciones):
        nombre = m.group(1).upper()
        if nombre in VARIABLES_QUE_FILTRAN:
            errores.append(
                f"FILTRO DE EXCLUSION POR ENTORNO: `{nombre}` llega por "
                f"`-e`/`--env` dentro de `options:` en {donde}. `options` es el "
                f"paso-through a `docker create`, asi que el entorno lo heredan "
                f"TODOS los pasos del job sin que aparezca en ningun `env:`."
            )
        elif nombre in VARIABLES_CON_POLITICA_DE_VALOR:
            errores.append(
                f"PYTHONPATH NO INSPECCIONABLE: llega por `-e`/`--env` dentro de "
                f"`options:` en {donde}. Ahi el gate no puede comprobar sus "
                f"entradas; declara `PYTHONPATH` en un `env:` normal."
            )
    return errores


def _revisa_run(cuerpo: str, donde: str) -> list[str]:
    """SUP-6/7/8: lo que ocurre DENTRO de un bloque `run:`."""
    errores = []
    for linea in cuerpo.splitlines():
        if linea.lstrip().startswith("#"):
            continue
        # G1: la linea se lee VARIAS veces, normalizando lo que el shell
        # COLAPSA al construir una palabra. Leerla sin comillas rejunta
        # `PYTEST_ADD""OPTS`; quitar ademas `%s`, `$(...)`, `${VAR}` y `$VAR`
        # rejunta `PYTEST_ADD%sOPTS`, `PYTEST_ADD$(echo)OPTS` y compania. Basta
        # que UNA normalizacion revele un nombre prohibido.
        vistas = [linea]
        sin_comillas = RE_COMILLAS.sub("", linea)
        sin_sustituciones = RE_SUSTITUCION.sub("", sin_comillas)
        for variante in (sin_comillas, sin_sustituciones):
            if variante not in vistas:
                vistas.append(variante)
        nombres = {m.group(1) for v in vistas for m in RE_ASIGNA_ENTORNO.finditer(v)}
        for m in RE_ASIGNA_ENTORNO.finditer(linea):
            nombre = m.group(1)
            if nombre in VARIABLES_QUE_FILTRAN:
                errores.append(
                    f"FILTRO DE EXCLUSION POR ENTORNO: `{nombre}` se asigna "
                    f"dentro del `run:` de {donde}. Es el mismo apagado que por "
                    f"`env:`, una capa mas abajo. Cuenta en CUALQUIER posicion "
                    f"de la linea: como prefijo, tras `export`, tras `env`, y "
                    f"dentro de `out=\"$(...)\"`, que es como este repo envuelve "
                    f"TODAS sus invocaciones. Si va a `$GITHUB_ENV`, ademas la "
                    f"hereda el paso siguiente."
                )
            elif nombre in VARIABLES_CON_POLITICA_DE_VALOR:
                resto = linea[m.end():].split()
                if resto:
                    errores.extend(_politica_de_pythonpath(resto[0], donde))
        # Nombres que solo aparecen al quitar las comillas: es G1.
        for nombre in sorted(nombres - {m.group(1) for m in RE_ASIGNA_ENTORNO.finditer(linea)}):
            if nombre in VARIABLES_QUE_FILTRAN:
                errores.append(
                    f"NOMBRE CONCATENADO (G1) en {donde}: `{linea.strip()[:90]}`. "
                    f"Normalizando lo que el shell colapsa —comillas vacias, "
                    f"`%s`, `$(...)`, `${{VAR}}`— la linea asigna `{nombre}`, que "
                    f"esta prohibida. El shell junta `PYTEST_ADD\"\"OPTS` en un "
                    f"solo nombre antes de ejecutar nada; partirlo en trozos no lo "
                    f"convierte en otra variable."
                )

        # Nombre CONSTRUIDO con expansiones en cualquier asignacion del `run:`,
        # no solo hacia `$GITHUB_ENV`: `${A}${B}=v` no lo puede resolver ningun
        # reconocedor de nombres literales, asi que se prohibe la FORMA.
        for m in RE_ASIGNA_NOMBRE_CONSTRUIDO.finditer(linea):
            if "$" in m.group(1):
                errores.append(
                    f"NOMBRE DE VARIABLE CONSTRUIDO en {donde}: "
                    f"`{linea.strip()[:90]}`. El nombre se arma con expansiones "
                    f"(`{m.group(1)}`), asi que NINGUN control sobre nombres puede "
                    f"decidir si es una de las prohibidas. Escribe el nombre "
                    f"literal y este gate lo comprobara."
                )
                break

        if RE_GITHUB_ENV.search(linea):
            # SUP-8, en lista blanca (G1): la UNICA forma de escribir en
            # `$GITHUB_ENV` que este gate puede verificar es un `echo` con el
            # nombre LITERAL y un valor sin expansiones. Todo lo demas —nombre
            # partido en comillas, `$N`, `printf` con `%s`, heredoc, `cat`, y
            # cualquier TUBERIA a `tee -a`— es rojo por la FORMA, sin intentar
            # adivinar que emite. La condicion ya no es "hay un `>>`" sino "se
            # menciona el fichero": `tee -a` escribe igual y no lleva `>>`.
            if not RE_ECHO_LITERAL_A_GITHUB_ENV.match(linea.strip()):
                errores.append(
                    f"ESCRITURA NO VERIFICABLE A `$GITHUB_ENV` en {donde}: "
                    f"`{linea.strip()[:90]}`. Lo que acabe en el entorno del paso "
                    f"SIGUIENTE tiene que poder leerse aqui. Solo se admite "
                    f"`echo \"NOMBRE=valor\" >> \"$GITHUB_ENV\"` con el nombre "
                    f"literal y un valor sin `$`, comillas, backtick, `%` ni "
                    f"barra invertida; cualquier otra forma de escribir en ese "
                    f"fichero —`tee -a`, `printf`, heredoc, `cat`— tambien cuenta. "
                    f"Enumerar las formas MALAS de construir un nombre no acaba "
                    f"nunca —se probo con `$`, se esquivo con comillas; se cerro "
                    f"la redireccion, se esquivo con una tuberia—, asi que se "
                    f"admite solo la buena. Hoy `ci.yml` no escribe en "
                    f"`$GITHUB_ENV` ni una vez, asi que esto es fail-closed sin "
                    f"coste."
                )
    return errores


def comprueba_addopts_por_entorno(datos: dict) -> list[str]:
    """Ninguna variable de entorno puede inyectar opciones de pytest.

    Recorre las NUEVE superficies enumeradas arriba, no las que se recuerden:
    la que se olvide es por donde entra. Cada una tiene su caso de calibracion
    con ancla propia, para que ninguna se apoye en el rojo de otra.
    """
    errores = list(_revisa_env(_env_de(datos),
                               "el `env:` del WORKFLOW (SUP-1, afecta a TODOS "
                               "los jobs)"))

    if isinstance(datos.get("defaults"), dict) and "env" in datos["defaults"]:
        errores.append(
            "ALCANCE ROTO: ha aparecido un `env:` bajo `defaults:`. GitHub no "
            "lo admitia cuando se escribio esta politica, asi que no se parsea "
            "como superficie. O deja de estar ahi, o hay que anadir su "
            "superficie y su caso de calibracion."
        )

    for job_id, job in (datos.get("jobs") or {}).items():
        job = job or {}
        errores += _revisa_env(_env_de(job), f"el `env:` del job `{job_id}` (SUP-2)")
        contenedor = job.get("container")
        if isinstance(contenedor, dict):
            errores += _revisa_env(_env_de(contenedor),
                                   f"el `container.env` del job `{job_id}` (SUP-4)")
            errores += _revisa_options(
                contenedor.get("options"),
                f"`container.options` del job `{job_id}` (SUP-10)")
        elif isinstance(contenedor, str):
            pass  # `container: imagen` a secas no trae entorno
        for sid, servicio in (job.get("services") or {}).items():
            if isinstance(servicio, dict):
                errores += _revisa_env(
                    _env_de(servicio),
                    f"el `services.{sid}.env` del job `{job_id}` (SUP-5)")
                errores += _revisa_options(
                    servicio.get("options"),
                    f"`services.{sid}.options` del job `{job_id}` (SUP-10)")

        # G3: la prohibicion de `uses: ./...` estaba SOLO en el paso. A nivel de
        # JOB, un workflow reutilizable local trae su propio `env:` y sus
        # propios `jobs:`, que este gate tampoco parsea. El agujero era el mismo
        # un nivel mas arriba.
        usa_job = job.get("uses")
        if isinstance(usa_job, str):
            errores.append(
                f"FUERA DE ALCANCE DECLARADO (SUP-11): el job `{job_id}` delega "
                f"en el workflow `{usa_job}`, que trae su propio `env:` y sus "
                f"propios pasos, y este gate NO los parsea. Mientras no sepa "
                f"mirarlos, delegar un job esta prohibido: la misma razon por la "
                f"que lo esta `uses: ./...` en un paso."
            )
        if isinstance(job.get("defaults"), dict) and "env" in job["defaults"]:
            errores.append(
                f"ALCANCE ROTO: `env:` bajo `defaults:` del job `{job_id}`; "
                f"ver la nota de alcance de esta politica."
            )
        for paso in job.get("steps") or []:
            if not isinstance(paso, dict):
                continue
            nombre_paso = str(paso.get("name") or "(sin nombre)")
            donde = f"`{job_id}` / `{nombre_paso}`"
            errores += _revisa_env(_env_de(paso), f"el `env:` del paso {donde} (SUP-3)")
            usa = paso.get("uses")
            if isinstance(usa, str) and usa.strip().startswith("./"):
                errores.append(
                    f"FUERA DE ALCANCE DECLARADO: el paso {donde} usa la accion "
                    f"local `{usa}`, que trae su propio `env:` y este gate NO "
                    f"parsea. Mientras no lo parsee, usarla esta prohibido: una "
                    f"exencion que hoy no hace falta es la rendija de manana."
                )
            cuerpo = paso.get("run")
            if isinstance(cuerpo, str):
                errores += _revisa_run(cuerpo, f"{donde} (SUP-6/7/8)")
    return errores


def comprueba_arranque_oculto() -> list[str]:
    """SUP-9: ningun `sitecustomize.py`/`usercustomize.py` en el repositorio.

    No depende de `PYTHONPATH`: el directorio de trabajo y cualquier entrada
    del path los importan solos. Se pregunta a git con `--cached --others
    --exclude-standard`, no al arbol crudo: cuenta lo versionado Y lo no
    versionado que SI se subiria, y no cuenta lo que `.gitignore` descarta
    (cache, artefactos, entornos). Un fichero recien creado y sin `git add`
    tambien apaga la suite, asi que tambien cuenta.
    """
    p = _git("ls-files", "-z", "--cached", "--others", "--exclude-standard",
             "*sitecustomize.py", "*usercustomize.py")
    if p.returncode != 0:
        return ["ARRANQUE OCULTO: no se pudo preguntar a git por los ficheros "
                "de arranque; sin esa respuesta el control no puede afirmar "
                "nada."]
    errores = []
    for ruta in [r for r in p.stdout.split("\0") if r.strip()]:
        errores.append(
            f"ARRANQUE OCULTO: el repositorio versiona `{ruta}`. Python lo "
            f"importa por el mero hecho de estar en el path, y dentro cabe un "
            f"`os.environ.setdefault('PYTEST_ADDOPTS', ...)` que apaga la suite "
            f"sin que ninguna variable prohibida asome en `ci.yml`."
        )
    return errores


def comprueba_filtros_de_exclusion(invocaciones: list[dict],
                                   raices: list[Path]) -> list[str]:
    """Ningun job vigilado puede EXCLUIR parte de lo que recorre."""
    protegidas = {r.relative_to(REPO).as_posix() for r in raices}
    errores = []
    for inv in invocaciones:
        base = REPO / inv["cwd"]
        suyas = set()
        for r in inv["raices"]:
            ruta = (base / r.split("::")[0]).resolve()
            try:
                rel = ruta.relative_to(REPO).as_posix()
            except ValueError:
                continue
            if any(rel == p or rel.startswith(p + "/") for p in protegidas):
                suyas.add(rel)
        if not suyas:
            continue
        for bandera in inv.get("banderas", ()):
            nombre = bandera.split("=", 1)[0]
            if nombre in BANDERAS_QUE_EXCLUYEN:
                errores.append(
                    f"FILTRO DE EXCLUSION: el job `{inv['job']}`, paso "
                    f"`{inv['paso']}`, invoca pytest con `{bandera}` sobre "
                    f"{sorted(suyas)}. Esa bandera APAGA parte de la suite sin "
                    f"tocar ni un fichero de test, y el inventario no la ve: "
                    f"mide lo que el job RECORRE, no lo que EXCLUYE. Un job "
                    f"requerido ejecuta todo lo que recorre; si de verdad sobra "
                    f"algo, quitalo de las rutas, que se ve en el diff."
                )
    return errores


def raices_invocadas() -> list[Path]:
    """Union de las raices que CUALQUIER job invoca, en rutas del repo."""
    vistas: dict[str, None] = {}
    for inv in derivar_invocaciones():
        base = REPO / inv["cwd"]
        for r in inv["raices"]:
            p = (base / r.split("::")[0]).resolve()
            try:
                vistas.setdefault(p.relative_to(REPO).as_posix(), None)
            except ValueError:
                continue
    # Se quitan las raices contenidas en otra: `viewer/tests/browser` dentro de
    # `viewer/tests` no aporta nada y duplicaria modulos.
    todas = sorted(vistas)
    return [REPO / r for r in todas
            if not any(r != otra and r.startswith(otra + "/") for otra in todas)]


# --------------------------------------------------------------------------
# F2: la coleccion real
# --------------------------------------------------------------------------

def inventario_recolectado(raices: list[Path]) -> tuple[dict[str, int], str]:
    """modulo -> nº de tests que pytest dice haber recolectado.

    `-p no:cacheprovider` y `PYTHONDONTWRITEBYTECODE=1` para no dejar rastro en
    el arbol: un arnes que escribe el arbol que mide contamina la medida.
    """
    entorno = dict(os.environ)
    entorno["PYTHONDONTWRITEBYTECODE"] = "1"
    entorno.setdefault("S9K_ALLOW_REAL_INGEST", "")
    argumentos = [sys.executable, "-m", "pytest", "--collect-only", "-q",
                  "-p", "no:cacheprovider", "--no-header"]
    argumentos += [r.relative_to(REPO).as_posix() for r in raices]
    p = subprocess.run(argumentos, cwd=REPO, capture_output=True, text=True,
                       env=entorno, timeout=1800)
    conteo: dict[str, int] = {}
    for linea in p.stdout.splitlines():
        linea = linea.strip()
        if "::" not in linea or linea.startswith(("ERROR", "E ", "<")):
            continue
        modulo = linea.split("::", 1)[0]
        if modulo.endswith(".py"):
            conteo[modulo] = conteo.get(modulo, 0) + 1
    return conteo, p.stdout + p.stderr


def declara_tests(texto: str) -> bool:
    """¿El modulo DEFINE algun test, o es un modulo de fixtures?

    Se decide por AST, no por el nombre: en este repositorio hay ficheros
    `test_*_fixtures.py` que a proposito no contienen ni un test (son las
    fuentes de prueba, generadas en codigo). Exigirles coleccion seria un rojo
    falso, y un rojo falso ensena a desconfiar del instrumento.

    Que un modulo se vacie de tests NO queda impune por esto: el trinquete C
    ve desaparecer sus casos del inventario de la base.
    """
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return True  # que no parsee ya es un fallo; lo reporta `silenciado()`
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and nodo.name.startswith("test_"):
            return True
        if isinstance(nodo, ast.ClassDef) and nodo.name.startswith("Test"):
            return True
    return False


def modulos_en_disco(raices: list[Path]) -> set[str]:
    """Ficheros `test_*.py` que EXISTEN bajo las raices invocadas."""
    encontrados = set()
    for raiz in raices:
        if raiz.is_file():
            if raiz.name.startswith("test_"):
                encontrados.add(raiz.relative_to(REPO).as_posix())
            continue
        for py in raiz.rglob("test_*.py"):
            if any(p in ("__pycache__", ".venv", "node_modules") for p in py.parts):
                continue
            encontrados.add(py.relative_to(REPO).as_posix())
    return encontrados


# --------------------------------------------------------------------------
# A: silenciado a nivel de modulo, por AST
# --------------------------------------------------------------------------

# `xfail` entra aqui por un superviviente MEDIDO, no por simetria. Diferencial
# con un defecto inyectado de verdad en una suite critica:
#
#   el defecto SIN xfail   -> 1 failed, 21 passed      EXIT=1  (CI ROJO)
#   el MISMO CON xfail     -> 1 xfailed, 21 xpassed    EXIT=0  (CI VERDE)
#
# Y las DOS capas de este carril salian verdes: el reconocedor porque
# `silenciado()` solo modelaba `skip`/`skipif` —`tests_en_pie` seguia contando
# la prueba y `apagados_por_decorador` salia vacio—, y la capa de ejecucion real
# porque el informe JUnit trae las 22 `<testcase>` con `xfail` puesto, asi que
# `reportadas != 0`. Una suite critica que YA NO PUEDE FALLAR, con todos los
# instrumentos en verde.
#
# `xfail` es peor que `skip`, no igual: `skip` dice en voz alta que no se
# ejecuta; `xfail` FINGE ejecucion y ademas se traga el fallo. Y no es
# rebuscado: `xfail(reason="infra inestable")` es exactamente lo que alguien
# escribe un viernes para acallar un test que molesta.
MARCAS_QUE_APAGAN = ("skip", "skipif", "xfail")


def _menciona_skip(nodo: ast.AST) -> bool:
    for hijo in ast.walk(nodo):
        if isinstance(hijo, ast.Attribute) and hijo.attr in MARCAS_QUE_APAGAN:
            return True
        if isinstance(hijo, ast.Name) and hijo.id in MARCAS_QUE_APAGAN:
            return True
        if isinstance(hijo, ast.Constant) and isinstance(hijo.value, str) \
                and hijo.value in MARCAS_QUE_APAGAN:
            return True
    return False


INCONDICIONAL, CONDICIONAL = "INCONDICIONAL", "CONDICIONAL"


def _condicion_constante_verdadera(nodo: ast.AST) -> bool:
    """`skipif(True, ...)` es un `skip` disfrazado; `skipif(not URI, ...)` no."""
    if isinstance(nodo, ast.Call) and nodo.args:
        prim = nodo.args[0]
        return isinstance(prim, ast.Constant) and bool(prim.value)
    return False


def _tiene_condicion_real(nodo: ast.AST) -> bool:
    """Un `xfail` con condicion POSICIONAL real es condicional; uno pelado no.

    `pytest.mark.xfail`, `xfail(reason=...)` y `xfail(strict=True)` apagan
    SIEMPRE. `xfail(sys.platform == "win32", reason=...)` solo a veces, y eso
    lo gobierna el trinquete A2 igual que un `skipif`.
    """
    if not isinstance(nodo, ast.Call):
        return False  # `pytest.mark.xfail` pelado
    return bool(nodo.args) and not _condicion_constante_verdadera(nodo)


def silenciado(texto: str) -> tuple[str, str] | None:
    """(clase, motivo) del apagado del modulo ENTERO, o None.

    Se lee el AST, no el texto: `pytestmark = pytest.mark.skip`,
    `pytestmark = [pytest.mark.skip]`, `pytestmark = pytest.mark.skipif(True, ...)`
    y `pytest.skip(..., allow_module_level=True)` son la misma cosa escrita de
    cuatro maneras, y un grep vigilaria una sola.

    La clase importa y no es un matiz:

      INCONDICIONAL -> el modulo NO se ejecuta en ningun sitio, nunca. Es
        exactamente la mutacion del revisor adversarial. ROJO SIEMPRE, sin
        base de comparacion y sin excepciones.

      CONDICIONAL -> `skipif` sobre una condicion real (`not NEO4J_TEST_URI`,
        una herramienta ausente). En este repositorio hay siete asi y son
        legitimos: son suites que un job concreto habilita con su entorno.
        NO se pueden prohibir de plano sin poner el gate rojo por cumplir su
        propia regla. Lo que SI se prohibe es que aparezca uno NUEVO: el
        conjunto de modulos silenciados es un trinquete contra la base
        (control A2). Convertir uno de los tres ficheros del ejercicio RC en
        `skipif(not os.environ.get("LO_QUE_SEA"))` se pone rojo por ahi.
    """
    try:
        arbol = ast.parse(texto)
    except SyntaxError as e:
        return INCONDICIONAL, f"el modulo no parsea ({e.msg}): no ejecuta nada"
    for nodo in arbol.body:
        if isinstance(nodo, (ast.Assign, ast.AnnAssign)):
            destinos = nodo.targets if isinstance(nodo, ast.Assign) else [nodo.target]
            nombres = {d.id for d in destinos if isinstance(d, ast.Name)}
            if "pytestmark" not in nombres or nodo.value is None:
                continue
            if not _menciona_skip(nodo.value):
                continue
            candidatos = list(nodo.value.elts) if isinstance(nodo.value, (ast.List, ast.Tuple)) \
                else [nodo.value]
            for c in candidatos:
                if not _menciona_skip(c):
                    continue
                # `pytest.mark.skip` (con o sin llamada) es incondicional.
                nucleo = c.func if isinstance(c, ast.Call) else c
                nombre_marca = nucleo.attr if isinstance(nucleo, ast.Attribute) else ""
                if nombre_marca == "skip":
                    return INCONDICIONAL, "`pytestmark = pytest.mark.skip` a nivel de modulo"
                if nombre_marca == "xfail" and not _tiene_condicion_real(c):
                    return (INCONDICIONAL,
                            "`pytestmark = pytest.mark.xfail` a nivel de modulo: la "
                            "suite ya no puede fallar. Medido: el mismo defecto da "
                            "`1 failed` (EXIT=1) sin la marca y `1 xfailed, 21 "
                            "xpassed` (EXIT=0) con ella")
                if nombre_marca in ("skipif", "xfail") and _condicion_constante_verdadera(c):
                    return (INCONDICIONAL,
                            f"`pytestmark = pytest.mark.{nombre_marca}(<constante "
                            f"verdadera>)`, que es un apagado disfrazado de condicional")
                return CONDICIONAL, f"`pytestmark` a nivel de modulo con `{nombre_marca or 'skipif'}`"
        if isinstance(nodo, ast.Expr) and isinstance(nodo.value, ast.Call):
            llamada = nodo.value
            fn = llamada.func
            es_skip = (isinstance(fn, ast.Attribute) and fn.attr == "skip") or \
                      (isinstance(fn, ast.Name) and fn.id == "skip")
            if es_skip and any(k.arg == "allow_module_level" for k in llamada.keywords):
                return INCONDICIONAL, "`pytest.skip(..., allow_module_level=True)`"
    return None


def condicion_de_silencio(texto: str) -> str:
    """El TEXTO de la condicion del `skipif` de modulo, normalizado por AST.

    A2 hace trinquete sobre la PERTENENCIA al conjunto de silenciados, y eso
    dejaba una rendija medida: a un modulo ya silenciado se le puede reescribir
    la condicion —de `not NEO4J_TEST_URI` a `not S9K_LO_QUE_SEA`, que nadie
    define nunca— sin entrar ni salir del conjunto, asi que nada enrojecia.
    Se guarda la condicion desparseada con `ast.unparse`, no el texto crudo:
    reformatear no es cambiar, y cambiar tiene que doler.
    """
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return ""
    for nodo in arbol.body:
        if not isinstance(nodo, ast.Assign):
            continue
        if not any(isinstance(d, ast.Name) and d.id == "pytestmark" for d in nodo.targets):
            continue
        candidatos = list(nodo.value.elts) if isinstance(nodo.value, (ast.List, ast.Tuple)) \
            else [nodo.value]
        for c in candidatos:
            if isinstance(c, ast.Call) and _nucleo_marca(c) == "skipif" and c.args:
                try:
                    return ast.unparse(c.args[0])
                except Exception:
                    return "<no desparseable>"
    return ""


def _nucleo_marca(nodo: ast.AST) -> str:
    """Nombre de la marca de pytest, este llamada o no: `mark.skip` -> "skip"."""
    nucleo = nodo.func if isinstance(nodo, ast.Call) else nodo
    return nucleo.attr if isinstance(nucleo, ast.Attribute) else ""


def _es_test(nodo: ast.AST) -> bool:
    if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return nodo.name.startswith("test_")
    if isinstance(nodo, ast.ClassDef):
        return nodo.name.startswith("Test")
    return False


def apagados_por_decorador(texto: str) -> list[tuple[str, str]]:
    """(nombre, motivo) de cada test apagado INCONDICIONALMENTE por decorador.

    ESTE CONTROL EXISTE POR UN SUPERVIVIENTE MEDIDO. La primera version de este
    gate solo miraba `pytestmark` a NIVEL DE MODULO. Un revisor decoro las 20
    funciones y clases de `test_parcialidad_declarada.py` con
    `@pytest.mark.skip` —el ataque original escrito en otra sintaxis— y el gate
    salio VERDE con 0 errores: baseline `22 passed` -> `0 ejecutados`.

    Y el trinquete de recuento TAMPOCO lo veia, y la razon importa: un test
    decorado con `skip` SIGUE RECOLECTANDOSE. Comprobado, no supuesto. Por eso
    contar lo recolectado nunca puede ser la garantia: hay que contar lo que
    QUEDA EN PIE.

    No hay indulto para los existentes porque no hay existentes: hoy el arbol
    tiene CERO decoradores `skip` incondicionales (11 `skipif`, todos con
    condicion real). Un gate que nace sin excepciones no las adquiere solo.
    """
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return []
    hallazgos = []
    for nodo in ast.walk(arbol):
        if not _es_test(nodo):
            continue
        for dec in nodo.decorator_list:
            marca = _nucleo_marca(dec)
            if marca == "skip":
                hallazgos.append((nodo.name, "@pytest.mark.skip"))
            elif marca == "skipif" and _condicion_constante_verdadera(dec):
                hallazgos.append((nodo.name, "@pytest.mark.skipif(<constante verdadera>)"))
    return hallazgos


def xfail_por_decorador(texto: str) -> list[tuple[str, str]]:
    """(nombre, motivo) de cada test que no puede fallar por `@xfail`.

    VA APARTE DE `apagados_por_decorador` Y NO ES ORDEN: es que la evidencia es
    distinta. Aquel control nacio SIN excepciones porque el arbol tenia CERO
    decoradores `skip` incondicionales. Con `xfail` no se puede decir lo mismo:
    HAY 13 hoy, en 5 modulos, medidos con este mismo codigo. Prohibirlos de
    plano pondria el CI en rojo por codigo legitimo que ademas es de otros
    carriles, y un gate que grita sin motivo acaba desactivado.

    Asi que se trata como el gate ya trata los `skipif` de modulo, que tambien
    tienen siete casos legitimos:

      * en un modulo CRITICO -> ROJO SIEMPRE, con condicion o sin ella. Hoy
        hay CERO, asi que la prohibicion nace sin excepciones. Es donde vive el
        ataque: apagar la suite que sujeta la garantia.
      * en el resto -> TRINQUETE. `tests_en_pie` los descuenta TODOS, asi que un
        `xfail` NUEVO baja esa medida y el trinquete D2 —ya calibrado— se pone
        rojo. La defensa sale de un control que ya existia, no de uno nuevo sin
        calibrar.

    NINGUNA EXENCION POR CONDICION. `xfail` no es `skipif` y no hereda su regla:
    `skipif` con condicion DECLARA que no se ejecuta; `xfail` condicional finge
    ejecucion y se traga el fallo, y su condicion es indecidible en AST
    (`pytest.__version__ != ""` es cierta siempre).

    A nivel de MODULO no hay matiz y por eso no esta aqui: `silenciado()` lo
    trata como INCONDICIONAL y hoy el arbol tiene CERO, asi que ahi la
    prohibicion es total y sin coste.

    LOS DELEGADOS: 7 de los 13 estan en modulos que el inventario cuenta en
    `en_pie` —esos los sujeta D2— y 6 en modulos DELEGADOS, que no entran en
    `en_pie` porque su trinquete es de PRESENCIA. La ronda anterior dijo que
    "los cubre el job que los ejecuta, que ya falla si ve `skipped`" y ESO ERA
    FALSO: pytest no imprime `skipped` para un `xfail`, imprime `xfailed`, asi
    que aquel `grep` no lo veia. Comprobado con un `xfail` pelado en
    `test_browser_navigation.py`: gate EXIT=0, sin `en_pie` que lo descuente,
    sin A5 (no es critico) y sin que el `grep` lo delatara. Corregido donde
    tocaba: el job del navegador ahora tambien busca `xfailed`. Ahi vive el
    contrato del navegador —escribir = 0 POST, Enter = 1 POST—, que es
    propiedad declarada del RC.
    """
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return []

    # ALIAS de modulo: `XF_TABLA = pytest.mark.xfail(...)` y luego
    # `pytest.param(..., marks=XF_TABLA)`. Sin esto el censo se queda corto y el
    # trinquete deja pasar `xfail` nuevos por la puerta de al lado. Medido en
    # CI: el arnes de navegador declara 6 decoradores `@pytest.mark.xfail` que
    # el AST veia, y la corrida real dio `12 xfailed` -los que faltaban
    # llegaban por alias dentro de `parametrize`-.
    alias_xfail = set()
    for nodo in arbol.body:
        if not isinstance(nodo, ast.Assign) or len(nodo.targets) != 1:
            continue
        destino = nodo.targets[0]
        if isinstance(destino, ast.Name) and _nucleo_marca(nodo.value) == "xfail":
            alias_xfail.add(destino.id)

    def _es_xfail(nodo_marca) -> bool:
        if _nucleo_marca(nodo_marca) == "xfail":
            return True
        base = nodo_marca.func if isinstance(nodo_marca, ast.Call) else nodo_marca
        return isinstance(base, ast.Name) and base.id in alias_xfail

    hallazgos = []
    # `pytest.param(..., marks=...)` DENTRO de un `parametrize`: la marca no
    # decora la funcion, viaja en el caso. Se cuenta una vez por cada `param`
    # marcado, que es lo que pytest ejecuta como prueba `xfail`.
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        base = nodo.func
        nombre = base.attr if isinstance(base, ast.Attribute) else \
            (base.id if isinstance(base, ast.Name) else "")
        if nombre != "param":
            continue
        for kw in nodo.keywords:
            if kw.arg != "marks":
                continue
            marcas = kw.value.elts if isinstance(kw.value, (ast.List, ast.Tuple)) \
                else [kw.value]
            for marca in marcas:
                if _es_xfail(marca):
                    hallazgos.append((
                        f"<param en linea {getattr(nodo, 'lineno', 0)}>",
                        "`pytest.param(..., marks=xfail)`: la marca viaja en el "
                        "caso, no en el decorador, y el censo por decorador no "
                        "la veia"))

    for nodo in ast.walk(arbol):
        if not _es_test(nodo):
            continue
        for dec in nodo.decorator_list:
            if not _es_xfail(dec):
                continue
            # SIN EXENCION POR CONDICION, y esto es la correccion del quinto
            # dictamen. La version anterior eximia el decorador con condicion
            # posicional no literal, heredando la regla de `skipif`. Un revisor
            # la atraveso con la condicion mas tonta posible:
            #
            #   @pytest.mark.xfail(pytest.__version__ != '', reason='infra')
            #
            # cierta SIEMPRE, indecidible en AST, y con ella la suite critica
            # daba `1 xfailed, 21 xpassed` y EXIT=0 con el gate en 0 errores.
            # `sys.platform == 'linux'` hace lo mismo en CI.
            #
            # La herencia era el fallo: `skipif` con condicion es legitimo
            # porque DECLARA que no se ejecuta, y ademas su condicion de modulo
            # esta gobernada por el trinquete A2. `xfail` condicional FINGE
            # ejecucion, se traga el fallo, y a nivel de decorador no tenia
            # trinquete ninguno —precisamente porque la exencion impedia el
            # descuento que alimentaria a D2—.
            #
            # Contar TODOS devuelve la defensa a D2, que ya esta calibrado, para
            # todo el arbol y sin casuistica. Coste hoy: CERO. Medido antes de
            # tocar nada: los 13 `xfail` del arbol son PELADOS, no hay ni uno
            # condicional, asi que la base no se mueve y no enrojece nada
            # legitimo.
            condicion = ""
            if isinstance(dec, ast.Call) and dec.args:
                try:
                    condicion = f" con condicion `{ast.unparse(dec.args[0])[:60]}`"
                except Exception:  # pragma: no cover
                    condicion = " con condicion"
            hallazgos.append((nodo.name,
                              f"@pytest.mark.xfail{condicion}: la prueba ya no "
                              f"puede fallar, y ademas finge ejecucion"))
    return hallazgos


def decoradores_no_verificables(texto: str) -> list[tuple[str, str]]:
    """(test, decorador) que NO resuelve a una marca literal de pytest.

    POLARIDAD INVERTIDA, y por la misma razon que en `$GITHUB_ENV`: enumerar
    las formas MALAS de esconder un `xfail` no acaba nunca. Ya iban cuatro
    vueltas —decorador directo, `pytestmark`, alias de modulo,
    `pytest.param(marks=...)`— y el revisor entro con la quinta:

        def _marca_infra(motivo):
            return pytest.mark.xfail(reason=motivo)

        @_marca_infra('inestable')
        def test_...

    Gate EXIT=0. Y detras de esa hay un `dict` de marcas, un alias de alias, un
    `import` desde otro modulo, un decorador generado... El censo cubria bien
    las tres vias que enumeraba; el problema era que seguia siendo una
    enumeracion.

    Asi que en un modulo CRITICO se admite SOLO la forma verificable —un
    decorador `pytest.mark.<nombre>`, con o sin llamada— y cualquier otra cosa
    es roja POR LA FORMA, sin intentar adivinar a que resuelve. No hace falta
    saber si `_marca_infra` devuelve un `xfail`: basta con que este gate no
    pueda comprobarlo.

    COSTE MEDIDO ANTES DE ESCRIBIRLO, como siempre: en los 20 modulos criticos
    hay 57 decoradores y los 57 son `pytest.mark.parametrize`. Ni uno solo cae
    fuera de la forma admitida, asi que la regla nace sin excepciones y sin
    romper nada.

    SOLO en modulos criticos, a proposito: en el resto del arbol un decorador
    propio es una herramienta legitima y prohibirla seria un gate gritando ante
    trabajo normal. Alli la defensa es el trinquete —D2 y X-T—, que no necesita
    entender el decorador para ver que las pruebas en pie bajan.
    """
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return []
    hallazgos = []
    for nodo in ast.walk(arbol):
        if not _es_test(nodo):
            continue
        for dec in nodo.decorator_list:
            base = dec.func if isinstance(dec, ast.Call) else dec
            # Forma admitida: `pytest.mark.<nombre>` (Attribute sobre
            # Attribute `mark` sobre Name `pytest`).
            ok = (isinstance(base, ast.Attribute)
                  and isinstance(base.value, ast.Attribute)
                  and base.value.attr == "mark"
                  and isinstance(base.value.value, ast.Name)
                  and base.value.value.id == "pytest")
            if ok:
                continue
            try:
                escrito = ast.unparse(dec)
            except Exception:  # pragma: no cover
                escrito = "<no representable>"
            hallazgos.append((nodo.name, escrito[:70]))
    return hallazgos


def marca_inyectada_en_ejecucion() -> list[tuple[str, str]]:
    """(fichero, motivo) de cada fichero que MARCA pruebas EN EJECUCION.

    EL TERCER SUPERVIVIENTE DEL QUINTO DICTAMEN, y el unico que NINGUNA
    inspeccion del modulo puede ver: la marca no esta en el fichero de test.

        # conftest.py
        def pytest_collection_modifyitems(config, items):
            for it in items:
                it.add_marker(pytest.mark.xfail(reason="infra inestable"))

    Medido en un sandbox: con esas cuatro lineas, `1 xfailed, 1 xpassed` y
    EXIT=0 donde antes habia `1 failed` y EXIT=1. El AST del modulo sigue
    limpio, `tests_en_pie` no baja, D2 no se entera y A5 tampoco.

    Y la capa de ejecucion real solo lo ve A MEDIAS, lo que obliga a tener este
    control: medido sobre el informe JUnit, una prueba `xpassed` sale como un
    `<testcase>` PELADO, indistinguible de un aprobado normal; solo cuando la
    prueba llega a fallar aparece `<skipped type="pytest.xfail">`. O sea: la
    capa de ejecucion caza el fallo TRAGADO, pero no la marca puesta a la
    espera. Este control caza la marca antes de que haya ningun defecto.

    ALCANCE: TODO fichero `.py` del arbol vigilado, no solo `conftest.py`. La
    primera version solo miraba los `conftest` y un revisor entro por el propio
    modulo de test con un fixture `autouse` que hace
    `request.node.add_marker(...)`: gate EXIT=0, 0 errores, y el diferencial
    `1 failed, 21 passed` (EXIT=1) -> `1 xfailed, 21 xpassed` (EXIT=0). El
    `conftest` nunca fue la propiedad relevante; lo es MARCAR EN EJECUCION, y
    eso se hace desde cualquier fichero que pytest importe.

    Hoy el arbol tiene CERO ficheros con `add_marker`/`applymarker` de una marca
    de apagado (medido), asi que la prohibicion nace sin excepciones. Si alguna
    vez hace falta marcar en ejecucion, que sea una decision visible y
    discutida, no un renglon que nadie mira.
    """
    hallazgos = []
    vistos = set()
    for raiz in (REPO, *(REPO / r for r in ("viewer", "data-engine", "deploy",
                                            "tests", "contracts"))):
        if not raiz.exists():
            continue
        # TODO fichero .py del arbol vigilado, no solo `conftest.py`. La version
        # anterior solo miraba los `conftest`, y un revisor entro por el propio
        # MODULO con un fixture `autouse`:
        #
        #   @pytest.fixture(autouse=True)
        #   def _estabilidad(request):
        #       request.node.add_marker(pytest.mark.xfail(reason='infra'))
        #
        # Gate EXIT=0, 0 errores, y el diferencial `1 failed, 21 passed`
        # (EXIT=1) -> `1 xfailed, 21 xpassed` (EXIT=0). El `conftest` nunca fue
        # la propiedad relevante: lo es MARCAR EN EJECUCION, y eso se puede
        # hacer desde cualquier fichero que pytest importe.
        for cf in sorted(raiz.rglob("*.py")):
            # Las exclusiones se miran SOBRE LA RUTA RELATIVA AL REPO, jamas
            # sobre `cf.parts` absoluto. Escrito primero con `cf.parts` y
            # medido despues: en un worktree bajo `.claude/worktrees/...` TODOS
            # los ficheros llevan `.claude` en su ruta absoluta, asi que la
            # exclusion se tragaba el repositorio ENTERO y este control no
            # miraba ni un fichero —salia verde por no mirar—. Lo delato su
            # propio diferencial: S-D seguia en EXIT=0 con el control ya puesto.
            try:
                partes = cf.relative_to(REPO).parts
            except ValueError:
                continue
            if any(parte in ("__pycache__", ".git", ".claude", "node_modules",
                             ".venv", "venv") for parte in partes):
                continue
            rel = cf.resolve()
            if rel in vistos:
                continue
            vistos.add(rel)
            try:
                arbol = ast.parse(cf.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for nodo in ast.walk(arbol):
                if not isinstance(nodo, ast.Call):
                    continue
                fn = nodo.func
                if not isinstance(fn, ast.Attribute):
                    continue
                if fn.attr not in ("add_marker", "applymarker"):
                    continue
                texto_arg = " ".join(ast.unparse(a) for a in nodo.args) if nodo.args else ""
                for marca in MARCAS_QUE_APAGAN:
                    if marca in texto_arg:
                        hallazgos.append((
                            cf.relative_to(REPO).as_posix(),
                            f"`{fn.attr}(...)` con `{marca}`: marca pruebas EN "
                            f"EJECUCION, asi que la marca no esta en el codigo "
                            f"del test y ninguna inspeccion estatica del modulo "
                            f"la ve"))
                        break
    return hallazgos


def tests_en_pie(texto: str) -> int:
    """Cuantos tests DEFINE el modulo que no estan apagados sin condicion.

    Es una medida distinta de la coleccion —no expande `parametrize`— y esa es
    justo su virtud: la coleccion no cambia cuando alguien decora un test con
    `skip`, y esta si. Van las dos al inventario, y las dos con trinquete.
    """
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return 0
    # SOLO se descuentan los apagados POR DECORADOR. El silencio a nivel de
    # modulo NO se resta aqui, y es deliberado: si esta medida tambien cayera a
    # cero con un `pytestmark`, D2 estaria cazando lo mismo que A y la ablacion
    # de A no podria aislarse —lo dijo la propia calibracion, que salio ROJA
    # con A ablacionado—. Cada control tiene que sujetar algo que solo el
    # sujeta, o no se puede demostrar que sujete nada. El silencio de modulo lo
    # cubren A1 (siempre, sin base) y A2 (trinquete).
    # Tambien los `xfail`: una prueba que no puede fallar no esta EN PIE. Ese
    # descuento es lo que convierte el trinquete D2 en el guardian de los
    # `xfail` no criticos sin escribir un control nuevo.
    apagados = {n for n, _ in apagados_por_decorador(texto)}
    apagados |= {n for n, _ in xfail_por_decorador(texto)}
    return sum(1 for nodo in ast.walk(arbol) if _es_test(nodo) and nodo.name not in apagados)


# --------------------------------------------------------------------------
# F3/F4: quien declara un modulo CRITICO
# --------------------------------------------------------------------------

DIRECTORIOS_CALIBRADORES = ("scripts", "artifacts", ".github/scripts")


def _ficheros_calibradores() -> list[Path]:
    salida = []
    for d in DIRECTORIOS_CALIBRADORES:
        raiz = REPO / d
        if not raiz.exists():
            continue
        for py in raiz.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            nombre = py.name.lower()
            if "calibra" in nombre or "calibracion" in py.parts or "mutacion" in nombre:
                salida.append(py)
    return sorted(salida)


def criticos_por_calibrador() -> dict[str, list[str]]:
    """modulo de test -> calibradores que lo usan como INSTRUMENTO.

    AST sobre cada calibrador: toda constante de modulo cuyo valor sea una
    cadena que resuelva a un fichero de test existente. No es grep: una cadena
    dentro de un comentario o de un docstring no cuenta, y una cadena partida
    en una expresion tampoco puede colarse.
    """
    hallazgos: dict[str, list[str]] = {}
    bases = (REPO, REPO / "viewer", REPO / "data-engine")
    for cal in _ficheros_calibradores():
        try:
            arbol = ast.parse(cal.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for nodo in arbol.body:
            if not isinstance(nodo, ast.Assign) or not isinstance(nodo.value, ast.Constant):
                continue
            valor = nodo.value.value
            if not isinstance(valor, str) or not valor.endswith(".py"):
                continue
            for base in bases:
                destino = base / valor
                if destino.is_file() and destino.name.startswith("test_"):
                    rel = destino.resolve().relative_to(REPO).as_posix()
                    hallazgos.setdefault(rel, []).append(
                        cal.relative_to(REPO).as_posix())
                    break
    return hallazgos


def criticos_por_marcador(modulos: set[str]) -> list[str]:
    """`pytestmark = pytest.mark.critico` a nivel de modulo, leido por AST."""
    salida = []
    for rel in sorted(modulos):
        ruta = REPO / rel
        if not ruta.is_file():
            continue
        try:
            arbol = ast.parse(ruta.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for nodo in arbol.body:
            if not isinstance(nodo, ast.Assign):
                continue
            if not any(isinstance(d, ast.Name) and d.id == "pytestmark"
                       for d in nodo.targets):
                continue
            if any(isinstance(h, ast.Attribute) and h.attr == "critico"
                   for h in ast.walk(nodo.value)):
                salida.append(rel)
                break
    return salida


# --------------------------------------------------------------------------
# E: preflight de dependencias
# --------------------------------------------------------------------------

def dependencias_exigidas(modulos: set[str]) -> dict[str, list[str]]:
    """paquete -> modulos que se auto-omiten si falta.

    Se leen los argumentos REALES de `pytest.importorskip` por AST; la cadena
    `importorskip` es solo el cedazo previo para no parsear lo que no lo usa.
    """
    exigidas: dict[str, list[str]] = {}
    for rel in sorted(modulos):
        ruta = REPO / rel
        if not ruta.is_file():
            continue
        texto = ruta.read_text(encoding="utf-8", errors="replace")
        if "importorskip" not in texto:
            continue
        try:
            arbol = ast.parse(texto)
        except SyntaxError:
            continue
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute) \
                    and nodo.func.attr == "importorskip" and nodo.args:
                arg = nodo.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    exigidas.setdefault(arg.value, []).append(rel)
    return exigidas


def _importable(nombre: str) -> bool:
    try:
        return importlib.util.find_spec(nombre) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _es_del_repositorio(paquete: str) -> bool:
    """¿El paquete vive EN el repositorio? (p. ej. `arnes` -> benchmarks/perf).

    Un modulo local no se declara en un `requirements.txt`; exigirlo seria un
    rojo falso. Se comprueba que exista el fichero, no que suene local.
    """
    raiz = paquete.split(".")[0]
    for patron in (f"{raiz}.py", f"{raiz}/__init__.py"):
        for hallado in REPO.glob(f"**/{patron}"):
            if not any(p in ("__pycache__", ".venv", "node_modules", ".git")
                       for p in hallado.parts):
                return True
    return False


def _distribuciones(paquete: str) -> set[str]:
    """Nombres de distribucion que proveen ese modulo (`yaml` -> `PyYAML`).

    Se DERIVA de los metadatos del entorno (`packages_distributions()`), no de
    una tabla escrita a mano: una tabla se queda vieja y vuelve a ser el
    problema de las listas.
    """
    try:
        from importlib.metadata import packages_distributions
    except ImportError:  # pragma: no cover
        return set()
    mapa = packages_distributions()
    nombres = set(mapa.get(paquete.split(".")[0], []))
    nombres.add(paquete.split(".")[0])
    return nombres


def normaliza_distribucion(nombre: str) -> str:
    """PEP 503: `PyYAML`, `pyyaml` y `py_yaml` son el mismo nombre."""
    return re.sub(r"[-_.]+", "-", nombre).lower()


RE_NOMBRE_REQUISITO = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _nombres_de_requirements(texto: str) -> set[str]:
    nombres = set()
    for linea in texto.splitlines():
        linea = linea.split("#")[0].strip()
        if not linea or linea.startswith("-"):
            continue
        m = RE_NOMBRE_REQUISITO.match(linea)
        if m:
            nombres.add(normaliza_distribucion(m.group(1)))
    return nombres


def instalaciones_por_job() -> dict[str, set[str]]:
    """job -> nombres de distribucion que instala DE VERDAD.

    Se leen los argumentos de `pip install` y el contenido de cada `-r
    fichero`, y se quedan los NOMBRES normalizados (PEP 503). Antes esto era
    una busqueda de subcadena y era un agujero: `pip` aparecia en la linea
    `pip install`, asi que cualquier dependencia llamada `pip` se daba por
    declarada. Lo caza la calibracion, caso «dependencia usada y NO declarada».
    """
    datos = yaml.safe_load(CI.read_text(encoding="utf-8"))
    salida: dict[str, set[str]] = {}
    for job_id, job in (datos.get("jobs") or {}).items():
        nombres: set[str] = set()
        for paso in (job or {}).get("steps") or []:
            if not isinstance(paso, dict) or not isinstance(paso.get("run"), str):
                continue
            for linea in paso["run"].splitlines():
                if not RE_INSTALA.search(linea):
                    continue
                pos = linea.find("install")
                if pos < 0:
                    continue
                tokens = linea[pos + len("install"):].split()
                siguiente_es_fichero = False
                for bruto in tokens:
                    token = bruto.strip("\"'")
                    if siguiente_es_fichero:
                        siguiente_es_fichero = False
                        req = REPO / token
                        if req.is_file():
                            nombres |= _nombres_de_requirements(
                                req.read_text(encoding="utf-8", errors="replace"))
                        continue
                    if token in ("-r", "--requirement"):
                        siguiente_es_fichero = True
                        continue
                    if token.startswith("-") or not token:
                        continue
                    m = RE_NOMBRE_REQUISITO.match(token)
                    if m:
                        nombres.add(normaliza_distribucion(m.group(1)))
        salida[job_id] = nombres
    return salida


def _cci():
    """`check_ci_config` como modulo. Si no se puede importar, es fallo.

    La delegacion de Node/Chromium se apoya en el; sin el seria una exencion
    sin dueno, que es justo lo que este gate persigue.
    """
    import check_ci_config
    return check_ci_config


def modulos_delegados() -> tuple[set[str], list[str]]:
    """Ficheros cuyo skip ya vigila `check_ci_config`, y los fallos de esa vigilancia.

    Se DERIVA llamando al propio gate: `ficheros_con_skip_critico()` dice que
    ficheros dependen de una herramienta externa modelada alli, y
    `comprueba_skips_criticos()` exige que exista un job que la instale, los
    ejecute por nombre y falle si ve `skipped`. Si esa cobertura se rompe,
    aqui salen errores: delegar no es eximir.
    """
    try:
        cci = _cci()
    except Exception as e:  # pragma: no cover
        return set(), [f"no se puede importar check_ci_config ({e}); sin el, "
                       f"la delegacion de Node/Chromium seria una exencion sin dueno"]
    datos = yaml.safe_load(CI.read_text(encoding="utf-8"))
    fallos = [f"la delegacion en check_ci_config no cubre: {e}"
              for e in cci.comprueba_skips_criticos(datos, CI.name)]
    directos = set(cci.ficheros_con_skip_critico())

    # La delegacion se HEREDA por `conftest.py`, y esto no es un detalle: en
    # `viewer/tests/browser` solo `test_login_browser.py` nombra Playwright; los
    # otros cinco modulos lo reciben del `conftest.py` del directorio. Sin esta
    # herencia, esos cinco aparecian como DESAPARECIDOS en cualquier job sin
    # Playwright —lo detecto CI, no una suposicion— y el gate se ponia rojo por
    # una cobertura que SI existe: `test-login-browser` los ejecuta por nombre
    # de directorio y falla si ve `skipped`.
    #
    # Se DERIVA recorriendo los `conftest.py` que pytest aplicaria a cada
    # modulo, no con una lista de directorios.
    directorios = {Path(rel).parent.as_posix()
                   for rel in directos if Path(rel).name == "conftest.py"}
    heredados = set()
    for raiz in raices_invocadas():
        base = raiz if raiz.is_dir() else raiz.parent
        for py in base.rglob("test_*.py"):
            rel = py.relative_to(REPO).as_posix()
            padre = Path(rel).parent
            while True:
                if padre.as_posix() in directorios:
                    heredados.add(rel)
                    break
                if padre.as_posix() in (".", ""):
                    break
                padre = padre.parent
    return directos | heredados, fallos


# --------------------------------------------------------------------------
# F5: la base de comparacion
# --------------------------------------------------------------------------

def _git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                          text=True, timeout=180)


def inventario_base() -> tuple[dict[str, int] | None, str]:
    """Inventario del `merge-base` con `origin/main`, o None si no hay base.

    Se recupera el inventario publicado por la base. Si la base no lo tiene
    (rama anterior a este gate) el trinquete no puede aplicarse y se dice EN
    VOZ ALTA; no se inventa un cero, que dejaria pasar cualquier borrado.
    """
    base = _git("merge-base", "HEAD", "origin/main").stdout.strip()
    if not base:
        _git("fetch", "--no-tags", "origin", "main")
        base = _git("merge-base", "HEAD", "origin/main").stdout.strip()
    if not base:
        return None, "SIN TRINQUETE: no hay merge-base con origin/main"
    p = _git("show", f"{base}:.github/suite-inventario.json")
    if p.returncode != 0:
        # La base no publica inventario (rama anterior a este gate). ESPERAR
        # "al primer merge" seria una eleccion, no una necesidad: el arbol de
        # la base se puede MATERIALIZAR y medir aqui mismo. Sin esto, el primer
        # PR que introduce el gate corre sin trinquete, que es justo el PR en
        # el que mas falta hace.
        return inventario_materializando(base)
    try:
        datos = json.loads(p.stdout)
        if "modulos" not in datos:
            raise KeyError("modulos")
        return datos, f"base {base[:8]}"
    except (ValueError, KeyError) as e:
        return None, f"SIN TRINQUETE: inventario de la base ilegible ({e})"


def inventario_materializando(base: str) -> tuple[dict | None, str]:
    """Deriva el inventario del merge-base sacando su arbol a un temporal.

    `git archive <base> | tar -x` en un directorio de usar y tirar, y alli se
    ejecuta este mismo gate con `--escribir-inventario --sin-base`. La medida
    de la base sale del ARBOL de la base, no de lo que la base dijera de si
    misma, y no toca el arbol de trabajo ni por un instante.

    Si algo falla se devuelve None y el gate lo dice como AVISO; lo que NO
    puede pasar —y pasaba— es que el mensaje final afirme un trinquete que no
    se aplico.
    """
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="s9k-base-inventario-"))
    try:
        tar = subprocess.run(["git", "archive", "--format=tar", base],
                             cwd=REPO, capture_output=True, timeout=300)
        if tar.returncode != 0:
            return None, f"SIN TRINQUETE: no se pudo materializar {base[:8]}"
        ex = subprocess.run(["tar", "-x", "-C", str(tmp)], input=tar.stdout,
                            capture_output=True, timeout=300)
        if ex.returncode != 0:
            return None, f"SIN TRINQUETE: no se pudo desempaquetar {base[:8]}"
        gate = tmp / ".github" / "scripts" / "check_suite_inventory.py"
        if not gate.is_file():
            # La base es anterior al gate: se le presta ESTE, que es lo unico
            # honesto que se puede hacer. Se mide el arbol de la base con el
            # instrumento de hoy.
            gate.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(__file__).resolve(), gate)
            propio = REPO / ".github" / "scripts" / "check_ci_config.py"
            destino = tmp / ".github" / "scripts" / "check_ci_config.py"
            if propio.is_file() and not destino.is_file():
                shutil.copy2(propio, destino)
        entorno = dict(os.environ)
        entorno["PYTHONDONTWRITEBYTECODE"] = "1"
        entorno.pop("S9K_INVENTARIO_ABLACION", None)
        entorno.setdefault("S9K_ALLOW_REAL_INGEST", "")
        r = subprocess.run(
            [sys.executable, str(gate), "--escribir-inventario", "--sin-base"],
            cwd=tmp, capture_output=True, text=True, env=entorno, timeout=1800)
        destino = tmp / ".github" / "suite-inventario.json"
        if not destino.is_file():
            return None, (f"SIN TRINQUETE: la medida de {base[:8]} no produjo "
                          f"inventario (rc={r.returncode})")
        datos = json.loads(destino.read_text(encoding="utf-8"))
        return datos, f"base {base[:8]} MATERIALIZADA y medida en el sitio"
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return None, f"SIN TRINQUETE: fallo al materializar {base[:8]} ({e})"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _lineas_de_bajas() -> list[str]:
    if not BAJAS.exists():
        return []
    return [l.split("#")[0].strip()
            for l in BAJAS.read_text(encoding="utf-8").splitlines()
            if l.split("#")[0].strip()]


PREFIJOS_DECLARACION = ("descritificar:",)

REGISTRO_XFAIL = REPO / ".github" / "xfail-registro.txt"


def bajas_declaradas() -> set[str]:
    """Modulos retirados a proposito. NO sirve para retirar un CRITICO."""
    return {l for l in _lineas_de_bajas()
            if not l.startswith(PREFIJOS_DECLARACION)}


def _nodeids_autorizados() -> set[str]:
    """Los nodeids EXACTOS que el registro autoriza."""
    if not REGISTRO_XFAIL.exists():
        return set()
    salida = set()
    for cruda in REGISTRO_XFAIL.read_text(encoding="utf-8").splitlines():
        if cruda.lstrip().startswith("#") or not cruda.strip():
            continue
        campos = [c.strip() for c in cruda.split("|")]
        if len(campos) == 3 and campos[1]:
            salida.add(campos[1])
    return salida


def xfail_autorizados_por_modulo() -> dict[str, int]:
    """modulo -> cuantos `xfail` autoriza `.github/xfail-registro.txt`.

    LA ESCOTILLA DE X-T ES EL REGISTRO, no una sintaxis propia. Se probo con un
    `defecto-conocido:` en `suite-bajas.txt` y se retiro antes de empujarlo:
    tener DOS sitios donde declarar la misma excepcion es como se acaba con dos
    verdades distintas. El registro ya es el fichero escrito a mano, versionado
    y visible en el diff donde vive la autorizacion; X-T solo lo consulta.

    Ojo con lo que este trinquete mide, que no es lo mismo que mide el registro:
    X-T cuenta SITIOS de marca en el codigo (decoradores y
    `pytest.param(..., marks=...)`), y el registro cuenta PRUEBAS EJECUTADAS.
    Un sitio parametrizado produce varias pruebas. Por eso X-T es defensa en
    profundidad y no la garantia: la garantia es el registro contra la
    ejecucion.
    """
    if not REGISTRO_XFAIL.exists():
        return {}
    conteo: dict[str, int] = {}
    for cruda in REGISTRO_XFAIL.read_text(encoding="utf-8").splitlines():
        if cruda.lstrip().startswith("#") or not cruda.strip():
            continue
        campos = [c.strip() for c in cruda.split("|")]
        if len(campos) != 3:
            continue
        modulo = campos[1].split("::")[0]
        if modulo.endswith(".py"):
            conteo[modulo] = conteo.get(modulo, 0) + 1
    return conteo


def descritificaciones_declaradas() -> set[str]:
    """Modulos a los que se les retira la CRITICIDAD, que es otra cosa.

    Separado de las bajas a proposito, y no es burocracia: un revisor demostro
    que juntarlo permitia retirar una suite critica en UN SOLO commit —quitar
    el marcador, escribir la baja y borrar el fichero— porque la criticidad se
    recalcula desde HEAD y en HEAD ya no habia marcador. Ahora descritificar y
    dar de baja son dos actos distintos, y el gate exige que el modulo siga
    VIVO Y RECOLECTADO cuando se le quita la criticidad. Retirarlo de verdad
    necesita un segundo commit, con la descritificacion ya mergeada.
    """
    return {l[len("descritificar:"):].strip() for l in _lineas_de_bajas()
            if l.startswith("descritificar:")}


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Inventario de suites como PUERTA")
    ap.add_argument("--escribir-inventario", action="store_true",
                    help="regenera .github/suite-inventario.json (la base del trinquete)")
    ap.add_argument("--sin-base", action="store_true",
                    help="no aplica el trinquete contra origin/main (uso local)")
    ap.add_argument("--base-fichero", metavar="JSON",
                    help="usa ESE inventario como base en vez del merge-base "
                         "(SOLO calibracion: en ci.yml esta prohibido)")
    args = ap.parse_args()

    # Autoguardia. Las tres banderas de desarme de este gate existen para la
    # calibracion y para el uso local. Si alguna aparece en `ci.yml`, el gate
    # de CI estaria midiendo con el instrumento desarmado y saldria verde sin
    # comprobar nada: exactamente la familia de fallo que este fichero cierra.
    # No se confia en que nadie las escriba: se COMPRUEBA.
    if CI.exists():
        texto_ci = CI.read_text(encoding="utf-8")
        if "check_suite_inventory.py" in texto_ci:
            for bandera in ("--sin-base", "--base-fichero", "S9K_INVENTARIO_ABLACION"):
                if bandera in texto_ci:
                    print(f"::error::`{bandera}` aparece en ci.yml. Desarma este "
                          f"gate: el job saldria verde sin trinquete ni control.")
                    return 1

    # El REGISTRO no se genera: si algun paso de CI lo escribiera, la escotilla
    # dejaria de ser una decision revisable y se convertiria en un sello
    # automatico —y ademas inferiria la excepcion de la misma ejecucion cuya
    # integridad este gate protege—. No hay ninguna opcion que lo escriba, y
    # ademas se comprueba que nadie lo redirija desde `ci.yml`.
    if CI.exists():
        texto_ci = CI.read_text(encoding="utf-8")
        for linea in texto_ci.splitlines():
            if "xfail-registro.txt" not in linea:
                continue
            if any(op in linea for op in (">", ">>", "tee", "sed -i", "cp ", "mv ")):
                print(f"::error::`ci.yml` ESCRIBE en `xfail-registro.txt`: "
                      f"`{linea.strip()[:90]}`. El registro es una escotilla "
                      f"revisable, no un artefacto: si CI lo regenera deja de "
                      f"declarar nada y pasa a sellar lo que haya.")
                return 1

    if ABLACION:
        print(f"::warning::ABLACION ACTIVA: control {ABLACION} DESACTIVADO. "
              f"Solo es legitimo dentro de la calibracion.")

    errores: list[str] = []
    invocaciones = derivar_invocaciones()
    raices = raices_invocadas()
    print("=== F1: invocaciones de pytest DERIVADAS de ci.yml ===")
    for inv in invocaciones:
        print(f"  {inv['job']} / {inv['paso']}  [cwd={inv['cwd']}]  -> {inv['raices']}")
    print(f"\n=== raices invocadas (union, sin solapes): "
          f"{[r.relative_to(REPO).as_posix() for r in raices]}")
    if not raices:
        print("::error::no se derivo ninguna raiz de ci.yml: sin fuente canonica "
              "no hay inventario que valga")
        return 1

    inventario_bruto, salida = inventario_recolectado(raices)
    en_disco = modulos_en_disco(raices)
    print(f"\n=== F2: {len(inventario_bruto)} modulos recolectados, "
          f"{sum(inventario_bruto.values())} tests; {len(en_disco)} ficheros "
          f"`test_*.py` en disco bajo esas raices")

    por_calibrador = criticos_por_calibrador()
    por_marcador = criticos_por_marcador(en_disco)
    criticos = set(por_calibrador) | set(por_marcador)
    print(f"\n=== F3/F4: {len(criticos)} modulos CRITICOS derivados")
    for rel in sorted(criticos):
        print(f"  {rel}  <- {por_calibrador.get(rel) or ['pytest.mark.critico']}")

    delegados, fallos_delegacion = modulos_delegados()
    exigidas = dependencias_exigidas(en_disco)

    # El inventario que se compara y se publica EXCLUYE los delegados: si se
    # colaran, la misma rama daria un inventario distinto en una maquina con
    # Playwright y en un runner sin el, y el trinquete se volveria un generador
    # de rojos falsos. Su trinquete es de presencia (C-bis), no de recuento.
    inventario = {k: v for k, v in inventario_bruto.items() if k not in delegados}
    if len(inventario) != len(inventario_bruto):
        print(f"    ({len(inventario_bruto) - len(inventario)} modulos delegados "
              f"excluidos del recuento; su trinquete es de presencia)")

    # --- E: preflight de dependencias -------------------------------------
    # E1 (ENTORNO): lo que un modulo necesita para no auto-omitirse tiene que
    #    poder importarse aqui.
    # E2 (DECLARACION): y ademas tiene que estar DECLARADO en lo que instala
    #    cada job que ejecuta ese modulo. E1 sin E2 pasa en verde mientras la
    #    dependencia llegue por transitividad, y el dia que el paquete de
    #    arriba cambie de rango N pruebas se vuelven skips sin que nada avise.
    instalaciones = instalaciones_por_job()
    modulos_por_job: dict[str, set[str]] = {}
    for inv in invocaciones:
        base_cwd = REPO / inv["cwd"]
        raices_job = []
        for r in inv["raices"]:
            p = (base_cwd / r.split("::")[0]).resolve()
            if p.exists():
                raices_job.append(p)
        modulos_por_job.setdefault(inv["job"], set()).update(modulos_en_disco(raices_job))

    if ABLACION != "E":
        errores += fallos_delegacion
        for paquete, quienes in sorted(exigidas.items()):
            pendientes = [q for q in quienes if q not in delegados]
            if not pendientes or _es_del_repositorio(paquete):
                continue
            if not (_importable(paquete) or _importable(paquete.split(".")[0])):
                errores.append(
                    f"PREFLIGHT (entorno): falta `{paquete}` y {len(pendientes)} "
                    f"modulo(s) se auto-omiten sin el: {pendientes[:5]}"
                    f"{'...' if len(pendientes) > 5 else ''}. Una dependencia "
                    f"ausente NO puede convertir pruebas en skips verdes."
                )
                continue
            distribuciones = {normaliza_distribucion(d) for d in _distribuciones(paquete)}
            for job_id, declarados in sorted(instalaciones.items()):
                afectados = sorted(modulos_por_job.get(job_id, set()) & set(pendientes))
                if not afectados or not declarados:
                    continue
                if distribuciones & declarados:
                    continue
                errores.append(
                    f"PREFLIGHT (declaracion): el job `{job_id}` ejecuta "
                    f"{afectados[:3]}{'...' if len(afectados) > 3 else ''}, que se "
                    f"auto-omiten sin `{paquete}`, y NO declara ninguna de "
                    f"{sorted(distribuciones)} en lo que instala. Si hoy llega por "
                    f"transitividad, el dia que deje de llegar esas pruebas se "
                    f"convierten en skips verdes."
                )

    # --- F: ningun job puede EXCLUIR parte de lo que recorre ---------------
    if ABLACION != "F":
        errores += comprueba_filtros_de_exclusion(invocaciones, raices)

    # --- H: ninguna VARIABLE DE ENTORNO puede inyectar filtros -------------
    # Bandera PROPIA, separada de F: mientras compartieron bandera, un caso de
    # entorno podia estar apoyandose en el rojo del control de ARGUMENTOS sin
    # que nadie lo notara. Con dos banderas, cada familia demuestra su rojo.
    if ABLACION != "H":
        errores += comprueba_addopts_por_entorno(
            yaml.safe_load(CI.read_text(encoding="utf-8")))
        errores += comprueba_arranque_oculto()

    # --- A: anti-silenciado ------------------------------------------------
    # A1 incondicional: rojo siempre, no necesita base. Es la mutacion del
    # ejercicio RC. A2 (mas abajo, con la base): el conjunto de silenciados
    # CONDICIONALES no puede crecer.
    silenciados_ahora: dict[str, str] = {}
    condiciones_ahora: dict[str, str] = {}
    en_pie_ahora: dict[str, int] = {}
    # Censo de `xfail` por modulo, DELEGADOS INCLUIDOS. `en_pie` los deja fuera
    # -su trinquete es de presencia-, y ahi estaba el hueco: los 6 `xfail` del
    # arnes de navegador no los descontaba nadie. Este censo si los ve.
    xfail_ahora: dict[str, int] = {}
    for rel in sorted(en_disco):
        cuerpo = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        if rel not in delegados:
            en_pie_ahora[rel] = tests_en_pie(cuerpo)
        n_xfail = len(xfail_por_decorador(cuerpo))
        if n_xfail:
            xfail_ahora[rel] = n_xfail
        veredicto = silenciado(cuerpo)
        if veredicto:
            clase, motivo = veredicto
            silenciados_ahora[rel] = clase
            if clase == CONDICIONAL:
                condiciones_ahora[rel] = condicion_de_silencio(cuerpo)
            if ABLACION != "A" and clase == INCONDICIONAL:
                etiqueta = "CRITICO " if rel in criticos else ""
                errores.append(
                    f"SILENCIADO: el modulo {etiqueta}`{rel}` esta apagado ENTERO e "
                    f"INCONDICIONALMENTE ({motivo}). El recuento `N passed` no lo "
                    f"delata: sus tests se siguen recolectando. Un fichero de gate "
                    f"silenciado es un gate que no existe."
                )
        # A4: el mismo apagado, test a test. Es el superviviente que decoro las
        # 20 funciones de `test_parcialidad_declarada.py` y dejo el gate verde.
        if ABLACION != "A":
            for nombre, motivo in apagados_por_decorador(cuerpo):
                etiqueta = "CRITICO " if rel in criticos else ""
                errores.append(
                    f"TEST APAGADO: `{rel}::{nombre}` del modulo {etiqueta}esta "
                    f"apagado INCONDICIONALMENTE ({motivo}). Apagar una suite test "
                    f"a test es el mismo ataque que apagar el modulo, escrito en "
                    f"otra sintaxis, y NO cambia el recuento de coleccion: un test "
                    f"con `skip` se sigue recolectando. Si de verdad sobra, borralo."
                )

        # A7: en un modulo CRITICO, todo decorador tiene que resolver a una
        # marca literal de pytest. Polaridad invertida, como en `$GITHUB_ENV`.
        if ABLACION != "A" and rel in criticos:
            for nombre, escrito in decoradores_no_verificables(cuerpo):
                errores.append(
                    f"DECORADOR NO VERIFICABLE en un modulo CRITICO: "
                    f"`{rel}::{nombre}` lleva `@{escrito}`, que no es un "
                    f"`pytest.mark.<nombre>` literal. Este gate no puede decidir "
                    f"a que marca resuelve —puede ser una funcion que devuelve "
                    f"`pytest.mark.xfail`, un `dict` de marcas, un alias de alias "
                    f"o un import de otro modulo—, y enumerar esas formas no "
                    f"acaba nunca: ya se probo cuatro veces. Se admite solo la "
                    f"forma comprobable. Medido: los 57 decoradores de los 20 "
                    f"modulos criticos son `pytest.mark.parametrize`, asi que "
                    f"esto no rompe nada de lo que hay."
                )

        # A5: `@pytest.mark.xfail` en un modulo CRITICO. Prohibido siempre y sin
        # excepciones, porque hoy hay CERO en modulos criticos (medido: 13
        # `xfail` en 5 modulos, ninguno critico). Los NO criticos no se
        # prohiben —seria rojo por codigo legitimo de otros carriles— y los
        # sujeta el trinquete D2, porque `tests_en_pie` los descuenta.
        if ABLACION != "A" and rel in criticos:
            for nombre, motivo in xfail_por_decorador(cuerpo):
                # AUTORIZADO en el registro -> legitimo tambien en una suite
                # critica. Sin esta exencion el registro no seria una escotilla
                # ahi, y "prohibido siempre" sin via declarada es como se acaba
                # desactivando un gate.
                #
                # El prefijo `rel::nombre[` es para localizar las INSTANCIAS
                # parametrizadas de esta funcion, no para ampliar ninguna
                # autorizacion: la autorizacion sigue siendo EXACTA y la
                # comprueba la capa de resultados nodeid a nodeid.
                ancla = f"{rel}::{nombre}"
                if any(n == ancla or n.startswith(ancla + "[")
                       for n in _nodeids_autorizados()):
                    continue
                errores.append(
                    f"PRUEBA QUE NO PUEDE FALLAR: `{rel}::{nombre}` en un modulo "
                    f"CRITICO ({motivo}). Medido con un defecto inyectado de "
                    f"verdad en una suite critica: sin la marca, `1 failed` y "
                    f"EXIT=1; con ella, `1 xfailed, 21 xpassed` y EXIT=0. Ni el "
                    f"recuento ni el informe JUnit lo delatan —las 22 `<testcase>` "
                    f"siguen ahi—, asi que una suite critica dejaba de sujetar "
                    f"nada con todos los instrumentos en verde. Si la prueba esta "
                    f"rota, arreglala o borrala; no la vuelvas incapaz de fallar."
                )

    # A6: ningun `conftest.py` puede MARCAR pruebas desde fuera del modulo.
    # Va fuera del bucle de modulos porque no es una propiedad de un modulo:
    # es del arbol entero, y un solo `conftest.py` alcanza a todos los de su
    # directorio hacia abajo.
    if ABLACION != "A":
        for fichero, motivo in marca_inyectada_en_ejecucion():
            errores.append(
                f"APAGADO INYECTADO EN EJECUCION: `{fichero}` {motivo}. Medido en "
                f"un sandbox: cuatro lineas de `pytest_collection_modifyitems` con "
                f"`add_marker(pytest.mark.xfail(...))` convierten `1 failed` "
                f"(EXIT=1) en `1 xfailed, 1 xpassed` (EXIT=0) sin tocar una coma "
                f"del fichero de test. Ni el AST del modulo, ni `tests_en_pie`, "
                f"ni D2, ni A5 pueden verlo, y el informe JUnit solo delata la "
                f"marca cuando ya se ha tragado un fallo. Si de verdad hace falta "
                f"marcar desde un `conftest`, que sea una decision visible."
            )

    # --- B: anti-desaparicion ---------------------------------------------
    if ABLACION != "B":
        sin_tests = {rel for rel in en_disco
                     if not declara_tests((REPO / rel).read_text(encoding="utf-8",
                                                                 errors="replace"))}
        for rel in sorted(en_disco - set(inventario) - delegados - sin_tests):
            porque = ""
            for paquete, quienes in exigidas.items():
                if rel in quienes:
                    porque = (f" Depende de `{paquete}` via `importorskip`: si no "
                              f"esta instalado, el modulo desaparece de la "
                              f"coleccion sin una sola linea de aviso.")
            errores.append(
                f"DESAPARECIDO: `{rel}` define tests y existe en el arbol, pero "
                f"pytest NO recolecta ni uno de el.{porque}"
            )

    # --- C y D: trinquete contra la base ----------------------------------
    if args.sin_base:
        datos_base, nota = None, "SIN TRINQUETE: --sin-base"
    elif args.base_fichero:
        ruta = Path(args.base_fichero)
        datos_base = json.loads(ruta.read_text(encoding="utf-8"))
        nota = f"base LOCAL {ruta} (calibracion; en ci.yml esta prohibido)"
    else:
        datos_base, nota = inventario_base()
    base = None if datos_base is None else datos_base["modulos"]
    print(f"\n=== F5: {nota}")
    if base is not None:
        bajas = bajas_declaradas()
        # C-bis: los modulos DELEGADOS (Node, Chromium) no se recolectan en el
        # entorno de este job, asi que su trinquete no puede ser de coleccion
        # —seria rojo en un job y verde en otro, que es medir una cosa y
        # certificar otra—. El suyo es de PRESENCIA: el fichero tiene que
        # seguir existiendo. Sin esto quedaba un hueco real: borrar uno de los
        # cinco `viewer/tests/browser/test_browser_*.py` no lo veia nadie,
        # porque `check_ci_config` exige que el job los ejecute por NOMBRE DE
        # DIRECTORIO y un directorio con un fichero menos sigue pasando.
        # El silenciado de un delegado si lo ve el control A, que es AST y no
        # necesita entorno.
        if ABLACION != "C":
            for rel in sorted(datos_base.get("delegados") or []):
                if (REPO / rel).is_file() or rel in bajas:
                    continue
                errores.append(
                    f"BORRADO DE SUITE DELEGADA: `{rel}` estaba en el inventario "
                    f"de la base y ya no existe en el arbol. Sus pruebas solo "
                    f"corren en el job que instala su herramienta externa, que "
                    f"las ejecuta por directorio: un fichero menos ahi no baja "
                    f"ningun recuento que nadie vigile."
                )
        # A2: el conjunto de modulos silenciados no puede CRECER. Aqui es donde
        # muere el `skipif` sobre una condicion inventada, que A1 no ve.
        if ABLACION != "A":
            silenciados_antes = set(datos_base.get("silenciados") or {})
            condiciones_antes = datos_base.get("condiciones") or {}
            for rel, cond in sorted(condiciones_ahora.items()):
                antes = condiciones_antes.get(rel)
                if antes is None or antes == cond:
                    continue
                errores.append(
                    f"CONDICION DE SILENCIO REESCRITA: `{rel}` sigue silenciado, "
                    f"pero su condicion paso de `{antes}` a `{cond}`. A2 hace "
                    f"trinquete sobre la PERTENENCIA al conjunto, asi que sin esto "
                    f"se le podia cambiar la condicion por una que nadie define "
                    f"nunca y el modulo quedaba apagado sin salir del conjunto."
                )
            for rel in sorted(set(silenciados_ahora) - silenciados_antes):
                etiqueta = "CRITICO " if rel in criticos else ""
                errores.append(
                    f"SILENCIADO NUEVO: el modulo {etiqueta}`{rel}` no estaba "
                    f"silenciado en la base y ahora lo esta "
                    f"({silenciados_ahora[rel]}). El conjunto de suites apagadas "
                    f"es un trinquete: solo puede encoger."
                )
        if ABLACION != "C":
            for rel in sorted(set(base) - set(inventario)):
                if rel in criticos:
                    errores.append(
                        f"BORRADO DE SUITE CRITICA: `{rel}` estaba en el inventario "
                        f"de la base ({base[rel]} tests) y ya no se recolecta. Es "
                        f"CRITICO (lo declara "
                        f"{por_calibrador.get(rel) or 'pytest.mark.critico'}): NO se "
                        f"puede dar de baja en .github/suite-bajas.txt."
                    )
                elif rel not in bajas:
                    errores.append(
                        f"BORRADO DE SUITE: `{rel}` estaba en el inventario de la "
                        f"base ({base[rel]} tests) y ya no se recolecta. Si la baja "
                        f"es deliberada, declarala en .github/suite-bajas.txt "
                        f"—queda a la vista en el diff—; si no lo es, acabas de "
                        f"perder {base[rel]} pruebas en silencio."
                    )
        # G: el conjunto de CRITICOS solo puede crecer.
        #
        # Dos supervivientes medidos vivian aqui. (1) Borrar
        # `pytestmark = pytest.mark.critico` bajaba los criticos de 20 a 19 en
        # silencio: el JSON los PUBLICABA y ningun control los comparaba.
        # (2) Peor: se podia retirar una suite critica en UN SOLO commit
        # —quitar el marcador, escribir la baja, borrar el fichero— porque la
        # criticidad se recalcula desde HEAD y en HEAD ya no habia marcador.
        # La afirmacion "un critico no se puede dar de baja" era FALSA.
        # G tiene su PROPIA ablacion, y no es un detalle de contabilidad: mientras
        # compartio la de C, el trinquete de criticos —el control mas nuevo y el
        # que mas sujeta— era el unico sin demostrar que sujetase algo por si
        # solo. La regla vale para todos o no vale.
        if ABLACION != "G":
            criticos_antes = set(datos_base.get("criticos") or [])
            descritificados = descritificaciones_declaradas()
            for rel in sorted(criticos_antes - criticos):
                if rel not in inventario:
                    errores.append(
                        f"CRITICIDAD RETIRADA Y SUITE PERDIDA A LA VEZ: `{rel}` era "
                        f"CRITICO en la base y ahora ni es critico ni se recolecta. "
                        f"Descritificar y dar de baja son dos actos y necesitan dos "
                        f"commits: primero se retira la criticidad con la suite VIVA "
                        f"—queda mergeado y a la vista—, y solo despues se puede "
                        f"retirar la suite."
                    )
                elif rel not in descritificados:
                    errores.append(
                        f"CRITICIDAD RETIRADA EN SILENCIO: `{rel}` era CRITICO en la "
                        f"base y ya no lo es. El conjunto de criticos solo puede "
                        f"CRECER. Si es deliberado, declaralo en "
                        f".github/suite-bajas.txt como `descritificar: {rel}` "
                        f"—se ve en el diff— y deja la suite viva."
                    )

        if ABLACION != "D":
            # D2: trinquete sobre los tests QUE QUEDAN EN PIE, no sobre los
            # recolectados. Un test decorado con `skip` se sigue recolectando,
            # asi que el recuento de coleccion no baja y no delataba nada.
            en_pie_antes = datos_base.get("en_pie") or {}
            for rel, antes in sorted(en_pie_antes.items()):
                ahora = en_pie_ahora.get(rel)
                if ahora is None or ahora >= antes:
                    continue
                errores.append(
                    f"TESTS EN PIE A LA BAJA: `{rel}` definia {antes} tests sin "
                    f"apagar y ahora {ahora}. Esta medida no la mueve `parametrize` "
                    f"ni la maquilla un `skip`: cuenta lo que queda por ejecutar."
                )
            for rel, antes in sorted(base.items()):
                ahora = inventario.get(rel)
                if ahora is None or ahora >= antes:
                    continue
                errores.append(
                    f"RECUENTO A LA BAJA: `{rel}` recolectaba {antes} tests en la "
                    f"base y ahora {ahora}. El trinquete es POR MODULO a proposito: "
                    f"anadir tests en otro sitio no compensa esta caida."
                )
            # X-T: trinquete sobre el censo de `xfail`, delegados incluidos.
            #
            # POR QUE UN TRINQUETE Y NO UNA PROHIBICION, y esto lo ensenó un
            # rojo mio en CI: se puso un `grep -qE '[0-9]+ (xfailed|xpassed)'`
            # en el job del navegador y ENROJECIO, porque esa suite lleva 6
            # `xfail(strict=True)` que NO son silenciadores. Son un registro de
            # DEFECTOS CONOCIDOS: la prueba que deberia pasar, escrita ya, para
            # que el dia que alguien arregle el defecto el XPASS se convierta en
            # fallo (`strict`) y obligue a quitar la marca. Eso es lo contrario
            # de apagar una prueba, y ademas esta documentado.
            #
            # Un `grep` no distingue el patron declarado del apagado nuevo:
            # solo sabe contar hasta uno. Un trinquete si, porque compara contra
            # una BASE. Los 6 existentes se quedan; lo que no puede es CRECER.
            #
            # UNIDADES: X-T cuenta SITIOS de marca (decoradores y
            # `pytest.param(..., marks=...)`), no INSTANCIAS ejecutadas. Es la
            # misma distincion que ya esta escrita para `en_pie` frente a
            # JUnit, y por eso 9 sitios dan 12 `xfailed` en corrida real: no es
            # un fallo del censo. Consecuencia asumida y dicha en voz alta:
            # anadir un caso a un `parametrize` YA marcado aumenta las pruebas
            # que no pueden fallar sin mover el censo. Cerrarlo pediria contar
            # instancias, o sea ejecutar; el sitio para eso es la capa de
            # ejecucion real, no este trinquete estatico.
            xfail_antes = datos_base.get("xfail") or {}
            declarados = xfail_autorizados_por_modulo()
            for rel in sorted(set(xfail_ahora) | set(xfail_antes)):
                antes, ahora = xfail_antes.get(rel, 0), xfail_ahora.get(rel, 0)
                permitido = antes + declarados.get(rel, 0)
                if ahora <= permitido:
                    continue
                errores.append(
                    f"MAS PRUEBAS QUE NO PUEDEN FALLAR: `{rel}` tenia {antes} "
                    f"`xfail` en la base y ahora {ahora}"
                    + (f" (con {declarados[rel]} autorizado(s) en el registro, "
                       f"total permitido {permitido})"
                       if rel in declarados else "")
                    + f". El trinquete cubre tambien los modulos DELEGADOS, que "
                    f"no entran en `en_pie`.\n"
                    f"    SALIDA DECLARADA: la escotilla es el REGISTRO. Anade "
                    f"a `.github/xfail-registro.txt` una linea\n"
                    f"        <id> | {rel}::<test> | <motivo>\n"
                    f"    y aparecera en el diff del PR, que es donde se "
                    f"discute. NO regeneres el inventario esperando que sirva, "
                    f"porque NO sirve: la base de este trinquete se MIDE del "
                    f"arbol del merge-base, no del fichero publicado. Medido: "
                    f"con un `xfail` nuevo, sin regenerar da EXIT=1 y "
                    f"regenerando da EXIT=1 con los mismos errores.\n"
                    f"    Si en cambio es una prueba que molesta: arreglala o "
                    f"borrala, pero no la vuelvas incapaz de fallar."
                )

            total_antes, total_ahora = sum(base.values()), sum(inventario.values())
            if total_ahora < total_antes * (1 - TOLERANCIA_GLOBAL):
                errores.append(
                    f"CAIDA ANORMAL DEL RECUENTO GLOBAL: {total_antes} -> "
                    f"{total_ahora} tests recolectados (tolerancia "
                    f"{TOLERANCIA_GLOBAL:.0%})."
                )

    if args.escribir_inventario:
        INVENTARIO.write_text(json.dumps({
            "_generado_por": ".github/scripts/check_suite_inventory.py --escribir-inventario",
            "_no_editar_a_mano": "es una MEDIDA, no una lista: se regenera, no se mantiene",
            "raices": [r.relative_to(REPO).as_posix() for r in raices],
            "criticos": sorted(criticos),
            "silenciados": dict(sorted(silenciados_ahora.items())),
            "condiciones": dict(sorted(condiciones_ahora.items())),
            "en_pie": dict(sorted(en_pie_ahora.items())),
            "xfail": dict(sorted(xfail_ahora.items())),
            "delegados": sorted(delegados & en_disco),
            "total": sum(inventario.values()),
            "modulos": dict(sorted(inventario.items())),
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\ninventario escrito en {INVENTARIO.relative_to(REPO)}")

    for e in errores:
        print(f"::error::{e}")
    if errores:
        print(f"\nFALLO: {len(errores)} problema(s) de inventario de suites")
        if not inventario:
            print("(la coleccion salio VACIA; ultimas lineas de pytest:)")
            print(salida[-4000:])
        return 1
    # El mensaje de exito NO puede afirmar un control que no se ejecuto. La
    # version anterior imprimia "trinquete de presencia y de recuento
    # satisfecho" incluso cuando NO habia base, y ademas el aviso de que
    # faltaba era un `print` corriente: la ejecucion no emitia ni una
    # anotacion. Un OK que miente sobre un control que no corrio es peor que
    # no tener el control, porque compra la confianza sin dar la garantia.
    aplicados = [
        f"{len(inventario)} modulos recolectados ({sum(inventario.values())} tests)",
        "ninguno silenciado entero ni test a test",
        "ninguna suite desaparecida",
        "ningun job excluye parte de lo que recorre",
        f"{len(criticos)} criticos derivados de fuentes ejecutables",
        "ninguna dependencia ausente convirtiendo pruebas en skips verdes",
    ]
    if base is None:
        print("::warning::SIN TRINQUETE: no hay base de comparacion "
              f"({nota}). NO se han comprobado el anti-borrado (C/C-bis), el "
              f"trinquete de recuento (D), el de tests en pie (D2), el de "
              f"criticos (G) ni el de silenciados (A2). Este verde NO los "
              f"incluye.")
    else:
        aplicados += [
            f"trinquete de presencia, de recuento, de tests en pie, de criticos "
            f"y de silenciados satisfecho contra la {nota}",
        ]
    print("\nOK: " + ", ".join(aplicados))
    return 0


if __name__ == "__main__":
    sys.exit(main())
