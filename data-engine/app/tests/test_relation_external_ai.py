# -*- coding: utf-8 -*-
"""Tests del evaluador de relaciones con IA externa (Fase A, MODO SOMBRA).

Sin red: el transporte HTTP (_post_chat del proveedor reutilizado) se inyecta
con un doble sintetico. Ningun test escribe en Neo4j ni activa ingesta. Se
verifica ademas que una API key inyectada NUNCA aparece en logs/repr/serializacion.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from external_ai.errors import (
    InvalidResponseError,
    ProviderServerError,
    ProviderTimeoutError,
    RateLimitError,
    SecretLeakError,
)
from external_ai.models import (
    HUMAN_REQUIRED,
    INVALID_RESPONSES,
    MODEL_CONFLICT,
    PARTIAL_CONSENSUS,
    STRONG_CONSENSUS,
)
from external_ai import ShadowModeRequired
from relations.contracts import (
    Direction,
    EpistemicStatus,
    ExtractionMethod,
    RelationCandidate,
)
from relations.external_ai_shadow import (
    RelationExternalConfig,
    RelationExternalEvaluation,
    RelationVolumeError,
    evaluate_relation_external,
    summarize,
)

SEG = "Kakita Asuka es aliada de Bayushi Hisao en el castillo del norte."
FAKE_KEY = "nvapi-FAKEKEY000000000000000000FAKE"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _candidate(cid_sub="ent_asuka", cid_obj="ent_hisao", predicate="ALIADO_DE",
               negated=False, seg=SEG, evidence="Kakita Asuka es aliada de Bayushi Hisao"):
    return RelationCandidate(
        subject_id=cid_sub, subject_type="Character", predicate=predicate,
        object_id=cid_obj, object_type="Character",
        direction=Direction.SUBJECT_TO_OBJECT, confidence=0.8,
        evidence_text=evidence, evidence_start=seg.find(evidence),
        evidence_end=seg.find(evidence) + len(evidence),
        source_id="src1", source_page=1, source_segment=seg,
        extraction_method=ExtractionMethod.HEURISTIC, model=None, negated=negated,
        temporal_scope=None, epistemic_status=EpistemicStatus.ASSERTED, workspace="leyenda",
    ).validate()


def _cid(cand):
    return f"{cand.subject_id}|{cand.predicate}|{cand.object_id}"


def _verdict(cand, *, verdict="confirm", predicate=None, subject_type="Character",
             object_type="Character", negated=False, evidence=None, start=None, end=None,
             confidence=0.9, cid=None):
    seg = cand.source_segment
    ev = evidence if evidence is not None else "Kakita Asuka es aliada de Bayushi Hisao"
    s = seg.find(ev) if start is None else start
    e = (s + len(ev)) if end is None else end
    return {
        "candidate_id": cid if cid is not None else _cid(cand),
        "verdict": verdict,
        "predicate": predicate if predicate is not None else cand.predicate,
        "subject_type": subject_type,
        "object_type": object_type,
        "negated": negated,
        "evidence_text": ev,
        "evidence_start": s,
        "evidence_end": e,
        "confidence": confidence,
        "reason_codes": [],
        "explanation": "x",
    }


class FakeProvider:
    """Doble del proveedor reutilizado: mismo contrato `_post_chat`, sin red."""

    provider_name = "nvidia"

    def __init__(self, content=None, *, raise_exc=None, latency=42):
        self._content = content
        self._raise = raise_exc
        self._latency = latency
        self.calls = 0
        self.last_messages = None

    def _post_chat(self, model, messages):
        self.calls += 1
        self.last_messages = messages
        if self._raise is not None:
            raise self._raise
        content = self._content
        if callable(content):
            content = content(self.calls)
        return ({"choices": [{"message": {"content": content}}],
                 "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}},
                self._latency)


def _content_verdicts(*verdicts):
    return json.dumps({"verdicts": list(verdicts)}, ensure_ascii=False)


def _config(provider, **kw):
    kw.setdefault("model", "meta/llama-3.1-70b-instruct")
    return RelationExternalConfig(provider=provider, **kw)


def _eval_one(cand, content, **cfgkw):
    prov = FakeProvider(content=content)
    res = evaluate_relation_external(cand, config=_config(prov, **cfgkw))
    assert len(res) == 1
    return res[0], prov


# ---------------------------------------------------------------------------
# 1. Respuesta valida -> STRONG_CONSENSUS (pero nunca AUTO_APPROVED)
# ---------------------------------------------------------------------------
def test_valid_response_strong_consensus():
    c = _candidate()
    r, _ = _eval_one(c, _content_verdicts(_verdict(c, verdict="confirm")))
    assert r.state == STRONG_CONSENSUS
    assert r.shadow_recommendation == "confirm"
    assert r.shadow_recommendation != "AUTO_APPROVED"
    assert r.shadow_mode is True
    assert r.model == "meta/llama-3.1-70b-instruct"
    assert r.provider == "nvidia"
    assert r.verdict is not None and r.verdict["candidate_id"] == _cid(c)


# ---------------------------------------------------------------------------
# 2. Respuesta parcial -> PARTIAL_CONSENSUS (refine)
# ---------------------------------------------------------------------------
def test_partial_response():
    c = _candidate()
    v = _verdict(c, verdict="refine")
    r, _ = _eval_one(c, _content_verdicts(v))
    assert r.state == PARTIAL_CONSENSUS
    assert r.shadow_recommendation == "refine"


# ---------------------------------------------------------------------------
# 3. Respuesta conflictiva -> MODEL_CONFLICT (rechazo del modelo)
# ---------------------------------------------------------------------------
def test_conflicting_response_reject():
    c = _candidate()
    v = _verdict(c, verdict="reject")
    r, _ = _eval_one(c, _content_verdicts(v))
    assert r.state == MODEL_CONFLICT
    assert r.shadow_recommendation == "reject"
    assert r.state != "AUTO_APPROVED"


def test_conflict_negation_flip():
    # El modelo confirma pero invierte la negacion -> conflicto de polaridad.
    c = _candidate(negated=False)
    v = _verdict(c, verdict="confirm", negated=True)
    r, _ = _eval_one(c, _content_verdicts(v))
    assert r.state == MODEL_CONFLICT
    assert r.shadow_recommendation == "human"


# ---------------------------------------------------------------------------
# 4. uncertain -> HUMAN_REQUIRED
# ---------------------------------------------------------------------------
def test_uncertain_human_required():
    c = _candidate()
    v = _verdict(c, verdict="uncertain")
    r, _ = _eval_one(c, _content_verdicts(v))
    assert r.state == HUMAN_REQUIRED
    assert r.shadow_recommendation == "human"


# ---------------------------------------------------------------------------
# 5. Respuesta invalida (verdict fuera de catalogo)
# ---------------------------------------------------------------------------
def test_invalid_verdict_value():
    c = _candidate()
    v = _verdict(c, verdict="APPROVED")  # no valido
    r, _ = _eval_one(c, _content_verdicts(v))
    assert r.state == INVALID_RESPONSES
    assert r.shadow_recommendation == "human"
    assert r.validation_errors


# ---------------------------------------------------------------------------
# 6. JSON malformado -> INVALID_RESPONSES (fallo aislado, no propaga)
# ---------------------------------------------------------------------------
def test_malformed_json():
    c = _candidate()
    r, _ = _eval_one(c, "no hay ningun json aqui, solo prosa")
    assert r.state == INVALID_RESPONSES
    assert r.shadow_recommendation == "human"
    assert r.reason_codes == ["provider_error"]  # extract_json lanza InvalidResponseError


# ---------------------------------------------------------------------------
# 7. Evidencia inexistente (rechazada)
# ---------------------------------------------------------------------------
def test_evidence_not_in_segment_rejected():
    c = _candidate()
    v = _verdict(c, evidence="texto totalmente inventado que no aparece", start=0, end=10)
    r, _ = _eval_one(c, _content_verdicts(v))
    assert r.state == INVALID_RESPONSES
    assert any("evidencia_inexistente" in e for e in r.validation_errors)


# ---------------------------------------------------------------------------
# 8. Offsets invalidos (rechazados)
# ---------------------------------------------------------------------------
def test_invalid_offsets_rejected():
    c = _candidate()
    ev = "Kakita Asuka es aliada de Bayushi Hisao"
    v = _verdict(c, evidence=ev, start=0, end=3)  # start/end no casan con la cita
    r, _ = _eval_one(c, _content_verdicts(v))
    assert r.state == INVALID_RESPONSES
    assert any("offsets_invalidos" in e for e in r.validation_errors)


def test_offsets_out_of_range_rejected():
    c = _candidate()
    ev = "Kakita Asuka es aliada de Bayushi Hisao"
    v = _verdict(c, evidence=ev, start=c.source_segment.find(ev), end=99999)
    r, _ = _eval_one(c, _content_verdicts(v))
    assert r.state == INVALID_RESPONSES
    assert any("offsets_invalidos" in e for e in r.validation_errors)


# ---------------------------------------------------------------------------
# 9. Tipo incompatible (rechazado)
# ---------------------------------------------------------------------------
def test_incompatible_type_rejected():
    c = _candidate()
    v = _verdict(c, object_type="Weapon")  # no en ALLOWED_ENTITY_TYPES
    r, _ = _eval_one(c, _content_verdicts(v))
    assert r.state == INVALID_RESPONSES
    assert any("tipo incompatible" in e for e in r.validation_errors)


# ---------------------------------------------------------------------------
# 10. Timeout / 11. HTTP 429 / 12. HTTP 500 -> INVALID_RESPONSES aislado
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("exc", [
    ProviderTimeoutError("timeout"),
    RateLimitError("429"),
    ProviderServerError("500"),
])
def test_provider_errors_isolated(exc):
    c = _candidate()
    prov = FakeProvider(raise_exc=exc)
    res = evaluate_relation_external(c, config=_config(prov))
    assert len(res) == 1
    assert res[0].state == INVALID_RESPONSES
    assert res[0].shadow_recommendation == "human"
    assert res[0].reason_codes == ["provider_error"]
    assert type(exc).__name__ in res[0].validation_errors


# ---------------------------------------------------------------------------
# 13. Fallo AISLADO por candidato: uno falla, el resto continua
# ---------------------------------------------------------------------------
def test_isolated_failure_per_candidate():
    c_ok = _candidate(cid_sub="ent_a", cid_obj="ent_b")
    c_bad = _candidate(cid_sub="ent_c", cid_obj="ent_d")

    def content(call_n):
        # 1er candidato: valido; 2o candidato: JSON roto.
        if call_n == 1:
            return _content_verdicts(_verdict(c_ok, verdict="confirm", cid=_cid(c_ok)))
        return "prosa sin json"

    prov = FakeProvider(content=content)
    res = evaluate_relation_external([c_ok, c_bad], config=_config(prov))
    assert len(res) == 2
    assert res[0].state == STRONG_CONSENSUS
    assert res[1].state == INVALID_RESPONSES  # el fallo del 2o no aborto el 1o
    assert prov.calls == 2


# ---------------------------------------------------------------------------
# 14. Control de volumen
# ---------------------------------------------------------------------------
def test_volume_control():
    c = _candidate()
    prov = FakeProvider(content=_content_verdicts(_verdict(c)))
    with pytest.raises(RelationVolumeError):
        evaluate_relation_external([c, c, c], config=_config(prov, max_candidates=2))


# ---------------------------------------------------------------------------
# 15. Modo sombra OBLIGATORIO
# ---------------------------------------------------------------------------
def test_shadow_mode_required():
    c = _candidate()
    prov = FakeProvider(content=_content_verdicts(_verdict(c)))
    with pytest.raises(ShadowModeRequired):
        evaluate_relation_external(c, config=_config(prov, shadow_mode=False))


# ---------------------------------------------------------------------------
# 16. SECRETO NO EXPUESTO: la API key nunca aparece en salida/repr/serializacion
# ---------------------------------------------------------------------------
def test_secret_not_exposed(monkeypatch, caplog):
    monkeypatch.setenv("S9K_NVIDIA_API_KEY", FAKE_KEY)
    c = _candidate()
    prov = FakeProvider(content=_content_verdicts(_verdict(c, verdict="confirm")))
    cfg = _config(prov)

    import logging
    with caplog.at_level(logging.DEBUG):
        res = evaluate_relation_external(c, config=cfg)

    blob = json.dumps([r.to_dict() for r in res], ensure_ascii=False)
    assert FAKE_KEY not in blob
    assert FAKE_KEY not in repr(res)
    assert FAKE_KEY not in repr(cfg)
    assert FAKE_KEY not in json.dumps(cfg.to_dict(), ensure_ascii=False)
    assert FAKE_KEY not in caplog.text
    # Tampoco 'nvapi-' debe filtrarse en la serializacion del resultado.
    assert "nvapi-" not in blob


# ---------------------------------------------------------------------------
# 17. Guarda de secretos: un secreto en el payload bloquea el envio
# ---------------------------------------------------------------------------
def test_secret_in_payload_blocks_send():
    # Metemos un secreto en el segmento -> assert_no_secrets debe bloquear antes de enviar.
    seg = SEG + " api_key='sk-abcdefghijklmnopqrstuvwxyz012345'"
    c = _candidate(seg=seg)
    prov = FakeProvider(content=_content_verdicts(_verdict(c)))
    res = evaluate_relation_external(c, config=_config(prov))
    assert res[0].state == INVALID_RESPONSES
    assert prov.calls == 0  # nunca se llamo al transporte
    assert "SecretLeakError" in res[0].validation_errors


# ---------------------------------------------------------------------------
# 18. candidate_id que no pertenece -> rechazado
# ---------------------------------------------------------------------------
def test_wrong_candidate_id_rejected():
    c = _candidate()
    v = _verdict(c, cid="otro_id_que_no_toca")
    r, _ = _eval_one(c, _content_verdicts(v))
    assert r.state == INVALID_RESPONSES
    assert any("candidate_id" in e for e in r.validation_errors)


# ---------------------------------------------------------------------------
# 19. Sin red: el doble no toca sockets y produce trazabilidad completa
# ---------------------------------------------------------------------------
def test_no_network_and_traceability():
    c = _candidate()
    r, prov = _eval_one(c, _content_verdicts(_verdict(c)))
    assert prov.last_messages is not None
    assert prov.last_messages[0]["role"] == "system"
    assert r.request_hash and r.response_hash
    assert r.latency_ms == 42
    assert r.prompt_suite_version and r.schema_version


# ---------------------------------------------------------------------------
# 20. summarize agrega sin escribir y jamas reporta auto-aprobados
# ---------------------------------------------------------------------------
def test_summarize_no_auto_approved():
    c = _candidate()
    r, _ = _eval_one(c, _content_verdicts(_verdict(c)))
    s = summarize([r])
    assert s["total"] == 1
    assert s["shadow_mode"] is True
    assert s["auto_approved"] == 0
    assert s["by_state"][STRONG_CONSENSUS] == 1


# ---------------------------------------------------------------------------
# 21. dict de entrada (contrato interno-v1) tambien es aceptado
# ---------------------------------------------------------------------------
def test_dict_candidate_accepted():
    c = _candidate()
    r, _ = _eval_one(c.to_dict(), _content_verdicts(_verdict(c)))
    assert r.state == STRONG_CONSENSUS


# ---------------------------------------------------------------------------
# 22. Cero escrituras: ningun import/uso de neo4j en este flujo
# ---------------------------------------------------------------------------
def test_zero_writes_no_neo4j():
    c = _candidate()
    before = set(sys.modules)
    _eval_one(c, _content_verdicts(_verdict(c)))
    # Evaluar en sombra no debe CARGAR ningun cliente Neo4j nuevo.
    newly_loaded = set(sys.modules) - before
    assert not any("neo4j" in m.lower() for m in newly_loaded)
