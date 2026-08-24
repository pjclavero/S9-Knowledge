#!/usr/bin/env python3
"""FUENTE UNICA de las excepciones `xfail`: lectura VERIFICADA del registro.

POR QUE ESTE MODULO EXISTE
==========================
Todos los controles que vigilan `xfail` —A5, A7 y D2/X-T en
`check_suite_inventory.py`, y la capa de resultados en
`check_ejecucion_real.py`— tienen que consumir EXACTAMENTE el mismo registro.
Cuando cada capa lo leia por su cuenta aparecio el defecto de siempre
desplazado un control: X-T respetaba una entrada legitima y D2 la bloqueaba
igual, asi que el patron de defecto conocido seguia siendo imposible de anadir.
Una escotilla reconocida por una capa y prohibida por otra no es una escotilla.
Se cierra por construccion: una sola implementacion, importada por todos.

LA PROPIEDAD, NO LA ENUMERACION
===============================
No se persigue COMO se escribe el registro durante CI. La version anterior
enumeraba operadores (`>`, `>>`, `tee`, `sed -i`, `cp`, `mv`) en las lineas de
`ci.yml` que nombraran el fichero, y se atraveso partiendo la referencia:

    REG=.github/xfail-registro.txt      <- nombra, no escribe
    echo "AUTO-01 | ..." >> "$REG"      <- escribe, no nombra

Y un `python3 scripts/lo_que_sea.py` ni siquiera menciona el fichero. Se
comprueba la PROPIEDAD: el registro que la ejecucion USA tiene que ser, byte a
byte, el que hay en el COMMIT que se esta certificando. Eso cubre por
construccion el nombre construido, `$GITHUB_ENV`, un helper, un paso `uses:`
local, un `conftest.py` escribiendo en tiempo de import, `PYTHONPATH` +
`sitecustomize`, y lo que se invente manana.

LA REFERENCIA SALE DE GIT. NUNCA DEL ARBOL. Y SIN RESPALDO.
===========================================================
`git show <commit>:<ruta>` es la REFERENCIA; el fichero del arbol es el
SUJETO. Nunca al reves, y no hay `except` que caiga al arbol si git falla:
ese respaldo seria exactamente el agujero, porque bastaria con romper git para
que el sujeto pasara a ser su propia referencia. Si git no puede dar la
referencia, es ROJO.

Esto ademas hace el veredicto independiente del estado del DIRECTORIO: da igual
que haya `__pycache__`, ficheros ignorados o basura de otra corrida. Lo que se
compara es contenido versionado contra contenido en disco.

SIN VENTANA TEMPORAL (TOCTOU)
=============================
Verificar y consumir son la MISMA llamada, y lo que se devuelve a los
consumidores es el contenido DE GIT, no el del arbol. Asi no existe el hueco
"valido al principio del job y confio despues": cada lectura revalida, y aunque
alguien escribiera el fichero entre dos lecturas, (a) la siguiente lectura lo
detecta y (b) el contenido consumido nunca fue el suyo.

CUAL ES EL COMMIT DE REFERENCIA
===============================
El que se esta CERTIFICANDO, no un `HEAD` ambiguo. En un runner con
`actions/checkout` sobre `pull_request`, `HEAD` es un commit de MERGE efimero
—no la punta de la rama—, y eso podria hacer que la referencia no fuera el
codigo que se ejecuta. Aqui se resuelve asi, y se IMPRIME siempre:

  * `GITHUB_SHA` si esta definido y git lo conoce. En `pull_request` es
    justamente ese merge efimero, y ES el correcto para esta garantia: es el
    arbol que `actions/checkout` deja en disco y sobre el que corre pytest, asi
    que "lo que la ejecucion usa" y "lo que el commit dice" son comparables. La
    punta de la rama NO serviria: el job no ejecuta ese arbol.
  * si no, `git rev-parse HEAD` (uso local y `push`).

En los dos casos la propiedad es la misma: el fichero en disco tiene que ser el
del commit cuyo arbol se esta ejecutando.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUTA = ".github/xfail-registro.txt"
FICHERO = REPO / RUTA

# Salida de emergencia SOLO para `calibra_registro_xfail.py`, que necesita mutar
# el registro para ejercitar sus casos; sin ella todos sus casos saldrian rojos
# por integridad en vez de por el control que cada uno calibra, o sea rojos
# prestados. Como las demas banderas de desarme del carril, esta PROHIBIDA en
# `ci.yml` y los gates lo comprueban.
# NINGUNA DE ESTAS DOS SALE DEL ENTORNO. Son variables de MODULO, y solo puede
# tocarlas quien IMPORTA este fichero en su propio proceso.
#
# Antes eran `S9K_REGISTRO_MUTADO` y `S9K_MIDIENDO_BASE`, y la concesion se
# defendia comprobando la ASCENDENCIA del proceso. Un revisor la falsifico con
# `exec -a`: `argv` es texto que el proceso elige, asi que el nombre que ve el
# arbol de procesos no prueba que ese script se haya ejecutado. Y por debajo hay
# algo peor: todo lo que puede hacer un arnes lo puede hacer un paso de
# `ci.yml`, asi que NINGUN apreton de manos es una frontera. Se quita la
# entrada: lo que no existe no se falsifica.
#
# MUTADO   -> lo pone `calibra_registro_xfail.py` para poder mutar el registro.
# MIDIENDO -> lo pone el propio gate cuando MIDE (`--escribir-inventario`), no
#             cuando certifica. Al medir el arbol de una base, el registro no es
#             el sujeto y su integridad no aplica.
MUTADO = False
MIDIENDO = False


def _mutado() -> bool:
    return MUTADO


def _midiendo_base() -> bool:
    return MIDIENDO


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                          text=True, timeout=180)


def commit_de_referencia() -> tuple[str | None, str]:
    """(sha, de donde sale). Nunca del arbol de trabajo."""
    sha_env = os.environ.get("GITHUB_SHA", "").strip()
    if sha_env:
        p = _git("rev-parse", "--verify", f"{sha_env}^{{commit}}")
        if p.returncode == 0:
            return p.stdout.strip(), "GITHUB_SHA (el arbol que ejecuta el job)"
    p = _git("rev-parse", "--verify", "HEAD^{commit}")
    if p.returncode == 0:
        return p.stdout.strip(), "git rev-parse HEAD"
    return None, "no se pudo resolver ningun commit"


def contenido_verificado() -> tuple[str | None, list[str]]:
    """(contenido DEL COMMIT, errores). Verificar y entregar, en una llamada.

    Devuelve SIEMPRE el contenido que viene de git. El fichero del arbol se lee
    unicamente como SUJETO de la comparacion y su contenido no sale de aqui.
    """
    if _midiendo_base():
        # No se compara nada: se entrega el registro que traiga el arbol de la
        # base (o vacio si no lo trae). Las comprobaciones que dependen del
        # registro son de error, no de medida, asi que el inventario que
        # produce esta pasada no depende de esto.
        return (FICHERO.read_text(encoding="utf-8") if FICHERO.exists() else ""), []
    if _mutado():
        # La calibracion muta el registro a proposito. Se entrega lo que hay en
        # disco porque es justo lo que el caso quiere ejercitar, y se GRITA.
        print("::warning::REGISTRO MUTADO por un arnes: integridad NO "
              "comprobada y se usa el fichero del arbol. Esta variable solo se "
              "puede poner IMPORTANDO este modulo, nunca desde el entorno.")
        return (FICHERO.read_text(encoding="utf-8") if FICHERO.exists() else ""), []

    sha, origen = commit_de_referencia()
    if sha is None:
        return None, [
            "INTEGRIDAD DEL REGISTRO: no se pudo resolver el commit de "
            "referencia con git. Sin referencia no hay comparacion posible, y "
            "NO se cae al fichero del arbol como respaldo: ese respaldo seria "
            "el agujero, porque el sujeto pasaria a ser su propia referencia."]

    p = _git("show", f"{sha}:{RUTA}")
    existe_en_commit = p.returncode == 0
    existe_en_arbol = FICHERO.exists()

    if not existe_en_commit and not existe_en_arbol:
        return "", []
    if not existe_en_commit:
        return None, [
            f"REGISTRO NO VERSIONADO: `{RUTA}` existe en disco pero NO en el "
            f"commit {sha[:12]} ({origen}). Un registro que no esta en el "
            f"commit no ha pasado por ningun diff, asi que no lo ha revisado "
            f"nadie: es un sello, no una escotilla."]

    referencia = p.stdout
    if not existe_en_arbol:
        return None, [
            f"REGISTRO BORRADO EN CALIENTE: `{RUTA}` esta en el commit "
            f"{sha[:12]} y no en disco. Alguien lo quito durante la ejecucion."]

    sujeto_del_arbol = FICHERO.read_text(encoding="utf-8")
    h_ref = hashlib.sha256(referencia.encode("utf-8")).hexdigest()
    h_suj = hashlib.sha256(sujeto_del_arbol.encode("utf-8")).hexdigest()
    if h_ref != h_suj:
        return None, [
            f"REGISTRO ESCRITO FUERA DEL DIFF: `{RUTA}` en disco no coincide "
            f"con el del commit {sha[:12]} ({origen}). disco={h_suj[:16]}... "
            f"commit={h_ref[:16]}... Da igual la via —redireccion, `tee`, un "
            f"nombre partido en dos variables, un script que ni menciona el "
            f"fichero, un `conftest` en tiempo de import—: una autorizacion "
            f"escrita durante la ejecucion NO aparece en ningun diff, no la "
            f"revisa nadie, y convierte la escotilla deliberada en un sello "
            f"automatico que ademas infiere la excepcion de la misma ejecucion "
            f"cuya integridad se pretende proteger. Si la entrada es legitima, "
            f"COMMITEALA."]
    return referencia, []


def entradas() -> tuple[dict[str, tuple[str, str]], list[str]]:
    """nodeid -> (id, motivo), y los problemas. UNICA puerta de lectura.

    Verifica y consume en la misma llamada: no hay instante entre comprobar y
    usar en el que quepa una escritura.
    """
    contenido, errores = contenido_verificado()
    if contenido is None:
        return {}, errores

    parsed: dict[str, tuple[str, str]] = {}
    for numero, cruda in enumerate(contenido.splitlines(), 1):
        if cruda.lstrip().startswith("#") or not cruda.strip():
            continue
        campos = [c.strip() for c in cruda.split("|")]
        if len(campos) != 3 or not all(campos):
            errores.append(
                f"REGISTRO MAL FORMADO (linea {numero}): `{cruda.strip()[:70]}`. "
                f"El formato es `<id> | <nodeid exacto> | <motivo>`, los tres "
                f"campos obligatorios. Un motivo vacio no declara nada.")
            continue
        ident, nodeid, motivo = campos
        # La coincidencia es IGUALDAD DE CADENA, nunca `fnmatch`, asi que un `*`
        # no puede ampliar nada. Esto es legibilidad: que nadie ESCRIBA algo con
        # pinta de patron y crea que cubre varias pruebas. Y se mira solo la
        # parte anterior al `[`, porque dentro del parametro los caracteres son
        # DATOS del caso: hay entradas legitimas con `ops/**` ahi dentro.
        if any(c in nodeid.split("[", 1)[0] for c in "*?") or nodeid.endswith("::"):
            errores.append(
                f"REGISTRO CON PINTA DE PATRON (linea {numero}): `{nodeid}`. La "
                f"ruta y el nombre de la prueba tienen que ser literales.")
            continue
        if "::" not in nodeid or not nodeid.split("::")[0].endswith(".py"):
            errores.append(
                f"REGISTRO SIN PRUEBA (linea {numero}): `{nodeid}` no nombra una "
                f"prueba concreta (`<ruta>.py::<test>`). Autorizar un modulo "
                f"entero no es una excepcion, es un permiso.")
            continue
        if nodeid in parsed:
            errores.append(
                f"REGISTRO DUPLICADO (linea {numero}): `{nodeid}` ya estaba "
                f"declarado como `{parsed[nodeid][0]}`.")
            continue
        parsed[nodeid] = (ident, motivo)
    return parsed, errores


def nodeids_autorizados() -> tuple[set[str], list[str]]:
    parsed, errores = entradas()
    return set(parsed), errores


def lineas_por_modulo() -> dict[str, int]:
    """modulo -> LINEAS autorizadas. La unidad de X-T son sitios de marca."""
    conteo: dict[str, int] = {}
    for nodeid in nodeids_autorizados()[0]:
        modulo = nodeid.split("::")[0]
        conteo[modulo] = conteo.get(modulo, 0) + 1
    return conteo


def funciones_por_modulo() -> dict[str, int]:
    """modulo -> FUNCIONES distintas autorizadas.

    Unidad distinta de `lineas_por_modulo`: una funcion parametrizada tiene una
    entrada por caso. D2 cuenta funciones, asi que su margen tiene que contar
    funciones o aflojaria de mas. Medido: un modulo con 6 lineas tiene 3
    funciones.
    """
    por_modulo: dict[str, set[str]] = {}
    for nodeid in nodeids_autorizados()[0]:
        por_modulo.setdefault(nodeid.split("::")[0], set()).add(nodeid.split("[", 1)[0])
    return {m: len(f) for m, f in por_modulo.items()}
