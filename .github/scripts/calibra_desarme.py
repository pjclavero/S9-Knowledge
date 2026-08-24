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


def con_usercustomize_envenenado(script: Path,
                                 extra: list[str] | None = None) -> tuple[int, str, bool]:
    """Monta un `usercustomize.py` FUERA del repo y ejecuta el gate.

    `site` lo importa AL ARRANCAR EL INTERPRETE, antes que el codigo del gate,
    asi que cuando este hace `import registro_xfail` recibe el mismo objeto de
    `sys.modules` ya envenenado, con la linea de invocacion intacta. Medido
    antes del arreglo: EXIT=0 y 0 errores con un defecto real tragado.

    Se restaura SIEMPRE lo que hubiera antes; si no se puede montar, el caso lo
    dice en vez de darse por bueno.
    """
    destino = user_site()
    fichero = destino / "usercustomize.py"
    previo = fichero.read_bytes() if fichero.exists() else None
    try:
        destino.mkdir(parents=True, exist_ok=True)
        fichero.write_text(
            "import sys\n"
            f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
            "try:\n"
            "    import registro_xfail\n"
            "    registro_xfail.MUTADO = True\n"
            "    registro_xfail.MIDIENDO = True\n"
            "except Exception:\n"
            "    pass\n", encoding="utf-8")
    except OSError as e:
        return -1, f"MUTACION IMPOSIBLE: no se pudo escribir {fichero} ({e})", False
    try:
        # Se comprueba que el veneno LLEGA de verdad: si no, el caso no
        # demostraria nada y decirlo verde seria mentir.
        sonda = subprocess.run(
            [sys.executable, "-c",
             "import registro_xfail as r; print(r.MUTADO)"],
            cwd=REPO, capture_output=True, text=True, timeout=120)
        llega = sonda.stdout.strip() == "True"
        p = subprocess.run([sys.executable, str(script), *(extra or [])],
                           cwd=REPO, capture_output=True, text=True, timeout=3600)
        return p.returncode, p.stdout + p.stderr, llega
    finally:
        if previo is None:
            fichero.unlink(missing_ok=True)
        else:
            fichero.write_bytes(previo)
        for basura in destino.glob("__pycache__"):
            subprocess.run(["rm", "-rf", str(basura)], timeout=60)


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

    # --- 5b/5c. arranque automatico FUERA del repositorio -----------------
    # `check_ejecucion_real.py` exige `--junit`: sin el, argparse devuelve 2 y
    # el caso mediria el parser, no el control. Se le pasa un informe real.
    for etiqueta, script, extra_arg in (
            ("gate estatico", GATE, []),
            ("capa de resultados", CONTROL, ["--junit", str(INVENTARIO)])):
        print(f"\n########## `usercustomize` fuera del repo, {etiqueta}")
        rc_uc, salida_uc, llega = con_usercustomize_envenenado(script, extra_arg)
        alterado = "ESTADO ALTERADO ANTES DE ARRANCAR" in salida_uc
        print(f"    veneno llega al modulo={llega}  EXIT={rc_uc}  "
              f"lo dice={alterado}")
        anota(f"5 `usercustomize` fuera del repo ({etiqueta})",
              "ROJO por estado alterado",
              f"veneno={llega}, EXIT={rc_uc}, lo dice={alterado}",
              llega and rc_uc == 1 and alterado)

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
