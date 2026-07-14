# -*- coding: utf-8 -*-
"""Prioridad 2.1 — normalizador de extremos de relación (alias + dirección)."""
from __future__ import annotations
import sys
from pathlib import Path
_APP=Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path: sys.path.insert(0,str(_APP))
from review.relation_normalizer import normalize_relations, resolve_endpoint, build_alias_map

ENTS=[{"name":"Kakita Asuka","entity_type":"Character"},
      {"name":"Bayushi Hisao","entity_type":"Character"},
      {"name":"Clan Escorpión","entity_type":"Faction"},
      {"name":"Ciudad Moto","entity_type":"Location"}]

def _rel(f,t,rt="KNOWS",conf=0.9):
    return {"kind":"relation","from_entity":f,"to_entity":t,"relation_type":rt,
            "evidence":"x","confidence":conf}

def test_alias_from_resolves_to_canonical():
    rels=[_rel("Asuka","Bayushi Hisao")]
    normalize_relations(ENTS,rels)
    assert rels[0]["from_entity"]=="Kakita Asuka"
    assert rels[0]["_from_match"] in ("alias_match","canonical_match")

def test_alias_to_resolves_to_canonical():
    rels=[_rel("Kakita Asuka","Hisao")]
    normalize_relations(ENTS,rels)
    assert rels[0]["to_entity"]=="Bayushi Hisao"

def test_exact_match_type():
    rels=[_rel("Kakita Asuka","Bayushi Hisao")]
    normalize_relations(ENTS,rels)
    assert rels[0]["_from_match"]=="exact_match"

def test_direction_fix_member_of():
    rels=[_rel("Clan Escorpión","Bayushi Hisao",rt="MEMBER_OF")]
    normalize_relations(ENTS,rels)
    assert rels[0]["from_entity"]=="Bayushi Hisao"
    assert rels[0]["to_entity"]=="Clan Escorpión"

def test_ambiguous_endpoint_goes_to_review():
    ents=ENTS+[{"name":"Bayushi Reika","entity_type":"Character"}]
    rels=[_rel("Bayushi","Ciudad Moto",rt="LOCATED_IN")]  # 'Bayushi' ambiguo
    normalize_relations(ents,rels)
    assert rels[0]["_from_match"]=="ambiguous_match"
    assert rels[0]["status"]=="needs_review"
    assert rels[0]["confidence"]<=0.55

def test_unresolved_endpoint_lowers_confidence():
    rels=[_rel("Personaje Inexistente","Bayushi Hisao",conf=0.95)]
    normalize_relations(ENTS,rels)
    assert rels[0]["_from_match"]=="unresolved"
    assert rels[0]["status"]=="needs_review"
    assert rels[0]["confidence"]<=0.55

def test_workspace_glossary_alias_applied():
    rels=[_rel("La Cazadora","Bayushi Hisao")]
    normalize_relations(ENTS,rels,glossary_aliases={"La Cazadora":"Kakita Asuka"})
    assert rels[0]["from_entity"]=="Kakita Asuka"

def test_direction_fix_with_unextracted_faction():
    # 'Clan Escorpión' no está entre las entidades extraídas; se rescata por patrón
    ents=[{"name":"Bayushi Hisao","entity_type":"Character"}]
    rels=[_rel("Clan Escorpión","Bayushi Hisao",rt="MEMBER_OF")]
    normalize_relations(ents,rels)
    assert rels[0]["from_entity"]=="Bayushi Hisao"
    assert rels[0]["to_entity"]=="Clan Escorpión"
    assert rels[0].get("status")!="needs_review"
