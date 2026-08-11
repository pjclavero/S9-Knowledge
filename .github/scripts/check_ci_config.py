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

   Y la misma familia de fallo una vuelta mas arriba: mirar SOLO
   `on.push.branches` deja tres vias de escape que no lo tocan. Bajo `on.push`,
   un `paths-ignore: ['**']` apaga CI en TODAS las ramas, un `branches-ignore`
   recorta la cobertura universal por detras, y `paths` la acota; con
   `branches: ['**']` intacto, el gate seguia VERDE en los tres casos. Ademas
   el gate solo miraba `ci.yml`, asi que `supply-chain.yml` —el unico workflow
   que audita dependencias— podia volver a una lista blanca sin que nada se
   pusiera rojo. Ahora se exige la propiedad en AMBOS workflows y la sola
   presencia de esos campos es un fallo: una barrera que puede dejar de
   evaluarse sin ponerse roja no es una barrera.

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
WORKFLOWS = REPO / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
SUPPLY = WORKFLOWS / "supply-chain.yml"
FRAGMENTO_NODE = REPO / ".github" / "ci-fragments" / "test-graph-js.yml"

# Todos los workflows cuya politica de disparo se EXIGE universal. No basta con
# `ci.yml`: `supply-chain.yml` es el unico que audita dependencias, y si vuelve
# a una lista blanca de prefijos reproduce exactamente el agujero silencioso
# que este gate existe para cerrar.
WORKFLOWS_VIGILADOS = (CI, SUPPLY)

# Campos que, bajo `on.push`, pueden APAGAR CI sin tocar `branches`. Son la
# via de escape de este gate: con `branches: ['**']` intacto —y por tanto el
# gate en verde— un `paths-ignore: ['**']` deja de ejecutar CI en TODAS las
# ramas, y un `branches-ignore` recorta la cobertura universal por detras.
# Igual que el defecto original: la barrera deja de evaluarse y nada se pone
# rojo. Por eso su sola presencia es un fallo, no un aviso.
CAMPOS_SILENCIADORES = ("paths", "paths-ignore", "branches-ignore")

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


def bloque_push(texto: str, nombre: str) -> str:
    """Devuelve el cuerpo del bloque `on.push` de un workflow."""
    m = re.search(r"^  push:\n((?:    .*\n|\n)+)", texto, re.M)
    if not m:
        raise SystemExit(f"ERROR: no se encuentra el bloque `on.push` en {nombre}")
    return m.group(1)


def comprueba_silenciadores(bloque: str, nombre: str) -> list[str]:
    """Ningun campo de `on.push` puede apagar CI por detras de `branches`."""
    errores = []
    for campo in CAMPOS_SILENCIADORES:
        if re.search(rf"^    {re.escape(campo)}:", bloque, re.M):
            errores.append(
                f"{nombre}: `on.push` declara `{campo}`. Ese campo puede APAGAR "
                f"CI en silencio sin tocar `branches`: con `branches: ['**']` "
                f"intacto, un `paths-ignore: ['**']` deja de ejecutar CI en "
                f"todas las ramas y un `branches-ignore` recorta la cobertura "
                f"universal por detras; en ambos casos la barrera deja de "
                f"evaluarse y NADA se pone rojo. La politica de disparo tiene "
                f"que ser `branches: ['**']` y nada mas. Si de verdad hace "
                f"falta acotar por rutas, hazlo dentro del job (un paso que "
                f"decida y lo deje escrito), no en el disparador."
            )
    return errores


def patrones_push(texto: str, nombre: str) -> list[str]:
    """Extrae `on.push.branches`, en forma de lista inline o de guiones."""
    bloque = bloque_push(texto, nombre)
    inline = re.search(r"^    branches:\s*\[(.+)\]\s*$", bloque, re.M)
    if inline:
        crudo = inline.group(1).split(",")
    else:
        lista = re.search(r"^    branches:\s*\n((?:      -.*\n|      #.*\n)+)", bloque, re.M)
        if not lista:
            raise SystemExit(f"ERROR: no se encuentra `on.push.branches` en {nombre}")
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


def comprueba_ramas(texto: str, nombre: str) -> list[str]:
    """La politica debe cubrir CUALQUIER rama, no una lista de las de hoy."""
    # 0. Antes que la cobertura: que no haya un campo capaz de apagar CI sin
    #    que `branches` cambie. Si lo hay, `branches` ya no decide nada.
    silenciadores = comprueba_silenciadores(bloque_push(texto, nombre), nombre)

    patrones = patrones_push(texto, nombre)
    print(f"{nombre}: patrones de `on.push.branches`: {patrones}")

    # 1. La propiedad. Se prueba contra nombres inventados, que es lo que
    #    ninguna lista blanca puede cubrir.
    sin_cubrir = [r for r in RAMAS_SONDA if not cubierta(r, patrones)]
    if sin_cubrir:
        return silenciadores + [
            f"{nombre}: `on.push.branches` NO cubre toda rama: no dispararian CI, entre "
            f"otros, {sin_cubrir}. La reparacion NO es anadir esos nombres "
            "(son inventados, y manana seran otros) sino dejar la politica "
            "universal:\n"
            "      push:\n"
            "        branches:\n"
            "          - '**'\n"
            f"    Asi una rama nueva tiene CI el dia que nace, sin editar {nombre}."
        ]

    # 2. Ademas, y como red por si la propiedad se cumpliera por accidente:
    #    ninguna rama que exista HOY en origin puede quedarse fuera.
    errores = list(silenciadores)
    for rama in sorted(set(ramas_remotas())):
        if any(fnmatch.fnmatch(rama, e) for e in EXENTAS):
            continue
        if not cubierta(rama, patrones):
            errores.append(
                f"{nombre}: la rama `{rama}` existe en origin y NO dispara CI al hacer push"
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
    errores = []
    for ruta in WORKFLOWS_VIGILADOS:
        if not ruta.exists():
            errores.append(
                f"{ruta.name}: el workflow no existe. Se exige su politica de "
                f"disparo universal; si desaparece, la comprobacion no puede "
                f"darse por satisfecha en silencio."
            )
            continue
        errores += comprueba_ramas(ruta.read_text(encoding="utf-8"), ruta.name)

    errores += comprueba_node(CI.read_text(encoding="utf-8"))

    for e in errores:
        print(f"::error::{e}")
    if errores:
        print(f"\nFALLO: {len(errores)} problema(s) de configuracion de CI")
        return 1
    print(
        "OK: ci.yml y supply-chain.yml disparan en toda rama, sin campos que "
        "puedan apagar CI en silencio, y sin tests que se omitan por falta de Node"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
