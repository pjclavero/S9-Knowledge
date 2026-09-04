#!/usr/bin/env python3
"""Calibracion de la propiedad "el binario que certifica NO se puede desarmar".

QUE SE DEMUESTRA
================
Durante cuatro rondas el desarme se protegio RECONOCIENDO quien pedia la
concesion: primero buscando los nombres en `ci.yml` (se atraveso partiendo el
nombre en comillas, luego repartiendolo entre lineas) y despues exigiendo que un
`calibra_*.py` real fuera ANTECESOR del proceso. Esta ultima se falsifico en una
linea:

    bash -c 'exec -a ".github/scripts/calibra_registro_xfail.py" \
             /usr/bin/python3 /tmp/impostor.py'     -> EXIT=0, desarme concedido

`argv` es TEXTO QUE EL PROCESO ELIGE: el nombre que ve el arbol de procesos no
prueba que ese fichero se haya ejecutado. Y por debajo habia algo peor: todo lo
que puede hacer un arnes lo puede hacer un paso de `ci.yml` —un secreto
efimero, un fichero 0600, un descriptor heredado—, asi que NINGUN apreton de
manos habria sido una frontera.

Asi que se quito LA ENTRADA. Los gates ya no leen ninguna variable de desarme, y
su ablacion es una variable de MODULO que solo toca quien los IMPORTA. Lo que
aqui se calibra es esa propiedad, en las dos direcciones:

  1. AST: ningun gate lee una variable de desarme del entorno.
  2. Con las CUATRO variables puestas y la ascendencia FABRICADA, el gate
     certifica igual: aplica los trinquetes, sin ablacion y sin saltarse la
     integridad del registro.
  3. `--sin-base` desde la linea de comandos -> ROJO (no certifica nada).
  4. `--base-fichero` desde la linea de comandos -> ROJO.
  5. `--solo-registro` desde la linea de comandos -> ROJO (capa de resultados).
  6. CONTROL POSITIVO: el arnes SI puede ablacionar. Si esto saliera verde, el
     arreglo habria roto la calibracion entera, que es la otra forma de fallar.

NO MUTA NINGUN FICHERO DEL REPOSITORIO.
"""
from __future__ import annotations

import ast
import hashlib
import os
import re
import shutil
import tempfile
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / ".github" / "scripts"
GATE = SCRIPTS / "check_suite_inventory.py"
CONTROL = SCRIPTS / "check_ejecucion_real.py"
INVENTARIO = REPO / ".github" / "suite-inventario.json"

sys.path.insert(0, str(SCRIPTS))
import arnes_comun  # noqa: E402

VIGILADOS = (GATE, CONTROL, SCRIPTS / "registro_xfail.py",
             SCRIPTS / "normaliza_shell.py")

DESARMES = ("S9K_INVENTARIO_ABLACION", "S9K_EJECUCION_ABLACION",
            "S9K_REGISTRO_MUTADO", "S9K_MIDIENDO_BASE")


def sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def lee_entorno_de_desarme(ruta: Path) -> list[str]:
    """Por AST: `os.environ[...]`/`os.environ.get(...)` con un nombre de desarme.

    No es un `grep`: se mira el ARBOL, asi que una mencion en un comentario o en
    un mensaje de error no cuenta -y estos ficheros estan llenos de ellas,
    porque documentan la historia de como se cerro esto-.
    """
    hallazgos = []
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        cadenas = []
        if isinstance(nodo, ast.Call):
            fn = nodo.func
            if isinstance(fn, ast.Attribute) and fn.attr in ("get", "getenv"):
                base = fn.value
                nombre_base = getattr(base, "id", None) or getattr(base, "attr", None)
                if nombre_base in ("environ", "os"):
                    cadenas = [a.value for a in nodo.args
                               if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        elif isinstance(nodo, ast.Subscript):
            base = nodo.value
            if getattr(base, "attr", None) == "environ":
                s = nodo.slice
                if isinstance(s, ast.Constant) and isinstance(s.value, str):
                    cadenas = [s.value]
        for c in cadenas:
            if c in DESARMES:
                hallazgos.append(f"{ruta.name}:{nodo.lineno}: lee `{c}` del entorno")
    return hallazgos


def con_ascendencia_fabricada(programa: str) -> tuple[int, str]:
    """Ejecuta `programa` mintiendo en `argv[0]` como hizo el revisor."""
    guion = Path("/tmp/s9k-impostor-calibra.py")
    guion.write_text(programa, encoding="utf-8")
    try:
        p = subprocess.run(
            ["bash", "-c",
             'exec -a ".github/scripts/calibra_registro_xfail.py" '
             f'{sys.executable} {guion}'],
            cwd=REPO, capture_output=True, text=True, timeout=3600)
        return p.returncode, p.stdout + p.stderr
    finally:
        guion.unlink(missing_ok=True)


def user_site() -> Path:
    p = subprocess.run([sys.executable, "-m", "site", "--user-site"],
                       capture_output=True, text=True, timeout=120)
    return Path(p.stdout.strip())


VENENO = (
    "import sys\n"
    "sys.path.insert(0, {scripts!r})\n"
    "try:\n"
    "    import registro_xfail\n"
    "    registro_xfail.MUTADO = True\n"
    "    registro_xfail.MIDIENDO = True\n"
    "except Exception:\n"
    "    pass\n"
)

VENENO_OTRA_PROPIEDAD = (
    "import sys\n"
    "sys.path.insert(0, {scripts!r})\n"
    "try:\n"
    "    import check_suite_inventory\n"
    "    check_suite_inventory.ABLACION = 'A'\n"
    "except Exception:\n"
    "    pass\n"
)


def con_arranque_contaminado(script: Path, destino: Path, nombre: str,
                             plantilla: str = VENENO,
                             extra: list[str] | None = None
                             ) -> tuple[int, str, bool]:
    """Monta un arranque automatico de Python y ejecuta el gate.

    `destino` es el directorio (el *user site*, fuera del repo, o el propio
    repo) y `nombre` el fichero (`usercustomize.py` o `sitecustomize.py`).
    Python los importa AL ARRANCAR EL INTERPRETE, antes que el codigo del gate.

    Devuelve tambien si el veneno LLEGO de verdad: si no llegara, el caso no
    demostraria nada y darlo por bueno seria mentir. Es la leccion de los dos
    falsos hallazgos que hubo que descartar en esta ronda —uno ocultaba PyYAML
    y ponia el gate rojo por otra causa—: un rojo por accidente NO es una
    deteccion.
    """
    fichero = destino / nombre
    previo = fichero.read_bytes() if fichero.exists() else None
    try:
        destino.mkdir(parents=True, exist_ok=True)
        fichero.write_text(plantilla.format(scripts=str(SCRIPTS)),
                           encoding="utf-8")
    except OSError as e:
        return -1, f"MUTACION IMPOSIBLE: no se pudo escribir {fichero} ({e})", False
    try:
        sonda = subprocess.run(
            [sys.executable, "-c",
             "import registro_xfail as r, check_suite_inventory as c; "
             "print(r.MUTADO or c.ABLACION != '')"],
            cwd=REPO, capture_output=True, text=True, timeout=300)
        llega = sonda.stdout.strip() in ("True", "A")
        p = subprocess.run([sys.executable, str(script), *(extra or [])],
                           cwd=REPO, capture_output=True, text=True, timeout=3600)
        return p.returncode, p.stdout + p.stderr, llega
    finally:
        if previo is None:
            fichero.unlink(missing_ok=True)
        else:
            fichero.write_bytes(previo)
        subprocess.run(["rm", "-rf", str(destino / "__pycache__")], timeout=60)


ASERCION = ("    alterado = estado_de_fabrica.comprueba()\n"
            "    for e in alterado:\n"
            '        print(f"::error::{e}")\n'
            "    if alterado:\n"
            "        return 1\n")


def sin_la_asercion(script: Path):
    """Retira LA ASERCION de estado inicial del gate. Devuelve los bytes previos.

    No hay bandera de ablacion en el producto: seria una perilla mas que
    defender, y ya se vio adonde lleva. La ablacion se hace quitando el codigo,
    y el que llama restaura los BYTES EXACTOS y lo verifica por SHA-256.
    """
    previo = script.read_bytes()
    texto = previo.decode("utf-8")
    if ASERCION not in texto:
        raise SystemExit("MUTACION IMPOSIBLE: no esta la asercion que ablacionar")
    script.write_text(texto.replace(ASERCION, "", 1), encoding="utf-8")
    return previo


REGISTRO_PY = SCRIPTS / "registro_xfail.py"

MUTACION_INTERNA = "\n# INYECTADO POR LA CALIBRACION\nMUTADO = True\n"


def con_mutacion_desde_dentro(script: Path, extra=None, aislado=False):
    """La MISMA contaminacion, pero escrita DENTRO del repositorio.

    No hace falta ningun arranque automatico: se altera el propio
    `registro_xfail.py`, que es codigo del repo que el gate importa siempre. El
    estado protegido queda igual de sucio, asi que el gate tiene que abortar por
    el MISMO motivo. Sirve ademas para demostrar que endurecer la invocacion
    (`-s`) NO cubre esta via: el fichero no vive en el *user site*.

    Restaura los BYTES exactos y el que llama lo verifica por SHA-256.
    """
    previo = REGISTRO_PY.read_bytes()
    try:
        REGISTRO_PY.write_bytes(previo + MUTACION_INTERNA.encode("utf-8"))
        sonda = subprocess.run(
            [sys.executable] + (["-s"] if aislado else []) +
            ["-c", "import sys; sys.path.insert(0, %r); "
                   "import registro_xfail as r; print(r.MUTADO)" % str(SCRIPTS)],
            cwd=REPO, capture_output=True, text=True, timeout=300)
        llega = sonda.stdout.strip() == "True"
        p = subprocess.run([sys.executable, str(script), *(extra or [])],
                           cwd=REPO, capture_output=True, text=True, timeout=3600)
        return p.returncode, p.stdout + p.stderr, llega
    finally:
        REGISTRO_PY.write_bytes(previo)
        subprocess.run(["rm", "-rf", str(SCRIPTS / "__pycache__")], timeout=60)


def arranque_externo_se_ejecuta(aislado: bool) -> bool:
    """¿Corre el arranque automatico del *user site*? Sonda minima.

    Se mide con un fichero testigo, sin meter al gate de por medio: asi la
    respuesta no depende de si el gate tiene sus dependencias, que es donde se
    fabricaron dos falsos hallazgos en esta ronda.
    """
    destino = user_site()
    fichero = destino / "usercustomize.py"
    testigo = Path("/tmp/s9k-testigo-arranque")
    previo = fichero.read_bytes() if fichero.exists() else None
    testigo.unlink(missing_ok=True)
    try:
        destino.mkdir(parents=True, exist_ok=True)
        fichero.write_text(
            "from pathlib import Path\n"
            f"Path({str(testigo)!r}).write_text('si')\n", encoding="utf-8")
        subprocess.run([sys.executable] + (["-s"] if aislado else []) +
                       ["-c", "pass"], capture_output=True, timeout=300)
        return testigo.exists()
    finally:
        if previo is None:
            fichero.unlink(missing_ok=True)
        else:
            fichero.write_bytes(previo)
        subprocess.run(["rm", "-rf", str(destino / "__pycache__")], timeout=60)
        testigo.unlink(missing_ok=True)


BOOTSTRAP = SCRIPTS / "bootstrap_certificacion.py"
CENTINELA = Path("/tmp/s9k-centinela-payload")

# Cada payload deja CENTINELA si LLEGA A EJECUTARSE. Es lo que permite
# distinguir "bloqueado por la frontera de ejecucion" -resultado correcto- de
# "ejecutado y no detectado" -falso verde-.
# El centinela APUNTA EL `argv` de cada proceso que ejecuta el payload, no un
# simple "si/no". La primera version escribia "ejecutado" a secas y me llevo a
# una conclusion falsa: el fichero aparecia porque el payload corria en los
# SUBPROCESOS DE MEDICION que lanza el gate (la coleccion de pytest), no en la
# ruta de certificacion. "Algun interprete lo ejecuto" y "alcanzo lo que
# certifica" no son la misma afirmacion.
PAYLOAD_BANDERA = '''
from pathlib import Path
import sys
with open({centinela!r}, "a") as _f:
    _f.write(repr(sys.argv) + chr(10))
import sys
sys.path.insert(0, {scripts!r})
try:
    import registro_xfail
    registro_xfail.MUTADO = True
except Exception:
    pass
'''

PAYLOAD_FUNCION = '''
from pathlib import Path
import sys
with open({centinela!r}, "a") as _f:
    _f.write(repr(sys.argv) + chr(10))
import builtins, sys
sys.path.insert(0, {scripts!r})
_real = builtins.__import__
def _mio(nombre, *a, **k):
    mod = _real(nombre, *a, **k)
    if nombre == "registro_xfail":
        def _sin_integridad():
            return (mod.FICHERO.read_text(encoding="utf-8")
                    if mod.FICHERO.exists() else ""), []
        mod.contenido_verificado = _sin_integridad
    return mod
builtins.__import__ = _mio
'''


SUITE_CRITICA = REPO / "viewer" / "tests" / "test_parcialidad_declarada.py"
REGISTRO_TXT = REPO / ".github" / "xfail-registro.txt"


# `[ \t]`, NO `\s`: `\s` incluye el salto de linea y se comia el final de
# la linea, pegando la siguiente. Medido: la ablacion producia
# `problemas = ... + sin_precarga()     for e in problemas:`.
def _re_termino(nombre: str):
    return re.compile(r"[ \t]*\+?[ \t]*" + nombre + r"\(sha\)[ \t]*\+?")


def neutraliza_verificacion(texto: str, terminos=("verifica_fuente",)) -> str:
    """Quita el termino `verifica_fuente(sha)` de la linea que lo compone.

    Se DERIVA con una expresion en vez de anclarse a la linea literal: la
    anterior se rompio en cuanto la llamada gano otro termino
    (`soy_el_objeto_git(sha) + ...`) y el caso murio con `MUTACION IMPOSIBLE`.
    El arnes hizo bien en negarse -mejor eso que pasar- pero un ancla que se
    rompe cada vez que se toca la linea no es un ancla.
    """
    lineas = texto.splitlines(keepends=True)
    for i, linea in enumerate(lineas):
        if "problemas =" in linea and "verifica_fuente(sha)" in linea:
            nueva = linea
            for nombre in terminos:
                nueva = _re_termino(nombre).sub(" ", nueva)
            nueva = nueva.replace("=  ", "= ").replace("  +", " +")
            if nueva.split("=", 1)[1].strip() in ("", "+"):
                nueva = linea.split("problemas =")[0] + "problemas = []\n"
            lineas[i] = nueva
            return "".join(lineas)
    raise SystemExit("MUTACION IMPOSIBLE: no se encuentra la composicion de "
                     "`problemas` con `verifica_fuente(sha)`")


def sujeto_actual() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                          capture_output=True, text=True,
                          timeout=120).stdout.strip()


RUTA_BOOTSTRAP = ".github/scripts/bootstrap_certificacion.py"
MOTIVO_MATERIALIZACION = "RAIZ NO MATERIALIZADA"


def _config_local_sha() -> str:
    """Huella de la configuracion LOCAL del repositorio real."""
    p = subprocess.run(["git", "config", "--local", "--list"], cwd=REPO,
                       capture_output=True, text=True, timeout=120)
    return hashlib.sha256(p.stdout.encode("utf-8")).hexdigest()


