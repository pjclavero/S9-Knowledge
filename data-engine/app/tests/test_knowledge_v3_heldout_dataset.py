# -*- coding: utf-8 -*-
"""El split HELD-OUT existe, carga con el arnes real y no miente sobre si mismo.

Este fichero es del EQUIPO INDEPENDIENTE (dosier §9). Comprueba lo minimo e
imprescindible y nada mas:

1. el dataset entero carga con el loader REAL usando `split="heldout"`;
2. todo el gold valida contra los contratos CONGELADOS (mismo validador que el
   gate de contratos, no una copia);
3. no hay ninguna clave de hecho duplicada — dos afirmaciones gold para el
   mismo hecho harian imposible emparejar uno a uno y regalarian recall;
4. los recuentos del manifiesto cuadran con lo que hay en disco, y el dataset
   no ha derivado respecto a su autoria (se regenera byte a byte).

Lo que este fichero NO hace, a proposito: no mide nada, no ejecuta el arnes y
no engancha el held-out a ningun flujo automatico. Medir con held-out es una
decision de quien coordina, no un efecto secundario de correr los tests.
"""
from __future__ import annotations

import importlib.util

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.benchmarks.loader import (  # noqa: E402
    DATASETS_DIR,
    SOURCE_FILES,
    contract_documents,
    load_gold,
)
from knowledge_v3.benchmarks.matching import MatchConfig, fact_key  # noqa: E402

SPLIT = "heldout"
BUILDER = DATASETS_DIR / SPLIT / "_authoring" / "build_heldout.py"


def test_el_split_heldout_carga_valida_y_cuadra():
    # 1. carga con el loader real, con la doble marca de split (sobre + documento)
    gold = load_gold(SPLIT, validate=True)
    assert gold.split == SPLIT
    assert gold.sources, "el split held-out no trae ninguna fuente"
    for entry in gold.manifest["sources"]:
        base = DATASETS_DIR / SPLIT / "sources" / entry["source_id"]
        for name in SOURCE_FILES:
            assert (base / f"{name}.json").exists(), f"{entry['source_id']}/{name}"

    # 2. contratos congelados: `validate=True` ya los ha pasado; aqui se
    #    comprueba que de verdad habia documentos que validar y de que familia.
    docs = contract_documents(gold)
    assert len(docs) >= 250, "el held-out perdio documentos"
    assert {d["contract_id"] for d in docs} == {
        "source-asset/v3-internal-v1",
        "source-episode/v3-internal-v1",
        "evidence-fragment/v3-internal-v1",
        "entity-mention/v3-internal-v1",
        "entity-resolution/v3-internal-v1",
        "claim-proposal/v3-internal-v1",
        "fact-assertion/v3-internal-v1",
        "graph-mutation-plan/v3-internal-v1",
        "game-profile/v3-internal-v1",
    }
    for doc in docs:
        assert (doc.get("metadata") or {})["benchmark"]["split"] == SPLIT

    # 3. cero claves de hecho duplicadas
    config = MatchConfig(symmetric_predicates=gold.symmetric_predicates)
    claves = [fact_key(a, config) for a in gold.assertions]
    assert None not in claves, "afirmacion gold sin sujeto/predicado/objeto"
    assert len(claves) == len(set(claves)), "dos afirmaciones gold para el mismo hecho"

    # 4. el manifiesto cuadra con lo que hay en disco
    totals = gold.manifest["totals"]
    assert totals["episodes"] == len(gold.episodes)
    assert totals["fragments"] == len(gold.fragments)
    assert totals["mentions"] == len(gold.mentions)
    assert totals["resolutions"] == len(gold.resolutions)
    assert totals["claims"] == len(gold.claims)
    assert totals["assertions"] == len(gold.assertions)
    assert totals["plans"] == len(gold.plans)
    assert totals["negatives"] == len(gold.negatives)
    assert totals["decisions"] == len(gold.decisions)
    assert totals["claims_extractor_gold"] == len(gold.claims_for("extractor"))


def test_el_held_out_se_regenera_byte_a_byte():
    """El gold esta versionado pero se GENERA. Si deriva, el gate se pone rojo."""
    spec = importlib.util.spec_from_file_location("heldout_builder", BUILDER)
    assert spec and spec.loader, f"no encuentro el generador en {BUILDER}"
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    assert builder.build_dataset() == builder.build_dataset(), "la generacion no es determinista"
    assert builder.check_dataset() == [], "el held-out ha derivado respecto a su autoria"
