#!/usr/bin/env python3
"""Calibracion de la RUTA QUE CI EJECUTA DE VERDAD: la base materializada.

POR QUE HACIA FALTA ESTE ARNES
==============================
`calibra_suite_inventory.py` mide SIEMPRE con `--base-fichero`, o sea con una
base ya escrita. Pero en CI el gate no usa esa bandera —esta prohibida ahi—:
DERIVA el merge-base, saca su arbol con `git archive | tar` a un temporal y
mide alli. Esa ruta no la ejercitaba ningun caso.

Y se pago. Al introducir la integridad del registro, el hijo que mide la base
empezo a morir dentro del temporal —que NO es un repositorio git, asi que no hay
commit de referencia— y ademas le faltaba un modulo que el gate habia empezado a
importar. Resultado: sin inventario de base, y el padre certificando con SIETE
controles sin ejecutar (C, C-bis, D, D2, A2, G y X-T), en verde. Sobre arbol
limpio. La calibracion no lo veia porque probaba el instrumento en una
configuracion en la que el producto no corre.

Es exactamente el fallo que este carril persigue —verde por no mirar— un nivel
mas arriba, asi que la ruta real tiene su arnes.

QUE SE COMPRUEBA
================
  1. Sobre arbol limpio y SIN `--base-fichero`: EXIT=0 y la salida tiene que
     decir `MATERIALIZADA`. Si dijera `SIN TRINQUETE`, el caso es ROJO aunque
     el gate salga 0: un verde sin trinquetes no es un verde.
  2. Con la materializacion ROTA de verdad (un `git` que falla solo en
     `archive`): EXIT=1. Antes era EXIT=0 con un aviso enterrado.
  3. Con `--sin-base` PEDIDO a proposito: EXIT=0 con aviso. Es la unica forma
     legitima de quedarse sin base, y tiene que seguir existiendo.
  4. El instrumento prestado al temporal esta COMPLETO: se comprueba que la
     medida de la base devuelve inventario y no None.

NO MUTA NINGUN FICHERO DEL REPOSITORIO. Publica igualmente el SHA-256 de lo que
podria tocar, porque "no lo toco" tambien hay que medirlo.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arnes_comun  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / ".github" / "scripts" / "check_suite_inventory.py"
VIGILADOS = (
    GATE,
    REPO / ".github" / "scripts" / "registro_xfail.py",
    REPO / ".github" / "scripts" / "normaliza_shell.py",
    REPO / ".github" / "suite-inventario.json",
    REPO / ".github" / "xfail-registro.txt",
)

VERDE, ROJO = "VERDE", "ROJO"


def sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def git_que_falla_en_archive() -> Path:
    """Un `git` real salvo para `archive`, que devuelve 1.

    Inyeccion QUIRURGICA: no se rompe git entero —eso tumbaria tambien la
    derivacion del merge-base y el caso no distinguiria una causa de otra—,
    solo el subcomando que materializa.
    """
    tmp = Path(tempfile.mkdtemp(prefix="git-sin-archive-"))
    shim = tmp / "git"
    real = subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip()
    shim.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = "archive" ]; then\n'
        '  echo "fallo inyectado por la calibracion" >&2\n'
        "  exit 1\n"
        "fi\n"
        f'exec {real} "$@"\n',
        encoding="utf-8")
    shim.chmod(0o755)
    return tmp


def clon_con_main_en(sha: str) -> Path:
    """Un clon local del repo con `origin/main` apuntando a `sha`.

    Asi se ejercitan LAS DOS vias de `inventario_base()` sin depender de en cual
    caiga el repositorio hoy:

      * `origin/main` en un commit SIN inventario -> via de MATERIALIZACION
      * `origin/main` en un commit CON inventario -> via RAPIDA (`git show`)

    Hace falta porque el arnes se auto-invalidaba al fusionar: solo era correcto
    MIENTRAS la base no publicara `suite-inventario.json`. En cuanto esto entre
    en `main`, la via rapida seria la real, la nota dejaria de decir
    `MATERIALIZADA` y el job saldria ROJO en `main` el primer dia. Falso rojo,
    y ademas la via que quedaria en produccion se quedaba sin arnes.
    """
    tmp = Path(tempfile.mkdtemp(prefix="clon-base-"))
    destino = tmp / "repo"
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(REPO),
                    str(destino)], check=True, capture_output=True, timeout=900)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", sha],
                   cwd=destino, check=True, capture_output=True, timeout=120)
    return destino


def corre_gate_en(raiz: Path, extra: list[str]) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, ".github/scripts/check_suite_inventory.py", *extra],
        cwd=raiz, capture_output=True, text=True, timeout=3600,
        env=os.environ.copy(),
    )
    return p.returncode, p.stdout + p.stderr


def corre_gate(extra: list[str], entorno: dict | None = None) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(GATE), *extra],
        cwd=REPO, capture_output=True, text=True, timeout=3600,
        env=entorno or os.environ.copy(),
    )
    return p.returncode, p.stdout + p.stderr


def precondicion() -> list[str]:
    """Este arnes EXIGE el mismo checkout que el job donde el gate corre.

    Si no hay historia suficiente para derivar el merge-base con `origin/main`,
    los casos saldrian rojos por una razon que no es la que calibran y la tabla
    confundiria a quien la lea. Medido: colocado en un job con el checkout por
    defecto, dio `SIN TRINQUETE: no hay merge-base con origin/main` y dos
    desviaciones que parecian del producto y eran del sitio donde se le puso.
    Mejor una PRECONDICION explicita que una tabla enganosa.
    """
    problemas = []
    sucio = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                           capture_output=True, text=True).stdout.strip()
    if sucio:
        problemas.append(
            "PRECONDICION: el arbol tiene cambios sin commitear. Este arnes "
            "monta clones aislados para ejercitar las DOS vias de la base, y un "
            "clon solo ve lo COMMITEADO: mediria codigo distinto del que hay "
            "delante. Commitea antes de calibrar.")
    p = subprocess.run(["git", "rev-parse", "--verify", "origin/main^{commit}"],
                       cwd=REPO, capture_output=True, text=True)
    if p.returncode != 0:
        problemas.append(
            "PRECONDICION: no existe `origin/main` en este checkout, asi que no "
            "hay merge-base que materializar. Este arnes ejercita LA RUTA REAL "
            "de la base y necesita el mismo checkout que el job donde el gate "
            "corre de verdad: `fetch-depth: 0`. Sin eso no mide el producto, "
            "mide el sitio donde se le ha puesto.")
    return problemas


def main() -> int:
    fallos_previos = precondicion()
    for e in fallos_previos:
        print(f"::error::{e}")
    if fallos_previos:
        return 1

    hashes = {f: sha(f) for f in VIGILADOS if f.exists()}
    print("SHA-256 ANTES (este arnes NO deberia tocar ninguno):")
    for f, h in hashes.items():
        print(f"  {h}  {f.relative_to(REPO)}")

    filas, fallos = [], 0
    temporales = []

    # --- 1. via de MATERIALIZACION (base SIN inventario publicado) --------
    print("\n########## 1. via de MATERIALIZACION (base sin inventario)")
    # `aaf9695` (main de partida) no publica inventario; si algun dia lo
    # publicara, se busca hacia atras el primer commit que no lo tenga.
    base_sin = None
    p = subprocess.run(["git", "rev-list", "-n", "60", "origin/main"], cwd=REPO,
                       capture_output=True, text=True)
    # OJO con el nombre: `sha` es la funcion de hash de este modulo. Usarla como
    # variable de bucle la convertia en local de `main()` y reventaba la primera
    # linea con `UnboundLocalError`. Lo caza la EJECUCION, no el AST: el nombre
    # existe a nivel de modulo, asi que el control de nombres definidos no tiene
    # nada que objetar. Otro recordatorio de que los arneses hay que correrlos.
    for candidato in p.stdout.split():
        q = subprocess.run(["git", "cat-file", "-e",
                            f"{candidato}:.github/suite-inventario.json"],
                           cwd=REPO, capture_output=True)
        if q.returncode != 0:
            base_sin = candidato
            break
    if base_sin is None:
        print("  (no hay ningun commit reciente SIN inventario: via no ejercitable)")
        ok = False
        detalle = "no ejercitable"
        rc = -1
    else:
        clon = clon_con_main_en(base_sin)
        temporales.append(clon.parent)
        rc, salida = corre_gate_en(clon, [])
        materializada = "MATERIALIZADA" in salida
        sin_trinquete = "SIN TRINQUETE" in salida
        ok = (rc == 0) and materializada and not sin_trinquete
        detalle = f"EXIT={rc}, MATERIALIZADA={materializada}"
        print(f"  base sin inventario: {base_sin[:8]}")
        print(f"  EXIT={rc}  MATERIALIZADA={materializada}  SIN TRINQUETE={sin_trinquete}")
    fallos += 0 if ok else 1
    filas.append(("1 via de MATERIALIZACION (base sin inventario)",
                  "VERDE y nota MATERIALIZADA", detalle,
                  "OK" if ok else "**DESVIACION**"))

    # --- 1b. via RAPIDA (base CON inventario publicado) -------------------
    # ESTA es la via que quedara en produccion en cuanto el carril se fusione,
    # y hasta ahora no la ejercitaba nadie.
    print("\n########## 1b. via RAPIDA (base con inventario publicado)")
    sha_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                              capture_output=True, text=True).stdout.strip()
    clon2 = clon_con_main_en(sha_head)
    temporales.append(clon2.parent)
    rc1b, salida1b = corre_gate_en(clon2, [])
    rapida = f"base {sha_head[:8]}" in salida1b
    sin_trinquete1b = "SIN TRINQUETE" in salida1b
    ok1b = (rc1b == 0) and rapida and not sin_trinquete1b
    print(f"  EXIT={rc1b}  via rapida={rapida}  SIN TRINQUETE={sin_trinquete1b}")
    fallos += 0 if ok1b else 1
    filas.append(("1b via RAPIDA (base con inventario) = la de post-fusion",
                  "VERDE con trinquete aplicado",
                  f"EXIT={rc1b}, via rapida={rapida}",
                  "OK" if ok1b else "**DESVIACION**"))

    # --- 2. materializacion ROTA -> ROJO, no verde con aviso --------------
    #
    # EN UN CLON con la base SIN inventario, no en el repo ambiente. Medido en
    # un clon post-fusion: sobre el repo ambiente, cuando la base YA publica
    # inventario se toma la via rapida, `git archive` no llega a usarse y
    # `INSTRUMENTO ROTO` no aparece nunca. O sea que este caso solo era correcto
    # mientras la base no publicara inventario: exactamente la trampa que ya se
    # arreglo para los casos 1 y 1b, dejada a medias aqui. Al integrar los
    # carriles habria puesto «Calibracion de gates» ROJO en `main`.
    print("\n########## 2. materializacion ROTA (`git archive` falla)")
    tmp = git_que_falla_en_archive()
    temporales.append(tmp)
    entorno = os.environ.copy()
    entorno["PATH"] = f"{tmp}{os.pathsep}{entorno.get('PATH', '')}"
    if base_sin is None:
        rc2, instrumento = -1, False
        print("  (sin base sin inventario: no ejercitable)")
    else:
        clon3 = clon_con_main_en(base_sin)
        temporales.append(clon3.parent)
        p2 = subprocess.run(
            [sys.executable, ".github/scripts/check_suite_inventory.py"],
            cwd=clon3, capture_output=True, text=True, timeout=3600, env=entorno)
        rc2 = p2.returncode
        instrumento = "INSTRUMENTO ROTO" in (p2.stdout + p2.stderr)
    ok2 = (rc2 == 1) and instrumento
    print(f"  EXIT={rc2}  dice INSTRUMENTO ROTO={instrumento}")
    fallos += 0 if ok2 else 1
    filas.append(("2 materializacion rota (en clon con base sin inventario)",
                  "ROJO (no verde con aviso)",
                  f"EXIT={rc2}, INSTRUMENTO ROTO={instrumento}",
                  "OK" if ok2 else "**DESVIACION**"))

    # --- 3. `--sin-base` PEDIDO -> verde con aviso ------------------------
    #
    # "Pedido a proposito" ya no puede ser desde la LINEA DE COMANDOS: esa
    # invocacion no certifica nada y por eso es ROJO desde que el desarme se
    # cerro por propiedad. La forma legitima es la que usan los arneses: llamar
    # a `main()` dentro del propio proceso. Se comprueban las DOS caras.
    print("\n########## 3. `--sin-base` pedido a proposito (en proceso)")
    rc3, salida3 = arnes_comun.ejecuta_gate(
        "check_suite_inventory", ["--sin-base"], ablacion="", timeout=2400)
    aviso = "SIN TRINQUETE" in salida3
    ok3 = (rc3 == 0) and aviso
    print(f"  EXIT={rc3}  avisa={aviso}")
    fallos += 0 if ok3 else 1
    filas.append(("3 `--sin-base` en proceso (arnes)", "VERDE con aviso",
                  f"EXIT={rc3}, avisa={aviso}", "OK" if ok3 else "**DESVIACION**"))

    print("\n########## 3b. `--sin-base` desde la LINEA DE COMANDOS")
    rc3b, _ = corre_gate(["--sin-base"])
    ok3b = rc3b == 1
    print(f"  EXIT={rc3b}")
    fallos += 0 if ok3b else 1
    filas.append(("3b `--sin-base` desde linea de comandos",
                  "ROJO (no certifica nada)", f"EXIT={rc3b}",
                  "OK" if ok3b else "**DESVIACION**"))

    # --- 4. el instrumento prestado esta COMPLETO -------------------------
    print("\n########## 4. la medida de la base devuelve inventario")
    sys.path.insert(0, str(REPO / ".github" / "scripts"))
    import check_suite_inventory as G  # noqa: E402
    datos_base, nota = G.inventario_base()
    ok4 = datos_base is not None and bool(datos_base.get("modulos"))
    print(f"  nota: {nota}")
    print(f"  modulos en la base: "
          f"{len(datos_base['modulos']) if datos_base else 'NINGUNO'}")
    fallos += 0 if ok4 else 1
    filas.append(("4 instrumento prestado completo", "inventario no vacio",
                  nota[:60], "OK" if ok4 else "**DESVIACION**"))

    for t in temporales:
        shutil.rmtree(t, ignore_errors=True)

    print("\n===== SHA-256 DESPUES =====")
    for f, esperado in hashes.items():
        real = sha(f)
        marca = "OK" if real == esperado else "**NO COINCIDE**"
        fallos += 0 if real == esperado else 1
        print(f"  {marca}  {real}  {f.relative_to(REPO)}")

    print("\n\n===== TABLA (ruta de la base que CI ejecuta) =====\n")
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
