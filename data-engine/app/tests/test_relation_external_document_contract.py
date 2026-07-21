# -*- coding: utf-8 -*-
"""Base común PR#95 — contrato DOCUMENTO/ID del evaluador externo (P0).

Regresión: el proveedor externo debe recibir y validar contra el TEXTO REAL del
segmento (`document_text`), NO contra su ID (`cand.source_segment`). Estos tests
FALLAN en el código previo al fix (donde el DOCUMENTO era el ID). Todo OFFLINE
(proveedor falso inyectado): sin red, sin escritura, determinista.
"""
from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from external_ai.errors import ProviderTimeoutError
from relations.contracts import Direction, EpistemicStatus, ExtractionMethod, RelationCandidate
from relations.external_ai_shadow import (
    RelationExternalConfig,
    evaluate_relation_external,
)
from relations.pipeline import PipelineConfig, run_pipeline


# --- Proveedor falso (sin red) --------------------------------------------
class CapturingProvider:
    """Captura los messages y devuelve una respuesta preconfigurada."""

    def __init__(self, response_builder=None):
        self.captured = []
        self._builder = response_builder

    def _post_chat(self, model, messages):
        self.captured.append(messages)
        content = self._builder(messages) if self._builder else "{}"
        return {"choices": [{"message": {"content": content}}]}, 10.0

    def document_seen(self) -> str:
        """Extrae el texto del DOCUMENTO mostrado en el último prompt."""
        blob = json.dumps(self.captured[-1], ensure_ascii=False)
        return blob


class RaisingProvider:
    def __init__(self, exc):
        self._exc = exc

    def _post_chat(self, model, messages):
        raise self._exc


def _verdict_content(cid, evidence, start, end, *, verdict="confirm"):
    return json.dumps([{
        "candidate_id": cid, "verdict": verdict, "predicate": "MEMBER_OF",
        "subject_type": "Character", "object_type": "Faction", "negated": False,
        "evidence_text": evidence, "evidence_start": start, "evidence_end": end,
        "confidence": 0.9, "reason_codes": [], "explanation": "ok",
    }])


def _cand(*, source_segment_id, evidence="X", predicate="MEMBER_OF"):
    """Candidato con source_segment = ID (como en el pipeline real), no el texto."""
    return RelationCandidate(
        subject_id="Bayushi Hisao", subject_type="Character", predicate=predicate,
        object_id="Clan Escorpion", object_type="Faction",
        direction=Direction.SUBJECT_TO_OBJECT, confidence=0.8,
        evidence_text=evidence, evidence_start=0, evidence_end=len(evidence),
        source_id="src1", source_page=1, source_segment=source_segment_id,
        extraction_method=ExtractionMethod.HEURISTIC, model=None, negated=False,
        temporal_scope=None, epistemic_status=EpistemicStatus.ASSERTED, workspace="leyenda",
    ).validate()


def _cid(c):
    return f"{c.subject_id}|{c.predicate}|{c.object_id}"


SEG_ID = "audio_l5a_s03e01"
DOC = "Bayushi Hisao juro lealtad al Clan Escorpion."


# ===========================================================================
# Regresión P0 (fallan sin el fix)
# ===========================================================================
def test_provider_receives_document_text_not_id():
    prov = CapturingProvider(lambda m: "{}")
    cand = _cand(source_segment_id=SEG_ID)
    cfg = RelationExternalConfig(model="m", provider_name="nvidia", shadow_mode=True, provider=prov)
    evaluate_relation_external(cand, config=cfg, document_text=DOC)
    seen = prov.document_seen()
    assert DOC in seen            # ve el TEXTO real
    assert SEG_ID not in seen     # NO ve el ID del segmento


