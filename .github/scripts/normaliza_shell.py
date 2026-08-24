#!/usr/bin/env python3
"""Normalizacion de linea de shell y deteccion de BANDERAS DE DESARME.

Vive aparte porque lo usan los DOS gates y una sola implementacion es la unica
forma de que no se separen. Es la misma leccion que el registro: dos lectores
acaban en dos verdades.

POR QUE NO BASTA `if "NOMBRE" in texto`
=======================================
Era la ultima comprobacion del carril basada en buscar la cadena literal, y cae
con la tecnica que este carril ya derroto tres veces en otros sitios:

    export S9K_REGISTRO_MU""TADO=1

Para bash eso es `S9K_REGISTRO_MUTADO=1`; para un `in` es otra cadena. Medido de
punta a punta: con esa linea puesta, un defecto REAL tragado por un `xfail`
autorizado con una entrada escrita EN CALIENTE daba EXIT=0 y 0 errores. Y lo
mismo con `S9K_INVENTARIO_ABLA""CION=A`, que desarma el control A entero.

Se reutiliza la normalizacion que ya estaba calibrada en `_revisa_run`: leer la
linea tal cual, sin comillas, y sin comillas ni sustituciones. El shell colapsa
`""`, `%s`, `$(...)`, `${VAR}` y `$VAR` al construir la palabra, asi que leerla
normalizada es leer lo que el shell ve.
"""
from __future__ import annotations

import re

RE_COMILLAS = re.compile(r"[\"']")
RE_SUSTITUCION = re.compile(r"\$\([^)]*\)|\$\{\w+\}|\$\w+|%[sd]")

# Nombres que DESARMAN un gate. No inyectan opciones de pytest —por eso no van
# con las variables que filtran—: apagan controles enteros, que es peor.
VARIABLES_DE_DESARME = (
    "S9K_INVENTARIO_ABLACION",
    "S9K_EJECUCION_ABLACION",
    "S9K_REGISTRO_MUTADO",
    "S9K_MIDIENDO_BASE",
)

# Banderas de linea de comandos con el mismo efecto.
BANDERAS_DE_DESARME = ("--sin-base", "--base-fichero", "--solo-registro")

TODOS_LOS_DESARMES = (*VARIABLES_DE_DESARME, *BANDERAS_DE_DESARME)


def variantes_normalizadas(linea: str) -> list[str]:
    """La linea tal cual, sin comillas, y sin comillas ni sustituciones."""
    sin_comillas = RE_COMILLAS.sub("", linea)
    sin_sustituciones = RE_SUSTITUCION.sub("", sin_comillas)
    vistas = [linea]
    for variante in (sin_comillas, sin_sustituciones):
        if variante not in vistas:
            vistas.append(variante)
    return vistas


def desarmes_en_ci(texto_ci: str) -> list[tuple[str, str]]:
    """(nombre, linea) de cada desarme presente en `ci.yml`.

    Se mira CADA LINEA en sus variantes normalizadas, no la cadena cruda del
    fichero entero: es la unica forma de ver el nombre partido en comillas, con
    `%s` o con `$()` en medio.
    """
    hallados: list[tuple[str, str]] = []
    for linea in texto_ci.splitlines():
        if linea.lstrip().startswith("#"):
            continue
        for variante in variantes_normalizadas(linea):
            for nombre in TODOS_LOS_DESARMES:
                if nombre in variante and (nombre, linea) not in hallados:
                    hallados.append((nombre, linea))
    return hallados


