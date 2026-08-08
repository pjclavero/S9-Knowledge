"""Recolectores del Centro de Estado (100% solo lectura).

Reglas de la casa:

* Cada sección tiene UNA fuente ya existente en el repo. Si esa fuente falta,
  está corrupta o trae marcas de tiempo inválidas, la sección vale UNKNOWN.
  Nunca se inventa un valor ni se degrada a OK "porque no había nada malo".
* Ninguna función escribe nada, ni en Neo4j, ni en SQLite, ni en disco.
* Los errores se sanean: se publica el TIPO de error, nunca el mensaje, la
  traza ni la ruta del fichero implicado.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.ops.models import OpsStatus, SectionResult, worst

# ---------------------------------------------------------------------------
# Umbrales (configurables por entorno; valores por defecto conservadores)
# ---------------------------------------------------------------------------
DEFAULTS = {
    # Edad máxima del último informe de health antes de considerarlo rancio.
    "S9K_OPS_HEALTH_STALE_HOURS": 6,
    # Jobs fallidos: a partir de 1 avisa, a partir de N es crítico.
    "S9K_OPS_JOBS_FAILED_CRITICAL": 5,
    # Cola parada: sin ningún job nuevo en tantas horas -> aviso.
    "S9K_OPS_JOBS_IDLE_WARN_HOURS": 168,
    # Cola de revisión demasiado larga.
    "S9K_OPS_REVIEW_PENDING_WARN": 50,
    # Backups (mismos umbrales que el healthcheck existente).
    "S9K_OPS_BACKUP_WARN_AGE_HOURS": 26,
    "S9K_OPS_BACKUP_MAX_AGE_HOURS": 48,
    # Restore verificado: si no se verifica en tantas horas, aviso / crítico.
    "S9K_OPS_RESTORE_WARN_AGE_HOURS": 720,   # 30 días
    "S9K_OPS_RESTORE_MAX_AGE_HOURS": 2160,   # 90 días
    # El propio watchdog de backups debe refrescar su estado a diario.
    "S9K_OPS_BACKUP_WATCHDOG_STALE_HOURS": 25,
    # Seguridad: fallos de login en la ventana reciente.
    "S9K_OPS_AUDIT_WINDOW_HOURS": 24,
    "S9K_OPS_LOGIN_FAILURE_WARN": 10,
}


def threshold(name: str) -> int:
    """Umbral entero desde entorno, tolerante a basura (cae al valor por defecto)."""
    default = int(DEFAULTS[name])
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Tiempo
# ---------------------------------------------------------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: Any) -> Optional[datetime]:
    """Parsea un instante ISO-8601. Devuelve None si es inválido o ausente.

    Un timestamp inválido NO es "ahora" ni "hace mucho": es desconocido, y el
    llamador debe traducirlo a UNKNOWN.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def age_hours(value: Any, now: Optional[datetime] = None) -> Optional[float]:
    """Edad en horas de una marca de tiempo, o None si no se puede saber."""
    dt = parse_ts(value)
    if dt is None:
        return None
    delta = (now or now_utc()) - dt
    return round(delta.total_seconds() / 3600.0, 2)


def _read_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    """Lee un JSON. Devuelve (dato, motivo_de_fallo). Nunca lanza."""
    try:
        if not path.exists():
            return None, "fuente_ausente"
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError:
        return None, "json_corrupto"
    except OSError:
        return None, "fuente_ilegible"
    except Exception as exc:  # nunca propagar detalles hacia la web
        return None, "error_%s" % type(exc).__name__


# ---------------------------------------------------------------------------
# 1. Aplicación
# ---------------------------------------------------------------------------

_HEALTH_TO_OPS = {
    "HEALTHY": OpsStatus.OK,
    "DEGRADED": OpsStatus.WARNING,
    "UNHEALTHY": OpsStatus.CRITICAL,
    "UNKNOWN": OpsStatus.UNKNOWN,
}


