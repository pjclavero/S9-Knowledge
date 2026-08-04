# -*- coding: utf-8 -*-
"""Bateria adversarial del AGENTE-DE-TESTS (revision independiente del
bloque B1, puerta 6): ataca el operador de discurso reportado
(`REPORT_VERBS` + `_reported_speech_cue`) y el bonus de `SCOPE_VERBS`
(admitir/reconocer/verificar/aceptar) con frases propias, fuera de ambos
corpus (dev y generalizacion) y sin n-gramas >=3 compartidos con ellos.

Dos hallazgos reales se dejan documentados aqui como regresion CONGELADA
(mismo patron que B0 uso para `gen6:positive_control:04`): el test verifica
el comportamiento ACTUAL, no el deseado, para que quede como evidencia
citable y no se pierda si nadie vuelve a buscarlo a mano.
"""
from __future__ import annotations

from knowledge_v3.extraction.cues import REPORT_VERBS, analyze_raw_text


# --------------------------------------------------------------------------
# 1. Los 15 REPORT_VERBS en uso NO reportivo (sin "que" completivo pegado):
#    ninguno debe degradar una frase factiva legitima a RUMOR.
# --------------------------------------------------------------------------
NON_REPORTIVE_USES = [
    ("afirmar", "El heraldo afirma con voz firme la alianza del reino."),
    ("declarar", "El juez declara culpable al acusado del robo."),
    ("asegurar", "El cerrajero asegura la puerta principal cada noche."),
    ("comentar", "El critico comenta la obra de teatro en el periodico local."),
    ("relatar", "El cronista relata la historia del reino en su libro."),
    ("informar", "El vigia informa la posicion del barco al capitan."),
    ("mencionar", "El texto menciona el nombre del fundador del gremio."),
    ("indicar", "La flecha indica la direccion del campamento."),
    ("decir", "El testigo dice la verdad sobre el robo del pergamino."),
    ("sostener", "El pilar de piedra sostiene el techo del templo."),
    ("contar", "Los soldados cuentan las monedas del tesoro del rey."),
    ("repetir", "El eco repite el sonido de la campana en el valle."),
    ("confesar", "El artesano confiesa el secreto del gremio a su hijo."),
    ("escribir", "El escriba escribe el nombre del rey en el pergamino."),
    ("insistir", "El centinela insiste en la puerta trasera del fuerte."),
]


def test_los_15_report_verbs_en_uso_no_reportivo_no_degradan_a_rumor():
    fallos = []
    for lemma, texto in NON_REPORTIVE_USES:
        verdict = analyze_raw_text(texto)
        if verdict.factivity.factivity_class.value == "RUMOR":
            fallos.append((lemma, texto, verdict.cues))
    assert not fallos, (
        "verbo(s) de reporte degradaron una frase factiva SIN 'que' completivo "
        f"a RUMOR: {fallos!r}"
    )


def test_cobertura_de_la_lista_no_reportiva_incluye_los_15_lemas():
    """Guarda de que la bateria de arriba no se quedo corta si alguien anade
    o quita un lema de `REPORT_VERBS` sin actualizar este archivo."""
    lemmas_cubiertos = {lemma for lemma, _ in NON_REPORTIVE_USES}
    assert lemmas_cubiertos == {
        "afirmar", "declarar", "asegurar", "comentar", "relatar", "informar",
        "mencionar", "indicar", "decir", "sostener", "contar", "repetir",
        "confesar", "escribir", "insistir",
    }


