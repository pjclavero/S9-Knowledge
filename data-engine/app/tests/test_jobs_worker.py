"""Tests del worker genérico (noop/echo). No escribe en Neo4j ni toca datos reales."""
from jobs import job_store, worker


def _db(tmp_path) -> str:
    path = str(tmp_path / "jobs.db")
    job_store.init_db(path)
    return path


def test_worker_processes_echo_job(tmp_path):
    db = _db(tmp_path)
    job_id = job_store.create_job("leyenda", job_type="echo",
                                  payload={"message": "prueba worker"}, db_path=db)

    processed = worker.run("worker-test", once=True, limit=1, db_path=db)

    assert processed == 1
    job = job_store.get_job(job_id, db_path=db)
    assert job["status"] == "complete"
    import json
    result = json.loads(job["result_json"])
    assert result == {"echo": {"message": "prueba worker"}}


def test_worker_processes_noop_job(tmp_path):
    db = _db(tmp_path)
    job_store.create_job("leyenda", job_type="noop", db_path=db)

    processed = worker.run("worker-test", once=True, limit=1, db_path=db)
    assert processed == 1


def test_worker_marks_unknown_job_type_as_skipped(tmp_path):
    db = _db(tmp_path)
    job_id = job_store.create_job("leyenda", job_type="media_probe", db_path=db)

    processed = worker.run("worker-test", once=True, limit=1, db_path=db)

    assert processed == 1
    job = job_store.get_job(job_id, db_path=db)
    assert job["status"] == "skipped"
    assert "media_probe" in job["error_message"]


def test_worker_stops_when_no_pending_jobs(tmp_path):
    db = _db(tmp_path)
    processed = worker.run("worker-test", once=True, limit=5, db_path=db)
    assert processed == 0


def test_worker_dry_run_does_not_claim(tmp_path):
    db = _db(tmp_path)
    job_id = job_store.create_job("leyenda", job_type="echo", db_path=db)

    count = worker.run("worker-test", dry_run=True, limit=10, db_path=db)

    assert count == 1
    job = job_store.get_job(job_id, db_path=db)
    assert job["status"] == "pending"       # dry-run no modifica nada


def test_worker_respects_job_type_filter(tmp_path):
    db = _db(tmp_path)
    noop_id = job_store.create_job("leyenda", job_type="noop", db_path=db)
    echo_id = job_store.create_job("leyenda", job_type="echo", db_path=db)

    worker.run("worker-test", once=True, limit=1, job_type="echo", db_path=db)

    assert job_store.get_job(echo_id, db_path=db)["status"] == "complete"
    assert job_store.get_job(noop_id, db_path=db)["status"] == "pending"


def test_worker_processes_multiple_jobs_up_to_limit(tmp_path):
    db = _db(tmp_path)
    for _ in range(3):
        job_store.create_job("leyenda", job_type="noop", db_path=db)

    processed = worker.run("worker-test", once=True, limit=2, db_path=db)
    assert processed == 2

    counts = job_store.get_counts_by_status(workspace="leyenda", db_path=db)
    assert counts.get("complete") == 2
    assert counts.get("pending") == 1
