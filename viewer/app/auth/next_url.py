# -*- coding: utf-8 -*-
"""Autoridad única del destino ``next``: ¿es una ruta interna de este producto?

PROPIEDAD QUE CIERRA ESTE MÓDULO
--------------------------------
``next`` sólo puede representar una ruta interna del propio producto; **ninguna
representación equivalente puede convertirse en autoridad externa al
interpretarla el navegador**.

Esa última frase es la razón de ser del módulo. El defecto que lo motiva no es
que ``/\\evil.example/x`` «parezca» una URL externa: es que Chrome y Firefox
**normalizan ``\\`` a ``/``** al interpretar una cabecera ``Location`` o un
``href``, con lo que ``/\\evil.example/x`` se convierte en ``//evil.example/x``,
que es protocolo-relativo y **sale del sitio**. Lo mismo vale para ``///…``,
que ya escapaba tal cual, y para cualquier codificación que se deshaga antes de
esa interpretación.

CRITERIO: POR COMPONENTES, NO POR LISTA DE CADENAS
--------------------------------------------------
Una lista de cadenas prohibidas crece para siempre y siempre va por detrás. Aquí
se descompone la entrada en componentes y se exige de cada uno una propiedad
positiva. Regla de diseño explícita: **ante una representación ambigua se
rechaza, nunca se transforma y se acepta**. No «normalizamos las barras
repetidas» para quedarnos con el resultado: si hicieron falta barras repetidas,
la entrada ya era ambigua y se cae.

Los siete criterios:

1. Sin scheme.
2. Sin netloc.
3. El path empieza por **exactamente una** ``/``.
4. Backslash prohibida en el path.
5. Tras deshacer la codificación porcentual del path (hasta punto fijo): sigue
   empezando por una sola ``/``, no aparecen backslashes y no aparecen
   controles.
6. La query se permite **como query** (es la ergonomía del producto:
   ``/v3/review?workspace=…&job_id=…`` debe seguir funcionando).
7. **La query nunca participa en decidir host/origen.** El host se decide sólo
   con scheme, netloc y path; la query se valida aparte y con criterios de
   query. Un navegador no puede convertir una query en autoridad: lo que va
   detrás del primer ``?`` ya no puede volver a ser host.

TECHO DECLARADO — QUÉ **NO** VE ESTE VALIDADOR
-----------------------------------------------
- No valida que la ruta **exista** ni que el usuario tenga permiso sobre ella.
  Sólo garantiza «mismo origen», no «destino legítimo». La autorización la
  siguen haciendo los guardas de ruta.
- No modela el parser WHATWG completo. Se defiende rechazando por encima de lo
  necesario, no reproduciendo el algoritmo del navegador.
- No inspecciona el **contenido semántico** de la query: acepta cualquier
  ``%XX`` dentro de ella. Eso es deliberado (criterio 7) y es seguro para la
  propiedad de origen, pero significa que este módulo **no** protege de
  inyecciones que consuma el destino a partir de sus propios parámetros.
- No cubre redirecciones que ocurran **después** (una página interna que a su
  vez redirija fuera). La propiedad es de un salto.
- No cubre cabeceras ``Location`` construidas en otro sitio que no pase por
  aquí; el alcance son las superficies inventariadas que llaman a ``_safe_next``.
- Al exigir path ASCII tras decodificar, **rechaza rutas internas legítimas que
  usaran caracteres no ASCII en el path**. Hoy no existe ninguna; si algún día
  existiese, esto la rompería en rojo (no la dejaría pasar en silencio).
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import unquote, urlsplit

#: Destino interno al que se cae cuando la entrada no es aceptable.
DESTINO_POR_DEFECTO = "/"

#: Un ``%`` que no inicia un escape válido: representación rota => ambigua.
_PORCENTAJE_ROTO = re.compile(r"%(?![0-9A-Fa-f]{2})")

#: Máximo de vueltas de decodificación. Con punto fijo antes del límite basta;
#: si no se alcanza el punto fijo en estas vueltas, la entrada está anidando
#: codificaciones a propósito y se rechaza.
_MAX_VUELTAS_DECODE = 5


def _tiene_control(texto: str) -> bool:
    """Controles C0, DEL y C1. Incluye CR, LF y TAB, que son los que parten
    una cabecera ``Location`` en dos."""
    return any(ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F for ch in texto)


def _path_decodificado_es_seguro(path: str) -> bool:
    """Criterio 5: el path sigue siendo una ruta interna tras decodificarlo.

    Se decodifica hasta punto fijo y se comprueba en CADA vuelta, no sólo al
    final: así una vuelta intermedia hostil no puede esconderse detrás de otra.
    """
    actual = path
    for _ in range(_MAX_VUELTAS_DECODE):
        if _PORCENTAJE_ROTO.search(actual):
            return False
        try:
            siguiente = unquote(actual, errors="strict")
        except (UnicodeDecodeError, ValueError):
            return False
        if not _componente_path_es_seguro(siguiente):
            return False
        if siguiente == actual:
            return True                      # punto fijo alcanzado y seguro
        actual = siguiente
    return False                             # anidamiento sin punto fijo


def _componente_path_es_seguro(path: str) -> bool:
    """Criterios 3 y 4 sobre una representación concreta del path."""
    if not path.startswith("/"):
        return False
    if path.startswith("//"):                # dos o más: protocolo-relativo
        return False
    if "\\" in path:
        return False
    if _tiene_control(path):
        return False
    if not path.isascii():
        return False
    if any(seg == ".." for seg in path.split("/")):
        return False
    return True


def ruta_interna_o_defecto(next_url: Optional[str]) -> str:
    """Devuelve ``next_url`` si es una ruta interna inequívoca, si no ``/``.

    Nunca devuelve una versión «arreglada» de la entrada: o la entrada era ya
    una ruta interna inequívoca y se devuelve **tal cual**, o se cae al destino
    por defecto. Devolver algo transformado sería aceptar lo ambiguo.
    """
    if not next_url or not isinstance(next_url, str):
        return DESTINO_POR_DEFECTO

    # Espacios al borde: `urlsplit` los IGNORA, así que si no se rechazan aquí
    # el validador estaría opinando sobre una cadena distinta de la que viaja.
    if next_url != next_url.strip():
        return DESTINO_POR_DEFECTO
    if _tiene_control(next_url):
        return DESTINO_POR_DEFECTO

    try:
        partes = urlsplit(next_url)
    except ValueError:
        return DESTINO_POR_DEFECTO

    if partes.scheme:                        # criterio 1
        return DESTINO_POR_DEFECTO
    if partes.netloc:                        # criterio 2
        return DESTINO_POR_DEFECTO
    if partes.fragment or "#" in next_url:   # no declarado como necesario: fuera
        return DESTINO_POR_DEFECTO

    # El path CRUDO, recortado a mano hasta el primer `?`. No se usa
    # `partes.path`: `urlsplit("///evil.example/x")` devuelve netloc vacío y
    # path `/evil.example/x`, es decir, **se come dos barras** y presenta como
    # ruta interna algo que el navegador lee como protocolo-relativo. Ése es
    # justo el escape que hay que cerrar, así que el criterio 3 se aplica sobre
    # lo que de verdad viaja. Criterio 7: el corte es por `?`, y lo que queda
    # detrás no interviene aquí.
    path_crudo = next_url.split("?", 1)[0]
    if not _componente_path_es_seguro(path_crudo):       # criterios 3 y 4
        return DESTINO_POR_DEFECTO
    if not _componente_path_es_seguro(partes.path):      # coherencia parser/crudo
        return DESTINO_POR_DEFECTO
    if not _path_decodificado_es_seguro(path_crudo):     # criterio 5
        return DESTINO_POR_DEFECTO

    # Criterios 6 y 7: la query se permite COMO QUERY y no ha participado en
    # nada de lo anterior. Se le exige sólo lo que puede romper el transporte
    # de la cabecera (controles) o cambiar de significado en el navegador
    # (backslash cruda). Su `%XX` NO se decodifica: no puede volver a ser host.
    if partes.query:
        if _tiene_control(partes.query) or "\\" in partes.query:
            return DESTINO_POR_DEFECTO
        if _PORCENTAJE_ROTO.search(partes.query):
            return DESTINO_POR_DEFECTO

    return next_url
