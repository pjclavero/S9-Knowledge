# -*- coding: utf-8 -*-
"""Tests unitarios y adversariales del bloque B1 (puerta 6): operador de
DISCURSO REPORTADO POR TERCERO, "mientras no" como condicional, y la
extension de `SCOPE_VERBS` con verbos factivos/de reconocimiento
(admitir/reconocer/verificar/aceptar).

No repite lo que ya cubre `test_gate6_harness.py`/`test_gate6_harness_adversarial.py`
(integridad de corpus, no-solapamiento, determinismo): esto prueba la
POLITICA nueva directamente, con frases propias (nunca literales de ningun
corpus), y las guardas de precision que el encargo exige: ninguna frase
factiva legitima debe caer a no-factiva por el operador nuevo.
"""
from __future__ import annotations

from knowledge_v3.extraction.cues import (
    REPORT_VERBS,
    analyze_raw_text,
)


# --------------------------------------------------------------------------
# 1. El operador de reporte clasifica RUMOR (no ASSERTED/NEGATED_FACT) para
#    discurso simple atribuido a un tercero, con vocabulario y entidades
#    propios de este fichero.
# --------------------------------------------------------------------------
def test_dijo_que_no_se_lee_como_hecho_del_mundo():
    verdict = analyze_raw_text(
        "El capataz dijo que Renata Solf dirige el taller de cordeleria."
    )
    assert verdict.factivity.factivity_class.value == "RUMOR"
    assert verdict.factivity.factivity_class.value not in ("ASSERTED_FACT", "NEGATED_FACT")


def test_afirma_que_no_se_lee_como_hecho_del_mundo():
    verdict = analyze_raw_text(
        "Un vecino afirma que Toms Bregar administra el molino viejo."
    )
    assert verdict.factivity.factivity_class.value == "RUMOR"


def test_informo_que_cubre_reporte_de_una_negacion():
    """REPORT_OF_NEGATION generico: el verbo de reporte gana a la negacion
    interna de la clausula reportada -- no se lee como NEGATED_FACT."""
    verdict = analyze_raw_text(
        "El notario informo que Delia Vance no administra el molino viejo."
    )
    assert verdict.factivity.factivity_class.value == "RUMOR"
    assert verdict.factivity.factivity_class.value != "NEGATED_FACT"


def test_reporte_anidado_de_dos_niveles_no_se_lee_como_hecho():
    """NESTED_REPORT generico: dos verbos de reporte encadenados."""
    verdict = analyze_raw_text(
        "Renata Solf dijo que Toms Bregar asegura que el taller vende cordeleria "
        "al mercado del sur."
    )
    assert verdict.factivity.factivity_class.value not in ("ASSERTED_FACT", "NEGATED_FACT")


# --------------------------------------------------------------------------
# 2. Guarda de precision: ningun verbo FACTIVO (confirmar/admitir/reconocer/
#    verificar/aceptar) entra en REPORT_VERBS. Si una futura edicion los
#    anade por error, esta guarda lo caza antes de que degrade una frase
#    factiva legitima a RUMOR.
# --------------------------------------------------------------------------
def test_verbos_factivos_no_estan_en_report_verbs():
    factivos = {
        "confirmo", "confirma", "admite", "admitio", "reconoce", "reconocio",
        "verifica", "verifico", "acepta", "acepto",
    }
    assert not (factivos & set(REPORT_VERBS)), (
        "un verbo factivo/de reconocimiento se colo en REPORT_VERBS: eso "
        "degradaria a RUMOR frases que SI deben leerse como hecho "
        "(confirmar/admitir/reconocer/verificar/aceptar presuponen que lo "
        "dicho es cierto, no son un reporte no verificado)"
    )


def test_referir_queda_fuera_de_report_verbs_a_proposito():
    """`fact:hecho-afirmado:08` del corpus dev ('El escribano refirio que...
    y sus libros lo confirman', gold WRITE_POSITIVE) es un reporte con
    corroboracion en la misma frase que SI se escribe como hecho. Anadir
    'referir' aqui convertiria ese caso en una violacion nueva."""
    assert "refirio" not in REPORT_VERBS
    assert "refiere" not in REPORT_VERBS


