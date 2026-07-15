# -*- coding: utf-8 -*-
"""Tests del planificador de procesamiento externo (Fase B1).

Tests 1-5: seleccion de modo y estimaciones.
"""
import os
import pytest
from pathlib import Path

# Ajustar PYTHONPATH
import sys
_HERE = Path(__file__).resolve().parent
_APP = _HERE.parent.parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from external_processing.manifests import BatchFile
from external_processing.models import ProcessingMode
from external_processing.planner import BurstPlanner, PlannerConfig, SourceLoad, _select_mode, _estimate_local_seconds


REPO_ROOT = _APP.parent.parent


def _make_audio_file(duration_seconds: float) -> BatchFile:
    return BatchFile(
        private_path="/private/audio.mp3",
        sanitized_name="audio.mp3",
        mime_type="audio/mpeg",
        size_bytes=int(duration_seconds * 16000),
        file_hash="a" * 64,
        duration_seconds=duration_seconds,
    )


def _make_pdf_file(pages: int) -> BatchFile:
    return BatchFile(
        private_path="/private/doc.pdf",
        sanitized_name="doc.pdf",
        mime_type="application/pdf",
        size_bytes=pages * 50000,
        file_hash="b" * 64,
        pages=pages,
    )


def _make_image_file(count: int = 1) -> BatchFile:
    return BatchFile(
        private_path="/private/img.jpg",
        sanitized_name="img.jpg",
        mime_type="image/jpeg",
        size_bytes=count * 200000,
        file_hash="c" * 64,
        image_count=count,
    )


# ── Test 1: modo local con carga pequeña ─────────────────────────────────────

def test_seleccion_modo_local_carga_pequena():
    """Carga pequeña debe seleccionar modo LOCAL."""
    cfg = PlannerConfig()
    load = SourceLoad()
    load.audio_minutes = 5.0  # < 30 (limite local)
    load.pdf_pages = 5         # < 20
    load.images = 3            # < 10

    mode, codes = _select_mode(load, cfg)
    assert mode == ProcessingMode.LOCAL
    assert "WITHIN_LOCAL_LIMITS" in codes


# ── Test 2: modo hybrid con carga media ──────────────────────────────────────

def test_seleccion_modo_hybrid_audio():
    """Audio entre limite local y burst -> HYBRID."""
    cfg = PlannerConfig()
    load = SourceLoad()
    load.audio_minutes = 60.0   # > 30 (local) pero < 120 (burst)
    load.pdf_pages = 0
    load.images = 0

    mode, codes = _select_mode(load, cfg)
    assert mode == ProcessingMode.HYBRID
    assert "AUDIO_DURATION_EXCEEDS_LOCAL_LIMIT" in codes


def test_seleccion_modo_hybrid_pdf():
    """PDF entre limite local y burst -> HYBRID."""
    cfg = PlannerConfig()
    load = SourceLoad()
    load.audio_minutes = 0
    load.pdf_pages = 40   # > 20 pero < 60
    load.images = 0

    mode, codes = _select_mode(load, cfg)
    assert mode == ProcessingMode.HYBRID
    assert "PDF_PAGES_EXCEEDS_LOCAL_LIMIT" in codes


# ── Test 3: modo burst con carga grande ──────────────────────────────────────

def test_seleccion_modo_burst_audio_grande():
    """Audio >= 120 min -> BURST."""
    cfg = PlannerConfig()
    load = SourceLoad()
    load.audio_minutes = 150.0
    load.pdf_pages = 0
    load.images = 0

    mode, codes = _select_mode(load, cfg)
    assert mode == ProcessingMode.BURST
    assert "AUDIO_DURATION_EXCEEDS_BURST_THRESHOLD" in codes


def test_seleccion_modo_burst_imagenes():
    """Muchas imagenes -> BURST."""
    cfg = PlannerConfig()
    load = SourceLoad()
    load.audio_minutes = 0
    load.pdf_pages = 0
    load.images = 50  # >= 30

    mode, codes = _select_mode(load, cfg)
    assert mode == ProcessingMode.BURST
    assert "IMAGE_COUNT_EXCEEDS_BURST_THRESHOLD" in codes


def test_seleccion_modo_burst_pdf_grande():
    """PDF >= 60 paginas -> BURST."""
    cfg = PlannerConfig()
    load = SourceLoad()
    load.audio_minutes = 0
    load.pdf_pages = 80
    load.images = 0

    mode, codes = _select_mode(load, cfg)
    assert mode == ProcessingMode.BURST
    assert "PDF_PAGES_EXCEEDS_BURST_THRESHOLD" in codes


# ── Test 4: estimacion de carga con metrica ──────────────────────────────────

def test_estimacion_con_metricas():
    """Con metricas disponibles -> HIGH confidence."""
    load = SourceLoad()
    load.audio_minutes = 10.0
    load.pdf_pages = 5
    load.images = 2

    secs, confidence = _estimate_local_seconds(load, has_metrics=True)
    assert secs > 0
    assert confidence == "HIGH"


# ── Test 5: estimacion sin metricas -> LOW_CONFIDENCE ────────────────────────

def test_estimacion_sin_metricas():
    """Sin metricas historicas -> ESTIMATE_LOW_CONFIDENCE."""
    load = SourceLoad()
    load.audio_minutes = 30.0

    secs, confidence = _estimate_local_seconds(load, has_metrics=False)
    assert secs > 0
    assert confidence == "ESTIMATE_LOW_CONFIDENCE"


# ── Test de planner completo ──────────────────────────────────────────────────

def test_planner_genera_plan_correcto(tmp_path):
    """Planner genera plan con modo correcto y jobs."""
    planner = BurstPlanner(tmp_path)
    bf = _make_audio_file(duration_seconds=120.0)  # 2 min -> local

    plan = planner.plan(
        workspace="test_ws",
        source_id="source_001",
        source_path="/data/audio.mp3",
        source_hash="a" * 64,
        files=[bf],
        dry_run=True,
    )

    assert plan.workspace == "test_ws"
    assert plan.source_id == "source_001"
    assert plan.selected_mode in (ProcessingMode.LOCAL, ProcessingMode.HYBRID, ProcessingMode.BURST)
    assert len(plan.jobs) >= 1
    assert plan.dry_run is True


def test_planner_override_modo(tmp_path):
    """Override de modo respeta el valor especificado."""
    planner = BurstPlanner(tmp_path)
    bf = _make_audio_file(duration_seconds=10.0)  # seria LOCAL normalmente

    plan = planner.plan(
        workspace="ws",
        source_id="s",
        source_path="/p",
        source_hash="x" * 64,
        files=[bf],
        mode_override=ProcessingMode.BURST,
        dry_run=True,
    )

    assert plan.selected_mode == ProcessingMode.BURST


def test_planner_explain_formato(tmp_path):
    """Explain devuelve dict con claves requeridas."""
    planner = BurstPlanner(tmp_path)
    bf = _make_pdf_file(pages=5)

    plan = planner.plan("ws", "s", "/p", "h" * 64, [bf], dry_run=True)
    exp = planner.explain(plan)

    assert "selected_mode" in exp
    assert "reason_codes" in exp
    assert isinstance(exp["reason_codes"], list)