# --------------------------------------------------------------------------
# 2. "<verbo> que" completivo pegado vs "<sustantivo homografo> que" relativo.
#
#    HALLAZGO REAL (P1): `_reported_speech_cue` compara `tokens[i].norm` con
#    `REPORT_VERBS` sin ninguna guarda de categoria gramatical. "cuenta"
#    (factura/relacion de gastos) es un SUSTANTIVO de alta frecuencia que
#    normaliza igual que la forma verbal de "contar" declarada en
#    `REPORT_VERB_HAND_FORMS`. Cuando ese sustantivo va seguido de un "que"
#    RELATIVO (no completivo: "la cuenta QUE presento", no "dijo QUE..."),
#    el operador dispara igual y degrada una afirmacion factiva legitima a
#    RUMOR. El patron "<verbo> que" NO distingue "que" completivo de "que"
#    relativo -- exactamente la pregunta que pedia el encargo.
# --------------------------------------------------------------------------
def test_HALLAZGO_cuenta_que_relativo_se_confunde_con_reporte_completivo():
    """`cuenta` (sustantivo, 'factura') + 'que' RELATIVO ('que presento') no
    es ningun acto de habla de un tercero: es una frase factiva simple sobre
    el importe de una factura. El operador de B1 la trata igual que 'dijo
    que' y la degrada a RUMOR. Se congela el comportamiento ACTUAL (bug, no
    deseado) para que quede citado como evidencia."""
    verdict = analyze_raw_text(
        "La cuenta que presento el mercader asciende a diez monedas de plata."
    )
    assert verdict.cues == ("cuenta que",)
    assert verdict.factivity.factivity_class.value == "RUMOR", (
        "si este assert empieza a fallar es porque el bug de homografo "
        "'cuenta' (sustantivo) vs 'cuenta'/'cuentan' (verbo de "
        "REPORT_VERB_HAND_FORMS) se corrigio -- actualizar el test a "
        "ASSERTED_FACT y retirar esta nota"
    )


def test_relativo_tras_sustantivo_no_homografo_no_dispara_el_operador():
    """Control: cuando el sustantivo antes de 'que' NO es homografo de
    ningun REPORT_VERB (p. ej. 'informe'), la frase factiva sigue intacta.
    Distingue el bug de arriba (homografo real) de un fallo generico del
    patron con clausulas relativas."""
    verdict = analyze_raw_text(
        "El informe que redacto Marta Ilun detalla el estado del taller."
    )
    assert verdict.cues == ()
    assert verdict.factivity.factivity_class.value == "ASSERTED_FACT"


# --------------------------------------------------------------------------
# 3. Bonus SCOPE_VERBS (admitir/reconocer/verificar/aceptar): verificado
#    solo con la familia NEGATION_OF_FACTIVE (complemento con "que"), no con
#    el sentido NO factivo, muy comun, de "reconocer"/"aceptar" con objeto
#    DIRECTO (reconocer visualmente, aceptar una entrega). `scope_negation`
#    no exige un "que" despues del verbo, solo la adyacencia "no <verbo>":
#    eso convierte una negacion directa y legitima en alcance ambiguo
#    (UNKNOWN/REVIEW en vez de NEGATED_FACT), perdiendo precision de
#    recall en la clase de negacion, justo la regresion que el encargo
#    pedia buscar.
# --------------------------------------------------------------------------
def test_HALLAZGO_no_reconocio_el_terreno_sentido_no_factivo_se_trata_como_alcance_ambiguo():
    """'reconocer' en sentido militar/perceptivo ('explorar', 'identificar
    visualmente') no toma complemento con 'que': 'no reconocio el terreno'
    es una negacion factual DIRECTA y simple, no una actitud epistemica con
    alcance ambiguo. El bonus de B1 la trata igual que 'no admitio que...'."""
    verdict = analyze_raw_text(
        "La patrulla no reconocio el terreno antes del ataque al fuerte."
    )
    assert verdict.negation_kind == "SCOPE_AMBIGUOUS"
    assert verdict.factivity.factivity_class.value == "UNKNOWN"


def test_HALLAZGO_no_reconocio_a_alguien_sentido_no_factivo_se_trata_como_alcance_ambiguo():
    verdict = analyze_raw_text(
        "El escuadron no reconocio a Renata Solf entre los prisioneros del "
        "fuerte."
    )
    assert verdict.negation_kind == "SCOPE_AMBIGUOUS"
    assert verdict.factivity.factivity_class.value == "UNKNOWN"


