# -*- coding: utf-8 -*-
"""Tests del bloque B2 (puerta 6): correccion del bug de homografo
('cuenta'/'relato' como sustantivo) y del bug de scope sin 'que' completivo
(SCOPE_VERBS con objeto directo).

No repite lo que ya cubren los tests de B0/B1 (integridad de corpus, no-
solapamiento, determinismo, etc.): esto prueba directamente las dos
correcciones de `cues.py` introducidas en B2, con frases propias que no
aparecen en ningun corpus ni en los tests de B1, y sin n-gramas >=3
compartidos con ellos.
"""
from __future__ import annotations

from knowledge_v3.extraction.cues import (
    COMPLEMENT_DETERMINERS,
    INDIRECT_QUESTION_CONNECTORS,
    INDIRECT_QUESTION_CONNECTOR_PAIRS,
    REPORT_VERB_NOUN_HOMOGRAPHS,
    REPORT_VERBS,
    analyze_raw_text,
)


# --------------------------------------------------------------------------
# 1. Bug 1 (homografo): formas de REPORT_VERBS que son tambien sustantivos.
#    Con determinante previo: ASSERTED_FACT (sustantivo + relativo).
#    Sin determinante previo: RUMOR (verbo de reporte + completivo).
# --------------------------------------------------------------------------
def test_REPORT_VERB_NOUN_HOMOGRAPHS_esta_declarado_y_es_subconjunto_de_report_verbs():
    """La guarda de homografo solo puede suprimir formas que son REPORT_VERBS:
    si no lo fueran, el operador nunca dispararia y la guarda seria letra muerta.
    Tambiense comprueba que el conjunto no esta vacio."""
    assert REPORT_VERB_NOUN_HOMOGRAPHS, "REPORT_VERB_NOUN_HOMOGRAPHS no puede estar vacio"
    for forma in REPORT_VERB_NOUN_HOMOGRAPHS:
        assert forma in REPORT_VERBS, (
            f"'{forma}' esta en REPORT_VERB_NOUN_HOMOGRAPHS pero no en "
            "REPORT_VERBS: la guarda nunca dispararia para esa forma"
        )


def test_cuenta_sustantivo_con_articulo_la_no_se_lee_como_rumor():
    """'La cuenta que...': 'cuenta' precedido de 'La' (determinante) es un
    sustantivo (factura/relacion de gastos), no un verbo de reporte. La guarda
    de B2 debe impedir que el operador dispare."""
    verdict = analyze_raw_text(
        "La cuenta que el tesorero Aldric Venn presento al Sindicato Vitivinicola "
        "detalla el saldo pendiente."
    )
    assert verdict.factivity.factivity_class.value == "ASSERTED_FACT", (
        "con determinante 'La' antes de 'cuenta', la guarda de homografo "
        "de B2 debe suprimir el operador de reporte"
    )
    assert "cuenta que" not in verdict.cues


def test_cuenta_sustantivo_con_posesivo_no_se_lee_como_rumor():
    """'Su cuenta que...': 'Su' es un posesivo de COMPLEMENT_DETERMINERS."""
    verdict = analyze_raw_text(
        "Su cuenta que el Sindicato Vitivinicola reclamo al tesorero Aldric Venn "
        "fue rechazada por el arbitro."
    )
    assert verdict.factivity.factivity_class.value == "ASSERTED_FACT"
    assert "cuenta que" not in verdict.cues


def test_cuenta_verbo_sin_determinante_previo_si_dispara_como_rumor():
    """'cuenta que' como verbo de reporte (sin determinante antes): el operador
    DEBE disparar. La guarda solo suprime la forma cuando va precedida de un
    determinante de COMPLEMENT_DETERMINERS."""
    verdict = analyze_raw_text(
        "Aldric Venn cuenta que el Sindicato Vitivinicola acepto el acuerdo."
    )
    assert verdict.factivity.factivity_class.value == "RUMOR", (
        "'cuenta que' como verbo (sujeto nominal previo, no determinante) "
        "debe seguir disparando como reporte de tercero"
    )
    assert "cuenta que" in verdict.cues


def test_relato_sustantivo_con_articulo_el_no_se_lee_como_rumor():
    """'El relato que...': 'relato' normaliza igual que la 3a persona de
    preterito de 'relatar' (en REPORT_VERBS), pero precedido de 'El' es un
    sustantivo (narracion). La guarda de B2 lo suprime."""
    verdict = analyze_raw_text(
        "El relato que Aldric Venn transcribio describe la fundacion del "
        "Sindicato Vitivinicola."
    )
    assert verdict.factivity.factivity_class.value == "ASSERTED_FACT"
    assert "relato que" not in verdict.cues


