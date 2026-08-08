"""Tests del Centro de Estado (Carril B) — panel de observación, solo lectura.

Lo que se demuestra aquí:

* los cuatro estados se distinguen de verdad (OK / WARNING / CRITICAL / UNKNOWN);
* una fuente ausente, un JSON corrupto o un timestamp inválido dan UNKNOWN y
  NUNCA OK;
* UNKNOWN gana a OK al agregar el estado global;
* el panel es de admin (401/403 para el resto) y no expone rutas de escritura;
* control positivo: un panel que devolviera siempre OK haría fallar estos tests
  (ver `test_control_positivo_*`).
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.ops import collector
from app.ops.models import OpsReport, OpsStatus, SectionResult, worst


NOW = datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc)


def iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Modelo: UNKNOWN no es OK
# ---------------------------------------------------------------------------

def test_unknown_pesa_mas_que_ok():
    assert worst([OpsStatus.OK, OpsStatus.UNKNOWN]) == OpsStatus.UNKNOWN
    assert worst([OpsStatus.UNKNOWN, OpsStatus.WARNING]) == OpsStatus.WARNING
    assert worst([OpsStatus.WARNING, OpsStatus.CRITICAL]) == OpsStatus.CRITICAL
    assert worst([]) == OpsStatus.UNKNOWN


def test_overall_no_se_traga_un_unknown():
    rep = OpsReport(sections=[
        SectionResult("a", "A", OpsStatus.OK),
        SectionResult("b", "B", OpsStatus.UNKNOWN),
    ])
    assert rep.overall == OpsStatus.UNKNOWN
    assert rep.to_dict()["read_only"] is True


# ---------------------------------------------------------------------------
# Tiempo: un timestamp inválido es desconocido, no "ahora"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["", "   ", "ayer", "2026-13-45T99:99:99Z",
                                 None, 12345, {"a": 1}])
def test_parse_ts_invalido(bad):
    assert collector.parse_ts(bad) is None
    assert collector.age_hours(bad, NOW) is None


def test_age_hours_valido():
    assert collector.age_hours(iso(5), NOW) == pytest.approx(5.0, abs=0.01)
    # Con sufijo Z y sin zona explícita (se asume UTC).
    assert collector.age_hours("2026-08-08T06:00:00Z", NOW) == pytest.approx(6.0, abs=0.01)
    assert collector.age_hours("2026-08-08T06:00:00", NOW) == pytest.approx(6.0, abs=0.01)


def test_threshold_tolera_basura(monkeypatch):
    monkeypatch.setenv("S9K_OPS_JOBS_FAILED_CRITICAL", "no-soy-un-numero")
    assert collector.threshold("S9K_OPS_JOBS_FAILED_CRITICAL") == 5
    monkeypatch.setenv("S9K_OPS_JOBS_FAILED_CRITICAL", "2")
    assert collector.threshold("S9K_OPS_JOBS_FAILED_CRITICAL") == 2


# ---------------------------------------------------------------------------
# Sección Backups (watchdog externo)
# ---------------------------------------------------------------------------

def _write_state(tmp_path, monkeypatch, payload, raw=None) -> Path:
    p = tmp_path / "backup_watchdog.json"
    p.write_text(raw if raw is not None else json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("S9K_OPS_BACKUP_STATE_PATH", str(p))
    return p


def _healthy_backup_state():
    return {
        "vmid": 105,
        "last_backup": iso(12),
        "age_hours": 12,
        "status": "ok",
        "last_restore_verified": iso(48),
        "restore_status": "ok",
        "generated_at": iso(1),
    }


def test_backups_sano(tmp_path, monkeypatch):
    _write_state(tmp_path, monkeypatch, _healthy_backup_state())
    s = collector.collect_backups(now=NOW)
    assert s.status == OpsStatus.OK
    assert s.metrics["vmid"] == 105
    assert s.metrics["age_hours"] == pytest.approx(12.0, abs=0.01)
    assert s.metrics["rpo_hours"] == s.metrics["age_hours"]


def test_backups_warning_por_edad(tmp_path, monkeypatch):
    st = _healthy_backup_state()
    st["last_backup"] = iso(30)          # > 26 h de aviso, < 48 h crítico
    _write_state(tmp_path, monkeypatch, st)
    assert collector.collect_backups(now=NOW).status == OpsStatus.WARNING


def test_backups_critical_por_edad(tmp_path, monkeypatch):
    st = _healthy_backup_state()
    st["last_backup"] = iso(200)
    _write_state(tmp_path, monkeypatch, st)
    s = collector.collect_backups(now=NOW)
    assert s.status == OpsStatus.CRITICAL


def test_backups_fuente_ausente(tmp_path, monkeypatch):
    monkeypatch.setenv("S9K_OPS_BACKUP_STATE_PATH", str(tmp_path / "no-existe.json"))
    s = collector.collect_backups(now=NOW)
    assert s.status == OpsStatus.UNKNOWN
    assert s.metrics["last_backup"] is None
    assert any("fuente_ausente" in n for n in s.notes)


def test_backups_json_corrupto(tmp_path, monkeypatch):
    _write_state(tmp_path, monkeypatch, None, raw="{ esto no es json ")
    s = collector.collect_backups(now=NOW)
    assert s.status == OpsStatus.UNKNOWN
    assert any("json_corrupto" in n for n in s.notes)


def test_backups_timestamp_invalido_no_es_ok(tmp_path, monkeypatch):
    st = _healthy_backup_state()
    st["last_backup"] = "el martes pasado"
    st.pop("age_hours")
    _write_state(tmp_path, monkeypatch, st)
    s = collector.collect_backups(now=NOW)
    assert s.status == OpsStatus.UNKNOWN
    assert s.metrics["age_hours"] is None


def test_backups_restore_nunca_verificado(tmp_path, monkeypatch):
    st = _healthy_backup_state()
    st["last_restore_verified"] = None
    st["restore_status"] = None
    _write_state(tmp_path, monkeypatch, st)
    s = collector.collect_backups(now=NOW)
    assert s.status == OpsStatus.UNKNOWN
    assert s.metrics["restore_age_hours"] is None


def test_backups_watchdog_rancio(tmp_path, monkeypatch):
    st = _healthy_backup_state()
    st["generated_at"] = iso(72)   # el watchdog lleva 3 días sin refrescar
    _write_state(tmp_path, monkeypatch, st)
    s = collector.collect_backups(now=NOW)
    assert s.status == OpsStatus.WARNING


def test_backups_watchdog_declara_critico(tmp_path, monkeypatch):
    st = _healthy_backup_state()
    st["status"] = "critical"
    _write_state(tmp_path, monkeypatch, st)
    assert collector.collect_backups(now=NOW).status == OpsStatus.CRITICAL


# ---------------------------------------------------------------------------
# Sección Aplicación (informe de health)
# ---------------------------------------------------------------------------

def _health_report(overall="HEALTHY", generated=None, viewer="HEALTHY"):
    return {
        "overall": overall,
        "generated_at": generated if generated is not None else iso(1),
        "components": [
            {"component": "viewer", "status": viewer, "checked_at": iso(1),
             "latency_ms": 3, "message": "", "details": {}},
            {"component": "neo4j", "status": "HEALTHY", "checked_at": iso(1),
             "latency_ms": 8, "message": "", "details": {}},
        ],
    }


def _set_health(tmp_path, monkeypatch, report, raw=None):
    p = tmp_path / "last_report.json"
    p.write_text(raw if raw is not None else json.dumps(report), encoding="utf-8")
    monkeypatch.setenv("S9K_HEALTH_REPORT_PATH", str(p))
    return p


def test_application_sano(tmp_path, monkeypatch):
    _set_health(tmp_path, monkeypatch, _health_report())
    monkeypatch.setenv("S9K_APP_VERSION", "0.3.0")
    monkeypatch.setenv("S9K_GIT_COMMIT", "abcdef1234567890")
    s = collector.collect_application(now=NOW)
    assert s.status == OpsStatus.OK
    assert s.metrics["version"] == "0.3.0"
    assert s.metrics["commit"] == "abcdef123456"   # recortado, sin ruido


def test_application_sin_version_es_unknown(tmp_path, monkeypatch):
    _set_health(tmp_path, monkeypatch, _health_report())
    monkeypatch.delenv("S9K_APP_VERSION", raising=False)
    monkeypatch.delenv("S9K_GIT_COMMIT", raising=False)
    s = collector.collect_application(now=NOW)
    assert s.status == OpsStatus.UNKNOWN
    assert s.metrics["version"] is None


def test_application_informe_ausente(tmp_path, monkeypatch):
    monkeypatch.setenv("S9K_HEALTH_REPORT_PATH", str(tmp_path / "nope.json"))
    monkeypatch.setenv("S9K_APP_VERSION", "0.3.0")
    monkeypatch.setenv("S9K_GIT_COMMIT", "abcdef1")
    s = collector.collect_application(now=NOW)
    assert s.status == OpsStatus.UNKNOWN
    assert s.metrics["health_overall"] is None


def test_application_json_corrupto(tmp_path, monkeypatch):
    _set_health(tmp_path, monkeypatch, None, raw="{{{")
    monkeypatch.setenv("S9K_APP_VERSION", "0.3.0")
    monkeypatch.setenv("S9K_GIT_COMMIT", "abcdef1")
    assert collector.collect_application(now=NOW).status == OpsStatus.UNKNOWN


def test_application_informe_rancio(tmp_path, monkeypatch):
    _set_health(tmp_path, monkeypatch, _health_report(generated=iso(48)))
    monkeypatch.setenv("S9K_APP_VERSION", "0.3.0")
    monkeypatch.setenv("S9K_GIT_COMMIT", "abcdef1")
    s = collector.collect_application(now=NOW)
    assert s.status == OpsStatus.WARNING
    assert s.metrics["health_age_hours"] == pytest.approx(48.0, abs=0.1)


def test_application_timestamp_invalido(tmp_path, monkeypatch):
    _set_health(tmp_path, monkeypatch, _health_report(generated="cuando sea"))
    monkeypatch.setenv("S9K_APP_VERSION", "0.3.0")
    monkeypatch.setenv("S9K_GIT_COMMIT", "abcdef1")
    s = collector.collect_application(now=NOW)
    assert s.status == OpsStatus.UNKNOWN
    assert s.metrics["health_age_hours"] is None


def test_application_unhealthy_es_critical(tmp_path, monkeypatch):
    _set_health(tmp_path, monkeypatch, _health_report(overall="UNHEALTHY",
                                                     viewer="UNHEALTHY"))
    monkeypatch.setenv("S9K_APP_VERSION", "0.3.0")
    monkeypatch.setenv("S9K_GIT_COMMIT", "abcdef1")
    assert collector.collect_application(now=NOW).status == OpsStatus.CRITICAL


# ---------------------------------------------------------------------------
# Sección Datos (Neo4j / proveedor)
# ---------------------------------------------------------------------------

class _FakeProvider:
    name = "neo4j"

    def __init__(self, connected=True, counts=(10, 20), boom=False):
        self._connected, self._counts, self._boom = connected, counts, boom

    def is_connected(self):
        if self._boom:
            raise RuntimeError("bolt://usuario:secreto@10.0.0.5:7687 caído")
        return self._connected

    def counts(self, workspace=None):
        return self._counts


def test_data_sano(tmp_path, monkeypatch):
    _set_health(tmp_path, monkeypatch, _health_report())
    s = collector.collect_data(provider=_FakeProvider(), now=NOW)
    assert s.status == OpsStatus.OK
    assert (s.metrics["nodes"], s.metrics["relationships"]) == (10, 20)
    assert s.metrics["last_check"] is not None


def test_data_neo4j_no_disponible(tmp_path, monkeypatch):
    _set_health(tmp_path, monkeypatch, _health_report())
    s = collector.collect_data(provider=_FakeProvider(connected=False), now=NOW)
    assert s.status == OpsStatus.CRITICAL
    assert s.metrics["nodes"] is None


def test_data_error_de_proveedor_es_unknown_y_saneado(tmp_path, monkeypatch):
    _set_health(tmp_path, monkeypatch, _health_report())
    s = collector.collect_data(provider=_FakeProvider(boom=True), now=NOW)
    assert s.status == OpsStatus.UNKNOWN
    blob = json.dumps(s.to_dict())
    assert "secreto" not in blob and "10.0.0.5" not in blob and "bolt://" not in blob


def test_data_grafo_vacio_es_warning(tmp_path, monkeypatch):
    _set_health(tmp_path, monkeypatch, _health_report())
    s = collector.collect_data(provider=_FakeProvider(counts=(0, 0)), now=NOW)
    assert s.status == OpsStatus.WARNING


def test_data_sin_informe_de_health_no_es_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("S9K_HEALTH_REPORT_PATH", str(tmp_path / "nope.json"))
    s = collector.collect_data(provider=_FakeProvider(), now=NOW)
    assert s.status == OpsStatus.UNKNOWN
    assert s.metrics["last_check"] is None


# ---------------------------------------------------------------------------
# Sección Procesado (cola de jobs)
# ---------------------------------------------------------------------------

def _patch_jobs(monkeypatch, *, ok=True, counts=None, jobs=None, boom=False):
    from app import jobs_client

    def _status():
        if boom:
            raise RuntimeError("/srv/s9k/state/jobs.db ilegible")
        return {"ok": ok, "db_path": "/no/importa"} if ok else {
            "ok": False, "error": "jobs_db_not_found"}

    monkeypatch.setattr(jobs_client, "jobs_db_status", _status)
    monkeypatch.setattr(jobs_client, "get_counts_by_status",
                        lambda *a, **k: dict(counts or {}))
    monkeypatch.setattr(jobs_client, "list_jobs", lambda *a, **k: list(jobs or []))


def test_processing_sano(monkeypatch):
    _patch_jobs(monkeypatch,
                counts={"pending": 1, "running": 1, "completed": 40, "failed": 0},
                jobs=[{"job_id": "j1", "status": "running", "updated_at": iso(2)}])
    s = collector.collect_processing(now=NOW)
    assert s.status == OpsStatus.OK
    assert s.metrics["pending"] == 1 and s.metrics["completed"] == 40
    assert s.metrics["last_job_age_hours"] == pytest.approx(2.0, abs=0.01)


def test_processing_warning_por_fallidos(monkeypatch):
    _patch_jobs(monkeypatch, counts={"completed": 10, "failed": 2},
                jobs=[{"job_id": "j1", "status": "failed", "updated_at": iso(1)}])
    assert collector.collect_processing(now=NOW).status == OpsStatus.WARNING


def test_processing_critical_por_fallidos(monkeypatch):
    _patch_jobs(monkeypatch, counts={"completed": 10, "failed": 9},
                jobs=[{"job_id": "j1", "status": "failed", "updated_at": iso(1)}])
    assert collector.collect_processing(now=NOW).status == OpsStatus.CRITICAL


def test_processing_base_de_jobs_ausente(monkeypatch):
    _patch_jobs(monkeypatch, ok=False)
    s = collector.collect_processing(now=NOW)
    assert s.status == OpsStatus.UNKNOWN
    assert s.metrics["pending"] is None


def test_processing_timestamps_invalidos(monkeypatch):
    _patch_jobs(monkeypatch, counts={"completed": 3},
                jobs=[{"job_id": "j1", "status": "completed", "updated_at": "nunca"}])
    s = collector.collect_processing(now=NOW)
    assert s.status == OpsStatus.UNKNOWN
    assert s.metrics["last_job_age_hours"] is None


def test_processing_cola_stale_con_pendientes(monkeypatch):
    _patch_jobs(monkeypatch, counts={"pending": 3},
                jobs=[{"job_id": "j1", "status": "pending", "updated_at": iso(400)}])
    assert collector.collect_processing(now=NOW).status == OpsStatus.WARNING


def test_processing_error_saneado(monkeypatch):
    _patch_jobs(monkeypatch, boom=True)
    s = collector.collect_processing(now=NOW)
    assert s.status == OpsStatus.UNKNOWN
    assert "/srv/s9k" not in json.dumps(s.to_dict())


# ---------------------------------------------------------------------------
# Sección Revisión
# ---------------------------------------------------------------------------

def _patch_review(monkeypatch, summaries=None, decisions=None,
                  boom_summaries=False, boom_decisions=False):
    from app.services import review_console

    def _sum(*a, **k):
        if boom_summaries:
            raise ValueError("fixture rota en /srv/s9k/fixtures")
        return list(summaries or [])

    def _dec(*a, **k):
        if boom_decisions:
            raise json.JSONDecodeError("bad", "doc", 0)
        return list(decisions or [])

    monkeypatch.setattr(review_console, "list_source_summaries", _sum)
    monkeypatch.setattr(review_console, "read_decisions", _dec)


def test_review_sano(monkeypatch):
    _patch_review(monkeypatch,
                  summaries=[{"source_id": "s1", "pending": 0},
                             {"source_id": "s2", "pending": 2}],
                  decisions=[{"action": "APPROVE"}, {"action": "REJECT"},
                             {"action": "EDIT"}])
    s = collector.collect_review(now=NOW)
    assert s.status == OpsStatus.OK
    assert s.metrics["pending"] == 2
    assert s.metrics["sources_pending"] == 1
    assert s.metrics["approved"] == 2 and s.metrics["rejected"] == 1


def test_review_warning_por_cola_larga(monkeypatch):
    _patch_review(monkeypatch, summaries=[{"source_id": "s1", "pending": 500}])
    assert collector.collect_review(now=NOW).status == OpsStatus.WARNING


def test_review_sin_fuentes_es_unknown(monkeypatch):
    _patch_review(monkeypatch, summaries=[])
    assert collector.collect_review(now=NOW).status == OpsStatus.UNKNOWN


def test_review_decisiones_corruptas(monkeypatch):
    _patch_review(monkeypatch, summaries=[{"source_id": "s1", "pending": 0}],
                  boom_decisions=True)
    s = collector.collect_review(now=NOW)
    assert s.status == OpsStatus.UNKNOWN
    assert s.metrics["approved"] is None


def test_review_fuente_ilegible_saneada(monkeypatch):
    _patch_review(monkeypatch, boom_summaries=True)
    s = collector.collect_review(now=NOW)
    assert s.status == OpsStatus.UNKNOWN
    assert "/srv/s9k" not in json.dumps(s.to_dict())


# ---------------------------------------------------------------------------
# Sección Seguridad
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_db(tmp_path, monkeypatch):
    from app.auth import db as auth_db_mod
    from app.auth.config import get_auth_settings

    db_path = tmp_path / "auth.db"
    monkeypatch.setenv("S9K_AUTH_ENABLED", "true")
    monkeypatch.setenv("S9K_AUTH_DB_PATH", str(db_path))
    get_auth_settings.cache_clear()
    auth_db_mod.ensure_migrated(db_path)
    yield db_path
    get_auth_settings.cache_clear()


def _mkuser(db_path, username="admin1", role="admin", locked_until=None,
            password="TestPass_1234567890!"):
    from app.auth import db as auth_db_mod
    from app.auth.passwords import hash_password
    with auth_db_mod.get_conn(db_path) as conn:
        user = auth_db_mod.create_user(
            conn, username=username, display_name=username,
            password_hash=hash_password(password), role=role)
        if locked_until:
            conn.execute("UPDATE users SET locked_until = ? WHERE id = ?",
                         (locked_until, user.id))
            conn.commit()
    return user


def _audit(db_path, event_type, created_at, result="SUCCESS"):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO audit_events (event_type, result, created_at) VALUES (?,?,?)",
            (event_type, result, created_at))


def test_security_sano(auth_db):
    _mkuser(auth_db)
    _audit(auth_db, "LOGIN_SUCCESS", iso(1))
    s = collector.collect_security(now=NOW)
    assert s.status == OpsStatus.OK
    assert s.metrics["auth_enabled"] is True
    assert s.metrics["active_sessions"] == 0
    assert s.metrics["audit_events_recent"] == 1


def test_security_sesiones_activas(auth_db):
    from app.auth import db as auth_db_mod
    from app.auth.sessions import create_session
    user = _mkuser(auth_db)
    with auth_db_mod.get_conn(auth_db) as conn:
        create_session(conn, user)
    s = collector.collect_security(now=NOW)
    assert s.metrics["active_sessions"] == 1


def test_security_usuario_bloqueado_es_warning(auth_db):
    _mkuser(auth_db, username="bloqueado", role="viewer",
            locked_until=(NOW + timedelta(hours=1)).isoformat())
    s = collector.collect_security(now=NOW)
    assert s.status == OpsStatus.WARNING
    assert s.metrics["locked_users"] == 1


def test_security_fallos_de_login_es_warning(auth_db):
    _mkuser(auth_db)
    for _ in range(12):
        _audit(auth_db, "LOGIN_FAILURE", iso(1), result="FAILURE")
    s = collector.collect_security(now=NOW)
    assert s.status == OpsStatus.WARNING
    assert s.metrics["login_failures_recent"] == 12


def test_security_backend_error_es_critical(auth_db):
    _mkuser(auth_db)
    _audit(auth_db, "AUTH_BACKEND_ERROR", iso(1), result="FAILURE")
    assert collector.collect_security(now=NOW).status == OpsStatus.CRITICAL


def test_security_base_ausente(tmp_path, monkeypatch):
    from app.auth.config import get_auth_settings
    monkeypatch.setenv("S9K_AUTH_ENABLED", "true")
    monkeypatch.setenv("S9K_AUTH_DB_PATH", str(tmp_path / "no-existe.db"))
    get_auth_settings.cache_clear()
    try:
        s = collector.collect_security(now=NOW)
    finally:
        get_auth_settings.cache_clear()
    assert s.status == OpsStatus.UNKNOWN
    assert s.metrics["active_sessions"] is None


def test_security_auth_desactivada_es_unknown(monkeypatch):
    from app.auth.config import get_auth_settings
    monkeypatch.setenv("S9K_AUTH_ENABLED", "false")
    get_auth_settings.cache_clear()
    try:
        s = collector.collect_security(now=NOW)
    finally:
        get_auth_settings.cache_clear()
    assert s.status == OpsStatus.UNKNOWN


def test_security_no_publica_secretos(auth_db):
    from app.auth import db as auth_db_mod
    from app.auth.sessions import create_session
    user = _mkuser(auth_db)
    with auth_db_mod.get_conn(auth_db) as conn:
        token, _ = create_session(conn, user)
    blob = json.dumps(collector.collect_security(now=NOW).to_dict())
    assert token not in blob
    assert str(auth_db) not in blob
    assert "password" not in blob.lower() and "hash" not in blob.lower()


# ---------------------------------------------------------------------------
# Informe completo
# ---------------------------------------------------------------------------

def test_build_report_todo_ausente_es_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("S9K_OPS_BACKUP_STATE_PATH", str(tmp_path / "nope.json"))
    monkeypatch.setenv("S9K_HEALTH_REPORT_PATH", str(tmp_path / "nope2.json"))
    monkeypatch.setenv("S9K_AUTH_ENABLED", "false")
    _patch_jobs(monkeypatch, ok=False)
    _patch_review(monkeypatch, summaries=[])
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    try:
        rep = collector.build_report(now=NOW, provider=_FakeProvider(connected=False))
    finally:
        get_auth_settings.cache_clear()
    keys = [s.key for s in rep.sections]
    assert keys == ["application", "data", "processing", "review", "backups", "security"]
    assert rep.overall == OpsStatus.CRITICAL   # datos inaccesibles manda
    unknowns = [s.key for s in rep.sections if s.status == OpsStatus.UNKNOWN]
    assert set(unknowns) == {"application", "processing", "review", "backups", "security"}
    assert not any(s.status == OpsStatus.OK for s in rep.sections)


def test_build_report_aisla_un_recolector_roto(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("/srv/secreto/ruta")

    monkeypatch.setattr(collector, "COLLECTORS",
                        (("backups", _boom),))
    rep = collector.build_report(now=NOW)
    assert rep.sections[0].status == OpsStatus.UNKNOWN
    assert "/srv/secreto" not in json.dumps(rep.to_dict())


# ---------------------------------------------------------------------------
# Rutas HTTP: solo admin, solo lectura
# ---------------------------------------------------------------------------

def _ops_app():
    """App mínima con el middleware de auth y SOLO el router de ops.

    Se monta aquí (y no en app.main) porque `viewer/app/main.py` pertenece a
    otro equipo del programa y este carril no puede editarlo.
    """
    from fastapi import FastAPI
    from app.auth.middleware import AuthMiddleware
    from app.routers import ops as ops_router

    application = FastAPI()
    application.add_middleware(AuthMiddleware)
    application.include_router(ops_router.router)
    return application


def _client(cookie=None):
    from fastapi.testclient import TestClient
    c = TestClient(_ops_app(), raise_server_exceptions=False, follow_redirects=False)
    if cookie:
        c.cookies.set("s9k_session", cookie)
    return c


def _session_cookie(db_path, user):
    from app.auth import db as auth_db_mod
    from app.auth.sessions import create_session
    with auth_db_mod.get_conn(db_path) as conn:
        token, _ = create_session(conn, user)
    return token


def test_api_ops_anonimo_401(auth_db):
    resp = _client().get("/api/admin/ops")
    assert resp.status_code == 401


def test_api_ops_usuario_no_admin_403(auth_db):
    user = _mkuser(auth_db, username="lector", role="viewer")
    resp = _client(_session_cookie(auth_db, user)).get("/api/admin/ops")
    assert resp.status_code == 403


def test_api_ops_reviewer_tambien_403(auth_db):
    user = _mkuser(auth_db, username="revisor", role="reviewer")
    resp = _client(_session_cookie(auth_db, user)).get("/api/admin/ops")
    assert resp.status_code == 403


def test_api_ops_admin_200(auth_db, tmp_path, monkeypatch):
    monkeypatch.setenv("S9K_OPS_BACKUP_STATE_PATH", str(tmp_path / "nope.json"))
    monkeypatch.setenv("S9K_HEALTH_REPORT_PATH", str(tmp_path / "nope2.json"))
    user = _mkuser(auth_db)
    resp = _client(_session_cookie(auth_db, user)).get("/api/admin/ops")
    assert resp.status_code == 200
    body = resp.json()
    assert body["read_only"] is True
    assert body["overall"] in {"OK", "WARNING", "CRITICAL", "UNKNOWN"}
    assert [s["key"] for s in body["sections"]] == [
        "application", "data", "processing", "review", "backups", "security"]
    # Fuentes ausentes: el panel lo dice, no lo disimula.
    assert body["sections"][4]["status"] == "UNKNOWN"


def test_html_ops_no_admin_403(auth_db):
    user = _mkuser(auth_db, username="lector2", role="viewer")
    resp = _client(_session_cookie(auth_db, user)).get(
        "/admin/ops", headers={"accept": "text/html"})
    assert resp.status_code == 403


def test_html_ops_anonimo_redirige_a_login(auth_db):
    resp = _client().get("/admin/ops", headers={"accept": "text/html"})
    assert resp.status_code == 302
    assert "/login" in resp.headers.get("location", "")


def test_html_ops_admin_pinta_unknown(auth_db, tmp_path, monkeypatch):
    monkeypatch.setenv("S9K_OPS_BACKUP_STATE_PATH", str(tmp_path / "nope.json"))
    monkeypatch.setenv("S9K_HEALTH_REPORT_PATH", str(tmp_path / "nope2.json"))
    user = _mkuser(auth_db)
    resp = _client(_session_cookie(auth_db, user)).get(
        "/admin/ops", headers={"accept": "text/html"})
    assert resp.status_code == 200
    assert "Centro de Estado" in resp.text
    assert "UNKNOWN" in resp.text


def test_router_no_expone_escritura():
    from app.routers import ops as ops_router
    metodos = set()
    for route in ops_router.router.routes:
        metodos |= set(getattr(route, "methods", set()))
    assert metodos <= {"GET", "HEAD"}, metodos


# ---------------------------------------------------------------------------
# CONTROL POSITIVO
# ---------------------------------------------------------------------------
# Un panel que devolviera siempre OK debe hacer fallar la suite. Aquí se fuerza
# esa mutación en caliente y se comprueba que los tests de "fuente ausente"
# efectivamente REVIENTAN. Si algún día dejaran de reventar, el panel habría
# vuelto a confundir "no lo sé" con "está bien".

def test_control_positivo_panel_siempre_ok_hace_fallar_los_tests(tmp_path, monkeypatch):
    """Mutación: los recolectores devuelven OK siempre. Los tests reales revientan."""

    def _siempre_ok(*a, **k):
        return SectionResult("backups", "Backups", OpsStatus.OK, "todo bien")

    monkeypatch.setattr(collector, "collect_backups", _siempre_ok)

    # Se ejecutan los tests REALES de fuente ausente / json corrupto contra el
    # panel mutado: deben fallar. Si pasaran, la suite no distinguiría estados.
    with pytest.raises(AssertionError):
        test_backups_fuente_ausente(tmp_path, monkeypatch)
    with pytest.raises(AssertionError):
        test_backups_json_corrupto(tmp_path, monkeypatch)
    with pytest.raises(AssertionError):
        test_backups_critical_por_edad(tmp_path, monkeypatch)

    # Revertido por monkeypatch al salir del test: el comportamiento vuelve.


def test_control_positivo_unknown_degradado_a_ok_hace_fallar_los_tests(monkeypatch):
    """Mutación: UNKNOWN con severidad 0 (= "está bien"). Debe romper la suite."""
    from app.ops import models

    monkeypatch.setitem(models.SEVERITY, OpsStatus.UNKNOWN, 0)

    with pytest.raises(AssertionError):
        test_unknown_pesa_mas_que_ok()
    with pytest.raises(AssertionError):
        test_overall_no_se_traga_un_unknown()


def test_control_positivo_revertido():
    """Tras revertir las mutaciones, el panel vuelve a distinguir los estados."""
    assert worst([OpsStatus.OK, OpsStatus.UNKNOWN]) == OpsStatus.UNKNOWN
    from app.ops import models
    assert models.SEVERITY[OpsStatus.UNKNOWN] == 1
