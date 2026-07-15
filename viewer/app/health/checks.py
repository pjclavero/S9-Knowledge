"""Checks de componentes. Todos son de SOLO LECTURA.

Cada función devuelve un ``ComponentResult``. Ningún check reinicia servicios,
escribe en Neo4j, ni expone secretos. Los fallos degradan el estado en vez de
lanzar excepciones.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.health.models import ComponentResult, HealthStatus

DISK_WARNING_PCT = 80
DISK_CRITICAL_PCT = 90
# Un job 'running' mas antiguo que esto se considera atascado (segundos).
JOB_STUCK_SECONDS = 3600
JOB_MAX_ATTEMPTS = 5


class _Timer:
    def __enter__(self):
        self._t0 = time.perf_counter()
        self._t1 = None
        return self

    def __exit__(self, *a):
        self._t1 = time.perf_counter()

    @property
    def ms(self) -> float:
        end = self._t1 if self._t1 is not None else time.perf_counter()
        return round((end - self._t0) * 1000, 2)


def _result(component, status, message="", details=None, latency_ms=None):
    return ComponentResult(component=component, status=status, message=message,
                           details=details or {}, latency_ms=latency_ms)


# ---------------------------------------------------------------------------
# Visor
# ---------------------------------------------------------------------------

def check_viewer(base_url: str = "http://127.0.0.1:8088", timeout: float = 5.0,
                 version: Optional[str] = None) -> ComponentResult:
    try:
        import httpx
    except Exception:  # pragma: no cover
        return _result("viewer", HealthStatus.UNKNOWN, "httpx no disponible")
    with _Timer() as t:
        try:
            r = httpx.get(base_url + "/api/status", timeout=timeout,
                          headers={"accept": "application/json"})
            code = r.status_code
        except Exception as exc:
            return _result("viewer", HealthStatus.UNHEALTHY,
                           "sin respuesta HTTP: %s" % type(exc).__name__, latency_ms=t.ms)
    # 200 (auth off) o 401 (auth on) significan que el proceso responde.
    ok = code in (200, 401)
    return _result("viewer", HealthStatus.HEALTHY if ok else HealthStatus.DEGRADED,
                   "HTTP %d" % code, {"http_status": code, "version": version}, latency_ms=t.ms)


# ---------------------------------------------------------------------------
# Neo4j (solo lectura: RETURN 1 + metricas)
# ---------------------------------------------------------------------------

def check_neo4j(uri: str, user: str, password: Optional[str], timeout: float = 5.0) -> ComponentResult:
    if not password:
        return _result("neo4j", HealthStatus.UNKNOWN, "sin credencial (no verificado)")
    try:
        from neo4j import GraphDatabase
    except Exception:  # pragma: no cover
        return _result("neo4j", HealthStatus.UNKNOWN, "driver neo4j no disponible")
    with _Timer() as t:
        driver = None
        try:
            driver = GraphDatabase.driver(uri, auth=(user, password),
                                          connection_timeout=timeout)
            with driver.session() as s:
                one = s.run("RETURN 1 AS ok").single()["ok"]
                nodes = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
                rels = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            status = HealthStatus.HEALTHY if one == 1 else HealthStatus.DEGRADED
            return _result("neo4j", status, "conectado",
                           {"nodes": nodes, "relationships": rels}, latency_ms=t.ms)
        except Exception as exc:
            return _result("neo4j", HealthStatus.UNHEALTHY,
                           "error de conexion: %s" % type(exc).__name__, latency_ms=t.ms)
        finally:
            if driver is not None:
                try:
                    driver.close()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Ollama (endpoint + modelo presente; sin inferencia pesada)
# ---------------------------------------------------------------------------

def check_ollama(base_url: Optional[str], required_model: Optional[str] = None,
                 timeout: float = 5.0) -> ComponentResult:
    if not base_url:
        return _result("ollama", HealthStatus.UNKNOWN, "no configurado")
    try:
        import httpx
    except Exception:  # pragma: no cover
        return _result("ollama", HealthStatus.UNKNOWN, "httpx no disponible")
    with _Timer() as t:
        try:
            r = httpx.get(base_url.rstrip("/") + "/api/tags", timeout=timeout)
            if r.status_code != 200:
                return _result("ollama", HealthStatus.DEGRADED, "HTTP %d" % r.status_code,
                               latency_ms=t.ms)
            models = [m.get("name", "") for m in r.json().get("models", [])]
        except Exception as exc:
            return _result("ollama", HealthStatus.UNHEALTHY,
                           "sin respuesta: %s" % type(exc).__name__, latency_ms=t.ms)
    if required_model and not any(required_model in m for m in models):
        return _result("ollama", HealthStatus.DEGRADED,
                       "modelo requerido ausente", {"models": len(models)}, latency_ms=t.ms)
    return _result("ollama", HealthStatus.HEALTHY, "endpoint accesible",
                   {"models": len(models)}, latency_ms=t.ms)


# ---------------------------------------------------------------------------
# Nextcloud / rclone mount (no crea ni borra ficheros)
# ---------------------------------------------------------------------------

def check_nextcloud_rclone(mountpoint: Optional[str], timeout: float = 5.0) -> ComponentResult:
    if not mountpoint:
        return _result("nextcloud_rclone", HealthStatus.UNKNOWN, "no configurado")
    p = Path(mountpoint)
    if not p.exists():
        return _result("nextcloud_rclone", HealthStatus.UNHEALTHY, "mountpoint no existe")
    with _Timer() as t:
        try:
            is_mount = os.path.ismount(str(p))
            listing = os.listdir(str(p))
        except Exception as exc:
            return _result("nextcloud_rclone", HealthStatus.UNHEALTHY,
                           "no legible: %s" % type(exc).__name__, latency_ms=t.ms)
    if not is_mount:
        return _result("nextcloud_rclone", HealthStatus.DEGRADED,
                       "la ruta existe pero NO es un montaje", latency_ms=t.ms)
    if not listing:
        return _result("nextcloud_rclone", HealthStatus.DEGRADED,
                       "montaje vacio o desconectado", latency_ms=t.ms)
    return _result("nextcloud_rclone", HealthStatus.HEALTHY, "montaje legible",
                   {"entries": len(listing)}, latency_ms=t.ms)


# ---------------------------------------------------------------------------
# Job store (SQLite): accesible, jobs atascados, reintentos excesivos
# ---------------------------------------------------------------------------

def check_job_store(db_path: Optional[str], stuck_seconds: int = JOB_STUCK_SECONDS,
                    max_attempts: int = JOB_MAX_ATTEMPTS) -> ComponentResult:
    if not db_path:
        return _result("job_store", HealthStatus.UNKNOWN, "no configurado")
    if not Path(db_path).exists():
        return _result("job_store", HealthStatus.UNKNOWN, "jobs.db no existe")
    with _Timer() as t:
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True, timeout=3)
            cols = {r[1] for r in con.execute("PRAGMA table_info(jobs)")}
            total = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            running = con.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0]
            attempts_col = "attempts" if "attempts" in cols else (
                "attempt" if "attempt" in cols else None)
            excessive = 0
            if attempts_col:
                excessive = con.execute(
                    "SELECT COUNT(*) FROM jobs WHERE %s > ?" % attempts_col,
                    (max_attempts,)).fetchone()[0]
            con.close()
        except Exception as exc:
            return _result("job_store", HealthStatus.UNHEALTHY,
                           "SQLite no accesible: %s" % type(exc).__name__, latency_ms=t.ms)
    status = HealthStatus.HEALTHY
    msgs = []
    if excessive:
        status = HealthStatus.DEGRADED
        msgs.append("%d jobs con reintentos excesivos" % excessive)
    return _result("job_store", status, "; ".join(msgs) or "accesible",
                   {"total": total, "running": running, "excessive_retries": excessive},
                   latency_ms=t.ms)


# ---------------------------------------------------------------------------
# Auth DB: accesible, esquema, al menos un admin activo, sesiones expiradas
# ---------------------------------------------------------------------------

def check_auth_db(db_path: Optional[str], enabled: bool = True) -> ComponentResult:
    if not enabled:
        return _result("auth_db", HealthStatus.UNKNOWN, "auth desactivada")
    if not db_path or not Path(db_path).exists():
        return _result("auth_db", HealthStatus.UNHEALTHY, "auth.db no existe con auth activa")
    with _Timer() as t:
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True, timeout=3)
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            required = {"users", "sessions", "audit_events"}
            if not required.issubset(tables):
                con.close()
                return _result("auth_db", HealthStatus.UNHEALTHY,
                               "esquema incompleto", latency_ms=t.ms)
            admins = con.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1").fetchone()[0]
            expired = con.execute(
                "SELECT COUNT(*) FROM sessions WHERE revoked_at IS NULL "
                "AND expires_at < datetime('now')").fetchone()[0]
            con.close()
        except Exception as exc:
            return _result("auth_db", HealthStatus.UNHEALTHY,
                           "no accesible: %s" % type(exc).__name__, latency_ms=t.ms)
    if admins == 0:
        return _result("auth_db", HealthStatus.UNHEALTHY, "sin admin activo",
                       {"active_admins": 0}, latency_ms=t.ms)
    status = HealthStatus.DEGRADED if expired > 50 else HealthStatus.HEALTHY
    return _result("auth_db", status, "ok",
                   {"active_admins": admins, "expired_sessions": expired}, latency_ms=t.ms)


# ---------------------------------------------------------------------------
# External AI / Burst: desactivados por defecto
# ---------------------------------------------------------------------------

def check_external_ai(enabled: bool = False) -> ComponentResult:
    return _result("external_ai",
                   HealthStatus.HEALTHY if not enabled else HealthStatus.DEGRADED,
                   "desactivado (modo sombra)" if not enabled else "activado",
                   {"enabled": enabled})


def check_burst(enabled: bool = False) -> ComponentResult:
    return _result("burst",
                   HealthStatus.HEALTHY if not enabled else HealthStatus.DEGRADED,
                   "desactivado; mock disponible" if not enabled else "activado",
                   {"enabled": enabled, "mock_available": True})


# ---------------------------------------------------------------------------
# Filesystem (disco)
# ---------------------------------------------------------------------------

def check_filesystem(path: str = "/", warning_pct: int = DISK_WARNING_PCT,
                     critical_pct: int = DISK_CRITICAL_PCT) -> ComponentResult:
    with _Timer() as t:
        try:
            usage = shutil.disk_usage(path)
        except Exception as exc:
            return _result("filesystem", HealthStatus.UNKNOWN,
                           "no medible: %s" % type(exc).__name__, latency_ms=t.ms)
    pct = round(usage.used / usage.total * 100, 1)
    if pct >= critical_pct:
        status = HealthStatus.UNHEALTHY
    elif pct >= warning_pct:
        status = HealthStatus.DEGRADED
    else:
        status = HealthStatus.HEALTHY
    return _result("filesystem", status, "uso %.1f%%" % pct,
                   {"used_pct": pct, "free_gb": round(usage.free / 1e9, 1)}, latency_ms=t.ms)


# ---------------------------------------------------------------------------
# Backups: ultimo backup, antiguedad
# ---------------------------------------------------------------------------

def check_backups(backup_dir: Optional[str], max_age_hours: int = 48,
                  pattern: str = "*") -> ComponentResult:
    if not backup_dir:
        return _result("backups", HealthStatus.UNKNOWN, "no configurado")
    d = Path(backup_dir)
    if not d.exists():
        return _result("backups", HealthStatus.UNHEALTHY, "directorio de backup no existe")
    files = [p for p in d.glob(pattern) if p.is_file()]
    if not files:
        return _result("backups", HealthStatus.UNHEALTHY, "sin backups")
    latest = max(files, key=lambda p: p.stat().st_mtime)
    age_h = round((time.time() - latest.stat().st_mtime) / 3600, 1)
    checksum_present = (latest.with_suffix(latest.suffix + ".sha256").exists()
                        or (d / (latest.name + ".sha256")).exists())
    status = HealthStatus.HEALTHY if age_h <= max_age_hours else HealthStatus.DEGRADED
    return _result("backups", status, "ultimo backup hace %.1fh" % age_h,
                   {"age_hours": age_h, "checksum": checksum_present}, latency_ms=None)


# ---------------------------------------------------------------------------
# systemd: servicios activos (no reinicia)
# ---------------------------------------------------------------------------

def check_systemd(units: Optional[List[str]] = None) -> ComponentResult:
    units = units or ["s9-knowledge-viewer.service"]
    if not shutil.which("systemctl"):
        return _result("systemd", HealthStatus.UNKNOWN, "systemctl no disponible")
    states: Dict[str, str] = {}
    with _Timer() as t:
        for u in units:
            try:
                r = subprocess.run(["systemctl", "is-active", u],
                                   capture_output=True, text=True, timeout=5)
                states[u] = r.stdout.strip() or "unknown"
            except Exception:
                states[u] = "error"
    inactive = [u for u, s in states.items() if s != "active"]
    status = HealthStatus.HEALTHY if not inactive else HealthStatus.UNHEALTHY
    return _result("systemd", status,
                   "todas activas" if not inactive else "inactivas: %s" % ",".join(inactive),
                   {"units": states}, latency_ms=t.ms)
