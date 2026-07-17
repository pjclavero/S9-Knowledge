"""Tests del subsistema de healthchecks (solo lectura)."""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest

from app.health import checks, runner, storage
from app.health.models import (EXIT_CONFIG_ERROR, ComponentResult, HealthReport,
                               HealthStatus, worst_status)


# ---------------------------------------------------------------------------
# Modelos y agregación
# ---------------------------------------------------------------------------

def test_worst_status_orden():
    assert worst_status([HealthStatus.HEALTHY, HealthStatus.DEGRADED]) == HealthStatus.DEGRADED
    assert worst_status([HealthStatus.DEGRADED, HealthStatus.UNHEALTHY]) == HealthStatus.UNHEALTHY
    assert worst_status([]) == HealthStatus.UNKNOWN


def test_report_exit_codes():
    assert HealthReport([ComponentResult("x", HealthStatus.HEALTHY)]).exit_code() == 0
    assert HealthReport([ComponentResult("x", HealthStatus.DEGRADED)]).exit_code() == 1
    assert HealthReport([ComponentResult("x", HealthStatus.UNHEALTHY)]).exit_code() == 2


def test_report_json_shape():
    r = HealthReport([ComponentResult("viewer", HealthStatus.HEALTHY, message="ok")])
    d = r.to_dict()
    assert d["overall"] == "HEALTHY"
    assert d["components"][0]["component"] == "viewer"
    assert set(d["components"][0]) == {"component", "status", "checked_at", "latency_ms", "message", "details"}


# ---------------------------------------------------------------------------
# Filesystem (disco)
# ---------------------------------------------------------------------------

def _fake_usage(total, used):
    from collections import namedtuple
    U = namedtuple("U", "total used free")
    return U(total, used, total - used)


def test_disk_healthy(monkeypatch):
    monkeypatch.setattr(checks.shutil, "disk_usage", lambda p: _fake_usage(100, 50))
    assert checks.check_filesystem("/").status == HealthStatus.HEALTHY


def test_disk_warning(monkeypatch):
    monkeypatch.setattr(checks.shutil, "disk_usage", lambda p: _fake_usage(100, 85))
    assert checks.check_filesystem("/").status == HealthStatus.DEGRADED


def test_disk_critical(monkeypatch):
    monkeypatch.setattr(checks.shutil, "disk_usage", lambda p: _fake_usage(100, 95))
    assert checks.check_filesystem("/").status == HealthStatus.UNHEALTHY


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------

def test_backup_ausente(tmp_path):
    assert checks.check_backups(str(tmp_path)).status == HealthStatus.UNHEALTHY


def test_backup_tarball_suelto_ya_no_es_healthy(tmp_path):
    """CAMBIO DE CONTRATO deliberado (hotfix postdespliegue RC2).

    Antes, un fichero suelto bastaba para declarar HEALTHY sin mirar dentro. Un
    tar.gz no se puede validar (ni integrity_check, ni sumas, ni contenido), asi
    que ya no se acepta: el criterio es 'backup validable', no 'hay algo ahi'.
    La cobertura completa vive en test_health_backups.py.
    """
    (tmp_path / "backup.tar.gz").write_text("x")
    assert checks.check_backups(str(tmp_path)).status == HealthStatus.UNHEALTHY


def test_backup_no_configurado():
    assert checks.check_backups(None).status == HealthStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Nextcloud / rclone
# ---------------------------------------------------------------------------

def test_mount_inexistente():
    assert checks.check_nextcloud_rclone("/no/existe/xyz").status == HealthStatus.UNHEALTHY


def test_mount_falso_no_es_montaje(tmp_path):
    (tmp_path / "f").write_text("x")
    r = checks.check_nextcloud_rclone(str(tmp_path))
    assert r.status == HealthStatus.DEGRADED  # existe y legible pero no es mount


# ---------------------------------------------------------------------------
# Job store
# ---------------------------------------------------------------------------

def _make_jobs_db(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, status TEXT, attempts INTEGER)")
    con.executemany("INSERT INTO jobs (status, attempts) VALUES (?,?)", rows)
    con.commit(); con.close()


