# -*- coding: utf-8 -*-
"""Suite del Bloque 5: RUMORES y ESTADO EPISTEMICO (`relation-epistemic/v1`).

Cubre la clasificacion epistemica determinista de `relations.epistemic` y la
guardia de seguridad `is_epistemically_safe`, mas MUTATION CHECKS bloqueantes que
codifican la REGLA DURA del bloque:

  * Un RUMOR **nunca** se convierte en HECHO (status != ASSERTED).
  * El ESTADO EPISTEMICO **no se pierde**: un candidato no-asertado nunca es
    afirmable (`RelationCandidate.is_affirmative()` es False).

Los tests son puros: sin red, sin disco, sin mocks. Las comprobaciones de mutacion
(`@pytest.mark.mutation`) aseveran sobre el modulo importado de verdad y sobre el
contrato real `RelationCandidate`, de modo que MATAN al mutante correspondiente.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from relations.epistemic import (  # noqa: E402
    EPISTEMIC_VERSION,
    EPISTEMIC_NUANCES,
    classify_epistemic,
    is_epistemically_safe,
)
from relations.contracts import (  # noqa: E402
    EpistemicStatus,
    RelationCandidate,
    Direction,
    ExtractionMethod,
)


# ---------------------------------------------------------------------------
# Corpus de textos por matiz (reutilizado por tests normales y de mutacion).
# ---------------------------------------------------------------------------
RUMOR_TEXTS = ("se rumorea que es aliado", "dicen que gobierna", "se comenta que gobierna")
INDIRECT_TEXTS = ("segun cuentan, fundo la casa", "de acuerdo con las cronicas")
BELIEF_TEXTS = ("cree que gobierna", "opina que gobierna", "sospecha que se alio")
DOUBT_TEXTS = ("quiza se alio", "tal vez es miembro")
POSSIBILITY_TEXTS = ("podria ser miembro", "es posible que gobierne")
HYPOTHESIS_TEXTS = ("si cae la ciudad, huira", "en caso de guerra", "hipoteticamente lidera")
CONTRADICTION_TEXTS = (
    "otros afirman lo contrario",
    "se contradice con la cronica",
    "esa version esta en disputa",
)
INTENTION_TEXTS = ("planea aliarse", "pretende gobernar", "proyecta una alianza")
ASSERTED_TEXTS = ("es miembro del clan", "goberno el reino")

# Todos los textos cuyo estado NUNCA puede ser ASSERTED (regla dura del bloque).
RUMORED_ALL = RUMOR_TEXTS + INDIRECT_TEXTS + BELIEF_TEXTS
HYPOTHETICAL_ALL = DOUBT_TEXTS + POSSIBILITY_TEXTS + HYPOTHESIS_TEXTS + CONTRADICTION_TEXTS
NON_ASSERTED_ALL = RUMORED_ALL + HYPOTHETICAL_ALL + INTENTION_TEXTS


# ---------------------------------------------------------------------------
# 1. RUMOR -> RUMORED / rumor
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", RUMOR_TEXTS)
def test_rumor_is_rumored(text):
    r = classify_epistemic(text)
    assert r.status == EpistemicStatus.RUMORED
    assert r.nuance == "rumor"
    assert not r.is_asserted
    assert r.has_epistemic_cue is True
    assert r.cues  # hay evidencia lexica


# ---------------------------------------------------------------------------
# 2. INDIRECTO (segunda mano) -> RUMORED / indirect
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", INDIRECT_TEXTS)
def test_indirect_is_rumored(text):
    r = classify_epistemic(text)
    assert r.status == EpistemicStatus.RUMORED
    assert r.nuance == "indirect"
    assert not r.is_asserted


# ---------------------------------------------------------------------------
# 3. CREENCIA (opinion de un sujeto) -> RUMORED (NO ASSERTED) / belief
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", BELIEF_TEXTS)
def test_belief_is_rumored_not_asserted(text):
    r = classify_epistemic(text)
    assert r.status == EpistemicStatus.RUMORED
    assert r.status != EpistemicStatus.ASSERTED
    assert r.nuance == "belief"


# ---------------------------------------------------------------------------
# 4. DUDA / POSIBILIDAD -> HYPOTHETICAL (doubt/possibility)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", DOUBT_TEXTS)
def test_doubt_is_hypothetical(text):
    r = classify_epistemic(text)
    assert r.status == EpistemicStatus.HYPOTHETICAL
    assert r.nuance == "doubt"


@pytest.mark.parametrize("text", POSSIBILITY_TEXTS)
def test_possibility_is_hypothetical(text):
    r = classify_epistemic(text)
    assert r.status == EpistemicStatus.HYPOTHETICAL
    assert r.nuance == "possibility"


# ---------------------------------------------------------------------------
# 5. HIPOTESIS / CONDICIONAL -> HYPOTHETICAL / hypothesis
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", HYPOTHESIS_TEXTS)
def test_hypothesis_is_hypothetical(text):
    r = classify_epistemic(text)
    assert r.status == EpistemicStatus.HYPOTHETICAL
    assert r.nuance == "hypothesis"


# ---------------------------------------------------------------------------
# 6. CONTRADICCION -> HYPOTHETICAL / contradiction (DEGRADADA, nunca ASSERTED)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", CONTRADICTION_TEXTS)
def test_contradiction_is_degraded_to_hypothetical(text):
    r = classify_epistemic(text)
    assert r.status == EpistemicStatus.HYPOTHETICAL
    assert r.nuance == "contradiction"
    # nunca se afirma algo en disputa
    assert r.status != EpistemicStatus.ASSERTED


# ---------------------------------------------------------------------------
# 7. INTENCION / PLAN -> INTENDED / intention
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", INTENTION_TEXTS)
def test_intention_is_intended(text):
    r = classify_epistemic(text)
    assert r.status == EpistemicStatus.INTENDED
    assert r.nuance == "intention"
    assert not r.is_asserted


# ---------------------------------------------------------------------------
# 8. NARRADOR (asercion llana) vs PERSONAJE (atribucion)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", ASSERTED_TEXTS)
def test_plain_narrator_assertion_is_asserted(text):
    """Una afirmacion LLANA del narrador, sin ninguna marca epistemica, es un
    HECHO (ASSERTED)."""
    r = classify_epistemic(text)
    assert r.status == EpistemicStatus.ASSERTED
    assert r.nuance == "assertion"
    assert r.is_asserted is True
    assert r.has_epistemic_cue is False
    assert r.cues == ()


def test_attribution_degrades_a_plain_fact():
    """Pero CUALQUIER atribucion ("cree que" / "segun X") sobre el mismo hecho lo
    degrada: el narrador afirma, el personaje/tercero solo atribuye."""
    hecho = "gobierna el reino"
    assert classify_epistemic(hecho).status == EpistemicStatus.ASSERTED
    # atribucion por creencia
    assert classify_epistemic("cree que " + hecho).status == EpistemicStatus.RUMORED
    # atribucion indirecta a una fuente
    assert classify_epistemic("segun las cronicas " + hecho).status == EpistemicStatus.RUMORED


# ---------------------------------------------------------------------------
# 9. is_asserted / has_epistemic_cue coherentes con status/nuance
# ---------------------------------------------------------------------------
def test_is_asserted_and_has_cue_are_coherent():
    # asertado: is_asserted True, sin cue epistemico
    a = classify_epistemic("es miembro del clan")
    assert a.is_asserted is True
    assert a.has_epistemic_cue is False
    assert (a.nuance == "assertion") == (not a.has_epistemic_cue)

    # no asertado: is_asserted False, con cue epistemico
    for text in NON_ASSERTED_ALL:
        r = classify_epistemic(text)
        assert r.is_asserted is False
        assert r.has_epistemic_cue is True
        # invariante: is_asserted <=> status ASSERTED
        assert r.is_asserted == (r.status == EpistemicStatus.ASSERTED)
        # invariante: has_epistemic_cue <=> nuance != assertion
        assert r.has_epistemic_cue == (r.nuance != "assertion")


def test_nuance_pertenece_al_vocabulario():
    for text in NON_ASSERTED_ALL + ASSERTED_TEXTS:
        assert classify_epistemic(text).nuance in EPISTEMIC_NUANCES


# ---------------------------------------------------------------------------
# 10. VERSION / TRAZABILIDAD y DETERMINISMO
# ---------------------------------------------------------------------------
def test_version_is_stamped_in_classification():
    r = classify_epistemic("dicen que gobierna")
    assert r.epistemic_version == EPISTEMIC_VERSION
    assert EPISTEMIC_VERSION == "relation-epistemic-1.0.0"


def test_determinism_same_input_same_output():
    for text in NON_ASSERTED_ALL + ASSERTED_TEXTS:
        first = classify_epistemic(text)
        second = classify_epistemic(text)
        assert first == second
        assert first.status == second.status
        assert first.nuance == second.nuance
        assert first.cues == second.cues


# ---------------------------------------------------------------------------
# 11. FRONTERA DE PALABRA: "si" dentro de "casino"/"asignar" NO dispara hipotesis
# ---------------------------------------------------------------------------
def test_word_boundary_no_false_positive_por_subcadena():
    """El cue "si" (hipotesis) NO debe casar como subcadena de "casino" ni de
    "asignar"; un texto neutro con esas palabras es ASSERTED."""
    r = classify_epistemic("el casino esta en la ciudad y hay que asignar tropas")
    assert r.status == EpistemicStatus.ASSERTED
    assert r.nuance == "assertion"
    assert r.cues == ()


# ===========================================================================
# MUTATION CHECKS BLOQUEANTES
# Aseveran sobre el modulo/contrato reales; matan al mutante correspondiente.
# ===========================================================================
@pytest.mark.mutation
@pytest.mark.parametrize("text", RUMORED_ALL)
def test_mut_rumor_nunca_es_hecho(text):
    """REGLA DURA: rumor/indirecto/creencia -> NUNCA ASSERTED, y la guardia lo
    declara seguro. Si el clasificador devolviera ASSERTED, esto FALLA."""
    r = classify_epistemic(text)
    assert r.status != EpistemicStatus.ASSERTED
    assert is_epistemically_safe(r.status, True) is True


@pytest.mark.mutation
@pytest.mark.parametrize("text", CONTRADICTION_TEXTS)
def test_mut_contradiccion_no_asertada(text):
    r = classify_epistemic(text)
    assert r.status != EpistemicStatus.ASSERTED
    assert r.status == EpistemicStatus.HYPOTHETICAL


@pytest.mark.mutation
@pytest.mark.parametrize("text", HYPOTHETICAL_ALL)
def test_mut_hipotesis_no_es_hecho(text):
    """Hipotesis / duda / posibilidad / contradiccion -> HYPOTHETICAL, jamas
    ASSERTED."""
    r = classify_epistemic(text)
    assert r.status == EpistemicStatus.HYPOTHETICAL
    assert r.status != EpistemicStatus.ASSERTED


def _candidate(**overrides) -> RelationCandidate:
    """Construye un RelationCandidate REAL y valido; overrides ajustan campos."""
    data = dict(
        subject_id="ent:akodo",
        subject_type="Character",
        predicate="MEMBER_OF",
        object_id="ent:clan_leon",
        object_type="Faction",
        direction=Direction.SUBJECT_TO_OBJECT,
        confidence=0.82,
        evidence_text="Akodo pertenece al Clan Leon",
        evidence_start=0,
        evidence_end=28,
        source_id="src:doc1",
        source_page=12,
        source_segment="seg:0007",
        extraction_method=ExtractionMethod.LLM_LOCAL,
        model="qwen2.5@7b",
        negated=False,
        temporal_scope=None,
        epistemic_status=EpistemicStatus.ASSERTED,
        workspace="l5r",
        validation_flags=[],
    )
    data.update(overrides)
    return RelationCandidate(**data).validate()


@pytest.mark.mutation
def test_mut_estado_no_se_pierde():
    """El estado epistemico NO se pierde: un candidato RUMORED (aunque no negado)
    NO es afirmable. Control no trivial: ASSERTED + negated=False SI lo es."""
    rumored = _candidate(epistemic_status=EpistemicStatus.RUMORED, negated=False)
    assert rumored.is_affirmative() is False

    asserted = _candidate(epistemic_status=EpistemicStatus.ASSERTED, negated=False)
    assert asserted.is_affirmative() is True


@pytest.mark.mutation
def test_mut_guardia_dura_rumored_no_recomendado():
    """Cualquier estado NO-asertivo bloquea la afirmacion, se recorren los tres."""
    for status in (
        EpistemicStatus.RUMORED,
        EpistemicStatus.HYPOTHETICAL,
        EpistemicStatus.INTENDED,
    ):
        cand = _candidate(epistemic_status=status, negated=False)
        assert cand.is_affirmative() is False


@pytest.mark.mutation
def test_mut_is_epistemically_safe():
    """La guardia debe marcar INSEGURO exactamente el caso peligroso: hay cue
    epistemico pero el status es ASSERTED (un rumor convertido en hecho)."""
    # caso peligroso -> False
    assert is_epistemically_safe(EpistemicStatus.ASSERTED, True) is False
    # rumor con cue -> seguro (estado preservado)
    assert is_epistemically_safe(EpistemicStatus.RUMORED, True) is True
    # asercion sin cue -> seguro
    assert is_epistemically_safe(EpistemicStatus.ASSERTED, False) is True