def calibra_filtros_hostiles(gate_rel: str) -> list[tuple]:
    """Los filtros `clean` de Git pueden MENTIR sobre el hash de un fichero.

    `git hash-object` SIN `--no-filters` no devuelve el hash de los bytes del
    fichero: devuelve el del resultado de pasarlos por el filtro `clean` que
    diga la configuracion (`core.attributesFile` + `filter.<x>.clean`). O sea
    la comparacion de materializacion se podia satisfacer con un fichero VACIO,
    y entonces `python3 -I` volveria a no ejecutar nada saliendo en verde: el
    mismo falso verde otra vez, ahora a traves del instrumento de medida.

    Todo esto se monta en un REPOSITORIO DE PRUEBA AISLADO en un temporal: en
    el repositorio real no se toca `core.attributesFile` ni ningun filtro, y se
    comprueba por huella de `git config --local --list` que sigue igual.
    """
    antes = _config_local_sha()
    base = Path(tempfile.mkdtemp(prefix="raiz-filtros-"))
    filas = []
    try:
        repo = base / "repo"
        (repo / ".github" / "scripts").mkdir(parents=True)
        contenido = subprocess.run(
            ["git", "show", f"{sujeto_actual()}:{RUTA_BOOTSTRAP}"], cwd=REPO,
            capture_output=True, text=True, timeout=300).stdout
        (repo / RUTA_BOOTSTRAP).write_text(contenido, encoding="utf-8")
        for cmd in (["init", "-q", "."], ["config", "user.email", "calibracion@local"],
                    ["config", "user.name", "calibracion"],
                    ["add", RUTA_BOOTSTRAP], ["commit", "-qm", "raiz"]):
            subprocess.run(["git"] + cmd, cwd=repo, capture_output=True,
                           text=True, timeout=300, check=True)
        sujeto = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                                capture_output=True, text=True,
                                timeout=120).stdout.strip()
        objeto = f"{sujeto}:{RUTA_BOOTSTRAP}"

        legitima = base / "legitima.py"
        legitima.write_text(contenido, encoding="utf-8")
        vacia = base / "vacia.py"
        vacia.write_bytes(b"")

        def envenena():
            attrs = base / "attrs"
            attrs.write_text("* filter=veneno\n", encoding="utf-8")
            subprocess.run(["git", "config", "core.attributesFile", str(attrs)],
                           cwd=repo, check=True, timeout=120)
            subprocess.run(["git", "config", "filter.veneno.clean",
                            f"cat {legitima}"], cwd=repo, check=True, timeout=120)

        def compara(raiz: Path, no_filters: bool) -> tuple[int, str]:
            cuerpo = (f'set -eu\nRAIZ="{raiz}"\n'
                      + control_materializacion(objeto, no_filters))
            p = subprocess.run(["bash", "-c", cuerpo], cwd=repo,
                               capture_output=True, text=True, timeout=300)
            return p.returncode, p.stdout + p.stderr

        rc1, _ = compara(legitima, True)
        filas.append(("N1 configuracion normal (sin filtros) -> PASS",
                      "PASS: los bytes correctos coinciden",
                      f"EXIT={rc1}", rc1 == 0))

        envenena()
        rc2, _ = compara(vacia, False)
        filas.append(("N2 filtro Git hostil + `hash-object` SIN `--no-filters`",
                      "FALSO PASS reproducido (un fichero VACIO coincide)",
                      f"EXIT={rc2} con la raiz VACIA", rc2 == 0))

        rc3, sal3 = compara(vacia, True)
        motivo3 = MOTIVO_MATERIALIZACION in sal3
        filas.append(("N3 el MISMO ataque + `--no-filters`",
                      f"ROJO por `{MOTIVO_MATERIALIZACION}`",
                      f"EXIT={rc3}, motivo={motivo3}", rc3 == 1 and motivo3))

        rc4, _ = compara(legitima, True)
        filas.append(("N4 caso legitimo + `--no-filters` (con el filtro puesto)",
                      "PASS: la bandera no rompe el caso bueno",
                      f"EXIT={rc4}", rc4 == 0))
    finally:
        shutil.rmtree(base, ignore_errors=True)
    despues = _config_local_sha()
    hostil = subprocess.run(["git", "config", "--get", "core.attributesFile"],
                            cwd=REPO, capture_output=True, text=True,
                            timeout=120).stdout.strip()
    filas.append(("N restauracion: el repositorio REAL sin tocar",
                  "misma huella de `git config --local --list`, sin "
                  "`core.attributesFile`",
                  f"huella igual={antes == despues}, "
                  f"core.attributesFile={hostil or 'ausente'}",
                  antes == despues and not hostil))
    return filas


def control_materializacion(objeto: str, no_filters: bool = True) -> str:
    """La comparacion de identidad Git, generada en UN solo sitio.

    `--no-filters` es la parte que hace que la comparacion signifique algo: sin
    ella `git hash-object` aplica el filtro `clean` que diga la configuracion,
    y entonces el hash no describe los BYTES del fichero sino la salida de un
    programa que el atacante elige. `no_filters=False` existe solo para que la
    fila N2 pueda REPRODUCIR el bypass y demostrar que la bandera es lo que lo
    mata.
    """
    bandera = " --no-filters" if no_filters else ""
    return (f'ESPERADO="$(git rev-parse "{objeto}")"\n'
            f'OBTENIDO="$(git hash-object{bandera} "$RAIZ")"\n'
            'if [ "$OBTENIDO" != "$ESPERADO" ]; then\n'
            f'  echo "::error::{MOTIVO_MATERIALIZACION}: $OBTENIDO no es $ESPERADO"\n'
            '  exit 1\n'
            'fi\n')


def cuerpo_embarcado(objeto: str, gate_rel: str, trunca: int | None = None,
                     verifica: bool = True) -> str:
    """La MISMA construccion que `ci.yml`, generada en UN solo sitio.

    Se genera aqui y se COMPARA contra `ci.yml` (fila M0): si el arnes midiera
    una construccion distinta de la que corre en CI, todas las filas M1-M7
    hablarian de otra cosa. `trunca` deja la raiz materializada en N bytes
    -0 = vacia- y `verifica` ABLACIONA la comprobacion de materializacion.
    """
    sabotaje = f'truncate -s {trunca} "$RAIZ"\n' if trunca is not None else ""
    control = control_materializacion(objeto) if verifica else ""
    return ('set -eu\n'
            'umask 077\n'
            'RAIZ="$(mktemp)"\n'
            'trap \'rm -f "$RAIZ"\' EXIT\n'
            f'git show "{objeto}" > "$RAIZ"\n'
            + sabotaje + control +
            f'python3 -I "$RAIZ" --sujeto "$SUJETO" {gate_rel}\n')


def _canon(cuerpo: str, objeto: str) -> list[str]:
    """Forma comparable: sin comentarios, sin los valores que solo son datos."""
    unidas, acc = [], ""
    for linea in cuerpo.splitlines():
        acc += linea.split("#", 1)[0].strip() if not acc else " " + linea.strip()
        if acc.endswith("\\"):
            acc = acc[:-1].strip()
            continue
        unidas.append(acc)
        acc = ""
    if acc:
        unidas.append(acc)
    fuera = []
    for l in unidas:
        l = " ".join(l.split())
        if not l or l.startswith("#"):
            continue
        if l.startswith("SUJETO=") or l.startswith("RUTA_RAIZ="):
            continue
        l = l.replace("set -euo pipefail", "set -eu")
        l = l.replace('"$SUJETO:$RUTA_RAIZ"', '"OBJ"').replace(f'"{objeto}"', '"OBJ"')
        if l.startswith("echo") and MOTIVO_MATERIALIZACION in l:
            l = f"echo {MOTIVO_MATERIALIZACION}"
        if l.startswith("python3 -I"):
            l = 'python3 -I "$RAIZ" --sujeto "$SUJETO" GATE'
        fuera.append(l)
    return fuera


def pasos_de_certificacion_de_ci() -> list[tuple[str, str]]:
    """Los pasos de `ci.yml` que materializan la raiz. Falla cerrado."""
    import yaml  # dependencia ya exigida por `check_ci_config`
    datos = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml")
                           .read_text(encoding="utf-8"))
    fuera = []
    for job in (datos.get("jobs") or {}).values():
        for paso in job.get("steps", []) or []:
            cuerpo = paso.get("run") or ""
            if 'RAIZ="$(mktemp)"' in cuerpo:
                fuera.append((paso.get("name", "?"), cuerpo))
    return fuera


def corre_certificacion_desde_git(gate: Path, extra=None):
    """La cadena EXACTA que corre en CI, con el SHA SUJETO explicito.

        SHA sujeto -> objeto Git <SHA>:<bootstrap> -> bootstrap limpio ->
        verificacion del codigo critico -> gate

    El codigo de la raiz sale de `git show`, no del fichero del working tree, y
    el sujeto se PASA para que el codigo que se ejecuta y el commit contra el
    que se verifica sean el mismo.
    """
    sujeto = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                            capture_output=True, text=True, timeout=120).stdout.strip()
    fuente = subprocess.run(
        ["git", "show", f"{sujeto}:.github/scripts/bootstrap_certificacion.py"],
        cwd=REPO, capture_output=True, text=True, timeout=300)
    if fuente.returncode != 0:
        return -1, f"MUTACION IMPOSIBLE: `git show` fallo ({fuente.stderr[:100]})"
    p = subprocess.run(
        [sys.executable, "-I", "-", "--sujeto", sujeto, str(gate), *(extra or [])],
        cwd=REPO, input=fuente.stdout, capture_output=True, text=True, timeout=3600)
    return p.returncode, p.stdout + p.stderr


def corre_bootstrap(gate: Path, extra=None, aislado=True):
    orden = [sys.executable] + (["-I"] if aislado else [])
    orden += [str(BOOTSTRAP), str(gate), *(extra or [])]
    p = subprocess.run(orden, cwd=REPO, capture_output=True, text=True,
                       timeout=3600)
    return p.returncode, p.stdout + p.stderr


