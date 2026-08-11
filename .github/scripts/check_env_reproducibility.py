#!/usr/bin/env python3
"""Reproducibilidad de entorno: lo DECLARADO tiene que ser lo EJECUTADO.

Este gate cierra cuatro huecos que en este repositorio ya se leyeron como
verde sin comprobar nada:

1. VERSIONES. `viewer/requirements.txt` declara `fastapi>=0.141.1` y
   `pytest>=9.1.1`, pero un entorno con `fastapi 0.139.0` y `pytest 8.4.2`
   ejecutaba las pruebas igual. Nada comparaba lo declarado con lo instalado,
   asi que la suite verde no decia nada sobre la version que se probaba.

2. FIJACION. Un `.lock` que no fija (`==`) no es un lock. Y un rango sin cota
   superior (`python-multipart>=0.0.9`) instala manana una version que nadie
   ha probado, sin cambiar una linea del repositorio.

3. DEPENDENCIA USADA Y NO DECLARADA. Un import de tercero que funciona porque
   llego arrastrado como dependencia transitiva desaparece el dia que el
   paquete intermedio deje de traerlo. Los imports se DERIVAN del arbol de
   fuentes con `ast`: no hay lista que mantener.

4. RUNTIMES EXTERNOS (Node, Chromium). Dos veces una suite se auto-omitio por
   falta de runtime y el job siguio en verde; un modulo entero llego a saltarse
   170 pruebas. Aqui la ausencia de runtime es un FALLO RUIDOSO:

   - `runtimes --require node,chromium` comprueba la presencia AHORA, dentro
     del job, y sale en rojo si falta. No hay `|| true` ni degradacion.
   - `runtime-gates` DERIVA del arbol de tests que runtimes externos hacen que
     un fichero se auto-omita (`shutil.which(...)`, `importorskip`, `skip` con
     mensaje de runtime) y exige que exista un job en `ci.yml` que aprovisione
     ese runtime, ejecute el fichero por nombre y lleve guardia antisalto.
     Un fichero NUEVO que manana se auto-omita por falta de un runtime pone el
     gate en rojo hasta que tenga job: es construccion, no vigilancia.

FRONTERA: este fichero es del carril de reproducibilidad de entorno.
`.github/scripts/check_ci_config.py` es de otro carril y NO se toca; alli se
comprueba la politica de disparo de ramas, aqui el entorno. El solape en Node
es deliberado y barato: dos gates que fallan por el mismo motivo es mejor que
cero.

Sin dependencias externas: se ejecuta con el Python del runner tal cual.
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# La raiz es inyectable para que el gate se pueda CALIBRAR: la calibracion
# (`check_env_reproducibility_calibration.py`) construye repositorios sinteticos
# en directorios temporales, mete una violacion, comprueba que este fichero se
# pone ROJO, la retira y comprueba que vuelve a VERDE. Sin esta inyeccion la
# unica forma de calibrar seria romper el repositorio de verdad.
REPO = Path(os.environ.get("S9K_ENV_REPRO_ROOT") or Path(__file__).resolve().parents[2])
CI = REPO / ".github" / "workflows" / "ci.yml"

# Arboles de fuentes y el fichero que declara SUS dependencias.
ARBOLES = (
    ("viewer", REPO / "viewer", REPO / "viewer" / "requirements.txt"),
    ("data-engine", REPO / "data-engine", REPO / "data-engine" / "requirements.lock"),
)

EXCLUIDOS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache"}

# Runtimes externos que un test puede necesitar, y como se detecta su presencia.
# La deteccion es por EJECUTABLE, no por paquete: `pip install playwright` no
# implica que el navegador este descargado, y ese es justo el fallo que se ha
# dado (Chromium ausente -> skip verde).
RUNTIMES = {
    "node": {
        "cmds": ("node",),
        "prueba": ("node", "--version"),
        "provision": ("actions/setup-node",),
    },
    "chromium": {
        "cmds": (),  # se resuelve via playwright, ver `presente_chromium`
        "prueba": None,
        "provision": ("playwright install",),
    },
}

# Como se reconoce, en el texto de un test, que depende de un runtime externo.
# Patrones, no lista de ficheros: un test nuevo queda cubierto el dia que nace.
PATRONES_RUNTIME = {
    "node": (
        re.compile(r"which\(\s*[\"']node[\"']\s*\)"),
        re.compile(r"[\"']node[\"']\s*,\s*[\"']--version[\"']"),
    ),
    "chromium": (
        re.compile(r"importorskip\(\s*[\"']playwright"),
        re.compile(r"skip\([^)]*chromium", re.I),
        re.compile(r"which\(\s*[\"']chromium"),
    ),
}


# --------------------------------------------------------------------------
# utilidades
# --------------------------------------------------------------------------
def ficheros_py(raiz: Path):
    for py in raiz.rglob("*.py"):
        if any(p in EXCLUIDOS for p in py.parts):
            continue
        yield py


def normaliza(nombre: str) -> str:
    """Nombre de distribucion normalizado (PEP 503)."""
    return re.sub(r"[-_.]+", "-", nombre).strip().lower()


def lee_requisitos(ruta: Path) -> list[tuple[str, str, str]]:
    """(nombre_normalizado, especificador, linea_cruda) por requisito declarado."""
    fuera = []
    if not ruta.exists():
        return fuera
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        crudo = linea.split("#", 1)[0].strip()
        if not crudo or crudo.startswith("-"):
            continue
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(.*)$", crudo)
        if not m:
            continue
        fuera.append((normaliza(m.group(1)), m.group(3).strip(), crudo))
    return fuera


def version_tupla(v: str) -> tuple:
    """Orden de versiones suficiente para los esquemas que aqui se usan."""
    partes = []
    for trozo in re.split(r"[.\-+]", v):
        if trozo.isdigit():
            partes.append((0, int(trozo), ""))
        elif trozo:
            # 'rc1', 'b2', 'post1'... ordenan por debajo del numero limpio.
            num = re.match(r"^([A-Za-z]+)(\d*)$", trozo)
            if num:
                partes.append((-1, int(num.group(2) or 0), num.group(1)))
            else:
                partes.append((-1, 0, trozo))
    return tuple(partes)


def cumple(instalada: str, especificador: str) -> bool:
    """Evalua un especificador PEP 440 en las formas que este repo usa."""
    if not especificador:
        return True
    for clausula in especificador.split(","):
        clausula = clausula.strip()
        m = re.match(r"^(==|!=|>=|<=|>|<|~=)\s*(.+)$", clausula)
        if not m:
            continue
        op, ref = m.group(1), m.group(2).strip()
        if op == "==" and ref.endswith(".*"):
            if not instalada.startswith(ref[:-1]):
                return False
            continue
        a, b = version_tupla(instalada), version_tupla(ref)
        ok = {
            "==": a == b,
            "!=": a != b,
            ">=": a >= b,
            "<=": a <= b,
            ">": a > b,
            "<": a < b,
        }.get(op)
        if op == "~=":
            # `~=X.Y` == `>=X.Y, ==X.*`
            base = ref.rsplit(".", 1)[0]
            ok = a >= b and instalada.startswith(base + ".")
        if not ok:
            return False
    return True


def versiones_instaladas() -> dict[str, str]:
    import importlib.metadata as md

    fuera = {}
    for dist in md.distributions():
        nombre = dist.metadata["Name"]
        if nombre:
            fuera[normaliza(nombre)] = dist.version
    return fuera


# --------------------------------------------------------------------------
# 1. versiones declaradas vs instaladas
# --------------------------------------------------------------------------
def check_versions(strict_missing: bool) -> list[str]:
    errores = []
    instaladas = versiones_instaladas()
    for etiqueta, _raiz, req in ARBOLES:
        declarados = lee_requisitos(req)
        if not declarados:
            errores.append(f"{req.relative_to(REPO)}: no declara ninguna dependencia")
            continue
        rel = req.relative_to(REPO)
        print(f"-- {rel}: {len(declarados)} requisitos declarados")
        for nombre, spec, crudo in declarados:
            inst = instaladas.get(nombre)
            if inst is None:
                msg = (
                    f"{rel}: `{crudo}` esta DECLARADO y NO instalado en este "
                    f"entorno; lo que se ejecuta no es lo que el repositorio dice "
                    f"necesitar"
                )
                if strict_missing:
                    errores.append(msg)
                else:
                    print(f"AVISO: {msg}")
                continue
            if not cumple(inst, spec):
                errores.append(
                    f"{rel}: DIVERGENCIA en `{nombre}`: declarado `{spec or 'sin '
                    'especificador'}`, instalado `{inst}`. Un test verde con esta "
                    f"version no dice nada sobre la version declarada."
                )
    # Conflicto entre ficheros: el job combinado instala los dos.
    porfichero = {
        req.relative_to(REPO).as_posix(): dict(
            (n, s) for n, s, _ in lee_requisitos(req)
        )
        for _e, _r, req in ARBOLES
    }
    nombres = set()
    for d in porfichero.values():
        nombres |= set(d)
    for nombre in sorted(nombres):
        specs = {f: d[nombre] for f, d in porfichero.items() if nombre in d}
        if len(specs) < 2:
            continue
        pin = None
        for f, s in specs.items():
            m = re.match(r"^==\s*(.+)$", s.strip())
            if m:
                pin = m.group(1)
        if pin is None:
            continue
        for f, s in specs.items():
            if not cumple(pin, s):
                errores.append(
                    f"CONFLICTO entre ficheros para `{nombre}`: {specs}. El job "
                    f"combinado instala ambos, asi que uno de los dos NO se "
                    f"cumple y la version realmente probada depende del orden "
                    f"de instalacion."
                )
                break
    return errores


# --------------------------------------------------------------------------
# 2. fijacion
# --------------------------------------------------------------------------
def check_pinning() -> tuple[list[str], list[str]]:
    errores, avisos = [], []
    for _etiqueta, _raiz, req in ARBOLES:
        rel = req.relative_to(REPO)
        es_lock = req.suffix == ".lock"
        for nombre, spec, crudo in lee_requisitos(req):
            if es_lock:
                if not re.match(r"^==\s*\S+$", spec):
                    errores.append(
                        f"{rel}: `{crudo}` no esta FIJADO con `==`. Un fichero "
                        f".lock que no fija no es un lock: la version instalada "
                        f"puede cambiar sin que cambie el repositorio."
                    )
                continue
            tiene_sup = bool(re.search(r"(<|<=|==|~=)", spec))
            tiene_inf = bool(re.search(r"(>|>=|==|~=)", spec))
            if not spec:
                avisos.append(
                    f"{rel}: `{crudo}` SIN FIJAR: cualquier version vale, "
                    f"incluida una que nadie ha probado."
                )
            elif not tiene_sup:
                avisos.append(
                    f"{rel}: `{crudo}` sin COTA SUPERIOR: manana instala una "
                    f"version mayor sin cambiar una linea del repositorio."
                )
            elif not tiene_inf:
                avisos.append(
                    f"{rel}: `{crudo}` sin COTA INFERIOR: admite versiones "
                    f"antiguas que no cumplen lo que el codigo asume."
                )
    return errores, avisos


# --------------------------------------------------------------------------
# 2 bis. el .lock tiene que ser reconstruible desde su .in  (D5)
# --------------------------------------------------------------------------
def check_lock_reconstruible() -> list[str]:
    """Todo pin del `.lock` debe alcanzarse desde las raices del `.in`.

    D5 (carril I): el `.lock` fijaba `pytest` y `pytest-asyncio` sin que el
    `.in` los declarase. Un lock con pines huerfanos no se puede regenerar
    desde su fuente: quien lo rehaga pierde paquetes sin enterarse.

    La alcanzabilidad se DERIVA del grafo real de dependencias
    (`Requires-Dist` de las distribuciones instaladas), no de una lista. Se
    ignoran los marcadores de entorno a proposito: eso SOBRE-aproxima el
    cierre, asi que un huerfano senalado lo es de verdad.
    """
    import importlib.metadata as md

    errores = []
    for _etiqueta, _raiz, req in ARBOLES:
        if req.suffix != ".lock":
            continue
        entrada = req.with_suffix(".in")
        if not entrada.exists():
            continue
        rel_lock, rel_in = req.relative_to(REPO), entrada.relative_to(REPO)
        pines = {n for n, _s, _c in lee_requisitos(req)}
        raices = {n for n, _s, _c in lee_requisitos(entrada)}
        faltan = sorted(raices - pines)
        if faltan:
            errores.append(
                f"{rel_lock}: `{faltan}` estan declarados en {rel_in} y NO "
                f"aparecen fijados en el lock: el lock no refleja su fuente."
            )
        # Cierre transitivo desde las raices, usando el grafo instalado.
        requiere: dict[str, set[str]] = {}
        for dist in md.distributions():
            nombre = dist.metadata["Name"]
            if not nombre:
                continue
            hijos = set()
            for r in dist.requires or []:
                m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)", r)
                if m:
                    hijos.add(normaliza(m.group(1)))
            requiere[normaliza(nombre)] = hijos
        if not requiere:
            print(f"AVISO: sin metadatos instalados; no se comprueba {rel_lock}")
            continue
        alcanzados, pendientes = set(), list(raices)
        while pendientes:
            actual = pendientes.pop()
            if actual in alcanzados:
                continue
            alcanzados.add(actual)
            pendientes.extend(requiere.get(actual, ()))
        huerfanos = sorted(pines - alcanzados)
        if huerfanos:
            errores.append(
                f"{rel_lock}: {huerfanos} estan FIJADOS y no se alcanzan desde "
                f"{rel_in} ni por dependencia de nada declarado alli. El lock no "
                f"es reconstruible desde su fuente: quien lo regenere pierde "
                f"esos paquetes sin enterarse. Declaralos en {rel_in.name}."
            )
    return errores


# --------------------------------------------------------------------------
# 3. dependencias usadas y no declaradas
# --------------------------------------------------------------------------
def modulos_locales(raiz: Path) -> set[str]:
    """Todo lo importable como top-level desde ese arbol (primera parte)."""
    locales = set()
    for hijo in raiz.iterdir():
        if hijo.name in EXCLUIDOS:
            continue
        if hijo.is_dir():
            locales.add(hijo.name)
            # `viewer/` esta en sys.path, y `data-engine/app/` tambien: sus
            # subdirectorios son top-level en la corrida combinada.
            if hijo.name == "app":
                for nieto in hijo.iterdir():
                    if nieto.name not in EXCLUIDOS:
                        locales.add(nieto.stem)
        elif hijo.suffix == ".py":
            locales.add(hijo.stem)
    return locales


def check_undeclared() -> list[str]:
    import importlib.metadata as md

    errores = []
    mapa = md.packages_distributions()
    std = set(sys.stdlib_module_names)
    # Modulos locales de TODOS los arboles: la corrida combinada los mezcla.
    locales = set()
    for _e, raiz, _r in ARBOLES:
        locales |= modulos_locales(raiz)
    locales |= {p.stem for p in REPO.glob("*.py")}
    locales |= {d.name for d in REPO.iterdir() if d.is_dir() and d.name not in EXCLUIDOS}

    for etiqueta, raiz, req in ARBOLES:
        rel = req.relative_to(REPO)
        declarados = {n for n, _s, _c in lee_requisitos(req)}
        usados: dict[str, set[str]] = {}
        for py in ficheros_py(raiz):
            # Los tests pueden usar utillaje que no es dependencia de runtime
            # (playwright se instala aparte en su job), asi que se excluyen.
            if "tests" in py.parts:
                continue
            try:
                arbol = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.Import):
                    for alias in nodo.names:
                        usados.setdefault(alias.name.split(".")[0], set()).add(
                            py.relative_to(REPO).as_posix()
                        )
                elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
                    usados.setdefault(nodo.module.split(".")[0], set()).add(
                        py.relative_to(REPO).as_posix()
                    )
        for modulo, donde in sorted(usados.items()):
            if modulo in std or modulo in locales:
                continue
            dists = mapa.get(modulo)
            if not dists:
                continue  # no instalado aqui: lo coge `check_versions`
            if any(normaliza(d) in declarados for d in dists):
                continue
            ejemplo = sorted(donde)[0]
            errores.append(
                f"{rel}: `{modulo}` (distribucion {sorted(dists)}) se IMPORTA en "
                f"{ejemplo} y NO esta declarado. Hoy funciona porque llega como "
                f"dependencia transitiva; el dia que el paquete intermedio deje "
                f"de traerlo, el fallo aparece en ejecucion, no aqui."
            )
    return errores


# --------------------------------------------------------------------------
# 3 bis. interprete desplegado vs interprete probado  (D6)
# --------------------------------------------------------------------------
def check_interprete() -> list[str]:
    """Nada debe desplegarse sobre un interprete que CI nunca ejercita.

    D6 (carril I): `preflight.sh` acepta Python 3.11+ y todo el CI corre solo
    3.13. Se SEÑALA (no bloquea) porque el minimo del preflight es una
    decision del carril de despliegue, no de este: cerrarlo es o bien subir el
    minimo, o bien anadir una matriz de versiones en CI.
    """
    avisos = []
    preflight = REPO / "deploy" / "scripts" / "preflight.sh"
    if not (preflight.exists() and CI.exists()):
        return avisos
    m = re.search(r"py_minor[^\n]*-ge\s+\"?(\d+)", preflight.read_text(encoding="utf-8"))
    if not m:
        return avisos
    minimo = (3, int(m.group(1)))
    probadas = {
        tuple(int(x) for x in v.split("."))
        for v in re.findall(r"python-version:\s*'?(\d+\.\d+)'?", CI.read_text(encoding="utf-8"))
    }
    if probadas and minimo < min(probadas):
        avisos.append(
            f"deploy/scripts/preflight.sh acepta Python {minimo[0]}.{minimo[1]}+ "
            f"y CI solo ejercita {sorted('.'.join(map(str, p)) for p in probadas)}: "
            f"se puede desplegar sobre un interprete que nunca se ha probado. "
            f"Se cierra subiendo el minimo del preflight o anadiendo esas "
            f"versiones a la matriz de CI."
        )
    return avisos


# --------------------------------------------------------------------------
# 3 ter. la documentacion no puede contradecir al lock  (D7)
# --------------------------------------------------------------------------
def check_docs_versiones() -> list[str]:
    """Toda version `paquete==X` escrita en docs/ debe coincidir con el lock."""
    avisos = []
    docs = REPO / "docs"
    if not docs.exists():
        return avisos
    fijadas = {}
    for _e, _r, req in ARBOLES:
        if req.suffix == ".lock":
            for nombre, spec, _c in lee_requisitos(req):
                m = re.match(r"^==\s*(\S+)$", spec)
                if m:
                    fijadas[nombre] = m.group(1)
    for md_ in docs.rglob("*.md"):
        texto = md_.read_text(encoding="utf-8", errors="replace")
        for nombre, version in re.findall(r"([A-Za-z0-9][A-Za-z0-9._-]*)==(\d[\w.]*)", texto):
            clave = normaliza(nombre)
            if clave in fijadas and fijadas[clave] != version:
                avisos.append(
                    f"{md_.relative_to(REPO)}: dice `{nombre}=={version}` y el "
                    f"lock fija `{fijadas[clave]}`. La documentacion ha derivado."
                )
    return sorted(set(avisos))


# --------------------------------------------------------------------------
# 4. runtimes externos
# --------------------------------------------------------------------------
def presente_chromium() -> tuple[bool, str]:
    """Chromium DE VERDAD: el binario que Playwright lanzaria."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        return False, f"playwright no importable ({exc})"
    try:
        with sync_playwright() as p:
            ruta = p.chromium.executable_path
    except Exception as exc:  # noqa: BLE001
        return False, f"playwright no arranca ({exc})"
    if not ruta or not os.path.exists(ruta):
        return False, f"el binario de chromium no existe en {ruta!r}"
    return True, ruta


