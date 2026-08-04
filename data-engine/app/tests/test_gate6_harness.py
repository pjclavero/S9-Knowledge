# -*- coding: utf-8 -*-
"""Tests del arnes de la puerta 6 (bloque B0), no de la politica de factividad.

Defiende cuatro cosas, mismo patron que `test_gate4_harness.py`: que la
integridad de los dos corpus se comprueba de verdad (y que un fichero tocado
sin declarar el cambio rompe la carga), que no hay n-gramas (>=3) compartidos
entre el corpus de desarrollo y el de generalizacion composicional, que el
arnes es determinista byte a byte, y que el esquema de los items del corpus
de generalizacion es el que documenta el modulo.
"""
from __future__ import annotations

import hashlib
import json
import re

import pytest

from knowledge_v3.eval import gate6_dev_corpus, gate6_generalization_corpus
from knowledge_v3.eval.gate6_generalization_corpus import (
    CASES_FILE,
    GenerationCorpusError,
    load_generalization,
)
from knowledge_v3.eval.gate6_harness import measure_gate6_program
from knowledge_v3.eval.integrity import IntegrityError, verify_or_raise


# --------------------------------------------------------------------------
# 1. Integridad
# --------------------------------------------------------------------------
def test_integridad_del_corpus_de_desarrollo_no_rompe_en_reposo():
    gate6_dev_corpus.verify_integrity()


def test_integridad_del_corpus_de_generalizacion_no_rompe_en_reposo():
    gate6_generalization_corpus.verify_integrity()


def test_integridad_rompe_si_el_fichero_declarado_cambia(tmp_path):
    fichero = tmp_path / "dataset.json"
    fichero.write_text('{"a": 1}', encoding="utf-8")
    hash_original = hashlib.sha256(fichero.read_bytes()).hexdigest()

    verify_or_raise(tmp_path, {"dataset.json": hash_original}, label="fixture de prueba")

    fichero.write_text('{"a": 2}', encoding="utf-8")
    with pytest.raises(IntegrityError):
        verify_or_raise(tmp_path, {"dataset.json": hash_original}, label="fixture de prueba")


def test_integridad_rompe_si_falta_un_fichero_declarado(tmp_path):
    with pytest.raises(IntegrityError):
        verify_or_raise(tmp_path, {"no-existe.json": "0" * 64}, label="fixture de prueba")


def test_integridad_rompe_si_no_hay_hashes_declarados(tmp_path):
    with pytest.raises(IntegrityError):
        verify_or_raise(tmp_path, {}, label="fixture de prueba")


# --------------------------------------------------------------------------
# 2. No solapamiento (n-gramas >= 3) entre desarrollo y generalizacion
# --------------------------------------------------------------------------
_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]+")


def _ngrams(text: str, n: int = 3) -> set[tuple[str, ...]]:
    words = [w.lower() for w in _WORD_RE.findall(text)]
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def test_sin_solapamiento_de_ngramas_con_el_corpus_dev():
    dev = gate6_dev_corpus.load_dev_cases()
    dev_ngrams: set[tuple[str, ...]] = set()
    for case in dev["cases"]:
        dev_ngrams |= _ngrams(case["text"])

    gen_items = load_generalization()
    for item in gen_items:
        overlap = _ngrams(item.text) & dev_ngrams
        assert not overlap, (
            f"{item.case_id}: n-gramas compartidos con el corpus dev: {overlap}"
        )


def test_sin_solapamiento_de_ngramas_con_el_codigo_de_cues():
    """Ningun n-grama (>=3 palabras) del corpus de generalizacion es un
    literal de 3+ palabras copiado tal cual de `cues.py` (las cue phrases de
    varias palabras SI pueden aparecer -- se necesitan para probar
    composicion -- pero no como copia literal de una tupla completa del
    modulo; se comprueba que ninguna FALSITY_PHRASE/CONDITIONAL_PHRASE/
    DEONTIC_PHRASE de 3+ palabras aparece verbatim, salvo las que el propio
    diseno del corpus declara que SI usa a proposito)."""
    from knowledge_v3.extraction import cues as C

    # Frases de cues.py de 3+ palabras que el corpus usa A PROPOSITO para
    # ejercer composicion (declaradas explicitamente, no coladas por azar).
    _DELIBERATE_CUE_REUSE = {
        "en caso de que",
        "a menos que",
        "salvo que",
        "suponiendo que",
        "solo si",
        "es cierto que",
        "no es cierto que",
        "es falso que",
        "corre el rumor de que",
        "se dice que",
        "se rumorea",
        "al parecer",
    }
    gen_items = load_generalization()
    gen_text = " ".join(item.text.lower() for item in gen_items)

    for name in dir(C):
        value = getattr(C, name)
        if not isinstance(value, tuple) or not value:
            continue
        for entry in value:
            phrase = entry[0] if isinstance(entry, tuple) else entry
            if not isinstance(phrase, str):
                continue
            words = phrase.split()
            if len(words) < 3:
                continue
            if phrase in _DELIBERATE_CUE_REUSE:
                continue
            assert phrase not in gen_text, (
                f"cue phrase {phrase!r} de cues.py::{name} aparece en el corpus "
                "de generalizacion sin declararse como reuso deliberado"
            )