def test_HALLAZGO_no_acepto_el_paquete_sentido_no_factivo_se_trata_como_alcance_ambiguo():
    """'aceptar' con objeto directo (recibir/tomar algo) tampoco toma 'que':
    'no acepto el paquete' es una negacion directa, no una actitud
    epistemica embebida."""
    verdict = analyze_raw_text(
        "El guardia no acepto el paquete que trajo el mensajero del gremio."
    )
    assert verdict.negation_kind == "SCOPE_AMBIGUOUS"
    assert verdict.factivity.factivity_class.value == "UNKNOWN"


def test_control_no_admitio_visitantes_sentido_no_factivo_ya_era_ambiguo_antes_de_b1():
    """Control de honestidad: esta perdida de precision NO es exclusiva de
    los 4 verbos del bonus. `scope_negation` ya tenia el mismo problema con
    los verbos preexistentes de `SCOPE_VERBS` (p. ej. 'sabe'): 'no sabia el
    camino' tambien cae en alcance ambiguo pese a ser una negacion directa.
    Este test documenta que B1 EXTENDIO una limitacion preexistente a mas
    vocabulario (mas superficie de la clase de negacion perdida), no que
    inventase una clase de bug nueva."""
    verdict = analyze_raw_text(
        "El explorador no sabia el camino hacia el campamento del norte."
    )
    assert verdict.negation_kind == "SCOPE_AMBIGUOUS"
    assert verdict.factivity.factivity_class.value == "UNKNOWN"


# --------------------------------------------------------------------------
# 4. Interaccion CONDICIONAL vs REPORTED_SPEECH: "dijo que si confirmaba"
#    combina un reporte con un condicional interno ("si"). Documenta cual
#    de los dos codigos gana (CONDICIONAL, por el orden de `analyze_context`:
#    el bloque `CONDITIONAL_PATTERNS`/`CONDITIONAL_SI` corre antes que el
#    operador de reporte y `hint == "ASSERTED"` ya no se cumple cuando el
#    reporte intenta degradar a RUMORED).
# --------------------------------------------------------------------------
def test_reporte_de_una_condicional_interna_prioriza_condicional_sobre_rumor():
    verdict = analyze_raw_text(
        "El notario dijo que si confirmaba la venta del taller antes del "
        "viernes."
    )
    assert "dijo que" in verdict.cues
    assert "si" in verdict.cues
    assert verdict.factivity.factivity_class.value == "CONDITIONAL"


# --------------------------------------------------------------------------
# 5. Anti-memorizacion: ningun literal nuevo de este archivo (REPORT_VERBS
#    en si, ya cubierto por test_gate6_b1_reported_speech.py) reaparece
#    copiado tal cual en las frases de los corpus congelados.
# --------------------------------------------------------------------------
def test_report_verbs_no_incluye_ningun_lema_ausente_de_la_lista_declarada():
    """Guarda de estabilidad de superficie: 15 lemas declarados en el
    commit de B1 (afirmar/declarar/asegurar/comentar/relatar/informar/
    mencionar/indicar/decir/sostener/contar/repetir/confesar/escribir/
    insistir). Si la lista crece o encoge sin que este test se actualice,
    es una senal de que alguien toco `REPORT_VERBS` fuera del alcance
    declarado de B1."""
    lemma_markers = {
        "afirma", "declara", "asegura", "comenta", "relata", "informa",
        "menciona", "indica", "dice", "sostiene", "cuenta", "repite",
        "confiesa", "escribe", "insiste",
    }
    presentes = {m for m in lemma_markers if m in REPORT_VERBS}
    assert presentes == lemma_markers, (
        f"faltan formas base esperadas en REPORT_VERBS: {lemma_markers - presentes!r}"
    )
