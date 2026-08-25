#!/usr/bin/env python3
"""Raiz de confianza de la certificacion. Solo stdlib.

LA REGLA QUE OBLIGO A ESCRIBIR ESTO
===================================
    Un proceso potencialmente contaminado no puede certificarse a si mismo
    comparando una coleccion de atributos de ese mismo proceso.

Las rondas anteriores hicieron justo eso: comprobar unas perillas, luego el
`__file__` de unos modulos, luego el bytecode de unas funciones. Cada vuelta
cerraba el mecanismo encontrado y aparecia el siguiente -el ultimo fue un
`usercustomize` que engancha `builtins.__import__` y SUSTITUYE
`registro_xfail.contenido_verificado`, sin tocar ninguna perilla ni cambiar
ningun `__file__`: EXIT=0 con un defecto real tragado-. Anadir el hash de esa
funcion habria sido el caso N+1 de una lista, no una propiedad.

LO QUE SE AFIRMA AHORA, y es lo unico que se afirma
===================================================
    El gate no confia en modulos del proyecto ni en estado mutable heredado de
    un proceso anterior: ejecuta su certificacion en un interprete aislado y
    carga el codigo critico desde el sujeto Git verificado.

No se promete cubrir "cualquier mecanismo que se invente manana". Esa garantia
seria absoluta, innecesaria y no medible. La de arriba SI es medible, y cada
pieza tiene su fila en `calibra_desarme.py`.

LA ARQUITECTURA
===============
    CI / lanzador
        -> interprete NUEVO y AISLADO (`python3 -I`): sin *user site*, sin
           `PYTHONPATH` heredado, sin el directorio del script en `sys.path`,
           y por tanto sin arranques automaticos de Python
        -> este bootstrap, solo stdlib:
             1. identifica el SHA del sujeto
             2. verifica la fuente critica en disco contra ese sujeto Git
             3. comprueba que los modulos criticos AUN NO estan cargados
             4. carga el codigo critico desde la RUTA EXACTA
        -> el gate real

El aislamiento ya no es "defensa secundaria opcional": es parte de la
arquitectura. Pero el bootstrap tiene que seguir detectando contaminacion
AUNQUE ALGUIEN RETIRE EL AISLAMIENTO -por eso los pasos 2 y 3 se ejecutan
siempre, y por eso tienen fila propia en la calibracion-.

SOBRE LAS DEPENDENCIAS
======================
`-I` deja fuera el *user site*, donde en algunas maquinas vive PyYAML. El
bootstrap vuelve a poner ESA RUTA en `sys.path` DESPUES del arranque, que es
justo la diferencia que importa: tener las dependencias disponibles no es lo
mismo que ejecutar los ganchos de arranque que viven en ese directorio. Los
modulos del PROYECTO no se buscan ahi: se cargan de su ruta exacta y verificada.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import site
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / ".github" / "scripts"

# Codigo del proyecto del que depende la certificacion. Se verifica contra el
# sujeto Git y se carga de su ruta exacta.
CRITICOS = ("normaliza_shell", "registro_xfail", "estado_de_fabrica")

# Banderas que convierten una ejecucion en MEDICION y no en certificacion.
NO_CERTIFICAN = ("--sin-base", "--base-fichero", "--solo-registro")

MOTIVO_INTEGRIDAD = "INTEGRIDAD DEL SUJETO"
MOTIVO_PRECARGA = "MODULO CRITICO YA CARGADO"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                          text=True, timeout=180)


def sujeto() -> tuple[str | None, str]:
    """El commit que se esta certificando, y de donde sale."""
    sha = os.environ.get("GITHUB_SHA", "").strip()
    if sha:
        p = _git("rev-parse", "--verify", f"{sha}^{{commit}}")
        if p.returncode == 0:
            return p.stdout.strip(), "GITHUB_SHA (el arbol que ejecuta el job)"
    p = _git("rev-parse", "--verify", "HEAD^{commit}")
    if p.returncode == 0:
        return p.stdout.strip(), "git rev-parse HEAD"
    return None, "no se pudo resolver ningun commit"


def verifica_fuente(sha: str) -> list[str]:
    """La fuente critica EN DISCO tiene que ser la del sujeto Git."""
    problemas = []
    for nombre in (*CRITICOS, "check_suite_inventory", "check_ejecucion_real",
                   "bootstrap_certificacion"):
        rel = f".github/scripts/{nombre}.py"
        fichero = REPO / rel
        if not fichero.exists():
            problemas.append(f"{MOTIVO_INTEGRIDAD}: falta `{rel}` en disco.")
            continue
        p = _git("show", f"{sha}:{rel}")
        if p.returncode != 0:
            problemas.append(
                f"{MOTIVO_INTEGRIDAD}: `{rel}` no existe en el sujeto "
                f"{sha[:12]}. Codigo que no esta en el commit no se revisa en "
                f"ningun diff.")
            continue
        en_git = hashlib.sha256(p.stdout.encode("utf-8")).hexdigest()
        en_disco = hashlib.sha256(
            fichero.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        if en_git != en_disco:
            problemas.append(
                f"{MOTIVO_INTEGRIDAD}: `{rel}` en disco NO coincide con el "
                f"sujeto {sha[:12]} (disco {en_disco[:16]}..., commit "
                f"{en_git[:16]}...). La certificacion ejercitaria codigo que no "
                f"es el que se certifica.")
    return problemas


def sin_precarga() -> list[str]:
    """Ningun modulo critico puede estar YA cargado cuando llega el bootstrap.

    Si lo estuviera, alguien lo metio antes -precargado o manipulado- y este
    proceso ya no puede afirmar que el codigo en uso sea el del sujeto.
    """
    return [
        f"{MOTIVO_PRECARGA}: `{nombre}` ya estaba en `sys.modules` antes de que "
        f"el bootstrap lo cargara desde su ruta verificada. Alguien lo precargo "
        f"o lo manipulo, y desde aqui ya no se puede afirmar de que fichero "
        f"viene el codigo que se ejecutaria."
        for nombre in (*CRITICOS, "check_suite_inventory", "check_ejecucion_real")
        if nombre in sys.modules
    ]


def carga_exacto(nombre: str):
    """Carga desde la RUTA EXACTA, sin pasar por `sys.path` ni por `__import__`."""
    ruta = SCRIPTS / f"{nombre}.py"
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    if spec is None or spec.loader is None:
        raise ImportError(f"no se pudo preparar {ruta}")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("::error::uso: bootstrap_certificacion.py <ruta-del-gate> [args]")
        return 2
    ruta_gate, resto = argv[0], argv[1:]
    nombre_gate = Path(ruta_gate).stem

    aislado = bool(getattr(sys.flags, "isolated", 0)) or (
        bool(getattr(sys.flags, "no_user_site", 0))
        and bool(getattr(sys.flags, "ignore_environment", 0)))
    if not aislado:
        # No se aborta: la fila G de la calibracion exige que, retirado el
        # aislamiento, las barreras internas SIGAN detectando lo que alcance al
        # codigo critico. Se avisa para que no pase inadvertido.
        print("::warning::AISLAMIENTO RETIRADO: este bootstrap no corre en un "
              "interprete aislado (`-I`). Las comprobaciones de integridad y de "
              "precarga siguen ejecutandose, pero el arranque automatico de "
              "Python SI ha podido correr.")

    for bandera in NO_CERTIFICAN:
        if bandera in resto:
            print(f"::error::`{bandera}` en una ejecucion de CERTIFICACION. Esa "
                  f"bandera cambia contra que se compara o que se comprueba, "
                  f"asi que el verde que produjera no incluiria la garantia.")
            return 1

    sha, origen = sujeto()
    if sha is None:
        print(f"::error::{MOTIVO_INTEGRIDAD}: no se pudo identificar el sujeto "
              f"({origen}). Sin sujeto no hay nada contra lo que verificar la "
              f"fuente critica.")
        return 1
    print(f"bootstrap: sujeto {sha[:12]} ({origen}); aislado={aislado}")

    problemas = sin_precarga() + verifica_fuente(sha)
    for e in problemas:
        print(f"::error::{e}")
    if problemas:
        return 1

    for nombre in CRITICOS:
        carga_exacto(nombre)
    gate = carga_exacto(nombre_gate)
    return int(gate.main(resto))


if __name__ == "__main__":
    sys.path.append(site.getusersitepackages())
    sys.exit(main())
