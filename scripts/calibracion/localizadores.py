#!/usr/bin/env python3
"""Localizadores ESTRUCTURALES para los arneses de calibración.

POR QUÉ EXISTE
--------------
Una mutación anclada a texto literal y aplicada con `str.replace(viejo, nuevo, 1)`
elige la PRIMERA aparición en todo el fichero. Eso convierte la posición en el
fichero —algo que cualquier carril puede mover sin darse cuenta— en parte de la
garantía. El precedente está medido en `corte1_existencia_partida.py` (M6, PR
#259): el Corte 6B-2(b) añadió un segundo bucle sobre la misma enumeración, el
ancla de ocho espacios resultó ser SUBCADENA de la línea de doce del bloque
nuevo, y la mutación empezó a caer en el bloque equivocado dejando la garantía
real INTACTA y la suite VERDE. Un calibrador así no avisa de nada.

El arreglo no es afinar el texto del ancla —eso se rompe a la siguiente
reindentación—, sino localizar ESTRUCTURALMENTE el sitio y mutar sólo dentro de
él. `_mutar_oferta_del_grant` lo hace para HTML (el `<form>` cuya `action` es la
ruta canónica). Este módulo generaliza el MISMO principio a Python, por AST:
acotar al nodo que la garantía nombra y exigir unicidad DENTRO de ese nodo.

INVARIANTE COMPARTIDO: ambigüedad y ausencia devuelven ``None``, que los arneses
leen como DETECTOR ROTO. Nunca un verde silencioso.

TECHO DECLARADO
---------------
`mutar_en_funcion` acota por el nombre de la función de nivel sintáctico: si el
nombre aparece dos veces (redefinición, o un método homónimo en una clase del
mismo fichero) devuelve ``None`` en vez de elegir uno. NO resuelve alias, NO
sigue decoradores que reescriban la función, y NO ve el sitio si la garantía se
mueve a otra función: en ese caso da DETECTOR ROTO, que es el aviso correcto.
"""
from __future__ import annotations

import ast


def span_de_funcion(texto: str, nombre: str) -> tuple[int, int] | None:
    """Offsets [inicio, fin) del `def nombre(...)` COMPLETO (firma y cuerpo).

    Excluye los decoradores a propósito: lo que estas mutaciones atacan vive en
    la firma o en el cuerpo, y un decorador compartido entre varias rutas no
    debe formar parte del ámbito acotado.

    Devuelve ``None`` si hay cero o más de una función con ese nombre.
    """
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return None

    encontradas = [
        n for n in ast.walk(arbol)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nombre
    ]
    if len(encontradas) != 1:
        return None

    nodo = encontradas[0]
    if nodo.end_lineno is None:
        return None

    lineas = texto.splitlines(keepends=True)
    if nodo.end_lineno > len(lineas):
        return None
    inicio = sum(len(l) for l in lineas[: nodo.lineno - 1])
    fin = sum(len(l) for l in lineas[: nodo.end_lineno])
    return inicio, fin


def mutar_en_funcion(texto: str, nombre: str, viejo: str, nuevo: str) -> str | None:
    """Sustituye `viejo` por `nuevo` SÓLO dentro de la función `nombre`.

    Exige que `viejo` aparezca EXACTAMENTE UNA VEZ dentro de esa función. Que
    aparezca más veces fuera es irrelevante y es justo el caso que hundía al
    `replace(..., 1)`: aquí no cambia ni el sitio mutado ni el veredicto.

    Devuelve ``None`` —DETECTOR ROTO— si la función no se localiza, si el ancla
    no está dentro de ella, si está más de una vez, o si el texto no cambia.
    """
    span = span_de_funcion(texto, nombre)
    if span is None:
        return None
    inicio, fin = span

    cuerpo = texto[inicio:fin]
    if cuerpo.count(viejo) != 1:
        return None

    mutado = texto[:inicio] + cuerpo.replace(viejo, nuevo, 1) + texto[fin:]
    return None if mutado == texto else mutado


def mutar_unico(texto: str, viejo: str, nuevo: str) -> str | None:
    """Sustitución de ámbito de FICHERO pero exigiendo unicidad.

    Es el reemplazo honesto de `texto.replace(viejo, nuevo, 1)`: hace lo mismo
    cuando el ancla es única —el único caso en que «la primera» y «la correcta»
    coinciden con certeza— y devuelve ``None`` en cuanto deja de serlo, en vez
    de mutar silenciosamente la primera de varias.
    """
    if texto.count(viejo) != 1:
        return None
    mutado = texto.replace(viejo, nuevo, 1)
    return None if mutado == texto else mutado


def python_sigue_siendo_valido(texto: str) -> bool:
    """``True`` si `texto` compila como Python; ``False`` si es inválido.

    POR QUÉ EXISTE. El arnés de calibración daba por CALIBRADA una mutación que
    tumbaba la SINTAXIS o el IMPORT del módulo mutado: el proceso de pytest
    devolvía rc!=0 (luego "ROJO") y la lista de rojos nombrados venía vacía, lo
    que el código leía como "rojo sin nombres fuera de lo declarado" —ningún
    ajeno, cero sobrantes— en vez de leer "el módulo no llegó a ejecutarse".
    Un módulo que no compila no es un rojo de la garantía: es el INSTRUMENTO
    roto. Esta comprobación se hace ANTES de correr pytest y, combinada con
    exigir ``len(rojos) > 0`` para declarar CALIBRADA, separa las tres causas:
    la garantía muerde (rojos nombrados), el módulo no compiló (aquí) o el
    módulo no se pudo importar/ejecutar pero sí compiló (rojos vacíos, luego
    cazado por la exigencia de ``len(rojos) > 0``).
    """
    try:
        ast.parse(texto)
    except SyntaxError:
        return False
    return True
