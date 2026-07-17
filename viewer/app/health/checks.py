"""Checks de componentes. Todos son de SOLO LECTURA.

Cada función devuelve un ``ComponentResult``. Ningún check reinicia servicios,
escribe en Neo4j, ni expone secretos. Los fallos degradan el estado en vez de
lanzar excepciones.
"""
from __future__ import annotations

import hashlib
import json
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

# Backups. El aviso a 26h cubre un backup diario con margen para que un retraso
# normal no pinte DEGRADED; a 48h ya es un fallo operativo real.
BACKUP_WARN_AGE_HOURS = 26
BACKUP_MAX_AGE_HOURS = 48
# Los conjuntos cuelgan directamente de la raiz: 2 niveles bastan y acotan el
# escaneo para que el check no recorra un arbol grande.
BACKUP_MAX_SCAN_DEPTH = 2


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

def _is_backup_set(d: Path) -> bool:
    """Un conjunto de backup es un directorio con al menos una base .db dentro."""
    try:
        return any(p.is_file() and p.suffix == ".db" for p in d.iterdir())
    except OSError:
        return False


def _find_backup_sets(root: Path, max_depth: int) -> List[Path]:
    """Busca conjuntos de backup hasta `max_depth` niveles.

    El layout real los guarda como DIRECTORIOS (pre-deploy-<ts>/auth.db, ...),
    no como ficheros sueltos en la raiz: mirar solo el primer nivel con
    `is_file()` daba siempre 'sin backups' y un UNHEALTHY falso.
    """
    found: List[Path] = []
    if _is_backup_set(root):
        found.append(root)

    def walk(d: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(d.iterdir())
        except OSError:
            return
        for p in entries:
            if p.is_symlink() or not p.is_dir():
                continue
            if _is_backup_set(p):
                found.append(p)
            else:
                walk(p, depth + 1)

    walk(root, 1)
    return found


def _set_mtime(d: Path) -> float:
    """Edad del conjunto medida por sus FICHEROS, no por el directorio.

    El mtime del directorio cambia en cuanto alguien crea un fichero dentro
    (p.ej. un -shm de SQLite), y eso rejuvenece un backup rancio: justo el error
    que debe detectar. Los ficheros conservan la fecha real de la copia.
    """
    try:
        mtimes = [p.stat().st_mtime for p in d.iterdir() if p.is_file()]
    except OSError:
        mtimes = []
    if not mtimes:
        try:
            return d.stat().st_mtime
        except OSError:
            return 0.0
    return max(mtimes)


def _pending_wal(d: Path) -> List[str]:
    """Un -wal con datos significa que la copia no se cerro limpiamente."""
    problems = []
    for p in d.iterdir():
        if p.is_file() and p.name.endswith("-wal"):
            try:
                if p.stat().st_size > 0:
                    problems.append(f"{p.name} con datos sin consolidar")
            except OSError:
                continue
    return problems


def _sqlite_integrity_ro(path: Path) -> Optional[str]:
    """integrity_check sin escribir NADA. None = ok; str = motivo del fallo.

    `mode=ro` NO basta: ante una base en modo WAL, SQLite crea los ficheros
    -shm/-wal aunque solo vaya a leer, y eso ensucia el conjunto y altera el
    mtime del directorio. `immutable=1` promete que el fichero no cambia, con lo
    que SQLite se salta el WAL y no crea nada.

    A cambio, immutable ignora un -wal pendiente. Es correcto aqui porque un
    backup es estatico y se genera con la API .backup (que no deja WAL); si
    apareciera un -wal con datos, se reporta aparte en _pending_wal().
    """
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True, timeout=5)
    except sqlite3.Error as e:
        return f"no se pudo abrir: {e}"
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return None if row and row[0] == "ok" else f"integrity_check: {row[0] if row else 'sin salida'}"
    except sqlite3.Error as e:
        return f"integrity_check fallo: {e}"
    finally:
        conn.close()


def _verify_checksums(d: Path) -> tuple[Optional[bool], str]:
    """Verifica el fichero de sumas del conjunto, si lo hay.

    Devuelve (None, motivo) si no hay ninguno; (True/False, detalle) si lo hay.
    Los nombres varian segun quien creo el backup (SHA256SUMS, checksums.sha256).
    """
    sums = None
    for name in ("SHA256SUMS", "checksums.sha256", "sha256sums.txt"):
        if (d / name).is_file():
            sums = d / name
            break
    if sums is None:
        return None, "sin fichero de sumas"
    try:
        lines = sums.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        return False, f"sumas ilegibles: {e}"

    checked = 0
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        expected, name = parts[0], parts[1].lstrip("*").strip()
        target = d / name
        if not target.is_file():
            continue  # el fichero pudo no formar parte de este conjunto
        h = hashlib.sha256()
        try:
            with target.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
        except OSError as e:
            return False, f"no se pudo leer {name}: {e}"
        if h.hexdigest() != expected:
            return False, f"checksum incorrecto en {name}"
        checked += 1
    if checked == 0:
        return None, "fichero de sumas sin entradas aplicables"
    return True, f"{checked} checksums verificados"


