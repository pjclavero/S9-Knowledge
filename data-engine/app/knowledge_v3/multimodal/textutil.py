# -*- coding: utf-8 -*-
"""Segmentacion textual determinista y decodificacion de bytes.

Todo lo de este modulo devuelve tramos `(start, end, texto)` con offsets
ABSOLUTOS sobre la cadena de entrada, de forma que siempre se cumple
`texto == entrada[start:end]`. Es la base del invariante de anclaje: si la
segmentacion mintiera aqui, toda la evidencia aguas abajo apuntaria mal.

Normalizacion de saltos de linea — decision documentada
-------------------------------------------------------
`decode_text()` convierte CRLF y CR sueltos a LF ANTES de segmentar. Los
offsets de todo el subsistema se refieren, por tanto, al **texto normalizado**,
no a los bytes originales del fichero.

Es una decision, y estas son las dos razones:

1. Sin ella, un `.txt` de Windows no casa con el separador de parrafos
   (`\\n\\s*\\n`) y el fichero ENTERO acaba en un unico episodio; pasado de
   200.000 caracteres, el contrato lo rechaza y la fuente se pierde por
   completo. La granularidad de episodios no puede depender del sistema
   operativo donde se escribio el fichero.
2. El anclaje sigue siendo verificable: `episode.text[start:end]` es exacto
   contra el texto del episodio, que es la unidad direccionable del contrato.
   Quien quiera volver a los bytes originales tiene `content_hash` del asset.

La normalizacion es idempotente, asi que aplicarla dos veces en la cadena no
cambia nada.
"""
from __future__ import annotations

import re

from . import errors

#: Fin de frase: puntuacion terminal seguida de espacio o fin de linea. No
#: pretende ser un segmentador linguistico: pretende ser reproducible.
_SENTENCE_END = re.compile(r"[.!?…](?=\s|$)")

#: Separador de parrafos: una o mas lineas en blanco.
_PARAGRAPH_SPLIT = re.compile(r"\n[ \t]*\n")

#: Bytes de control que no aparecen en texto legible y delatan un binario.
_BINARY_MARKERS = bytes(range(0, 9)) + bytes(range(14, 32))


def normalize_newlines(text: str) -> str:
    """CRLF y CR sueltos -> LF. Idempotente.

    Se aplica ANTES de segmentar, de modo que los offsets se refieren al texto
    normalizado (ver la nota del encabezado del modulo).
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def decode_text(data: bytes, *, where: str = "fuente") -> str:
    """Decodifica UTF-8 estricto, rechaza binarios y normaliza saltos de linea.

    No usa `errors="replace"`: sustituir bytes ilegibles por `�` produce un
    texto que parece valido y no lo es, y ese texto acabaria como evidencia
    literal de algo que nadie escribio.
    """
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    sample = data[:4096]
    if b"\x00" in sample or sum(sample.count(bytes([b])) for b in _BINARY_MARKERS) > 0:
        raise errors.NormalizationError(
            errors.CORRUPT_SOURCE,
            f"{where} contiene bytes de control binarios: no es texto",
        )
    try:
        return normalize_newlines(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise errors.NormalizationError(
            errors.UNDECODABLE_TEXT, f"{where} no es UTF-8 valido: {exc}"
        ) from exc


def strip_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Recorta espacios en los extremos de `[start, end)` conservando offsets."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def split_paragraphs(text: str) -> list[tuple[int, int, str]]:
    """Parrafos separados por linea en blanco, con offsets absolutos."""
    spans: list[tuple[int, int, str]] = []
    cursor = 0
    for match in _PARAGRAPH_SPLIT.finditer(text):
        spans.append((cursor, match.start(), text))
        cursor = match.end()
    spans.append((cursor, len(text), text))
    out: list[tuple[int, int, str]] = []
    for start, end, _ in spans:
        start, end = strip_span(text, start, end)
        if start < end:
            out.append((start, end, text[start:end]))
    return out


def split_sentences(text: str) -> list[tuple[int, int, str]]:
    """Frases de `text`, con offsets absolutos sobre `text`.

    Si no hay puntuacion terminal, devuelve el texto entero como una frase: es
    preferible un fragmento largo y correcto a varios cortos e inventados.
    """
    out: list[tuple[int, int, str]] = []
    cursor = 0
    for match in _SENTENCE_END.finditer(text):
        end = match.end()
        start, end = strip_span(text, cursor, end)
        if start < end:
            out.append((start, end, text[start:end]))
        cursor = match.end()
    start, end = strip_span(text, cursor, len(text))
    if start < end:
        out.append((start, end, text[start:end]))
    return out
