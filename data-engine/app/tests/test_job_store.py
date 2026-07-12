"""Tests de la cola genérica añadida a job_store.py (Fase jobs-worker-panel).

No tocan Neo4j. Usan bases de datos SQLite temporales (tmpfile), nunca la
DB real. Cubren también que el modo de ingesta de fuentes (histórico) sigue
funcionando sin cambios de comportamiento.
"""
import time

import pytest

from jobs import job_store


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "jobs.db")
    job_store.init_db(path)
    return path


# ── Compatibilidad con el modo histórico (source_kind) ────────────────────────

def test_legacy_source_kind_mode_still_works(db):
    job_id = job_store.create_job("leyenda", "test", source_path="/x/y.pdf", db_path=db)
    job = job_store.get_job(job_id, db_path=db)
    assert job["status"] == "pending"
    assert job["source_kind"] == "test"
    assert job["job_type"] is None


# ── Modo genérico ──────────────────────────────────────────────────────────

def test_create_job_generic_defaults_to_generic_source_kind(db):
    job_id = job_store.create_job("leyenda", job_type="echo", payload={"message": "hola"}, db_path=db)
    job = job_store.get_job(job_id, db_path=db)
    assert job["status"] == "pending"
    assert job["source_kind"] == "generic"
    assert job["job_type"] == "echo"
    assert job["attempts"] == 0
    assert job["max_attempts"] == 3
    import json
    assert json.loads(job["payload_json"]) == {"message": "hola"}


def test_create_job_requires_source_kind_or_job_type(db):
    with pytest.raises(ValueError):
        job_store.create_job("leyenda", db_path=db)


def test_list_jobs_filters_by_workspace_and_status(db):
    job_store.create_job("leyenda", job_type="echo", db_path=db)
    job_store.create_job("otro_ws", job_type="echo", db_path=db)

    leyenda_jobs = job_store.list_jobs(workspace="leyenda", db_path=db)
    assert len(leyenda_jobs) == 1
    assert leyenda_jobs[0]["workspace"] == "leyenda"

    pending_jobs = job_store.list_jobs(status="pending", db_path=db)
    assert len(pending_jobs) == 2


def test_list_jobs_filters_by_job_type_and_limit(db):
    job_store.create_job("leyenda", job_type="echo", db_path=db)
    job_store.create_job("leyenda", job_type="noop", db_path=db)

    echo_jobs = job_store.list_jobs(job_type="echo", db_path=db)
    assert len(echo_jobs) == 1
    assert echo_jobs[0]["job_type"] == "echo"

    limited = job_store.list_jobs(limit=1, db_path=db)
    assert len(limited) == 1


def test_claim_next_job_locks_and_marks_running(db):
    job_id = job_store.create_job("leyenda", job_type="echo", db_path=db)

    claimed = job_store.claim_next_job("worker-1", db_path=db)
    assert claimed["job_id"] == job_id
    assert claimed["status"] == "running"
    assert claimed["locked_by"] == "worker-1"
    assert claimed["started_at"] is not None

    # Ya no debe quedar pending para un segundo worker.
    second = job_store.claim_next_job("worker-2", db_path=db)
    assert second is None


def test_claim_next_job_respects_job_types_filter(db):
    job_store.create_job("leyenda", job_type="noop", db_path=db)
    echo_id = job_store.create_job("leyenda", job_type="echo", db_path=db)

    claimed = job_store.claim_next_job("worker-1", job_types=["echo"], db_path=db)
    assert claimed["job_id"] == echo_id


def test_claim_next_job_priority_order(db):
    low = job_store.create_job("leyenda", job_type="echo", priority=0, db_path=db)
    high = job_store.create_job("leyenda", job_type="echo", priority=10, db_path=db)

    claimed = job_store.claim_next_job("worker-1", db_path=db)
    assert claimed["job_id"] == high

    claimed2 = job_store.claim_next_job("worker-1", db_path=db)
    assert claimed2["job_id"] == low


def test_mark_complete_saves_result_and_clears_lock(db):
    job_id = job_store.create_job("leyenda", job_type="echo", db_path=db)
    job_store.claim_next_job("worker-1", db_path=db)

    ok = job_store.mark_complete(job_id, result={"message": "hola"}, db_path=db)
    assert ok
    job = job_store.get_job(job_id, db_path=db)
    assert job["status"] == "complete"
    assert job["locked_by"] is None
    assert job["finished_at"] is not None
    import json
    assert json.loads(job["result_json"]) == {"message": "hola"}


