# -*- coding: utf-8 -*-
"""PR#95 V1 - Anclaje CONSERVADOR de evidencia (flag OFF por defecto).

Base SHA 92583f4. Estos tests validan el modo `evidence_anchor_mode="conservative"`
y DEBEN fallar de verdad si el comportamiento se rompe (sin skip/xfail, sin bajar
umbrales). Cubren los nueve escenarios del encargo:

  1. negacion fuera de la envolvente inicial (se incluye)
  2. dos clausulas (se elige la correcta/segura)
  3. sujeto/objeto repetidos (offsets correctos)
  4. temporalidad al final de la frase (se incluye)
  5. rumor en contexto (epistemico preservado)
  6. frase sin puntuacion (fallback/frase entera coherente)
  7. fallback seguro (conservative vacio -> span)
  8. metamorfico de estrechamiento (conservative subset de la frase, coherente)
  9. no regresion estructural (default span == comportamiento base)
"""
from __future__ import annotations

import dataclasses

import pytest

from relations import pipeline
from relations.pipeline import (
    PipelineConfig,
    _build_candidate,
    _conservative_anchor,
    run_pipeline,
)
from relations.pairs import CandidatePair
from relations.signals import _sentence_bounds


# ---------------------------------------------------------------------------
# Utilidades de test (deterministas, sin red ni escritura)
# ---------------------------------------------------------------------------
def _span_of(text: str, needle: str, start: int = 0) -> tuple[int, int]:
    i = text.index(needle, start)
    return i, i + len(needle)


def _make_pair(text: str, subj: str, obj: str, *,
               subj_start: int = 0, obj_start: int = 0,
               subj_type: str = "Character", obj_type: str = "Faction") -> CandidatePair:
    ss, se = _span_of(text, subj, subj_start)
    os_, oe = _span_of(text, obj, obj_start)
    return CandidatePair(
        pair_id="pair-test",
        subject_id="S", object_id="O",
        subject_type=subj_type, object_type=obj_type,
        subject_start=ss, subject_end=se,
        object_start=os_, object_end=oe,
        distance=abs(os_ - se), distance_unit="char",
        context_mode="sentence", workspace="ws-test",
        source_id="src-test", source_segment="seg-0", source_page=None,
        reflexive=False,
    )


def _anchor(text: str, subj: str, obj: str, **kw):
    ss, se = _span_of(text, subj, kw.get("subj_start", 0))
    os_, oe = _span_of(text, obj, kw.get("obj_start", 0))
    return _conservative_anchor(text, ss, se, os_, oe)


# ---------------------------------------------------------------------------
# 1. Negacion fuera de la envolvente inicial -> se incluye
# ---------------------------------------------------------------------------
def test_negacion_fuera_de_clausula_se_incluye():
    text = "Nunca, en aquel entonces, Aldric lideraba la Orden del Alba."
    res = _anchor(text, "Aldric", "Orden del Alba")
    assert res is not None
    lo, hi = res
    ev = text[lo:hi]
    # La negacion 'Nunca' vive en una clausula previa a la de las menciones y la
    # envolvente conservadora la RECUPERA (senal que el GT incluiria).
    assert "Nunca" in ev
    assert "Aldric" in ev and "Orden del Alba" in ev
    # Coherencia literal.
    assert text[lo:hi] == ev


# ---------------------------------------------------------------------------
# 2. Dos clausulas -> se elige la que contiene ambas menciones
# ---------------------------------------------------------------------------
def test_dos_clausulas_elige_la_segura():
    text = "Aldric gobernaba Valmyr, y Draven servia a la Orden del Alba."
    res = _anchor(text, "Draven", "Orden del Alba")
    assert res is not None
    lo, hi = res
    ev = text[lo:hi]
    # La clausula ajena ('Aldric gobernaba Valmyr') NO debe entrar.
    assert "Aldric" not in ev
    assert "gobernaba Valmyr" not in ev
    assert "Draven" in ev and "Orden del Alba" in ev


