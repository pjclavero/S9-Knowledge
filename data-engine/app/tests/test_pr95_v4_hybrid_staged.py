# -*- coding: utf-8 -*-
"""PR#95 V4 -- Motor hibrido por etapas: compatibilidad, ablation y seguridad.

Estos tests FALLAN de verdad si se rompe alguna de las garantias duras del motor
hibrido (`relations/hybrid/`):

  * compatibilidad: con `hybrid_stages=None` la salida es IDENTICA a la base
    (mismo `result_hash`); con `hybrid_stages={}` el CONTENIDO de candidatos
    (results/documents/summary) es identico a la base.
  * ablation por etapa: activar/desactivar cada etapa tiene el efecto esperado.
  * anti-explosion: `hybrid_top_k` ACOTA el numero de candidatos.
  * inter-frase: `hybrid_cross_sentence` habilita pares a mas de una frase.
  * seguridad: desactivar temporal/epistemica degrada RUMORED->ASSERTED (regresion
    detectable; la etapa activada preserva "un rumor nunca es un hecho").
  * fallback stdlib: sin parser fuerte (spaCy/stanza) se usa el heuristico stdlib.
  * separacion razonamiento/evidencia: la cita literal no se mezcla con el "por que".
"""
from __future__ import annotations

import time

import pytest

from relations.contracts import Direction, EpistemicStatus, RelationCandidate
from relations.hybrid import EvidenceBundle, RelationHypothesis, SegmentReference
from relations.hybrid import engine as hyb_engine
from relations.hybrid import stages as hyb_stages
from relations.pipeline import PipelineConfig, PipelineError, run_pipeline


# ---------------------------------------------------------------------------
# Helpers de payload
# ---------------------------------------------------------------------------
def _seg(text, entities, seg_id="s1", ws="ws1", src="doc1"):
    return {"segment_id": seg_id, "source_id": src, "workspace": ws, "text": text,
            "entities": entities}


def _payload(text, entities, ws="ws1", src="doc1"):
    return {"workspace": ws, "source_id": src, "segments": [_seg(text, entities, ws=ws, src=src)]}


def _ent(eid, etype, start, length):
    return {"id": eid, "type": etype, "start": start, "end": start + length}


def _membership_payload():
    # "Se dice que Bob es miembro del Gremio." -> rumor cue + MEMBER_OF
    txt = "Se dice que Bob es miembro del Gremio."
    return _payload(txt, [
        {"id": "Bob", "type": "Character", "start": txt.index("Bob"), "end": txt.index("Bob") + 3},
        {"id": "Gremio", "type": "Faction", "start": txt.index("Gremio"), "end": txt.index("Gremio") + 6},
    ])


def _two_relations_payload():
    txt = "Alice is a member of the Guild. Bob owns a mysterious Sword."
    return _payload(txt, [
        {"id": "Alice", "type": "Character", "start": 0, "end": 5},
        {"id": "Guild", "type": "Faction", "start": txt.index("Guild"), "end": txt.index("Guild") + 5},
        {"id": "Bob", "type": "Character", "start": txt.index("Bob"), "end": txt.index("Bob") + 3},
        {"id": "Sword", "type": "Object", "start": txt.index("Sword"), "end": txt.index("Sword") + 5},
    ])


def _predicates(out):
    return sorted({r["candidate"]["predicate"] for r in out["results"]})


def _spans(out):
    return [(r["candidate"]["evidence_start"], r["candidate"]["evidence_end"]) for r in out["results"]]


# ===========================================================================
# COMPATIBILIDAD
# ===========================================================================
def test_default_none_is_classic_and_identical_hash():
    """`hybrid_stages=None` (default): salida byte-identica a la base."""
    p = _two_relations_payload()
    base = run_pipeline(p, config=PipelineConfig())
    default = run_pipeline(p, config=PipelineConfig(hybrid_stages=None))
    assert base["result_hash"] == default["result_hash"]
    # La config canonica NO debe contener ninguna clave hibrida en default.
    assert not any(k.startswith("hybrid_") for k in base["config"])


