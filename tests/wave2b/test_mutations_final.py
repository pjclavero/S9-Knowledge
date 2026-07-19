# -*- coding: utf-8 -*-
"""QA final OLA 2B (Lote 3) — MUTATION checks FINALES (objetivo 20/20).

Cada test comprueba que una regla del PRODUCTO REAL es load-bearing: si el
producto regresara (relajara la regla), el test FALLARIA. Se ejercita el
producto importado, sin espejos ni logica duplicada:

  * M1-M12  : reproducidas a nivel del pipeline R8 real (`relations.pipeline`).
  * M13-M20 : nuevas, contra el benchmark B2 real (`relations.benchmark`) y el
              contrato de determinismo/identidad del pipeline.

Ollama/NVIDIA reales NUNCA se ejecutan; sin red; sin escritura.
"""
from __future__ import annotations

import copy
import shutil
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _final_helpers import find_ent, payload, simple_payload  # noqa: E402

from relations import pipeline as _real_pipeline  # noqa: E402
from relations.pipeline import (  # noqa: E402
    PROVIDER_FAILED_CLOSED,
    PROVIDER_NOT_EXECUTED,
    PipelineConfig,
    PipelineError,
    config_from_dict,
    run_pipeline,
)
from relations.benchmark import (  # noqa: E402
    build_report,
    load_corpus,
    match_predictions,
    run_benchmark,
)
from relations.benchmark import runner as _bench_runner  # noqa: E402
from relations.benchmark.matching import structural_flags  # noqa: E402
from relations.benchmark.runner import BenchmarkError  # noqa: E402


@pytest.fixture(scope="module")
def corpus():
    return load_corpus(verify=True)


@pytest.fixture(scope="module")
def bench_run(corpus):
    return run_benchmark(corpus, mode="baseline1")


def _ws_ents(text):
    return [find_ent("e:aria", "Aria", "Character", text),
            find_ent("e:orden", "Orden del Alba", "Faction", text)]


# ===========================================================================
# M1-M12  — reproducidas contra el pipeline R8 REAL
# ===========================================================================
@pytest.mark.mutation
def test_m01_empty_workspace_rejected():
    """M1: workspace vacio. Si el pipeline lo aceptara, escribiria sin espacio."""
    with pytest.raises(PipelineError):
        run_pipeline({"source_id": "d", "workspace": "", "segments": []})
    # Control: workspace valido no es rechazado.
    assert run_pipeline(simple_payload())["workspace"] == "ws1"


@pytest.mark.mutation
def test_m02_pair_limit_enforced():
    """M2: sin limite de pares. El limite real TRUNCA; si se quitara, explota."""
    text = ("Aria Blan Cira Dorn Enna Fael Gorm se reunieron en el Consejo del norte "
            "para tratar la guerra que amenazaba las tierras libres del reino.")
    ents = [find_ent(f"e:{n}", n, "Character", text)
            for n in ("Aria", "Blan", "Cira", "Dorn", "Enna", "Fael", "Gorm")]
    out = run_pipeline(payload(text, ents), config=PipelineConfig(max_pairs_per_segment=4))
    seg = out["documents"][0]["segments"][0]
    assert seg["truncated"] is True
    assert len(seg["pairs"]) <= 4


@pytest.mark.mutation
def test_m03_workspace_mix_rejected():
    """M3: mezcla de workspaces. El segmento de otro workspace se rechaza."""
    p = simple_payload(workspace="ws-a")
    p["segments"][0]["workspace"] = "ws-b"
    out = run_pipeline(p)
    assert any(e["code"] == "workspace_mismatch" for e in out["errors"])
    assert out["results"] == []