def test_frase_factiva_simple_no_se_degrada_por_el_operador_nuevo():
    """Guarda de regresion directa: una afirmacion simple, sin ningun verbo
    de reporte, sigue leyendose como ASSERTED_FACT."""
    verdict = analyze_raw_text("Renata Solf dirige el taller de cordeleria.")
    assert verdict.factivity.factivity_class.value == "ASSERTED_FACT"


def test_confirmar_positivo_sin_negacion_no_se_ve_afectado_por_b1():
    """`confirmar` no esta en REPORT_VERBS: una frase con 'confirmo que' sin
    negacion previa sigue leyendose como hecho del mundo (comportamiento
    heredado, sin cambios de B1)."""
    verdict = analyze_raw_text(
        "El veedor confirmo que Renata Solf dirige el taller de cordeleria."
    )
    assert verdict.factivity.factivity_class.value == "ASSERTED_FACT"


# --------------------------------------------------------------------------
# 3. "mientras no" como condicional, sin convertir "mientras" temporal.
# --------------------------------------------------------------------------
def test_mientras_no_con_sujeto_interpuesto_es_condicional():
    verdict = analyze_raw_text(
        "Mientras Renata Solf no venda el taller, el gremio respetara el contrato."
    )
    assert verdict.factivity.factivity_class.value not in ("ASSERTED_FACT", "NEGATED_FACT")


def test_mientras_temporal_sin_no_no_se_convierte_en_condicional():
    """'mientras' + indicativo, sin 'no' cercano: sigue siendo temporal, no
    condicional. Es la guarda explicita que pide el encargo: no convertir
    usos temporales en condicionales."""
    verdict = analyze_raw_text(
        "Mientras cenaban en el puerto, Renata Solf firmo el contrato del taller."
    )
    assert verdict.factivity.factivity_class.value == "ASSERTED_FACT"


def test_mientras_no_lejos_del_foco_no_dispara_fuera_de_ventana():
    """Sujeto largo entre 'mientras' y 'no' (mas de 4 tokens): el patron no
    dispara -- se prefiere no reconocer el condicional antes que reconocerlo
    a distancia arbitraria (ventana declarada y acotada, no heuristica
    abierta)."""
    verdict = analyze_raw_text(
        "Mientras la vieja guardia del muelle sur y sus aliados historicos no "
        "vendan el taller, el gremio respetara el contrato."
    )
    # No se exige un valor concreto (depende de otras marcas de la frase);
    # solo que el patron NO sea el que dispare la lectura no-factiva, para
    # que quede documentado que la ventana es finita a proposito.
    assert "mientras <sujeto> no" not in verdict.cues


# --------------------------------------------------------------------------
# 4. Extension de SCOPE_VERBS (admitir/reconocer/verificar/aceptar):
#    "no <verbo> que" es alcance ambiguo, igual que ya lo era con
#    "confirmar".
# --------------------------------------------------------------------------
def test_no_admitio_que_es_alcance_ambiguo():
    verdict = analyze_raw_text(
        "El intendente no admitio que Renata Solf dirigiera el taller."
    )
    assert verdict.factivity.factivity_class.value == "UNKNOWN"
    assert verdict.negation_kind == "SCOPE_AMBIGUOUS"


def test_no_reconocio_que_es_alcance_ambiguo():
    verdict = analyze_raw_text(
        "El consejo no reconocio que Toms Bregar administrara el molino."
    )
    assert verdict.factivity.factivity_class.value == "UNKNOWN"


def test_no_verifico_que_es_alcance_ambiguo():
    verdict = analyze_raw_text(
        "El auditor no verifico que el taller pagara el arancel del gremio."
    )
    assert verdict.factivity.factivity_class.value == "UNKNOWN"


def test_no_acepto_que_es_alcance_ambiguo():
    verdict = analyze_raw_text(
        "El gremio no acepto que Renata Solf vendiera el taller sin permiso."
    )
    assert verdict.factivity.factivity_class.value == "UNKNOWN"
