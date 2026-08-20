#!/usr/bin/env python3
"""Calibracion de la capa que verifica el RESULTADO (`check_ejecucion_real.py`).

QUE SE DEMUESTRA AQUI
=====================
Que apagar una suite critica por CUALQUIERA de los vectores conocidos —los que
tres revisores independientes encontraron, uno por ronda, incluidos G1, G2 y
G3— deja el informe de ejecucion sin las pruebas de esa suite, y que el control
lo ve. Y que quitar el control (`S9K_EJECUCION_ABLACION=1`) devuelve esos mismos
casos a VERDE.

POR QUE LOS VECTORES CONVERGEN, Y POR QUE ESO ES EL PUNTO
=========================================================
`PYTEST_ADDOPTS` en cinco niveles de `env:`, por `$GITHUB_ENV`, con el nombre
concatenado sin `$` (G1), por `container.options -e` (G2), por un `uses:` a un
workflow reutilizable (G3) o por un `sitecustomize.py`: TODOS terminan en lo
mismo, una variable en el entorno del proceso que ejecuta pytest. Ahi esta la
razon de esta capa: la lista de MECANISMOS es abierta y no se acaba nunca; el
EFECTO observable es uno solo y se puede medir.

Para que ningun caso tome prestado el rojo de otro, cada uno apaga un MODULO
DISTINTO. El error nombra el modulo, asi que el rojo de cada caso es suyo y se
distingue del de al lado.

HONESTIDAD SOBRE LA ENTREGA
===========================
G1 se reproduce ENTERO: se ejecuta la linea de shell de verdad contra un
fichero `$GITHUB_ENV` y se parsea como hace el runner. G2 y G3 necesitan Docker
y el runner de GitHub, que aqui no hay: lo que se reproduce es su EFECTO
DOCUMENTADO —la variable presente en el entorno de los pasos del job—, y se
dice asi en la tabla en vez de fingir que se ejecuto `docker create`. Que ese
efecto sea el correcto es justamente lo que G2 y G3 demostraron VIVOS en CI con
`EXIT=0`.

NO MUTA NINGUN FICHERO DEL REPOSITORIO. Los artefactos van a un directorio
temporal. Aun asi se publica el SHA-256 de los ficheros del carril antes y
despues, porque "no lo toco" es una afirmacion que tambien hay que medir.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTROL = REPO / ".github" / "scripts" / "check_ejecucion_real.py"
RAIZ = "viewer/tests"

VERDE, ROJO = "VERDE", "ROJO"

# Un modulo DISTINTO por caso: asi el rojo de cada uno lleva su propio nombre y
# ninguno se apoya en el del vecino.
#
# LOS NOMBRES NO SE ESCRIBEN AQUI, Y NO ES ESTETICA. La primera version de este
# arnes los llevaba como constantes literales, y eso ROMPIO otra calibracion:
# `check_suite_inventory.py` DERIVA la criticidad de las fuentes ejecutables que
# nombran un modulo —un arnes de calibracion es una de ellas—, asi que escribir
# `viewer/tests/test_parcialidad_declarada.py` aqui lo convertia en critico por
# DOS caminos. El caso S4 de `calibra_suite_inventory.py` (borrar
# `pytest.mark.critico` y ver caer los criticos de 20 a 19) dejo de ponerse rojo:
# el modulo seguia siendo critico gracias a ESTE fichero. Medido: S4 esperaba
# ROJO y salio VERDE.
#
# Es el mismo error que este carril persigue, cometido desde el otro lado: una
# medida que se contamina a si misma. Se corrige leyendo los modulos del
# INVENTARIO en tiempo de ejecucion, que es donde ya estan medidos, en vez de
# repetirlos en codigo.
def _criticos_del_visor(cuantos: int) -> list[str]:
    """Los primeros `cuantos` modulos criticos bajo `viewer/tests`, en orden.

    Del inventario, no de una lista escrita a mano: asi este fichero no NOMBRA
    ningun modulo y no puede volver critico a nadie.
    """
    datos = json.loads((REPO / ".github" / "suite-inventario.json")
                       .read_text(encoding="utf-8"))
    delegados = set(datos.get("delegados") or ())
    en_pie = datos.get("en_pie") or {}
    elegidos = [m for m in sorted(datos.get("criticos") or ())
                if m.startswith(RAIZ + "/")
                and m not in delegados
                and en_pie.get(m, 0) > 0]
    if len(elegidos) < cuantos:
        raise SystemExit(
            f"CALIBRACION IMPOSIBLE: hacen falta {cuantos} modulos criticos con "
            f"pruebas bajo `{RAIZ}` para que cada caso tenga su ancla propia, y "
            f"el inventario solo ofrece {len(elegidos)}. Sin anclas distintas los "
            f"casos se prestarian el rojo, y eso no demuestra nada.")
    return elegidos[:cuantos]


(M_A, M_B, M_C, M_D, M_E, M_F) = _criticos_del_visor(6)


def sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def corre_pytest(tmp: Path, entorno: dict, extra: list[str] | None = None) -> Path:
    """Ejecuta la suite del visor y devuelve el informe JUnit."""
    informe = tmp / "junit.xml"
    subprocess.run(
        [sys.executable, "-m", "pytest", RAIZ, "-q", "--no-header", "--tb=no",
         f"--junitxml={informe}", *(extra or [])],
        cwd=REPO, capture_output=True, text=True, timeout=3600, env=entorno,
    )
    return informe


def corre_control(informe: Path, ablacion: bool) -> tuple[int, str]:
    entorno = dict(os.environ)
    entorno.pop("S9K_EJECUCION_ABLACION", None)
    if ablacion:
        entorno["S9K_EJECUCION_ABLACION"] = "1"
    p = subprocess.run(
        [sys.executable, str(CONTROL), "--junit", str(informe), "--raiz", RAIZ],
        cwd=REPO, capture_output=True, text=True, timeout=600, env=entorno,
    )
    return p.returncode, p.stdout + p.stderr


# --------------------------------------------------------------------------
# ENTREGAS: cada una mete `PYTEST_ADDOPTS` en el entorno de pytest por una via
# distinta. Devuelven el entorno con el que se lanzara la suite.
# --------------------------------------------------------------------------

def base() -> dict:
    entorno = dict(os.environ)
    for v in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD"):
        entorno.pop(v, None)
    return entorno


def entrega_g1_concatenado(tmp: Path, opcion: str) -> dict:
    """G1 REPRODUCIDO ENTERO: bash escribe el nombre por concatenacion de
    comillas en `$GITHUB_ENV`, y el entorno se construye parseando ese fichero
    exactamente como hace el runner de GitHub con el paso siguiente."""
    fichero = tmp / "github_env"
    guion = f'echo "PYTEST_ADD""OPTS={opcion}" >> "$GITHUB_ENV"'
    subprocess.run(["bash", "-c", guion], check=True, timeout=60,
                   env={**os.environ, "GITHUB_ENV": str(fichero)})
    entorno = base()
    for linea in fichero.read_text(encoding="utf-8").splitlines():
        if "=" in linea:
            clave, valor = linea.split("=", 1)
            entorno[clave] = valor
    if "PYTEST_ADDOPTS" not in entorno:
        raise SystemExit("ENTREGA IMPOSIBLE (G1): la linea de shell no produjo "
                         "el nombre prohibido; sin entrega el caso no demuestra "
                         "nada y callarlo seria peor")
    return entorno


def entrega_g2_container_options(tmp: Path, opcion: str) -> dict:
    """G2: `container.options: -e PYTEST_ADDOPTS=...`. Docker no esta aqui; se
    reproduce su efecto documentado: la variable en el entorno de los pasos."""
    entorno = base()
    entorno["PYTEST_ADDOPTS"] = opcion
    return entorno


def entrega_g3_uses_de_job(tmp: Path, opcion: str) -> dict:
    """G3: `uses:` a nivel de job. El workflow reutilizable trae su `env:`; el
    efecto es el mismo y es el que se mide."""
    entorno = base()
    entorno["PYTEST_ADDOPTS"] = opcion
    return entorno


def entrega_e2_prefijo_en_sustitucion(tmp: Path, opcion: str) -> dict:
    """E2: `out="$(VAR=v python -m pytest ...)"`. Se ejecuta de verdad en bash y
    se comprueba que el entorno llego al proceso hijo."""
    guion = ('out="$(PYTEST_ADDOPTS=%s %s -c \'import os;print(os.environ.get("PYTEST_ADDOPTS",""))\' 2>&1)"; '
             'printf %%s "$out"' % (opcion, sys.executable))
    p = subprocess.run(["bash", "-c", guion], capture_output=True, text=True,
                       timeout=60, env=base())
    if p.stdout.strip() != opcion:
        raise SystemExit(f"ENTREGA IMPOSIBLE (E2): el prefijo no llego al hijo "
                         f"({p.stdout!r}); sin entrega el caso no demuestra nada")
    entorno = base()
    entorno["PYTEST_ADDOPTS"] = opcion
    return entorno


def entrega_e1_github_env(tmp: Path, opcion: str) -> dict:
    """E1: `echo "VAR=v" >> "$GITHUB_ENV"`, el mecanismo documentado."""
    fichero = tmp / "github_env_e1"
    subprocess.run(["bash", "-c", f'echo "PYTEST_ADDOPTS={opcion}" >> "$GITHUB_ENV"'],
                   check=True, timeout=60,
                   env={**os.environ, "GITHUB_ENV": str(fichero)})
    entorno = base()
    for linea in fichero.read_text(encoding="utf-8").splitlines():
        if "=" in linea:
            clave, valor = linea.split("=", 1)
            entorno[clave] = valor
    return entorno


def entrega_e3_sitecustomize(tmp: Path, opcion: str) -> dict:
    """E3 REPRODUCIDO ENTERO: `sitecustomize.py` en `PYTHONPATH`. Python lo
    importa por estar en el path y el `ci.yml` no menciona nada prohibido."""
    directorio = tmp / "ci-tools"
    directorio.mkdir(exist_ok=True)
    (directorio / "sitecustomize.py").write_text(
        "import os\n"
        f"os.environ.setdefault('PYTEST_ADDOPTS', {opcion!r})\n",
        encoding="utf-8")
    entorno = base()
    previo = entorno.get("PYTHONPATH", "")
    entorno["PYTHONPATH"] = f"{directorio}{os.pathsep}{previo}" if previo else str(directorio)
    return entorno


CASOS = [
    # (titulo, entrega, opcion de apagado, ablacion, esperado)
    ("control positivo: corrida legitima completa de viewer/tests",
     None, None, False, VERDE),

    ("G1: nombre CONCATENADO por comillas hacia `$GITHUB_ENV` (bash real)",
     entrega_g1_concatenado, f"--ignore={M_A}", False, ROJO),
    ("G2: `container.options: -e` (efecto documentado de docker create)",
     entrega_g2_container_options, f"--ignore={M_B}", False, ROJO),
    ("G3: `uses:` a nivel de JOB (env del workflow reutilizable)",
     entrega_g3_uses_de_job, f"--ignore={M_C}", False, ROJO),
    ("E2: prefijo `VAR=v` dentro de `out=\"$(...)\"` (bash real)",
     entrega_e2_prefijo_en_sustitucion, f"--ignore={M_D}", False, ROJO),
    ("E1: `echo \"VAR=v\" >> \"$GITHUB_ENV\"` (bash real)",
     entrega_e1_github_env, f"--ignore={M_E}", False, ROJO),
    ("E3: `sitecustomize.py` en `PYTHONPATH` (import real de Python)",
     entrega_e3_sitecustomize, f"--ignore={M_F}", False, ROJO),
    # `-k` con la expresion ENTRECOMILLADA: pytest parsea `PYTEST_ADDOPTS` con
    # `shlex`, asi que sin comillas la expresion se parte y el rojo lo daria la
    # guardia anti-cero en vez del control que se quiere calibrar. Entrecomillada
    # el resto de la suite corre y el rojo nombra el modulo desaparecido, que es
    # el rojo propio de este caso.
    ("vector NO IMAGINADO: `-k` que descarta una suite entera",
     entrega_g2_container_options,
     '-k "not %s"' % Path(M_C).stem, False, ROJO),
    ("vector NO IMAGINADO: `--deselect` de un modulo entero",
     entrega_g2_container_options, f"--deselect={M_B}", False, ROJO),

    # --- ablacion: sin la comparacion contra el inventario, verde otra vez ---
    ("ABLACION: G1 con la comparacion contra el inventario quitada",
     entrega_g1_concatenado, f"--ignore={M_A}", True, VERDE),
    ("ABLACION: G2 con la comparacion contra el inventario quitada",
     entrega_g2_container_options, f"--ignore={M_B}", True, VERDE),
    ("ABLACION: E3 con la comparacion contra el inventario quitada",
     entrega_e3_sitecustomize, f"--ignore={M_F}", True, VERDE),
]


def main() -> int:
    vigilados = [
        REPO / ".github" / "scripts" / "check_ejecucion_real.py",
        REPO / ".github" / "scripts" / "check_suite_inventory.py",
        REPO / ".github" / "suite-inventario.json",
        REPO / ".github" / "workflows" / "ci.yml",
    ]
    antes = {f: sha(f) for f in vigilados}
    print("SHA-256 ANTES (este arnes NO deberia tocar ninguno):")
    for f, h in antes.items():
        print(f"  {h}  {f.relative_to(REPO)}")

    tmp = Path(tempfile.mkdtemp(prefix="calibra-ejecucion-"))
    filas, fallos = [], 0
    try:
        for titulo, entrega, opcion, ablacion, esperado in CASOS:
            entorno = entrega(tmp, opcion) if entrega else base()
            print(f"\n########## {titulo}  (esperado: {esperado})")
            if entrega:
                print(f"  entregado: PYTEST_ADDOPTS={entorno.get('PYTEST_ADDOPTS')!r} "
                      f"PYTHONPATH={entorno.get('PYTHONPATH', '')[:60]!r}")
            informe = corre_pytest(tmp, entorno)
            rc, salida = corre_control(informe, ablacion)
            obtenido = VERDE if rc == 0 else ROJO
            print("\n".join(salida.splitlines()[-6:]))
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
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n===== SHA-256 DESPUES =====")
    for f, h in antes.items():
        real = sha(f)
        marca = "OK" if real == h else "**NO COINCIDE**"
        fallos += 0 if real == h else 1
        print(f"  {marca}  {real}  {f.relative_to(REPO)}")

    print("\n\n===== TABLA DE CALIBRACION (capa de EJECUCION REAL) =====\n")
    print("| Caso | Esperado | RC | Obtenido | Veredicto | Primer error |")
    print("|---|---|---|---|---|---|")
    for fila in filas:
        print("| {} | {} | {} | {} | {} | {} |".format(*fila))

    if fallos:
        print(f"\nCALIBRACION FALLIDA: {fallos} desviacion(es)")
        return 1
    print(f"\nCALIBRACION SUPERADA: {len(filas)}/{len(filas)} casos con el "
          f"veredicto esperado, y ningun fichero del repositorio modificado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
