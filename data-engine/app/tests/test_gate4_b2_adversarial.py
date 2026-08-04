# -*- coding: utf-8 -*-
"""Puerta 4, bloque B2: bateria ADVERSARIAL del AGENTE-DE-TESTS.

No repite lo que ya cubre `test_gate4_b2_rules.py` (presencia de frase en
RELATION_RULES, predicado correcto). Esto ataca las reglas nuevas de B2
desde tres angulos que el implementador no probo:

1. Trampas de falso positivo con marcadores parecidos pero SIN negacion real
   ("no obstante", "sin embargo", "dejar de lado", "ha dejado de <verbo
   generico>", "ha dejado atras <lugar fisico>"...).
2. Generalizacion morfologica de las frases nuevas: si una regla solo
   reconoce UNA conjugacion exacta de un verbo (la que aparecia literalmente
   en el episodio de origen) y falla con el resto de conjugaciones de la
   misma familia verbal, es evidencia de que la "regla de lengua" es en
   realidad un literal de corpus disfrazado.
3. Variantes nuevas de las 4 construcciones de HARD_SCOPE_LITOTES (>= 2 por
   construccion), para separar "entiende el marcador" de "coincide con la
   frase exacta del caso de generalizacion".

Los 6 `xfail(strict=True)` originales documentaban defectos P0 reales de la
primera entrega de B2. La ronda de REWORK (dictamen NO CONFORME) los corrigio
todos, asi que aqui ya son tests verdes normales: cada uno conserva en su
docstring el defecto que documentaba y la guarda que lo cierra. Un futuro
parche que reintroduzca cualquiera de ellos vuelve a poner esta bateria en
rojo, que es exactamente para lo que existe.
"""
from __future__ import annotations

import pytest

from knowledge_v3.extraction.cues import analyze_raw_text


def _negated(text: str, anchor: str) -> tuple[bool, str]:
    focus_char = text.find(anchor)
    assert focus_char >= 0, f"ancla no encontrada: {anchor!r}"
    v = analyze_raw_text(text, focus_char=focus_char)
    return bool(v.negated), v.negation_kind


# ---------------------------------------------------------------------------
# 1. Falsos positivos reales introducidos por reglas NUEVAS de B2 (regresion
#    de precision: NO estaban presentes antes de B2, se comprobo por
#    comparacion directa contra el codigo pre-B2 via `git stash`).
# ---------------------------------------------------------------------------

def test_sin_que_no_debe_negar_cuando_la_subordinada_no_rige_el_complemento():
    """CORREGIDO en el rework de B2 (era xfail P0).

    B2 disparaba negacion en cuanto 'sin'+'que' aparecian antes del foco, sin
    comprobar que el foco cayera DENTRO de la subordinada exceptiva.
    `cues.exceptive_scope` delimita ahora el alcance desde el 'que' hasta el
    primer limite (puntuacion, conjuncion de clausula o preposicion de
    adjunto). Aqui 'sobre la Liga de Corvo' queda FUERA -> no se niega.
    """
    text = (
        "El emisario hablo sin que nadie lo interrumpiera sobre la Liga de "
        "Corvo."
    )
    negated, kind = _negated(text, "la Liga de Corvo")
    assert negated is False
    assert kind == "SCOPE_AMBIGUOUS"


def test_sin_que_no_afecta_a_un_hecho_de_la_clausula_principal():
    """Exigido por el dictamen: un claim de la PRINCIPAL, enunciado ANTES de
    'sin que', no puede quedar negado por la subordinada posterior."""
    text = (
        "El notario del Concejo de Aguasverdes firmo el acta sin que el "
        "testigo la avalara."
    )
    negated, kind = _negated(text, "el Concejo de Aguasverdes")
    assert negated is False
    assert kind == ""


def test_ha_dejado_de_no_debe_negar_relacion_no_vinculada_al_complemento():
    """CORREGIDO en el rework de B2 (era xfail P0).

    `cues.cessation_complement_ok` exige ahora que el infinitivo que sigue a
    la perifrasis este en `RELATIONAL_INFINITIVES`. 'fumar' no lo esta: es un
    habito, no un vinculo.
    """
    text = "Ha dejado de fumar desde que llego a la ciudad de Ostrava."
    negated, _kind = _negated(text, "la ciudad de Ostrava")
    assert negated is False


