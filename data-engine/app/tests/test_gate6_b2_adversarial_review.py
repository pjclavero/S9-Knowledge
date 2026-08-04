# -*- coding: utf-8 -*-
"""Bateria adversarial del AGENTE-DE-TESTS (revision independiente del
bloque B2, puerta 6, CIERRE): ataca las dos correcciones que B2 dice haber
entregado -- la guarda de homografo de `_reported_speech_cue` y el requisito
de conector "que"/"si" de `classify_negation` -- con frases propias, fuera de
ambos corpus (dev y generalizacion) y sin n-gramas >=3 compartidos con ellos
ni con `tests/test_gate6_b2_bugs.py`.

Los dos hallazgos que este archivo levanto quedaron CERRADOS por el rework
del bloque B2 (mismo commit que este cambio). Los tests siguen aqui, con las
mismas frases, invertidos para verificar el comportamiento CORREGIDO: son la
prueba de no-regresion de ambas correcciones, y el texto de cada uno conserva
el relato del hallazgo original para que no se pierda por que existen.

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
   El mecanismo SI funcionaba para el extractor de PROVEEDOR/LLM
   (`extraction/payload.py`, que si llama a `analyze_context` y lee
   `verdict.hint`), asi que el hallazgo era especifico del carril
   determinista.

   CERRADO en el rework de B2: `deterministic.py` reutiliza ahora el
   `verdict` que ya calculaba para las ramas de aborto y aplica la misma
   degradacion que `payload.py` (`if verdict.hint != "ASSERTED" and hint ==
   "ASSERTED"`). "El heraldo dijo que ..." sale RUMORED con
   `review_required=True`.

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
   interrogativas indirectas.

   CERRADO en el rework de B2: `classify_negation` reconoce ahora la clase
   gramatical CERRADA completa (`cues.INDIRECT_QUESTION_CONNECTORS` +
   `INDIRECT_QUESTION_CONNECTOR_PAIRS`), no solo los dos conectores que los
   corpus exigieron. Las mismas frases vuelven a leerse como
   SCOPE_AMBIGUOUS, y los casos con objeto directo ("no reconocio el
   terreno") siguen siendo NEGATED_FACT.
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
def test_dijo_que_en_el_extractor_determinista_se_degrada_a_rumor():
    """CIERRE del hallazgo P0. Las dos capas deben coincidir: el
    clasificador (`analyze_raw_text`, lo que mide el arnes de la puerta 6)
    y el extractor de PRODUCCION (`DeterministicExtractor`). Antes del
    rework de B2 la segunda capa ignoraba a la primera y escribia el reporte
    de un tercero como hecho del mundo sin marca de revision."""
    texto = "El heraldo dijo que Elara lidera la Orden del Alba."

    # A nivel de clasificador (lo que mide el arnes de la puerta 6): RUMOR.
    verdict = analyze_raw_text(texto)
    assert verdict.factivity.factivity_class.value == "RUMOR"

    # A nivel del extractor determinista de produccion: la MISMA lectura.
    ctx, _ = single_context("ep:gate6-b2-adv-01", texto)
    claims = asserted(DeterministicExtractor().extract(ctx))
    assert claims, "se esperaba al menos una propuesta de hecho"
    claim = claims[0]
    assert claim.epistemic_status_hint == "RUMORED", (
        "el extractor determinista debe degradar 'dijo que' a RUMORED "
        "reutilizando el verdict de `analyze_context` (rework B2)"
    )
    assert claim.review_required is True, (
        "un hecho atribuido a un tercero nunca puede salir sin marca de "
        "revision"
    )
    assert "dijo que" in claim.epistemic_cues, (
        "la marca que provoco la degradacion debe quedar en la traza"
    )


def test_afirma_que_en_el_extractor_determinista_tambien_se_degrada():
    """Mismo cierre con otro REPORT_VERB regular (-AR, generado por
    paradigma) para comprobar que la conexion no depende del lema 'decir'
    ni de ninguna forma declarada a mano."""
    texto = "Un cronista afirma que Elara lidera la Orden del Alba."
    verdict = analyze_raw_text(texto)
    assert verdict.factivity.factivity_class.value == "RUMOR"

    ctx, _ = single_context("ep:gate6-b2-adv-02", texto)
    claims = asserted(DeterministicExtractor().extract(ctx))
    assert claims
    assert claims[0].epistemic_status_hint == "RUMORED"
    assert claims[0].review_required is True


def test_se_dice_que_si_se_degrada_en_el_extractor_determinista():
    """Control de no-regresion: el mecanismo VIEJO (lista `EPISTEMIC_CUES`
    local de `deterministic.py`, anterior a B0/B1) sigue funcionando para
    'se dice que'. La conexion nueva COMPLEMENTA esa lista (solo degrada
    cuando la local no vio nada), no la sustituye."""
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


def test_interrogativas_indirectas_distintas_de_que_y_si_son_alcance_ambiguo():
    """CIERRE del hallazgo P1: 'no sabe/recuerda <wh> ...' es, semanticamente,
    el mismo alcance epistemico que 'no sabe si ...' -- ninguna de estas
    frases dice que el hecho reportado sea falso, dicen que el sujeto ignora
    un dato sobre el. Tras el rework de B2 la clase de conectores es la clase
    gramatical cerrada completa, no los dos conectores que los corpus
    exigieron, y las seis frases vuelven a ser SCOPE_AMBIGUOUS."""
    for _etiqueta, texto in INDIRECT_INTERROGATIVES_NOT_QUE_NOR_SI:
        verdict = analyze_raw_text(texto)
        assert verdict.negation_kind == "SCOPE_AMBIGUOUS", (
            f"se esperaba SCOPE_AMBIGUOUS para {texto!r}, obtenido "
            f"{verdict.negation_kind!r}"
        )
        assert verdict.factivity.factivity_class.value == "UNKNOWN"


def test_no_sabe_si_si_sigue_cubierto_por_la_correccion_de_b2():
    """Control de no-regresion: el conector "si" (el unico no-"que" que B2
    cubria antes del rework) sigue funcionando igual. Tras ampliar la clase,
    esta frase y las de `INDIRECT_INTERROGATIVES_NOT_QUE_NOR_SI` se comportan
    ya de la MISMA manera; esa igualdad es el cierre del hallazgo."""
    verdict = analyze_raw_text(
        "El archivero no sabe si el mercader llego al Sindicato Vitivinicola."
    )
    assert verdict.negation_kind == "SCOPE_AMBIGUOUS"


def test_la_ampliacion_no_arrastra_al_objeto_directo():
    """Guarda del limite de la correccion: ampliar la clase de conectores no
    puede reabrir el bug que B2 cerro. Un `SCOPE_VERB` negado con objeto
    DIRECTO (sin ningun conector de la clase) sigue siendo negacion directa.
    Sin esta guarda, "ampliar conectores" podria degenerar en "cualquier cosa
    despues del verbo vale", que es la adyacencia simple de B1."""
    directos = [
        "La patrulla no reconocio el terreno antes del ataque al fuerte.",
        "El explorador no sabia el camino hacia el campamento del norte.",
        "El guardia no acepto el paquete del mensajero del gremio.",
    ]
    for texto in directos:
        verdict = analyze_raw_text(texto)
        assert verdict.negation_kind == "SIMPLE", texto
        assert verdict.factivity.factivity_class.value == "NEGATED_FACT", texto