def test_evidence_validated_against_real_text_accepts_literal():
    ev = "juro lealtad al Clan Escorpion"
    s = DOC.find(ev)
    prov = CapturingProvider(lambda m, cid=None: None)
    cand = _cand(source_segment_id=SEG_ID)
    cid = _cid(cand)
    prov._builder = lambda m: _verdict_content(cid, ev, s, s + len(ev))
    cfg = RelationExternalConfig(model="m", provider_name="nvidia", shadow_mode=True, provider=prov)
    res = evaluate_relation_external(cand, config=cfg, document_text=DOC)[0]
    # evidencia literal del DOCUMENTO real -> NO se rechaza por evidencia inexistente
    assert "evidencia_inexistente" not in json.dumps(getattr(res, "validation_errors", []) or [])
    assert res.state != "INVALID_RESPONSES"


def test_document_slice_equals_evidence_end_to_end_via_pipeline():
    # Regresión end-to-end: el pipeline pasa el texto real; el proveedor lo ve.
    prov = CapturingProvider(lambda m: "{}")
    payload = {
        "document": SEG_ID, "workspace": "leyenda",
        "segments": [{
            "segment_id": SEG_ID, "source_id": SEG_ID, "text": DOC,
            "entities": [
                {"id": "Bayushi Hisao", "start": 0, "end": 13, "type": "Character"},
                {"id": "Clan Escorpion", "start": DOC.find("Clan Escorpion"),
                 "end": DOC.find("Clan Escorpion") + len("Clan Escorpion"), "type": "Faction"},
            ],
        }],
    }
    cfg = PipelineConfig(context_mode="segment", external_ai_enabled=True)
    run_pipeline(payload, config=cfg, external_provider=prov)
    seen = prov.document_seen()
    assert DOC in seen
    assert seen.count(SEG_ID) == 0 or DOC in seen  # el ID no suplanta al texto


# ===========================================================================
# Casos borde comunes
# ===========================================================================
def test_evidence_not_in_document_is_rejected():
    prov = CapturingProvider()
    cand = _cand(source_segment_id=SEG_ID)
    cid = _cid(cand)
    prov._builder = lambda m: _verdict_content(cid, "texto inventado", 0, 14)
    cfg = RelationExternalConfig(model="m", provider_name="nvidia", shadow_mode=True, provider=prov)
    res = evaluate_relation_external(cand, config=cfg, document_text=DOC)[0]
    assert res.state == "INVALID_RESPONSES"
    assert any("evidencia_inexistente" in e for e in res.validation_errors)


def test_offsets_out_of_range_rejected():
    prov = CapturingProvider()
    cand = _cand(source_segment_id=SEG_ID)
    cid = _cid(cand)
    prov._builder = lambda m: _verdict_content(cid, "Clan Escorpion", 0, 99999)
    cfg = RelationExternalConfig(model="m", provider_name="nvidia", shadow_mode=True, provider=prov)
    res = evaluate_relation_external(cand, config=cfg, document_text=DOC)[0]
    assert res.state == "INVALID_RESPONSES"
    assert any("offsets_invalidos" in e for e in res.validation_errors)


def test_empty_document_rejects_any_evidence():
    prov = CapturingProvider()
    cand = _cand(source_segment_id=SEG_ID)
    cid = _cid(cand)
    prov._builder = lambda m: _verdict_content(cid, "algo", 0, 4)
    cfg = RelationExternalConfig(model="m", provider_name="nvidia", shadow_mode=True, provider=prov)
    res = evaluate_relation_external(cand, config=cfg, document_text="")[0]
    assert res.state == "INVALID_RESPONSES"


def test_crlf_document_offsets_coherent():
    doc = "Prologo.\r\nBayushi Hisao sirve al Clan Escorpion."
    ev = "Bayushi Hisao sirve al Clan Escorpion"
    s = doc.find(ev)
    prov = CapturingProvider()
    cand = _cand(source_segment_id=SEG_ID)
    cid = _cid(cand)
    prov._builder = lambda m: _verdict_content(cid, ev, s, s + len(ev))
    cfg = RelationExternalConfig(model="m", provider_name="nvidia", shadow_mode=True, provider=prov)
    res = evaluate_relation_external(cand, config=cfg, document_text=doc)[0]
    assert res.state != "INVALID_RESPONSES"
    assert doc[s:s + len(ev)] == ev