def presente(runtime: str) -> tuple[bool, str]:
    if runtime == "chromium":
        return presente_chromium()
    conf = RUNTIMES.get(runtime)
    cmds = conf["cmds"] if conf else (runtime,)
    for cmd in cmds:
        ruta = shutil.which(cmd)
        if ruta:
            try:
                r = subprocess.run(
                    [ruta, "--version"], capture_output=True, text=True, timeout=30
                )
                return True, f"{ruta} ({r.stdout.strip() or r.stderr.strip()})"
            except (OSError, subprocess.SubprocessError) as exc:
                return False, f"{ruta} presente pero no ejecutable: {exc}"
    return False, f"no se encuentra ningun ejecutable de {runtime}"


def check_require(runtimes: list[str]) -> list[str]:
    errores = []
    for rt in runtimes:
        ok, detalle = presente(rt)
        if ok:
            print(f"OK: runtime `{rt}` presente: {detalle}")
        else:
            errores.append(
                f"RUNTIME AUSENTE `{rt}`: {detalle}. Sin el, las pruebas que lo "
                f"necesitan se auto-omiten y el job pasa en VERDE sin haber "
                f"comprobado nada. Aqui eso es un FALLO, no un skip."
            )
    return errores


def _lineas_dentro_de_funcion(cuerpo: str) -> set[int]:
    """Lineas que viven dentro de una funcion (no se ejecutan al importar)."""
    dentro: set[int] = set()
    try:
        arbol = ast.parse(cuerpo)
    except SyntaxError:
        return dentro
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fin = getattr(nodo, "end_lineno", nodo.lineno)
            dentro.update(range(nodo.lineno, fin + 1))
    return dentro