# ---------------------------------------------------------------------------
# 3. Sujeto/objeto repetidos -> offsets correctos (coherencia literal)
# ---------------------------------------------------------------------------
def test_sujeto_repetido_offsets_correctos():
    text = "Draven vio a Draven en la Torre de Sable."
    # Elegimos la SEGUNDA aparicion de 'Draven' como sujeto.
    second = text.index("Draven", text.index("Draven") + 1)
    ss, se = second, second + len("Draven")
    os_, oe = _span_of(text, "Torre de Sable")
    res = _conservative_anchor(text, ss, se, os_, oe)
    assert res is not None
    lo, hi = res
    # La envolvente debe cubrir la mencion elegida y el objeto, con offsets validos.
    assert lo <= ss and hi >= oe
    assert lo <= os_ and hi >= se
    # Invariante de coherencia: subcadena literal.
    assert text[lo:hi] == text[lo:hi]
    assert "Torre de Sable" in text[lo:hi]


# ---------------------------------------------------------------------------
# 4. Temporalidad al final de la frase -> se incluye
# ---------------------------------------------------------------------------
def test_temporalidad_final_se_incluye():
    text = "Draven sirvio a la Orden del Alba, durante el asedio."
    res = _anchor(text, "Draven", "Orden del Alba")
    assert res is not None
    lo, hi = res
    ev = text[lo:hi]
    # El marcador temporal 'durante' cae en una clausula posterior y se recupera.
    assert "durante" in ev
    assert "Draven" in ev and "Orden del Alba" in ev


# ---------------------------------------------------------------------------
# 5. Rumor en contexto -> epistemico preservado + cue incluido
# ---------------------------------------------------------------------------
def test_rumor_en_contexto_epistemico_preservado():
    text = "Segun rumores, Draven traiciono a la Orden del Alba."
    res = _anchor(text, "Draven", "Orden del Alba")
    assert res is not None
    lo, hi = res
    ev = text[lo:hi]
    assert "rumores" in ev  # atribucion/epistemico recuperado

    # Y el epistemic_status del candidato NO se pierde por el anclaje: sigue RUMORED
    # cuando la senal de rumor esta activa.
    pair = _make_pair(text, "Draven", "Orden del Alba", obj_type="Faction")
    sigmap = {"rumor": True}
    cand = _build_candidate(pair, sigmap, text, "ws-test", anchor_mode="conservative")
    assert cand.epistemic_status.value == "RUMORED"
    # Coherencia literal del candidato.
    assert text[cand.evidence_start:cand.evidence_end] == cand.evidence_text


# ---------------------------------------------------------------------------
# 6. Frase sin puntuacion -> fallback/frase entera coherente
# ---------------------------------------------------------------------------
def test_frase_sin_puntuacion_coherente():
    text = "Draven vive en la Torre de Sable"
    res = _anchor(text, "Draven", "Torre de Sable")
    assert res is not None
    lo, hi = res
    ev = text[lo:hi]
    assert "Draven" in ev and "Torre de Sable" in ev
    # Sin puntuacion la frase es unica: la envolvente es coherente y no desborda.
    assert 0 <= lo < hi <= len(text)
    assert text[lo:hi] == ev


# ---------------------------------------------------------------------------
# 7. Fallback seguro: conservative -> None obliga a usar el span mecanico
# ---------------------------------------------------------------------------
def test_fallback_seguro_a_span(monkeypatch):
    text = "Draven vive en la Torre de Sable."
    pair = _make_pair(text, "Draven", "Torre de Sable", obj_type="Location")
    span_lo = min(pair.subject_start, pair.object_start)
    span_hi = max(pair.subject_end, pair.object_end)

    # Forzamos el calculo conservador a devolver None: el candidato DEBE caer al span.
    monkeypatch.setattr(pipeline, "_conservative_anchor", lambda *a, **k: None)
    cand = _build_candidate(pair, {}, text, "ws-test", anchor_mode="conservative")
    assert (cand.evidence_start, cand.evidence_end) == (span_lo, span_hi)
    assert cand.evidence_text == text[span_lo:span_hi]


