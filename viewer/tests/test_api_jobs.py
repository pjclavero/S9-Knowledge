"""Tests del panel/API de jobs del visor (solo lectura, no crea/cancela/borra)."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def _data_engine_app_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data-engine" / "app"


def _make_temp_jobs_db(tmp_path) -> str:
    sys.path.insert(0, str(_data_engine_app_dir()))
    from jobs import job_store  # type: ignore

    db_path = str(tmp_path / "jobs.db")
    job_store.init_db(db_path)
    job_store.create_job("leyenda", job_type="echo", payload={"message": "hola"}, db_path=db_path)
    job_store.create_job("leyenda", job_type="noop", db_path=db_path)
    return db_path


def test_api_jobs_reports_not_found_when_db_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("S9K_JOBS_DB", str(tmp_path / "no_existe" / "jobs.db"))
    from app.main import app

    client = TestClient(app)
    response = client.get("/api/jobs")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["error"] == "jobs_db_not_found"


def test_api_jobs_returns_jobs_with_temp_db(monkeypatch, tmp_path):
    db_path = _make_temp_jobs_db(tmp_path)
    monkeypatch.setenv("S9K_JOBS_DB", db_path)
    from app.main import app

    client = TestClient(app)
    response = client.get("/api/jobs", params={"workspace": "leyenda"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert len(data["jobs"]) == 2
    types = {j["type"] for j in data["jobs"]}
    assert types == {"echo", "noop"}


def test_api_jobs_counts(monkeypatch, tmp_path):
    db_path = _make_temp_jobs_db(tmp_path)
    monkeypatch.setenv("S9K_JOBS_DB", db_path)
    from app.main import app

    client = TestClient(app)
    response = client.get("/api/jobs/counts", params={"workspace": "leyenda"})
    data = response.json()
    assert data["ok"] is True
    assert data["counts"].get("pending") == 2


def test_api_job_detail_not_found(monkeypatch, tmp_path):
    db_path = _make_temp_jobs_db(tmp_path)
    monkeypatch.setenv("S9K_JOBS_DB", db_path)
    from app.main import app

    client = TestClient(app)
    response = client.get("/api/jobs/does-not-exist")
    data = response.json()
    assert data["ok"] is False
    assert data["error"] == "job_not_found"


def test_jobs_panel_renders_html(monkeypatch, tmp_path):
    db_path = _make_temp_jobs_db(tmp_path)
    monkeypatch.setenv("S9K_JOBS_DB", db_path)
    from app.main import app

    client = TestClient(app)
    response = client.get("/jobs")
    assert response.status_code == 200
    assert "Jobs" in response.text
    assert "echo" in response.text


def test_jobs_panel_renders_without_db(monkeypatch, tmp_path):
    monkeypatch.setenv("S9K_JOBS_DB", str(tmp_path / "no_existe" / "jobs.db"))
    from app.main import app

    client = TestClient(app)
    response = client.get("/jobs")
    assert response.status_code == 200
    assert "jobs_db_not_found" in response.text