def test_empty_dict_reproduces_base_candidates():
    """`hybrid_stages={}` (motor activo, etapas default): candidatos identicos a base."""
    p = _two_relations_payload()
    base = run_pipeline(p, config=PipelineConfig())
    hyb = run_pipeline(p, config=PipelineConfig(hybrid_stages={}))
    assert base["results"] == hyb["results"]
    assert base["documents"] == hyb["documents"]
    assert base["summary"] == hyb["summary"]


def test_hybrid_is_deterministic():
    p = _two_relations_payload()
    cfg = PipelineConfig(hybrid_stages={}, hybrid_top_k=2)
    a = run_pipeline(p, config=cfg)
    b = run_pipeline(p, config=cfg)
    assert a["result_hash"] == b["result_hash"]


def test_contract_stays_20_fields_under_hybrid():
    p = _two_relations_payload()
    hyb = run_pipeline(p, config=PipelineConfig(hybrid_stages={}))
    assert hyb["results"], "debe haber al menos un candidato"
    for r in hyb["results"]:
        assert len(r["candidate"]) == 20


# ===========================================================================
# ABLATION -- una etapa cada vez
# ===========================================================================
def test_ablation_predicate_direction_off_generic():
    """Etapa predicado OFF -> predicados genericos (RELATED_TO)."""
    p = _two_relations_payload()
    base = run_pipeline(p, config=PipelineConfig(hybrid_stages={}))
    off = run_pipeline(p, config=PipelineConfig(hybrid_stages={"predicate_direction": False}))
    assert _predicates(base) == ["MEMBER_OF", "OWNS"]
    assert _predicates(off) == ["RELATED_TO"]


def test_predicate_direction_on_sets_specific_direction():
    """Etapa predicado ON: MEMBER_OF con direccion no-UNDIRECTED (SUBJECT_TO_OBJECT)."""
    p = _membership_payload()
    on = run_pipeline(p, config=PipelineConfig(hybrid_stages={}))
    cand = on["results"][0]["candidate"]
    assert cand["predicate"] == "MEMBER_OF"
    assert cand["direction"] == Direction.SUBJECT_TO_OBJECT.value
    off = run_pipeline(p, config=PipelineConfig(hybrid_stages={"predicate_direction": False}))
    assert off["results"][0]["candidate"]["direction"] == Direction.UNDIRECTED.value


def test_ablation_temporal_epistemic_off_is_security_regression():
    """SEGURIDAD: etapa temporal/epistemica OFF convierte RUMORED en ASSERTED."""
    p = _membership_payload()
    on = run_pipeline(p, config=PipelineConfig(hybrid_stages={}))
    off = run_pipeline(p, config=PipelineConfig(hybrid_stages={"temporal_epistemic": False}))
    assert on["results"][0]["candidate"]["epistemic_status"] == EpistemicStatus.RUMORED.value
    # Regresion detectable: sin la etapa, el rumor se afirma como hecho.
    assert off["results"][0]["candidate"]["epistemic_status"] == EpistemicStatus.ASSERTED.value


def test_ablation_evidence_off_degrades_span():
    """Etapa evidencia OFF -> span degradado (solo sujeto), no cubre el objeto."""
    p = _membership_payload()
    on = run_pipeline(p, config=PipelineConfig(hybrid_stages={}))
    # Con evidencia degradada la verificacion la rechaza; se apaga tambien para observarla.
    off = run_pipeline(p, config=PipelineConfig(hybrid_stages={"evidence": False, "verification": False}))
    on_span = _spans(on)[0]
    off_span = _spans(off)[0]
    assert on_span != off_span
    # El span base cubre ambas menciones; el degradado es estrictamente mas corto.
    assert (off_span[1] - off_span[0]) < (on_span[1] - on_span[0])


def test_ablation_verification_rejects_incomplete_coverage():
    """Etapa verificacion ON rechaza evidencia que no cubre ambas menciones."""
    p = _membership_payload()
    ev_off_ver_on = run_pipeline(p, config=PipelineConfig(hybrid_stages={"evidence": False}))
    ev_off_ver_off = run_pipeline(p, config=PipelineConfig(hybrid_stages={"evidence": False, "verification": False}))
    # Con verificacion ON y evidencia degradada: 0 candidatos (rechazados).
    assert len(ev_off_ver_on["results"]) == 0
    # Con verificacion OFF: el candidato degradado sobrevive.
    assert len(ev_off_ver_off["results"]) == 1


