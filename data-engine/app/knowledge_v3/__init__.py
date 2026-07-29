# -*- coding: utf-8 -*-
"""S9-Knowledge V3 — subsistema aislado.

Fase 6 (contratos): solo `contracts/` y `adapters/`. Ningun modulo de este
paquete escribe en Neo4j, llama a proveedores ni toca produccion.

`relation-candidate/internal-v1` (`relations/contracts.py`) sigue siendo la
frontera intocable aguas abajo; se alcanza mediante
`knowledge_v3.adapters.relation_candidate_v1`.
"""
from __future__ import annotations

__all__ = ["contracts", "adapters"]