def _depende(cuerpo: str, patrones, solo_modulo: bool) -> bool:
    """Hay dependencia de runtime; con `solo_modulo`, solo si es al importar.

    La distincion importa: un `importorskip` a nivel de MODULO en un
    `conftest.py` omite el directorio ENTERO (el caso real de las 171 pruebas
    de `viewer/tests/browser`). El mismo `importorskip` dentro de una fixture
    solo afecta a los tests que la piden, y atribuirle el directorio entero
    seria una falsa alarma que obliga a un job que no comprueba nada.
    """
    dentro = _lineas_dentro_de_funcion(cuerpo) if solo_modulo else set()
    for patron in patrones:
        for m in patron.finditer(cuerpo):
            linea = cuerpo.count("\n", 0, m.start()) + 1
            if linea not in dentro:
                return True
    return False


def tests_por_runtime() -> dict[str, list[str]]:
    """Deriva del arbol que ficheros de test dependen de que runtime."""
    fuera: dict[str, list[str]] = {rt: [] for rt in PATRONES_RUNTIME}
    for py in REPO.rglob("test_*.py"):
        if any(p in EXCLUIDOS for p in py.parts):
            continue
        cuerpo = py.read_text(encoding="utf-8", errors="replace")
        for rt, patrones in PATRONES_RUNTIME.items():
            if _depende(cuerpo, patrones, solo_modulo=False):
                fuera[rt].append(py.relative_to(REPO).as_posix())
    # `conftest.py` puede omitir un directorio ENTERO: se atribuye a todos los
    # tests que cuelgan de el, pero SOLO si la omision ocurre al importar.
    for conf in REPO.rglob("conftest.py"):
        if any(p in EXCLUIDOS for p in conf.parts):
            continue
        cuerpo = conf.read_text(encoding="utf-8", errors="replace")
        for rt, patrones in PATRONES_RUNTIME.items():
            if _depende(cuerpo, patrones, solo_modulo=True):
                for py in conf.parent.rglob("test_*.py"):
                    rel = py.relative_to(REPO).as_posix()
                    if rel not in fuera[rt]:
                        fuera[rt].append(rel)
    return {k: sorted(v) for k, v in fuera.items()}