def _release_info() -> Dict[str, Optional[str]]:
    """Versión y commit desplegados, si alguien los ha dejado dichos.

    Fuentes admitidas, en orden: fichero de release (``S9K_OPS_RELEASE_PATH``)
    y variables de entorno ``S9K_APP_VERSION`` / ``S9K_GIT_COMMIT``. Si no hay
    ninguna, se devuelve None: el panel dirá "no lo sé", no inventará la versión.
    """
    version = None
    commit = None
    raw_path = os.environ.get("S9K_OPS_RELEASE_PATH")
    if raw_path:
        data, _ = _read_json(Path(raw_path))
        if isinstance(data, dict):
            version = data.get("version")
            commit = data.get("commit")
    version = version or os.environ.get("S9K_APP_VERSION") or None
    commit = commit or os.environ.get("S9K_GIT_COMMIT") or None
    if isinstance(commit, str) and len(commit) > 12:
        commit = commit[:12]  # nunca hace falta más, y evita ruido
    return {"version": version or None, "commit": commit or None}


def collect_application(now: Optional[datetime] = None) -> SectionResult:
    """Versión, commit, estado del viewer y frescura del último healthcheck."""
    from app.health import storage

    metrics: Dict[str, Any] = dict(_release_info())
    notes = []
    statuses = []

    if metrics["version"] is None or metrics["commit"] is None:
        statuses.append(OpsStatus.UNKNOWN)
        notes.append("versión/commit no declarados por el despliegue")

    report, reason = None, None
    try:
        report = storage.load_last()
    except Exception as exc:
        reason = "error_%s" % type(exc).__name__
    if report is None and reason is None:
        reason = "fuente_ausente"

    if not isinstance(report, dict):
        metrics.update({"health_overall": None, "health_checked_at": None,
                        "health_age_hours": None, "viewer_status": None})
        notes.append("sin informe de health: %s" % (reason or "json_corrupto"))
        statuses.append(OpsStatus.UNKNOWN)
        return SectionResult("application", "Aplicación", worst(statuses),
                             "No hay informe de health que leer.", metrics, notes)

    overall = report.get("overall")
    checked_at = report.get("generated_at")
    edad = age_hours(checked_at, now)
    metrics["health_overall"] = overall if overall in _HEALTH_TO_OPS else None
    metrics["health_checked_at"] = checked_at if parse_ts(checked_at) else None
    metrics["health_age_hours"] = edad

    viewer_status = None
    for comp in report.get("components", []) or []:
        if isinstance(comp, dict) and comp.get("component") == "viewer":
            viewer_status = comp.get("status")
            break
    metrics["viewer_status"] = viewer_status if viewer_status in _HEALTH_TO_OPS else None
    statuses.append(_HEALTH_TO_OPS.get(viewer_status, OpsStatus.UNKNOWN))
    statuses.append(_HEALTH_TO_OPS.get(overall, OpsStatus.UNKNOWN))

    if edad is None:
        statuses.append(OpsStatus.UNKNOWN)
        notes.append("marca de tiempo del informe inválida: edad desconocida")
    elif edad > threshold("S9K_OPS_HEALTH_STALE_HOURS"):
        statuses.append(OpsStatus.WARNING)
        notes.append("informe de health rancio (%.1f h)" % edad)

    status = worst(statuses)
    return SectionResult("application", "Aplicación", status,
                         "Estado del viewer según el último healthcheck.",
                         metrics, notes)


# ---------------------------------------------------------------------------
# 2. Datos (Neo4j)
# ---------------------------------------------------------------------------