def con_payload(nombre_fichero: str, plantilla: str, gate: Path,
                extra=None, aislado: bool = True):
    """Monta el payload en el *user site*, corre el bootstrap y mira el centinela.

    Devuelve (rc, salida, ejecutado). `ejecutado` es la prueba de si el payload
    llego a correr: si NO corrio, un PASS es el resultado CORRECTO -la
    contaminacion quedo excluida por la frontera de ejecucion- y hay que
    demostrarlo, no suponerlo.
    """
    destino = user_site()
    fichero = destino / nombre_fichero
    previo = fichero.read_bytes() if fichero.exists() else None
    CENTINELA.unlink(missing_ok=True)
    try:
        destino.mkdir(parents=True, exist_ok=True)
        fichero.write_text(
            plantilla.format(centinela=str(CENTINELA), scripts=str(SCRIPTS)),
            encoding="utf-8")
        rc, salida = corre_bootstrap(gate, extra, aislado)
        huellas = (CENTINELA.read_text(encoding="utf-8").splitlines()
                   if CENTINELA.exists() else [])
        return rc, salida, huellas
    finally:
        if previo is None:
            fichero.unlink(missing_ok=True)
        else:
            fichero.write_bytes(previo)
        subprocess.run(["rm", "-rf", str(destino / "__pycache__")], timeout=60)
        CENTINELA.unlink(missing_ok=True)


def desde_linea_de_comandos(script: Path, extra: list[str]) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(script), *extra], cwd=REPO,
                       capture_output=True, text=True, timeout=3600)
    return p.returncode, p.stdout + p.stderr


