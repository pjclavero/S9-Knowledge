# -*- coding: utf-8 -*-
"""Tests del arnes de la puerta 4 (bloque B0), no del extractor.

Defiende cuatro cosas: que la integridad de los dos corpus se comprueba de
verdad (y que un fichero tocado sin declarar el cambio rompe la carga), que
no hay literales compartidos entre el corpus de desarrollo y el de
generalizacion, que el arnes es determinista byte a byte, y que el esquema de
los items de generalizacion es el que documenta el modulo.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from knowledge_v3.eval import dev_corpus, generalization_corpus
from knowledge_v3.eval.generalization_corpus import (
    DATA_DIR,
    GeneralizationCorpusError,
    load_generalization,
)
from knowledge_v3.eval.harness import measure_gate4_program
from knowledge_v3.eval.integrity import IntegrityError, verify_or_raise


# --------------------------------------------------------------------------
# 1. Integridad
# --------------------------------------------------------------------------
def test_integridad_del_corpus_de_desarrollo_no_rompe_en_reposo():
    dev_corpus.verify_integrity()


def test_integridad_del_corpus_de_generalizacion_no_rompe_en_reposo():
    generalization_corpus.verify_integrity()


def test_integridad_rompe_si_el_fichero_declarado_cambia(tmp_path):
    fichero = tmp_path / "dataset.json"
    fichero.write_text('{"a": 1}', encoding="utf-8")
    hash_original = hashlib.sha256(fichero.read_bytes()).hexdigest()

    # En reposo, cuadra.
    verify_or_raise(tmp_path, {"dataset.json": hash_original}, label="fixture de prueba")

    # Se edita SIN declarar el cambio: tiene que romper.
    fichero.write_text('{"a": 2}', encoding="utf-8")
    with pytest.raises(IntegrityError):
        verify_or_raise(tmp_path, {"dataset.json": hash_original}, label="fixture de prueba")


def test_integridad_rompe_si_falta_un_fichero_declarado(tmp_path):
    with pytest.raises(IntegrityError):
        verify_or_raise(
            tmp_path, {"no-existe.json": "0" * 64}, label="fixture de prueba"
        )


def test_integridad_rompe_si_no_hay_hashes_declarados(tmp_path):
    with pytest.raises(IntegrityError):
        verify_or_raise(tmp_path, {}, label="fixture de prueba")


# --------------------------------------------------------------------------
# 2. No solapamiento literal entre desarrollo y generalizacion
# --------------------------------------------------------------------------
_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]+")


def _proper_nouns(gold) -> set[str]:
    """Nombres propios (entidades del catalogo) del corpus de desarrollo."""
    return {e["name"].strip().lower() for e in gold.entities if e.get("name")}


def test_sin_solapamiento_de_nombres_propios_entre_corpus():
    dev = dev_corpus.load_dev_gold()
    dev_names = _proper_nouns(dev)
    gen_items = load_generalization()

    for item in gen_items:
        for field_name, value in (
            ("subject", item.subject),
            ("object", item.object),
        ):
            normalizado = value.strip().lower()
            # Los objetos llevan articulo ("la Escuadra de Poniente"); se
            # compara el nombre propio sin el determinante inicial.
            normalizado = re.sub(r"^(el|la|los|las)\s+", "", normalizado)
            assert normalizado not in dev_names, (
                f"{item.case_id}: {field_name} {value!r} coincide literalmente "
                "con una entidad del corpus de desarrollo"
            )


def test_ningun_nombre_propio_de_generalizacion_aparece_en_los_textos_de_desarrollo():
    dev = dev_corpus.load_dev_gold()
    dev_text = " ".join(dev.reference_text.values()).lower()
    gen_items = load_generalization()

    gen_proper_nouns = set()
    for item in gen_items:
        for value in (item.subject, item.object):
            cleaned = re.sub(r"^(el|la|los|las)\s+", "", value.strip().lower())
            if cleaned:
                gen_proper_nouns.add(cleaned)

    for nombre in gen_proper_nouns:
        assert nombre not in dev_text, (
            f"el nombre propio de generalizacion {nombre!r} aparece en el texto "
            "del corpus de desarrollo: ha dejado de ser un caso fuera de corpus"
        )


def test_ningun_nombre_propio_de_desarrollo_aparece_en_los_textos_de_generalizacion():
    dev = dev_corpus.load_dev_gold()
    dev_names = _proper_nouns(dev)
    gen_items = load_generalization()
    gen_text = " ".join(item.text for item in gen_items).lower()

    # TODO(limitacion conocida, senalada en revision CONFORME CON OBSERVACIONES):
    # el umbral `len(nombre) < 6` evita falsos positivos por coincidir con una
    # silaba de otra palabra, pero con ello NO comprueba nombres propios de
    # desarrollo mas cortos de 6 caracteres si se reutilizaran en
    # generalizacion. Pendiente: sustituir el umbral por una lista explicita
    # de palabras vacias (stopwords) en vez de un corte por longitud. El
    # chequeo directo por entidad completa
    # (`test_el_detector_de_solapamiento_atrapa_una_entidad_multi_palabra_reutilizada`
    # en la bateria adversarial) SI cubre nombres multi-palabra sin este
    # umbral, asi que la exposicion real es solo a nombres propios de UNA
    # palabra y menos de 6 letras, que no hay en el catalogo de desarrollo hoy.
    for nombre in dev_names:
        if len(nombre) < 6:
            continue
        assert nombre not in gen_text, (
            f"la entidad de desarrollo {nombre!r} aparece en el corpus de "
            "generalizacion: deja de ser un corpus fuera de literales"
        )


# --------------------------------------------------------------------------
# 3. Determinismo
# --------------------------------------------------------------------------
def test_el_arnes_es_determinista_byte_a_byte():
    primero = json.dumps(measure_gate4_program(), ensure_ascii=False, sort_keys=True)
    segundo = json.dumps(measure_gate4_program(), ensure_ascii=False, sort_keys=True)
    assert primero == segundo


# --------------------------------------------------------------------------
# 4. Esquema de los items de generalizacion
# --------------------------------------------------------------------------
_EXPECTED_FAMILIES = {
    "SIMPLE",
    "NEVER",
    "CESSATION",
    "NEGATED_CESSATION",
    "NOT_YET",
    "SCOPE_EMBEDDED",
    "QUESTION_CONDITIONAL_RUMOR",
    "POSITIVE_CONTROL",
    "DOUBLE_NEGATION",
    # Anadida en la revision CONFORME CON OBSERVACIONES: construcciones duras
    # de negacion (sin que / no es que no / ha dejado atras / no pocos) donde
    # se espera exactitud BAJA a proposito -- ver `harness._HARD_FAMILIES`.
    "HARD_SCOPE_LITOTES",
}


def test_el_corpus_de_generalizacion_cubre_al_menos_cuarenta_casos():
    items = load_generalization()
    assert len(items) >= 40


def test_el_corpus_de_generalizacion_cubre_las_familias_exigidas():
    items = load_generalization()
    familias = {item.family for item in items}
    assert _EXPECTED_FAMILIES <= familias
    # Las familias minimas exigidas por el encargo de B0.
    for obligatoria in ("SIMPLE", "CESSATION", "SCOPE_EMBEDDED", "POSITIVE_CONTROL"):
        assert obligatoria in familias


def test_cada_item_de_generalizacion_tiene_los_campos_del_esquema():
    items = load_generalization()
    for item in items:
        assert item.case_id
        assert item.family in _EXPECTED_FAMILIES
        # "archivos" se anadio con la familia HARD_SCOPE_LITOTES (revision).
        assert item.domain in {"naval", "gremios", "linajes", "archivos"}
        assert item.text.strip()
        assert 0 <= item.focus_char <= len(item.text)
        assert item.subject.strip() and item.subject in item.text
        assert item.predicate.strip()
        assert item.object.strip() and item.object in item.text
        assert isinstance(item.negated, bool)
        assert isinstance(item.review_scope, bool)
        assert isinstance(item.non_factive, bool)
        assert item.why_evaluable.strip()
        if item.family == "HARD_SCOPE_LITOTES":
            assert item.expected_asserted_fact is not None, (
                f"{item.case_id}: la familia dura exige declarar "
                "expected_asserted_fact"
            )
        else:
            assert item.expected_asserted_fact is None


def test_los_case_id_del_corpus_de_generalizacion_son_unicos():
    items = load_generalization()
    ids = [item.case_id for item in items]
    assert len(ids) == len(set(ids))


def test_el_ancla_de_foco_inexistente_rompe_la_carga(tmp_path, monkeypatch):
    """Si el ancla de una frase no existe, la carga falla alto y claro."""
    original = json.loads((DATA_DIR / "cases.json").read_text(encoding="utf-8"))
    roto = copy.deepcopy(original)
    roto["items"][0]["focus_anchor"] = "esto-no-aparece-en-el-texto"

    roto_dir = tmp_path / "generalization"
    roto_dir.mkdir()
    (roto_dir / "cases.json").write_text(
        json.dumps(roto, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(generalization_corpus, "DATA_DIR", roto_dir)
    monkeypatch.setattr(generalization_corpus, "CASES_FILE", roto_dir / "cases.json")

    with pytest.raises(GeneralizationCorpusError):
        load_generalization(verify=False)