def collect_data(provider: Any = None, now: Optional[datetime] = None) -> SectionResult:
    """Accesibilidad del grafo y volumen (nodos/relaciones).

    No abre conexiones nuevas por su cuenta: usa el proveedor ya construido por
    el visor, y jamás escribe.
    """
    from app.health import storage

    metrics: Dict[str, Any] = {"provider": None, "connected": None,
                               "nodes": None, "relationships": None,
                               "last_check": None}
    notes = []
    if provider is None:
        try:
            from app.deps import get_provider
            provider = get_provider()
        except Exception as exc:
            notes.append("proveedor no disponible (%s)" % type(exc).__name__)
            return SectionResult("data", "Datos", OpsStatus.UNKNOWN,
                                 "No se pudo obtener el proveedor de grafo.",
                                 metrics, notes)

    metrics["provider"] = getattr(provider, "name", None)
    try:
        connected = bool(provider.is_connected())
    except Exception as exc:
        notes.append("comprobación de conexión fallida (%s)" % type(exc).__name__)
        return SectionResult("data", "Datos", OpsStatus.UNKNOWN,
                             "No se pudo determinar si el grafo es accesible.",
                             metrics, notes)

    metrics["connected"] = connected
    if not connected:
        return SectionResult("data", "Datos", OpsStatus.CRITICAL,
                             "El grafo no es accesible.", metrics, notes)

    try:
        nodes, rels = provider.counts()
        metrics["nodes"], metrics["relationships"] = int(nodes), int(rels)
    except Exception as exc:
        notes.append("conteo no disponible (%s)" % type(exc).__name__)
        return SectionResult("data", "Datos", OpsStatus.UNKNOWN,
                             "Grafo accesible pero sin conteos fiables.",
                             metrics, notes)

    # Fecha del último chequeo: la del componente neo4j del informe de health.
    try:
        report = storage.load_last()
    except Exception:
        report = None
    if isinstance(report, dict):
        for comp in report.get("components", []) or []:
            if isinstance(comp, dict) and comp.get("component") == "neo4j":
                if parse_ts(comp.get("checked_at")):
                    metrics["last_check"] = comp.get("checked_at")
                break
    if metrics["last_check"] is None:
        notes.append("sin fecha fiable del último chequeo de Neo4j")

    status = OpsStatus.OK
    if metrics["nodes"] == 0:
        status = OpsStatus.WARNING
        notes.append("el grafo está vacío")
    if metrics["last_check"] is None:
        status = worst([status, OpsStatus.UNKNOWN])
    return SectionResult("data", "Datos", status,
                         "Grafo accesible.", metrics, notes)


# ---------------------------------------------------------------------------
# 3. Procesado (cola de jobs)
# ---------------------------------------------------------------------------