def jobs_de(ci: str) -> dict[str, str]:
    """Parte `ci.yml` en bloques por job (clave con dos espacios de sangria)."""
    encabezados = [
        (m.start(), m.group(1))
        for m in re.finditer(r"^  ([A-Za-z0-9_-]+):\s*$", ci, re.M)
    ]
    fuera = {}
    for i, (pos, nombre) in enumerate(encabezados):
        fin = encabezados[i + 1][0] if i + 1 < len(encabezados) else len(ci)
        fuera[nombre] = ci[pos:fin]
    return fuera


def objetivos_pytest(bloque: str) -> list[str]:
    """Rutas que ese job pasa a pytest, resueltas desde la raiz del repo.

    Los jobs hacen `cd viewer` y luego `pytest tests/browser`, asi que un
    objetivo se resuelve tanto desde la raiz como desde cada directorio de
    primer nivel. Devuelve prefijos; la cobertura se decide por prefijo de
    ruta, NO por que el nombre del directorio aparezca suelto en el fichero
    —esa comparacion laxa daba por cubierto cualquier test cuya carpeta se
    llamara `tests`, que es precisamente como una suite entera se omitia en
    verde—.
    """
    raices = [""] + [
        d.name + "/" for d in REPO.iterdir() if d.is_dir() and d.name not in EXCLUIDOS
    ]
    objetivos = []
    for m in re.finditer(r"pytest\s+([^\n|&;]*)", bloque):
        for token in m.group(1).split():
            if token.startswith("-") or "=" in token or token.startswith("$"):
                continue
            if not ("/" in token or token.endswith(".py")):
                continue
            token = token.strip("\"'")
            for raiz in raices:
                objetivos.append((raiz + token).lstrip("./"))
    return objetivos