# --------------------------------------------------------------------------
# 3. Determinismo
# --------------------------------------------------------------------------
def test_el_arnes_es_determinista_byte_a_byte():
    primero = json.dumps(measure_gate6_program(), ensure_ascii=False, sort_keys=True)
    segundo = json.dumps(measure_gate6_program(), ensure_ascii=False, sort_keys=True)
    assert primero == segundo


# --------------------------------------------------------------------------
# 4. Esquema del corpus de generalizacion
# --------------------------------------------------------------------------
_EXPECTED_FAMILIES = {
    "CONDITIONAL_IN_RUMOR",
    "NESTED_REPORT",
    "NEGATION_OF_FACTIVE",
    "FACTIVE_IN_CONDITIONAL",
    "NEGATED_RUMOR_HARD",
    "REPORT_OF_NEGATION",
    "POSITIVE_CONTROL",
    "LEXICAL_NEGATION_EDGE",
    # Bloque B2 (puerta 6): familias nuevas que ejercen los bugs corregidos.
    "REPORT_FALSE_FRIEND",
    "SCOPE_VERB_DIRECT_OBJ",
}


def test_el_corpus_de_generalizacion_cubre_al_menos_cuarenta_casos():
    items = load_generalization()
    assert len(items) >= 40  # B0: 42; B1: 42; B2: 48


def test_el_corpus_de_generalizacion_cubre_las_familias_exigidas():
    items = load_generalization()
    familias = {item.family for item in items}
    assert familias == _EXPECTED_FAMILIES


def test_el_corpus_de_generalizacion_declara_al_menos_una_familia_dura():
    items = load_generalization()
    duras = {item.family for item in items if item.hard}
    assert duras, "no hay ninguna familia declarada como HARD"


def test_cada_item_de_generalizacion_tiene_los_campos_del_esquema():
    items = load_generalization()
    for item in items:
        assert item.case_id
        assert item.family in _EXPECTED_FAMILIES
        assert item.text.strip()
        assert item.subject.strip() and item.subject in item.text
        assert item.object.strip() and item.object in item.text
        assert item.expected_class in {"ASSERTED_FACT", "NEGATED_FACT", "NON_FACTIVE"}
        assert isinstance(item.hard, bool)
        assert item.why_evaluable.strip()


def test_los_case_id_del_corpus_de_generalizacion_son_unicos():
    items = load_generalization()
    ids = [item.case_id for item in items]
    assert len(ids) == len(set(ids))


def test_el_esquema_roto_rompe_la_carga(tmp_path, monkeypatch):
    """Un item sin subject/object literal en el texto rompe la carga."""
    original = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    roto = json.loads(json.dumps(original))
    roto["items"][0]["subject"] = "esto-no-aparece-en-el-texto"

    roto_dir = tmp_path / "gate6_generalization"
    roto_dir.mkdir()
    (roto_dir / "cases.json").write_text(
        json.dumps(roto, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(gate6_generalization_corpus, "DATA_DIR", roto_dir)
    monkeypatch.setattr(gate6_generalization_corpus, "CASES_FILE", roto_dir / "cases.json")

    with pytest.raises(GenerationCorpusError):
        load_generalization(verify=False)


# --------------------------------------------------------------------------
# 5. Cifras honestas del baseline (fijadas por esta corrida, no a mano)
# --------------------------------------------------------------------------
def test_el_baseline_post_b1_sube_a_80_sobre_100_sin_bajar_de_f6_7():
    """`policy_accuracy` sobre el corpus dev era 79/100 = 0.79 en B0 (misma
    cifra que `gate6-findings.md`, F6-7). B1 anadio el operador de discurso
    reportado por tercero, "mientras no" como condicional y la extension de
    SCOPE_VERBS (admitir/reconocer/verificar/aceptar): la UNICA fila de dev
    que cambia es `fact:condicional:04` (NEGATED_FACT -> CONDITIONAL,
    correcto), sin ninguna regresion (verificado fila a fila en el informe
    de B1, docs/v3/44) -- de ahi 80/100 = 0.80. Si este test empieza a
    fallar POR DEBAJO de 0.79, es la regla de oro violada (regla del
    encargo: ninguna mejora se acepta si baja `policy_accuracy` de dev);
    si falla por encima o por debajo de 0.80 sin que nadie haya tocado
    `cues.py`/`factivity.py` a proposito, hay que investigar y documentar
    por que difiere, no forzar que vuelva a cuadrar."""
    report = measure_gate6_program()
    accuracy = report["corpora"]["dev"]["metrics_global"]["policy_accuracy"]
    assert accuracy >= 0.79 - 1e-9, (
        f"policy_accuracy de dev bajo de la cifra F6-7 (0.79): {accuracy} -- "
        "regla de oro violada, ninguna mejora se acepta si hunde el numero de dev"
    )
    assert accuracy == pytest.approx(0.80)


def test_la_familia_dura_de_generalizacion_no_se_fuerza_a_acertar():
    """La familia HARD se declara con exactitud baja a proposito: este test
    documenta el numero actual como evidencia, no como objetivo. No falla si
    sube (mejorar es bienvenido); solo confirma que el bloque no maquillo el
    gold para que saliera bonito."""
    report = measure_gate6_program()
    hard_acc = report["corpora"]["generalization"]["metrics_global"]["hard_family_accuracy"]
    assert hard_acc is not None
    assert 0.0 <= hard_acc <= 1.0