@pytest.mark.mutation
def test_m04_nonexistent_evidence_rejected():
    """M4: evidencia inexistente. Toda evidencia emitida es subcadena LITERAL."""
    text = "Aria es miembro de la Orden del Alba."
    out = run_pipeline(payload(text, _ws_ents(text)))
    assert out["results"]
    for rec in out["results"]:
        c = rec["candidate"]
        # Si el pipeline inventara evidencia, esta igualdad se romperia.
        assert text[c["evidence_start"]:c["evidence_end"]] == c["evidence_text"]
        assert c["evidence_text"].strip() != ""


@pytest.mark.mutation
def test_m05_negation_not_ignored():
    """M5: ignorar negacion. Una relacion negada se marca negated=True."""
    text = "Aria no es miembro de la Orden del Alba."
    out = run_pipeline(payload(text, _ws_ents(text)))
    assert out["results"][0]["candidate"]["negated"] is True
    # Control: sin negacion, negated=False.
    pos = "Aria es miembro de la Orden del Alba."
    assert run_pipeline(payload(pos, _ws_ents(pos)))["results"][0]["candidate"]["negated"] is False


@pytest.mark.mutation
def test_m06_temporality_not_ignored():
    """M6: ignorar temporalidad. Un marcador temporal produce temporal_scope."""
    text = "En 1123 Aria fue miembro de la Orden del Alba."
    out = run_pipeline(payload(text, _ws_ents(text)))
    assert out["results"][0]["candidate"]["temporal_scope"] is not None
    # Control: sin marcador temporal, temporal_scope=None.
    plain = "Aria es miembro de la Orden del Alba."
    assert run_pipeline(payload(plain, _ws_ents(plain)))["results"][0]["candidate"]["temporal_scope"] is None


@pytest.mark.mutation
def test_m07_absent_provider_not_a_reject():
    """M7: proveedor ausente = rechazo. Ausente NO invalida el candidato."""
    out = run_pipeline(simple_payload())
    assert out["provider_status"]["local_llm"] == PROVIDER_NOT_EXECUTED
    assert out["results"], "el candidato heuristico existe sin proveedores"


@pytest.mark.mutation
def test_m08_no_auto_approval():
    """M8: autoaprobacion. Ninguna recomendacion es APPROVED/AUTO_APPROVED."""
    out = run_pipeline(simple_payload())
    assert out["dry_run"] is True
    for rec in out["results"]:
        reco = str(rec["consensus"].get("recommendation", "")).upper()
        assert "APPROV" not in reco
        assert reco in {"PROPOSE", "REJECT", "HUMAN"}


@pytest.mark.mutation
def test_m09_write_in_dryrun_rejected():
    """M9: escritura en dry-run. Flags de escritura en config -> rechazadas."""
    for bad in ("write", "apply", "persist", "commit", "auto_approve"):
        with pytest.raises(PipelineError):
            config_from_dict({bad: True})
    assert run_pipeline(simple_payload())["dry_run"] is True


@pytest.mark.mutation
def test_m10_ids_not_random():
    """M10: IDs aleatorios. execution_id/result_hash derivan del contenido."""
    a = run_pipeline(simple_payload())
    b = run_pipeline(simple_payload())
    assert a["execution_id"] == b["execution_id"]
    assert a["result_hash"] == b["result_hash"]
    # Distinto input -> distinto id (no es una constante fija).
    other = run_pipeline(simple_payload(workspace="ws-otro"))
    assert other["execution_id"] != a["execution_id"]


@pytest.mark.mutation
def test_m11_result_order_independent():
    """M11: resultado dependiente del orden. Reordenar segmentos no cambia la salida."""
    text = "Aria es miembro de la Orden del Alba."
    ents = _ws_ents(text)
    p = {"source_id": "d1", "workspace": "ws1", "segments": [
        {"segment_id": "sA", "text": text, "workspace": "ws1", "source_id": "d1", "entities": ents},
        {"segment_id": "sB", "text": text, "workspace": "ws1", "source_id": "d1", "entities": ents},
    ]}
    p_rev = copy.deepcopy(p)
    p_rev["segments"] = list(reversed(p_rev["segments"]))
    assert run_pipeline(p)["result_hash"] == run_pipeline(p_rev)["result_hash"]


