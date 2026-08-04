# -*- coding: utf-8 -*-
"""Validaciones de reproducibilidad, escala y aceptación del reconciliador."""
from __future__ import annotations

import copy
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import pytest

from knowledge_v3.benchmarks.loader import load_gold
from knowledge_v3.contracts import parse_document
from knowledge_v3.extraction.base import ExtractionOutput
from knowledge_v3.extraction.provider_port import MockProviderPort
from knowledge_v3.extraction.semantic_bench import (
    CachingPort,
    build_context,
    run_config,
    score,
)
from knowledge_v3.reconcile import ProposalReconciler

ROOT = Path(__file__).resolve().parents[3]
C1_CACHE = ROOT / "docs/v3/measurements/runs/c1-cache.json"


def _mention(base: dict, identifier: str, origin: int):
    doc = copy.deepcopy(base)
    doc["mention_id"] = identifier
    trace = [dict(item) for item in (doc.get("provider_trace") or [])]
    step, provider = (
        ("extract.deterministic", "local")
        if origin % 2 == 0
        else ("extract.semantic", "ollama")
    )
    if trace:
        trace[0]["step"] = step
        trace[0]["provider"] = provider
    doc["provider_trace"] = trace
    doc["produced_by_step"] = step
    return parse_document(doc)


def _synthetic_mentions(count: int):
    """Corpus fijo con grupos repetidos y orden barajado de forma sembrada."""
    bases = list(load_gold("dev").mentions)[:10]
    docs = [
        _mention(bases[index % len(bases)], f"synthetic-m-{index:04d}", index)
        for index in range(count)
    ]
    random.Random(20260730).shuffle(docs)
    return tuple(docs)


def test_salida_byte_identica_con_pythonhashseed_distinto():
    probe = Path(__file__).with_name("reconcile_hashseed_probe.py")
    hashes = {}
    for seed in ("0", "1", "random"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        app_path = str(ROOT / "data-engine/app")
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (app_path, env.get("PYTHONPATH", "")) if part
        )
        completed = subprocess.run(
            [sys.executable, str(probe)],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        hashes[seed] = completed.stdout.strip()
    assert len(set(hashes.values())) == 1, hashes


def test_rendimiento_escala_razonablemente_hasta_mil_propuestas():
    reconciler = ProposalReconciler()
    timings = {}
    for count in (10, 100, 1000):
        samples = []
        output = ExtractionOutput(mentions=_synthetic_mentions(count))
        for _ in range(3):
            started = time.perf_counter()
            reconciler.reconcile(output)
            samples.append(time.perf_counter() - started)
        timings[count] = min(samples)

    assert timings[1000] < 30.0, timings
    # Umbral deliberadamente holgado: protege de una regresión claramente
    # superlineal sin convertir ruido de máquinas compartidas en flakes.
    assert timings[1000] < max(1.0, timings[100] * 30), timings


def test_aceptacion_los_ocho_claims_de_c1_sobreviven_en_D_R():
    assert C1_CACHE.exists(), f"falta el cache offline: {C1_CACHE}"
    gold = load_gold("dev")
    ctx = build_context(gold)
    offline = MockProviderPort(
        handler=lambda _request: pytest.fail("cache C1 incompleto: se intentó inferencia")
    )
    port = CachingPort(offline, C1_CACHE)

    a = run_config("A", ctx)
    c1 = run_config("C1", ctx, port=port)
    d = run_config("D", ctx, prior={"A": a, "C1": c1})
    dr = run_config("D-R", ctx, prior={"D": d})

    assert port.hits == len(ctx.episodes) and port.misses == 0
    a_claims = score(a, gold, ctx)["harness_extractor"]["claims"]
    c1_claims = score(c1, gold, ctx)["harness_extractor"]["claims"]
    d_claims = score(d, gold, ctx)["harness_extractor"]["claims"]
    dr_claims = score(dr, gold, ctx)["harness_extractor"]["claims"]
    # Las cuatro configuraciones se comprueban con tp Y fp. La version anterior
    # solo miraba `tp` de C1/D/D-R y `fp` de A, y esa combinacion enmascaro una
    # regresion real de integracion: los falsos positivos que la union metia en
    # D-R no los veia nadie. Aqui no hay ninguna metrica de precision sin su
    # aserto.
    assert c1_claims["tp"] == 8 and c1_claims["fp"] == 10
    assert a_claims["tp"] == 2 and a_claims["fp"] == 0, (
        "el extractor determinista propone 2 claims en dev desde B2, ambos "
        "verdaderos positivos: si aparece un fp, es una regresion de precision"
    )

    # D es la UNION CRUDA, sin reconciliar (asi esta documentada en
    # `run_config`): arrastra las menciones de los dos extractores duplicadas,
    # el arnes no puede alinearlas 1:1 y casi todos los claims quedan
    # inevaluables. NO es un defecto de B2 -- medido sobre 7fc9512 (pre-B2, con
    # el determinista proponiendo CERO claims) D ya daba tp=0/fp=18. Se asierta
    # tal cual para que quede a la vista que la union sin reconciliador no vale
    # como salida, que es justo por lo que existe D-R.
    assert d_claims["tp"] == 2 and d_claims["fp"] == 18

    # D-R es la salida real del pipeline y es la que tiene que sostener la
    # precision. Los 2 claims deterministas hablan de las MISMAS relaciones que
    # dos claims semanticos; sin fundirlos, sobrevivian como duplicados y metian
    # 2 fp netos nuevos (fp=12). Con la fusion de propuestas co-referentes del
    # reconciliador vuelven a fp=10, el baseline pre-B2, sin perder ningun tp.
    assert dr_claims["tp"] == 8 and dr_claims["fp"] == 10
    assert dr_claims["fp"] <= c1_claims["fp"], (
        "la union reconciliada no puede introducir falsos positivos netos "
        "respecto al extractor semantico solo"
    )
    assert dr_claims["tp"] >= c1_claims["tp"] == 8