def test_complement_determiners_cubre_los_casos_de_uso():
    """Guarda de que la lista de determinantes usada por la guarda de homografo
    incluye al menos los determinantes y posesivos de alta frecuencia."""
    esperados = {"la", "el", "los", "las", "un", "una", "su", "sus",
                 "este", "esta", "ese", "esa"}
    assert esperados <= COMPLEMENT_DETERMINERS, (
        f"COMPLEMENT_DETERMINERS no cubre: {esperados - COMPLEMENT_DETERMINERS}"
    )


# --------------------------------------------------------------------------
# 2. Bug 2 (scope sin 'que'): SCOPE_VERBS con objeto directo.
#    Sin 'que' inmediato: NEGATED_FACT (negacion directa).
#    Con 'que' inmediato: UNKNOWN/SCOPE_AMBIGUOUS (alcance epistemico).
# --------------------------------------------------------------------------
def test_no_reconocio_objeto_directo_es_negated_fact():
    """'reconocer' + objeto directo sin 'que' completivo: negacion directa.
    La correccion de B2 exige 'que' inmediato tras el verbo de alcance."""
    verdict = analyze_raw_text(
        "El archivero Aldric Venn no reconocio el documento presentado por "
        "el Sindicato Vitivinicola."
    )
    assert verdict.factivity.factivity_class.value == "NEGATED_FACT"
    assert verdict.negation_kind != "SCOPE_AMBIGUOUS"


def test_no_acepto_objeto_directo_es_negated_fact():
    """'aceptar' + objeto directo: negacion directa, no de alcance."""
    verdict = analyze_raw_text(
        "El Sindicato Vitivinicola no acepto la oferta de Aldric Venn."
    )
    assert verdict.factivity.factivity_class.value == "NEGATED_FACT"


def test_no_verifico_objeto_directo_es_negated_fact():
    """'verificar' + objeto directo: negacion directa."""
    verdict = analyze_raw_text(
        "Aldric Venn no verifico el registro de operaciones del Sindicato Vitivinicola."
    )
    assert verdict.factivity.factivity_class.value == "NEGATED_FACT"


def test_no_reconocio_que_completivo_sigue_siendo_scope_ambiguo():
    """'no reconocio que ...' con 'que' completivo INMEDIATO: sigue siendo
    SCOPE_AMBIGUOUS (el operador de B1 no se rompe)."""
    verdict = analyze_raw_text(
        "El archivero no reconocio que Aldric Venn hubiera firmado el acuerdo."
    )
    assert verdict.factivity.factivity_class.value == "UNKNOWN"
    assert verdict.negation_kind == "SCOPE_AMBIGUOUS"


def test_no_acepto_que_completivo_sigue_siendo_scope_ambiguo():
    """'no acepto que ...' con 'que' completivo INMEDIATO: sigue siendo
    SCOPE_AMBIGUOUS."""
    verdict = analyze_raw_text(
        "El Sindicato Vitivinicola no acepto que Aldric Venn dirigiera el taller."
    )
    assert verdict.factivity.factivity_class.value == "UNKNOWN"
    assert verdict.negation_kind == "SCOPE_AMBIGUOUS"


def test_no_sabia_objeto_directo_es_negated_fact():
    """La correccion generaliza a los SCOPE_VERBS preexistentes a B1.
    'saber' + objeto directo sin 'que': NEGATED_FACT."""
    verdict = analyze_raw_text(
        "Aldric Venn no sabia la respuesta que el Sindicato Vitivinicola esperaba."
    )
    assert verdict.factivity.factivity_class.value == "NEGATED_FACT"


def test_no_sabe_que_completivo_sigue_siendo_scope_ambiguo():
    """'no sabe que ...' con 'que' completivo: sigue siendo SCOPE_AMBIGUOUS.
    La correccion es quirurgica: no rompe los casos que ya funcionaban."""
    verdict = analyze_raw_text(
        "El Sindicato Vitivinicola no sabe que Aldric Venn firmo el contrato."
    )
    assert verdict.factivity.factivity_class.value == "UNKNOWN"
    assert verdict.negation_kind == "SCOPE_AMBIGUOUS"


