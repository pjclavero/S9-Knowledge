# -*- coding: utf-8 -*-
"""Filtro de unión del modo híbrido (Prioridad 2.1).

El híbrido tenía buen recall pero arrastraba los falsos positivos del
heurístico (precisión de entidades 0.634 en el benchmark). Este filtro aplica
tres reglas configurables sobre las ENTIDADES y registra qué se elimina:

  Regla A — acuerdo heurístico ∧ LLM  → alta confianza, se conserva.
  Regla B — solo LLM                  → se conserva si tiene evidencia, tipo
                                        válido, confianza ≥ umbral y no es weak.
  Regla C — solo heurístico           → se conserva SOLO si está en glosario, o
                                        es un nombre fuerte (no weak, no
                                        single-token, confianza alta). En otro
                                        caso se elimina (registrando el motivo).

Las relaciones NO se filtran aquí (pasan por relation_normalizer y por el
quality gate de auto_decider); solo se deduplican por from|type|to.
"""
from __future__ import annotations
from typing import Optional

_VALID_ENTITY_TYPES = {"Character", "Location", "Faction", "Object", "Event", "Concept"}


def _ekey(c) -> str:
    return f"{(getattr(c, 'name', '') or '').lower().strip()}|{getattr(c, 'entity_type', '') or ''}"


def _rkey(c) -> str:
    return (
        f"{(getattr(c, 'from_entity', '') or '').lower().strip()}|"
        f"{getattr(c, 'relation_type', '') or ''}|"
        f"{(getattr(c, 'to_entity', '') or '').lower().strip()}"
    )


def _is_single_token(name: Optional[str]) -> bool:
    return len((name or "").split()) == 1


def merge_hybrid(heuristic_cands: list, llm_cands: list,
                 conf_threshold: float = 0.7,
                 heuristic_only_min_conf: float = 0.85) -> tuple[list, dict]:
    """Combina y filtra candidatos híbridos. Devuelve (kept, stats)."""
    h_ents = [c for c in heuristic_cands if getattr(c, "kind", None) == "entity"]
    l_ents = [c for c in llm_cands if getattr(c, "kind", None) == "entity"]
    l_rels = [c for c in llm_cands if getattr(c, "kind", None) == "relation"]

    hmap = {_ekey(c): c for c in h_ents}
    lmap = {_ekey(c): c for c in l_ents}

    stats = {
        "entities_before": len(h_ents) + len(l_ents),
        "entities_before_unique": len(set(hmap) | set(lmap)),
        "rule_a_agreement": 0,
        "rule_b_llm_only": 0,
        "rule_c_heuristic_kept": 0,
        "filtered_out": 0,
        "filtered": [],  # {name, entity_type, reason, provenance}
    }
    kept: list = []

    for k in set(hmap) | set(lmap):
        h = hmap.get(k)
        l = lmap.get(k)
        if h and l:  # Regla A
            c = l if l.confidence >= h.confidence else h
            c.confidence = max(0.9, float(c.confidence))
            setattr(c, "_provenance", "both")
            stats["rule_a_agreement"] += 1
            kept.append(c)
        elif l and not h:  # Regla B — solo LLM
            ok = (
                bool(l.evidence)
                and (l.entity_type in _VALID_ENTITY_TYPES)
                and float(l.confidence) >= conf_threshold
                and not getattr(l, "weak", False)
            )
            if ok:
                setattr(l, "_provenance", "llm")
                stats["rule_b_llm_only"] += 1
                kept.append(l)
            else:
                stats["filtered_out"] += 1
                stats["filtered"].append({
                    "name": l.name, "entity_type": l.entity_type,
                    "reason": "llm_only_low_quality", "provenance": "llm",
                })
        else:  # Regla C — solo heurístico
            keep = (
                getattr(h, "glossary_match", False)
                or (not getattr(h, "weak", False)
                    and not _is_single_token(h.name)
                    and float(h.confidence) >= heuristic_only_min_conf)
            )
            if keep:
                setattr(h, "_provenance", "heuristic")
                stats["rule_c_heuristic_kept"] += 1
                kept.append(h)
            else:
                stats["filtered_out"] += 1
                stats["filtered"].append({
                    "name": h.name, "entity_type": h.entity_type,
                    "reason": "heuristic_only_uncorroborated", "provenance": "heuristic",
                })

    # Relaciones: dedup por from|type|to (sin filtrar por calidad aquí)
    seen: set = set()
    rels: list = []
    for r in l_rels:
        rk = _rkey(r)
        if rk not in seen:
            seen.add(rk)
            rels.append(r)

    stats["entities_kept"] = len(kept)
    stats["relations_kept"] = len(rels)
    return kept + rels, stats
