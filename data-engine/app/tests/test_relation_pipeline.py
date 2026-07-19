# -*- coding: utf-8 -*-
"""Tests del PIPELINE end-to-end de relaciones en DRY-RUN (`relation-pipeline/v1`).

El pipeline ORQUESTA los componentes ya integrados de `relations/` (pairs,
signals, syntax heuristica, prompts, proveedores en sombra, consenso y
observabilidad) sin reimplementar ninguno y sin crear un segundo
`RelationCandidate`.

Estos tests verifican, entre otras cosas: documento vacio/pequeno/multi-segmento,
una/dos/muchas entidades, anti-explosion combinatoria, workspace vacio (error) y
mezcla de workspace (rechazada), Unicode, negacion, temporalidad, rumor,
proveedor local/externo ausente/invalido, timeout, JSON invalido, fallo parcial,
determinismo (mismo input y orden alterado), candidatos repetidos, evidencia
inexistente, offsets incorrectos, CERO red / CERO escritura / CERO Neo4j y
observabilidad redactada.

MUTATION CHECKS (12/12): al final, cada mutacion del codigo del pipeline rompe al
menos uno de los tests aqui presentes. La tabla mutacion -> test esta documentada
en `test_mutation_matrix_is_documented` y en el cuerpo del PR.
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from relations.pipeline import (  # noqa: E402
    GENERIC_PREDICATE,
    PIPELINE_SCHEMA,
    PROVIDER_EXECUTED,
    PROVIDER_FAILED_CLOSED,
    PROVIDER_NOT_EXECUTED,
    PipelineConfig,
    PipelineError,
    config_from_dict,
    run_pipeline,
    to_json,
    to_jsonl,
)
from relations.contracts import EpistemicStatus  # noqa: E402


# ---------------------------------------------------------------------------
# Factorias de entrada
# ---------------------------------------------------------------------------
def _ent(id_, start, end, type_=None, **extra):
    d = {"id": id_, "start": start, "end": end}
    if type_ is not None:
        d["type"] = type_
    d.update(extra)
    return d


def _seg(text, seg_id, entities, **extra):
    d = {"segment_id": seg_id, "text": text, "entities": entities}
    d.update(extra)
    return d


def _payload(segments, *, workspace="leyenda", document="doc-1", config=None):
    p = {"document": document, "workspace": workspace, "segments": segments}
    if config is not None:
        p["config"] = config
    return p


# Documento de referencia (Character -> Faction => categoria MEMBERSHIP).
DOC = "Bayushi Hisao juro lealtad al Clan Escorpion."
S_START, S_END = 0, len("Bayushi Hisao")
O_START = DOC.find("Clan Escorpion")
O_END = O_START + len("Clan Escorpion")


def _membership_segment(seg_id="s1"):
    return _seg(
        DOC,
        seg_id,
        [
            _ent("Bayushi Hisao", S_START, S_END, "Character"),
            _ent("Clan Escorpion", O_START, O_END, "Faction"),
        ],
    )


# ---------------------------------------------------------------------------
# 1. Documento vacio / pequeno / multi-segmento
# ---------------------------------------------------------------------------
def test_empty_document():
    out = run_pipeline(_payload([]))
    assert out["schema"] == PIPELINE_SCHEMA
    assert out["dry_run"] is True
    assert out["summary"]["segments"] == 0
    assert out["results"] == []
    assert out["summary"]["candidates_evaluated"] == 0


def test_small_document_one_candidate():
    out = run_pipeline(_payload([_membership_segment()]))
    assert out["summary"]["candidates_evaluated"] == 1
    assert len(out["results"]) == 1
    cand = out["results"][0]["candidate"]
    assert cand["subject_id"] == "Bayushi Hisao"
    assert cand["object_id"] == "Clan Escorpion"
    assert cand["predicate"] == "MEMBER_OF"       # Character->Faction => MEMBERSHIP
    assert cand["extraction_method"] == "HEURISTIC"
    assert cand["evidence_text"]  # evidencia literal no vacia


def test_multiple_segments():
    segs = [_membership_segment("s1"), _membership_segment("s2")]
    out = run_pipeline(_payload(segs))
    assert out["summary"]["segments"] == 2
    assert out["summary"]["segments_processed"] == 2
    # Dos segmentos distintos => dos candidatos (source_segment distinto).
    assert out["summary"]["candidates_evaluated"] == 2


# ---------------------------------------------------------------------------
# 2. Numero de entidades: una / dos / muchas + anti-explosion combinatoria
# ---------------------------------------------------------------------------
def test_single_entity_no_pairs():
    seg = _seg("Hisao camina solo.", "s1", [_ent("Hisao", 0, 5, "Character")])
    out = run_pipeline(_payload([seg]))
    assert out["summary"]["pairs_generated"] == 0
    assert out["results"] == []


def test_two_entities_one_pair():
    out = run_pipeline(_payload([_membership_segment()]))
    assert out["summary"]["pairs_generated"] == 1


def test_many_entities_combinatorial_limit():
    # Cinco entidades en la misma frase => C(5,2)=10 pares potenciales; limite 2.
    text = "Aza y Ben y Cid y Dan y Eli hablan."
    ents = []
    for name in ("Aza", "Ben", "Cid", "Dan", "Eli"):
        i = text.find(name)
        ents.append(_ent(name, i, i + len(name), "Character"))
    seg = _seg(text, "s1", ents)
    out = run_pipeline(_payload([seg], config={"max_pairs_per_segment": 2}))
    assert out["summary"]["pairs_potential"] == 10
    assert out["summary"]["pairs_generated"] <= 2
    assert out["documents"][0]["segments"][0]["truncated"] is True


# ---------------------------------------------------------------------------
# 3. Workspace: vacio (error) / mezcla (rechazada)
# ---------------------------------------------------------------------------
def test_workspace_empty_raises():
    with pytest.raises(PipelineError):
        run_pipeline(_payload([_membership_segment()], workspace=""))


def test_workspace_mixed_rejected():
    seg = _membership_segment()
    seg["workspace"] = "otro-workspace"
    out = run_pipeline(_payload([seg], workspace="leyenda"))
    segres = out["documents"][0]["segments"][0]
    assert segres["status"] == "failed"
    assert any(e["code"] == "workspace_mismatch" for e in segres["errors"])
    assert out["summary"]["segments_failed"] == 1
    # La mezcla no produce candidatos.
    assert out["summary"]["candidates_evaluated"] == 0


# ---------------------------------------------------------------------------
# 4. Unicode
# ---------------------------------------------------------------------------
def test_unicode_offsets_and_evidence():
    text = "Aria pertenece a la Orden del Fénix 🔥 desde siempre."
    a = text.find("Aria")
    o = text.find("Orden del Fénix")
    seg = _seg(
        text,
        "s1",
        [
            _ent("Aria", a, a + len("Aria"), "Character"),
            _ent("Orden del Fénix", o, o + len("Orden del Fénix"), "Faction"),
        ],
    )
    out = run_pipeline(_payload([seg]))
    cand = out["results"][0]["candidate"]
    # La evidencia es un span literal del texto Unicode.
    assert cand["evidence_text"] == text[cand["evidence_start"]:cand["evidence_end"]]
    assert "Fénix" in cand["evidence_text"]


# ---------------------------------------------------------------------------
# 5. Negacion / temporalidad / rumor / ambigüedad
# ---------------------------------------------------------------------------
def test_negation_preserved():
    text = "Hisao no pertenece al Clan Escorpion."
    s = text.find("Hisao")
    o = text.find("Clan Escorpion")
    seg = _seg(text, "s1", [
        _ent("Hisao", s, s + 5, "Character"),
        _ent("Clan Escorpion", o, o + 14, "Faction"),
    ])
    out = run_pipeline(_payload([seg]))
    cand = out["results"][0]["candidate"]
    assert cand["negated"] is True
    assert out["results"][0]["consensus"]["negated"] is True


def test_temporality_preserved():
    text = "El torneo ocurrio antes del asedio en el ano 1123."
    a = text.find("torneo")
    b = text.find("asedio")
    seg = _seg(text, "s1", [
        _ent("torneo", a, a + len("torneo"), "Event"),
        _ent("asedio", b, b + len("asedio"), "Event"),
    ])
    out = run_pipeline(_payload([seg]))
    cand = out["results"][0]["candidate"]
    assert cand["temporal_scope"] is not None
    assert out["results"][0]["consensus"]["temporal_scope"] == cand["temporal_scope"]


def test_rumor_epistemic_status():
    text = "Se dice que Hisao pertenece al Clan Escorpion."
    s = text.find("Hisao")
    o = text.find("Clan Escorpion")
    seg = _seg(text, "s1", [
        _ent("Hisao", s, s + 5, "Character"),
        _ent("Clan Escorpion", o, o + 14, "Faction"),
    ])
    out = run_pipeline(_payload([seg]))
    cand = out["results"][0]["candidate"]
    assert cand["epistemic_status"] == EpistemicStatus.RUMORED.value


def test_ambiguous_relation_goes_human_or_partial():
    # Dos entidades lejanas y sin cue claro: relacion ambigua.
    text = "Zeta estaba lejos. Muy lejos vivia Omega en su torre distante."
    a = text.find("Zeta")
    b = text.find("Omega")
    seg = _seg(text, "s1", [
        _ent("Zeta", a, a + 4, "Character"),
        _ent("Omega", b, b + 5, "Character"),
    ])
    out = run_pipeline(_payload([seg], config={"context_mode": "segment"}))
    # Sin proveedores y con heuristicas debiles -> nunca es un rechazo automatico.
    for r in out["results"]:
        assert r["consensus"]["recommendation"] in ("propose", "human")


# ---------------------------------------------------------------------------
# 6. Evidencia inexistente / offsets incorrectos
# ---------------------------------------------------------------------------
def test_empty_evidence_rejected():
    # Menciones de longitud cero en la misma posicion => span de evidencia vacio.
    seg = _seg("texto irrelevante", "s1", [
        _ent("A", 5, 5, "Character"),
        _ent("B", 5, 5, "Character"),
    ])
    out = run_pipeline(_payload([seg]))
    seg_errs = out["documents"][0]["segments"][0]["errors"]
    assert any(e["code"] == "evidence_span_empty" for e in seg_errs)
    assert out["summary"]["candidates_evaluated"] == 0


def test_bad_offsets_isolated():
    # Offset de fin mas alla del texto: SignalContext lo rechaza; el par se aisla.
    text = "Hola mundo."
    seg = _seg(text, "s1", [
        _ent("Hola", 0, 4, "Character"),
        _ent("mundo", 5, 999, "Character"),  # end fuera de rango
    ])
    out = run_pipeline(_payload([seg]))
    seg_errs = out["documents"][0]["segments"][0]["errors"]
    assert any(e["code"] == "signal_error" for e in seg_errs)


# ---------------------------------------------------------------------------
# 7. Fallo parcial: un segmento roto no invalida el resto
# ---------------------------------------------------------------------------
def test_partial_failure_isolated():
    good = _membership_segment("s1")
    bad = _membership_segment("s2")
    bad["workspace"] = "otro"  # mezcla => segmento fallido
    out = run_pipeline(_payload([good, bad]))
    assert out["summary"]["segments_processed"] == 1
    assert out["summary"]["segments_failed"] == 1
    # El segmento bueno conserva su candidato.
    assert out["summary"]["candidates_evaluated"] == 1


# ---------------------------------------------------------------------------
# 8. Candidatos repetidos (dedup determinista)
# ---------------------------------------------------------------------------
def test_repeated_candidates_deduped():
    # generate_pairs ya deduplica pares por (subject, object); el candidato es unico.
    text = "Hisao pertenece al Clan. Hisao pertenece al Clan."
    ents = [
        _ent("Hisao", 0, 5, "Character"),
        _ent("Clan", text.find("Clan"), text.find("Clan") + 4, "Faction"),
    ]
    seg = _seg(text, "s1", ents)
    out = run_pipeline(_payload([seg], config={"context_mode": "segment"}))
    ids = [r["candidate_id"] for r in out["results"]]
    assert len(ids) == len(set(ids))  # sin duplicados


# ---------------------------------------------------------------------------
# 9. Determinismo: mismo input dos veces / orden de segmentos alterado
# ---------------------------------------------------------------------------
def test_deterministic_same_input():
    payload = _payload([_membership_segment("s1"), _membership_segment("s2")])
    out1 = run_pipeline(payload)
    out2 = run_pipeline(payload)
    assert out1["execution_id"] == out2["execution_id"]
    assert out1["result_hash"] == out2["result_hash"]
    assert to_json(out1) == to_json(out2)


def test_segment_order_invariant():
    a = _membership_segment("aaa")
    b = _membership_segment("bbb")
    out_ab = run_pipeline(_payload([a, b]))
    out_ba = run_pipeline(_payload([b, a]))
    assert out_ab["execution_id"] == out_ba["execution_id"]
    assert out_ab["result_hash"] == out_ba["result_hash"]


# ---------------------------------------------------------------------------
# 10. Proveedor LOCAL: ausente / valido / invalido / timeout / JSON invalido
# ---------------------------------------------------------------------------
def _local_content(text, evidence, drop=None, **over):
    start = text.find(evidence)
    rel = {
        "predicate": "MEMBER_OF",
        "direction": "SUBJECT_TO_OBJECT",
        "confidence": 0.9,
        "evidence_text": evidence,
        "evidence_start": start,
        "evidence_end": start + len(evidence),
        "negated": False,
        "temporal_scope": None,
        "epistemic_status": "ASSERTED",
        "subject_type": "Character",
        "object_type": "Faction",
    }
    rel.update(over)
    if drop:
        rel.pop(drop, None)
    return json.dumps({"relations": [rel]})


def _local_transport(content, latency=42):
    def transport(messages):
        assert isinstance(messages, list) and messages[0]["role"] == "system"
        return ({"choices": [{"message": {"content": content}}]}, latency)
    return transport


def test_local_provider_absent_not_rejection():
    # Proveedores deshabilitados por defecto: NOT_EXECUTED, jamas rechazo por ausencia.
    out = run_pipeline(_payload([_membership_segment()]))
    assert out["provider_status"]["local_llm"] == PROVIDER_NOT_EXECUTED
    assert out["provider_status"]["external_ai"] == PROVIDER_NOT_EXECUTED
    r = out["results"][0]
    assert r["local"] is None and r["external"] is None
    assert r["consensus"]["recommendation"] != "reject"
    assert out["summary"]["local_calls_simulated"] == 0


def test_local_provider_valid_injected():
    content = _local_content(DOC, "juro lealtad al Clan Escorpion")
    out = run_pipeline(
        _payload([_membership_segment()], config={"local_llm_enabled": True}),
        local_transport=_local_transport(content),
    )
    r = out["results"][0]
    assert r["local_status"] == PROVIDER_EXECUTED
    assert r["local"] is not None
    assert r["local"]["validation_status"] == "VALID"
    assert out["summary"]["local_calls_simulated"] == 1


def test_local_provider_invalid_json():
    out = run_pipeline(
        _payload([_membership_segment()], config={"local_llm_enabled": True}),
        local_transport=_local_transport("esto no es json"),
    )
    r = out["results"][0]
    assert r["local"]["validation_status"] == "INVALID"
    # Un proveedor presente pero invalido invalida el consenso.
    assert r["consensus"]["state"] == "INVALID_RESPONSES"


def test_local_provider_timeout_isolated():
    from external_ai.errors import ProviderTimeoutError

    def transport(messages):
        raise ProviderTimeoutError("timeout simulado")

    out = run_pipeline(
        _payload([_membership_segment()], config={"local_llm_enabled": True}),
        local_transport=transport,
    )
    r = out["results"][0]
    # Timeout del proveedor: recomendacion local INVALID, consenso no se rompe.
    assert r["local"]["validation_status"] == "INVALID"
    assert r["consensus"]["state"] == "INVALID_RESPONSES"


def test_local_enabled_without_transport_fails_closed():
    # Habilitado pero SIN transporte ni endpoint: fallo cerrado, sin red.
    out = run_pipeline(
        _payload([_membership_segment()], config={"local_llm_enabled": True}),
        local_transport=None,
    )
    r = out["results"][0]
    assert r["local"] is None
    assert r["local_status"] == PROVIDER_FAILED_CLOSED
    assert out["provider_status"]["local_llm"] == PROVIDER_FAILED_CLOSED


# ---------------------------------------------------------------------------
# 11. Proveedor EXTERNO: ausente / valido / invalido
# ---------------------------------------------------------------------------
class _FakeProvider:
    provider_name = "nvidia"

    def __init__(self, content):
        self._content = content

    def _post_chat(self, model, messages):
        return ({"choices": [{"message": {"content": self._content}}]}, 42)


def _external_content(cid, evidence, verdict="confirm", **over):
    v = {
        "candidate_id": cid,
        "verdict": verdict,
        "predicate": "MEMBER_OF",
        "subject_type": "Character",
        "object_type": "Faction",
        "negated": False,
        "evidence_text": evidence,
        "evidence_start": DOC.find(evidence),
        "evidence_end": DOC.find(evidence) + len(evidence),
        "confidence": 0.9,
        "reason_codes": [],
        "explanation": "ok",
    }
    v.update(over)
    return json.dumps({"verdicts": [v]})


def test_external_provider_valid_injected():
    cid = "Bayushi Hisao|MEMBER_OF|Clan Escorpion"
    provider = _FakeProvider(_external_content(cid, "juro lealtad al Clan Escorpion"))
    out = run_pipeline(
        _payload([_membership_segment()], config={"external_ai_enabled": True}),
        external_provider=provider,
    )
    r = out["results"][0]
    assert r["external_status"] == PROVIDER_EXECUTED
    assert r["external"] is not None
    assert out["summary"]["external_calls_simulated"] == 1


def test_external_provider_invalid_response():
    cid = "Bayushi Hisao|MEMBER_OF|Clan Escorpion"
    # Evidencia inexistente en el segmento => verdicto invalido.
    provider = _FakeProvider(_external_content(cid, "frase que no existe", evidence_start=0, evidence_end=5))
    out = run_pipeline(
        _payload([_membership_segment()], config={"external_ai_enabled": True}),
        external_provider=provider,
    )
    r = out["results"][0]
    assert r["external"]["state"] == "INVALID_RESPONSES"
    assert r["consensus"]["state"] == "INVALID_RESPONSES"


def test_external_provider_absent():
    out = run_pipeline(_payload([_membership_segment()]))
    assert out["provider_status"]["external_ai"] == PROVIDER_NOT_EXECUTED
    assert out["results"][0]["external"] is None


# ---------------------------------------------------------------------------
# 12. Cero red / cero escritura / cero Neo4j
# ---------------------------------------------------------------------------
def test_zero_network(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("el pipeline NO debe abrir sockets en dry-run")

    monkeypatch.setattr(socket, "socket", _boom)
    out = run_pipeline(_payload([_membership_segment()]))
    assert out["summary"]["candidates_evaluated"] == 1


def test_zero_neo4j():
    # El pipeline nunca importa un driver Neo4j. Se comprueba en un proceso LIMPIO
    # (sys.modules del proceso de tests puede estar contaminado por otros tests).
    import subprocess

    code = (
        "import sys; sys.path.insert(0, %r);"
        "from relations.pipeline import run_pipeline;"
        "run_pipeline({'document':'d','workspace':'w','segments':[]});"
        "assert 'neo4j' not in sys.modules, 'neo4j fue importado';"
        "print('ok')"
    ) % str(_APP)
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert "ok" in res.stdout

    import relations.pipeline as mod
    src = Path(mod.__file__).read_text(encoding="utf-8").lower()
    assert "import neo4j" not in src
    assert "from neo4j" not in src


def test_zero_write_no_write_flags():
    # No existe ningun flag de escritura: la config los rechaza EXPLICITAMENTE con
    # un error especifico de "escritura/apply" (distinto del de clave desconocida).
    with pytest.raises(PipelineError, match="escritura"):
        config_from_dict({"write": True})
    with pytest.raises(PipelineError, match="escritura"):
        run_pipeline(_payload([_membership_segment()], config={"apply": True}))


def test_dry_run_flag_always_true():
    out = run_pipeline(_payload([_membership_segment()]))
    assert out["dry_run"] is True


# ---------------------------------------------------------------------------
# 13. Sin autoaprobacion
# ---------------------------------------------------------------------------
def test_no_autoapproval_anywhere():
    content = _local_content(DOC, "juro lealtad al Clan Escorpion")
    out = run_pipeline(
        _payload([_membership_segment()], config={"local_llm_enabled": True}),
        local_transport=_local_transport(content),
    )
    for r in out["results"]:
        assert r["consensus"]["recommendation"] in ("propose", "reject", "human")
    blob = to_json(out).upper()
    assert "AUTO_APPROVED" not in blob
    assert "APPROVED" not in blob


# ---------------------------------------------------------------------------
# 14. Observabilidad redactada
# ---------------------------------------------------------------------------
def test_observability_redacted_no_secrets():
    # El documento contiene un token con forma de secreto; la traza no lo filtra.
    text = "Aria pertenece al Clan. token=sk-ABCDEFGHIJKLMNOPQRSTUVWX secreto."
    a = text.find("Aria")
    o = text.find("Clan")
    seg = _seg(text, "s1", [
        _ent("Aria", a, a + 4, "Character"),
        _ent("Clan", o, o + 4, "Faction"),
    ])
    out = run_pipeline(_payload([seg]))
    from relations.observability import find_secrets

    trace_blob = json.dumps(out["observability"], ensure_ascii=False)
    assert find_secrets(trace_blob) == []
    # La traza no vuelca texto en claro del segmento, solo metadatos/hashes.
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in trace_blob


# ---------------------------------------------------------------------------
# 15. Serializacion JSON / JSONL determinista
# ---------------------------------------------------------------------------
def test_json_and_jsonl_serialization():
    out = run_pipeline(_payload([_membership_segment()]))
    blob = to_json(out)
    assert json.loads(blob)["execution_id"] == out["execution_id"]
    jsonl = to_jsonl(out)
    lines = jsonl.splitlines()
    assert json.loads(lines[0])["type"] == "execution"
    assert json.loads(lines[1])["type"] == "candidate"
    # Determinismo de la serializacion.
    assert to_jsonl(run_pipeline(_payload([_membership_segment()]))) == jsonl


# ---------------------------------------------------------------------------
# 16. Limites configurables
# ---------------------------------------------------------------------------
def test_limit_segments_per_doc():
    segs = [_membership_segment(f"s{i}") for i in range(3)]
    with pytest.raises(PipelineError):
        run_pipeline(_payload(segs, config={"max_segments_per_doc": 2}))


def test_limit_entities_per_segment():
    seg = _membership_segment()
    out = run_pipeline(_payload([seg], config={"max_entities_per_segment": 1}))
    segres = out["documents"][0]["segments"][0]
    assert segres["status"] == "failed"
    assert any(e["code"] == "too_many_entities" for e in segres["errors"])


def test_limit_text_chars():
    seg = _seg("x" * 100, "s1", [])
    out = run_pipeline(_payload([seg], config={"max_text_chars": 10}))
    segres = out["documents"][0]["segments"][0]
    assert any(e["code"] == "segment_text_too_large" for e in segres["errors"])


# ---------------------------------------------------------------------------
# 17. Inmutabilidad de la entrada
# ---------------------------------------------------------------------------
def test_input_not_mutated():
    seg = _membership_segment()
    payload = _payload([seg])
    snapshot = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    run_pipeline(payload)
    assert json.dumps(payload, sort_keys=True, ensure_ascii=False) == snapshot


# ---------------------------------------------------------------------------
# MUTATION MATRIX (documentacion viva de las 12 mutaciones)
# ---------------------------------------------------------------------------
MUTATION_MATRIX = {
    1: ("permitir workspace vacio", "test_workspace_empty_raises"),
    2: ("quitar limite de pares", "test_many_entities_combinatorial_limit"),
    3: ("permitir mezcla de workspaces", "test_workspace_mixed_rejected"),
    4: ("aceptar evidencia inexistente", "test_empty_evidence_rejected"),
    5: ("ignorar negacion", "test_negation_preserved"),
    6: ("ignorar temporalidad", "test_temporality_preserved"),
    7: ("proveedor ausente -> rechazo", "test_local_provider_absent_not_rejection"),
    8: ("habilitar autoaprobacion", "test_no_autoapproval_anywhere"),
    9: ("escribir en dry-run", "test_zero_write_no_write_flags"),
    10: ("IDs aleatorios", "test_deterministic_same_input"),
    11: ("resultado dependiente del orden", "test_segment_order_invariant"),
    12: ("conectar a endpoint por defecto", "test_local_enabled_without_transport_fails_closed"),
}


def test_mutation_matrix_is_documented():
    assert set(MUTATION_MATRIX) == set(range(1, 13))
    this_module = sys.modules[__name__]
    for num, (mutation, test_name) in MUTATION_MATRIX.items():
        assert hasattr(this_module, test_name), f"falta el test {test_name} para mutacion {num}"
