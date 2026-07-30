# -*- coding: utf-8 -*-
"""Puerta 6: el corpus de NO-FACTIVIDAD tiene que ser gold antes de medir nada.

El corpus (`benchmarks/datasets/factivity/cases.json`, split `dev-synthetic`)
existe para medir una sola pregunta: **¿el motor distingue lo que el texto
AFIRMA del mundo de lo que solo menciona?** Una pregunta, un deseo, una
hipotesis o una ficcion dentro de la ficcion nombran una relacion sin afirmarla;
escribirla al grafo es inventarse un hecho.

Estos tests no miden al motor: miden al CORPUS. Si el corpus se contradice a si
mismo —un caso marcado `ABSTAIN` que dice llevar un hecho del mundo—, cualquier
metrica calculada sobre el es ruido con dos decimales. Es el mismo criterio que
el corpus gold del motor aplica a sus propios documentos.

El corpus es `dev-synthetic` y lo declara en su procedencia: NO es evidencia de
generalizacion, y ningun resultado medido sobre el debe presentarse como tal.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "knowledge_v3/benchmarks/datasets/factivity/cases.json"
)

PROVENANCE = "dev-synthetic/opus-2026-07-30"

#: Minimos por familia del encargo. El corpus puede superarlos, nunca bajarlos.
FAMILY_MINIMUMS = {
    "HECHO_AFIRMADO": 10,
    "NEGACION_FACTUAL": 10,
    "PREGUNTA": 10,
    "CONDICIONAL": 10,
    "CONTRAFACTUAL": 10,
    "HIPOTESIS": 10,
    "DESEO": 8,
    "ORDEN": 8,
    "FALSEDAD_ATRIBUIDA": 8,
    "FICCION_EN_FICCION": 8,
    "RUMOR": 4,
    "ALCANCE_COMPLEJO": 4,
}

EXPECTED_VALUES = {"WRITE_POSITIVE", "WRITE_NEGATIVE", "ABSTAIN", "DIAGNOSTIC"}

CASE_KEYS = {
    "case_id",
    "text",
    "family",
    "world_fact",
    "negative",
    "expected",
    "note",
    "provenance",
}


@pytest.fixture(scope="module")
def corpus() -> dict:
    assert CORPUS_PATH.exists(), f"no existe el corpus de factividad en {CORPUS_PATH}"
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cases(corpus) -> list[dict]:
    return corpus["cases"]


# ==========================================================================
# Forma del corpus
# ==========================================================================
def test_el_corpus_se_declara_dev_synthetic_con_su_procedencia(corpus):
    """Un corpus sintetico que no se declara como tal acaba citandose como real."""
    assert corpus["split"] == "dev-synthetic"
    assert corpus["provenance"] == PROVENANCE
    assert corpus["benchmark_file"] == "factivity/cases"
    assert corpus["dataset_version"]
    assert corpus["description"].strip()


def test_cada_caso_tiene_exactamente_los_campos_del_contrato(cases):
    for case in cases:
        assert set(case) == CASE_KEYS, case.get("case_id")


def test_cada_caso_declara_su_procedencia(cases):
    """Procedencia POR CASO, no solo en la cabecera: los casos se copian sueltos."""
    for case in cases:
        assert case["provenance"] == PROVENANCE, case["case_id"]


def test_los_identificadores_y_los_textos_son_unicos(cases):
    duplicated_ids = [i for i, n in Counter(c["case_id"] for c in cases).items() if n > 1]
    duplicated_texts = [t for t, n in Counter(c["text"] for c in cases).items() if n > 1]
    assert duplicated_ids == [], duplicated_ids
    assert duplicated_texts == [], duplicated_texts


def test_los_valores_enumerados_son_los_del_contrato(cases):
    for case in cases:
        assert case["family"] in FAMILY_MINIMUMS, case["case_id"]
        assert case["expected"] in EXPECTED_VALUES, case["case_id"]
        assert isinstance(case["world_fact"], bool), case["case_id"]
        assert isinstance(case["negative"], bool), case["case_id"]


# ==========================================================================
# Cobertura: las familias y sus cuotas
# ==========================================================================
def test_todas_las_familias_llegan_a_su_minimo(cases):
    counts = Counter(c["family"] for c in cases)
    short = {
        family: (counts.get(family, 0), minimum)
        for family, minimum in FAMILY_MINIMUMS.items()
        if counts.get(family, 0) < minimum
    }
    assert short == {}, f"familias por debajo del minimo (real, minimo): {short}"


def test_la_cabecera_declara_el_recuento_real(corpus, cases):
    """Un recuento declarado que no cuadra con el contenido es peor que ninguno."""
    assert corpus["families"] == dict(Counter(c["family"] for c in cases))


def test_el_corpus_tiene_al_menos_cien_casos(cases):
    assert len(cases) >= 100, len(cases)


# ==========================================================================
# Coherencia interna: el corpus no puede contradecirse
# ==========================================================================
def test_la_anotacion_de_cada_caso_es_internamente_coherente(cases):
    """`expected` fija `world_fact` y `negative`. Sin esto no hay gold.

    `DIAGNOSTIC` queda fuera a proposito: es justamente la clase donde el
    corpus admite que el par (hecho, alcance) no es limpio, y por eso se le
    exige una nota que lo explique.
    """
    problems = []
    for case in cases:
        expected, fact, negative = case["expected"], case["world_fact"], case["negative"]
        if expected == "WRITE_POSITIVE" and not (fact and not negative):
            problems.append((case["case_id"], expected, fact, negative))
        if expected == "WRITE_NEGATIVE" and not (fact and negative):
            problems.append((case["case_id"], expected, fact, negative))
        if expected == "ABSTAIN" and (fact or negative):
            problems.append((case["case_id"], expected, fact, negative))
    assert problems == [], problems


def test_cada_caso_justifica_su_resultado_esperado(cases):
    for case in cases:
        assert case["note"].strip(), case["case_id"]


def test_los_casos_diagnostico_explican_por_que_lo_son(cases):
    diagnostics = [c for c in cases if c["expected"] == "DIAGNOSTIC"]
    assert diagnostics, "sin casos DIAGNOSTIC el corpus no mide el alcance problematico"
    for case in diagnostics:
        assert len(case["note"].split()) >= 5, case["case_id"]


# ==========================================================================
# Las familias significan lo que dicen
# ==========================================================================
def test_las_familias_no_factivas_nunca_escriben_un_hecho(cases):
    """Preguntas, deseos, ordenes, hipotesis, contrafactuales, rumores, ficcion.

    Ninguna afirma un hecho del mundo. Si una de estas familias trajese un
    `WRITE_*`, el corpus estaria ensenando al motor exactamente lo contrario de
    lo que pretende medir.
    """
    non_factive = {
        "PREGUNTA",
        "CONDICIONAL",
        "CONTRAFACTUAL",
        "HIPOTESIS",
        "DESEO",
        "ORDEN",
        "FICCION_EN_FICCION",
        "RUMOR",
    }
    offenders = [
        (c["case_id"], c["family"], c["expected"])
        for c in cases
        if c["family"] in non_factive and c["expected"] != "ABSTAIN"
    ]
    assert offenders == [], offenders


def test_los_hechos_afirmados_y_las_negaciones_son_los_controles_positivos(cases):
    """Sin controles que SI se escriben, un motor que abstiene siempre acertaria.

    Es el fallo clasico de un corpus de abstencion: mide solo lo que no hay que
    escribir y premia al sistema que no escribe nada.
    """
    positives = [c for c in cases if c["family"] == "HECHO_AFIRMADO"]
    negatives = [c for c in cases if c["family"] == "NEGACION_FACTUAL"]
    assert all(c["expected"] == "WRITE_POSITIVE" for c in positives)
    assert all(c["expected"] == "WRITE_NEGATIVE" for c in negatives)


def test_el_corpus_no_es_mayoritariamente_abstencion(cases):
    """Al menos un 15% de casos escribibles: si no, la metrica es degenerada."""
    writable = [c for c in cases if c["expected"].startswith("WRITE_")]
    assert len(writable) / len(cases) >= 0.15, len(writable) / len(cases)


# ==========================================================================
# Calidad del texto: variedad real, no plantillas
# ==========================================================================
def test_los_textos_estan_en_espanol_y_tienen_cuerpo(cases):
    for case in cases:
        words = case["text"].split()
        assert 5 <= len(words) <= 60, (case["case_id"], len(words))


def test_los_textos_de_una_familia_no_son_la_misma_plantilla(cases):
    """Heuristica anti-plantilla: los primeros tres tokens de cada caso.

    Diez preguntas que empiecen igual y solo cambien el nombre propio no miden
    la comprension de la no-factividad: miden un unico caso repetido diez veces.
    Se exige que al menos la mitad de los arranques de cada familia sean
    distintos.
    """
    by_family: dict[str, list[str]] = {}
    for case in cases:
        prefix = " ".join(case["text"].lower().split()[:3])
        by_family.setdefault(case["family"], []).append(prefix)

    poor = {
        family: (len(set(prefixes)), len(prefixes))
        for family, prefixes in by_family.items()
        if len(set(prefixes)) * 2 < len(prefixes)
    }
    assert poor == {}, f"familias con arranques repetidos (únicos, total): {poor}"


def test_hay_variedad_sintactica_declarada_en_el_conjunto(cases):
    """Marcadores de subordinacion, pasiva y discurso indirecto.

    No prueba que cada frase sea compleja —seria absurdo exigirlo a una orden—,
    sino que el conjunto no es una lista de oraciones simples calcadas.

    Se exige un UMBRAL sobre una lista amplia y no la presencia de cada
    marcador: pedir uno concreto convierte el test en una lotería sobre el
    vocabulario del redactor, no en una medida de variedad.
    """
    texts = " ".join(c["text"].lower() for c in cases)
    markers = (
        " que ", " si ", " cuando ", " se ", " habría", " fuera ", " aunque ",
        " porque ", " cuyo ", " cuya ", " quien ", " donde ", " sería ",
        " hubiera ", " pese a ", " según ", " mientras ", " tras ",
    )
    present = [m for m in markers if m in texts]
    assert len(present) >= 10, f"variedad sintáctica pobre; solo aparecen: {present}"

    # Y que la subordinacion no esté concentrada en cuatro casos largos.
    with_subordination = [
        c for c in cases if any(m in f" {c['text'].lower()} " for m in markers)
    ]
    assert len(with_subordination) / len(cases) >= 0.5, len(with_subordination)
