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
        -> `git show <sujeto>:<este fichero>` -EL CODIGO DE LA RAIZ SALE DEL
           OBJETO GIT, NO DEL ARBOL DE TRABAJO-
        -> interprete NUEVO y AISLADO (`python3 -I -`): sin *user site*, sin
           `PYTHONPATH` heredado, sin el directorio del script en `sys.path`,
           y por tanto sin arranques automaticos de Python
        -> este bootstrap, solo stdlib:
             1. identifica el SHA del sujeto
             2. verifica la fuente critica en disco contra ese sujeto Git
             3. comprueba que los modulos criticos AUN NO estan cargados
             4. carga el codigo critico desde la RUTA EXACTA
        -> el gate real

LA RAIZ NO SE AUTOVERIFICA, Y ESO ERA UNA REGRESION CLASICA
==========================================================
`verifica_fuente()` lista este fichero entre los que comprueba, pero si el
codigo que corre es el del ARBOL, esa comprobacion se ejecuta dentro del propio
bootstrap ya modificado: circular. Medido, combinando un reemplazo aqui sin
commitear con un parcheo de `contenido_verificado` -sin tocar ninguna perilla-:
EXIT=0, 0 errores, con un defecto real tragado y `HOT-01` nunca commiteado.

Se cierra sacando la raiz del arbol mutable: `ci.yml` ejecuta el codigo que sale
de `git show <sujeto>:<ruta>`. La verificacion del fichero EN DISCO se conserva
-detecta que disco y sujeto difieren- pero ya no es de quien depende la
honestidad de la raiz.

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

def _raiz_del_repo() -> Path:
    """La raiz, preguntandole a git desde el directorio de trabajo.

    NO se deduce de `__file__`, y eso es deliberado: este codigo se ejecuta
    desde un fichero TEMPORAL fuera del repositorio, asi que su ruta no dice
    nada de donde esta la raiz. Intentar deducirla del sitio del fichero fue lo
    que me llevo a resolver otro checkout entero.
    """
    p = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise SystemExit("::error::no se pudo determinar la raiz del repositorio")
    return Path(p.stdout.strip()).resolve()


REPO = _raiz_del_repo()
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


def soy_el_objeto_git(sha: str) -> list[str]:
    """Los BYTES QUE ESTOY EJECUTANDO vienen del objeto Git del SHA sujeto.

    ESTA es la propiedad que importa, y hubo que reformularla. La version
    anterior comprobaba que `__file__` estuviera en `<raiz>/.github/scripts/`,
    o sea VALIDABA LA MECANICA VIEJA -"el fichero vive donde vivia antes"-. Con
    la raiz materializada en un temporal eso habria rechazado el caso legitimo
    y habria sido otro rojo accidental, que es justo el error que este carril
    lleva quince rondas persiguiendo.

    Lo que se afirma ahora no menciona rutas ni permisos: los bytes en
    ejecucion coinciden con `git show <sujeto>:<ruta del bootstrap>`. Da igual
    si vienen de un temporal en `/tmp`, del fichero del repositorio o de
    cualquier otro sitio: lo que se comprueba es su PROCEDENCIA.

    FALLA CERRADO: si no se puede leer el propio fuente -por ejemplo si el
    codigo llegara por una tuberia y no hubiera fichero que leer- no se puede
    afirmar la procedencia, y entonces es ROJO.
    """
    propio = globals().get("__file__")
    if not propio or not Path(propio).exists():
        return [f"{MOTIVO_INTEGRIDAD}: no hay fichero del que leer los bytes en "
                f"ejecucion (`__file__`={propio!r}), asi que no se puede afirmar "
                f"que vengan del objeto Git del sujeto. Se falla cerrado."]
    en_ejecucion = Path(propio).read_bytes()
    p = _git("show", f"{sha}:.github/scripts/bootstrap_certificacion.py")
    if p.returncode != 0:
        return [f"{MOTIVO_INTEGRIDAD}: el sujeto {sha[:12]} no contiene el "
                f"bootstrap, asi que no hay con que comparar los bytes en "
                f"ejecucion."]
    del_objeto = p.stdout.encode("utf-8")
    if hashlib.sha256(en_ejecucion).hexdigest() != hashlib.sha256(del_objeto).hexdigest():
        return [f"{MOTIVO_INTEGRIDAD}: los bytes que se estan ejecutando NO son "
                f"los del objeto Git del sujeto {sha[:12]}. La raiz de confianza "
                f"tiene que salir del commit que se certifica, no del arbol de "
                f"trabajo ni de ninguna copia intermedia alterada."]
    return []


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
    # EL SHA SUJETO SE PASA, NO SE RE-DEDUCE. La cadena tiene que ser exacta:
    #     SHA sujeto -> objeto Git <SHA>:<bootstrap> -> bootstrap limpio ->
    #     verificacion del codigo critico -> gate
    # Si el bootstrap volviera a resolver el sujeto por su cuenta, el codigo que
    # se ejecuta y el sujeto contra el que se verifica podrian no ser el mismo
    # commit, y toda la cadena dejaria de ser una cadena.
    sujeto_pasado = None
    if argv and argv[0] == "--sujeto":
        if len(argv) < 2:
            print("::error::`--sujeto` sin valor")
            return 2
        sujeto_pasado, argv = argv[1], argv[2:]
    if not argv:
        print("::error::uso: bootstrap_certificacion.py [--sujeto SHA] <gate> [args]")
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

    if sujeto_pasado:
        p = _git("rev-parse", "--verify", f"{sujeto_pasado}^{{commit}}")
        if p.returncode != 0:
            print(f"::error::{MOTIVO_INTEGRIDAD}: el sujeto `{sujeto_pasado}` "
                  f"no es un commit de este repositorio.")
            return 1
        sha, origen = p.stdout.strip(), "--sujeto (el mismo del que salio este codigo)"
    else:
        sha, origen = sujeto()
        if sha is not None:
            print("::warning::sin `--sujeto`: el bootstrap resuelve el commit por "
                  "su cuenta, asi que el codigo que corre y el sujeto contra el "
                  "que se verifica podrian no ser el mismo. En `ci.yml` se pasa.")
    if sha is None:
        print(f"::error::{MOTIVO_INTEGRIDAD}: no se pudo identificar el sujeto "
              f"({origen}). Sin sujeto no hay nada contra lo que verificar la "
              f"fuente critica.")
        return 1
    print(f"bootstrap: sujeto {sha[:12]} ({origen}); aislado={aislado}")

    problemas = soy_el_objeto_git(sha) + sin_precarga() + verifica_fuente(sha)
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
