"""Qué LEE de verdad el motor de política, leído con AST y no con `grep`.

No es un fichero de pruebas: es el instrumento de medida que usan las redes
inversas de `test_provider_authz_fields_contract.py` y
`test_registro_de_autorizacion.py`. Vive aparte porque una red inversa que se
mide a sí misma no es una red.

POR QUÉ AST (P0-AUTH)
---------------------
La red inversa anterior era SINTÁCTICA y buscaba dos formas literales:

    node.get("campo")            -- dimensiones del dato
    (?:ctx|self)\\.campo          -- dimensiones del contexto

y por tanto sólo veía el bypass si el programador lo escribía con el nombre de
variable que la expresión regular esperaba. Está MEDIDO que esto pasaba VERDE
con los 1161 tests del visor:

    _c = ctx
    if _c.puerta_trasera:
        return _ALLOW

Un alias local de una línea desactivaba la red entera. Y no es una hipótesis
retorcida: renombrar `ctx` a `contexto`, o extraer una regla a una función que
reciba el contexto con otro nombre, produce exactamente el mismo agujero sin
mala intención ninguna.

Aquí se lee el ÁRBOL, no el texto. La regla es deliberadamente
SOBRE-APROXIMADA: cuenta como consumo *cualquier* acceso a un atributo cuyo
nombre sea un campo de `ViewerContext`, venga del objeto que venga. Sobre-contar
sólo puede obligar a declarar de más; sub-contar es lo que deja una dimensión
decidiendo sin cadena. La asimetría es intencionada.

LÍMITES, con su cifra y sin adornos
-----------------------------------
Lo que este instrumento NO ve, dicho para que nadie le pida lo que no da:

  * acceso DINÁMICO con nombre calculado: `getattr(ctx, "admin" + "_full")`.
    Se detecta `getattr(x, "literal")` (nombre constante), no una expresión.
  * consumo INDIRECTO: pasar el contexto entero a una función de otro módulo
    que decida allí. El barrido cubre `policies/engine.py` y `policies/models.py`;
    lo que decida fuera de esos dos módulos no lo ve nadie aquí.
  * `dataclasses.asdict(ctx)["admin_full"]` o cualquier recorrido por
    diccionario.

Los tres son EVASIONES DELIBERADAS, no descuidos: hay que escribirlas a
propósito. El alias local, en cambio, es el caso accidental y es el que se
cierra. Esa es toda la mejora reclamada, ni una línea más.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
from typing import Iterable

from app.policies import engine as engine_mod
from app.policies import models as models_mod
from app.policies.models import ViewerContext

#: Módulos que toman decisiones de política. Si una decisión se muda a otro
#: módulo, hay que añadirlo aquí: no hay descubrimiento automático, y decirlo
#: es parte del límite declarado.
MODULOS_DE_POLITICA = (engine_mod, models_mod)


def _arboles() -> list[ast.AST]:
    return [ast.parse(inspect.getsource(m)) for m in MODULOS_DE_POLITICA]


def campos_del_contexto() -> frozenset[str]:
    """Campos declarados por `ViewerContext`, tal cual.

    Se derivan del dataclass y no de una lista escrita a mano: un campo nuevo
    entra en el barrido el día que se añade, que es justo el caso que la
    cuarentena dejaba pasar en verde.
    """
    return frozenset(f.name for f in dataclasses.fields(ViewerContext))


def dimensiones_de_contexto_consumidas() -> frozenset[str]:
    """Dimensiones de `ViewerContext` que el motor consume, vía AST.

    Cuenta `ctx.x`, `self.ctx.x`, `self.x`, `alias.x` y `getattr(algo, "x")`.
    El nombre de la variable base es IRRELEVANTE a propósito.
    """
    campos = campos_del_contexto()
    encontrados: set[str] = set()
    for arbol in _arboles():
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Attribute) and nodo.attr in campos:
                encontrados.add(nodo.attr)
            elif (
                isinstance(nodo, ast.Call)
                and isinstance(nodo.func, ast.Name)
                and nodo.func.id == "getattr"
                and len(nodo.args) >= 2
                and isinstance(nodo.args[1], ast.Constant)
                and nodo.args[1].value in campos
            ):
                encontrados.add(nodo.args[1].value)
    return frozenset(encontrados)


def campos_de_dato_consumidos(excluir: Iterable[str] = ()) -> frozenset[str]:
    """Claves que el motor lee de un nodo/relación, vía AST.

    Cualquier `algo.get("literal")` dentro de los módulos de política. En estos
    dos módulos todos los `.get(...)` son lecturas del dato evaluado, así que
    no hace falta acertar con el nombre de la variable --que era justo la
    fragilidad de la versión con expresiones regulares--.
    """
    fuera = set(excluir)
    encontrados: set[str] = set()
    for arbol in _arboles():
        for nodo in ast.walk(arbol):
            if (
                isinstance(nodo, ast.Call)
                and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr == "get"
                and nodo.args
                and isinstance(nodo.args[0], ast.Constant)
                and isinstance(nodo.args[0].value, str)
            ):
                encontrados.add(nodo.args[0].value)
    return frozenset(encontrados - fuera)