def test_mark_failed_increments_attempts_and_retries(db):
    job_id = job_store.create_job("leyenda", job_type="echo", max_attempts=3, db_path=db)
    job_store.claim_next_job("worker-1", db_path=db)

    job_store.mark_failed(job_id, "boom", retry=True, db_path=db)
    job = job_store.get_job(job_id, db_path=db)
    assert job["attempts"] == 1
    assert job["status"] == "pending"        # todavía le quedan reintentos
    assert job["error_message"] == "boom"
    assert job["locked_by"] is None


def test_mark_failed_exhausts_retries(db):
    job_id = job_store.create_job("leyenda", job_type="echo", max_attempts=2, db_path=db)

    job_store.claim_next_job("worker-1", db_path=db)
    job_store.mark_failed(job_id, "boom 1", retry=True, db_path=db)   # attempts=1, pending

    job_store.claim_next_job("worker-1", db_path=db)
    job_store.mark_failed(job_id, "boom 2", retry=True, db_path=db)   # attempts=2 == max → failed

    job = job_store.get_job(job_id, db_path=db)
    assert job["attempts"] == 2
    assert job["status"] == "failed"
    assert job["finished_at"] is not None


def test_mark_cancelled(db):
    job_id = job_store.create_job("leyenda", job_type="echo", db_path=db)
    ok = job_store.mark_cancelled(job_id, db_path=db)
    assert ok
    job = job_store.get_job(job_id, db_path=db)
    assert job["status"] == "cancelled"


def test_mark_skipped(db):
    job_id = job_store.create_job("leyenda", job_type="unimplemented_type", db_path=db)
    job_store.claim_next_job("worker-1", db_path=db)
    ok = job_store.mark_skipped(job_id, message="sin handler", db_path=db)
    assert ok
    job = job_store.get_job(job_id, db_path=db)
    assert job["status"] == "skipped"
    assert job["error_message"] == "sin handler"


def test_heartbeat_only_updates_if_locked_by_same_worker(db):
    job_id = job_store.create_job("leyenda", job_type="echo", db_path=db)
    job_store.claim_next_job("worker-1", db_path=db)

    assert job_store.heartbeat(job_id, "worker-1", db_path=db) is True
    assert job_store.heartbeat(job_id, "worker-2", db_path=db) is False


def test_release_stale_jobs_returns_to_pending_when_retries_left(db):
    job_id = job_store.create_job("leyenda", job_type="echo", max_attempts=3, db_path=db)
    job_store.claim_next_job("worker-dead", db_path=db)

    # _now_iso() trunca a segundos enteros: con timeout_seconds=1 hace falta
    # más de 1s de margen extra para evitar falsos negativos en el borde de
    # segundo (locked_at y cutoff cayendo en el mismo segundo truncado).
    time.sleep(2.5)
    released = job_store.release_stale_jobs(1, db_path=db)
    assert job_id in released

    job = job_store.get_job(job_id, db_path=db)
    assert job["status"] == "pending"
    assert job["locked_by"] is None


def test_release_stale_jobs_fails_when_no_retries_left(db):
    # max_attempts=0: no le queda ningún reintento disponible desde el principio.
    job_id = job_store.create_job("leyenda", job_type="echo", max_attempts=0, db_path=db)
    job_store.claim_next_job("worker-dead", db_path=db)

    # _now_iso() trunca a segundos enteros: con timeout_seconds=1 hace falta
    # más de 1s de margen extra para evitar falsos negativos en el borde de
    # segundo (locked_at y cutoff cayendo en el mismo segundo truncado).
    time.sleep(2.5)
    released = job_store.release_stale_jobs(1, db_path=db)
    assert job_id in released

    job = job_store.get_job(job_id, db_path=db)
    assert job["status"] == "failed"


def test_get_counts_by_status(db):
    job_store.create_job("leyenda", job_type="echo", db_path=db)
    job_store.create_job("leyenda", job_type="echo", db_path=db)
    job_store.claim_next_job("worker-1", db_path=db)

    counts = job_store.get_counts_by_status(workspace="leyenda", db_path=db)
    assert counts.get("pending") == 1
    assert counts.get("running") == 1


def test_resolve_db_path_prefers_explicit_arg(monkeypatch):
    monkeypatch.setenv("S9K_JOBS_DB", "/env/path/jobs.db")
    assert job_store.resolve_db_path("/explicit/jobs.db") == "/explicit/jobs.db"
    assert job_store.resolve_db_path(None) == "/env/path/jobs.db"


def test_resolve_db_path_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("S9K_JOBS_DB", raising=False)
    assert job_store.resolve_db_path(None) == job_store.DEFAULT_DB_PATH