def test_ablation_consensus_off_drops_consensus():
    """Etapa consenso OFF -> el registro no lleva consenso."""
    p = _membership_payload()
    on = run_pipeline(p, config=PipelineConfig(hybrid_stages={}))
    off = run_pipeline(p, config=PipelineConfig(hybrid_stages={"consensus": False}))
    assert on["results"][0]["consensus"] is not None
    assert off["results"][0]["consensus"] is None


# ===========================================================================
# TOP-K / ANTI-EXPLOSION
# ===========================================================================
def test_topk_bounds_candidates():
    """`hybrid_top_k` acota el numero de candidatos por segmento."""
    p = _two_relations_payload()
    full = run_pipeline(p, config=PipelineConfig(hybrid_stages={}))
    capped = run_pipeline(p, config=PipelineConfig(hybrid_stages={}, hybrid_top_k=1))
    assert len(full["results"]) == 2
    assert len(capped["results"]) == 1


def test_candidate_explosion_is_bounded():
    """Muchas menciones: top-k ACOTA candidatos; nunca los multiplica."""
    n = 12
    txt = " ".join(f"E{i}" for i in range(n))  # entidades type-compatibles
    ents = []
    pos = 0
    for i in range(n):
        tok = f"E{i}"
        idx = txt.index(tok, pos)
        ents.append({"id": tok, "type": "Character", "start": idx, "end": idx + len(tok)})
        pos = idx + len(tok)
    p = _payload(txt, ents)
    top_k = 5
    capped = run_pipeline(p, config=PipelineConfig(hybrid_stages={}, hybrid_top_k=top_k))
    # INVARIANTE anti-explosion: nunca mas de top_k candidatos.
    assert len(capped["results"]) <= top_k


def test_topk_keeps_highest_score_first():
    """El recorte top-k conserva las hipotesis de mayor score (ranking)."""
    hyps = [
        RelationHypothesis("p_low", "A", "B", None, None, 0, 1, 2, 3, "RELATED_TO",
                           Direction.UNDIRECTED.value, 0.10),
        RelationHypothesis("p_high", "C", "D", None, None, 0, 1, 2, 3, "RELATED_TO",
                           Direction.UNDIRECTED.value, 0.80),
        RelationHypothesis("p_mid", "E", "F", None, None, 0, 1, 2, 3, "RELATED_TO",
                           Direction.UNDIRECTED.value, 0.50),
    ]
    kept, truncated = hyb_stages.stage_rank_mentions(hyps, 2)
    assert truncated is True
    kept_ids = {h.pair_id for h in kept}
    assert kept_ids == {"p_high", "p_mid"}


def test_rank_identity_when_topk_disabled():
    """top_k<=0: identidad total (mismo orden, sin truncar) -> reproduce base."""
    hyps = [
        RelationHypothesis("p1", "A", "B", None, None, 0, 1, 2, 3, "RELATED_TO",
                           Direction.UNDIRECTED.value, 0.10),
        RelationHypothesis("p2", "C", "D", None, None, 0, 1, 2, 3, "RELATED_TO",
                           Direction.UNDIRECTED.value, 0.90),
    ]
    kept, truncated = hyb_stages.stage_rank_mentions(hyps, 0)
    assert truncated is False
    assert [h.pair_id for h in kept] == ["p1", "p2"]


# ===========================================================================
# INTER-FRASE
# ===========================================================================
def test_inter_sentence_requires_flag():
    """Base (intra-frase) no cruza frases; `hybrid_cross_sentence` si."""
    txt = "Alice vive alli. El Gremio existe aqui."
    p = _payload(txt, [
        {"id": "Alice", "type": "Character", "start": txt.index("Alice"), "end": txt.index("Alice") + 5},
        {"id": "Gremio", "type": "Faction", "start": txt.index("Gremio"), "end": txt.index("Gremio") + 6},
    ])
    base = run_pipeline(p, config=PipelineConfig())
    cross = run_pipeline(p, config=PipelineConfig(hybrid_stages={}, hybrid_cross_sentence=True))
    assert len(base["results"]) == 0            # menciones en frases distintas
    assert len(cross["results"]) >= 1           # la etapa inter-frase las empareja


