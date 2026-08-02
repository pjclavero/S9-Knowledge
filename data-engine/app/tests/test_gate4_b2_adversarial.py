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

Todo lo que aqui se marca `xfail(strict=True)` es un defecto REAL documentado
que el B2 no corrige (no toca el codigo entregado, solo lo hace explicito).
Todo lo que se marca como assert duro y NO xfail es una regresion de
precision que un futuro parche NO debe reintroducir en silencio.
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

@pytest.mark.xfail(strict=True, reason=(
    "P0 B2: EXCEPTIVE_SUBORDINATORS ('sin'+'que' adyacentes) dispara "
    "negacion aunque la clausula 'sin que...' sea un adjunto del VERBO "
    "PRINCIPAL y no del complemento evaluado. Antes de B2 esta frase daba "
    "negated=False (correcto); B2 la vuelve un falso positivo. La regla no "
    "verifica que la subordinada exceptiva rija sobre el complemento "
    "focalizado, solo que 'sin que' aparezca en algun punto de la ventana."
))
def test_sin_que_no_debe_negar_cuando_la_subordinada_no_rige_el_complemento():
    text = (
        "El emisario hablo sin que nadie lo interrumpiera sobre la Liga de "
        "Corvo."
    )
    negated, _kind = _negated(text, "la Liga de Corvo")
    assert negated is False


@pytest.mark.xfail(strict=True, reason=(
    "P0 B2: CESSATION_PHRASES ahora incluye 'ha dejado de' sin exigir que "
    "el verbo que sigue sea semanticamente una RELACION (vinculo, cargo, "
    "alianza...). 'Ha dejado de fumar' es cesacion de un HABITO, no de "
    "ninguna relacion con la entidad-objeto de la frase (una ciudad que ni "
    "siquiera participa de la cesacion). Antes de B2 esta frase daba "
    "negated=False; B2 la convierte en falso positivo por simple presencia "
    "lexica de 'ha dejado de' en la ventana."
))
def test_ha_dejado_de_no_debe_negar_relacion_no_vinculada_al_complemento():
    text = "Ha dejado de fumar desde que llego a la ciudad de Ostrava."
    negated, _kind = _negated(text, "la ciudad de Ostrava")
    assert negated is False


@pytest.mark.xfail(strict=True, reason=(
    "P0 B2: 'ha dejado atras' se añadio a CESSATION_PHRASES leyendo SOLO el "
    "sentido figurado (cesar una alianza/relacion), pero la frase tambien "
    "tiene sentido LITERAL/fisico (dejar un lugar atras al desplazarse), que "
    "no es cesacion de ninguna relacion con la entidad. Antes de B2: "
    "negated=False (correcto). B2 la vuelve un falso positivo por el mismo "
    "matching puramente lexico, sin distinguir el sentido."
))
def test_ha_dejado_atras_sentido_fisico_no_debe_confundirse_con_cesacion():
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

@pytest.mark.xfail(strict=True, reason=(
    "P0 B2: CESSATION_PHRASES solo contiene 'ha dejado atras' (y su "
    "variante typo 'ha dejado atraes'), la conjugacion EXACTA del caso "
    "gen:hard:03. Ni el preterito ('dejo atras'/'dejaron atras'), ni el "
    "futuro ('dejara atras'), ni el gerundio ('esta dejando atras'), ni el "
    "plural del presente perfecto ('han dejado atras') se reconocen. Esto "
    "demuestra que la regla memoriza la forma verbal del episodio de origen "
    "en vez de generalizar la familia verbal 'dejar atras' como cesacion."
))
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
def test_ha_dejado_atras_no_generaliza_a_otras_conjugaciones(text, label):
    negated, _kind = _negated(text, "la Orden de Piedra Fria")
    assert negated is True, f"conjugacion {label} no reconocida como cesacion"


# ---------------------------------------------------------------------------
# 4. Variantes nuevas (>=2 por construccion) de las 4 familias de
#    HARD_SCOPE_LITOTES, con entidades y redacciones propias del
#    AGENTE-DE-TESTS (no repiten texto de gen:hard:01..04).
# ---------------------------------------------------------------------------

# 4a. EXCEPTIVE_SCOPE ("sin que" rigiendo el complemento focalizado): ambas
# generalizan correctamente porque "sin que" precede y rige directamente la
# clausula que contiene el complemento.
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
def test_exceptive_scope_generaliza_cuando_rige_el_complemento(text, anchor):
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
