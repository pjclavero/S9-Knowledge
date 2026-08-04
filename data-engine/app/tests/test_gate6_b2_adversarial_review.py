# -*- coding: utf-8 -*-
"""Bateria adversarial del AGENTE-DE-TESTS (revision independiente del
bloque B2, puerta 6, CIERRE): ataca las dos correcciones que B2 dice haber
entregado -- la guarda de homografo de `_reported_speech_cue` y el requisito
de conector "que"/"si" de `classify_negation` -- con frases propias, fuera de
ambos corpus (dev y generalizacion) y sin n-gramas >=3 compartidos con ellos
ni con `tests/test_gate6_b2_bugs.py`.

Dos hallazgos reales se documentan aqui como evidencia CONGELADA (mismo
patron que usa `test_gate6_b1_adversarial_review.py` para sus propios
hallazgos): el test verifica el comportamiento ACTUAL del sistema, no el
deseado, precisamente para que no se pierda si nadie mas lo busca a mano.

1. (P0) El operador de discurso reportado (`REPORT_VERBS` /
   `_reported_speech_cue`, entregado en B1 y sobre el que B2 construye su
   guarda de homografo) NUNCA llega al extractor determinista de produccion
   (`extraction/deterministic.py`). Ese modulo calcula su propio
   `epistemic_status_hint` con una lista local, mucho mas corta
   (`deterministic.EPISTEMIC_CUES`, alias de `cues.EPISTEMIC_CUES`), y jamas
   invoca `cues.analyze_context()` para las clases RUMOR/EMIT_EPISTEMIC_
   PROPOSAL (solo consulta `policy.action` para las ramas EMIT_DIAGNOSTIC y
   REVIEW_SCOPE). Consecuencia verificada: "El heraldo dijo que ..." y
   "El cronista afirma que ..." -- justo los verbos productivos que B1/B2
   anaden a `REPORT_VERBS` -- salen del extractor determinista como
   ASSERTED_FACT con `review_required=False`, exactamente el hecho no
   verificado que el programa de la puerta 6 existe para no materializar.
   El mecanismo SI funciona para el extractor de PROVEEDOR/LLM
   (`extraction/payload.py`, que si llama a `analyze_context` y lee
   `verdict.hint`), asi que el hallazgo es especifico del carril
   determinista.

2. (P1) La correccion de `classify_negation` que exige un conector "que" o
   "si" inmediato tras un `SCOPE_VERB` para clasificar SCOPE_AMBIGUOUS solo
   reconoce esos dos conectores. Cualquier otra interrogativa indirecta
   ("cuando", "donde", "como", "quien", "cual", "por que", "lo que") --
   semanticamente el MISMO fenomeno de alcance epistemico que "si" -- cae
   al camino de negacion DIRECTA (NEGATED_FACT). Antes de B2 (bloque B1,
   commit bb4a46a) estas mismas frases SI se leian como SCOPE_AMBIGUOUS
   (adyacencia simple, sin exigir conector): la correccion de B2 estrecha
   el conjunto de conectores reconocidos y, con ello, reintroduce en
   silencio el riesgo que B1 evitaba para esta familia concreta de
   interrogativas indirectas. No aparece en el corpus de generalizacion
   compuesto por el propio autor (por eso `b2-final.json` no lo detecta), y
   `scripts/gate4/measure_b5.py` tampoco lo ve: se comparo byte a byte
   contra `artifacts/gate4-program/b5-final.json` y no hay ninguna
   diferencia (el corpus de puerta 4 no contiene ninguna interrogativa
   indirecta con "cuando"/"donde"/"como"/"quien"/"cual"/"por que" pegada a
   un SCOPE_VERB negado).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from knowledge_v3.extraction.cues import analyze_raw_text
from test_knowledge_v3_extraction import DeterministicExtractor, asserted, single_context  # noqa: E402,I100


# --------------------------------------------------------------------------
# 1. (P0) El operador de discurso reportado no llega al extractor
#    determinista: RUMOR se convierte en ASSERTED_FACT sin revision.
# --------------------------------------------------------------------------
def test_dijo_que_en_el_extractor_determinista_no_se_degrada_a_rumor():
    """Documenta el hallazgo P0: `analyze_raw_text` (usado por el arnes de
    la puerta 6) SI clasifica esto como RUMOR, pero el extractor de
    PRODUCCION (`DeterministicExtractor`) no consulta ese resultado para
    las clases RUMOR/EMIT_EPISTEMIC_PROPOSAL y produce un hecho asertado sin
    marca de revision. Si esta asercion deja de cumplirse porque alguien
    conecto los dos carriles, el hallazgo esta resuelto y este test debe
    actualizarse (no borrarse sin mas: hay que declarar el cierre)."""
    texto = "El heraldo dijo que Elara lidera la Orden del Alba."

    # A nivel de clasificador (lo que mide el arnes de la puerta 6): RUMOR.
    verdict = analyze_raw_text(texto)
    assert verdict.factivity.factivity_class.value == "RUMOR"

    # A nivel del extractor determinista de produccion: el mismo texto no
    # se degrada. Esto es el bug, documentado como regresion congelada.
    ctx, _ = single_context("ep:gate6-b2-adv-01", texto)
    claims = asserted(DeterministicExtractor().extract(ctx))
    assert claims, "se esperaba al menos una propuesta de hecho"
    claim = claims[0]
    assert claim.epistemic_status_hint == "ASSERTED", (
        "HALLAZGO P0: el extractor determinista NO degrada 'dijo que' a "
        "RUMORED (el operador de discurso reportado de B1/B2 no esta "
        "conectado a este carril); si esto cambia a 'RUMORED' el hallazgo "
        "esta resuelto"
    )
    assert claim.review_required is False, (
        "consecuencia del hallazgo anterior: el hecho no verificado sale "
        "SIN marca de revision"
    )


def test_afirma_que_en_el_extractor_determinista_tampoco_se_degrada():
    """Mismo hallazgo con otro REPORT_VERB regular (-AR, generado por
    paradigma) para descartar que sea un caso aislado de 'decir'."""
    texto = "Un cronista afirma que Elara lidera la Orden del Alba."
    verdict = analyze_raw_text(texto)
    assert verdict.factivity.factivity_class.value == "RUMOR"

    ctx, _ = single_context("ep:gate6-b2-adv-02", texto)
    claims = asserted(DeterministicExtractor().extract(ctx))
    assert claims
    assert claims[0].epistemic_status_hint == "ASSERTED"
    assert claims[0].review_required is False


def test_se_dice_que_si_se_degrada_en_el_extractor_determinista():
    """Control: el mecanismo VIEJO (lista `EPISTEMIC_CUES` local de
    `deterministic.py`, anterior a B0/B1) si funciona para 'se dice que'.
    Esto acota el hallazgo: no es que el extractor determinista ignore TODA
    epistemicidad, es que ignora especificamente el operador NUEVO de
    discurso reportado por verbo (B1/B2)."""
    texto = "Se dice que Elara lidera la Orden del Alba."
    ctx, _ = single_context("ep:gate6-b2-adv-03", texto)
    claims = asserted(DeterministicExtractor().extract(ctx))
    assert claims
    assert claims[0].epistemic_status_hint == "RUMORED"
    assert claims[0].review_required is True


# --------------------------------------------------------------------------
# 2. (P1) classify_negation: el requisito de conector "que"/"si" deja fuera
#    a las demas interrogativas indirectas, que antes de B2 SI eran
#    SCOPE_AMBIGUOUS.
# --------------------------------------------------------------------------
INDIRECT_INTERROGATIVES_NOT_QUE_NOR_SI = [
    ("cuando", "El archivero no recuerda cuando llego el mercader al Sindicato Vitivinicola."),
    ("donde", "El archivero no sabe donde escondio el mercader el documento del Sindicato."),
    ("quien", "El archivero no recuerda quien firmo el documento del Sindicato Vitivinicola."),
    ("como", "El archivero no sabe como llego el mercader al Sindicato Vitivinicola."),
    ("por que", "El archivero no sabe por que llego tarde el mercader al Sindicato."),
    ("cual", "El archivero no sabe cual documento firmo el mercader del Sindicato."),
]


def test_interrogativas_indirectas_distintas_de_que_y_si_caen_a_negacion_directa():
    """HALLAZGO P1: 'no sabe/recuerda <wh> ...' es, semanticamente, el mismo
    alcance epistemico que 'no sabe si ...' (que B2 SI cubre) -- ninguna de
    estas frases dice que el hecho reportado sea falso, dicen que el sujeto
    ignora un dato sobre el. El requisito nuevo de B2 ("que" o "si"
    inmediato) no reconoce ningun otro pronombre/adverbio interrogativo, asi
    que la clasificacion cae a NEGATED_FACT (negacion directa) en vez de
    SCOPE_AMBIGUOUS. Se documenta el comportamiento ACTUAL."""
    for _etiqueta, texto in INDIRECT_INTERROGATIVES_NOT_QUE_NOR_SI:
        verdict = analyze_raw_text(texto)
        assert verdict.factivity.factivity_class.value == "NEGATED_FACT", (
            f"comportamiento actual esperado NEGATED_FACT para {texto!r}, "
            f"obtenido {verdict.factivity.factivity_class.value!r} -- si "
            "esto cambia a UNKNOWN/SCOPE_AMBIGUOUS el hallazgo P1 esta "
            "resuelto y este test debe actualizarse"
        )
        assert verdict.negation_kind == "SIMPLE"


def test_no_sabe_si_si_sigue_cubierto_por_la_correccion_de_b2():
    """Control directo de contraste con la lista de arriba: el UNICO
    conector no-"que" que B2 anadio ("si") si funciona. La diferencia de
    comportamiento entre esta frase y las de
    `INDIRECT_INTERROGATIVES_NOT_QUE_NOR_SI` es exactamente el hallazgo: la
    correccion es ad hoc a los dos casos de corpus (gate4 exigio anadir
    'si'), no una regla general de interrogativa indirecta."""
    verdict = analyze_raw_text(
        "El archivero no sabe si el mercader llego al Sindicato Vitivinicola."
    )
    assert verdict.negation_kind == "SCOPE_AMBIGUOUS"


def test_antes_de_b2_estas_mismas_interrogativas_si_eran_scope_ambiguous():
    """Prueba negativa de regresion, corrida contra el propio arnes: NO se
    reimplementa la logica de B1 aqui (seria autoria propensa a sesgo). Se
    deja constancia de que este archivo depende de la comparacion externa ya
    hecha por el agente (commit bb4a46a, antes de la correccion de B2) para
    afirmar que hubo un cambio de comportamiento, no solo que el actual sea
    'raro'. Este test solo fija el ANTES-DESPUES documentado: aqui, el
    DESPUES (comportamiento de esta rama)."""
    for _etiqueta, texto in INDIRECT_INTERROGATIVES_NOT_QUE_NOR_SI[:1]:
        verdict = analyze_raw_text(texto)
        # DESPUES de B2 (esta rama): NEGATED_FACT.
        assert verdict.factivity.factivity_class.value == "NEGATED_FACT"
        # ANTES de B2 (bloque B1, commit bb4a46a), medido manualmente por el
        # agente de tests fuera de este arnes: la misma frase clasificaba
        # UNKNOWN/SCOPE_AMBIGUOUS. Ver informe del agente de tests para el
        # detalle reproducible (checkout de bb4a46a + `analyze_raw_text`).
