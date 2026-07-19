# -*- coding: utf-8 -*-
"""Q — evaluador LLM LOCAL REAL (`relations.local_llm_shadow`).

Cubre:
  * Punto 2: "endpoint local usa default real". Sin endpoint explicito ni
    transporte inyectado, el evaluador FALLA CERRADO (ConfigError) SIN abrir un
    solo socket: no usa infraestructura real por defecto.
  * Punto 4: "JSON invalido aceptado". El evaluador local Y el externo RECHAZAN
    una respuesta que no es JSON valido (state INVALID_RESPONSES).

Todos los transportes/proveedores se inyectan: NO hay red, NO hay Ollama/NVIDIA
reales, NO se escribe nada. Importa los modulos REALES.
"""
from __future__ import annotations

import json
import socket

import pytest

from external_ai.errors import ConfigError
from external_ai.models import (
    CONSENSUS_STATES,
    INVALID_RESPONSES,
    STRONG_CONSENSUS,
)
from relations.local_llm_shadow import (
    LocalLLMConfig,
    RelationEvalInput,
    RECOMMEND_PROPOSE,
    evaluate_relation_local,
)

DOC = "Bayushi Hisao juro lealtad al Clan Escorpion."
EVIDENCE = "juro lealtad al Clan Escorpion"
_START = DOC.find(EVIDENCE)
_END = _START + len(EVIDENCE)


def _input(**over):
    base = dict(
        document=DOC,
        subject_id="Bayushi Hisao",
        object_id="Clan Escorpion",
        template_id="membership",
        subject_type="Character",
        object_type="Faction",
        workspace="leyenda",
    )
    base.update(over)
    return RelationEvalInput(**base)


def _relation(**over):
    rel = {
        "predicate": "MEMBER_OF",
        "direction": "SUBJECT_TO_OBJECT",
        "confidence": 0.9,
        "evidence_text": EVIDENCE,
        "evidence_start": _START,
        "evidence_end": _END,
        "negated": False,
        "temporal_scope": None,
        "epistemic_status": "ASSERTED",
        "subject_type": "Character",
        "object_type": "Faction",
    }
    rel.update(over)
    return rel


