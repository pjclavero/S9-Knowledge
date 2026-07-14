"""Regresión (Prioridad 2 benchmark): el subcomando `extract` aislado debe
honrar --extractor.

Bug demostrado por el benchmark real (2026-07-14): `data_review.py extract
--extractor llm|hybrid` ejecutaba SIEMPRE el extractor heurístico
(extractor.run), sin llamar nunca a Ollama — los runs LLM/hybrid producían
candidatos idénticos al heurístico en ~100ms y se contaban como OK.

Fix: cmd_extract delega en review.pipeline._run_extract_step para llm|hybrid,
que es el dispatch que realmente invoca al LLM. Estos tests no dependen de
Ollama ni Neo4j.
"""
from __future__ import annotations
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_APP_DIR = _TESTS_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from cli import data_review  # noqa: E402
import review.pipeline as pipeline  # noqa: E402
import review.extractor as heuristic_extractor  # noqa: E402


def _seed_segments(repo_root: Path, workspace: str, source_id: str) -> Path:
    out_dir = repo_root / "output" / "reviews" / workspace / source_id
    out_dir.mkdir(parents=True, exist_ok=True)
    seg = [{
        "segment_id": f"{source_id}_seg_0001",
        "source_id": source_id,
        "source_kind": "transcript_session",
        "workspace": workspace,
        "timestamp_start": "00:00:00",
        "timestamp_end": "00:01:00",
        "text": "Kakita Asuka llegó a Ciudad Moto.",
        "should_extract": True,
    }]
    (out_dir / "segments.classified.json").write_text(
        json.dumps(seg, ensure_ascii=False), encoding="utf-8")
    return out_dir


@pytest.mark.parametrize("mode", ["llm", "hybrid"])
def test_extract_llm_hybrid_routes_to_pipeline_dispatch(tmp_path, monkeypatch, capsys, mode):
    """llm|hybrid deben pasar por _run_extract_step (dispatch LLM), NO por extractor.run."""
    _seed_segments(tmp_path, "test_ws", "src_dispatch")
    monkeypatch.setattr(data_review, "_REPO_ROOT", tmp_path)

    calls = {"dispatch": None, "heuristic_run": 0}

    def fake_dispatch(workspace, source_id, repo_root, m, classified):
        calls["dispatch"] = m
        out = repo_root / "output" / "reviews" / workspace / source_id / "candidates.json"
        out.write_text("[]", encoding="utf-8")
        return []

    def fake_heuristic_run(*a, **k):
        calls["heuristic_run"] += 1
        raise AssertionError("extractor.run() no debe usarse para modo llm/hybrid")

    monkeypatch.setattr(pipeline, "_run_extract_step", fake_dispatch)
    monkeypatch.setattr(heuristic_extractor, "run", fake_heuristic_run)

    data_review.cmd_extract(Namespace(workspace="test_ws", source_id="src_dispatch", extractor=mode))

    assert calls["dispatch"] == mode
    assert calls["heuristic_run"] == 0


def test_extract_heuristic_uses_extractor_run(tmp_path, monkeypatch):
    """heuristic debe seguir usando extractor.run (path heurístico puro)."""
    _seed_segments(tmp_path, "test_ws", "src_heur")
    monkeypatch.setattr(data_review, "_REPO_ROOT", tmp_path)

    calls = {"heuristic_run": 0, "dispatch": 0}

    def fake_heuristic_run(workspace, source_id, repo_root):
        calls["heuristic_run"] += 1
        return repo_root / "output" / "reviews" / workspace / source_id / "candidates.json"

    def fake_dispatch(*a, **k):
        calls["dispatch"] += 1
        raise AssertionError("_run_extract_step no debe usarse para modo heuristic")

    monkeypatch.setattr(heuristic_extractor, "run", fake_heuristic_run)
    monkeypatch.setattr(pipeline, "_run_extract_step", fake_dispatch)

    data_review.cmd_extract(Namespace(workspace="test_ws", source_id="src_heur", extractor="heuristic"))

    assert calls["heuristic_run"] == 1
    assert calls["dispatch"] == 0
