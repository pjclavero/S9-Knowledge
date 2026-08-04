# -*- coding: utf-8 -*-
"""Puerta 4, bloque B4: unitarios + adversariales del conjugador morfologico.

`morphology.conjugate_regular_ar` genera formas de verbos de reporte -AR por
PARADIGMA (tabla de desinencias), no por lista de frases copiadas de ningun
caso de corpus. Esta bateria comprueba tres cosas:

1. El paradigma regular produce las formas correctas para verbos que SI son
   regulares (unitarios).
2. El paradigma NO se aplica a verbos -AR que son irregulares (adversarial:
   demuestra que aplicarlo a "negar" o "pensar" produciria formas que no
   existen en espanol, y que por eso `REPORTING_LEMMAS_AR` los excluye).
3. `cues.SCOPE_VERBS` reconoce verbos de reporte NUEVOS (fuera del dev y del
   corpus de generalizacion, con entidades propias) que el lexico literal
   anterior a B4 no reconocia -- la prueba de que el cambio generaliza y no
   memoriza un caso.
"""
from __future__ import annotations

import pytest

from knowledge_v3.extraction.cues import SCOPE_VERBS, analyze_raw_text
from knowledge_v3.extraction.morphology import (
    NEGAR_FORMS,
    REPORTING_LEMMAS_AR,
    conjugate_regular_ar,
    reporting_verb_forms,
)


def _negated(text: str, anchor: str) -> tuple[bool, str]:
    focus_char = text.find(anchor)
    assert focus_char >= 0, f"ancla no encontrada: {anchor!r}"
    v = analyze_raw_text(text, focus_char=focus_char)
    return bool(v.negated), v.negation_kind


# ---------------------------------------------------------------------------
# 1. Unitarios del paradigma regular
# ---------------------------------------------------------------------------

def test_conjugate_regular_ar_declarar():
    p = conjugate_regular_ar("declarar")
    assert p.presente == ("declara", "declaran")
    assert p.preterito == ("declaro", "declararon")
    assert p.imperfecto == ("declaraba", "declaraban")
    assert p.participio == "declarado"
    assert "ha declarado" in p.all_forms()
    assert "habian declarado" in p.all_forms()


def test_conjugate_regular_ar_rechaza_lema_sin_terminacion_ar():
    with pytest.raises(ValueError):
        conjugate_regular_ar("declarer")


def test_conjugate_regular_ar_no_genera_duplicados():
    p = conjugate_regular_ar("afirmar")
    formas = p.all_forms()
    assert len(formas) == len(set(formas))


def test_reporting_lemmas_ar_son_todas_realmente_regulares():
    """Cada lema declarado debe conjugar SIN diptongacion ni cambio ortografico.

    Si alguien anade a `REPORTING_LEMMAS_AR` un verbo con e->ie / o->ue
    (pensar, contar...) o con cambio ortografico en 1a persona (pero aqui solo
    generamos 3a, asi que ese caso concreto no aplica), este test no lo
    atraparia por si solo: lo que SI comprueba es que ninguno de los lemas
    declarados hoy es de esa clase, con la lista de verbos de reporte
    irregulares mas comunes del espaniol como lista negra explicita.
    """
    irregulares_conocidos = {
        "pensar", "negar", "contar", "recordar", "sentar", "acertar",
        "cerrar", "comenzar", "empezar", "confesar",
    }
    assert irregulares_conocidos.isdisjoint(REPORTING_LEMMAS_AR)


# ---------------------------------------------------------------------------
# 2. Adversarial: demostrar por que "negar" NO puede ir por la tabla regular
# ---------------------------------------------------------------------------

def test_aplicar_tabla_regular_a_negar_produce_formas_inexistentes():
    """Documenta la razon de excluir "negar" de `REPORTING_LEMMAS_AR`.

    "negar" diptonga en presente (niega/niegan, no "*nega"/"*negan"). Si
    alguien lo metiera en la tabla regular por descuido, el presente saldria
    mal. Este test fija ese comportamiento como ADVERTENCIA explicita: la
    funcion no valida regularidad (no es su trabajo), asi que quien declare
    lemas nuevos tiene que comprobarlo a mano, como aqui.
    """
    p = conjugate_regular_ar("negar")
    assert p.presente == ("nega", "negan")  # forma que NO EXISTE en espaniol
    assert p.presente != ("niega", "niegan")  # la real, por eso va aparte
    assert "negar" not in REPORTING_LEMMAS_AR
    assert "niega" in NEGAR_FORMS and "niegan" in NEGAR_FORMS


def test_pensar_diptonga_y_por_eso_no_esta_en_los_lemas_declarados():
    p = conjugate_regular_ar("pensar")
    assert p.presente == ("pensa", "pensan")  # inexistente ("piensa" es la real)
    assert "pensar" not in REPORTING_LEMMAS_AR


# ---------------------------------------------------------------------------
# 3. Generalizacion: SCOPE_VERBS reconoce reporte nuevo, con entidades propias
#    que no aparecen en el corpus de desarrollo ni en el de generalizacion de
#    B0/B2. Cero literales compartidos con el codigo o con casos existentes.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "texto,ancla",
    [
        ("El heraldo no declaro que Iset Vahn presida el Consulado.", "presida"),
        ("El cronista no aseguro que Doria Kessel lidere la flota.", "lidere"),
        ("El copista no confirmo que Alden Rook custodie el archivo.", "custodie"),
        ("El vocero no afirma que Yannic Bors administre el puerto.", "administre"),
        ("El testigo no niega que Corvin Thale gobierne la aldea.", "gobierne"),
    ],
)
def test_scope_verbs_generaliza_a_verbos_de_reporte_no_vistos(texto, ancla):
    """Antes de B4 estos 5 verbos de reporte no estaban en `SCOPE_VERBS`
    (solo estaban las formas irregulares y "afirma"/"afirmaba"/"afirmo" en
    singular). El clasificador debe leer la negacion como ALCANCE DE LA
    CREENCIA (no como negacion de la relacion): "no declaro que X presida Y"
    no dice que X no preside Y, dice que nadie lo declaro.
    """
    negated, kind = _negated(texto, ancla)
    assert negated is False
    assert kind == "SCOPE_AMBIGUOUS"


def test_scope_verbs_plural_tambien_generaliza():
    """El lexico anterior a B4 solo tenia "afirma" en singular; el plural
    "afirman" no estaba. Es exactamente el hueco que un lexico escrito a
    mano, verbo-forma a verbo-forma, deja sin querer.
    """
    negated, kind = _negated(
        "Los cronistas no afirman que Sable Nyx custodie el faro.", "custodie"
    )
    assert negated is False
    assert kind == "SCOPE_AMBIGUOUS"


def test_reporting_verb_forms_estan_todas_en_scope_verbs():
    for forma in reporting_verb_forms():
        assert forma in SCOPE_VERBS
