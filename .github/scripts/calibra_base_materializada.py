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


def corre_gate(extra: list[str], entorno: dict | None = None) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(GATE), *extra],
        cwd=REPO, capture_output=True, text=True, timeout=3600,
        env=entorno or os.environ.copy(),
    )
    return p.returncode, p.stdout + p.stderr


def main() -> int:
    hashes = {f: sha(f) for f in VIGILADOS if f.exists()}
    print("SHA-256 ANTES (este arnes NO deberia tocar ninguno):")
    for f, h in hashes.items():
        print(f"  {h}  {f.relative_to(REPO)}")

    filas, fallos = [], 0
    temporales = []

    # --- 1. la ruta REAL, sobre arbol limpio ------------------------------
    print("\n########## 1. materializacion REAL (como corre en CI)")
    rc, salida = corre_gate([])
    materializada = "MATERIALIZADA" in salida
    sin_trinquete = "SIN TRINQUETE" in salida
    ok = (rc == 0) and materializada and not sin_trinquete
    print(f"  EXIT={rc}  MATERIALIZADA={materializada}  SIN TRINQUETE={sin_trinquete}")
    fallos += 0 if ok else 1
    filas.append(("1 ruta REAL sobre arbol limpio", "VERDE con base medida",
                  f"EXIT={rc}, MATERIALIZADA={materializada}",
                  "OK" if ok else "**DESVIACION**"))

    # --- 2. materializacion ROTA -> ROJO, no verde con aviso --------------
    print("\n########## 2. materializacion ROTA (`git archive` falla)")
    tmp = git_que_falla_en_archive()
    temporales.append(tmp)
    entorno = os.environ.copy()
    entorno["PATH"] = f"{tmp}{os.pathsep}{entorno.get('PATH', '')}"
    rc2, salida2 = corre_gate([], entorno)
    instrumento = "INSTRUMENTO ROTO" in salida2
    ok2 = (rc2 == 1) and instrumento
    print(f"  EXIT={rc2}  dice INSTRUMENTO ROTO={instrumento}")
    fallos += 0 if ok2 else 1
    filas.append(("2 materializacion rota", "ROJO (no verde con aviso)",
                  f"EXIT={rc2}, INSTRUMENTO ROTO={instrumento}",
                  "OK" if ok2 else "**DESVIACION**"))

    # --- 3. `--sin-base` PEDIDO -> verde con aviso ------------------------
    print("\n########## 3. `--sin-base` pedido a proposito")
    rc3, salida3 = corre_gate(["--sin-base"])
    aviso = "SIN TRINQUETE" in salida3
    ok3 = (rc3 == 0) and aviso
    print(f"  EXIT={rc3}  avisa={aviso}")
    fallos += 0 if ok3 else 1
    filas.append(("3 `--sin-base` explicito", "VERDE con aviso",
                  f"EXIT={rc3}, avisa={aviso}", "OK" if ok3 else "**DESVIACION**"))

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