@pytest.mark.mutation
def test_m12_default_endpoint_fails_closed(monkeypatch):
    """M12: endpoint por defecto. Proveedor habilitado sin transporte -> FAILED_CLOSED,
    sin abrir un solo socket (no hay endpoint real por defecto)."""
    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("no debe abrir socket sin transporte")

    monkeypatch.setattr(socket, "socket", _boom)
    cfg = PipelineConfig(local_llm_enabled=True, external_ai_enabled=True)
    out = run_pipeline(simple_payload(), config=cfg)
    assert out["provider_status"]["local_llm"] == PROVIDER_FAILED_CLOSED
    assert out["provider_status"]["external_ai"] == PROVIDER_FAILED_CLOSED


# ===========================================================================
# M13-M20  — NUEVAS, contra el benchmark B2 REAL y el contrato de identidad
# ===========================================================================
@pytest.mark.mutation
def test_m13_wrong_ground_truth_hash_rejected(tmp_path, corpus):
    """M13: ground truth con hash incorrecto aceptado. El sha256 del GT en el
    manifest es load-bearing: manipularlo -> BenchmarkError."""
    dst = tmp_path / "corpus"
    shutil.copytree(corpus.corpus_dir, dst)
    gt = dst / "ground_truth" / "relations.json"
    data = gt.read_text(encoding="utf-8")
    gt.write_text(data + "\n ", encoding="utf-8")  # byte de mas -> hash distinto
    with pytest.raises(BenchmarkError):
        load_corpus(dst, verify=True)
    # Control: el corpus intacto SI verifica.
    assert load_corpus(corpus.corpus_dir, verify=True).manifest["source_count"] == 16


@pytest.mark.mutation
def test_m14_evidence_outside_text_not_accepted(bench_run, corpus):
    """M14: evidencia fuera del texto aceptada. Toda evidencia del benchmark real
    cae DENTRO del texto de su fuente y es literal."""
    for sr in bench_run.source_runs:
        text = corpus.sources[sr.source_id]
        for pred in sr.predictions:
            assert 0 <= pred["evidence_start"] < pred["evidence_end"] <= len(text)
            assert text[pred["evidence_start"]:pred["evidence_end"]] == pred["evidence_text"]


@pytest.mark.mutation
def test_m15_duplicate_prediction_not_double_counted(bench_run, corpus):
    """M15: prediccion duplicada contada dos veces. El matching 1:1 impide que una
    prediccion duplicada infle los TP; el duplicado pasa a FP."""
    preds = bench_run.predictions
    base = match_predictions(preds, corpus.relations)
    # Duplicar una prediccion existente (misma clave) NO debe subir los TP.
    dup = copy.deepcopy(preds[0])
    dup["candidate_id"] = dup["candidate_id"] + "-DUP"
    inflated = match_predictions(preds + [dup], corpus.relations)
    assert inflated.tp == base.tp
    assert inflated.fp == base.fp + 1  # el duplicado es un falso positivo


@pytest.mark.mutation
def test_m16_direction_not_ignored():
    """M16: direccion ignorada. structural_flags distingue direccion correcta de incorrecta."""
    gt = {"predicate": "MEMBER_OF", "evidence_start": 0, "evidence_end": 10,
          "temporal_status": "PRESENT", "direction": "SUBJECT_TO_OBJECT",
          "negated": False, "epistemic_status": "ASSERTED", "expected_decision": "ACCEPT",
          "subject_id": "a", "object_id": "b", "subject_type": "Character",
          "object_type": "Faction", "workspace": "ws1"}
    common = dict(predicate="MEMBER_OF", evidence_start=0, evidence_end=10,
                  temporal_scope=None, negated=False, epistemic_status="ASSERTED",
                  subject_id="a", object_id="b", subject_type="Character",
                  object_type="Faction", workspace="ws1", recommendation="propose")
    ok = structural_flags({**common, "direction": "SUBJECT_TO_OBJECT"}, gt)
    bad = structural_flags({**common, "direction": "OBJECT_TO_SUBJECT"}, gt)
    assert ok["direction_correct"] is True
    assert bad["direction_correct"] is False


