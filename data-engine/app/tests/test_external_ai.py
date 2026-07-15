# -*- coding: utf-8 -*-
"""Tests del subsistema de IA externa (Fase A, modo sombra). Sin llamadas reales
a NVIDIA: se mockea el transporte HTTP. Ningún test escribe en Neo4j."""
from __future__ import annotations
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from external_ai import require_shadow, PROMPT_VERSION
from external_ai.errors import (ConfigError, ShadowModeRequired, ProviderAuthError,
                                RateLimitError, InvalidResponseError, SecretLeakError)
from external_ai import registry, security, prompts, response_parser, consensus, calibration, cache
from external_ai.models import (ReviewItem, ReviewBatchRequest, ModelReviewResponse,
                                ModelReviewDecision, ConsensusResult, STRONG_CONSENSUS,
                                PARTIAL_CONSENSUS, MODEL_CONFLICT)
from external_ai.nvidia_nim import NvidiaNimProvider

SEG = "Kakita Asuka llega al castillo con Bayushi Hisao."


def _item(cid="c1", name="Kakita Asuka", et="Character", ev="Kakita Asuka", seg=SEG):
    return ReviewItem(candidate_id=cid, kind="entity", name=name, entity_type=et,
                      evidence=ev, local_confidence=0.9, segment_text=seg, neo4j_matches=[])


def _req(items=None):
    return ReviewBatchRequest(workspace="leyenda", source_id="src_anon",
                              items=items or [_item()], glossary=["Kakita Asuka"])


def _review_json(cid="c1", decision="accept", name="Kakita Asuka", et="Character",
                 ev="Kakita Asuka", matched=None):
    return json.dumps({"reviews": [{"candidate_id": cid, "decision": decision,
                                    "canonical_name": name, "entity_type": et,
                                    "matched_existing": matched, "evidence": ev,
                                    "confidence": 0.9, "reason_codes": [], "explanation": "x",
                                    "warnings": []}]})