def test_ha_dejado_atras_sentido_fisico_no_debe_confundirse_con_cesacion():
    """CORREGIDO en el rework de B2 (era xfail P0).

    `cues.cessation_complement_ok` exige que el nucleo del complemento de
    'dejar atras' este en `RELATIONAL_COMPLEMENT_NOUNS` (alianza, lazos,
    pacto, cargo...). 'campamento' no lo esta: es desplazamiento fisico.
    """
    text = (
        "El general ha dejado atras el campamento de Piedra Fria para "
        "avanzar hacia Rocavieja."
    )
    negated, _kind = _negated(text, "Rocavieja")
    assert negated is False


# ---------------------------------------------------------------------------
# 2. Controles: frases parecidas a las nuevas de B2 que NO deben disparar
#    (para separar el foco real de la regla del ruido) -- estas SI pasan hoy,
#    documentan que no todo lo nuevo de B2 es fragil.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,anchor", [
    ("No obstante, el barco zarpo hacia la isla de Meridion.", "la isla de Meridion"),
    ("Sin embargo, el gremio firmo el pacto con la Casa de Ulmar.", "la Casa de Ulmar"),
    ("No pocas veces el rey visito el castillo de Torre Alta.", "el castillo de Torre Alta"),
    (
        "No pocos dudaban, pero el si era miembro de la Guardia Real de "
        "Ostia.",
        "la Guardia Real de Ostia",
    ),
])
def test_controles_no_negacion_no_regresionados_por_b2(text, anchor):
    # NOTA: "No obstante" ya daba falso positivo ANTES de B2 (se verifico
    # con git stash) -- es deuda preexistente del vocabulario cerrado de
    # NEGATION_CUES ("no" suelto dispara SIMPLE), no algo que B2 haya
    # introducido ni corregido. Se documenta aqui, no como xfail nuevo de
    # B2, sino como constancia de que sigue igual. "Sin embargo" no
    # contiene "no" como token independiente, asi que no dispara.
    negated, _kind = _negated(text, anchor)
    if text.startswith("No obstante"):
        assert negated is True, (
            "deuda preexistente (pre-B2) de falso positivo con el conector "
            "'no obstante': si esto empieza a dar False, es una mejora "
            "real, actualizar el test"
        )
    else:
        assert negated is False


# ---------------------------------------------------------------------------
# 3. Generalizacion morfologica de "ha dejado atras": si la regla realmente
#    entendiera "cesacion perifrastica con dejar atras" (marcador de lengua),
#    generalizaria a otras personas/tiempos verbales del mismo verbo. Si solo
#    reconoce la conjugacion EXACTA que aparecia en gen:hard:03
#    ("ha dejado atras", 3a persona singular presente perfecto), es un
#    literal de corpus con forma de "frase de lengua".
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,label", [
    (
        "El curador dejo atras su alianza con la Orden de Piedra Fria.",
        "preterito 3s",
    ),
    (
        "Los curadores dejaron atras su alianza con la Orden de Piedra Fria.",
        "preterito 3p",
    ),
    (
        "Los curadores han dejado atras su alianza con la Orden de Piedra "
        "Fria.",
        "presente perfecto 3p",
    ),
])
def test_dejar_atras_generaliza_a_todo_el_paradigma(text, label):
    """CORREGIDO en el rework de B2 (era xfail P0 de memorizacion).

    Los literales 'ha dejado atras' / 'ha dejado atraes' (la conjugacion
    exacta de gen:hard:03, mas su typo) desaparecieron de `CESSATION_PHRASES`.
    La perifrasis se GENERA ahora del paradigma `cues.DEJAR_FORMS`, asi que
    todas las conjugaciones de la familia se reconocen igual.
    """
    negated, _kind = _negated(text, "la Orden de Piedra Fria")
    assert negated is True, f"conjugacion {label} no reconocida como cesacion"


# ---------------------------------------------------------------------------
# 4. Variantes nuevas (>=2 por construccion) de las 4 familias de
#    HARD_SCOPE_LITOTES, con entidades y redacciones propias del
#    AGENTE-DE-TESTS (no repiten texto de gen:hard:01..04).
# ---------------------------------------------------------------------------