def test_repeated_substring_offsets_disambiguate():
    doc = "Clan Escorpion. Clan Escorpion es el Clan Escorpion."
    ev = "Clan Escorpion"
    s = doc.find(ev, 16)  # la SEGUNDA aparición
    prov = CapturingProvider()
    cand = _cand(source_segment_id=SEG_ID)
    cid = _cid(cand)
    prov._builder = lambda m: _verdict_content(cid, ev, s, s + len(ev))
    cfg = RelationExternalConfig(model="m", provider_name="nvidia", shadow_mode=True, provider=prov)
    res = evaluate_relation_external(cand, config=cfg, document_text=doc)[0]
    # offsets apuntan a una ocurrencia válida -> aceptado
    assert res.state != "INVALID_RESPONSES"
    assert doc[s:s + len(ev)] == ev


def test_unicode_nfc_nfd_literal_matching():
    # El documento en NFC; evidencia en NFD NO es subcadena literal -> se rechaza.
    doc = unicodedata.normalize("NFC", "Akodo Kaédé lidera la Legion Leon.")
    ev_nfd = unicodedata.normalize("NFD", "Akodo Kaédé")
    prov = CapturingProvider()
    cand = _cand(source_segment_id=SEG_ID)
    cid = _cid(cand)
    prov._builder = lambda m: _verdict_content(cid, ev_nfd, 0, len(ev_nfd))
    cfg = RelationExternalConfig(model="m", provider_name="nvidia", shadow_mode=True, provider=prov)
    res = evaluate_relation_external(cand, config=cfg, document_text=doc)[0]
    # literalidad estricta: NFD no casa con NFC -> rechazo (evidencia/offsets)
    assert res.state == "INVALID_RESPONSES"


def test_provider_timeout_is_isolated_not_crash():
    prov = RaisingProvider(ProviderTimeoutError("timeout"))
    cand = _cand(source_segment_id=SEG_ID)
    cfg = RelationExternalConfig(model="m", provider_name="nvidia", shadow_mode=True, provider=prov)
    res = evaluate_relation_external(cand, config=cfg, document_text=DOC)[0]
    assert res.state == "INVALID_RESPONSES"  # aislado, no propaga


def test_invalid_json_response_isolated():
    prov = CapturingProvider(lambda m: "esto no es json {")
    cand = _cand(source_segment_id=SEG_ID)
    cfg = RelationExternalConfig(model="m", provider_name="nvidia", shadow_mode=True, provider=prov)
    res = evaluate_relation_external(cand, config=cfg, document_text=DOC)[0]
    assert res.state == "INVALID_RESPONSES"


def test_determinism_same_request_hash():
    ev = "Clan Escorpion"
    s = DOC.find(ev)
    def make():
        prov = CapturingProvider()
        cand = _cand(source_segment_id=SEG_ID)
        cid = _cid(cand)
        prov._builder = lambda m: _verdict_content(cid, ev, s, s + len(ev))
        cfg = RelationExternalConfig(model="m", provider_name="nvidia", shadow_mode=True, provider=prov)
        return evaluate_relation_external(cand, config=cfg, document_text=DOC)[0]
    r1, r2 = make(), make()
    assert r1.request_hash == r2.request_hash


def test_no_network_provider_is_injected_fake():
    # Garantía estructural: con proveedor inyectado no se construye transporte real.
    prov = CapturingProvider(lambda m: "{}")
    cand = _cand(source_segment_id=SEG_ID)
    cfg = RelationExternalConfig(model="m", provider_name="nvidia", shadow_mode=True, provider=prov)
    evaluate_relation_external(cand, config=cfg, document_text=DOC)
    assert prov.captured, "se usó el proveedor falso (sin red)"
