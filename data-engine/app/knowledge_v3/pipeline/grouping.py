# -*- coding: utf-8 -*-
"""Agrupacion de menciones en peticiones de resolucion.

DEFECTO DE SUBSISTEMA QUE ESTE MODULO RODEA (ver docs/v3/11-e2e.md, D-2)
-----------------------------------------------------------------------
El extractor entrega `EntityMention` sueltas con `coreference_candidates`
rellenado (`extraction/coreference.py`), y el resolutor exige un grupo ya
formado (`ResolutionRequest.mentions`, `resolution/resolver.py:38`). Nadie
implementa el paso intermedio: el cierre transitivo de `coreference_candidates`.

La UNICA implementacion de ese cierre en el repositorio vive en
`benchmarks/harness.py:243` (`clusters_from_candidates`), que es un modulo de
MEDICION, no de ejecucion — y ademas descarta los grupos de un solo elemento
porque a la metrica de correferencia no le interesan.

Aqui se reusa exactamente el mismo algoritmo (union-find sobre el grafo no
dirigido, representante = id minimo, salida ordenada) para no introducir una
segunda semantica de correferencia en el sistema, y se conservan los
singletons, que la cadena si necesita: una mencion sin correferente sigue
teniendo que resolverse contra el catalogo.

Esto NO es logica de negocio del orquestador: no decide que es correferente de
que —eso ya lo decidio el extractor— sino que traduce la forma en que un
subsistema lo dice a la forma en que el siguiente lo pide.
"""
from __future__ import annotations

from typing import Sequence

from ..contracts.mention import EntityMention


def mention_groups(mentions: Sequence[EntityMention]) -> list[list[EntityMention]]:
    """Cierre transitivo de `coreference_candidates`, singletons incluidos.

    Determinista: los grupos salen ordenados por el id de su primera mencion y
    dentro de cada grupo por `mention_id`. Un candidato que apunta a una
    mencion que no esta en el lote se ignora (no se inventa una mencion).
    """
    by_id = {m.mention_id: m for m in mentions}
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for mention in mentions:
        find(mention.mention_id)
        for other in mention.coreference_candidates or []:
            if other in by_id:
                union(mention.mention_id, other)

    groups: dict[str, list[str]] = {}
    for node in sorted(parent):
        groups.setdefault(find(node), []).append(node)
    return [
        [by_id[mid] for mid in sorted(ids)]
        for _, ids in sorted(groups.items())
    ]


__all__ = ["mention_groups"]
