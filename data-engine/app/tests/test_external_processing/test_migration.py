# -*- coding: utf-8 -*-
"""Test 30: compatibilidad de migracion SQLite.

Verifica que jobs existentes no se ven afectados por los nuevos campos
de la Fase B1 (batch_id, processing_mode, provider, model, etc.).
"""
import os
import sqlite3
import tempfile
import pytest
from pathlib import Path
import sys

_APP = Path(__file__).resolve().parent.parent.parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))


def _get_columns(db_path: str) -> set:
    conn = sqlite3.connect(db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    conn.close()
    return cols


# ── Test 30: jobs existentes no afectados por migracion ──────────────────────

def test_migracion_idempotente_no_rompe_jobs_existentes():
    """La migracion B1 es idempotente y los jobs existentes mantienen sus datos."""
    from jobs.job_store import init_db, create_job, get_job

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_jobs.db")

        # Inicializar base de datos
        init_db(db_path)

        # Crear job existente (antes de la migracion hipotetica)
        job_id = create_job(
            workspace="test_workspace",
            source_kind="audio",
            source_url="http://example.com/audio.mp3",
            db_path=db_path,
        )
        assert job_id is not None

        # Re-inicializar (simula migracion idempotente)
        init_db(db_path)

        # El job existente sigue siendo accesible
        job = get_job(job_id, db_path=db_path)
        assert job is not None
        assert job["workspace"] == "test_workspace"
        assert job["source_kind"] == "audio"

        # Los nuevos campos B1 existen en el esquema
        cols = _get_columns(db_path)
        assert "batch_id" in cols, "batch_id debe existir tras migracion B1"
        assert "processing_mode" in cols
        assert "provider" in cols
        assert "model" in cols
        assert "task_type" in cols
        assert "chunk_json" in cols
        assert "progress" in cols
        assert "error_code" in cols

        # El job existente tiene los nuevos campos en NULL (compatibilidad)
        assert job.get("batch_id") is None
        assert job.get("processing_mode") is None


def test_migracion_nuevos_campos_nulos_en_jobs_antiguos():
    """Jobs creados antes de la migracion tienen los nuevos campos en NULL."""
    from jobs.job_store import init_db, create_job, list_jobs

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_legacy.db")
        init_db(db_path)

        job_id = create_job(
            workspace="legacy_ws",
            source_kind="book",
            db_path=db_path,
        )

        jobs = list_jobs(workspace="legacy_ws", db_path=db_path)
        assert len(jobs) >= 1
        job = next(j for j in jobs if j["job_id"] == job_id)

        # Campos B1 son NULL en jobs legacy
        assert job.get("batch_id") is None
        assert job.get("provider") is None


def test_migracion_idempotente_multiples_llamadas():
    """init_db() puede llamarse multiples veces sin error (idempotente)."""
    from jobs.job_store import init_db

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_idempotent.db")
        init_db(db_path)
        init_db(db_path)  # segunda llamada: no debe fallar
        init_db(db_path)  # tercera llamada
        cols = _get_columns(db_path)
        assert "batch_id" in cols