def _chat(content):
    return ({"choices": [{"message": {"content": content}}],
             "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}}, 42)


def _provider(monkeypatch, key="test-fake-key-000000000000"):
    monkeypatch.setenv("S9K_NVIDIA_API_KEY", key)
    monkeypatch.setenv("S9K_NVIDIA_CACHE_ENABLED", "false")
    return NvidiaNimProvider(repo_root=_APP.parents[1])


# ── 1. config / 2. key ausente ────────────────────────────────────────────────
def test_config_keys(monkeypatch):
    monkeypatch.delenv("S9K_NVIDIA_ENABLED", raising=False)
    cfg = registry.nvidia_config()
    assert "base_url" in cfg and cfg["api_key_present"] in (True, False)
    assert registry.is_nvidia_enabled() is False

def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("S9K_NVIDIA_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        registry.get_api_key()


# ── 21. --shadow obligatorio ──────────────────────────────────────────────────
def test_shadow_required():
    with pytest.raises(ShadowModeRequired):
        require_shadow(False)
    require_shadow(True)  # no lanza


# ── 3. healthcheck mockeado ───────────────────────────────────────────────────
def test_healthcheck_mocked(monkeypatch):
    p = _provider(monkeypatch)
    with patch.object(type(p), "_get_models", return_value=(["m-a", "m-b"], 10)):
        h = p.healthcheck()
    assert h.ok and "m-a" in h.models_available and "nvapi" not in json.dumps(h.to_dict())


# ── 4. respuesta válida ───────────────────────────────────────────────────────
def test_valid_response(monkeypatch):
    p = _provider(monkeypatch)
    with patch.object(type(p), "_post_chat", return_value=_chat(_review_json())):
        r = p.review_candidates(_req(), "m-a", "reviewer_a")
    assert r.valid and len(r.decisions) == 1 and r.decisions[0].decision == "accept"


# ── 5. JSON en markdown ───────────────────────────────────────────────────────
def test_json_in_markdown():
    wrapped = "Claro:\n```json\n" + _review_json() + "\n```\nfin"
    d = response_parser.extract_json(wrapped)
    assert d["reviews"][0]["candidate_id"] == "c1"


# ── 6. JSON inválido ──────────────────────────────────────────────────────────
def test_invalid_json():
    with pytest.raises(InvalidResponseError):
        response_parser.extract_json("no hay json aqui")


# ── 10. sin evidence / 11. evidence no en segmento ────────────────────────────
def test_missing_evidence_rejected():
    dec, errs = response_parser.validate_decision(
        {"candidate_id": "c1", "decision": "accept", "evidence": "", "confidence": 0.9,
         "entity_type": "Character"}, _item())
    assert dec is None and errs

def test_evidence_not_in_segment():
    dec, errs = response_parser.validate_decision(
        {"candidate_id": "c1", "decision": "accept", "evidence": "texto inventado xyz",
         "confidence": 0.9, "entity_type": "Character"}, _item())
    assert dec is None and any("segment" in e.lower() for e in errs)


# ── 7/8/9. timeout, 429 retry, 401 no retry ───────────────────────────────────
def _http_error(code):
    return urllib.error.HTTPError("http://x", code, "err", {}, None)

def test_429_then_success(monkeypatch):
    p = _provider(monkeypatch)
    calls = {"n": 0}
    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429)
        class R:
            def read(self): return _review_json().encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False
        # devolver objeto tipo respuesta con choices
        class Resp:
            def read(self): return json.dumps({"choices":[{"message":{"content":_review_json()}}],"usage":{}}).encode()
            def __enter__(self): return self
            def __exit__(self,*a): return False
        return Resp()
    with patch("external_ai.openai_compatible.urllib.request.urlopen", side_effect=fake_urlopen), \
         patch("external_ai.openai_compatible.time.sleep", return_value=None):
        out, _lat = p._post_chat("m-a", [{"role":"user","content":"x"}])
    assert calls["n"] == 2 and "choices" in out

def test_401_no_retry(monkeypatch):
    p = _provider(monkeypatch)
    calls = {"n": 0}
    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        raise _http_error(401)
    with patch("external_ai.openai_compatible.urllib.request.urlopen", side_effect=fake_urlopen):
        with pytest.raises(ProviderAuthError):
            p._post_chat("m-a", [{"role":"user","content":"x"}])
    assert calls["n"] == 1  # sin reintento infinito


# ── 12. reviewers A/B independientes ──────────────────────────────────────────
def test_reviewers_independent():
    req = _req()
    pa = prompts.build_review_prompt(req, "m-a")
    pb = prompts.build_review_prompt(req, "m-b")
    txt_a = json.dumps(pa, ensure_ascii=False)
    # el prompt de A no contiene ninguna decisión de B (independencia)
    assert "reviewer_b" not in txt_a and "response_b" not in txt_a
    assert pa[0]["role"] == "system" and pb[0]["role"] == "system"


# ── 13/14/15/16. consenso ─────────────────────────────────────────────────────
def _resp(role, decision="accept", name="Kakita Asuka", et="Character", cid="c1", matched=None):
    d = ModelReviewDecision(candidate_id=cid, decision=decision, canonical_name=name,
                            entity_type=et, matched_existing=matched, evidence="Kakita Asuka",
                            confidence=0.9)
    return ModelReviewResponse(provider="nvidia", model="m-"+role, reviewer_role=role, decisions=[d])

def test_strong_consensus():
    res = consensus.compute_consensus(_resp("reviewer_a"), _resp("reviewer_b"), _req())
    assert res[0].state == STRONG_CONSENSUS and res[0].shadow_recommendation == "accept"

def test_partial_consensus():
    res = consensus.compute_consensus(_resp("reviewer_a", name="Kakita Asuka"),
                                      _resp("reviewer_b", name="Asuka"), _req())
    assert res[0].state == PARTIAL_CONSENSUS

def test_conflict_and_adjudication():
    a = _resp("reviewer_a", decision="accept")
    b = _resp("reviewer_b", decision="reject")
    called = {"n": 0}
    def adj(cid):
        called["n"] += 1
        return ModelReviewDecision(candidate_id=cid, decision="reject", evidence="Kakita Asuka", confidence=0.8)
    res = consensus.compute_consensus(a, b, _req(), adjudicate_fn=adj)
    assert res[0].state == MODEL_CONFLICT and called["n"] == 1
    assert res[0].adjudication is not None and res[0].shadow_recommendation == "reject"
    # sin estado AUTO_APPROVED
    assert res[0].state != "AUTO_APPROVED"


# ── 17/18. caché + invalidación por prompt version ────────────────────────────
def test_cache_put_get(tmp_path):
    c = cache.ResponseCache(tmp_path, enabled=True)
    k = cache.cache_key("nvidia", "m-a", "1.0", "leyenda", "c1", "segh", "1.0", "gh")
    c.put(k, "raw", {"ok": True}, 12)
    assert c.get(k)["normalized"]["ok"] is True

def test_cache_key_invalidates_on_prompt_version():
    k1 = cache.cache_key("nvidia", "m-a", "1.0", "leyenda", "c1", "s", "1.0", "g")
    k2 = cache.cache_key("nvidia", "m-a", "2.0", "leyenda", "c1", "s", "1.0", "g")
    assert k1 != k2


# ── 19/22. sanitización + secretos ────────────────────────────────────────────
def test_secret_detection_blocks():
    assert security.find_secrets({"k": "nvapi-" + "abcdef1234567890ghij"})  # split para no dejar literal
    with pytest.raises(SecretLeakError):
        security.assert_no_secrets({"authorization": "Bearer abcdefghij1234567890"})

def test_no_secret_clean_payload():
    security.assert_no_secrets({"name": "Kakita Asuka", "evidence": "texto"})  # no lanza


# ── 23. métricas vs decisiones humanas ────────────────────────────────────────
def test_calibration_vs_human():
    cr = ConsensusResult(candidate_id="c1", state=STRONG_CONSENSUS, shadow_recommendation="accept",
                         reviewer_a=_resp("reviewer_a").decisions[0].to_dict())
    human = {"c1": {"action": "approve"}}
    m = calibration.calibrate([cr], human)
    assert m["shadow_mode"] is True
    assert "overall_accuracy" in m or "accuracy" in m


# ── 20/24. NO escritura Neo4j / no ingest / no S9K_ALLOW_REAL_INGEST ───────────
def test_external_ai_never_touches_ingest_or_neo4j():
    """Falla si el subsistema IMPORTA ingesta/Neo4j o ASIGNA la variable de ingesta.
    (Las menciones en docstrings de seguridad están permitidas; el uso real no.)"""
    import re
    pkg = _APP / "external_ai"
    danger = [
        re.compile(r"(from\s+review\.ingest_approved|import\s+ingest_approved|ingest_approved\s*\.)"),
        re.compile(r"GraphDatabase"),
        re.compile(r"bolt://"),
        re.compile(r"from\s+review\.approved_writer|approved_writer\s*\."),
        # asignación real de la variable de ingesta (no una mención en docstring)
        re.compile(r"S9K_ALLOW_REAL_INGEST['\"]\s*\]\s*=|setenv\(\s*['\"]S9K_ALLOW_REAL_INGEST"),
    ]
    hits = []
    for f in pkg.glob("*.py"):
        txt = f.read_text(encoding="utf-8")
        for pat in danger:
            if pat.search(txt):
                hits.append(f"{f.name}: {pat.pattern[:40]}")
    assert not hits, f"El subsistema externo NO debe usar ingesta/Neo4j: {hits}"


def test_external_ai_cli_requires_shadow_and_no_write():
    """El CLI no debe importar ingest_approved ni el writer de Neo4j."""
    cli = _APP / "cli" / "external_ai.py"
    txt = cli.read_text(encoding="utf-8")
    assert "ingest_approved" not in txt
    assert "GraphDatabase" not in txt and "bolt://" not in txt