# ===========================================================================
# RENDIMIENTO (cota holgada, sin colgarse)
# ===========================================================================
def test_performance_bounded():
    """Un segmento con muchas menciones se procesa en tiempo holgado."""
    n = 30
    parts = [f"E{i}" for i in range(n)]
    txt = " ".join(parts)
    ents = []
    pos = 0
    for i in range(n):
        tok = f"E{i}"
        idx = txt.index(tok, pos)
        ents.append({"id": tok, "type": "Character", "start": idx, "end": idx + len(tok)})
        pos = idx + len(tok)
    p = _payload(txt, ents)
    t0 = time.perf_counter()
    out = run_pipeline(p, config=PipelineConfig(hybrid_stages={}, hybrid_top_k=20))
    elapsed = time.perf_counter() - t0
    assert elapsed < 10.0, f"tardo demasiado: {elapsed:.2f}s"
    assert len(out["results"]) <= 20


# ===========================================================================
# FALLBACK STDLIB (sin parser fuerte)
# ===========================================================================
def test_stdlib_fallback_no_strong_parser_required():
    """El pipeline funciona con el analizador heuristico stdlib; no exige spaCy/stanza."""
    import sys
    p = _membership_payload()
    out = run_pipeline(p, config=PipelineConfig(hybrid_stages={}))
    seg_syntax = out["documents"][0]["segments"][0]["syntax"]
    assert seg_syntax["provider"] == "heuristic"
    # No se ha impuesto ninguna dependencia de parser fuerte.
    assert "spacy" not in sys.modules
    assert "stanza" not in sys.modules


# ===========================================================================
# CONFIG FAIL-CLOSED
# ===========================================================================
def test_unknown_stage_flag_fails_closed():
    p = _membership_payload()
    with pytest.raises(PipelineError):
        run_pipeline(p, config=PipelineConfig(hybrid_stages={"no_existe": True}))


def test_non_bool_stage_flag_fails_closed():
    p = _membership_payload()
    with pytest.raises(PipelineError):
        run_pipeline(p, config=PipelineConfig(hybrid_stages={"consensus": "si"}))


def test_resolve_stages_defaults_are_base():
    flags = hyb_engine.resolve_stages({})
    assert all(flags[name] is True for name in hyb_engine.STAGE_DEFAULTS)


# ===========================================================================
# ABSTRACCIONES PURAS -- separacion razonamiento / evidencia
# ===========================================================================
def test_evidence_bundle_separates_literal_from_reasoning():
    seg = "Se dice que Bob es miembro del Gremio."
    hyp = RelationHypothesis(
        "pid", "Bob", "Gremio", "Character", "Faction",
        seg.index("Bob"), seg.index("Bob") + 3, seg.index("Gremio"), seg.index("Gremio") + 6,
        "MEMBER_OF", Direction.SUBJECT_TO_OBJECT.value, 0.5,
    )
    bundle = hyb_stages.stage_evidence(hyp, seg, enabled=True)
    # La cita es literal (verbatim del segmento), SIN el "por que".
    assert bundle.evidence_text == seg[bundle.evidence_start:bundle.evidence_end]
    assert "por que" not in bundle.evidence_text.lower()
    # El razonamiento vive aparte, en reasoning.
    assert bundle.reasoning and all(isinstance(x, str) for x in bundle.reasoning)
    assert bundle.evidence_text not in bundle.reasoning


def test_segment_reference_is_redacted():
    """SegmentReference guarda longitud, no el texto en claro."""
    ref = SegmentReference(segment_id="s1", source_id="d", source_page=None,
                           workspace="ws", text_len=42)
    d = ref.to_dict()
    assert d["text_len"] == 42
    assert "text" not in d  # no vuelca el texto


def test_hypothesis_score_bounds_validated():
    with pytest.raises(ValueError):
        RelationHypothesis("p", "A", "B", None, None, 0, 1, 2, 3,
                           "RELATED_TO", Direction.UNDIRECTED.value, 1.5)


def test_evidence_bundle_rejects_inverted_offsets():
    with pytest.raises(ValueError):
        EvidenceBundle("x", 5, 2, True, True, True)