def collect_processing(now: Optional[datetime] = None) -> SectionResult:
    """Cola de jobs: pendientes / en curso / fallidos / completados y último job."""
    from app import jobs_client

    metrics: Dict[str, Any] = {"counts": None, "pending": None, "running": None,
                               "failed": None, "completed": None,
                               "last_job_status": None, "last_job_at": None,
                               "last_job_age_hours": None}
    notes = []
    try:
        db_status = jobs_client.jobs_db_status()
    except Exception as exc:
        notes.append("cola no consultable (%s)" % type(exc).__name__)
        return SectionResult("processing", "Procesado", OpsStatus.UNKNOWN,
                             "No se pudo consultar la cola de jobs.", metrics, notes)

    if not db_status.get("ok"):
        notes.append("base de jobs ausente o ilegible")
        return SectionResult("processing", "Procesado", OpsStatus.UNKNOWN,
                             "No hay base de jobs que leer.", metrics, notes)

    try:
        counts = jobs_client.get_counts_by_status() or {}
        jobs = jobs_client.list_jobs(limit=200)
    except Exception as exc:
        notes.append("lectura de la cola fallida (%s)" % type(exc).__name__)
        return SectionResult("processing", "Procesado", OpsStatus.UNKNOWN,
                             "La cola de jobs no devolvió datos utilizables.",
                             metrics, notes)

    counts = {str(k): int(v) for k, v in counts.items() if isinstance(v, int)}
    metrics["counts"] = counts
    metrics["pending"] = counts.get("pending", 0) + counts.get("queued", 0)
    metrics["running"] = counts.get("running", 0)
    metrics["failed"] = counts.get("failed", 0)
    metrics["completed"] = counts.get("completed", 0) + counts.get("done", 0)

    statuses = [OpsStatus.OK]

    last = None
    for job in jobs:
        ts = job.get("updated_at") or job.get("created_at")
        dt = parse_ts(ts)
        if dt is None:
            continue
        if last is None or dt > last[0]:
            last = (dt, job, ts)
    if jobs and last is None:
        notes.append("hay jobs pero ninguna marca de tiempo válida")
        statuses.append(OpsStatus.UNKNOWN)
    elif last is not None:
        metrics["last_job_status"] = str(last[1].get("status") or "") or None
        metrics["last_job_at"] = last[2]
        metrics["last_job_age_hours"] = age_hours(last[2], now)
        idle = threshold("S9K_OPS_JOBS_IDLE_WARN_HOURS")
        if (metrics["last_job_age_hours"] is not None
                and metrics["last_job_age_hours"] > idle
                and (metrics["pending"] or 0) > 0):
            statuses.append(OpsStatus.WARNING)
            notes.append("hay trabajo pendiente y nada se mueve desde hace %.0f h"
                         % metrics["last_job_age_hours"])
    else:
        notes.append("la cola está vacía")

    failed = metrics["failed"] or 0
    if failed >= threshold("S9K_OPS_JOBS_FAILED_CRITICAL"):
        statuses.append(OpsStatus.CRITICAL)
        notes.append("%d jobs fallidos" % failed)
    elif failed > 0:
        statuses.append(OpsStatus.WARNING)
        notes.append("%d jobs fallidos" % failed)

    return SectionResult("processing", "Procesado", worst(statuses),
                         "Cola de procesado (solo lectura).", metrics, notes)


# ---------------------------------------------------------------------------
# 4. Revisión
# ---------------------------------------------------------------------------

def collect_review(now: Optional[datetime] = None) -> SectionResult:
    """Cola de revisión: pendientes, aprobados, rechazados y fuentes pendientes."""
    from app.services import review_console

    metrics: Dict[str, Any] = {"pending": None, "approved": None, "rejected": None,
                               "sources_total": None, "sources_pending": None}
    notes = []

    try:
        summaries = review_console.list_source_summaries()
    except Exception as exc:
        notes.append("resúmenes de revisión ilegibles (%s)" % type(exc).__name__)
        return SectionResult("review", "Revisión", OpsStatus.UNKNOWN,
                             "No se pudo leer la bandeja de revisión.", metrics, notes)

    metrics["sources_total"] = len(summaries)
    pending = 0
    sources_pending = 0
    for s in summaries:
        p = s.get("pending")
        if isinstance(p, int):
            pending += p
            if p > 0:
                sources_pending += 1
    metrics["pending"] = pending
    metrics["sources_pending"] = sources_pending

    try:
        decisions = review_console.read_decisions()
    except Exception as exc:
        notes.append("decisiones ilegibles (%s)" % type(exc).__name__)
        return SectionResult("review", "Revisión", OpsStatus.UNKNOWN,
                             "El registro de decisiones no es legible.", metrics, notes)

    approved = sum(1 for d in decisions
                   if d.get("action") in ("APPROVE", "EDIT", "USE_EXISTING",
                                          "RESOLVE_CONFLICT"))
    rejected = sum(1 for d in decisions if d.get("action") == "REJECT")
    metrics["approved"] = approved
    metrics["rejected"] = rejected

    statuses = [OpsStatus.OK]
    if not summaries:
        statuses.append(OpsStatus.UNKNOWN)
        notes.append("no hay fuentes de revisión visibles")
    if pending >= threshold("S9K_OPS_REVIEW_PENDING_WARN"):
        statuses.append(OpsStatus.WARNING)
        notes.append("%d candidatos pendientes de revisión" % pending)

    return SectionResult("review", "Revisión", worst(statuses),
                         "Bandeja de revisión (solo lectura).", metrics, notes)


