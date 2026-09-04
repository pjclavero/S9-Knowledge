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
# LO QUE AQUI YA NO ESTA, Y POR QUE
# ---------------------------------------------------------------------------
# Hubo aqui una comprobacion que concedia el desarme si un `calibra_*.py` real
# del repositorio era ANTECESOR del proceso. Se ha RETIRADO ENTERA porque es
# falsificable en una linea:
#
#     bash -c 'exec -a ".github/scripts/calibra_registro_xfail.py" \
#              /usr/bin/python3 /tmp/impostor.py'
#
# Medido: EXIT=0 con el desarme concedido. `argv` es TEXTO QUE EL PROCESO
# ELIGE; el nombre que ve el arbol de procesos no prueba que ese fichero se
# haya ejecutado. Era, otra vez, reconocer "quien parece ser" en vez de
# comprobar "que es verdad".
#
# Y el fondo del asunto: TODO lo que puede hacer un arnes lo puede hacer un
# paso de `ci.yml` —un secreto efimero, un fichero 0600, un descriptor
# heredado—, asi que ningun apreton de manos habria sido una frontera. La
# unica propiedad defendible es que el binario que CERTIFICA no tenga entrada
# de desarme. Eso es lo que se hizo: `check_suite_inventory.py` y
# `check_ejecucion_real.py` ya no leen NINGUNA variable de desarme del entorno,
# y su ablacion es una variable de modulo que solo puede tocar quien los
# IMPORTA en su propio proceso.
#
# Lo que queda debajo —`desarmes_en_ci`— se conserva como DEFENSA EN
# PROFUNDIDAD para `_revisa_run`: avisa antes y dice que se rompio. Ya no es la
# garantia, y no debe volver a serlo.
# ---------------------------------------------------------------------------
