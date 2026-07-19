# -*- coding: utf-8 -*-
"""Tests del runner/comparador del benchmark de relaciones (B2).

Verifican que:
  * el corpus B1 se carga y su integridad es correcta;
  * el runner usa el pipeline R8 **REAL** (`relations.pipeline.run_pipeline`),
    NO un espejo/reimplementacion;
  * el comparador es correcto y determinista (par, predicado, tipo, direccion,
    evidencia, negacion, temporalidad, workspace);
  * la ejecucion del pipeline es determinista (mismos hashes/IDs/predicciones) y
    entradas distintas producen hashes distintos.

NO llaman a Ollama, NVIDIA, Neo4j ni a red: el pipeline corre en dry-run con los
proveedores deshabilitados.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import relations.pipeline as r8_pipeline  # noqa: E402
from relations.benchmark import (  # noqa: E402
    build_payload,
    derive_entities,
    extract_predictions,
    load_corpus,
    match_predictions,
    run_benchmark,
    run_source,
    structural_flags,
)
from relations.benchmark import runner as bench_runner  # noqa: E402
from relations.benchmark import metrics as bench_metrics  # noqa: E402
from relations.benchmark import report as bench_report  # noqa: E402


@pytest.fixture(scope="module")
def corpus():
    return load_corpus()


# ---------------------------------------------------------------------------
# Corpus e integridad
# ---------------------------------------------------------------------------
def test_corpus_valido(corpus):
    assert corpus.manifest["source_count"] == len(corpus.sources) == 16
    assert corpus.manifest["relation_count"] == len(corpus.relations) == 54
    # load_corpus con verify=True (por defecto) ya recalculo y comparo los sha256.
    for s in corpus.manifest["sources"]:
        assert corpus.corpus_hashes[s["id"]] == s["sha256"]


def test_corpus_hash_invalido_detectado(tmp_path, corpus):
    # Alterar una fuente debe hacer fallar la verificacion de integridad.
    import json
    import shutil

    dst = tmp_path / "corpus"
    shutil.copytree(corpus.corpus_dir, dst)
    src_file = dst / corpus.manifest["sources"][0]["path"]
    src_file.write_text(src_file.read_text(encoding="utf-8") + " XX", encoding="utf-8")
    with pytest.raises(bench_runner.BenchmarkError):
        load_corpus(dst, verify=True)


# ---------------------------------------------------------------------------
# El runner usa el pipeline R8 REAL (no un espejo)
# ---------------------------------------------------------------------------
def test_usa_pipeline_r8_real():
    # La referencia del runner ES la funcion real del modulo del pipeline.
    assert bench_runner.run_pipeline is r8_pipeline.run_pipeline
    # El modulo del runner no define su propia run_pipeline (no es un espejo).
    assert "run_pipeline" not in bench_runner.__dict__ or (
        bench_runner.__dict__["run_pipeline"] is r8_pipeline.run_pipeline
    )
    # Firma del pipeline real intacta.
    import inspect

    params = list(inspect.signature(r8_pipeline.run_pipeline).parameters)
    assert params[0] == "payload"
    assert {"config", "local_transport", "external_provider"}.issubset(set(params))


def test_run_source_produce_salida_real(corpus):
    sr = run_source(corpus, "src-01")
    out = sr.output
    # Claves canonicas de la salida REAL del pipeline.
    for key in ("execution_id", "dry_run", "schema", "versions", "provider_status",
                "summary", "documents", "results", "result_hash"):
        assert key in out
    assert out["dry_run"] is True
    # Proveedores jamas ejecutados (sin red, sin Ollama/NVIDIA).
    assert out["provider_status"]["local_llm"] == "NOT_EXECUTED"
    assert out["provider_status"]["external_ai"] == "NOT_EXECUTED"
    assert sr.predictions, "src-01 debe producir predicciones"


# ---------------------------------------------------------------------------
# Derivacion de entidades
# ---------------------------------------------------------------------------
def test_derivacion_entidades_offsets_reales(corpus):
    sid = "src-01"
    text = corpus.sources[sid]
    ents, notes = derive_entities(sid, text, corpus.relations)
    assert ents
    for e in ents:
        # Los offsets recortan exactamente el texto de la mencion en la fuente.
        assert text[e["start"]:e["end"]] == e["text"]
    # Determinismo del orden.
    ents2, _ = derive_entities(sid, text, list(reversed(corpus.relations)))
    assert ents == ents2


# ---------------------------------------------------------------------------
# Comparador: casos base
# ---------------------------------------------------------------------------
def _gt(**over):
    base = {
        "relation_id": "rel-x", "source_id": "src-99", "workspace": "eldoria",
        "segment_id": "src-99#s1", "subject_id": "a", "subject_text": "A",
        "subject_type": "Character", "predicate": "MEMBER_OF", "object_id": "b",
        "object_text": "B", "object_type": "Faction", "evidence_text": "A es miembro de B",
        "evidence_start": 0, "evidence_end": 17, "negated": False,
        "temporal_status": "PRESENT", "epistemic_status": "ASSERTED",
        "direction": "SUBJECT_TO_OBJECT", "expected_decision": "ACCEPT",
        "annotator_notes": "",
    }
    base.update(over)
    return base


def _pred(**over):
    base = {
        "candidate_id": "c1", "source_id": "src-99", "workspace": "eldoria",
        "subject_id": "a", "object_id": "b", "subject_type": "Character",
        "object_type": "Faction", "predicate": "MEMBER_OF",
        "direction": "SUBJECT_TO_OBJECT", "negated": False, "temporal_scope": None,
        "epistemic_status": "ASSERTED", "evidence_text": "A es miembro de B",
        "evidence_start": 0, "evidence_end": 17, "consensus_state": "PARTIAL_CONSENSUS",
        "recommendation": "propose",
    }
    base.update(over)
    return base


def test_resultado_vacio(corpus):
    # Sin predicciones: todo son FN, ningun TP/FP.
    match = match_predictions([], corpus.relations)
    assert match.tp == 0
    assert match.fp == 0
    assert match.fn == len(corpus.relations) == 54
    glob = bench_metrics.global_metrics(match)
    assert glob["recall"] == 0.0 and glob["precision"] == 0.0


def test_prediccion_duplicada_no_cuenta_doble():
    gt = [_gt()]
    preds = [_pred(candidate_id="c1"), _pred(candidate_id="c2")]
    match = match_predictions(preds, gt)
    assert match.tp == 1          # una sola relacion de GT -> un solo TP
    assert match.fp == 1          # la duplicada sobra -> FP
    assert match.fn == 0


def test_par_correcto_es_tp_aunque_invertido():
    # Sujeto/objeto intercambiados textualmente: sigue siendo el mismo par.
    match = match_predictions([_pred(subject_id="b", object_id="a")], [_gt()])
    assert match.tp == 1


def test_tipo_incorrecto():
    flags = structural_flags(_pred(subject_type="Object", object_type="Object"), _gt())
    assert flags["types_correct"] is False
    flags_ok = structural_flags(_pred(), _gt())
    assert flags_ok["types_correct"] is True


def test_direccion_incorrecta():
    flags = structural_flags(_pred(direction="UNDIRECTED"), _gt())
    assert flags["direction_correct"] is False
    flags_ok = structural_flags(_pred(direction="SUBJECT_TO_OBJECT"), _gt())
    assert flags_ok["direction_correct"] is True


def test_evidencia_incorrecta():
    # Span de evidencia sin solape -> evidencia y offsets incorrectos.
    flags = structural_flags(_pred(evidence_start=500, evidence_end=520), _gt())
    assert flags["evidence_correct"] is False
    assert flags["offsets_correct"] is False
    flags_ok = structural_flags(_pred(), _gt())
    assert flags_ok["evidence_correct"] is True
    assert flags_ok["offsets_correct"] is True


def test_negacion_incorrecta():
    flags = structural_flags(_pred(negated=True), _gt(negated=False))
    assert flags["negation_correct"] is False
    flags_ok = structural_flags(_pred(negated=True), _gt(negated=True))
    assert flags_ok["negation_correct"] is True


def test_temporalidad_incorrecta():
    # El matching temporal es ahora CLASS-AWARE (clasificacion, no mera deteccion):
    # se deriva la CLASE del temporal_scope (temporality.temporal_status_of) y se
    # exige IGUALDAD con la clase del ground truth.
    # 1) Sin alcance (None) frente a GT PAST: None no casa con ninguna clase -> False.
    flags = structural_flags(_pred(temporal_scope=None), _gt(temporal_status="PAST"))
    assert flags["temporal_correct"] is False
    # 2) Scope que SI clasifica a PAST frente a GT PAST -> True (misma clase).
    flags_ok = structural_flags(
        _pred(temporal_scope="PAST | markers=fue"), _gt(temporal_status="PAST")
    )
    assert flags_ok["temporal_correct"] is True
    # 3) Discriminacion de clase: un scope que clasifica a FUTURE frente a GT PAST
    #    NO casa (clase distinta), pese a tener senal temporal.
    flags_future = structural_flags(
        _pred(temporal_scope="será nombrado"), _gt(temporal_status="PAST")
    )
    assert flags_future["temporal_correct"] is False


def test_workspace_incorrecto():
    flags = structural_flags(_pred(workspace="umbral"), _gt(workspace="eldoria"))
    assert flags["workspace_correct"] is False


def test_epistemico_incorrecto():
    flags = structural_flags(_pred(epistemic_status="ASSERTED"), _gt(epistemic_status="RUMORED"))
    assert flags["epistemic_correct"] is False


def test_predicado_estricto_degrada_a_fp_fn():
    # Par correcto pero predicado erroneo: existe (TP) pero estricto lo penaliza.
    match = match_predictions([_pred(predicate="RELATED_TO")], [_gt(predicate="MEMBER_OF")])
    assert match.tp == 1
    strict = bench_metrics.strict_metrics(match)
    assert strict["tp"] == 0
    assert strict["fp"] == 1 and strict["fn"] == 1


# ---------------------------------------------------------------------------
# Determinismo
# ---------------------------------------------------------------------------
def test_ejecucion_repetida_determinista(corpus):
    a = run_source(corpus, "src-04")
    b = run_source(corpus, "src-04")
    assert a.output["result_hash"] == b.output["result_hash"]
    assert a.output["execution_id"] == b.output["execution_id"]
    assert a.predictions == b.predictions


def test_hashes_distintos_para_fuentes_distintas(corpus):
    a = run_source(corpus, "src-01")
    b = run_source(corpus, "src-02")
    assert a.output["result_hash"] != b.output["result_hash"]
    assert a.output["execution_id"] != b.output["execution_id"]


def test_comparador_determinista_e_independiente_del_orden(corpus):
    run = run_benchmark(corpus, mode="baseline1")
    preds = run.predictions
    m1 = match_predictions(preds, corpus.relations)
    m2 = match_predictions(list(reversed(preds)), list(reversed(corpus.relations)))
    assert bench_metrics.global_metrics(m1) == bench_metrics.global_metrics(m2)
    assert m1.tp == m2.tp and m1.fp == m2.fp and m1.fn == m2.fn


def test_build_report_determinista_y_gates(corpus):
    run = run_benchmark(corpus, mode="baseline1")
    report = bench_report.build_report(corpus, run, check_determinism=True)
    # Determinismo verificado dentro del propio informe.
    assert report["determinism"]["deterministic"] is True
    # Gates duros presentes y en PASS.
    assert report["gates"]["determinism"]["status"] == "PASS"
    assert report["gates"]["workspace_contamination"]["status"] == "PASS"
    # Dictamen pertenece al vocabulario cerrado y NO es "APTO PARA INGESTA REAL".
    assert report["verdict"] in bench_report.VERDICTS
    assert report["verdict"] != "APTO PARA INGESTA REAL"
    # Confirmaciones de seguridad.
    assert report["providers"]["network"] == "none"
    assert "NOT_EXECUTED" in report["providers"]["local_llm"]
    assert "NOT_EXECUTED" in report["providers"]["external_ai"]


def test_contaminacion_workspaces_rechazada_por_pipeline():
    # Mezclar workspaces en un segmento debe ser rechazado por el pipeline REAL
    # (defensa de contaminacion entre workspaces), no producir una relacion.
    payload = build_payload(
        "src-mix", "A pertenece a B", "eldoria",
        [
            {"id": "a", "text": "A", "type": "Character", "start": 0, "end": 1},
            {"id": "b", "text": "B", "type": "Faction", "start": 13, "end": 14},
        ],
    )
    payload["segments"][0]["workspace"] = "umbral"  # distinto del pipeline
    out = r8_pipeline.run_pipeline(payload)
    codes = {e.get("code") for e in out["errors"]}
    assert "workspace_mismatch" in codes
    assert out["results"] == []