# ---------------------------------------------------------------------------
# 5. Backups (estado ya saneado por un watchdog EXTERNO)
# ---------------------------------------------------------------------------
# El panel NO habla con Proxmox: no recibe token PVE, no hace SSH, no ejecuta
# vzdump ni lee el almacenamiento de copias. Sólo lee un fichero JSON que un
# watchdog externo deja escrito. Si ese fichero no existe todavía, esto es
# UNKNOWN; jamás "OK por defecto".

def backup_state_path() -> Path:
    return Path(os.environ.get("S9K_OPS_BACKUP_STATE_PATH",
                               "viewer/state/ops/backup_watchdog.json"))


def collect_backups(now: Optional[datetime] = None) -> SectionResult:
    metrics: Dict[str, Any] = {"vmid": None, "last_backup": None, "age_hours": None,
                               "rpo_hours": None, "watchdog_status": None,
                               "last_restore_verified": None,
                               "restore_age_hours": None, "restore_status": None,
                               "state_age_hours": None}
    notes = []
    data, reason = _read_json(backup_state_path())
    if data is None or not isinstance(data, dict):
        notes.append("watchdog de backups: %s" % (reason or "formato_inesperado"))
        notes.append("el panel no consulta Proxmox: sin fichero de estado no hay dato")
        return SectionResult("backups", "Backups", OpsStatus.UNKNOWN,
                             "Sin estado del watchdog de backups.", metrics, notes)

    vmid = data.get("vmid")
    metrics["vmid"] = vmid if isinstance(vmid, int) else None
    metrics["watchdog_status"] = (str(data.get("status")).lower()
                                  if isinstance(data.get("status"), str) else None)
    metrics["restore_status"] = (str(data.get("restore_status")).lower()
                                 if isinstance(data.get("restore_status"), str) else None)

    statuses = []

    # --- último backup ---
    last_backup = data.get("last_backup")
    edad = age_hours(last_backup, now)
    if edad is None:
        # Puede venir precalculada por el watchdog; sólo si es un número real.
        declared = data.get("age_hours")
        if isinstance(declared, (int, float)) and not isinstance(declared, bool):
            edad = float(declared)
        else:
            notes.append("fecha del último backup ausente o inválida")
    metrics["last_backup"] = last_backup if parse_ts(last_backup) else None
    metrics["age_hours"] = edad
    metrics["rpo_hours"] = edad  # RPO observado = antigüedad de la última copia

    warn = threshold("S9K_OPS_BACKUP_WARN_AGE_HOURS")
    crit = threshold("S9K_OPS_BACKUP_MAX_AGE_HOURS")
    if edad is None:
        statuses.append(OpsStatus.UNKNOWN)
    elif edad > crit:
        statuses.append(OpsStatus.CRITICAL)
        notes.append("última copia de hace %.1f h (límite %d h)" % (edad, crit))
    elif edad > warn:
        statuses.append(OpsStatus.WARNING)
        notes.append("última copia de hace %.1f h" % edad)
    else:
        statuses.append(OpsStatus.OK)

    # --- restore verificado ---
    last_restore = data.get("last_restore_verified")
    r_edad = age_hours(last_restore, now)
    metrics["last_restore_verified"] = last_restore if parse_ts(last_restore) else None
    metrics["restore_age_hours"] = r_edad
    if r_edad is None:
        statuses.append(OpsStatus.UNKNOWN)
        notes.append("nunca se ha verificado un restore (o la fecha es inválida)")
    elif r_edad > threshold("S9K_OPS_RESTORE_MAX_AGE_HOURS"):
        statuses.append(OpsStatus.CRITICAL)
        notes.append("restore sin verificar desde hace %.0f h" % r_edad)
    elif r_edad > threshold("S9K_OPS_RESTORE_WARN_AGE_HOURS"):
        statuses.append(OpsStatus.WARNING)
        notes.append("restore sin verificar desde hace %.0f h" % r_edad)

    # --- veredictos que el propio watchdog declara ---
    for label, value in (("backup", metrics["watchdog_status"]),
                         ("restore", metrics["restore_status"])):
        if value is None:
            statuses.append(OpsStatus.UNKNOWN)
            notes.append("el watchdog no declara estado de %s" % label)
        elif value in ("critical", "error", "failed", "fail"):
            statuses.append(OpsStatus.CRITICAL)
            notes.append("el watchdog declara %s=%s" % (label, value))
        elif value in ("warning", "warn", "degraded", "stale"):
            statuses.append(OpsStatus.WARNING)
            notes.append("el watchdog declara %s=%s" % (label, value))
        elif value in ("ok", "healthy", "pass", "verified"):
            statuses.append(OpsStatus.OK)
        else:
            statuses.append(OpsStatus.UNKNOWN)
            notes.append("estado de %s no reconocido" % label)

    # --- frescura del propio watchdog ---
    generated = data.get("generated_at") or data.get("checked_at")
    s_edad = age_hours(generated, now)
    metrics["state_age_hours"] = s_edad
    if s_edad is None:
        statuses.append(OpsStatus.UNKNOWN)
        notes.append("el fichero de estado no dice cuándo se generó")
    elif s_edad > threshold("S9K_OPS_BACKUP_WATCHDOG_STALE_HOURS"):
        statuses.append(OpsStatus.WARNING)
        notes.append("el watchdog no se refresca desde hace %.1f h" % s_edad)

    return SectionResult("backups", "Backups", worst(statuses),
                         "Estado publicado por el watchdog externo (VM105).",
                         metrics, notes)


