# -*- coding: utf-8 -*-
"""Comparacion de instantes ISO-8601 UTC del ledger.

Por que no se compara con `<` sobre la cadena: el patron del contrato admite
fraccion de segundo opcional, y `"...:00Z" > "...:00.5Z"` en orden lexicografico
('Z' = 0x5A, '.' = 0x2E). Un ledger que ordenase asi colocaria un hecho medio
segundo posterior ANTES que el anterior, y la bitemporalidad quedaria invertida
sin que nadie lo notara.

Tampoco se usa `datetime`: los ejes de tiempo de validez y de evento se expresan
en el calendario del mundo de juego (`calendar_id`) y pueden llevar anos como
`1041`, fuera de todo rango util del calendario proleptico. Aqui solo se
necesita un ORDEN TOTAL estable, no aritmetica de fechas.

Este modulo no genera timestamps. NINGUNA funcion del ledger llama a un reloj:
todos los instantes entran como dato desde fuera.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

#: Mismo patron que `_common-v3.schema.json#/$defs/iso8601_utc`.
_ISO_UTC = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?Z$"
)

TimeKey = Tuple[int, int, int, int, int, int, int]


def is_iso_utc(value: object) -> bool:
    """True si `value` es un instante ISO-8601 UTC valido para la familia v3."""
    return isinstance(value, str) and _ISO_UTC.match(value) is not None


def time_key(value: str) -> TimeKey:
    """Clave de orden total de un instante ISO-8601 UTC.

    La fraccion de segundo se normaliza a microsegundos para que `10:00:00Z`,
    `10:00:00.0Z` y `10:00:00.000000Z` sean el MISMO instante.
    """
    m = _ISO_UTC.match(value) if isinstance(value, str) else None
    if m is None:
        raise ValueError(f"instante ISO-8601 UTC invalido: {value!r}")
    frac = (m.group(7) or "")[:6].ljust(6, "0")
    return (
        int(m.group(1)), int(m.group(2)), int(m.group(3)),
        int(m.group(4)), int(m.group(5)), int(m.group(6)), int(frac),
    )


def _key_or_none(value: Optional[str]) -> Optional[TimeKey]:
    return None if value is None else time_key(value)


def before_or_equal(a: Optional[str], b: Optional[str]) -> bool:
    """`a <= b` tratando `None` como «sin limite» (misma convencion que el validador)."""
    if a is None or b is None:
        return True
    return time_key(a) <= time_key(b)


def strictly_before(a: str, b: str) -> bool:
    return time_key(a) < time_key(b)


def same_instant(a: Optional[str], b: Optional[str]) -> bool:
    if a is None or b is None:
        return a is b or a == b
    return time_key(a) == time_key(b)


def in_validity_interval(
    instant: str,
    valid_from: Optional[str],
    valid_to: Optional[str],
    *,
    include_unknown_start: bool = False,
) -> bool:
    """Pertenencia al intervalo de vigencia SEMIABIERTO `[valid_from, valid_to)`.

    Semiabierto a proposito: si una afirmacion se cierra en T y la siguiente
    empieza en T (el caso normal de una supersesion), un intervalo cerrado
    haria que AMBAS fuesen validas en T y la consulta devolveria dos verdades
    incompatibles para el mismo instante del mundo.

    `valid_from is None` significa «inicio desconocido», NO «desde siempre». Por
    defecto no cuenta como vigente: afirmar vigencia a partir de un dato que no
    existe es inventar. `include_unknown_start=True` lo admite de forma
    explicita y consciente.
    """
    ik = time_key(instant)
    if valid_from is None:
        if not include_unknown_start:
            return False
    elif ik < time_key(valid_from):
        return False
    if valid_to is not None and ik >= time_key(valid_to):
        return False
    return True


__all__ = [
    "TimeKey",
    "before_or_equal",
    "in_validity_interval",
    "is_iso_utc",
    "same_instant",
    "strictly_before",
    "time_key",
]
