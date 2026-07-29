# -*- coding: utf-8 -*-
"""Identificadores DERIVADOS de forma determinista.

El problema que resuelve este modulo: si el identificador de una entidad
provisional se generase con un contador o un UUID, la misma entidad recibiria
identificadores distintos en dos pasadas sobre el mismo corpus, y el grafo
resultante dependeria del numero de veces que se ha ejecutado la ingesta. Eso
convierte cualquier medicion en ruido.

Derivacion: `sha256(workspace \\x1f superficie_normalizada \\x1f tipo)`. Los tres
componentes son necesarios y ninguno sobra:

- `workspace`: dos bovedas pueden tener un "Ilya" cada una y NO son la misma
  entidad. Sin el, dos workspaces colisionarian en el mismo id provisional.
- superficie normalizada: es la identidad observable de la que se parte.
- tipo: `Character` "Umbra" y `Location` "Umbra" son entidades distintas; sin el
  tipo compartirian identificador.

El separador `\\x1f` (unit separator) no puede aparecer en ninguno de los tres
campos, asi que la concatenacion no es ambigua: `("ab", "c")` y `("a", "bc")`
producen digests distintos.
"""
from __future__ import annotations

import hashlib
from typing import Iterable, Sequence

from .normalization import normalize_surface

_SEP = "\x1f"
#: Marcador para el tipo ausente. No puede colisionar con un tipo real porque
#: el catalogo congelado solo admite nombres alfanumericos capitalizados.
_UNTYPED = "-"


def _digest(parts: Sequence[str], chars: int) -> str:
    raw = _SEP.join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:chars]


def derive_entity_id(
    *,
    workspace: str,
    normalized_surface: str,
    entity_type: str | None,
    prefix: str,
    digest_chars: int = 16,
) -> str:
    """Identificador estable para una entidad creada por el resolutor.

    Determinista: la misma terna produce el mismo identificador siempre, en
    cualquier maquina y en cualquier pasada. No depende del orden de las
    menciones ni del reloj.
    """
    if not workspace:
        raise ValueError("workspace vacio: el id derivado dejaria de ser por boveda")
    surface = normalize_surface(normalized_surface)
    if not surface:
        raise ValueError("superficie normalizada vacia: no hay identidad que derivar")
    parts = (workspace, surface, entity_type or _UNTYPED)
    return f"{prefix}{_digest(parts, digest_chars)}"


def derive_resolution_id(
    *,
    workspace: str,
    mention_ids: Iterable[str],
    prefix: str = "resolution:",
    digest_chars: int = 16,
) -> str:
    """Identificador estable de una resolucion, a partir de sus menciones.

    Se ordenan los `mention_ids` antes de mezclarlos: el mismo grupo de
    menciones en otro orden es el mismo grupo, y debe producir el mismo
    identificador. (`stable_id` del contrato exige justamente eso: "no
    dependiente del orden de arrays".)
    """
    ids = sorted(set(mention_ids))
    if not ids:
        raise ValueError("no hay mention_ids de los que derivar la resolucion")
    return f"{prefix}{_digest((workspace, *ids), digest_chars)}"


__all__ = ["derive_entity_id", "derive_resolution_id"]
