# -*- coding: utf-8 -*-
"""Puerta 4, bloque B3: carril semantico NVIDIA en SOMBRA.

SIN RED: toda respuesta "de NVIDIA" en este fichero es un `MockProviderPort`
guionizado. Los tests cubren:

  * `RetryingPort`/`MeteringPort` (parseo, backoff, metering) con dobles.
  * que el modulo `scripts.gate4.measure_b3` NUNCA importa ni invoca ningun
    escritor de Neo4j (modo sombra real, no solo declarado);
  * que la API key de NVIDIA (leida de `~/.config/s9k/nvidia.env`, si existe)
    no aparece en absolutamente ninguna salida generada por esta suite, ni en
    stdout/stderr capturados ni en los ficheros de `artifacts/` que toque el
    test.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1]
_REPO_ROOT = _APP.parents[1]
_SCRIPTS = _REPO_ROOT / "scripts" / "gate4"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import measure_b3 as b3  # noqa: E402  (path insertado arriba a proposito)
from knowledge_v3.extraction.provider_port import (  # noqa: E402
    MockProviderPort,
    ProviderRequest,
    ProviderUnavailable,
)


# ---------------------------------------------------------------------------
# RetryingPort: backoff exponencial, timeout duro, no reintenta BadJSON
# ---------------------------------------------------------------------------
def test_retrying_port_reintenta_fallos_transitorios_y_luego_acierta():
    calls = {"n": 0}

    def handler(_req: ProviderRequest):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderUnavailable("RateLimitError")
        return {"mentions": [], "claims": [], "abstentions": []}

    inner = MockProviderPort(handler=handler)
    sleeps: list[float] = []
    retrying = b3.RetryingPort(inner, max_retries=5, base_backoff=1.0, sleep=sleeps.append)

    reply = retrying.complete_json(ProviderRequest(system="s", prompt="p"))
    assert reply.payload == {"mentions": [], "claims": [], "abstentions": []}
    assert calls["n"] == 3
    assert retrying.retries_used == 2
    # Backoff exponencial: 1, 2 (base=1.0, intentos 0 y 1)
    assert sleeps == [1.0, 2.0]


def test_retrying_port_agota_reintentos_y_propaga_el_ultimo_error():
    inner = MockProviderPort(handler=lambda _r: ProviderUnavailable("ProviderUnavailableError"))
    retrying = b3.RetryingPort(inner, max_retries=2, base_backoff=0.0, sleep=lambda _s: None)
    with pytest.raises(ProviderUnavailable):
        retrying.complete_json(ProviderRequest(system="s", prompt="p"))
    assert retrying.retries_used == 2


def test_retrying_port_no_reintenta_json_invalido():
    """Un JSON malformado no es un fallo de transporte: no debe reintentarse aqui."""
    from knowledge_v3.extraction.provider_port import ProviderBadJSON

    calls = {"n": 0}

    def handler(_req):
        calls["n"] += 1
        return ProviderBadJSON("no es JSON")

    inner = MockProviderPort(handler=handler)
    retrying = b3.RetryingPort(inner, max_retries=3, base_backoff=0.0, sleep=lambda _s: None)
    with pytest.raises(ProviderBadJSON):
        retrying.complete_json(ProviderRequest(system="s", prompt="p"))
    assert calls["n"] == 1  # ni un reintento
    assert retrying.retries_used == 0


def test_retrying_port_timeout_duro():
    import time as _time

    def lento(_req):
        _time.sleep(5)
        return {"mentions": [], "claims": [], "abstentions": []}

    inner = MockProviderPort(handler=lento)
    retrying = b3.RetryingPort(
        inner, max_retries=0, base_backoff=0.0, timeout_seconds=1, sleep=lambda _s: None
    )
    with pytest.raises(ProviderUnavailable):
        retrying.complete_json(ProviderRequest(system="s", prompt="p"))
    assert retrying.timeouts == 1


# ---------------------------------------------------------------------------
# MeteringPort: registra tokens/latencia SOLO de llamadas reales
# ---------------------------------------------------------------------------
def test_metering_port_registra_tokens_y_latencia_de_llamadas_reales():
    inner = MockProviderPort(
        responses=[{"mentions": [], "claims": [], "abstentions": []}], latency_ms=42
    )
    metered = b3.MeteringPort(inner)
    metered.complete_json(ProviderRequest(system="s", prompt="p", purpose="extraction"))
    assert len(metered.calls) == 1
    call = metered.calls[0]
    assert call["ok"] is True
    assert call["latency_ms"] == 42
    assert call["purpose"] == "extraction"


def test_metering_port_no_registra_aciertos_de_cache():
    """El metering va DEBAJO de `CachingPort`: un hit de cache no pasa por aqui."""
    from knowledge_v3.extraction import semantic_bench as bench

    inner = MockProviderPort(
        responses=[
            {"mentions": [], "claims": [], "abstentions": []},
            {"mentions": [], "claims": [], "abstentions": []},
        ]
    )
    metered = b3.MeteringPort(inner)
    cached = bench.CachingPort(metered, path=None)
    req = ProviderRequest(system="s", prompt="p")
    cached.complete_json(req)
    cached.complete_json(req)  # misma peticion: acierto de cache
    assert cached.hits == 1
    assert cached.misses == 1
    assert len(metered.calls) == 1  # solo la llamada real llego al metering


# ---------------------------------------------------------------------------
# family_recall / b3_gates: scoring con datos sinteticos, sin gold real
# ---------------------------------------------------------------------------
def test_family_recall_cuenta_positivo_para_negado_como_error():
    from knowledge_v3.benchmarks.loader import GoldSource, GoldDataset
    from knowledge_v3.benchmarks.matching import MatchConfig

    gold_claim = {
        "claim_id": "c1",
        "episode_id": "e1",
        "negated": True,
        "subject_mentions": ["gm1"],
        "object_mentions": ["gm2"],
        "abstained": False,
        "metadata": {"negation": {"family": "SIMPLE"}},
    }
    gold_mentions = [
        {"mention_id": "gm1", "episode_id": "e1", "start": 0, "end": 3},
        {"mention_id": "gm2", "episode_id": "e1", "start": 4, "end": 7},
    ]
    source = GoldSource(
        source_id="s1",
        world="test-world",
        asset={"asset_id": "asset:s1"},
        episodes=[{"episode_id": "e1"}],
        fragments=[],
        mentions=gold_mentions,
        resolutions=[],
        claims=[gold_claim],
        assertions=[],
        plans=[],
        negatives=[],
    )
    gold = GoldDataset(split="negation", manifest={}, entities=[], profiles={}, sources=[source])

    class Bundle:
        mentions = [
            {"mention_id": "pm1", "episode_id": "e1", "start": 0, "end": 3},
            {"mention_id": "pm2", "episode_id": "e1", "start": 4, "end": 7},
        ]
        claims = [
            {
                "claim_id": "p1",
                "episode_id": "e1",
                "negated": False,  # el carril afirma lo que el gold niega
                "subject_mentions": ["pm1"],
                "object_mentions": ["pm2"],
                "abstained": False,
            }
        ]

    metrics = b3.family_recall(gold, Bundle(), MatchConfig())
    assert metrics["coverage"] == 1.0       # emparejo la relacion
    assert metrics["recall_overall"] == 0.0  # pero con la polaridad al reves
    assert metrics["recall_simple"] == 0.0
    gates = b3.b3_gates("nvidia", metrics)
    assert gates["recall_simple"]["veredicto"] == "NO_CONFORME"


# ---------------------------------------------------------------------------
# Modo sombra: measure_b3 nunca toca ningun escritor de Neo4j
# ---------------------------------------------------------------------------
def test_measure_b3_no_importa_ningun_modulo_de_escritura_neo4j():
    """Import estatico: si `measure_b3` importase el writer, apareceria aqui."""
    src = (_SCRIPTS / "measure_b3.py").read_text(encoding="utf-8")
    prohibido = ("writer.writer", "writer.executor", "writer.cli", "neo4j")
    hallados = [p for p in prohibido if p in src]
    assert not hallados, f"measure_b3.py referencia escritura/Neo4j: {hallados}"


def test_measure_b3_modulo_cargado_no_registra_ningun_writer_en_sys_modules():
    """Tras importar measure_b3 (arriba, a nivel de modulo), ningun writer real
    debe estar cargado en sys.modules POR CULPA de esa importacion: si lo
    estuviera, `knowledge_v3.writer.writer` apareceria."""
    assert "knowledge_v3.writer.writer" not in sys.modules
    assert "knowledge_v3.writer.executor" not in sys.modules


def test_mock_run_end_to_end_no_escribe_fuera_del_directorio_de_salida(tmp_path):
    """Corrida completa en `--mock` (sin red): produce su informe y nada mas."""
    out_dir = tmp_path / "out"
    cache = tmp_path / "cache.json"
    rc = b3.main(
        [
            "--mock",
            "--out-dir",
            str(out_dir),
            "--out-name",
            "b3-test",
            "--cache",
            str(cache),
        ]
    )
    assert rc == 0
    produced = {p.name for p in out_dir.iterdir()}
    assert produced == {"b3-test.json", "b3-test.md"}


# ---------------------------------------------------------------------------
# La API key de NVIDIA NUNCA aparece en ningun artefacto ni log de esta suite
# ---------------------------------------------------------------------------
def _real_nvidia_api_key() -> str | None:
    env_path = Path.home() / ".config" / "s9k" / "nvidia.env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("S9K_NVIDIA_API_KEY="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            return value or None
    return None


def test_la_api_key_real_nunca_aparece_en_la_salida_de_este_fichero_de_test(capsys, tmp_path):
    """Si hay una key real disponible en la maquina, se comprueba que ejecutar
    este mismo fichero de tests (en modo mock, sin red) no la deja escapar ni
    por stdout/stderr ni por ningun artefacto que produzca.
    """
    key = _real_nvidia_api_key()
    if not key:
        pytest.skip("no hay ~/.config/s9k/nvidia.env en esta maquina; nada que comprobar")

    out_dir = tmp_path / "out"
    b3.main(["--mock", "--out-dir", str(out_dir), "--out-name", "b3-key-check", "--cache", str(tmp_path / "c.json")])
    captured = capsys.readouterr()
    assert key not in captured.out
    assert key not in captured.err
    for produced in out_dir.rglob("*"):
        if produced.is_file():
            assert key not in produced.read_text(encoding="utf-8", errors="replace")


def test_la_api_key_real_no_aparece_en_los_artefactos_ya_commiteados_de_b3():
    """Grep final contra los artefactos versionados del bloque B3 (no el cache,
    que esta fuera de git -- ver `.gitignore`)."""
    key = _real_nvidia_api_key()
    if not key:
        pytest.skip("no hay ~/.config/s9k/nvidia.env en esta maquina; nada que comprobar")
    program_dir = _REPO_ROOT / "artifacts" / "gate4-program"
    for name in ("b3-nvidia-shadow.json", "b3-nvidia-shadow.md"):
        path = program_dir / name
        if path.exists():
            assert key not in path.read_text(encoding="utf-8", errors="replace")