def cubierto_por(fichero: str, objetivos: list[str]) -> bool:
    for obj in objetivos:
        obj = obj.rstrip("/")
        if fichero == obj or fichero.startswith(obj + "/"):
            return True
    return False


def check_runtime_gates() -> list[str]:
    errores = []
    if not CI.exists():
        return [f"{CI.relative_to(REPO)} no existe: no se puede comprobar nada"]
    ci = CI.read_text(encoding="utf-8")
    jobs = jobs_de(ci)
    mapa = tests_por_runtime()
    for rt, ficheros in mapa.items():
        if not ficheros:
            continue
        print(f"-- runtime `{rt}`: {len(ficheros)} fichero(s) de test dependen de el")
        pistas = RUNTIMES.get(rt, {}).get("provision", ())
        # Los jobs que APROVISIONAN el runtime. Todo lo demas se exige DENTRO
        # de uno de ellos: un job que instala Node y otro distinto que ejecuta
        # el test no protegen nada, porque el que ejecuta no tiene Node.
        candidatos = {n: b for n, b in jobs.items() if any(p in b for p in pistas)}
        if not candidatos:
            errores.append(
                f"runtime `{rt}`: {len(ficheros)} fichero(s) de test se omiten si "
                f"falta ({ficheros[:3]}...) y NINGUN job de ci.yml lo aprovisiona "
                f"({' o '.join(pistas)}). Esas pruebas se saltarian en verde."
            )
            continue
        for fichero in ficheros:
            ejecutores = {
                n: b
                for n, b in candidatos.items()
                if cubierto_por(fichero, objetivos_pytest(b))
            }
            if not ejecutores:
                errores.append(
                    f"runtime `{rt}`: `{fichero}` se auto-omite sin {rt} y NINGUN "
                    f"job que aprovisione {rt} lo ejecuta ({sorted(candidatos)} no "
                    f"lo tienen entre sus objetivos de pytest). Solo corre en la "
                    f"suite general, donde no hay {rt}: se OMITE en verde."
                )
                continue
            if not any("skipped" in b for b in ejecutores.values()):
                errores.append(
                    f"runtime `{rt}`: `{fichero}` se ejecuta en {sorted(ejecutores)} "
                    f"pero ese job no inspecciona la salida de pytest en busca de "
                    f"`skipped`. Sin guardia antisalto, una omision silenciosa "
                    f"vuelve a leerse como verde."
                )
            if not any(
                re.search(rf"--require[^\n]*{re.escape(rt)}", b) for b in ejecutores.values()
            ):
                errores.append(
                    f"runtime `{rt}`: `{fichero}` se ejecuta en {sorted(ejecutores)} "
                    f"pero ese job no invoca `check_env_reproducibility.py runtimes "
                    f"--require {rt}`, que es lo que convierte la ausencia en fallo "
                    f"ruidoso ANTES de que pytest tenga ocasion de omitir nada."
                )
    return errores


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="modo")

    p_all = sub.add_parser("all", help="todas las comprobaciones estaticas")
    p_all.add_argument(
        "--strict-missing",
        action="store_true",
        help="una dependencia declarada y no instalada es FALLO (usar en CI, "
        "despues de instalar los requirements)",
    )
    p_all.add_argument(
        "--strict-pinning",
        action="store_true",
        help="las dependencias sin fijar dejan de ser aviso y son FALLO",
    )

    p_rt = sub.add_parser("runtimes", help="presencia de runtimes externos AHORA")
    p_rt.add_argument("--require", required=True, help="lista separada por comas")

    args = ap.parse_args()
    if args.modo is None:
        ap.print_help()
        return 2

    errores: list[str] = []
    avisos: list[str] = []

    if args.modo == "runtimes":
        errores = check_require([r.strip() for r in args.require.split(",") if r.strip()])
    else:
        print("=== 1. versiones declaradas vs instaladas ===")
        errores += check_versions(args.strict_missing)
        print("=== 2. fijacion de versiones ===")
        e, a = check_pinning()
        errores += e
        if args.strict_pinning:
            errores += a
        else:
            avisos += a
        print("=== 2 bis. el .lock es reconstruible desde el .in ===")
        errores += check_lock_reconstruible()
        print("=== 3. dependencias usadas y no declaradas ===")
        errores += check_undeclared()
        print("=== 3 bis/ter. interprete desplegado y deriva de documentacion ===")
        avisos += check_interprete()
        avisos += check_docs_versiones()
        print("=== 4. puertas de runtime externo (Node, Chromium) ===")
        errores += check_runtime_gates()

    for a in avisos:
        print(f"::warning::SENALADO: {a}")
    for e in errores:
        print(f"::error::{e}")
    if errores:
        if args.modo == "runtimes":
            print(f"\nFALLO: {len(errores)} runtime(s) externo(s) AUSENTE(S)")
        else:
            print(
                f"\nFALLO: {len(errores)} divergencia(s) entre lo declarado y lo ejecutado"
            )
        return 1
    if args.modo == "runtimes":
        print("\nOK: todos los runtimes exigidos estan presentes")
    elif avisos:
        print(f"\nOK con {len(avisos)} aviso(s) de fijacion")
    else:
        print("\nOK: lo declarado coincide con lo instalado y los runtimes tienen puerta")
    return 0


if __name__ == "__main__":
    sys.exit(main())
