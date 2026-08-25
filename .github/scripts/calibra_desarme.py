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
