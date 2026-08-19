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
`S9K_INVENTARIO_ABLACION=A|B|C|D|E` desactiva UN control. Existe para que
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

def _menciona_skip(nodo: ast.AST) -> bool:
    for hijo in ast.walk(nodo):
        if isinstance(hijo, ast.Attribute) and hijo.attr in ("skip", "skipif"):
            return True
        if isinstance(hijo, ast.Name) and hijo.id in ("skip", "skipif"):
            return True
        if isinstance(hijo, ast.Constant) and isinstance(hijo.value, str) \
                and hijo.value in ("skip", "skipif"):
            return True
    return False


INCONDICIONAL, CONDICIONAL = "INCONDICIONAL", "CONDICIONAL"


def _condicion_constante_verdadera(nodo: ast.AST) -> bool:
    """`skipif(True, ...)` es un `skip` disfrazado; `skipif(not URI, ...)` no."""
    if isinstance(nodo, ast.Call) and nodo.args:
        prim = nodo.args[0]
        return isinstance(prim, ast.Constant) and bool(prim.value)
    return False


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
                if nombre_marca == "skipif" and _condicion_constante_verdadera(c):
                    return (INCONDICIONAL,
                            "`pytestmark = pytest.mark.skipif(<constante verdadera>)`, "
                            "que es un `skip` disfrazado")
                return CONDICIONAL, "`pytestmark` a nivel de modulo con `skipif`"
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
    apagados = {n for n, _ in apagados_por_decorador(texto)}
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


def bajas_declaradas() -> set[str]:
    """Modulos retirados a proposito. NO sirve para retirar un CRITICO."""
    return {l for l in _lineas_de_bajas() if not l.startswith("descritificar:")}


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

    # --- A: anti-silenciado ------------------------------------------------
    # A1 incondicional: rojo siempre, no necesita base. Es la mutacion del
    # ejercicio RC. A2 (mas abajo, con la base): el conjunto de silenciados
    # CONDICIONALES no puede crecer.
    silenciados_ahora: dict[str, str] = {}
    condiciones_ahora: dict[str, str] = {}
    en_pie_ahora: dict[str, int] = {}
    for rel in sorted(en_disco):
        cuerpo = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        if rel not in delegados:
            en_pie_ahora[rel] = tests_en_pie(cuerpo)
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
        if ABLACION != "C":
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
