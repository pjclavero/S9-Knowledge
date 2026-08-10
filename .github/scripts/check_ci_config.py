#!/usr/bin/env python3
"""Comprobaciones de configuracion del propio CI.

Dos fallos silenciosos reales de este repositorio, convertidos en gate:

1. `on.push.branches` era una lista blanca de prefijos. Una rama cuya familia
   no estuviera escrita a mano NO disparaba CI al hacer push, y no habia
   ningun aviso: el carril `test/viewer-browser-e2e-v1` se desarrollo entero
   sin senal.

   La primera version de este gate comparaba las ramas de `origin` con los
   patrones del workflow. Detectaba el agujero, pero la unica reparacion que
   ofrecia era anadir un prefijo mas, asi que el ciclo se repitio tres veces
   (`test/**`; luego `ops/**` y `dependabot/**`; luego `perf/**`) y a la
   cuarta habia otras nueve ramas descubiertas. Un gate que solo sabe pedir
   mantenimiento manual convierte el defecto en rutina.

   Ahora se comprueba la PROPIEDAD, no la lista: que CUALQUIER nombre de rama
   —los que existen hoy en `origin` y ademas una bateria de nombres
   deliberadamente inventados, de familias que aun no existen— quede cubierto
   por `on.push.branches`. Solo un patron universal (`**`) satisface eso; una
   lista blanca, por larga que sea, falla contra los nombres inventados. Es
   decir: no se puede aprobar el gate disfrazando la lista blanca.

2. Un test que se auto-omite cuando falta una herramienta (`shutil.which(...)`
   + `skipif`) es una prueba que no existe el dia que el runner cambie de
   imagen, y el job sigue en verde. Si aparece un test de este tipo apoyado en
   Node, tiene que existir un job que instale Node y lo ejecute con guardia
   antisalto.

Sin dependencias externas: el workflow se lee con un parser minimo de las
pocas formas YAML que aqui se usan, para que el gate funcione en cualquier
runner sin instalar nada.
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CI = REPO / ".github" / "workflows" / "ci.yml"
FRAGMENTO_NODE = REPO / ".github" / "ci-fragments" / "test-graph-js.yml"

# Ramas efimeras de maquina: no se les EXIGE CI. Con la politica universal
# `**` de todas formas la tienen, y esto solo evita que su ausencia se pueda
# alegar como excusa; la exencion sigue siendo EXPLICITA y esta a la vista.
EXENTAS = ("worktree-*", "gh-readonly-queue/*", "revert-*")

# Nombres INVENTADOS a proposito. No son ramas reales ni pretenden serlo: son
# la calibracion del gate. Representan familias que hoy no existen y que
# manana apareceran igual que aparecieron `work/`, `impl/` e `integration/`.
#
# Su unico proposito es que una lista blanca NO pueda pasar el gate: para
# cubrirlos haria falta escribirlos, y no se pueden escribir porque no se
# sabe cuales seran. Si alguien anade estos nombres literalmente a ci.yml
# para poner el gate en verde, se ha saltado la comprobacion a mano y la
# revision lo vera en el diff.
RAMAS_SONDA = (
    # Familias reales que la lista blanca ya dejo sin cubrir alguna vez.
    "main",
    "feat/lo-que-sea",
    "fix/lo-que-sea",
    "test/lo-que-sea",
    "ops/lo-que-sea",
    "perf/lo-que-sea",
    "dependabot/pip/lo-que-sea",
    "work",
    "work-carril-a",
    "impl/lo-que-sea",
    "integration/lo-que-sea",
    "docs-estado-verificado",
    # Y familias que no existen: el corazon de la calibracion.
    "familia-que-aun-no-existe",
    "familia/que/aun/no/existe",
    "zzz-inventada-2099/sub/rama",
    "UPPERCASE-Y-Simbolos_.raros/x",
)


def patrones_push(texto: str) -> list[str]:
    """Extrae `on.push.branches`, en forma de lista inline o de guiones."""
    m = re.search(r"^  push:\n((?:    .*\n|\n)+)", texto, re.M)
    if not m:
        raise SystemExit("ERROR: no se encuentra el bloque `on.push` en ci.yml")
    bloque = m.group(1)
    inline = re.search(r"^    branches:\s*\[(.+)\]\s*$", bloque, re.M)
    if inline:
        crudo = inline.group(1).split(",")
    else:
        lista = re.search(r"^    branches:\s*\n((?:      -.*\n|      #.*\n)+)", bloque, re.M)
        if not lista:
            raise SystemExit("ERROR: no se encuentra `on.push.branches` en ci.yml")
        crudo = [
            linea.split("-", 1)[1]
            for linea in lista.group(1).splitlines()
            if linea.strip().startswith("- ")
        ]
    patrones = []
    for pieza in crudo:
        pieza = pieza.split("#", 1)[0].strip().strip("'\"")
        if pieza:
            patrones.append(pieza)
    return patrones


def cubierta(rama: str, patrones: list[str]) -> bool:
    for p in patrones:
        # En los filtros de GitHub, `**` casa tambien con `/`; `fnmatch` trata
        # `*` como comodin sin distinguir separadores, que es exactamente el
        # comportamiento de `**`. Para `*` (un solo segmento) hay que excluir
        # los que llevan `/` despues del prefijo.
        if p.endswith("/**"):
            # `feat/**` cubre `feat/x` y `feat/x/y`, pero NO la rama `feat`.
            if rama.startswith(p[:-3] + "/"):
                return True
        elif "*" in p:
            if fnmatch.fnmatch(rama, p) and (
                "/" not in rama[len(p.split("*", 1)[0]):] or "**" in p
            ):
                return True
        elif rama == p:
            return True
    return False


def ramas_remotas() -> list[str]:
    try:
        salida = subprocess.run(
            ["git", "ls-remote", "--heads", "origin"],
            cwd=REPO, capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        print(f"AVISO: no se pudo consultar origin ({exc}); se usan refs locales")
        salida = None
    if salida is None or salida.returncode != 0:
        salida = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname)", "refs/remotes/origin"],
            cwd=REPO, capture_output=True, text=True, timeout=60,
        )
        if salida.returncode != 0:
            print("AVISO: sin acceso a las ramas; se omite la comprobacion de prefijos")
            return []
    ramas = []
    for linea in salida.stdout.splitlines():
        ref = linea.split()[-1]
        for prefijo in ("refs/heads/", "refs/remotes/origin/"):
            if ref.startswith(prefijo):
                ramas.append(ref[len(prefijo):])
    return [r for r in ramas if r and r != "HEAD"]


def comprueba_ramas(texto: str) -> list[str]:
    """La politica debe cubrir CUALQUIER rama, no una lista de las de hoy."""
    patrones = patrones_push(texto)
    print(f"patrones de `on.push.branches`: {patrones}")

    # 1. La propiedad. Se prueba contra nombres inventados, que es lo que
    #    ninguna lista blanca puede cubrir.
    sin_cubrir = [r for r in RAMAS_SONDA if not cubierta(r, patrones)]
    if sin_cubrir:
        return [
            "`on.push.branches` NO cubre toda rama: no dispararian CI, entre "
            f"otros, {sin_cubrir}. La reparacion NO es anadir esos nombres "
            "(son inventados, y manana seran otros) sino dejar la politica "
            "universal:\n"
            "      push:\n"
            "        branches:\n"
            "          - '**'\n"
            "    Asi una rama nueva tiene CI el dia que nace, sin editar ci.yml."
        ]

    # 2. Ademas, y como red por si la propiedad se cumpliera por accidente:
    #    ninguna rama que exista HOY en origin puede quedarse fuera.
    errores = []
    for rama in sorted(set(ramas_remotas())):
        if any(fnmatch.fnmatch(rama, e) for e in EXENTAS):
            continue
        if not cubierta(rama, patrones):
            errores.append(
                f"la rama `{rama}` existe en origin y NO dispara CI al hacer push"
            )
    return errores


def comprueba_node(texto: str) -> list[str]:
    """Todo test que dependa de Node debe tener un job que instale Node."""
    sospechosos = []
    for py in REPO.rglob("*/tests/**/test_*.py"):
        if any(parte in (".git", "node_modules", ".venv") for parte in py.parts):
            continue
        try:
            cuerpo = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"which\(\s*[\"']node[\"']\s*\)", cuerpo):
            sospechosos.append(py.relative_to(REPO).as_posix())
    if not sospechosos:
        return []
    errores = []
    hay_setup_node = "actions/setup-node" in texto
    for ruta in sospechosos:
        if not hay_setup_node:
            errores.append(
                f"{ruta} se auto-omite si falta Node y ningun job de ci.yml usa "
                f"actions/setup-node: esas pruebas se saltarian en verde. "
                f"Anade el job preparado en {FRAGMENTO_NODE.relative_to(REPO)}"
            )
        elif ruta not in texto:
            errores.append(
                f"{ruta} depende de Node y ningun job de ci.yml lo ejecuta por "
                f"nombre; sin eso solo corre en jobs sin Node, donde se omite"
            )
    return errores


def main() -> int:
    texto = CI.read_text(encoding="utf-8")
    errores = comprueba_ramas(texto) + comprueba_node(texto)
    for e in errores:
        print(f"::error::{e}")
    if errores:
        print(f"\nFALLO: {len(errores)} problema(s) de configuracion de CI")
        return 1
    print("OK: prefijos de rama cubiertos y sin tests que se omitan por falta de Node")
    return 0


if __name__ == "__main__":
    sys.exit(main())