# ---------------------------------------------------------------------------
# DESARME: SE CIERRA POR PROPIEDAD, NO POR RECONOCEDOR
# ---------------------------------------------------------------------------
# Lo de arriba —`desarmes_en_ci`— nacio para cazar `S9K_REGISTRO_MU""TADO=1`
# en `ci.yml`, y lo caza. Pero un revisor lo atraveso repartiendo el NOMBRE
# entre varias lineas, que es lo que un reconocedor linea a linea no puede ver:
#
#     A=S9K_REGISTRO; B=MUTADO; export ${A}_${B}=1
#     echo "${A}_${B}=1" >> $GITHUB_ENV      # ademas persiste al paso siguiente
#     export S9K_REGISTRO_MU\<salto de linea>TADO=1
#
# Con eso, un `xfail(strict=True)` sobre una prueba critica mas una autorizacion
# escrita en caliente daba EXIT=0 y el defecto quedaba tragado. Es el mismo
# escenario que se declaro cerrado, cambiando solo la forma de ESCRIBIR el
# nombre.
#
# Es la cuarta vez que enumerar pierde en este carril, asi que se deja de
# intentar leer `ci.yml` para esto y se comprueba la PROPIEDAD en el unico
# sitio donde el nombre ya no se puede disfrazar: EL ENTORNO DEL PROCESO. Da
# igual como se escribiera —dos variables, un salto de linea, `$GITHUB_ENV`,
# un script que ni menciona el nombre—: cuando el gate arranca, la variable o
# esta en `os.environ` o no esta.
#
# Y como una variable presente no basta para distinguir "arnes calibrando" de
# "alguien desarmando en CI", se exige PRUEBA de quien la puso: que un ARNES
# REAL de este repositorio sea ANTECESOR del proceso. Un paso de `ci.yml` que
# exporte la variable y llame al gate tiene como antecesor al shell del runner,
# no a un `calibra_*.py`, asi que se le niega el arranque.
#
# Si no se puede leer la ascendencia (sin `/proc`), FALLA CERRADO: sin poder
# probar quien lo puso, no se concede.

RE_ARNES = re.compile(r"\.github/scripts/(calibra_[a-z0-9_]+)\.py")
RE_GATE_BASE = re.compile(r"\.github/scripts/check_suite_inventory\.py")


def _ancestros(max_niveles: int = 16) -> tuple[list[str], str | None]:
    """Lineas de comando de los procesos antecesores, del padre hacia arriba."""
    import os as _os
    from pathlib import Path as _Path
    salida: list[str] = []
    try:
        pid = _os.getppid()
        for _ in range(max_niveles):
            if pid <= 1:
                break
            cmdline = _Path(f"/proc/{pid}/cmdline").read_bytes()
            salida.append(cmdline.replace(b"\0", b" ").decode("utf-8", "replace"))
            estado = _Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
            padre = [l for l in estado.splitlines() if l.startswith("PPid:")]
            if not padre:
                break
            pid = int(padre[0].split()[1])
    except (OSError, ValueError, IndexError) as e:
        return salida, f"no se pudo leer la ascendencia ({e})"
    return salida, None


def desarmes_en_entorno(entorno: dict) -> list[str]:
    """Nombres de desarme presentes en el entorno, con valor activo."""
    activos = []
    for nombre in VARIABLES_DE_DESARME:
        valor = (entorno.get(nombre) or "").strip()
        if valor and valor.lower() not in ("0", "false", "no"):
            activos.append(nombre)
    return activos


def exige_desarme_autorizado(repo, entorno: dict) -> list[str]:
    """Errores si hay desarme sin un arnes REAL de este repo como antecesor."""
    activos = desarmes_en_entorno(entorno)
    if not activos:
        return []

    ancestros, fallo = _ancestros()
    if fallo:
        return [f"DESARME SIN PRUEBA: {', '.join(activos)} en el entorno y "
                f"{fallo}. Sin poder comprobar QUIEN lo puso no se concede: "
                f"esta comprobacion falla cerrada a proposito."]

    arneses_reales = set()
    gate_padre = False
    for linea in ancestros:
        for m in RE_ARNES.finditer(linea):
            candidato = repo / ".github" / "scripts" / f"{m.group(1)}.py"
            if candidato.is_file():
                arneses_reales.add(m.group(1))
        if RE_GATE_BASE.search(linea):
            gate_padre = True

    if arneses_reales:
        return []
    # `S9K_MIDIENDO_BASE` lo pone el propio gate al medir una base: ahi el
    # antecesor legitimo es el gate, no un arnes.
    if activos == ["S9K_MIDIENDO_BASE"] and gate_padre:
        return []

    return [f"DESARME NO AUTORIZADO: {', '.join(activos)} en el entorno y "
            f"NINGUN arnes de calibracion de este repositorio entre los "
            f"procesos antecesores. Estas variables APAGAN controles enteros, "
            f"asi que solo valen cuando las pone un `calibra_*.py` real que "
            f"esta midiendo. Da exactamente igual como se escribiera el nombre "
            f"—dos variables, un salto de linea, `$GITHUB_ENV`, un script que "
            f"ni lo menciona—: aqui se mira el ENTORNO, no el texto de "
            f"`ci.yml`, y la autorizacion es la ASCENDENCIA del proceso."]