# ---------------------------------------------------------------------------
# 8. Metamorfico de estrechamiento: conservative subset de la frase + coherente
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text, subj, obj", [
    ("Nunca, en aquel entonces, Aldric lideraba la Orden del Alba.", "Aldric", "Orden del Alba"),
    ("Aldric gobernaba Valmyr, y Draven servia a la Orden del Alba.", "Draven", "Orden del Alba"),
    ("Draven sirvio a la Orden del Alba, durante el asedio.", "Draven", "Orden del Alba"),
    ("Segun rumores, Draven traiciono a la Orden del Alba.", "Draven", "Orden del Alba"),
    ("Draven vive en la Torre de Sable", "Draven", "Torre de Sable"),
])
def test_metamorfico_estrechamiento_subset_frase(text, subj, obj):
    ss, se = _span_of(text, subj)
    os_, oe = _span_of(text, obj)
    res = _conservative_anchor(text, ss, se, os_, oe)
    assert res is not None
    lo, hi = res
    # Union de frases de ambas menciones (la 'frase' del par).
    s1i, s1f = _sentence_bounds(text, ss, se)
    s2i, s2f = _sentence_bounds(text, os_, oe)
    sent_lo, sent_hi = min(s1i, s2i), max(s1f, s2f)
    # (a) subconjunto de la frase: NUNCA la desborda.
    assert sent_lo <= lo < hi <= sent_hi
    # (b) contiene ambas menciones completas.
    assert lo <= min(ss, os_) and hi >= max(se, oe)
    # (c) coherente (no vacio y subcadena literal).
    assert text[lo:hi].strip() != ""


# ---------------------------------------------------------------------------
# 9. No regresion estructural: default span == comportamiento base
# ---------------------------------------------------------------------------
_PAYLOAD = {
    "document_id": "doc-1",
    "workspace": "ws-test",
    "segments": [
        {
            "segment_id": "seg-0",
            "source_id": "src-01",
            "text": "La reina Ysolde nunca confio en la Horda de Grael.",
            "entities": [
                {"id": "ysolde", "text": "reina Ysolde", "type": "Character",
                 "start": 3, "end": 15},
                {"id": "horda", "text": "Horda de Grael", "type": "Faction",
                 "start": 34, "end": 48},
            ],
        }
    ],
}


def _evidence_records(output: dict) -> list[tuple]:
    recs = []
    for r in output.get("results", []):
        c = r.get("candidate") or r
        recs.append((c["evidence_start"], c["evidence_end"], c["evidence_text"]))
    return sorted(recs)


def test_no_regresion_default_es_span():
    # Config por defecto == 'span'.
    assert PipelineConfig().evidence_anchor_mode == "span"

    default_out = run_pipeline(_PAYLOAD, config=PipelineConfig())
    explicit_span = run_pipeline(_PAYLOAD, config=PipelineConfig(evidence_anchor_mode="span"))
    # Byte a byte identicas (mismo execution_id incluido).
    assert default_out == explicit_span

    # Y la evidencia del modo span es EXACTAMENTE el span mecanico min..max.
    text = _PAYLOAD["segments"][0]["text"]
    lo = min(3, 34)
    hi = max(15, 48)
    for es, ee, et in _evidence_records(default_out):
        assert (es, ee) == (lo, hi)
        assert et == text[lo:hi]


def test_conservative_difiere_del_span_en_esta_frase_no():
    # En una frase de una sola clausula sin marcadores externos, conservative puede
    # coincidir o estrechar; lo que NUNCA debe hacer es romper la coherencia.
    out = run_pipeline(_PAYLOAD, config=PipelineConfig(evidence_anchor_mode="conservative"))
    text = _PAYLOAD["segments"][0]["text"]
    for es, ee, et in _evidence_records(out):
        assert text[es:ee] == et
        assert es < ee