def test_no_sabe_si_interrogativa_indirecta_sigue_siendo_scope_ambiguo():
    """'no sabe si ...' con 'si' interrogativo indirecto: tambien es SCOPE_AMBIGUOUS.
    La guarda admite 'que' Y 'si'; 'si' cubre la construccion de interrogativa
    indirecta ('no sabe si dirige'), que crea el mismo efecto de alcance que
    'no sabe que'. Refinamiento de B2 para no romper el corpus de puerta 4."""
    verdict = analyze_raw_text(
        "La officiala Niran Ferro no sabe si Vidal Kuang dirige el Taller Carmesi."
    )
    assert verdict.negation_kind == "SCOPE_AMBIGUOUS"


# --------------------------------------------------------------------------
# 3. No regresion: las frases que B1 cubria siguen bien en B2.
# --------------------------------------------------------------------------
def test_dijo_que_sigue_siendo_rumor():
    """El operador de reporte (B1) no se rompe con los cambios de B2."""
    verdict = analyze_raw_text(
        "El archivero Aldric Venn dijo que el Sindicato Vitivinicola firma el acuerdo."
    )
    assert verdict.factivity.factivity_class.value == "RUMOR"


def test_informo_que_sigue_siendo_rumor():
    verdict = analyze_raw_text(
        "Aldric Venn informo que el Sindicato Vitivinicola habia renovado el contrato."
    )
    assert verdict.factivity.factivity_class.value == "RUMOR"


def test_frase_factiva_simple_sigue_siendo_asserted_fact():
    """Guarda de regresion: ninguna frase factiva sin operador especial
    se degrada por los cambios de B2."""
    verdict = analyze_raw_text(
        "Aldric Venn dirige el Sindicato Vitivinicola desde el ano pasado."
    )
    assert verdict.factivity.factivity_class.value == "ASSERTED_FACT"


# --------------------------------------------------------------------------
# 4. Rework de B2: la clase COMPLETA de conectores de interrogativa indirecta.
#
#    B2 solo reconocia "que" y "si" -- los dos que los corpus (dev y puerta 4)
#    exigieron. El resto de la clase gramatical ("cuando", "donde", "como",
#    "quien", "cual", "cuanto", "por que", "lo que") es el MISMO fenomeno de
#    alcance epistemico y caia en silencio a negacion directa, es decir, a
#    afirmar la negacion de una relacion que el texto no niega.
# --------------------------------------------------------------------------
INTERROGATIVOS_INDIRECTOS = [
    "El bodeguero no sabe cuando zarpo el carguero del muelle austral.",
    "El bodeguero no sabe donde amarro el carguero del muelle austral.",
    "El bodeguero no recuerda como llego el carguero al muelle austral.",
    "El bodeguero no recuerda quien fleto el carguero del muelle austral.",
    "El bodeguero no confirmo cual bodega alquilo el carguero del muelle austral.",
    "El bodeguero no confirmo cuantos fardos descargo el carguero del muelle austral.",
    "El bodeguero no verifico por que zarpo el carguero del muelle austral.",
    "El bodeguero no verifico lo que descargo el carguero del muelle austral.",
]


def test_toda_la_clase_de_interrogativas_indirectas_da_alcance_ambiguo():
    fallos = []
    for texto in INTERROGATIVOS_INDIRECTOS:
        verdict = analyze_raw_text(texto)
        if verdict.negation_kind != "SCOPE_AMBIGUOUS":
            fallos.append((texto, verdict.negation_kind))
    assert not fallos, (
        "conectores de la clase cerrada que no disparan alcance ambiguo: "
        f"{fallos!r}"
    )


def test_la_clase_declarada_cubre_los_conectores_de_una_palabra():
    """Guarda de completitud de la clase gramatical: si alguien recorta la
    lista, este test lo dice por su nombre en vez de dejar que se note solo
    como una cifra peor en el corpus."""
    esperados = {
        "que", "si", "cuando", "donde", "adonde", "como", "quien", "quienes",
        "cual", "cuales", "cuanto", "cuanta", "cuantos", "cuantas",
    }
    assert esperados <= INDIRECT_QUESTION_CONNECTORS


def test_los_conectores_de_dos_tokens_estan_declarados_aparte():
    assert ("por", "que") in INDIRECT_QUESTION_CONNECTOR_PAIRS
    assert ("lo", "que") in INDIRECT_QUESTION_CONNECTOR_PAIRS


def test_un_objeto_directo_corriente_no_es_conector():
    """El limite de la ampliacion: sin conector de la clase, la negacion sigue
    siendo directa (es la correccion original de B2, que no se toca)."""
    verdict = analyze_raw_text(
        "El bodeguero no verifico las bodegas del carguero austral."
    )
    assert verdict.negation_kind == "SIMPLE"
    assert verdict.factivity.factivity_class.value == "NEGATED_FACT"