# 4a. EXCEPTIVE_SCOPE. ACTUALIZADO en el rework de B2. En las dos frases el
# complemento focalizado va detras de una preposicion de adjunto ("ante", "para")
# que sigue al verbo subordinado, asi que puede colgar del verbo principal o del
# subordinado -- exactamente la misma configuracion que
# `test_sin_que_no_debe_negar_cuando_la_subordinada_no_rige_el_complemento`, que
# es un falso positivo demostrado. Token a token son indistinguibles.
#
# La regla de oro del programa dice que donde hay un falso positivo la regla sale
# o se degrada a REVIEW; se ha degradado. El coste esta declarado en el artefacto:
# gen:hard:01 pasa de acierto a abstencion y HARD_SCOPE_LITOTES baja. Es perdida
# de COBERTURA, no de precision: el clasificador ya no afirma nada aqui.
@pytest.mark.parametrize("text,anchor", [
    (
        "El notario firmo el acta sin que el testigo la avalara ante el "
        "Concejo de Aguasverdes.",
        "el Concejo de Aguasverdes",
    ),
    (
        "El heraldo proclamo el edicto sin que el consejo lo aprobara para "
        "la Provincia de Altavista.",
        "la Provincia de Altavista",
    ),
])
def test_exceptive_scope_con_adjuncion_ambigua_pide_revision(text, anchor):
    negated, kind = _negated(text, anchor)
    assert negated is False
    assert kind == "SCOPE_AMBIGUOUS"


@pytest.mark.parametrize("text,anchor", [
    (
        "El notario firmo el acta sin que el testigo avalara el Concejo de "
        "Aguasverdes.",
        "el Concejo de Aguasverdes",
    ),
    (
        "El heraldo proclamo el edicto sin que el consejo aprobara la "
        "Provincia de Altavista.",
        "la Provincia de Altavista",
    ),
])
def test_exceptive_scope_niega_cuando_el_foco_esta_dentro_del_alcance(text, anchor):
    """Sin preposicion de adjunto de por medio, el foco cae dentro de la
    subordinada exceptiva y la negacion SI se decide."""
    negated, kind = _negated(text, anchor)
    assert negated is True
    assert kind == "SIMPLE"  # cues.py no distingue EXCEPTIVE_SCOPE, cae en SIMPLE


# 4b. Litotes correctiva "no es que no...": ambas variantes se leen igual
# que gen:hard:02 -- SCOPE_AMBIGUOUS, no negada. Documenta que el "acierto"
# de B2 en 3/4 no incluye esta familia (sigue en 0/1 aqui tambien, coherente
# con el centinela).
@pytest.mark.parametrize("text,anchor", [
    (
        "No es que el mercader no comerciara con la Casa de Nueve Rios.",
        "la Casa de Nueve Rios",
    ),
    (
        "No es que el escriba no redactara el edicto para el Cabildo de "
        "Alba Gris.",
        "el Cabildo de Alba Gris",
    ),
])
def test_litotes_correctiva_sigue_sin_resolverse_sin_falsos_positivos(text, anchor):
    """No corrige la lectura (sigue sin marcar la afirmacion positiva
    resuelta), pero tampoco debe invertir el sentido a negado=True: se
    mantiene en SCOPE_AMBIGUOUS/no-negado, que es el comportamiento seguro
    (manda a revision, no afirma ni niega por error)."""
    negated, kind = _negated(text, anchor)
    assert negated is False
    assert kind == "SCOPE_AMBIGUOUS"


# 4c. Litotes cuantitativa "no pocos/pocas": generaliza bien al genero
# femenino y a nueva sintaxis (ya cubierto por LITOTES_QUANTIFIERS, que SI
# es una regla de lengua parametrica -- no un literal).
@pytest.mark.parametrize("text,anchor", [
    (
        "No pocas escribas respaldaron la fundacion del Priorato de Sal "
        "Vieja.",
        "el Priorato de Sal Vieja",
    ),
    (
        "No pocos mercaderes financiaron la expedicion de la Compania de "
        "Rio Largo.",
        "la Compania de Rio Largo",
    ),
])
def test_litotes_cuantitativa_generaliza_genero_y_sintaxis(text, anchor):
    negated, _kind = _negated(text, anchor)
    assert negated is False
