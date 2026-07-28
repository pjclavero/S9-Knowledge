# -*- coding: utf-8 -*-
"""Aritmetica de las metricas, con casos de resultado calculado a mano.

Si estos numeros no salen exactos, ningun otro numero del proyecto vale nada.
"""
from __future__ import annotations

import pytest

from knowledge_v3.benchmarks.metrics import (
    accuracy,
    align_clusters,
    duplicate_rate,
    error_rate,
    levenshtein,
    over_merge_rate,
    prf,
    ratio,
    repetition_score,
    set_prf,
)


# --------------------------------------------------------------------------
# P / R / F1
# --------------------------------------------------------------------------
def test_prf_calculado_a_mano():
    # 6 aciertos, 2 falsos positivos, 3 falsos negativos.
    # P = 6/8 = 0.75 ; R = 6/9 = 0.666667 ; F1 = 2*0.75*0.666667/1.416667
    r = prf(6, 2, 3)
    assert r["precision"] == 0.75
    assert r["recall"] == pytest.approx(0.666667, abs=1e-6)
    assert r["f1"] == pytest.approx(0.705882, abs=1e-6)


def test_prf_perfecto():
    assert prf(5, 0, 0) == {
        "tp": 5,
        "fp": 0,
        "fn": 0,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
    }


def test_prf_sin_aciertos_da_cero_no_none():
    r = prf(0, 3, 4)
    assert r["precision"] == 0.0 and r["recall"] == 0.0 and r["f1"] == 0.0


def test_sin_predicciones_la_precision_no_es_cero_sino_desconocida():
    r = prf(0, 0, 4)
    assert r["precision"] is None
    assert r["recall"] == 0.0
    assert r["f1"] is None


def test_sin_gold_el_recall_no_es_cero_sino_desconocido():
    r = prf(0, 3, 0)
    assert r["recall"] is None
    assert r["precision"] == 0.0
    assert r["f1"] is None


def test_denominador_cero_nunca_se_publica_como_cero():
    assert ratio(0, 0) is None
    assert accuracy(0, 0)["accuracy"] is None


def test_accuracy_calculada_a_mano():
    assert accuracy(7, 8)["accuracy"] == 0.875


def test_set_prf_sobre_conjuntos():
    gold = {"a", "b", "c"}
    pred = {"b", "c", "d", "e"}
    r = set_prf(gold, pred)
    assert (r["tp"], r["fp"], r["fn"]) == (2, 2, 1)
    assert r["precision"] == 0.5
    assert r["recall"] == pytest.approx(0.666667, abs=1e-6)


# --------------------------------------------------------------------------
# CER / WER
# --------------------------------------------------------------------------
def test_levenshtein_casos_conocidos():
    assert levenshtein("", "") == 0
    assert levenshtein("casa", "casa") == 0
    assert levenshtein("casa", "caza") == 1
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("abc", "") == 3


def test_cer_de_un_error_de_ocr_tipico():
    # 'm' leido como 'rn': una sustitucion mas una insercion sobre 8 caracteres.
    edits, ref_len = error_rate("nombrado", "nornbrado", unit="char")
    assert (edits, ref_len) == (2, 8)
    assert edits / ref_len == 0.25


def test_wer_cuenta_palabras_no_caracteres():
    edits, ref_len = error_rate("la casa del ciervo", "la caza de1 ciervo", unit="word")
    assert (edits, ref_len) == (2, 4)


def test_unidad_desconocida_se_rechaza():
    with pytest.raises(ValueError):
        error_rate("a", "b", unit="silabas")


def test_repeticion_detecta_el_bucle_y_no_el_texto_normal():
    normal = "El magistrado entrego el baston de mando en la primavera siguiente."
    assert repetition_score(normal) is False
    bucle = "la marea negra vuelve otra vez " * 5
    assert repetition_score(bucle) is True


# --------------------------------------------------------------------------
# Alineamiento de agrupaciones
# --------------------------------------------------------------------------
def test_los_ids_del_catalogo_quedan_fijados_a_si_mismos():
    gold = {"m1": "E_A", "m2": "E_A", "m3": "E_B"}
    pred = {"m1": "E_A", "m2": "E_A", "m3": "E_A"}
    mapping = align_clusters(gold, pred, pinned={"E_A", "E_B"})
    assert mapping == {"E_A": "E_A"}


def test_mutacion_sin_fijar_los_ids_un_enlace_equivocado_se_autocorrige():
    """Si los ids del catalogo no se fijasen, enlazar mal saldria gratis."""
    gold = {"m1": "E_A", "m2": "E_B"}
    pred = {"m1": "E_B", "m2": "E_A"}  # intercambiadas: dos errores

    fijado = align_clusters(gold, pred, pinned={"E_A", "E_B"})
    aciertos = sum(1 for m, g in gold.items() if fijado.get(pred[m]) == g)
    assert aciertos == 0

    libre = align_clusters(gold, pred, pinned=set())
    aciertos_libres = sum(1 for m, g in gold.items() if libre.get(pred[m]) == g)
    assert aciertos_libres == 2, (
        "esta es la trampa: sin fijar, el alineamiento renombra los clusters y "
        "convierte dos errores en dos aciertos"
    )


def test_una_entidad_nueva_se_alinea_por_solape():
    gold = {"m1": "E_A", "m2": "E_A", "m3": "E_B"}
    pred = {"m1": "prov:1", "m2": "prov:1", "m3": "prov:2"}
    mapping = align_clusters(gold, pred)
    assert mapping == {"prov:1": "E_A", "prov:2": "E_B"}


def test_el_alineamiento_es_uno_a_uno():
    gold = {"m1": "E_A", "m2": "E_B"}
    pred = {"m1": "p1", "m2": "p2"}
    mapping = align_clusters(gold, pred)
    assert len(set(mapping.values())) == len(mapping)


def test_duplicados_contados_a_mano():
    gold = {"m1": "E_A", "m2": "E_A", "m3": "E_A", "m4": "E_B"}
    pred = {"m1": "p1", "m2": "p2", "m3": "p3", "m4": "p4"}
    r = duplicate_rate(gold, pred)
    # E_A la parten en tres clusters (dos de mas), E_B en uno (ninguno de mas).
    assert r["gold_entities_covered"] == 2
    assert r["duplicate_clusters"] == 2
    assert r["duplicate_rate"] == 1.0


def test_sin_duplicados_la_tasa_es_cero():
    gold = {"m1": "E_A", "m2": "E_A"}
    pred = {"m1": "p1", "m2": "p1"}
    assert duplicate_rate(gold, pred)["duplicate_rate"] == 0.0


def test_fusion_indebida_contada_a_mano():
    gold = {"m1": "E_A", "m2": "E_B", "m3": "E_C"}
    pred = {"m1": "p1", "m2": "p1", "m3": "p2"}
    r = over_merge_rate(gold, pred)
    assert r["predicted_clusters"] == 2
    assert r["over_merged_clusters"] == 1
    assert r["over_merge_rate"] == 0.5


def test_la_metrica_de_identidad_castiga_fundirlo_todo():
    """Meter todas las menciones en un cluster no puede salir bien parado."""
    gold = {f"m{i}": f"E_{i}" for i in range(6)}
    todo_junto = {f"m{i}": "p0" for i in range(6)}
    mapping = align_clusters(gold, todo_junto)
    aciertos = sum(1 for m, g in gold.items() if mapping.get(todo_junto[m]) == g)
    assert aciertos == 1, "solo una de las seis entidades puede quedar bien"
    assert over_merge_rate(gold, todo_junto)["over_merge_rate"] == 1.0