@pytest.mark.mutation
def test_m17_negation_not_ignored_in_benchmark():
    """M17: negacion ignorada en benchmark. negation_correct refleja el desajuste real."""
    gt = {"predicate": "MEMBER_OF", "evidence_start": 0, "evidence_end": 10,
          "temporal_status": "PRESENT", "direction": "UNDIRECTED", "negated": True,
          "epistemic_status": "ASSERTED", "expected_decision": "REJECT",
          "subject_id": "a", "object_id": "b", "subject_type": "Character",
          "object_type": "Faction", "workspace": "ws1"}
    common = dict(predicate="MEMBER_OF", evidence_start=0, evidence_end=10,
                  temporal_scope=None, direction="UNDIRECTED", epistemic_status="ASSERTED",
                  subject_id="a", object_id="b", subject_type="Character",
                  object_type="Faction", workspace="ws1", recommendation="reject")
    assert structural_flags({**common, "negated": True}, gt)["negation_correct"] is True
    assert structural_flags({**common, "negated": False}, gt)["negation_correct"] is False


@pytest.mark.mutation
def test_m18_temporality_not_ignored_in_benchmark():
    """M18: temporalidad ignorada en benchmark. temporal_correct exige detectar el
    marcador exactamente cuando el ground truth lo tiene (estado PAST)."""
    gt = {"predicate": "MEMBER_OF", "evidence_start": 0, "evidence_end": 10,
          "temporal_status": "PAST", "direction": "UNDIRECTED", "negated": False,
          "epistemic_status": "ASSERTED", "expected_decision": "ACCEPT",
          "subject_id": "a", "object_id": "b", "subject_type": "Character",
          "object_type": "Faction", "workspace": "ws1"}
    common = dict(predicate="MEMBER_OF", evidence_start=0, evidence_end=10, negated=False,
                  direction="UNDIRECTED", epistemic_status="ASSERTED", subject_id="a",
                  object_id="b", subject_type="Character", object_type="Faction",
                  workspace="ws1", recommendation="propose")
    # Detecta marcador (scope no nulo) -> correcto; no detecta -> incorrecto.
    assert structural_flags({**common, "temporal_scope": "1123"}, gt)["temporal_correct"] is True
    assert structural_flags({**common, "temporal_scope": None}, gt)["temporal_correct"] is False


@pytest.mark.mutation
def test_m19_pipeline_is_real_not_a_fixture(bench_run):
    """M19: pipeline no real sustituido por fixture. El runner del benchmark usa el
    `run_pipeline` REAL (identidad de objeto) y emite el esquema del pipeline."""
    assert _bench_runner.run_pipeline is _real_pipeline.run_pipeline
    for sr in bench_run.source_runs:
        assert sr.output["schema"] == "relation-pipeline/v1"
        assert sr.output["versions"]["pipeline"] == _real_pipeline.PIPELINE_VERSION
        # execution_id es un hash de 32 hex (derivado de contenido, no un fixture).
        assert len(sr.output["execution_id"]) == 32
        int(sr.output["execution_id"], 16)


@pytest.mark.mutation
def test_m20_nondeterministic_result_rejected(corpus, bench_run):
    """M20: resultado no determinista aceptado. El gate DURO de determinismo del
    benchmark exige que dos ejecuciones reales coincidan (hashes, metricas, preds)."""
    report = build_report(corpus, bench_run, check_determinism=True)
    det = report["determinism"]
    assert det["deterministic"] is True
    assert det["hashes_equal"] and det["metrics_equal"] and det["predictions_equal"]
    assert report["gates"]["determinism"]["status"] == "PASS"
    assert report["gates"]["determinism"]["hard"] is True