def _mock_transport(content, latency=42):
    def transport(messages):
        assert isinstance(messages, list) and messages[0]["role"] == "system"
        return (
            {"choices": [{"message": {"content": content}}],
             "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}},
            latency,
        )
    return transport


def _cfg(transport=None, **over):
    kw = dict(model="ollama/llama3")
    if transport is not None:
        kw["transport"] = transport
    kw.update(over)
    return LocalLLMConfig(**kw)


# ---------------------------------------------------------------------------
# Comportamiento real basico (control): con transporte inyectado, valida.
# ---------------------------------------------------------------------------
def test_valid_response_is_evaluated():
    cfg = _cfg(_mock_transport(json.dumps({"relations": [_relation()]})))
    rec = evaluate_relation_local(_input(), config=cfg)
    assert rec.validation_status == "VALID"
    assert rec.state == STRONG_CONSENSUS
    assert rec.recommendation == RECOMMEND_PROPOSE
    assert rec.state in CONSENSUS_STATES
    assert rec.shadow is True


# ---------------------------------------------------------------------------
# MUTATION 2 (punto 2): sin endpoint ni transporte -> falla cerrado, sin sockets.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_mutation_no_endpoint_fails_closed_without_socket(monkeypatch):
    """El "fallo cerrado" del LLM local es load-bearing.

    Mutacion: si el modulo tuviera un endpoint por defecto hacia infraestructura
    real, `evaluate_relation_local` intentaria abrir red. Aqui `socket.socket`
    esta minado: cualquier apertura ABORTA. El modulo real lanza ConfigError
    ANTES de tocar red. Control: con transporte inyectado SI evalua (la barrera
    solo dispara sin via legitima), demostrando que la regla no rechaza todo.
    """
    def _boom(*a, **k):  # pragma: no cover - solo si algo intenta abrir red
        raise AssertionError("sin endpoint el LLM local NO debe abrir socket")

    monkeypatch.setattr(socket, "socket", _boom)

    # Rechazo real: endpoint=None y transport=None -> ConfigError, cero sockets.
    cfg_closed = _cfg(transport=None)  # endpoint por defecto None
    assert cfg_closed.endpoint is None
    with pytest.raises(ConfigError):
        evaluate_relation_local(_input(), config=cfg_closed)

    # Control: con transporte inyectado (via legitima de test) evalua sin red.
    rec = evaluate_relation_local(
        _input(), config=_cfg(_mock_transport(json.dumps({"relations": [_relation()]})))
    )
    assert rec.validation_status == "VALID"


# ---------------------------------------------------------------------------
# MUTATION 4 (punto 4): JSON invalido rechazado por el evaluador LOCAL y el EXTERNO.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_mutation_invalid_json_rejected_by_local_and_external():
    """El parseo estricto de JSON es load-bearing en AMBOS evaluadores.

    Mutacion: si cualquiera de los dos aceptara texto no-JSON (parser laxo), un
    "not json en absoluto" pasaria a validacion. Los modulos reales lo marcan
    INVALID_RESPONSES. Control: el mismo camino con JSON valido SI produce un
    estado valido, probando que no rechazan indiscriminadamente.
    """
    # --- Evaluador LOCAL real ---
    rec_bad = evaluate_relation_local(
        _input(), config=_cfg(_mock_transport("esto no es json en absoluto"))
    )
    assert rec_bad.state == INVALID_RESPONSES
    assert rec_bad.validation_status == "INVALID"
    assert any(e.startswith("parse:") for e in rec_bad.validation_errors)

    rec_ok = evaluate_relation_local(
        _input(), config=_cfg(_mock_transport(json.dumps({"relations": [_relation()]})))
    )
    assert rec_ok.state != INVALID_RESPONSES

    # --- Evaluador EXTERNO real (mismo punto, otra capa) ---
    from relations.external_ai_shadow import (
        RelationExternalConfig,
        evaluate_relation_external,
    )
    from relations.contracts import (
        Direction,
        EpistemicStatus,
        ExtractionMethod,
        RelationCandidate,
    )

    seg = "Kakita Asuka es aliada de Bayushi Hisao en la corte."
    ev = "Kakita Asuka es aliada de Bayushi Hisao"
    cand = RelationCandidate(
        subject_id="ent_asuka", subject_type="Character", predicate="ALLIED_WITH",
        object_id="ent_hisao", object_type="Character",
        direction=Direction.SUBJECT_TO_OBJECT, confidence=0.8,
        evidence_text=ev, evidence_start=seg.find(ev), evidence_end=seg.find(ev) + len(ev),
        source_id="src1", source_page=1, source_segment=seg,
        extraction_method=ExtractionMethod.HEURISTIC, model=None, negated=False,
        temporal_scope=None, epistemic_status=EpistemicStatus.ASSERTED, workspace="leyenda",
    ).validate()

    class _FakeProvider:
        provider_name = "nvidia"

        def __init__(self, content):
            self._content = content

        def _post_chat(self, model, messages):
            return ({"choices": [{"message": {"content": self._content}}]}, 5)

    cfg_ext_bad = RelationExternalConfig(model="meta/llama", provider=_FakeProvider("no soy json"))
    res_bad = evaluate_relation_external(cand, config=cfg_ext_bad)
    assert res_bad[0].state == INVALID_RESPONSES

    valid_verdict = {
        "candidate_id": f"{cand.subject_id}|{cand.predicate}|{cand.object_id}",
        "verdict": "confirm", "predicate": cand.predicate,
        "subject_type": "Character", "object_type": "Character", "negated": False,
        "evidence_text": ev, "evidence_start": seg.find(ev), "evidence_end": seg.find(ev) + len(ev),
        "confidence": 0.9, "reason_codes": [], "explanation": "x",
    }
    cfg_ext_ok = RelationExternalConfig(
        model="meta/llama",
        provider=_FakeProvider(json.dumps({"verdicts": [valid_verdict]})),
    )
    res_ok = evaluate_relation_external(cand, config=cfg_ext_ok)
    assert res_ok[0].state != INVALID_RESPONSES
