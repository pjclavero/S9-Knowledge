# -*- coding: utf-8 -*-
"""Bloque 7 - Tests de calibracion/seguridad del benchmark de relaciones.

Cubren el modo OFFLINE `ensemble_offline`, la submuestra `--sources`, el volcado y
recombinacion de payloads y, sobre todo, las PROTECCIONES que impiden que el
benchmark abra red o falsifique metricas.

Cinco de estos tests son *mutation checks*: si alguien revierte la proteccion que
verifican (meter un modo con proveedor en `MODES`, quitar una de las dos llaves,
bajar un umbral de gate, hardcodear metricas o el estado de proveedores), el test
FALLA. Ningun test de este fichero abre red: los sockets se bloquean
explicitamente donde el pipeline podria intentar usarlos.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from relations.benchmark import cli as bench_cli  # noqa: E402
from relations.benchmark import metrics as bench_metrics  # noqa: E402
from relations.benchmark import report as bench_report  # noqa: E402
from relations.benchmark import runner as bench_runner  # noqa: E402
from relations.benchmark.matching import match_predictions  # noqa: E402

# Ids REALES del corpus B1.
ALL_SOURCE_IDS = [f"src-{i:02d}" for i in range(1, 17)]
# Submuestra pequena y estable para los tests que ejecutan el pipeline.
SAMPLE_IDS = ["src-01", "src-02", "src-03"]


@pytest.fixture(scope="module")
def corpus():
    return bench_runner.load_corpus()


class _NetworkAttempt(AssertionError):
    """Se lanza si el codigo bajo test intenta abrir cualquier conexion."""


@pytest.fixture
def no_network(monkeypatch):
    """Bloquea TODA apertura de red y cuenta los intentos.

    Devuelve la lista de intentos (siempre debe quedar vacia). Cualquier intento
    ademas revienta en el acto, asi que un modo que llamara a un proveedor no
    podria pasar silenciosamente.
    """
    attempts: list[str] = []

    def _boom(name):
        def _fn(*args, **kwargs):
            attempts.append(name)
            raise _NetworkAttempt(f"intento de red prohibido via {name}: {args!r}")
        return _fn

    monkeypatch.setattr(socket, "socket", _boom("socket.socket"))
    monkeypatch.setattr(socket, "create_connection", _boom("socket.create_connection"))
    monkeypatch.setattr(urllib.request, "urlopen", _boom("urllib.request.urlopen"))
    monkeypatch.setattr(urllib.request, "urlretrieve", _boom("urllib.request.urlretrieve"))
    return attempts


def _clean_env() -> dict:
    """Entorno de subproceso sin la segunda llave (nunca toca el entorno global)."""
    env = dict(os.environ)
    env.pop(bench_runner.PROVIDERS_ENV_VAR, None)
    env["PYTHONPATH"] = str(_APP_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    return env


# ===========================================================================
# MUTATION CHECK 1 - MODES contiene EXCLUSIVAMENTE modos offline
# ===========================================================================
def test_mutation_modes_no_contiene_ningun_modo_con_proveedor():
    """Mata al mutante que mete `ollama_shadow` (o similar) en MODES."""
    assert set(bench_runner.MODES) & set(bench_runner.PROVIDER_MODES) == set()
    assert set(bench_runner.PROVIDER_MODES) == {
        "ollama_shadow", "nvidia_shadow", "ensemble_full"}
    assert set(bench_runner.MODES) == {
        "baseline1", "baseline2", "full_offline", "ensemble_offline"}

    # Ningun preset de MODES puede activar un proveedor, ni por el preset ni por
    # la PipelineConfig REAL que se construye a partir de el.
    for mode, preset in bench_runner.MODES.items():
        assert preset.get("local_llm_enabled") in (None, False), mode
        assert preset.get("external_ai_enabled") in (None, False), mode
        cfg = bench_runner._config_for_mode(mode).to_dict()
        assert cfg["local_llm_enabled"] is False, mode
        assert cfg["external_ai_enabled"] is False, mode
        assert bench_runner.is_provider_mode(mode) is False, mode

    # Y todos los modos con proveedor SI activan alguno (no son offline disfrazados).
    for mode, preset in bench_runner.PROVIDER_MODES.items():
        assert preset.get("local_llm_enabled") or preset.get("external_ai_enabled"), mode


# ===========================================================================
# MUTATION CHECK 2 - DOBLE LLAVE
# ===========================================================================
def test_mutation_doble_llave_provider_authorization(monkeypatch):
    """Mata al mutante que elimina una de las dos llaves (flag o variable)."""
    assert bench_runner.PROVIDERS_ENV_VAR == "S9K_BENCH_PROVIDERS"

    for mode in sorted(bench_runner.PROVIDER_MODES):
        # 1. Falta el flag (pero la variable esta puesta).
        with pytest.raises(bench_runner.BenchmarkError) as e1:
            bench_runner.require_provider_authorization(
                mode, enable_providers=False, env={bench_runner.PROVIDERS_ENV_VAR: "1"})
        assert "--enable-providers" in str(e1.value)

        # 2. Falta la variable (pero el flag esta puesto).
        for bad in ({}, {bench_runner.PROVIDERS_ENV_VAR: "0"},
                    {bench_runner.PROVIDERS_ENV_VAR: ""},
                    {bench_runner.PROVIDERS_ENV_VAR: "true"},
                    {bench_runner.PROVIDERS_ENV_VAR: "yes"}):
            with pytest.raises(bench_runner.BenchmarkError) as e2:
                bench_runner.require_provider_authorization(
                    mode, enable_providers=True, env=bad)
            assert bench_runner.PROVIDERS_ENV_VAR in str(e2.value)

        # 3. Faltan las dos.
        with pytest.raises(bench_runner.BenchmarkError):
            bench_runner.require_provider_authorization(
                mode, enable_providers=False, env={})

        # 4. Con AMBAS llaves: pasa (y solo entonces).
        assert bench_runner.require_provider_authorization(
            mode, enable_providers=True,
            env={bench_runner.PROVIDERS_ENV_VAR: "1"}) is None

    # Los modos offline nunca requieren autorizacion (no hay red que autorizar).
    for mode in sorted(bench_runner.MODES):
        assert bench_runner.require_provider_authorization(
            mode, enable_providers=False, env={}) is None

    # La segunda llave se lee del entorno REAL cuando no se pasa `env`.
    monkeypatch.delenv(bench_runner.PROVIDERS_ENV_VAR, raising=False)
    with pytest.raises(bench_runner.BenchmarkError):
        bench_runner.require_provider_authorization(
            "ollama_shadow", enable_providers=True)
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")
    assert bench_runner.require_provider_authorization(
        "ollama_shadow", enable_providers=True) is None


# ===========================================================================
# MUTATION CHECK 3 - ningun modo de MODES abre red
# ===========================================================================
def test_mutation_ningun_modo_de_modes_abre_red(corpus, no_network):
    """Mata al mutante que hace que algun modo de MODES llame a un proveedor."""
    for mode in sorted(bench_runner.MODES):
        run = bench_runner.run_benchmark(corpus, mode=mode, source_ids=SAMPLE_IDS)
        assert run.predictions, mode
        assert no_network == [], f"{mode} intento abrir red: {no_network}"
        # El propio pipeline confirma que no ejecuto proveedores.
        assert run.provider_status.get("local_llm") != "EXECUTED", mode
        assert run.provider_status.get("external_ai") != "EXECUTED", mode
        cost = bench_metrics.provider_cost(run.results, run.source_summaries)
        assert cost["total_calls"] == 0, mode
    assert no_network == []


# ===========================================================================
# MUTATION CHECK 4 - umbrales de gates congelados
# ===========================================================================
def test_mutation_umbrales_de_gates_literales():
    """Mata al mutante que baja un umbral para que un gate pase."""
    assert bench_report.THRESHOLDS == {
        "simple_relations_recall": 0.80,
        "evidence": 0.80,
        "offsets": 0.90,
        "negation": 0.80,
        "temporality": 0.60,
        "rumors": 0.60,
        "predicate_structural": 0.50,
    }
    # Valor a valor, para que un cambio en uno solo sea inequivoco.
    assert bench_report.THRESHOLDS["simple_relations_recall"] == pytest.approx(0.80)
    assert bench_report.THRESHOLDS["evidence"] == pytest.approx(0.80)
    assert bench_report.THRESHOLDS["offsets"] == pytest.approx(0.90)
    assert bench_report.THRESHOLDS["negation"] == pytest.approx(0.80)
    assert bench_report.THRESHOLDS["temporality"] == pytest.approx(0.60)
    assert bench_report.THRESHOLDS["rumors"] == pytest.approx(0.60)
    assert bench_report.THRESHOLDS["predicate_structural"] == pytest.approx(0.50)
    # El vocabulario de dictamen sigue cerrado y sin "APTO PARA INGESTA REAL".
    assert "APTO PARA INGESTA REAL" not in bench_report.VERDICTS
    # Un valor justo por debajo del umbral NO puede dar PASS.
    for key, thr in bench_report.THRESHOLDS.items():
        assert bench_report._status(thr, thr) == "PASS", key
        assert bench_report._status(thr - 0.01, thr) != "PASS", key


# ===========================================================================
# MUTATION CHECK 5 - las metricas dependen del ground truth REAL
# ===========================================================================
def _copy_corpus(tmp_path: Path) -> Path:
    dst = tmp_path / "corpus"
    shutil.copytree(bench_runner.DEFAULT_CORPUS_DIR, dst)
    return dst


def _rehash_manifest(corpus_dir: Path) -> None:
    manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    gt_path = corpus_dir / manifest["ground_truth"]["path"]
    manifest["ground_truth"]["sha256"] = hashlib.sha256(gt_path.read_bytes()).hexdigest()
    for s in manifest["sources"]:
        p = corpus_dir / s["path"]
        s["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    (corpus_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def test_mutation_metricas_no_son_constantes_hardcodeadas(tmp_path, corpus, no_network):
    """Mata al mutante que devuelve metricas fijas ignorando el ground truth.

    Dos demostraciones:
      a) alterar el ground truth (rehasheando el manifest) CAMBIA las metricas;
      b) alterar el corpus sin rehashear el manifest ABORTA el runner.
    """
    base_run = bench_runner.run_benchmark(corpus, mode="ensemble_offline",
                                          source_ids=SAMPLE_IDS)
    base_report = bench_report.build_report(corpus, base_run, check_determinism=False)
    base_global = base_report["metrics"]["global_existence"]
    assert base_global["tp"] + base_global["fn"] > 0

    # (a) ground truth alterado -> metricas distintas.
    tampered_dir = _copy_corpus(tmp_path)
    gt_file = tampered_dir / "ground_truth" / "relations.json"
    gt = json.loads(gt_file.read_text(encoding="utf-8"))
    tocadas = 0
    for rel in gt["relations"]:
        if rel["source_id"] in SAMPLE_IDS:
            rel["object_id"] = "entidad-inexistente-block7"
            tocadas += 1
    assert tocadas > 0
    gt_file.write_text(json.dumps(gt, ensure_ascii=False, indent=2), encoding="utf-8")
    _rehash_manifest(tampered_dir)

    tampered_corpus = bench_runner.load_corpus(tampered_dir)
    tampered_run = bench_runner.run_benchmark(tampered_corpus, mode="ensemble_offline",
                                              source_ids=SAMPLE_IDS)
    tampered_report = bench_report.build_report(tampered_corpus, tampered_run,
                                                check_determinism=False)
    tampered_global = tampered_report["metrics"]["global_existence"]
    assert tampered_global != base_global, (
        "las metricas NO cambian al alterar el ground truth: son constantes falsificadas"
    )
    assert (tampered_report["metrics"]["per_predicate"]
            != base_report["metrics"]["per_predicate"])
    assert (tampered_report["errors"]["false_negatives"]
            != base_report["errors"]["false_negatives"])
    # El sha256 del ground truth reportado tambien cambia (trazabilidad real).
    assert (tampered_report["corpus"]["ground_truth_sha256"]
            != base_report["corpus"]["ground_truth_sha256"])

    # (b) corpus alterado SIN rehashear -> el runner aborta al verificar.
    roto = _copy_corpus(tmp_path / "roto")
    src = roto / "sources" / "src-01-batalla-del-vado.txt"
    src.write_text(src.read_text(encoding="utf-8") + "\nlinea inyectada\n", encoding="utf-8")
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        bench_runner.load_corpus(roto)
    assert "sha256" in str(exc.value)

    assert no_network == []


# ===========================================================================
# MUTATION CHECK 6 - el bloque `providers` se DERIVA, no es un literal
# ===========================================================================
def test_mutation_bloque_providers_derivado_no_literal(corpus):
    """Mata al mutante que vuelve a hardcodear "Ollama real: NOT_EXECUTED"."""
    cli_src = Path(bench_cli.__file__).read_text(encoding="utf-8")
    # El literal mentiroso (estado fijo, sin interpolar) NO debe existir.
    assert "Ollama real: **NOT_EXECUTED**" not in cli_src
    assert "NVIDIA real: **NOT_EXECUTED**" not in cli_src
    assert "prov.get('local_llm'" in cli_src

    run = bench_runner.run_benchmark(corpus, mode="baseline1", source_ids=["src-01"])
    rep_real = bench_report.build_report(corpus, run, check_determinism=False)
    assert rep_real["providers"]["local_llm"] == "NOT_EXECUTED"
    assert rep_real["providers"]["network"] == "none"
    assert rep_real["providers"]["provider_status_raw"] == run.provider_status

    # Si el pipeline dijera que un proveedor SI se ejecuto, el informe y el
    # Markdown lo dirian: el texto se deriva de output['provider_status'].
    run.provider_status = {"local_llm": "EXECUTED", "external_ai": "FAILED_CLOSED"}
    rep_exec = bench_report.build_report(corpus, run, check_determinism=False)
    assert rep_exec["providers"]["local_llm"] == "EXECUTED"
    assert rep_exec["providers"]["external_ai"] == "FAILED_CLOSED"
    assert rep_exec["providers"]["network"].startswith("yes")
    md = bench_cli.render_markdown(rep_exec)
    assert "- Ollama real: **EXECUTED**" in md
    assert "- NVIDIA real: **FAILED_CLOSED**" in md
    assert "- Red: **yes (proveedores ejecutados)**" in md
    # Y la escritura sigue siendo siempre dry-run.
    assert rep_exec["providers"]["writes"] == "none (dry-run, sin Neo4j)"


# ===========================================================================
# FUNCIONALES
# ===========================================================================
def test_ensemble_offline_salida_bien_formada_y_determinista(corpus, no_network):
    run_a = bench_runner.run_benchmark(corpus, mode="ensemble_offline",
                                       source_ids=SAMPLE_IDS)
    run_b = bench_runner.run_benchmark(corpus, mode="ensemble_offline",
                                       source_ids=SAMPLE_IDS)
    assert run_a.ensemble is True
    assert run_a.source_ids == SAMPLE_IDS
    assert run_a.predictions == run_b.predictions
    assert run_a.result_hashes() == run_b.result_hashes()

    rep_a = bench_report.build_report(corpus, run_a, check_determinism=True)
    rep_b = bench_report.build_report(corpus, run_b, check_determinism=False)
    # Metricas identicas salvo los tiempos de pared (que no son deterministas
    # por definicion y no entran en ningun gate).
    for key in ("global_existence", "strict_predicate", "per_predicate",
                "predicted_predicate_distribution", "structural_quality",
                "decision_confusion", "provider_cost"):
        assert rep_a["metrics"][key] == rep_b["metrics"][key], key
    assert (rep_a["metrics"]["operational"]["counters"]
            == rep_b["metrics"]["operational"]["counters"])
    assert (rep_a["metrics"]["operational"]["consensus_rates"]
            == rep_b["metrics"]["operational"]["consensus_rates"])
    # El gate DURO de determinismo (segunda ejecucion real) pasa.
    assert rep_a["determinism"]["deterministic"] is True
    assert rep_a["gates"]["determinism"]["status"] == "PASS"
    assert rep_a["gates"]["workspace_contamination"]["status"] == "PASS"

    assert rep_a["ensemble"] is True
    assert rep_a["verdict"] in bench_report.VERDICTS
    assert rep_a["sources_used"] == SAMPLE_IDS
    assert rep_a["sources_available"] == ALL_SOURCE_IDS
    # El Markdown declara la submuestra y es estable en todo lo que no es tiempo.
    md_a = bench_cli.render_markdown(
        bench_report.build_report(corpus, run_a, check_determinism=False))
    md_b = bench_cli.render_markdown(rep_b)

    def _stable(md: str) -> list[str]:
        return [l for l in md.splitlines() if "(ms)" not in l]

    assert _stable(md_a) == _stable(md_b)
    assert "SUBMUESTRA" in md_a
    assert no_network == []


def test_extract_predictions_ensemble_estructura(corpus, no_network):
    run = bench_runner.run_benchmark(corpus, mode="ensemble_offline",
                                     source_ids=["src-01"])
    output = run.source_runs[0].output
    preds = bench_runner.extract_predictions_ensemble(output)
    base = bench_runner.extract_predictions(output)
    assert preds and len(preds) == len(base)

    campos_base = set(base[0])
    for p in preds:
        assert campos_base <= set(p)
        # Campos de trazabilidad ADITIVOS del ensemble.
        assert "base_consensus_state" in p and "ensemble_score" in p
        assert isinstance(p["ensemble_score"], float)
        assert 0.0 <= p["ensemble_score"] <= 1.0
        assert p["consensus_state"] is not None
        assert p["recommendation"] is not None
    # Los candidatos son los MISMOS (el ensemble solo recalibra el consenso).
    assert [p["candidate_id"] for p in preds] == [b["candidate_id"] for b in base]
    assert [p["predicate"] for p in preds] == [b["predicate"] for b in base]
    assert [p["base_consensus_state"] for p in preds] == [b["consensus_state"] for b in base]
    assert no_network == []


def test_select_sources_filtra_y_falla_con_id_inexistente(corpus):
    assert bench_runner.select_sources(corpus) == ALL_SOURCE_IDS
    assert bench_runner.select_sources(corpus, []) == ALL_SOURCE_IDS
    # Filtra y ORDENA de forma determinista, independientemente del orden pedido.
    assert bench_runner.select_sources(corpus, ["src-03", "src-01"]) == ["src-01", "src-03"]
    # Duplicados y espacios no rompen el filtro.
    assert bench_runner.select_sources(corpus, [" src-16 ", "src-16"]) == ["src-16"]

    with pytest.raises(bench_runner.BenchmarkError) as exc:
        bench_runner.select_sources(corpus, ["src-99"])
    assert "src-99" in str(exc.value)
    assert "desconocidos" in str(exc.value)
    # Un id valido mezclado con uno invalido tambien aborta (no ejecuta a medias).
    with pytest.raises(bench_runner.BenchmarkError):
        bench_runner.select_sources(corpus, ["src-01", "src-17"])


def test_mode_preset_y_is_provider_mode():
    assert bench_runner.mode_preset("ensemble_offline") == {"context_mode": "sentence"}
    assert bench_runner.mode_preset("baseline1") == {"context_mode": "sentence"}
    assert bench_runner.mode_preset("baseline2") == {"context_mode": "paragraph"}
    assert bench_runner.mode_preset("full_offline") == {"context_mode": "segment"}
    assert bench_runner.mode_preset("ollama_shadow")["local_llm_enabled"] is True
    assert bench_runner.mode_preset("nvidia_shadow")["external_ai_enabled"] is True

    # Devuelve una COPIA: mutarla no contamina el diccionario del modulo.
    preset = bench_runner.mode_preset("baseline1")
    preset["context_mode"] = "segment"
    assert bench_runner.MODES["baseline1"]["context_mode"] == "sentence"

    with pytest.raises(bench_runner.BenchmarkError) as exc:
        bench_runner.mode_preset("modo-que-no-existe")
    assert "modo desconocido" in str(exc.value)

    assert bench_runner.is_provider_mode("ollama_shadow") is True
    assert bench_runner.is_provider_mode("nvidia_shadow") is True
    assert bench_runner.is_provider_mode("ensemble_full") is True
    assert bench_runner.is_provider_mode("ensemble_offline") is False
    assert bench_runner.is_provider_mode("baseline1") is False
    assert bench_runner.is_provider_mode("desconocido") is False

    # `uses_ensemble` cubre los dos modos de ensemble y ninguno mas.
    assert bench_runner.uses_ensemble("ensemble_offline") is True
    assert bench_runner.uses_ensemble("ensemble_full") is True
    assert bench_runner.uses_ensemble("baseline1") is False


def test_collect_y_recombine_reproducen_metricas_sin_llamadas(corpus, no_network):
    run = bench_runner.run_benchmark(corpus, mode="ensemble_offline",
                                     source_ids=SAMPLE_IDS)
    payloads = bench_runner.collect_provider_payloads(run)
    assert len(payloads) == len(run.predictions)
    for rec in payloads:
        assert set(rec) >= {"source_id", "candidate_id", "pair_id", "candidate",
                            "consensus", "signals", "syntax", "local", "local_status",
                            "external", "external_status"}
    # Serializable a JSONL (es lo que escribe --out-payloads).
    records = [json.loads(line) for line in
               bench_cli.render_jsonl(payloads).splitlines() if line.strip()]
    assert len(records) == len(payloads)

    recombined = bench_runner.recombine_from_payloads(records)
    assert [p["candidate_id"] for p in recombined] == [p["candidate_id"] for p in run.predictions]
    for a, b in zip(recombined, run.predictions):
        assert a["consensus_state"] == b["consensus_state"]
        assert a["recommendation"] == b["recommendation"]
        assert a["ensemble_score"] == pytest.approx(b["ensemble_score"])

    gt = [r for r in corpus.relations if r["source_id"] in set(SAMPLE_IDS)]
    m_run = match_predictions(run.predictions, gt)
    m_rec = match_predictions(recombined, gt)
    assert bench_metrics.global_metrics(m_rec) == bench_metrics.global_metrics(m_run)
    assert bench_metrics.strict_metrics(m_rec) == bench_metrics.strict_metrics(m_run)
    assert bench_metrics.structural_quality(m_rec) == bench_metrics.structural_quality(m_run)

    # Contador de llamadas a proveedor: CERO (ni sockets, ni contadores del pipeline).
    assert no_network == []
    assert bench_metrics.provider_cost(records, [])["total_calls"] == 0


def test_provider_cost_calcula_lo_que_dice():
    results = [
        {"local": {"latency_ms": 10}, "local_status": "OK",
         "external": {"latency_ms": 100}, "external_status": "OK"},
        {"local": {"latency_ms": 20}, "local_status": "OK",
         "external": None, "external_status": "FAILED_CLOSED"},
        {"local": {"latency_ms": 30}, "local_status": "OK"},
        {"local": {"latency_ms": 40}, "local_status": "TIMEOUT"},
        {"local": None, "local_status": None},
    ]
    summaries = [
        {"local_calls_simulated": 3, "external_calls_simulated": 1},
        {"local_calls_simulated": 1, "external_calls_simulated": 0},
    ]
    cost = bench_metrics.provider_cost(results, summaries)

    assert cost["local"]["calls"] == 4          # sumado de los summaries REALES
    assert cost["external"]["calls"] == 1
    assert cost["total_calls"] == 5
    assert cost["local"]["payloads"] == 4       # payloads dict no nulos
    assert cost["external"]["payloads"] == 1
    assert cost["local"]["statuses"] == {"OK": 3, "TIMEOUT": 1}
    assert cost["external"]["statuses"] == {"FAILED_CLOSED": 1, "OK": 1}
    # p50/p95/max por interpolacion lineal sobre [10,20,30,40].
    assert cost["local"]["latency"] == {"samples": 4, "p50_ms": 25.0,
                                        "p95_ms": 38.5, "max_ms": 40.0}
    assert cost["external"]["latency"] == {"samples": 1, "p50_ms": 100.0,
                                           "p95_ms": 100.0, "max_ms": 100.0}

    # Sin datos: ceros y None limpios, jamas latencias inventadas.
    vacio = bench_metrics.provider_cost([], [])
    assert vacio["total_calls"] == 0
    for key in ("local", "external"):
        assert vacio[key]["calls"] == 0 and vacio[key]["payloads"] == 0
        assert vacio[key]["latency"] == {"samples": 0, "p50_ms": None,
                                         "p95_ms": None, "max_ms": None}


def test_cli_rechaza_modo_proveedor_sin_autorizacion(monkeypatch, no_network, tmp_path):
    """Sin doble llave el CLI aborta ANTES de tocar red (y sin salidas escritas)."""
    monkeypatch.delenv(bench_runner.PROVIDERS_ENV_VAR, raising=False)
    out_json = tmp_path / "no-debe-existir.json"
    for mode in sorted(bench_runner.PROVIDER_MODES):
        for argv in ([f"--mode={mode}"],
                     [f"--mode={mode}", "--enable-providers"]):
            with pytest.raises(bench_runner.BenchmarkError) as exc:
                bench_cli.main(argv + [f"--out-json={out_json}"])
            assert "DOBLE LLAVE" in str(exc.value)
            assert "ABORTADO ANTES DE ABRIR RED" in str(exc.value)
    assert not out_json.exists()
    assert no_network == []

    # Con las DOS llaves pero sin endpoint: falla CERRADO, tampoco abre red.
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")
    monkeypatch.delenv("S9K_BENCH_OLLAMA_ENDPOINT", raising=False)
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        bench_cli.main(["--mode=ollama_shadow", "--enable-providers"])
    assert "endpoint" in str(exc.value)
    assert no_network == []


def test_cli_modo_proveedor_sin_autorizacion_codigo_salida_no_cero():
    """El proceso real termina con codigo != 0 y mensaje claro en stderr."""
    for mode in sorted(bench_runner.PROVIDER_MODES):
        proc = subprocess.run(
            [sys.executable, "-m", "relations.benchmark.cli", f"--mode={mode}"],
            cwd=str(_APP_DIR), env=_clean_env(),
            capture_output=True, text=True, timeout=300,
        )
        assert proc.returncode != 0, (mode, proc.stdout, proc.stderr)
        assert proc.returncode == 2
        assert "DOBLE LLAVE" in proc.stderr
        assert "ABORTADO ANTES DE ABRIR RED" in proc.stderr
        assert proc.stdout.strip() == ""


def test_cli_offline_end_to_end_con_submuestra_y_payloads(tmp_path, no_network, monkeypatch):
    """Camino feliz OFFLINE: --sources + --out-payloads + --recombine-from."""
    monkeypatch.delenv(bench_runner.PROVIDERS_ENV_VAR, raising=False)
    out_json = tmp_path / "res.json"
    out_jsonl = tmp_path / "preds.jsonl"
    out_payloads = tmp_path / "payloads.jsonl"
    out_md = tmp_path / "res.md"

    rc = bench_cli.main([
        "--mode=ensemble_offline",
        f"--sources={','.join(SAMPLE_IDS)}",
        f"--out-json={out_json}", f"--out-jsonl={out_jsonl}",
        f"--out-payloads={out_payloads}", f"--out-md={out_md}",
        "--no-determinism",
    ])
    assert rc == 0
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert report["mode"] == "ensemble_offline"
    assert report["sources_used"] == SAMPLE_IDS
    assert report["ensemble"] is True
    assert report["metrics"]["provider_cost"]["total_calls"] == 0
    assert report["providers"]["local_llm"] == "NOT_EXECUTED"
    assert out_jsonl.read_text(encoding="utf-8").strip()
    assert out_md.read_text(encoding="utf-8").startswith("# 50 -")

    # Recombinar desde los payloads reproduce las MISMAS metricas, 0 llamadas.
    # BLOQUEANTE 2 (ronda 4): sin HMAC de operador la recombinacion es FAIL-CLOSED;
    # el camino feliz reconoce el modo no autenticado con la bandera dedicada.
    rec_json = tmp_path / "rec.json"
    rc2 = bench_cli.main([f"--recombine-from={out_payloads}", f"--out-json={rec_json}",
                          "--accept-unauthenticated-recombine"])
    assert rc2 == 0
    rec = json.loads(rec_json.read_text(encoding="utf-8"))
    assert rec["authenticity"].startswith("NO VERIFICADA")
    assert rec["providers_called"] == 0
    assert rec["sources_used"] == SAMPLE_IDS
    assert rec["metrics"]["global_existence"] == report["metrics"]["global_existence"]
    assert rec["metrics"]["strict_predicate"] == report["metrics"]["strict_predicate"]
    assert no_network == []


def test_all_modes_nunca_incluye_modos_con_proveedor(tmp_path, no_network, monkeypatch):
    """--all-modes solo recorre MODES; combinado con proveedor, aborta."""
    monkeypatch.delenv(bench_runner.PROVIDERS_ENV_VAR, raising=False)
    out_json = tmp_path / "all.json"
    rc = bench_cli.main([
        "--mode=baseline1", "--all-modes", "--no-determinism",
        f"--sources={','.join(SAMPLE_IDS)}", f"--out-json={out_json}",
    ])
    assert rc == 0
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert set(payload["all_modes"]) == set(bench_runner.MODES)
    assert set(payload["all_modes"]) & set(bench_runner.PROVIDER_MODES) == set()
    for name, row in payload["all_modes"].items():
        assert row["provider_calls"] == 0, name
        assert row["providers"]["local_llm"] == "NOT_EXECUTED", name

    # --all-modes con un modo de proveedor y SIN doble llave aborta por la doble
    # llave, antes de cargar el corpus y antes de cualquier red.
    # (NOTA: con la doble llave concedida, el guard de --all-modes se evalua DESPUES
    #  de ejecutar el run con proveedor; ver el informe. No es un agujero de
    #  seguridad -- exige autorizacion explicita -- pero si un defecto de orden.)
    for mode in sorted(bench_runner.PROVIDER_MODES):
        with pytest.raises(bench_runner.BenchmarkError) as exc:
            bench_cli.main([f"--mode={mode}", "--all-modes"])
        assert "DOBLE LLAVE" in str(exc.value)
    assert no_network == []


def test_providers_module_no_abre_red_al_importar_ni_sin_endpoint(no_network, monkeypatch):
    """Importar providers.py no abre red; sin endpoint la fabrica falla cerrada."""
    from relations.benchmark import providers as bench_providers

    monkeypatch.delenv(bench_providers.LOCAL_ENDPOINT_ENV, raising=False)
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        bench_providers.build_local_transport()
    assert "endpoint" in str(exc.value)

    # N13: tampoco se construye con el endpoint SOLO en el entorno; hay que
    # nombrarlo explicitamente (construirlo a proposito no implicaba saber a
    # donde apuntaba).
    monkeypatch.setenv(bench_providers.LOCAL_ENDPOINT_ENV, "http://127.0.0.1:1/v1")
    with pytest.raises(bench_runner.BenchmarkError) as exc_env:
        bench_providers.build_local_transport()
    assert "EXPLICITO" in str(exc_env.value)

    # Timeout demasiado bajo: se rechaza (mediria timeouts, no calidad).
    with pytest.raises(bench_runner.BenchmarkError) as exc2:
        bench_providers.build_local_transport("http://127.0.0.1:1/v1", timeout_s=30)
    assert "timeout" in str(exc2.value).lower()
    assert bench_runner.PROVIDER_LOCAL_TIMEOUT_S >= 120

    # Construir el transporte NO abre conexion: solo devuelve un callable.
    transport = bench_providers.build_local_transport("http://127.0.0.1:1/v1")
    assert callable(transport)
    assert no_network == []