def test_job_store_ok(tmp_path):
    db = tmp_path / "jobs.db"
    _make_jobs_db(str(db), [("done", 1), ("running", 0)])
    r = checks.check_job_store(str(db))
    assert r.status == HealthStatus.HEALTHY
    assert r.details["total"] == 2


def test_job_store_reintentos_excesivos(tmp_path):
    db = tmp_path / "jobs.db"
    _make_jobs_db(str(db), [("failed", 9)])
    r = checks.check_job_store(str(db), max_attempts=5)
    assert r.status == HealthStatus.DEGRADED


def test_job_store_corrupto(tmp_path):
    db = tmp_path / "jobs.db"
    db.write_text("no soy sqlite")
    assert checks.check_job_store(str(db)).status == HealthStatus.UNHEALTHY


# ---------------------------------------------------------------------------
# Auth DB
# ---------------------------------------------------------------------------

def _make_auth_db(tmp_path, with_admin=True):
    os.environ["S9K_AUTH_DB_PATH"] = str(tmp_path / "auth.db")
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    p = tmp_path / "auth.db"
    auth_db.ensure_migrated(p)
    if with_admin:
        with auth_db.get_conn(p) as conn:
            auth_db.create_user(conn, username="a", display_name="a",
                                password_hash=hash_password("x" * 14), role="admin")
    return p


def test_auth_db_ok(tmp_path):
    p = _make_auth_db(tmp_path, with_admin=True)
    assert checks.check_auth_db(str(p), enabled=True).status == HealthStatus.HEALTHY


def test_auth_db_sin_admin(tmp_path):
    p = _make_auth_db(tmp_path, with_admin=False)
    assert checks.check_auth_db(str(p), enabled=True).status == HealthStatus.UNHEALTHY


def test_auth_db_desactivada():
    assert checks.check_auth_db(None, enabled=False).status == HealthStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Viewer / Neo4j / Ollama / systemd / external
# ---------------------------------------------------------------------------

def test_viewer_conexion_rechazada(monkeypatch):
    import httpx
    def boom(*a, **k):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(httpx, "get", boom)
    assert checks.check_viewer().status == HealthStatus.UNHEALTHY


def test_viewer_responde(monkeypatch):
    import httpx
    class R: status_code = 200
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R())
    assert checks.check_viewer().status == HealthStatus.HEALTHY


def test_neo4j_sin_password_unknown():
    assert checks.check_neo4j("bolt://x", "neo4j", None).status == HealthStatus.UNKNOWN


def test_neo4j_solo_lectura(monkeypatch):
    """El check de Neo4j solo ejecuta lecturas (RETURN 1 / count), nunca escrituras."""
    queries = []
    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def run(self, q, *a, **k):
            queries.append(q)
            class Rec:
                def single(self_inner):
                    return {"ok": 1, "c": 199}
            return Rec()
    class FakeDriver:
        def session(self): return FakeSession()
        def close(self): pass
    import neo4j
    monkeypatch.setattr(neo4j.GraphDatabase, "driver", lambda *a, **k: FakeDriver())
    checks.check_neo4j("bolt://x", "neo4j", "pw")
    joined = " ".join(queries).upper()
    assert "CREATE" not in joined and "MERGE" not in joined and "SET " not in joined and "DELETE" not in joined


def test_ollama_no_configurado():
    assert checks.check_ollama(None).status == HealthStatus.UNKNOWN


def test_systemd_sin_systemctl(monkeypatch):
    monkeypatch.setattr(checks.shutil, "which", lambda x: None)
    assert checks.check_systemd().status == HealthStatus.UNKNOWN


def test_external_ai_y_burst_desactivados():
    assert checks.check_external_ai(enabled=False).status == HealthStatus.HEALTHY
    assert checks.check_burst(enabled=False).status == HealthStatus.HEALTHY


# ---------------------------------------------------------------------------
# Sanitización: ningún detalle contiene secretos
# ---------------------------------------------------------------------------

