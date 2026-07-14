# -*- coding: utf-8 -*-
"""Prioridad 2.1 — glosario de alias por workspace."""
from __future__ import annotations
import json, sys
from pathlib import Path
_APP=Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path: sys.path.insert(0,str(_APP))
from review.workspace_aliases import load_workspace_aliases, load_alias_records

def _write(root, ws, data):
    d=root/"data-engine"/"config"/"aliases"; d.mkdir(parents=True,exist_ok=True)
    (d/f"{ws}.json").write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")

def test_loads_reviewed_aliases(tmp_path):
    _write(tmp_path,"leyenda",{"workspace":"leyenda","aliases":[
        {"alias":"La Cazadora","canonical":"Kakita Asuka","type":"Character","reviewed":True}]})
    m=load_workspace_aliases(tmp_path,"leyenda")
    assert m=={"La Cazadora":"Kakita Asuka"}

def test_unreviewed_filtered(tmp_path):
    _write(tmp_path,"leyenda",{"workspace":"leyenda","aliases":[
        {"alias":"X","canonical":"Y","reviewed":False}]})
    assert load_workspace_aliases(tmp_path,"leyenda")=={}

def test_missing_file(tmp_path):
    assert load_workspace_aliases(tmp_path,"nope")=={}

def test_workspace_isolation(tmp_path):
    # fichero declara otro workspace -> no se aplica
    _write(tmp_path,"leyenda",{"workspace":"otro","aliases":[
        {"alias":"A","canonical":"B","reviewed":True}]})
    assert load_workspace_aliases(tmp_path,"leyenda")=={}

def test_alias_of_location_and_relation_use(tmp_path):
    _write(tmp_path,"leyenda",{"workspace":"leyenda","aliases":[
        {"alias":"La Ciudad","canonical":"Ciudad Moto","type":"Location","reviewed":True},
        {"alias":"El Espía","canonical":"Bayushi Hisao","type":"Character","reviewed":True}]})
    recs=load_alias_records(tmp_path,"leyenda")
    assert len(recs)==2
    m=load_workspace_aliases(tmp_path,"leyenda")
    assert m["La Ciudad"]=="Ciudad Moto" and m["El Espía"]=="Bayushi Hisao"

def test_same_alias_two_workspaces_isolated(tmp_path):
    _write(tmp_path,"leyenda",{"workspace":"leyenda","aliases":[
        {"alias":"El Maestro","canonical":"Doji Satsume","reviewed":True}]})
    _write(tmp_path,"otra",{"workspace":"otra","aliases":[
        {"alias":"El Maestro","canonical":"Akodo Toturi","reviewed":True}]})
    assert load_workspace_aliases(tmp_path,"leyenda")["El Maestro"]=="Doji Satsume"
    assert load_workspace_aliases(tmp_path,"otra")["El Maestro"]=="Akodo Toturi"
