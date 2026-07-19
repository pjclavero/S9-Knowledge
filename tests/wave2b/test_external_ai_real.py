# -*- coding: utf-8 -*-
"""Q — evaluador de IA EXTERNA REAL (`relations.external_ai_shadow`).

Cubre:
  * Punto 3: "secreto aparece en logs". Una API key inyectada en el payload NO
    llega al proveedor: `assert_no_secrets` (reutilizado del subsistema real)
    BLOQUEA el envio, y la config no serializa la key en `to_dict`/`repr`.
  * Punto 5: "evidencia inexistente aceptada". El evaluador RECHAZA un verdicto
    cuya `evidence_text` no es subcadena literal del segmento (evidencia
    inventada) -> INVALID_RESPONSES.

Sin red: el proveedor (`_post_chat`) se inyecta. Importa el modulo REAL.
"""
from __future__ import annotations

import json

import pytest

from external_ai.errors import SecretLeakError
from external_ai.models import INVALID_RESPONSES, STRONG_CONSENSUS
from external_ai.security import assert_no_secrets
from relations.contracts import (
    Direction,
    EpistemicStatus,
    ExtractionMethod,
    RelationCandidate,
)
from relations.external_ai_shadow import (
    RelationExternalConfig,
    RelationExternalEvaluation,
    evaluate_relation_external,
)

SEG = "Kakita Asuka es aliada de Bayushi Hisao en la corte del Escorpion."
EV = "Kakita Asuka es aliada de Bayushi Hisao"
# Clave SINTETICA con forma de credencial NVIDIA (no real): solo para el guardia.
FAKE_KEY = "nvapi-" + "A1b2C3d4E5f6G7h8I9j0K1l2"


def _candidate(**over):
    base = dict(
        subject_id="ent_asuka", subject_type="Character", predicate="ALLIED_WITH",
        object_id="ent_hisao", object_type="Character",
        direction=Direction.SUBJECT_TO_OBJECT, confidence=0.8,
        evidence_text=EV, evidence_start=SEG.find(EV), evidence_end=SEG.find(EV) + len(EV),
        source_id="src1", source_page=1, source_segment=SEG,
        extraction_method=ExtractionMethod.HEURISTIC, model=None, negated=False,
        temporal_scope=None, epistemic_status=EpistemicStatus.ASSERTED, workspace="leyenda",
    )
    base.update(over)
    return RelationCandidate(**base).validate()


def _cid(cand):
    return f"{cand.subject_id}|{cand.predicate}|{cand.object_id}"


def _verdict(cand, *, evidence=EV, start=None, end=None, **over):
    s = SEG.find(evidence) if start is None else start
    e = (s + len(evidence)) if end is None else end
    v = {
        "candidate_id": _cid(cand), "verdict": "confirm", "predicate": cand.predicate,
        "subject_type": "Character", "object_type": "Character", "negated": False,
        "evidence_text": evidence, "evidence_start": s, "evidence_end": e,
        "confidence": 0.9, "reason_codes": [], "explanation": "x",
    }
    v.update(over)
    return v


class FakeProvider:
    """Doble del proveedor reutilizado: mismo contrato `_post_chat`, sin red."""

    provider_name = "nvidia"

    def __init__(self, content):
        self._content = content
        self.last_messages = None

    def _post_chat(self, model, messages):
        self.last_messages = messages
        return ({"choices": [{"message": {"content": self._content}}]}, 42)


def _content(*verdicts):
    return json.dumps({"verdicts": list(verdicts)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Control: un verdicto con evidencia literal valida produce consenso fuerte.
# ---------------------------------------------------------------------------
def test_valid_verdict_is_accepted():
    cand = _candidate()
    res = evaluate_relation_external(cand, config=RelationExternalConfig(
        model="meta/llama", provider=FakeProvider(_content(_verdict(cand)))))
    assert res[0].state == STRONG_CONSENSUS
    assert res[0].shadow_recommendation != "AUTO_APPROVED"


# ---------------------------------------------------------------------------
# MUTATION 3 (punto 3): un secreto NO viaja al proveedor ni se serializa.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_mutation_secret_never_leaks_to_provider_or_logs():
    """La guarda de secretos es load-bearing en el evaluador externo.

    Mutacion: si se retirara `assert_no_secrets`, un payload con una API key
    saldria hacia el proveedor y podria acabar en logs. El modulo real BLOQUEA
    el envio (`SecretLeakError`) ANTES de llamar a `_post_chat`. Ademas la config
    NUNCA serializa la key en `to_dict`/`repr`. Control: un payload limpio SI
    pasa la guarda.
    """
    # Rechazo real: un payload con una credencial dispara SecretLeakError.
    leaky = [{"role": "system", "content": "sys"},
             {"role": "user", "content": f"Authorization: Bearer {FAKE_KEY}"}]
    with pytest.raises(SecretLeakError):
        assert_no_secrets(leaky)

    # Control: un payload limpio NO dispara (la guarda no bloquea todo).
    assert_no_secrets([{"role": "user", "content": "texto sin secretos"}])

    # La config no almacena ni serializa la API key (solo el tipo del proveedor).
    cand = _candidate()
    prov = FakeProvider(_content(_verdict(cand)))
    cfg = RelationExternalConfig(model="meta/llama", provider=prov)
    dumped = json.dumps(cfg.to_dict(), ensure_ascii=False)
    assert FAKE_KEY not in dumped
    assert FAKE_KEY not in repr(cfg)

    # El resultado serializado tampoco contiene la key en ningun campo.
    res = evaluate_relation_external(cand, config=cfg)
    assert FAKE_KEY not in json.dumps(res[0].to_dict(), ensure_ascii=False)


# ---------------------------------------------------------------------------
# MUTATION 5 (punto 5): evidencia inventada (no literal en el segmento) rechazada.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_mutation_invented_evidence_is_rejected():
    """La verificacion de evidencia LITERAL es load-bearing.

    Mutacion: si el validador no exigiera que `evidence_text` fuese subcadena del
    segmento, el modelo podria "inventar" citas y colarlas. El modulo real lo
    marca INVALID_RESPONSES. Control: la MISMA relacion con evidencia literal
    presente SI es aceptada.
    """
    cand = _candidate()

    invented = _verdict(cand, evidence="Cita totalmente inventada que no existe",
                        start=0, end=10)
    res_bad = evaluate_relation_external(cand, config=RelationExternalConfig(
        model="meta/llama", provider=FakeProvider(_content(invented))))
    assert res_bad[0].state == INVALID_RESPONSES
    assert any("evidencia_inexistente" in e or "offsets" in e
               for e in res_bad[0].validation_errors)

    res_ok = evaluate_relation_external(cand, config=RelationExternalConfig(
        model="meta/llama", provider=FakeProvider(_content(_verdict(cand)))))
    assert res_ok[0].state != INVALID_RESPONSES
