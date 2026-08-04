# -*- coding: utf-8 -*-
"""Capa 2 de la puerta 6: el invariante fail-closed contra el extractor REAL.

Cubre `knowledge_v3.eval.gate6_extractor_layer`, el arnes que el rework de B2
anade para no volver a concluir sobre lo que el sistema ESCRIBE a partir de una
medicion de lo que el clasificador LEE (ese fue el hallazgo P0 del revisor: las
dos capas discrepaban y solo se publicaba la primera).
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.eval.gate6_extractor_layer import (  # noqa: E402
    build_context,
    measure_extractor_layer,
    proper_name_candidates,
)
from knowledge_v3.extraction import DeterministicExtractor  # noqa: E402
from knowledge_v3.extraction.cues import analyze_raw_text  # noqa: E402


# --------------------------------------------------------------------------
# 1. Andamiaje de menciones
# --------------------------------------------------------------------------
def test_los_nombres_propios_pierden_el_determinante_inicial():
    nombres = proper_name_candidates(
        "El heraldo dijo que Elara lidera la Orden del Alba."
    )
    assert "Orden del Alba" in nombres
    assert "Elara" in nombres
    assert not any(n.lower().startswith("el ") for n in nombres)


def test_el_lexico_del_caso_permite_anclar_menciones():
    ctx = build_context("caso:01", "Elara lidera la Orden del Alba.")
    out = DeterministicExtractor().extract(ctx)
    assert out.mentions, "sin menciones ancladas la capa 2 no mediria nada"


# --------------------------------------------------------------------------
# 2. La conexion P0, medida en la capa que escribe
# --------------------------------------------------------------------------
def test_las_dos_capas_coinciden_en_el_discurso_reportado():
    """El caso exacto del hallazgo P0 del revisor, medido E2E."""
    texto = "El heraldo dijo que Elara lidera la Orden del Alba."
    assert analyze_raw_text(texto).factivity.factivity_class.value == "RUMOR"

    ctx = build_context("caso:p0", texto)
    claims = [c for c in DeterministicExtractor().extract(ctx).claims if not c.abstained]
    assert claims
    assert all(c.epistemic_status_hint == "RUMORED" for c in claims)
    assert all(c.review_required for c in claims)


# --------------------------------------------------------------------------
# 3. El arnes de la capa 2
# --------------------------------------------------------------------------
def test_la_medicion_de_la_capa_2_es_determinista_byte_a_byte():
    primero = json.dumps(measure_extractor_layer(), ensure_ascii=False, sort_keys=True)
    segundo = json.dumps(measure_extractor_layer(), ensure_ascii=False, sort_keys=True)
    assert primero == segundo


def test_la_capa_2_publica_su_cobertura_junto_a_las_violaciones():
    """Sin cobertura al lado, '0 violaciones' no es interpretable."""
    report = measure_extractor_layer()
    assert report["layer"] == "deterministic_extractor"
    for corpus in ("dev", "generalization"):
        cov = report["corpora"][corpus]["coverage"]
        assert cov["cases_total"] > 0
        assert 0 <= cov["cases_with_claims"] <= cov["cases_total"]
        assert (
            cov["gold_forbids_cases_with_claims"] <= cov["gold_forbids_cases"]
        )


def test_ninguna_violacion_de_la_capa_2_viene_del_dev_congelado():
    """El corpus dev congelado no debe empeorar por el rework: ningun caso
    suyo cuyo gold exija abstenerse llega a materializarse."""
    report = measure_extractor_layer()
    assert report["corpora"]["dev"]["violations_asserted"] == []


def test_las_violaciones_de_la_capa_2_son_un_subconjunto_diagnosticado():
    """Las unicas violaciones de capa 2 son casos que el CLASIFICADOR ya lee
    mal (estan tambien en las violaciones de capa 1): el extractor no anade
    fallos propios, solo propaga los de la politica. Si esta asercion cae,
    hay un fallo NUEVO del carril determinista y no de la politica."""
    from knowledge_v3.eval.gate6_harness import measure_gate6_program

    capa1 = {v["case_id"] for v in measure_gate6_program()["fail_closed_invariant"]["violations"]}
    capa2 = {v["case_id"] for v in measure_extractor_layer()["violations_asserted"]}
    assert capa2 <= capa1, sorted(capa2 - capa1)
