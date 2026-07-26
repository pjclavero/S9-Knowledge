# -*- coding: utf-8 -*-
"""Bloque 2 (motor de relaciones v2) — correccion de medicion + selector v2.

Tests REALES (sin skip/xfail, asserts efectivos, sin bajar umbrales) que fijan:

PARTE A — CORRECCION DE MEDICION (honesta):
  * `matching.structural_flags` acredita el predicado con IGUALDAD CANONICA
    ESTRICTA (`ontology.predicate_exact_strict`), NO con
    `vocabulary.predicates_match`.
  * Se reconoce el match EXACTO de los 11 canonicos que `vocabulary` marca
    out_of_vocab (antes infra-contabilizados: None != None).
  * Se ELIMINA el credito por alias que colapsa a otro canonico (LIVES_IN emitido
    como LOCATED_IN ya NO cuenta como predicado correcto).
  * Un fallo real sigue siendo fallo (la correccion no convierte fallos en aciertos).
  * Re-baselizacion: sobre el MISMO motor base (v1), el metro corregido da MENOS
    aciertos de predicado que el metro roto (se quita el credito por alias).

PARTE B — SELECTOR DE PREDICADOS v2:
  * Default `v1` == comportamiento base (metric-neutral por defecto).
  * Generacion de candidatos NO limitada a 5; filtro por dominio/rango; puntuacion;
    abstencion por margen insuficiente / sin evidencia lexica; fallback seguro a
    RELATED_TO; cada familia; predicados confundibles; determinismo.
  * Con `v2`, `predicate_structural` supera el gate experimental de B2 (>= 0.50)
    con el metro corregido, SIN bajar pair_F1 ni evidence_correct.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from relations import ontology as O
from relations import predicate_selector as PS
from relations import vocabulary as V
from relations.benchmark import matching as M
from relations.benchmark import metrics as BM
from relations.benchmark.matching import match_predictions, structural_flags
from relations.benchmark.runner import load_corpus, run_benchmark
from relations.pipeline import PipelineConfig, PipelineError, config_from_dict

_CORPUS_DIR = Path(__file__).resolve().parent / "data" / "relation_benchmark"

# 11 canonicos del GT que `vocabulary` marca out_of_vocab (canonical=None): su
# match EXACTO estaba infra-contabilizado por `predicates_match` (None != None).
_OUT_OF_VOCAB = (
    "ALIAS_OF", "CREATED", "FOUNDED", "GUARDS", "KNOWS", "LEADS", "MARRIED_TO",
    "MENTOR_OF", "PARENT_OF", "SIBLING_OF", "TRUSTS",
)


# ---------------------------------------------------------------------------
# Utilidades de construccion de pred/gt para structural_flags
# ---------------------------------------------------------------------------
def _gt(predicate="MEMBER_OF", **over):
    base = {
        "relation_id": "rel-x", "source_id": "src-99", "workspace": "eldoria",
        "segment_id": "src-99#s1", "subject_id": "a", "subject_text": "A",
        "subject_type": "Character", "predicate": predicate, "object_id": "b",
        "object_text": "B", "object_type": "Faction", "evidence_text": "A ... B",
        "evidence_start": 0, "evidence_end": 10, "negated": False,
        "temporal_status": "PRESENT", "epistemic_status": "ASSERTED",
        "direction": "SUBJECT_TO_OBJECT", "expected_decision": "ACCEPT",
        "annotator_notes": "",
    }
    base.update(over)
    return base


def _pred(predicate="MEMBER_OF", **over):
    base = {
        "candidate_id": "c1", "source_id": "src-99", "workspace": "eldoria",
        "subject_id": "a", "object_id": "b", "subject_type": "Character",
        "object_type": "Faction", "predicate": predicate,
        "direction": "SUBJECT_TO_OBJECT", "negated": False, "temporal_scope": None,
        "epistemic_status": "ASSERTED", "evidence_text": "A ... B",
        "evidence_start": 0, "evidence_end": 10, "consensus_state": "PARTIAL_CONSENSUS",
        "recommendation": "propose",
    }
    base.update(over)
    return base


@pytest.fixture(scope="module")
def corpus():
    return load_corpus(_CORPUS_DIR)


# ===========================================================================
# PARTE A — CORRECCION DE MEDICION
# ===========================================================================
def test_meter_uses_strict_canonical_equality_not_vocabulary():
    """El acierto de predicado del arnes ES `ontology.predicate_exact_strict`."""
    # Caso alias: vocabulary lo premia, el estricto (y el arnes) NO.
    flags = structural_flags(_pred(predicate="LOCATED_IN"), _gt(predicate="LIVES_IN"))
    assert flags["predicate_correct"] is False
    assert V.predicates_match("LOCATED_IN", "LIVES_IN") is True  # el sesgo antiguo
    assert O.predicate_exact_strict("LOCATED_IN", "LIVES_IN") is False


@pytest.mark.parametrize("pred_name", _OUT_OF_VOCAB)
def test_meter_recognizes_exact_match_of_out_of_vocab(pred_name):
    """El match EXACTO de un canonico out_of_vocab AHORA cuenta (antes: None!=None).

    Se ajustan los tipos para que sea un par plausible del predicado; la correccion
    del metro es sobre el PREDICADO, no sobre los tipos.
    """
    o = O.ONTOLOGY[pred_name]
    s_type = sorted(o.domain)[0]
    o_type = sorted(o.range)[0]
    flags = structural_flags(
        _pred(predicate=pred_name, subject_type=s_type, object_type=o_type),
        _gt(predicate=pred_name, subject_type=s_type, object_type=o_type),
    )
    assert flags["predicate_correct"] is True, f"{pred_name} exacto deberia acertar"
    # `vocabulary` NO reconoce ni el match exacto de estos (out_of_vocab).
    assert V.predicates_match(pred_name, pred_name) is False


def test_meter_removes_alias_credit_for_all_alias_collapse_predicates():
    """Los 3 predicados con credito por alias (LIVES_IN/ENEMY_OF/SUCCEEDED) dejan de
    puntuar cuando se predice su canonico-destino de vocabulary."""
    for gt_pred, vocab_pred in (("LIVES_IN", "LOCATED_IN"),
                                ("ENEMY_OF", "ENEMIES_WITH"),
                                ("SUCCEEDED", "SUCCESSOR_OF")):
        flags = structural_flags(_pred(predicate=vocab_pred), _gt(predicate=gt_pred))
        assert flags["predicate_correct"] is False, (
            f"predecir {vocab_pred} para GT {gt_pred} NO es acertar el predicado")
        assert V.predicates_match(vocab_pred, gt_pred) is True  # credito antiguo


def test_meter_exact_match_still_counts():
    """Un acierto EXACTO canonico sigue contando como correcto."""
    assert structural_flags(_pred(predicate="MEMBER_OF"),
                            _gt(predicate="MEMBER_OF"))["predicate_correct"] is True


def test_meter_wrong_prediction_still_wrong():
    """La correccion NO convierte un fallo en acierto."""
    assert structural_flags(_pred(predicate="OWNS"),
                            _gt(predicate="MEMBER_OF"))["predicate_correct"] is False


def test_rebaseline_corrected_meter_lowers_base_predicate_exact(corpus):
    """Re-baselizacion honesta sobre el MISMO motor base (v1): el metro corregido
    da MENOS aciertos de predicado que el metro roto (se quita el credito por alias).

    * metro roto (vocabulary.predicates_match): 11/43 = 0.2558
    * metro corregido (predicate_exact_strict): 9/43 = 0.2093
    Ambos sobre EXACTAMENTE los mismos TP de existencia del motor base.
    """
    run = run_benchmark(corpus, mode="baseline1")  # default = v1
    match = match_predictions(run.predictions,
                              [r for r in corpus.relations if r["source_id"] in set(run.source_ids)])
    tp = match.true_positives
    corrected = sum(1 for m in tp if m["flags"]["predicate_correct"])
    broken = sum(1 for m in tp
                 if V.predicates_match(m["pred"]["predicate"], m["gt"]["predicate"]))
    assert broken == 11, broken
    assert corrected == 9, corrected
    assert corrected < broken, "el metro corregido debe BAJAR respecto al roto (honesto)"
    assert round(corrected / len(tp), 4) == 0.2093


# ===========================================================================
# PARTE B — SELECTOR v2: default metric-neutral
# ===========================================================================
def test_default_predicate_selector_is_v1():
    assert PipelineConfig().predicate_selector == "v1"


def test_default_equals_v1_equals_no_override(corpus):
    """Default (sin override) == v1 explicito: predicciones y hashes IDENTICOS."""
    base = run_benchmark(corpus, mode="baseline1")
    v1 = run_benchmark(corpus, mode="baseline1", predicate_selector="v1")
    assert base.result_hashes() == v1.result_hashes()
    assert base.predictions == v1.predictions


def test_config_rejects_invalid_selector():
    with pytest.raises(PipelineError):
        config_from_dict({"predicate_selector": "v3"})


# ===========================================================================
# PARTE B — SELECTOR v2: generacion, filtro, puntuacion
# ===========================================================================
def test_candidate_generation_not_limited_to_five():
    """El selector propone predicados MAS ALLA de los 5 del selector v1."""
    five = {"MEMBER_OF", "OWNS", "LOCATED_IN", "PARTICIPATED_IN", "RELATED_TO"}
    sel = PS.select("Character", "Character", "Torin es hermano de Aldric", {})
    assert sel.predicate == "SIBLING_OF"
    assert sel.predicate not in five


def test_domain_range_filter_discards_type_incompatible_candidate():
    """El filtro de dominio/rango DESCARTA un candidato con cue lexico pero tipos
    incompatibles: 'vive en' sugiere LIVES_IN, pero el objeto es Object (no Lugar),
    asi que LIVES_IN NO puede ser candidato."""
    sel = PS.select("Character", "Object", "Draven vive en su Filo de Luna", {})
    cand_preds = {c.predicate for c in sel.candidates}
    assert "LIVES_IN" not in cand_preds  # descartado por rango (Object no es Lugar)
    assert sel.predicate != "LIVES_IN"


def test_abstention_when_prior_only_no_lexical():
    """Sin evidencia lexica (solo prior de tipos) -> ABSTENCION (marca revision)."""
    sel = PS.select("Character", "Faction", "Draven y la Orden del Alba", {})
    assert sel.predicate == "MEMBER_OF"  # prior de forma Persona+Organizacion
    assert sel.abstained is True
    assert sel.fallback is False


def test_abstention_when_low_margin_between_confusable_families():
    """Dos candidatos lexicos de familias distintas y margen insuficiente ->
    ABSTENCION en vez de forzar."""
    # 'fundo' (FOUNDED/foundation) y 'vive en' (LIVES_IN/residence): empate lexico.
    sel = PS.select("Character", "Location",
                    "Vayra fundo el Ateneo y aun vive en el Ateneo", {})
    assert sel.abstained is True
    assert sel.predicate in {"FOUNDED", "LIVES_IN"}


def test_commit_when_clear_lexical_evidence():
    """Con evidencia lexica clara y sin rival lexico de otra familia -> COMPROMETIDO
    (no se marca revision)."""
    sel = PS.select("Character", "Object", "Draven posee la espada Filo de Luna", {})
    assert sel.predicate == "OWNS"
    assert sel.abstained is False
    assert sel.fallback is False


def test_safe_fallback_to_related_to_when_no_support():
    """Sin lexico, sin prior y sin cue -> fallback SEGURO a RELATED_TO."""
    sel = PS.select("Concept", "Concept", "algo sin ninguna pista relacional", {})
    assert sel.predicate == PS.GENERIC_PREDICATE == "RELATED_TO"
    assert sel.fallback is True
    assert sel.abstained is False


def test_cue_signal_supports_family():
    """Un cue booleano de signals.py (possession) aporta soporte a la familia,
    incluso sin expresion lexica de la ontologia en la ventana."""
    sel = PS.select("Character", "Object", "Draven y el Filo de Luna",
                    {"possession": True})
    assert sel.predicate == "OWNS"


# ---- cada FAMILIA representada (cue -> predicado correcto, tipos validos) ----
_FAMILY_CASES = [
    ("kinship", "Character", "Character", "Torin es hermano de Aldric", "SIBLING_OF"),
    ("alliance", "Faction", "Faction", "sello una alianza con el Clan", "ALLIED_WITH"),
    # B2-purga: "enemigo declarado" era calcada del corpus (src-13); se usa el
    # marcador general "enemigo de". El predicado esperado NO cambia.
    ("enmity", "Faction", "Faction", "es enemigo de la Horda del Norte", "ENEMY_OF"),
    ("membership", "Character", "Faction", "es miembro de la Orden", "MEMBER_OF"),
    ("leadership", "Character", "Concept", "Ella lideraba la vanguardia", "LEADS"),
    ("location", "Faction", "Location", "la Orden se encuentra en Puerto", "LOCATED_IN"),
    ("residence", "Character", "Location", "Akio reside en el Valle", "LIVES_IN"),
    ("possession", "Character", "Object", "porta la espada Filo de Luna", "OWNS"),
    ("creation", "Faction", "Object", "fue forjada por los Herreros", "CREATED"),
    ("foundation", "Character", "Faction", "Aldric funda el Reino de Valmyr", "FOUNDED"),
    ("participation", "Character", "Event", "participo en el Torneo", "PARTICIPATED_IN"),
    ("mentorship", "Character", "Character", "es maestro de Sela", "MENTOR_OF"),
    # B2-purga: "domina" era calcada del corpus (src-09) y semanticamente dudosa;
    # se usa el marcador general "sabe de". El predicado esperado NO cambia.
    ("cognition", "Concept", "Concept", "sabe de la Escritura Astral", "KNOWS"),
    ("trust", "Character", "Faction", "nunca confio en la Horda", "TRUSTS"),
    ("succession", "Character", "Character", "Ysolde sucede a Aldric", "SUCCEEDED"),
    ("causality", "Event", "Event", "la sequia provoco la Hambruna", "CAUSED"),
    ("guardianship", "Faction", "Object", "custodia la Corona de Espinas", "GUARDS"),
    ("identity", "Character", "Character", "conocida como la Reina", "ALIAS_OF"),
]


@pytest.mark.parametrize("family,s_type,o_type,window,expected", _FAMILY_CASES)
def test_each_family_selects_expected_predicate(family, s_type, o_type, window, expected):
    sel = PS.select(s_type, o_type, window, {})
    assert sel.predicate == expected, f"familia {family}: {sel.predicate} != {expected}"
    assert O.ONTOLOGY[expected].family == family


def test_confusable_lives_in_vs_located_in():
    """LIVES_IN vs LOCATED_IN (la divergencia central): el cue de residencia decide."""
    residencia = PS.select("Character", "Location", "Akio reside en el Valle", {})
    assert residencia.predicate == "LIVES_IN"
    assert residencia.abstained is False
    # Sin cue de residencia, un Personaje en un Lugar cae en el prior LOCATED_IN.
    generico = PS.select("Character", "Location", "Sela llego a Puerto Niebla", {})
    assert generico.predicate == "LOCATED_IN"


def test_selection_is_deterministic():
    a = PS.select("Character", "Faction", "es miembro de la Orden", {})
    b = PS.select("Character", "Faction", "es miembro de la Orden", {})
    assert a == b


def test_type_filter_accepts_either_orientation():
    """El par textual puede venir invertido: el filtro acepta ambas orientaciones."""
    # OWNS es Actor->Cosa; con el par invertido (Cosa, Actor) sigue siendo candidato.
    directo = PS.select("Character", "Object", "posee la espada", {})
    invertido = PS.select("Object", "Character", "posee la espada", {})
    assert directo.predicate == "OWNS"
    assert invertido.predicate == "OWNS"


# ===========================================================================
# PARTE B — MEDICION A/B con el metro corregido
# ===========================================================================
def _report_bits(run, corpus):
    gt = [r for r in corpus.relations if r["source_id"] in set(run.source_ids)]
    match = match_predictions(run.predictions, gt)
    return {
        "predicate": BM.structural_quality(match)["predicate_correct"]["rate"],
        "evidence": BM.structural_quality(match)["evidence_correct"]["rate"],
        "pair_f1": BM.global_metrics(match)["f1"],
        "direction": BM.structural_quality(match)["direction_correct"]["rate"],
        "strict_f1": BM.strict_metrics(match)["f1"],
    }


def test_v2_meets_experimental_predicate_gate(corpus):
    """GATE experimental B2: predicate_structural >= 0.50 con el metro corregido."""
    v2 = run_benchmark(corpus, mode="baseline1", predicate_selector="v2")
    bits = _report_bits(v2, corpus)
    assert bits["predicate"] >= 0.50, (
        f"predicate_structural real = {bits['predicate']:.4f} < 0.50 (gate B2)")


def test_v2_does_not_lower_pair_f1_or_evidence(corpus):
    """v2 NO baja pair_F1 ni evidence_correct respecto a la base (v1)."""
    v1 = run_benchmark(corpus, mode="baseline1", predicate_selector="v1")
    v2 = run_benchmark(corpus, mode="baseline1", predicate_selector="v2")
    b1, b2 = _report_bits(v1, corpus), _report_bits(v2, corpus)
    assert b2["pair_f1"] == b1["pair_f1"], "pair_F1 (existencia) NO debe cambiar"
    assert b2["evidence"] >= b1["evidence"], "evidence_correct NO debe bajar"
    assert b2["predicate"] > b1["predicate"], "v2 debe MEJORAR el predicado"


def test_v2_is_offline_and_deterministic(corpus):
    """v2 sigue offline (sin proveedores) y determinista."""
    a = run_benchmark(corpus, mode="baseline1", predicate_selector="v2")
    b = run_benchmark(corpus, mode="baseline1", predicate_selector="v2")
    assert a.result_hashes() == b.result_hashes()
    assert a.predictions == b.predictions
    assert (a.provider_status or {}).get("external_ai", "NOT_EXECUTED") in (
        "NOT_EXECUTED", None)


def test_v2_marks_abstentions_in_validation_flags(corpus):
    """En un run real v2, alguna prediccion en abstencion lleva `review_predicate`."""
    v2 = run_benchmark(corpus, mode="baseline1", predicate_selector="v2")
    abstained = [p for p in v2.predictions
                 if PS.REVIEW_PREDICATE_FLAG in (p.get("validation_flags") or [])]
    # La abstencion es un mecanismo VIVO: hay al menos un caso marcado para revision.
    assert len(abstained) >= 1