def main() -> int:
    hashes = {f: sha(f) for f in VIGILADOS}
    print("SHA-256 ANTES (este arnes NO toca ninguno):")
    for f, h in hashes.items():
        print(f"  {h}  {f.relative_to(REPO)}")

    filas, fallos = [], 0

    def anota(titulo, esperado, obtenido, ok):
        nonlocal fallos
        fallos += 0 if ok else 1
        filas.append((titulo, esperado, obtenido, "OK" if ok else "**DESVIACION**"))
        print(f"  -> {obtenido}  [{'OK' if ok else 'DESVIACION'}]")

    # --- 1. AST: los gates no leen desarme del entorno --------------------
    print("\n########## 1. ningun gate lee una variable de desarme del entorno")
    lecturas = []
    for f in VIGILADOS:
        lecturas += lee_entorno_de_desarme(f)
    print("\n".join(f"    {x}" for x in lecturas) or "    (ninguna)")
    anota("1 los gates no leen desarme del entorno (AST)", "0 lecturas",
          f"{len(lecturas)} lecturas", not lecturas)

    # --- 2. entorno + ascendencia fabricada: el gate certifica igual ------
    print("\n########## 2. cuatro variables puestas + ascendencia FABRICADA")
    programa = (
        "import os, subprocess\n"
        "e = dict(os.environ)\n"
        + "".join(f"e[{v!r}] = 'A'\n" for v in DESARMES) +
        f"p = subprocess.run([{sys.executable!r}, {str(GATE)!r}],\n"
        "                   capture_output=True, text=True, env=e,\n"
        f"                   cwd={str(REPO)!r})\n"
        "s = p.stdout + p.stderr\n"
        "print('RC=%d' % p.returncode)\n"
        "print('TRINQUETES=%s' % ('SI' if 'MATERIALIZADA y medida en el sitio' in s else 'NO'))\n"
        "print('ABLACION=%s' % ('SI' if 'ABLACION ACTIVA' in s else 'NO'))\n"
        "print('INTEGRIDAD_SALTADA=%s' % ('SI' if 'integridad NO' in s else 'NO'))\n"
    )
    rc, salida = con_ascendencia_fabricada(programa)
    certifica = "TRINQUETES=SI" in salida
    sin_ablacion = "ABLACION=NO" in salida
    integridad = "INTEGRIDAD_SALTADA=NO" in salida
    print("    " + " | ".join(l for l in salida.splitlines() if "=" in l)[:160])
    anota("2 desarme por entorno con ascendencia fabricada",
          "INERTE: certifica igual",
          f"trinquetes={certifica}, sin ablacion={sin_ablacion}, integridad={integridad}",
          certifica and sin_ablacion and integridad)

    # --- 3/4/5. banderas de medicion en una invocacion que certifica ------
    for bandera, script, extra in (
            ("--sin-base", GATE, ["--sin-base"]),
            ("--base-fichero", GATE, ["--base-fichero", str(INVENTARIO)]),
            ("--solo-registro", CONTROL,
             ["--junit", str(INVENTARIO), "--solo-registro"])):
        print(f"\n########## `{bandera}` desde la LINEA DE COMANDOS")
        rc, salida = desde_linea_de_comandos(script, extra)
        print(f"    EXIT={rc}")
        anota(f"{bandera} desde linea de comandos", "ROJO", f"EXIT={rc}", rc == 1)

    # --- 5. LA MATRIZ DEL ESTADO INICIAL ----------------------------------
    # Cada negativo afirma EL MOTIVO, no un `EXIT != 0`: un rojo por accidente
    # -una dependencia rota, un `sys.path` cambiado, un `ImportError`- NO es una
    # deteccion. Por eso cada caso comprueba ademas que el veneno LLEGO.
    MOTIVO = "ESTADO INICIAL CONTAMINADO"
    fuera = user_site()

    # --- 0. PROCESO LIMPIO -> PASS ----------------------------------------
    # Sin esta fila, una comprobacion que dijera ROJO siempre pareceria
    # perfecta. Es el control positivo de toda la matriz.
    print("\n########## 0. proceso limpio")
    rc0, salida0 = desde_linea_de_comandos(GATE, [])
    limpio_ok = rc0 == 0 and MOTIVO not in salida0
    print(f"    EXIT={rc0}  sin contaminacion declarada={MOTIVO not in salida0}")
    anota("0 proceso limpio", "PASS", f"EXIT={rc0}", limpio_ok)

    escenarios = (
        ("usercustomize EXTERNO contamina el registro", VENENO, GATE, []),
        ("usercustomize EXTERNO, capa de resultados", VENENO, CONTROL,
         ["--junit", str(INVENTARIO)]),
        ("usercustomize EXTERNO contamina OTRA propiedad de fabrica",
         VENENO_OTRA_PROPIEDAD, GATE, []),
    )
    for etiqueta, plantilla, script, extra_arg in escenarios:
        print(f"\n########## estado inicial: {etiqueta}")
        rc_uc, salida_uc, llega = con_arranque_contaminado(
            script, fuera, "usercustomize.py", plantilla, extra_arg)
        por_el_motivo = MOTIVO in salida_uc
        print(f"    veneno llega={llega}  EXIT={rc_uc}  por el motivo={por_el_motivo}")
        anota(f"5 {etiqueta}", f"ROJO por `{MOTIVO}`",
              f"veneno={llega}, EXIT={rc_uc}, motivo={por_el_motivo}",
              llega and rc_uc == 1 and por_el_motivo)

    # --- 5s. `sitecustomize` EXTERNO: se INTENTA, y se mide si llega -------
    # No se declara de antemano que no es ejercitable: se prueba. Si la
    # distribucion trae su propio `sitecustomize` -medido aqui:
    # `/usr/lib/python3.13/sitecustomize.py`- este PRECEDE en `sys.path` y el
    # nuestro nunca corre; en un runner sin el, si corre. El caso se adapta a lo
    # que MIDE en vez de a lo que yo suponga de la maquina.
    print("\n########## 5s. `sitecustomize` EXTERNO")
    rc_sc, salida_sc, llega_sc = con_arranque_contaminado(
        GATE, fuera, "sitecustomize.py", VENENO)
    if llega_sc:
        por_motivo_sc = MOTIVO in salida_sc
        print(f"    veneno llega=True  EXIT={rc_sc}  motivo={por_motivo_sc}")
        anota("5s `sitecustomize` EXTERNO", f"ROJO por `{MOTIVO}`",
              f"veneno=True, EXIT={rc_sc}, motivo={por_motivo_sc}",
              rc_sc == 1 and por_motivo_sc)
    else:
        sistema = subprocess.run(
            [sys.executable, "-c",
             "import sitecustomize; print(sitecustomize.__file__)"],
            capture_output=True, text=True, timeout=120).stdout.strip()
        print(f"    el veneno NO llega; sitecustomize del sistema: {sistema}")
        # No es un PASS del control: es una via NO EJERCITABLE en esta maquina.
        # Se exige que la razon sea DEMOSTRABLE (existe uno del sistema), no una
        # suposicion. La clase la cubre `usercustomize`, que si se ejercita.
        anota("5s `sitecustomize` EXTERNO (no ejercitable aqui)",
              "razon demostrada, no supuesta",
              f"tapado por {sistema or '(nada)'}",
              bool(sistema) and not sistema.startswith(str(REPO)))

    # --- 5d. la MISMA contaminacion, DESDE DENTRO del repositorio ---------
    print("\n########## 5d. mutacion equivalente DESDE DENTRO del repo")
    sha_reg_antes = sha(REGISTRO_PY)
    rc_d, salida_d, llega_d = con_mutacion_desde_dentro(GATE)
    por_motivo_d = MOTIVO in salida_d
    restaurado_d = sha(REGISTRO_PY) == sha_reg_antes
    print(f"    veneno llega={llega_d}  EXIT={rc_d}  motivo={por_motivo_d}  "
          f"restaurado={restaurado_d}")
    anota("5d mutacion DESDE DENTRO del repo", f"ROJO por `{MOTIVO}`",
          f"veneno={llega_d}, EXIT={rc_d}, motivo={por_motivo_d}, "
          f"restaurado={restaurado_d}",
          llega_d and rc_d == 1 and por_motivo_d and restaurado_d)

    # --- 5z. ABLACION: sin la asercion, el ataque externo VUELVE A PASAR ---
    print("\n########## ABLACION: se retira la asercion de estado inicial")
    sha_antes = sha(GATE)
    previo = None
    try:
        previo = sin_la_asercion(GATE)
        rc_ab, salida_ab, llega_ab = con_arranque_contaminado(
            GATE, fuera, "usercustomize.py")
        vuelve = llega_ab and rc_ab == 0 and MOTIVO not in salida_ab
        print(f"    veneno llega={llega_ab}  EXIT={rc_ab}  (0 = el ataque pasa)")
    finally:
        if previo is not None:
            GATE.write_bytes(previo)
    restaurado = sha(GATE) == sha_antes
    print(f"    gate restaurado con el MISMO SHA-256: {restaurado}")
    anota("5z ABLACION de la asercion -> el ataque externo vuelve a pasar",
          "VERDE (pasa) y gate restaurado", f"pasa={vuelve}, restaurado={restaurado}",
          vuelve and restaurado)

    # Y RESTAURADA, el mismo ataque tiene que volver a fallar POR EL MOTIVO.
    # Sin esta fila, la ablacion demostraria que algo cambia, pero no que lo
    # que vuelve es la comprobacion correcta.
    print("\n########## 5r. restaurada la asercion, el ataque vuelve a fallar")
    rc_r, salida_r, llega_r = con_arranque_contaminado(
        GATE, fuera, "usercustomize.py")
    por_motivo_r = MOTIVO in salida_r
    print(f"    veneno llega={llega_r}  EXIT={rc_r}  motivo={por_motivo_r}")
    anota("5r restaurada la asercion -> vuelve a FALLAR por el motivo",
          f"ROJO por `{MOTIVO}`",
          f"veneno={llega_r}, EXIT={rc_r}, motivo={por_motivo_r}",
          llega_r and rc_r == 1 and por_motivo_r)

    # --- 5h. INVOCACION ENDURECIDA: defensa adicional, NO sustituta --------
    # Dos medidas, y las dos con sonda minima para que la respuesta no dependa
    # de si el gate tiene sus dependencias -que es donde se fabricaron dos
    # falsos hallazgos en esta ronda-:
    #   (i)  con `-s` el arranque automatico del *user site* NO se ejecuta:
    #        la barrera secundaria es EFECTIVA para esa via.
    #   (ii) con `-s` la contaminacion DESDE DENTRO del repositorio SIGUE
    #        llegando: la barrera NO cubre esa via, asi que la comprobacion
    #        interna sigue siendo NECESARIA. Es la jerarquia exigida: quitar un
    #        flag de la linea de ejecucion no puede destruir la garantia.
    print("\n########## 5h. invocacion endurecida (`-s`)")
    corre_normal = arranque_externo_se_ejecuta(aislado=False)
    corre_aislado = arranque_externo_se_ejecuta(aislado=True)
    print(f"    arranque del *user site* corre: normal={corre_normal}, "
          f"con -s={corre_aislado}")
    anota("5h(i) `-s` impide el arranque automatico externo",
          "corre sin -s, NO corre con -s",
          f"normal={corre_normal}, aislado={corre_aislado}",
          corre_normal and not corre_aislado)

    sha_reg2 = sha(REGISTRO_PY)
    _, _, llega_aislado = con_mutacion_desde_dentro(GATE, aislado=True)
    restaurado2 = sha(REGISTRO_PY) == sha_reg2
    print(f"    con -s, la contaminacion DESDE DENTRO llega={llega_aislado}")
    anota("5h(ii) `-s` NO cubre la contaminacion desde dentro",
          "el veneno llega igual -> la interna es necesaria",
          f"llega={llega_aislado}, restaurado={restaurado2}",
          llega_aislado and restaurado2)

    # ======================================================================
    # LA MATRIZ DE LA RAIZ DE CONFIANZA (A-H)
    # ======================================================================
    # La pregunta que decide todo esto: ¿hemos dejado de certificar atributos
    # enumerados de un proceso potencialmente contaminado y pasado a certificar
    # una ejecucion cuya raiz de confianza esta FUERA de ese proceso?
    #
    # En cada fila se exige EL MOTIVO, o el CENTINELA que demuestre que el
    # payload no llego a ejecutarse. Lo que NO vale: "payload ejecutado +
    # funcion critica modificada -> PASS", ni un FAIL por `ImportError`
    # accidental.
    INTEGRIDAD = "INTEGRIDAD DEL SUJETO"
    PRECARGA = "MODULO CRITICO YA CARGADO"

    # Procesos que SI son la ruta de certificacion. Si el payload no aparece en
    # ninguno de ellos, no alcanzo lo que se certifica.
    CERTIFICAN = ("bootstrap_certificacion.py", "check_suite_inventory.py",
                  "check_ejecucion_real.py")

    def juzga_contaminacion(etiqueta, rc, salida, huellas, motivos):
        """Tres desenlaces, y cada uno con su evidencia:

        1. el payload NO se ejecuto en ningun sitio -> bloqueado por la
           frontera; PASS es correcto.
        2. se ejecuto, pero NO en la ruta de certificacion -sino en algun
           subproceso de medicion- -> PASS es correcto, y se DEMUESTRA con el
           `argv` de los procesos que si lo ejecutaron.
        3. se ejecuto EN la ruta de certificacion -> se exige FAIL con motivo.
        """
        alcanza = [h for h in huellas if any(c in h for c in CERTIFICAN)]
        if not huellas:
            print(f"    payload NO EJECUTADO (centinela vacio); EXIT={rc}")
            anota(etiqueta, "bloqueado por la frontera de ejecucion",
                  f"centinela=vacio, EXIT={rc}", rc == 0)
        elif not alcanza:
            print(f"    payload ejecutado en {len(huellas)} proceso(s), NINGUNO "
                  f"de la ruta de certificacion; EXIT={rc}")
            print(f"      ejemplo: {huellas[0][:90]}")
            anota(etiqueta, "no alcanza la ruta de certificacion",
                  f"procesos ajenos={len(huellas)}, certificantes=0, EXIT={rc}",
                  rc == 0)
        else:
            por_motivo = any(m in salida for m in motivos)
            print(f"    payload ALCANZA la certificacion; EXIT={rc}; "
                  f"motivo={por_motivo}")
            anota(etiqueta, "FAIL con motivo especifico",
                  f"alcanza={len(alcanza)}, EXIT={rc}, motivo={por_motivo}",
                  rc == 1 and por_motivo)

    # --- A. interprete limpio -> PASS -------------------------------------
    print("\n########## A. interprete limpio")
    rcA, salidaA = corre_bootstrap(GATE)
    okA = rcA == 0 and "aislado=True" in salidaA
    print(f"    EXIT={rcA}")
    anota("A interprete limpio", "PASS y aislado",
          f"EXIT={rcA}, aislado={'aislado=True' in salidaA}", okA)

    # --- B. `sitecustomize` que cambia una BANDERA ------------------------
    print("\n########## B. `sitecustomize` cambia una bandera")
    rcB, salidaB, huellasB = con_payload("sitecustomize.py", PAYLOAD_BANDERA, GATE)
    juzga_contaminacion("B `sitecustomize` cambia bandera", rcB, salidaB, huellasB,
                        (MOTIVO, INTEGRIDAD, PRECARGA))

    # --- C. `usercustomize` equivalente -----------------------------------
    print("\n########## C. `usercustomize` cambia una bandera")
    rcC, salidaC, huellasC = con_payload("usercustomize.py", PAYLOAD_BANDERA, GATE)
    juzga_contaminacion("C `usercustomize` cambia bandera", rcC, salidaC, huellasC,
                        (MOTIVO, INTEGRIDAD, PRECARGA))

    # --- D. MONKEYPATCH de funcion critica (el ataque del revisor) --------
    print("\n########## D. `usercustomize` MONKEYPATCHEA una funcion critica")
    rcD, salidaD, huellasD = con_payload("usercustomize.py", PAYLOAD_FUNCION, GATE)
    juzga_contaminacion("D monkeypatch de funcion critica", rcD, salidaD, huellasD,
                        (MOTIVO, INTEGRIDAD, PRECARGA))

    # --- E. modulo critico PRECARGADO/manipulado --------------------------
    # Se llama al bootstrap DESDE un proceso que ya importo y manipulo el
    # modulo critico. No hay `usercustomize` de por medio: la contaminacion es
    # anterior por construccion.
    print("\n########## E. modulo critico PRECARGADO y manipulado")
    # `runpy.run_path(..., run_name='__main__')`, NO `exec(open(...).read())`:
    # eso ultimo deja el bootstrap sin `__file__` y revienta con `NameError`
    # antes de comprobar nada. Seria un rojo PRESTADO -medido, y me paso-, y un
    # rojo prestado no demuestra la garantia.
    programa = "\n".join([
        "import runpy, sys",
        f"sys.path.insert(0, {str(SCRIPTS)!r})",
        "import registro_xfail",
        "registro_xfail.MUTADO = True",
        f"sys.argv = [{str(BOOTSTRAP)!r}, {str(GATE)!r}]",
        f"runpy.run_path({str(BOOTSTRAP)!r}, run_name='__main__')",
    ])
    pE = subprocess.run([sys.executable, "-c", programa], cwd=REPO,
                        capture_output=True, text=True, timeout=3600)
    salidaE = pE.stdout + pE.stderr
    por_motivoE = PRECARGA in salidaE
    print(f"    EXIT={pE.returncode}  motivo={por_motivoE}")
    anota("E modulo critico precargado", f"FAIL por `{PRECARGA}`",
          f"EXIT={pE.returncode}, motivo={por_motivoE}",
          pE.returncode == 1 and por_motivoE)

    # --- F. modificar de verdad el fichero critico del SUJETO -------------
    print("\n########## F. el fichero critico en disco != sujeto Git")
    sha_F = sha(REGISTRO_PY)
    previo_F = REGISTRO_PY.read_bytes()
    try:
        REGISTRO_PY.write_bytes(previo_F + b"\n# ALTERADO POR LA CALIBRACION\n")
        rcF, salidaF = corre_bootstrap(GATE)
    finally:
        REGISTRO_PY.write_bytes(previo_F)
    por_motivoF = INTEGRIDAD in salidaF
    restauradoF = sha(REGISTRO_PY) == sha_F
    print(f"    EXIT={rcF}  motivo={por_motivoF}  restaurado={restauradoF}")
    anota("F fichero critico != sujeto Git", f"FAIL por `{INTEGRIDAD}`",
          f"EXIT={rcF}, motivo={por_motivoF}, restaurado={restauradoF}",
          rcF == 1 and por_motivoF and restauradoF)

    # --- G. retirar el AISLAMIENTO, manteniendo el bootstrap --------------
    # Sin `-I` el arranque automatico SI corre. Lo que se exige es que las
    # barreras internas sigan sujetando lo que alcance al codigo critico: o el
    # payload no llega a tocarlo -y hay que demostrarlo- o hay FAIL con motivo.
    print("\n########## G. sin aislamiento (`-I` retirado), bootstrap intacto")
    rcG, salidaG, huellasG = con_payload("usercustomize.py", PAYLOAD_FUNCION,
                                         GATE, aislado=False)
    ejeG = bool(huellasG)
    alcanzaG = [h for h in huellasG if any(c in h for c in CERTIFICAN)]
    aviso = "AISLAMIENTO RETIRADO" in salidaG
    print(f"    payload ejecutado en {len(huellasG)} proceso(s), "
          f"{len(alcanzaG)} de la ruta de certificacion; EXIT={rcG}; "
          f"avisa={aviso}")
    if ejeG and rcG == 0:
        # PASS solo es aceptable si se DEMUESTRA que el codigo critico en uso
        # sigue siendo el del repositorio.
        limpio = "ESTADO INICIAL CONTAMINADO" not in salidaG
        anota("G sin aislamiento, el payload no alcanza el codigo critico",
              "PASS solo con el aviso y sin contaminacion del codigo critico",
              f"ejecutado=True, EXIT=0, avisa={aviso}, codigo limpio={limpio}",
              aviso and limpio)
    else:
        por_motivoG = any(m in salidaG for m in (MOTIVO, INTEGRIDAD, PRECARGA))
        anota("G sin aislamiento", "FAIL con motivo especifico",
              f"ejecutado={ejeG}, EXIT={rcG}, motivo={por_motivoG}",
              rcG == 1 and por_motivoG)

    # --- H. ABLACION: sin las comprobaciones, el vector F vuelve a pasar --
    #
    # OJO AL CAMBIO DE PREMISA. Esta fila ablacionaba el bootstrap DEL DISCO, y
    # eso ya no demuestra nada: desde que la raiz se ejecuta desde el objeto
    # Git, tocar el fichero del arbol es INERTE -que es exactamente lo que mide
    # M4-. Medido al reejecutar: `pasa=False`, o sea el ataque seguia muriendo.
    # No era un defecto: era el arreglo funcionando.
    #
    # Para que la ablacion siga significando algo hay que quitar las
    # comprobaciones DE LOS BYTES QUE SE EJECUTAN: se parte del objeto Git, se
    # les quita `soy_el_objeto_git` y `verifica_fuente`, y se ejecuta eso. Si
    # entonces el vector F pasa, esas dos barreras estaban sujetando de verdad.
    print("\n########## H. ABLACION de las comprobaciones en los bytes que corren")
    sha_reg_H = sha(REGISTRO_PY)
    previo_H = REGISTRO_PY.read_bytes()
    sujeto = sujeto_actual()
    fuente = subprocess.run(
        ["git", "show", f"{sujeto}:.github/scripts/bootstrap_certificacion.py"],
        cwd=REPO, capture_output=True, text=True, timeout=300).stdout
    ablado = neutraliza_verificacion(fuente, ("soy_el_objeto_git", "verifica_fuente"))
    tmp_h = Path(tempfile.mkdtemp(prefix="raiz-ablada-")) / "raiz.py"
    tmp_h.write_text(ablado, encoding="utf-8")
    try:
        REGISTRO_PY.write_bytes(previo_H + b"\n# ALTERADO POR LA CALIBRACION\n")
        pH = subprocess.run(
            [sys.executable, "-I", str(tmp_h), "--sujeto", sujeto, str(GATE)],
            cwd=REPO, capture_output=True, text=True, timeout=3600)
        rcH, salidaH = pH.returncode, pH.stdout + pH.stderr
    finally:
        REGISTRO_PY.write_bytes(previo_H)
        shutil.rmtree(tmp_h.parent, ignore_errors=True)
        subprocess.run(["rm", "-rf", str(SCRIPTS / "__pycache__")], timeout=60)
    restauradoH = sha(REGISTRO_PY) == sha_reg_H
    pasa = rcH == 0 and INTEGRIDAD not in salidaH
    print(f"    EXIT={rcH}  (0 = el ataque pasa)  restaurado={restauradoH}")
    anota("H ablacion en los BYTES QUE CORREN -> el vector F vuelve a pasar",
          "PASS (pasa) y todo restaurado", f"pasa={pasa}, restaurado={restauradoH}",
          pasa and restauradoH)

    # --- I. PRUEBA POSITIVA: el bootstrap NO sale del disco ----------------
    # La mas simple y la mas convincente: se mete un MARCADOR INOCUO en el
    # bootstrap del working tree y se comprueba que ese marcador NO se ejecuta.
    # Si no aparece, el bootstrap que corre no es el del disco. Punto.
    print("\n########## I. marcador inocuo en el bootstrap del working tree")
    MARCA = Path("/tmp/s9k-marca-bootstrap-disco")
    MARCA.unlink(missing_ok=True)
    sha_boot_I = sha(BOOTSTRAP)
    previo_I = BOOTSTRAP.read_bytes()
    try:
        BOOTSTRAP.write_bytes(
            previo_I + (
                "\n# MARCADOR INOCUO DE LA CALIBRACION\n"
                "from pathlib import Path as _P\n"
                f"_P({str(MARCA)!r}).write_text('el bootstrap del disco SI corrio')\n"
            ).encode("utf-8"))
        rcI, salidaI = corre_certificacion_desde_git(GATE)
    finally:
        BOOTSTRAP.write_bytes(previo_I)
    marcador_corrio = MARCA.exists()
    MARCA.unlink(missing_ok=True)
    restauradoI = sha(BOOTSTRAP) == sha_boot_I
    print(f"    marcador ejecutado={marcador_corrio}  EXIT={rcI}  "
          f"restaurado={restauradoI}")
    anota("M4 marcador en el bootstrap del working tree: NO se ejecuta",
          "marcador ausente (el bootstrap sale del objeto Git)",
          f"marcador={marcador_corrio}, EXIT={rcI}, restaurado={restauradoI}",
          (not marcador_corrio) and restauradoI)

    # --- J. EL ATAQUE COMBINADO ------------------------------------------
    # No basta con probar cada mitad por separado: precisamente la COMBINACION
    # -bootstrap del working tree alterado para no verificar nada, MAS una
    # funcion critica sustituida- es la que demostro el hueco. Aqui se exige que
    # el ataque no sobreviva, y ademas se registra POR QUE no sobrevive.
    print("\n########## J. ATAQUE COMBINADO: bootstrap alterado + funcion parcheada")
    sha_boot_J = sha(BOOTSTRAP)
    sha_reg_J = sha(REGISTRO_PY)
    sha_suite_J = sha(SUITE_CRITICA)
    sha_registro_J = sha(REGISTRO_TXT)
    previo_boot = BOOTSTRAP.read_bytes()
    previo_reg = REGISTRO_PY.read_bytes()
    previo_suite = SUITE_CRITICA.read_bytes()
    previo_registro = REGISTRO_TXT.read_bytes()
    try:
        # (1) el bootstrap del disco deja de verificar nada
        BOOTSTRAP.write_text(
            neutraliza_verificacion(previo_boot.decode("utf-8")),
            encoding="utf-8")
        # (2) la FUNCION critica se sustituye por una que no comprueba nada
        texto_reg = previo_reg.decode("utf-8")
        BOOTSTRAP_MARCA = "\n\ndef contenido_verificado():\n    return (FICHERO.read_text(encoding='utf-8') if FICHERO.exists() else ''), []\n"
        REGISTRO_PY.write_text(texto_reg + BOOTSTRAP_MARCA, encoding="utf-8")
        # (3) defecto real tragado y autorizacion escrita en caliente
        SUITE_CRITICA.write_text(
            previo_suite.decode("utf-8")
            + "\n\n@pytest.mark.xfail(strict=True, reason='infra')\n"
              "def test_tragado_combinado():\n    assert 1 == 2\n",
            encoding="utf-8")
        REGISTRO_TXT.write_text(
            previo_registro.decode("utf-8")
            + f"HOT-01 | {SUITE_CRITICA.relative_to(REPO).as_posix()}"
              f"::test_tragado_combinado | escrito en caliente\n",
            encoding="utf-8")
        rcJ, salidaJ = corre_certificacion_desde_git(GATE)
    finally:
        BOOTSTRAP.write_bytes(previo_boot)
        REGISTRO_PY.write_bytes(previo_reg)
        SUITE_CRITICA.write_bytes(previo_suite)
        REGISTRO_TXT.write_bytes(previo_registro)
        subprocess.run(["rm", "-rf", str(SCRIPTS / "__pycache__")], timeout=60)
    motivoJ = [m for m in (INTEGRIDAD, PRECARGA, MOTIVO) if m in salidaJ]
    restauradoJ = (sha(BOOTSTRAP) == sha_boot_J and sha(REGISTRO_PY) == sha_reg_J
                   and sha(SUITE_CRITICA) == sha_suite_J
                   and sha(REGISTRO_TXT) == sha_registro_J)
    print(f"    EXIT={rcJ}  motivos={motivoJ}  restaurado={restauradoJ}")
    anota("M5 ataque COMBINADO (bootstrap del disco + funcion parcheada)",
          "ROJO con motivo, y todo restaurado",
          f"EXIT={rcJ}, motivos={motivoJ or 'ninguno'}, restaurado={restauradoJ}",
          rcJ == 1 and bool(motivoJ) and restauradoJ)

    # --- K. EL PASO DE CI NO PUEDE SALIR VERDE SIN CERTIFICAR -------------
    # La tuberia que introduje en el delta anterior traia un modo de fallo
    # SILENCIOSO: si `git show` falla, `python3 -I -` recibe stdin vacio, no
    # ejecuta nada y sale 0. La proteccion era `set -o pipefail`, declarada en
    # prosa y que ningun gate comprobaba ni ninguna fila calibraba.
    #
    # Aqui se mide la propiedad que de verdad importa -"si la raiz no se puede
    # materializar, el paso enrojece"- sobre las DOS formas, y con un defecto
    # REAL presente, para que un verde signifique de verdad que la
    # certificacion no llego a correr.
    print("\n########## K. el paso de CI con la raiz irrecuperable")
    sha_suite_K = sha(SUITE_CRITICA)
    previo_suite_K = SUITE_CRITICA.read_bytes()
    gate_rel = GATE.relative_to(REPO).as_posix()

    def paso(forma: str, objeto: str, trunca: int | None = None,
             verifica: bool = True) -> tuple[int, str]:
        if forma == "embarcada":
            cuerpo = cuerpo_embarcado(objeto, gate_rel, trunca, verifica)
        else:
            # La tuberia RETIRADA, con la proteccion quitada: es la edicion
            # accidental (normalizar `set -euo pipefail` a `set -eu`).
            cuerpo = ('set -eu\n'
                      f'git show "{objeto}" '
                      f'| python3 -I - --sujeto "$SUJETO" {gate_rel}\n')
        p = subprocess.run(["bash", "-c", cuerpo], cwd=REPO,
                           capture_output=True, text=True, timeout=3600,
                           env={**os.environ, "SUJETO": sujeto_actual()})
        return p.returncode, p.stdout + p.stderr

    try:
        SUITE_CRITICA.write_text(
            previo_suite_K.decode("utf-8")
            + "\n\n@pytest.mark.xfail(strict=True, reason='infra')\n"
              "def test_tragado_paso_ci():\n    assert 1 == 2\n",
            encoding="utf-8")
        sujeto = sujeto_actual()
        objeto_ok = f"{sujeto}:.github/scripts/bootstrap_certificacion.py"
        objeto_roto = f"{sujeto}:.github/scripts/NO_EXISTE.py"
        rcK1, salK1 = paso("embarcada", objeto_roto)
        rcK2, salK2 = paso("tuberia", objeto_roto)
        rcK3, salK3 = paso("embarcada", objeto_ok)
        # M6/M7: la raiz se materializa VACIA o TRUNCADA. Sin control, la
        # vacia sale EXIT=0 -Python no ejecuta nada- y la truncada muere por
        # `SyntaxError`, un rojo prestado: en los dos casos `soy_el_objeto_git`
        # NO llega a correr y la procedencia se queda sin comprobar.
        rcK6, salK6 = paso("embarcada", objeto_ok, trunca=0)
        rcK7, salK7 = paso("embarcada", objeto_ok, trunca=4000)
        # ABLACION de la comprobacion nueva: sin ella, vuelve el falso verde.
        rcK8, salK8 = paso("embarcada", objeto_ok, trunca=0, verifica=False)
    finally:
        SUITE_CRITICA.write_bytes(previo_suite_K)
        subprocess.run(["rm", "-rf", str(SCRIPTS / "__pycache__")], timeout=60)
    restauradoK = sha(SUITE_CRITICA) == sha_suite_K

    # M1: no basta con que enrojezca; hay que demostrar que PYTHON NO LLEGO A
    # EJECUTARSE. Si hubiera corrido, el bootstrap habria impreso su linea
    # `bootstrap: sujeto ...`.
    python_corrio_M1 = "bootstrap: sujeto" in salK1
    print(f"    M1 EMBARCADA + `git show` roto -> EXIT={rcK1}  "
          f"python ejecutado={python_corrio_M1}")
    anota("M1 `git show` falla -> ROJO ANTES de Python",
          "ROJO y Python sin ejecutar",
          f"EXIT={rcK1}, python={python_corrio_M1}",
          rcK1 != 0 and not python_corrio_M1)

    # M2 ES LA FILA CLAVE. Reintroduce la TUBERIA y hace fallar el primer
    # comando: tiene que REPRODUCIR el falso verde antiguo. Sin ella, el
    # arreglo seria una reescritura sin prueba de que la causa desaparecio;
    # con ella queda demostrado que lo eliminado es el MECANISMO CONCRETO que
    # producia el PASS falso, no una cuestion de sintaxis.
    silenciosa = rcK2 == 0 and "bootstrap: sujeto" not in salK2
    print(f"    M2 TUBERIA reintroducida + primer comando roto -> EXIT={rcK2}"
          f"{'  (FALSO VERDE reproducido)' if silenciosa else ''}")
    anota("M2 reintroducir la TUBERIA reproduce el falso verde",
          "EXIT=0 sin certificar (la causa era esa)",
          f"EXIT={rcK2}, python sin ejecutar={'bootstrap: sujeto' not in salK2}",
          silenciosa)

    # M3: se vuelve a la forma embarcada con EL MISMO fallo. Es el cierre A/B:
    # mismo error, distinto desenlace, y la unica variable es la tuberia.
    print(f"    M3 vuelta a EMBARCADA con el MISMO fallo -> EXIT={rcK1}")
    anota("M3 restaurado el fichero intermedio, el mismo fallo es ROJO",
          "ROJO (cierre A/B contra M2)", f"EXIT={rcK1} frente a M2 EXIT={rcK2}",
          rcK1 != 0 and rcK2 == 0)

    caza = rcK3 == 1
    print(f"    NORMAL: EMBARCADA + raiz correcta -> EXIT={rcK3} "
          f"(1 = certifica y caza el defecto real inyectado)")
    anota("NORMAL objeto Git -> temporal -> Python, y CERTIFICA",
          "ROJO por el defecto real inyectado",
          f"EXIT={rcK3}, suite restaurada={restauradoK}", caza and restauradoK)

    MOTIVO_MAT = MOTIVO_MATERIALIZACION

    # --- M0: el arnes mide LA MISMA construccion que corre en CI ----------
    # Sin esta fila, M1-M7 podrian estar hablando de un shell inventado aqui
    # mientras `ci.yml` corre otro. Se compara la forma canonica -sin
    # comentarios y sin los valores que solo son datos- del cuerpo GENERADO
    # contra la de CADA paso de `ci.yml` que materializa la raiz. Y se calibra:
    # con la comprobacion ablacionada la comparacion TIENE que diferir; si no,
    # no estaria mirando nada.
    obj_canon = f"{sujeto}:{RUTA_BOOTSTRAP}"
    try:
        pasos_ci = pasos_de_certificacion_de_ci()
    except Exception as e:  # falla cerrado: sin poder leer `ci.yml`, es ROJO
        pasos_ci, fallo_m0 = [], repr(e)
    else:
        fallo_m0 = "" if pasos_ci else "ningun paso de ci.yml materializa la raiz"
    mio = _canon(cuerpo_embarcado(obj_canon, gate_rel), obj_canon)
    ablado_m0 = _canon(cuerpo_embarcado(obj_canon, gate_rel, verifica=False),
                       obj_canon)
    iguales = [n for n, c in pasos_ci if _canon(c, obj_canon) == mio]
    distintos = [n for n, c in pasos_ci if _canon(c, obj_canon) != mio]
    detecta = all(_canon(c, obj_canon) != ablado_m0 for n, c in pasos_ci)
    print(f"\n    M0 pasos de ci.yml que materializan la raiz: {len(pasos_ci)}; "
          f"identicos al arnes: {len(iguales)}; distintos: {distintos or 'ninguno'}; "
          f"la comparacion detecta la ablacion={detecta}")
    anota("M0 el arnes mide la MISMA construccion que `ci.yml`",
          "todos los pasos identicos, y la comparacion capaz de enrojecer",
          f"pasos={len(pasos_ci)}, identicos={len(iguales)}, "
          f"distintos={distintos or 'ninguno'}, detecta ablacion={detecta}"
          + (f", fallo={fallo_m0}" if fallo_m0 else ""),
          bool(pasos_ci) and not distintos and detecta and not fallo_m0)

    # M6 y M7 cierran la variante N+1 del MISMO bypass: "Python sale 0 sin
    # certificar". La unidad de control cambia -ya no basta con que `git show`
    # devuelva 0: lo que se ejecuta tiene que SER el objeto, y quien lo dice es
    # `git hash-object` sobre el fichero en disco- en vez de anadir un caso
    # mas. El rojo se exige POR EL MOTIVO: `RAIZ NO MATERIALIZADA` y Python sin
    # ejecutar; un `SyntaxError` no contaria.
    for etiqueta, rc, salida, fila in (
        ("VACIA", rcK6, salK6,
         "M6 raiz materializada VACIA -> ROJO ANTES de Python"),
        ("TRUNCADA", rcK7, salK7,
         "M7 raiz materializada TRUNCADA -> ROJO ANTES de Python"),
    ):
        por_motivo = MOTIVO_MAT in salida
        corrio = "bootstrap: sujeto" in salida
        sintaxis = "SyntaxError" in salida
        print(f"    {fila.split()[0]} raiz {etiqueta} -> EXIT={rc}  "
              f"motivo={por_motivo}  python ejecutado={corrio}  "
              f"SyntaxError={sintaxis}")
        anota(fila, f"ROJO por `{MOTIVO_MAT}`, sin Python y sin rojo prestado",
              f"EXIT={rc}, motivo={por_motivo}, python={corrio}, "
              f"SyntaxError={sintaxis}",
              rc == 1 and por_motivo and not corrio and not sintaxis)

    # ABLACION de M6: quitada la comprobacion, la raiz vacia vuelve a salir en
    # verde sin certificar. Sin esta fila, la comprobacion nueva seria otra
    # garantia declarada sin control negativo -justo lo que bloqueo el delta
    # anterior-.
    falso_verde = rcK8 == 0 and "bootstrap: sujeto" not in salK8
    print(f"    M6b ABLACION de la comprobacion + raiz VACIA -> EXIT={rcK8}"
          f"{'  (FALSO VERDE reproducido)' if falso_verde else ''}")
    anota("M6b ablacion de la materializacion -> vuelve el falso verde",
          "EXIT=0 sin certificar (la comprobacion sujetaba de verdad)",
          f"EXIT={rcK8}, python sin ejecutar={'bootstrap: sujeto' not in salK8}",
          falso_verde)

    # --- N. los filtros `clean` de Git mienten sobre el hash --------------
    # N2 es a esta correccion lo que M2 a la anterior: demuestra que el bypass
    # EXISTIA y que la bandera es lo que lo mata, no una reescritura por si
    # acaso. Montado en repositorio de prueba AISLADO.
    print("\n########## N. `git hash-object` bajo filtros Git hostiles")
    for fila, esperado, obtenido, ok in calibra_filtros_hostiles(gate_rel):
        print(f"    {fila} -> {obtenido}")
        anota(fila, esperado, obtenido, ok)

    # --- 6. CONTROL POSITIVO: el arnes SI puede ablacionar ----------------
    print("\n########## 6. control positivo: el arnes SI puede ablacionar")
    rc_con, salida_con = arnes_comun.ejecuta_gate(
        "check_suite_inventory", ["--base-fichero", str(INVENTARIO)],
        ablacion="A", timeout=2400)
    activa = "ABLACION ACTIVA" in salida_con
    print(f"    EXIT={rc_con}  ablacion anunciada={activa}")
    anota("6 el arnes puede ablacionar (si no, la calibracion muere)",
          "ablacion ACTIVA y gate ejecutable", f"EXIT={rc_con}, activa={activa}",
          activa and rc_con in (0, 1))

    print("\n===== SHA-256 DESPUES =====")
    for f, esperado in hashes.items():
        real = sha(f)
        marca = "OK" if real == esperado else "**NO COINCIDE**"
        fallos += 0 if real == esperado else 1
        print(f"  {marca}  {real}  {f.relative_to(REPO)}")

    print("\n\n===== TABLA (el binario que certifica no se puede desarmar) =====\n")
    print("| Caso | Esperado | Obtenido | Veredicto |")
    print("|---|---|---|---|")
    for fila in filas:
        print("| {} | {} | {} | {} |".format(*fila))

    if fallos:
        print(f"\nCALIBRACION FALLIDA: {fallos} desviacion(es)")
        return 1
    print(f"\nCALIBRACION SUPERADA: {len(filas)}/{len(filas)} casos, y ningun "
          f"fichero del repositorio modificado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