# ---------------------------------------------------------------------------
# 6. Seguridad
# ---------------------------------------------------------------------------
# Solo agregados: número de sesiones vivas, usuarios bloqueados y recuento de
# eventos de auditoría recientes. Nunca tokens, hashes de sesión, contraseñas,
# IPs ni rutas de la base de datos.

_SECURITY_METRIC_KEYS = ("auth_enabled", "active_sessions", "locked_users",
                         "active_users", "audit_events_recent",
                         "login_failures_recent", "last_event_at",
                         "last_event_age_hours", "recent_event_types")


def collect_security(now: Optional[datetime] = None) -> SectionResult:
    from app.auth.config import get_auth_settings

    metrics: Dict[str, Any] = {k: None for k in _SECURITY_METRIC_KEYS}
    notes = []
    try:
        cfg = get_auth_settings()
    except Exception as exc:
        notes.append("configuración de auth no legible (%s)" % type(exc).__name__)
        return SectionResult("security", "Seguridad", OpsStatus.UNKNOWN,
                             "No se pudo leer la configuración de autenticación.",
                             metrics, notes)

    metrics["auth_enabled"] = bool(cfg.S9K_AUTH_ENABLED)
    if not cfg.S9K_AUTH_ENABLED:
        notes.append("auth desactivada: no hay sesiones ni auditoría que observar")
        return SectionResult("security", "Seguridad", OpsStatus.UNKNOWN,
                             "Autenticación desactivada en esta instancia.",
                             metrics, notes)

    db_path = Path(cfg.S9K_AUTH_DB_PATH)
    if not db_path.is_file():
        notes.append("base de autenticación ausente")
        return SectionResult("security", "Seguridad", OpsStatus.UNKNOWN,
                             "No hay base de autenticación que leer.", metrics, notes)

    window = threshold("S9K_OPS_AUDIT_WINDOW_HOURS")
    since = ((now or now_utc()) - timedelta(hours=window)).replace(microsecond=0).isoformat()
    ahora = (now or now_utc()).replace(microsecond=0).isoformat()

    try:
        conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
        try:
            conn.row_factory = sqlite3.Row
            metrics["active_sessions"] = conn.execute(
                "SELECT COUNT(*) FROM sessions "
                "WHERE revoked_at IS NULL AND expires_at > ?", (ahora,)
            ).fetchone()[0]
            metrics["locked_users"] = conn.execute(
                "SELECT COUNT(*) FROM users WHERE locked_until IS NOT NULL "
                "AND locked_until > ?", (ahora,)
            ).fetchone()[0]
            metrics["active_users"] = conn.execute(
                "SELECT COUNT(*) FROM users WHERE is_active = 1"
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT event_type, COUNT(*) AS n FROM audit_events "
                "WHERE created_at >= ? GROUP BY event_type", (since,)
            ).fetchall()
            last_row = conn.execute(
                "SELECT created_at FROM audit_events ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        notes.append("lectura de auditoría fallida (%s)" % type(exc).__name__)
        return SectionResult("security", "Seguridad", OpsStatus.UNKNOWN,
                             "La base de autenticación no es consultable.",
                             metrics, notes)

    by_type = {str(r["event_type"]): int(r["n"]) for r in rows}
    metrics["recent_event_types"] = by_type
    metrics["audit_events_recent"] = sum(by_type.values())
    metrics["login_failures_recent"] = by_type.get("LOGIN_FAILURE", 0)
    last_at = last_row["created_at"] if last_row else None
    metrics["last_event_at"] = last_at if parse_ts(last_at) else None
    metrics["last_event_age_hours"] = age_hours(last_at, now)

    statuses = [OpsStatus.OK]
    if last_at is not None and metrics["last_event_at"] is None:
        statuses.append(OpsStatus.UNKNOWN)
        notes.append("el último evento de auditoría tiene fecha inválida")
    if (metrics["locked_users"] or 0) > 0:
        statuses.append(OpsStatus.WARNING)
        notes.append("%d usuarios bloqueados" % metrics["locked_users"])
    if (metrics["login_failures_recent"] or 0) >= threshold("S9K_OPS_LOGIN_FAILURE_WARN"):
        statuses.append(OpsStatus.WARNING)
        notes.append("%d fallos de login en %d h"
                     % (metrics["login_failures_recent"], window))
    if by_type.get("AUTH_BACKEND_ERROR", 0) > 0:
        statuses.append(OpsStatus.CRITICAL)
        notes.append("errores del backend de autenticación en la ventana reciente")

    return SectionResult("security", "Seguridad", worst(statuses),
                         "Sesiones y auditoría (agregados, sin secretos).",
                         metrics, notes)


# ---------------------------------------------------------------------------
# Informe completo
# ---------------------------------------------------------------------------

COLLECTORS = (
    ("application", collect_application),
    ("data", collect_data),
    ("processing", collect_processing),
    ("review", collect_review),
    ("backups", collect_backups),
    ("security", collect_security),
)

_TITLES = {"application": "Aplicación", "data": "Datos", "processing": "Procesado",
           "review": "Revisión", "backups": "Backups", "security": "Seguridad"}


def build_report(now: Optional[datetime] = None, provider: Any = None):
    """Construye el informe completo. Un recolector que explote NO tumba el panel:
    su sección queda en UNKNOWN, que es exactamente lo que se sabe de ella."""
    from app.ops.models import OpsReport

    sections = []
    for key, fn in COLLECTORS:
        try:
            if key == "data":
                sections.append(fn(provider=provider, now=now))
            else:
                sections.append(fn(now=now))
        except Exception as exc:
            sections.append(SectionResult(
                key, _TITLES.get(key, key), OpsStatus.UNKNOWN,
                "Sección no evaluable.",
                notes=["recolector fallido (%s)" % type(exc).__name__]))
    return OpsReport(sections=sections)