def test_no_secretos_en_resultados(monkeypatch):
    import neo4j
    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def run(self, q, *a, **k):
            class Rec:
                def single(self_inner): return {"ok": 1, "c": 5}
            return Rec()
    class FakeDriver:
        def session(self): return FakeSession()
        def close(self): pass
    monkeypatch.setattr(neo4j.GraphDatabase, "driver", lambda *a, **k: FakeDriver())
    r = checks.check_neo4j("bolt://x", "neo4j", "SUPERSECRET")
    assert "SUPERSECRET" not in str(r.to_dict())


# ---------------------------------------------------------------------------
# Runner y storage
# ---------------------------------------------------------------------------

def test_runner_report_y_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(checks.shutil, "disk_usage", lambda p: _fake_usage(100, 10))
    cfg = {"filesystem": {"path": "/"}, "external_ai": {"enabled": False}, "burst": {"enabled": False}}
    report = runner.run_report(config=cfg, only=["filesystem", "external_ai", "burst"])
    assert report.overall == HealthStatus.HEALTHY
    p = storage.save_report(report, tmp_path / "r.json")
    loaded = storage.load_last(p)
    assert loaded["overall"] == "HEALTHY"


def test_run_component_desconocido_no_lanza():
    with pytest.raises(KeyError):
        runner.run_component("inexistente", {})


# ---------------------------------------------------------------------------
# CLI: códigos de salida
# ---------------------------------------------------------------------------

def test_cli_exit_healthy(monkeypatch, tmp_path):
    from app.cli import health as cli
    monkeypatch.setenv("S9K_HEALTH_REPORT_PATH", str(tmp_path / "r.json"))
    monkeypatch.setattr(cli.runner, "run_report",
                        lambda **k: HealthReport([ComponentResult("x", HealthStatus.HEALTHY)]))
    assert cli.main(["check"]) == 0


def test_cli_exit_unhealthy(monkeypatch, tmp_path):
    from app.cli import health as cli
    monkeypatch.setenv("S9K_HEALTH_REPORT_PATH", str(tmp_path / "r.json"))
    monkeypatch.setattr(cli.runner, "run_report",
                        lambda **k: HealthReport([ComponentResult("x", HealthStatus.UNHEALTHY)]))
    assert cli.main(["check"]) == 2


def test_cli_componente_desconocido():
    from app.cli import health as cli
    assert cli.main(["check", "--component", "inexistente"]) == EXIT_CONFIG_ERROR


# ---------------------------------------------------------------------------
# API admin: 401 anónimo · 403 reviewer · 200 admin
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_env(tmp_path):
    db = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db)
    os.environ["S9K_CSRF_SECRET"] = "clave-csrf-larga-y-aleatoria-para-tests-1234567890"
    os.environ["S9K_SESSION_SECURE"] = "false"
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    from app.auth import db as auth_db
    auth_db.ensure_migrated(db)
    yield db
    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()


def _user_cookie(db, username, role):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session
    with auth_db.get_conn(db) as conn:
        u = auth_db.create_user(conn, username=username, display_name=username,
                                password_hash=hash_password("x" * 14), role=role)
        token, _ = create_session(conn, u)
    return token


def _client():
    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


def test_api_health_anonimo_401(auth_env):
    c = _client()
    assert c.get("/api/admin/health", headers={"accept": "application/json"}).status_code == 401


def test_api_health_reviewer_403(auth_env):
    from app.auth.config import get_auth_settings
    tok = _user_cookie(auth_env, "rev", "reviewer")
    c = _client()
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, tok)
    assert c.get("/api/admin/health", headers={"accept": "application/json"}).status_code == 403


def test_api_health_admin_200(auth_env, monkeypatch):
    from app.auth.config import get_auth_settings
    # evitar checks con red: forzar report ligero
    monkeypatch.setattr("app.routers.health_admin.runner.run_report",
                        lambda **k: HealthReport([ComponentResult("x", HealthStatus.HEALTHY)]))
    tok = _user_cookie(auth_env, "adm", "admin")
    c = _client()
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, tok)
    r = c.get("/api/admin/health", headers={"accept": "application/json"})
    assert r.status_code == 200 and r.json()["overall"] == "HEALTHY"
