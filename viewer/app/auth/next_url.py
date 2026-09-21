# -*- coding: utf-8 -*-
r"""Autoridad única del destino ``next``: ¿es una ruta interna de este producto?

PROPIEDAD QUE CIERRA ESTE MÓDULO
--------------------------------
``next`` sólo puede representar una ruta interna del propio producto; **ninguna
representación equivalente puede convertirse en autoridad externa al
interpretarla el navegador**.

EL DEFECTO, DICHO CON PRECISIÓN (importa, porque se dijo mal dos veces)
-----------------------------------------------------------------------
El criterio anterior aceptaba ``///evil.example/x``, ``////…``, ``/\evil…`` y
``/%2F%2F…`` y los emitía casi intactos en la cabecera ``Location``: el destino
del atacante llegaba entero a una cabecera de redirección. La causa es que
``urlsplit("///evil.example/x")`` devuelve ``netloc=''`` y
``path='/evil.example/x'`` — **se come dos barras** y presenta como interna una
cadena que no lo es.

**Y SÍ ES UNA REDIRECCIÓN ABIERTA DE VERDAD.** Medido con la defensa retirada,
con el servidor emitiendo ``Location: ///evil.example/x`` intacto:

    curl -L  (cliente real siguiendo la redirección)  -> http://evil.example/x
                          rc=6, «Could not resolve host: evil.example»
    Node ``new URL(loc, base)``  (parser WHATWG)      -> http://evil.example/x

Un cliente HTTP real **se va del producto**. WHATWG —el estándar que
implementan los navegadores— salta todas las barras iniciales al entrar en la
autoridad, y ``Location`` se resuelve con ese mismo parser (Fetch Standard).
Reproducido en ``viewer/tests/test_next_url_redireccion_seguida.py``, cuyo
negativo se pone rojo al retirar la defensa.

Bajo WHATWG, ``/\evil.example/x`` **crudo también sale**
(``new URL("/\evil.example/x", base)`` da ``http://evil.example/x``). Lo que lo
neutraliza en ESTA ruta es únicamente que Starlette lo percent-encodea: el
cliente nunca llega a ver la backslash. Es el transporte quien lo salva, no el
validador — razón de más para que el validador la rechace.

PRECISIONES SOBRE LO QUE SE DIJO MAL EN RONDAS ANTERIORES
----------------------------------------------------------
- **No** es que Chrome normalice ``\`` a ``/`` en esta cabecera: Starlette la
  codifica antes. Esa normalización es real, pero en otros contextos (un
  ``href`` crudo, un ``location.assign``), no aquí.
- **Chromium no reproduce el escape** de ``///…`` por esta cabecera; se midió
  (``tests/browser/test_browser_next_calibracion.py``). Eso es un **outlier de
  motor** —Chromium usa GURL, que no es conforme a WHATWG en todos los
  bordes—, **no** una propiedad de «resolver un ``Location``».
- La ronda anterior citó ``urljoin`` y ``httpx`` como si corroborasen a
  Chromium. **No corroboran nada de esto**: implementan **RFC 3986**, y los dos
  estándares difieren *exactamente* en ``///``. Usarlos para una pregunta de
  navegador es medir con el instrumento de la familia equivocada.

Por eso la propiedad que este módulo defiende es sobre la **representación**, y
no sobre el comportamiento de un motor en una versión. Apoyar una defensa en «hoy este
navegador no lo explota» es exactamente el razonamiento que produjo el defecto.

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

ENDURECIMIENTOS MÁS ALLÁ DE LOS SIETE CRITERIOS — DECLARADOS, NO IMPLÍCITOS
---------------------------------------------------------------------------
Estos tres los añade este módulo por su cuenta. Ninguno lo pedía el criterio;
los tres son lectura del principio «lo ambiguo se rechaza». Se listan aquí
porque un endurecimiento sin declarar es indistinguible de un accidente:

- **Segmentos ``.`` y ``..``**, y **``//`` en mitad del path**. MEDIDO: ninguno
  de los tres sale del origen. ``/.//evil.example/x`` se queda dentro. Pero los
  tres son cadenas que el navegador RESUELVE a otra cosa antes de pedir nada, y
  aceptar eso sería exactamente lo que este módulo dice no hacer. La barra
  final (``/v3/review/``) no es ambigua y sí se acepta.
- **Path no ASCII tras decodificar.**

EL FRAGMENTO SE ACEPTA, Y ES UNA DECISIÓN, NO UN OLVIDO
--------------------------------------------------------
La primera versión de este módulo rechazaba todo ``next`` con ``#``. Era un
error de acoplamiento, no de seguridad: ``/v3/review?workspace=alpha#ficha-3``
caía a ``/`` y el operador perdía **el ancla y los filtros** — justo la
regresión que el corte anterior acababa de arreglar, y que habría mordido en
silencio el día que alguien enlazase a una ficha concreta.

El fragmento se acepta porque los criterios 6 y 7 se le aplican igual que a la
query, y con más margen todavía: **el fragmento ni siquiera viaja al
servidor**, y en un ``Location`` sólo-path la autoridad la fija la URL base, de
modo que nada detrás del ``#`` puede sustituirla. Se le exige lo mismo que a la
query: sin controles, sin backslash cruda, sin porcentaje roto.

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
- **El trinquete de alcance de las pruebas sólo ve funciones llamadas
  ``_safe_next``.** Una superficie nueva que llame directamente a
  ``ruta_interna_o_defecto``, o que envuelva el validador con otro nombre, NO
  aparece en ese inventario — y evitar justo eso es para lo que el trinquete
  existe. Se declara porque un trinquete que se cree completo es peor que no
  tenerlo.
- **Que una redirección use este módulo no lo garantiza este módulo.** Queda
  deuda ajena a este microcarril, DECLARADA y no arreglada aquí: **seis** sitios
  construyen ``/login?next=…`` interpolando ``request.url.path`` sin codificar
  (``routers/readonly.py`` ×2, ``routers/reviews_console.py``, ``main.py`` ×2 y
  ``auth/dependencies.py``), mientras ``v3_review.py`` sí usa ``urlencode``.
  El recuento es MEDIDO aquí, no heredado: la revisión decía tres. No es un escape —el prefijo
  es fijo y el valor se revalida al volver por aquí—, pero es una incoherencia
  que merece su propio corte.
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
    # SEGMENTOS. `..` y `.` son representaciones que el navegador RESUELVE
    # antes de pedir nada, y un `//` en mitad del path es exactamente la misma
    # ambigüedad que se rechaza al principio, sólo que más adentro. Ninguno de
    # los tres sale del origen —está MEDIDO—, pero los tres son «una cadena
    # que significa otra cosa cuando alguien la interpreta», que es lo que este
    # módulo se niega a aceptar. Rechazarlos es la única lectura coherente del
    # principio declarado arriba.
    #
    # El último segmento vacío SÍ se admite: es la barra final de `/v3/review/`,
    # que no es ambigua sino una ruta con forma de directorio.
    segmentos = path.split("/")[1:]
    for indice, seg in enumerate(segmentos):
        if seg in ("..", "."):
            return False
        if seg == "" and indice != len(segmentos) - 1:
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

    # El path CRUDO, recortado a mano hasta el primer `?`. No se usa
    # `partes.path`: `urlsplit("///evil.example/x")` devuelve netloc vacío y
    # path `/evil.example/x`, es decir, **se come dos barras** y presenta como
    # ruta interna algo que el navegador lee como protocolo-relativo. Ése es
    # justo el escape que hay que cerrar, así que el criterio 3 se aplica sobre
    # lo que de verdad viaja. Criterio 7: el corte es por `?`, y lo que queda
    # detrás no interviene aquí.
    path_crudo = re.split(r"[?#]", next_url, maxsplit=1)[0]
    if not _componente_path_es_seguro(path_crudo):       # criterios 3 y 4
        return DESTINO_POR_DEFECTO
    if not _componente_path_es_seguro(partes.path):      # coherencia parser/crudo
        return DESTINO_POR_DEFECTO
    if not _path_decodificado_es_seguro(path_crudo):     # criterio 5
        return DESTINO_POR_DEFECTO

    # Criterios 6 y 7 aplicados a la query Y AL FRAGMENTO. Ambos se permiten
    # COMO LO QUE SON y ninguno ha participado en nada de lo anterior. Se les
    # exige sólo lo que puede romper el transporte de la cabecera (controles) o
    # cambiar de significado en el navegador (backslash cruda). Su `%XX` NO se
    # decodifica: detrás del primer `?` o `#` nada puede volver a ser host.
    for nombre, componente in (("query", partes.query), ("fragmento", partes.fragment)):
        if not componente:
            continue
        if _tiene_control(componente) or "\\" in componente:
            return DESTINO_POR_DEFECTO
        if _PORCENTAJE_ROTO.search(componente):
            return DESTINO_POR_DEFECTO

    return next_url