def _is_sensitive(name: str) -> bool:
    """Miembros que portan datos o secretos y exigen 0600."""
    low = name.lower()
    return low.endswith(".db") or ".env" in low or "secret" in low or "password" in low


def _insecure_members(d: Path) -> List[str]:
    """Permisos y symlinks del conjunto.

    El control que de verdad protege es el del DIRECTORIO: si es 0700, nadie
    salvo root entra. Dentro solo se exige 0600 a lo sensible (bases, .env):
    exigirselo a todo marcaba como inseguras copias de unidades systemd y
    manifiestos .md, que no son secretos -> otro falso UNHEALTHY.
    """
    problems: List[str] = []
    try:
        st = d.stat()
    except OSError as e:
        return [f"{d.name}: {e}"]
    if st.st_mode & 0o077:
        problems.append(f"el directorio {d.name}/ es accesible a terceros "
                        f"({oct(st.st_mode & 0o777)})")
    try:
        entries = list(d.iterdir())
    except OSError as e:
        return problems + [f"{d.name}: {e}"]
    for p in entries:
        if p.is_symlink():
            problems.append(f"symlink inesperado: {p.name}")
            continue
        try:
            pst = p.stat()
        except OSError:
            continue
        if p.is_file() and _is_sensitive(p.name) and pst.st_mode & 0o077:
            problems.append(f"{p.name} con permisos {oct(pst.st_mode & 0o777)}")
    return problems


def check_backups(backup_root: Optional[str] = None,
                  warn_age_hours: int = BACKUP_WARN_AGE_HOURS,
                  max_age_hours: int = BACKUP_MAX_AGE_HOURS,
                  max_scan_depth: int = BACKUP_MAX_SCAN_DEPTH,
                  backup_dir: Optional[str] = None) -> ComponentResult:
    """Valida el backup mas reciente. SOLO LECTURA: no crea, borra ni modifica nada.

    Encontrar un directorio no basta para declarar HEALTHY: se valida contenido,
    integridad SQLite, sumas, edad y permisos.
    """
    root_str = backup_root or backup_dir  # backup_dir: nombre antiguo, se acepta
    if not root_str:
        return _result("backups", HealthStatus.UNKNOWN, "no configurado")
    root = Path(root_str)
    if not root.exists():
        return _result("backups", HealthStatus.UNHEALTHY, "la raiz de backups no existe",
                       {"root": str(root)})
    if not os.access(root, os.R_OK | os.X_OK):
        return _result("backups", HealthStatus.UNKNOWN, "raiz de backups inaccesible",
                       {"root": str(root)})

    with _Timer() as t:
        sets = _find_backup_sets(root, max_scan_depth)
    if not sets:
        return _result("backups", HealthStatus.UNHEALTHY, "sin conjuntos de backup",
                       {"root": str(root), "scan_depth": max_scan_depth}, latency_ms=t.ms)

    latest = max(sets, key=_set_mtime)
    age_h = round((time.time() - _set_mtime(latest)) / 3600, 1)
    meta: Dict[str, Any] = {"root": str(root), "sets": len(sets), "latest": latest.name,
                            "age_hours": age_h}

    problems: List[str] = []

    # Manifiesto, si el conjunto lo trae.
    manifest = latest / "manifest.json"
    if manifest.is_file():
        try:
            meta["manifest"] = bool(json.loads(manifest.read_text(encoding="utf-8")))
        except (ValueError, OSError) as e:
            problems.append(f"manifiesto invalido: {e}")

    # Bases SQLite: deben existir, no estar vacias y pasar integrity_check.
    dbs = sorted(p for p in latest.iterdir() if p.is_file() and p.suffix == ".db")
    meta["dbs"] = [p.name for p in dbs]
    if not dbs:
        problems.append("el conjunto no contiene ninguna base")
    for db in dbs:
        if db.stat().st_size == 0:
            problems.append(f"{db.name} vacia (0 bytes)")
            continue
        err = _sqlite_integrity_ro(db)
        if err:
            problems.append(f"{db.name}: {err}")

    ok_sums, sums_detail = _verify_checksums(latest)
    meta["checksums"] = sums_detail
    if ok_sums is False:
        problems.append(sums_detail)

    problems.extend(_pending_wal(latest))

    insecure = _insecure_members(latest)
    if insecure:
        problems.extend(insecure)

    if problems:
        return _result("backups", HealthStatus.UNHEALTHY,
                       "backup mas reciente no valido: " + "; ".join(problems[:3]),
                       {**meta, "problems": problems}, latency_ms=t.ms)

    if age_h > max_age_hours:
        return _result("backups", HealthStatus.UNHEALTHY,
                       "backup valido pero rancio: hace %.1fh (max %dh)" % (age_h, max_age_hours),
                       meta, latency_ms=t.ms)
    if age_h > warn_age_hours:
        return _result("backups", HealthStatus.DEGRADED,
                       "backup valido pero antiguo: hace %.1fh (aviso %dh)" % (age_h, warn_age_hours),
                       meta, latency_ms=t.ms)
    return _result("backups", HealthStatus.HEALTHY,
                   "backup validado hace %.1fh" % age_h, meta, latency_ms=t.ms)


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
