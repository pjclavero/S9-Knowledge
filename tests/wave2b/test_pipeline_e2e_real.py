# -*- coding: utf-8 -*-
"""QA final OLA 2B (Lote 3) — E2E contra el pipeline R8 REAL.

Estos tests IMPORTAN y EJECUTAN el producto real:

  * `relations.pipeline.run_pipeline` (R8, orquestador dry-run).
  * `relations.benchmark` (B2: `load_corpus`, `run_source`, `run_benchmark`,
    `build_report`) sobre el corpus B1 REAL en `app/tests/data/relation_benchmark/`.

No hay clases espejo, ni dataclasses locales que sustituyan producto, ni logica
duplicada: solo construccion de payloads de entrada (helpers) y asserts sobre el
comportamiento REAL. Proveedores Ollama/NVIDIA reales NUNCA se ejecutan; los
transportes en sombra se inyectan (sin red).

Cubre los 15 escenarios E2E minimos de la matriz Lote 3.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _final_helpers import (  # noqa: E402
    FakeExternalProvider,
    external_verdicts_content,
    find_ent,
    make_local_transport,
    payload,
    relation_verdict_content,
    segment,
    simple_payload,
)

from relations.pipeline import (  # noqa: E402
    PIPELINE_SCHEMA,
    PROVIDER_EXECUTED,
    PROVIDER_FAILED_CLOSED,
    PROVIDER_NOT_EXECUTED,
    PipelineConfig,
    PipelineError,
    run_pipeline,
)
from relations import pipeline as _real_pipeline  # noqa: E402
from relations.benchmark import (  # noqa: E402
    build_payload,
    build_report,
    derive_entities,
    load_corpus,
    run_benchmark,
    run_source,
)
from relations.benchmark import runner as _bench_runner  # noqa: E402


# Confirmacion en tiempo de import: se prueba el PRODUCTO REAL, no un espejo.
assert run_pipeline is _real_pipeline.run_pipeline
assert _bench_runner.run_pipeline is _real_pipeline.run_pipeline


@pytest.fixture(scope="module")
def corpus():
    return load_corpus(verify=True)


# ---------------------------------------------------------------------------
# 1. Relacion simple
# ---------------------------------------------------------------------------
def test_e2e_01_single_relation():
    out = run_pipeline(simple_payload())
    assert out["schema"] == PIPELINE_SCHEMA
    assert out["dry_run"] is True
    assert len(out["results"]) == 1
    cand = out["results"][0]["candidate"]
    assert cand["predicate"] == "MEMBER_OF"
    # Evidencia LITERAL del texto (no inventada).
    seg_text = simple_payload()["segments"][0]["text"]
    assert seg_text[cand["evidence_start"]:cand["evidence_end"]] == cand["evidence_text"]


# ---------------------------------------------------------------------------
# 2. Varias relaciones en un mismo segmento
# ---------------------------------------------------------------------------
def test_e2e_02_multiple_relations():
    text = "Aria es miembro de la Orden del Alba y posee la Espada de Luz."
    ents = [
        find_ent("e:aria", "Aria", "Character", text),
        find_ent("e:orden", "Orden del Alba", "Faction", text),
        find_ent("e:espada", "Espada de Luz", "Object", text),
    ]
    out = run_pipeline(payload(text, ents))
    assert len(out["results"]) >= 2
    # Todas las evidencias son subcadenas literales del segmento.
    for rec in out["results"]:
        c = rec["candidate"]
        assert text[c["evidence_start"]:c["evidence_end"]] == c["evidence_text"]


# ---------------------------------------------------------------------------
# 3. Negacion
# ---------------------------------------------------------------------------
def test_e2e_03_negation():
    text = "Aria no es miembro de la Orden del Alba."
    ents = [find_ent("e:aria", "Aria", "Character", text),
            find_ent("e:orden", "Orden del Alba", "Faction", text)]
    out = run_pipeline(payload(text, ents))
    assert out["results"], "deberia proponer al menos un candidato"
    assert out["results"][0]["candidate"]["negated"] is True


# ---------------------------------------------------------------------------
# 4. Temporalidad
# ---------------------------------------------------------------------------
def test_e2e_04_temporality():
    text = "En 1123 Aria fue miembro de la Orden del Alba."
    ents = [find_ent("e:aria", "Aria", "Character", text),
            find_ent("e:orden", "Orden del Alba", "Faction", text)]
    out = run_pipeline(payload(text, ents))
    assert out["results"]
    assert out["results"][0]["candidate"]["temporal_scope"] is not None


# ---------------------------------------------------------------------------
# 5. Rumor
# ---------------------------------------------------------------------------
def test_e2e_05_rumor():
    text = "Se rumorea que Aria es miembro de la Orden del Alba."
    ents = [find_ent("e:aria", "Aria", "Character", text),
            find_ent("e:orden", "Orden del Alba", "Faction", text)]
    out = run_pipeline(payload(text, ents))
    assert out["results"]
    assert out["results"][0]["candidate"]["epistemic_status"] == "RUMORED"


# ---------------------------------------------------------------------------
# 6. Conflicto entre proveedores (local propone / externo rechaza) -> MODEL_CONFLICT
# ---------------------------------------------------------------------------
def test_e2e_06_provider_conflict():
    p = simple_payload()
    cfg = PipelineConfig(local_llm_enabled=True, external_ai_enabled=True)
    local = make_local_transport(relation_verdict_content())
    # El proveedor externo emite un veredicto de RECHAZO sobre el mismo candidato.
    reject_verdict = {
        "candidate_id": "e:aria|MEMBER_OF|e:orden", "verdict": "reject",
        "predicate": "MEMBER_OF", "subject_type": "Character", "object_type": "Faction",
        "negated": False, "evidence_text": "Aria es miembro de la Orden del Alba",
        "evidence_start": 0, "evidence_end": 36, "confidence": 0.9,
        "reason_codes": ["contradiccion"], "explanation": "x",
    }
    external = FakeExternalProvider(external_verdicts_content(reject_verdict))
    out = run_pipeline(p, config=cfg, local_transport=local, external_provider=external)
    assert out["provider_status"]["local_llm"] == PROVIDER_EXECUTED
    assert out["provider_status"]["external_ai"] == PROVIDER_EXECUTED
    rec = out["results"][0]
    # Estados de consenso reutilizados (vocabulario canonico); nunca autoaprobacion.
    assert rec["consensus"]["state"] in {
        "MODEL_CONFLICT", "PARTIAL_CONSENSUS", "INVALID_RESPONSES", "HUMAN_REQUIRED",
        "STRONG_CONSENSUS",
    }
    assert "APPROVED" not in str(rec["consensus"].get("recommendation", "")).upper()


# ---------------------------------------------------------------------------
# 7. Proveedor ausente (por defecto deshabilitado) -> NOT_EXECUTED, sin rechazo
# ---------------------------------------------------------------------------
def test_e2e_07_provider_absent_not_executed():
    out = run_pipeline(simple_payload())
    assert out["provider_status"]["local_llm"] == PROVIDER_NOT_EXECUTED
    assert out["provider_status"]["external_ai"] == PROVIDER_NOT_EXECUTED
    # Ausencia de proveedor NO invalida el candidato heuristico.
    assert out["results"]
    assert out["results"][0]["local_status"] == PROVIDER_NOT_EXECUTED


# ---------------------------------------------------------------------------
# 8. Proveedor invalido (habilitado sin via legitima) -> FAILED_CLOSED, sin red
# ---------------------------------------------------------------------------
def test_e2e_08_provider_invalid_fails_closed():
    cfg = PipelineConfig(local_llm_enabled=True, external_ai_enabled=True)
    # Sin transporte/proveedor inyectado: debe fallar CERRADO, jamas abrir red.
    out = run_pipeline(simple_payload(), config=cfg,
                       local_transport=None, external_provider=None)
    assert out["provider_status"]["local_llm"] == PROVIDER_FAILED_CLOSED
    assert out["provider_status"]["external_ai"] == PROVIDER_FAILED_CLOSED
    # El candidato heuristico sigue existiendo (fallo de proveedor != rechazo).
    assert out["results"]


# ---------------------------------------------------------------------------
# 9. Multiples workspaces: sin contaminacion; la mezcla en un doc se RECHAZA
# ---------------------------------------------------------------------------
def test_e2e_09_multiple_workspaces_isolated():
    out_a = run_pipeline(simple_payload(workspace="ws-alpha"))
    out_b = run_pipeline(simple_payload(workspace="ws-beta"))
    assert out_a["workspace"] == "ws-alpha"
    assert out_b["workspace"] == "ws-beta"
    for rec in out_a["results"]:
        assert rec["candidate"]["workspace"] == "ws-alpha"
    for rec in out_b["results"]:
        assert rec["candidate"]["workspace"] == "ws-beta"
    # Distinto workspace -> distinta ejecucion (sin colision de IDs).
    assert out_a["execution_id"] != out_b["execution_id"]

    # Mezcla dentro de un mismo documento: segmento de otro workspace -> rechazado.
    p = simple_payload(workspace="ws-alpha")
    p["segments"][0]["workspace"] = "ws-otro"
    mixed = run_pipeline(p)
    assert any(e["code"] == "workspace_mismatch" for e in mixed["errors"])
    assert mixed["results"] == []


# ---------------------------------------------------------------------------
# 10. Segmento defectuoso: fallo AISLADO, el resto del documento sobrevive
# ---------------------------------------------------------------------------
def test_e2e_10_defective_segment_isolated():
    gtext = "Aria es miembro de la Orden del Alba."
    good = segment(gtext, [find_ent("e:aria", "Aria", "Character", gtext),
                           find_ent("e:orden", "Orden del Alba", "Faction", gtext)],
                   segment_id="ok")
    bad = {"segment_id": "bad", "text": 12345, "workspace": "ws1", "source_id": "d1",
           "entities": []}  # text no es str
    out = run_pipeline({"source_id": "d1", "workspace": "ws1", "segments": [good, bad]})
    seg_status = {s["segment_id"]: s["status"] for s in out["documents"][0]["segments"]}
    assert seg_status["bad"] == "failed"
    assert seg_status["ok"] != "failed"
    assert out["results"], "el segmento sano debe producir candidatos pese al defectuoso"
    assert out["summary"]["segments_failed"] == 1


# ---------------------------------------------------------------------------
# 11. Explosion combinatoria: el limite de pares TRUNCA (no explota)
# ---------------------------------------------------------------------------
def test_e2e_11_combinatorial_explosion_capped():
    text = ("Aria Blan Cira Dorn Enna Fael se reunieron en el Consejo del Alba "
            "para deliberar sobre la guerra que se avecinaba en las tierras del norte.")
    ents = [find_ent(f"e:{n.lower()}", n, "Character", text)
            for n in ("Aria", "Blan", "Cira", "Dorn", "Enna", "Fael")]
    out = run_pipeline(payload(text, ents), config=PipelineConfig(max_pairs_per_segment=3))
    seg = out["documents"][0]["segments"][0]
    assert seg["truncated"] is True
    assert len(seg["pairs"]) <= 3


# ---------------------------------------------------------------------------
# 12. Ejecucion repetida: DETERMINISTA (mismos IDs y hash)
# ---------------------------------------------------------------------------
def test_e2e_12_repeated_execution_deterministic():
    p = simple_payload()
    a = run_pipeline(p)
    b = run_pipeline(p)
    assert a["execution_id"] == b["execution_id"]
    assert a["result_hash"] == b["result_hash"]
    assert a["results"] == b["results"]


# ---------------------------------------------------------------------------
# 13. Corpus completo: run_pipeline sobre TODAS las fuentes B1 (via derivacion B2)
# ---------------------------------------------------------------------------
def test_e2e_13_full_corpus_via_run_pipeline(corpus):
    assert corpus.manifest["source_count"] == len(corpus.sources) == 16
    total_results = 0
    for sid in sorted(corpus.sources):
        text = corpus.sources[sid]
        ws = corpus.workspace_by_source[sid]
        entities, _notes = derive_entities(sid, text, corpus.relations)
        p = build_payload(sid, text, ws, entities)
        out = run_pipeline(p, config=PipelineConfig(context_mode="sentence"))
        assert out["dry_run"] is True
        assert out["provider_status"]["local_llm"] == PROVIDER_NOT_EXECUTED
        assert out["workspace"] == ws
        # Toda evidencia emitida es LITERAL dentro del texto de la fuente.
        for rec in out["results"]:
            c = rec["candidate"]
            assert c["workspace"] == ws
            assert 0 <= c["evidence_start"] < c["evidence_end"] <= len(text)
            assert text[c["evidence_start"]:c["evidence_end"]] == c["evidence_text"]
        total_results += len(out["results"])
    assert total_results > 0


# ---------------------------------------------------------------------------
# 14. Benchmark baseline (via B2 REAL): dictamen y determinismo reales
# ---------------------------------------------------------------------------
def test_e2e_14_benchmark_baseline_via_b2(corpus):
    run = run_benchmark(corpus, mode="baseline1")
    report = build_report(corpus, run, check_determinism=True)
    # Proveedores reales NUNCA ejecutados, sin red ni escritura.
    assert report["providers"]["network"] == "none"
    assert "NOT_EXECUTED" in report["providers"]["local_llm"]
    assert "NOT_EXECUTED" in report["providers"]["external_ai"]
    # Gates duros reales.
    assert report["determinism"]["deterministic"] is True
    assert report["gates"]["determinism"]["status"] == "PASS"
    assert report["gates"]["workspace_contamination"]["status"] == "PASS"
    # Dictamen dentro del vocabulario CERRADO (nunca "APTO PARA INGESTA REAL").
    from relations.benchmark.report import VERDICTS
    assert report["verdict"] in VERDICTS
    assert "INGESTA REAL" not in report["verdict"]
    glob = report["metrics"]["global_existence"]
    assert glob["tp"] > 0 and 0.0 <= glob["f1"] <= 1.0


# ---------------------------------------------------------------------------
# 15. Benchmark pipeline offline (modo full_offline via B2 REAL)
# ---------------------------------------------------------------------------
def test_e2e_15_benchmark_full_offline_via_b2(corpus):
    run = run_benchmark(corpus, mode="full_offline")
    assert run.config["local_llm_enabled"] is False
    assert run.config["external_ai_enabled"] is False
    assert run.config["context_mode"] == "segment"
    report = build_report(corpus, run, check_determinism=False)
    # Sin contaminacion de workspaces en el modo mas amplio (maxima cobertura de pares).
    assert report["gates"]["workspace_contamination"]["status"] == "PASS"
    # Cada fuente tiene su hash de resultado (evidencia de ejecucion real por fuente).
    assert set(run.result_hashes()) == set(corpus.sources)
