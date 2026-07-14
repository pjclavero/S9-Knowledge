# -*- coding: utf-8 -*-
"""Prioridad 2.1 — filtro de union del modo hibrido (reglas A/B/C)."""
from __future__ import annotations
import sys
from pathlib import Path
_APP=Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path: sys.path.insert(0,str(_APP))
from review.hybrid_filter import merge_hybrid
from review.models import Candidate

def _ent(name, conf=0.9, weak=False, gloss=False, etype="Character", ev="evidencia textual"):
    return Candidate(candidate_id="x", source_id="s", segment_id="g", workspace="w",
                     kind="entity", name=name, entity_type=etype, confidence=conf,
                     evidence=ev, weak=weak, glossary_match=gloss,
                     timestamp_start="00:00:00", timestamp_end="00:01:00", source_kind="audio")

def _rel(f,t,rt="KNOWS"):
    return Candidate(candidate_id="r", source_id="s", segment_id="g", workspace="w",
                     kind="relation", name=None, entity_type=None, from_entity=f, to_entity=t,
                     relation_type=rt, confidence=0.9, evidence="ev",
                     timestamp_start="00:00:00", timestamp_end="00:01:00", source_kind="audio")

def test_rule_a_agreement_boosts_confidence():
    h=[_ent("Kakita Asuka", conf=0.7)]; l=[_ent("Kakita Asuka", conf=0.8)]
    kept,st=merge_hybrid(h,l)
    ents=[c for c in kept if c.kind=="entity"]
    assert len(ents)==1 and ents[0].confidence>=0.9
    assert st["rule_a_agreement"]==1

def test_rule_b_llm_only_valid_kept():
    kept,st=merge_hybrid([], [_ent("Isawa Seiji", conf=0.9)])
    assert st["rule_b_llm_only"]==1 and st["filtered_out"]==0

def test_rule_b_llm_only_low_quality_filtered():
    kept,st=merge_hybrid([], [_ent("Cosa", conf=0.3, ev="")])
    assert st["filtered_out"]==1
    assert st["filtered"][0]["reason"]=="llm_only_low_quality"

def test_rule_c_heuristic_only_weak_filtered():
    kept,st=merge_hybrid([_ent("Todo", conf=0.9, weak=True)], [])
    assert st["filtered_out"]==1
    assert st["filtered"][0]["reason"]=="heuristic_only_uncorroborated"
    assert all(c.name!="Todo" for c in kept)

def test_rule_c_heuristic_only_single_token_filtered():
    kept,st=merge_hybrid([_ent("Asuka", conf=0.9)], [])  # single token, no gloss
    assert st["filtered_out"]==1

def test_rule_c_heuristic_only_glossary_kept():
    kept,st=merge_hybrid([_ent("Asuka", conf=0.9, gloss=True)], [])
    assert st["rule_c_heuristic_kept"]==1

def test_rule_c_heuristic_only_strong_compound_kept():
    kept,st=merge_hybrid([_ent("Doji Satsume", conf=0.9)], [])
    assert st["rule_c_heuristic_kept"]==1

def test_relations_preserved_and_deduped():
    l=[_ent("Kakita Asuka"), _rel("Kakita Asuka","Bayushi Hisao"), _rel("Kakita Asuka","Bayushi Hisao")]
    kept,st=merge_hybrid([], l)
    rels=[c for c in kept if c.kind=="relation"]
    assert len(rels)==1 and st["relations_kept"]==1

def test_stats_before_after():
    h=[_ent("Doji Satsume"), _ent("Todo", weak=True)]
    l=[_ent("Doji Satsume"), _ent("Isawa Seiji")]
    kept,st=merge_hybrid(h,l)
    assert st["entities_before_unique"]==3  # Doji(both), Todo, Isawa
    assert st["entities_kept"]+st["filtered_out"]==3
