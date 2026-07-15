"""Agregador de checks: construye la configuración y ejecuta los componentes."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.health import checks
from app.health.models import ComponentResult, HealthReport, HealthStatus


def _read_password_file(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        return Path(path).read_text(encoding="utf-8").strip() or None
    except Exception:
        return None


def build_default_config() -> Dict[str, Any]:
    """Config de checks a partir del entorno (sin exponer secretos aguas abajo)."""
    neo4j_pw = os.environ.get("S9K_NEO4J_PASSWORD") or _read_password_file(
        os.environ.get("S9K_NEO4J_PASSWORD_FILE"))
    auth_enabled = os.environ.get("S9K_AUTH_ENABLED", "false").lower() == "true"
    return {
        "viewer": {"base_url": os.environ.get("S9K_HEALTH_VIEWER_URL", "http://127.0.0.1:8088")},
        "neo4j": {
            "uri": os.environ.get("S9K_NEO4J_URI", "bolt://127.0.0.1:7687"),
            "user": os.environ.get("S9K_NEO4J_USER", "neo4j"),
            "password": neo4j_pw,
        },
        "ollama": {"base_url": os.environ.get("S9K_OLLAMA_URL"),
                   "required_model": os.environ.get("S9K_OLLAMA_MODEL")},
        "nextcloud_rclone": {"mountpoint": os.environ.get("S9K_RCLONE_MOUNT")},
        "job_store": {"db_path": os.environ.get("S9K_JOBS_DB")},
        "auth_db": {"db_path": os.environ.get("S9K_AUTH_DB_PATH"), "enabled": auth_enabled},
        "external_ai": {"enabled": os.environ.get("S9K_EXTERNAL_AI_ENABLED", "false").lower() == "true"},
        "burst": {"enabled": os.environ.get("S9K_EXTERNAL_PROCESSING_ENABLED", "false").lower() == "true"},
        "filesystem": {"path": os.environ.get("S9K_HEALTH_DISK_PATH", "/")},
        "backups": {"backup_dir": os.environ.get("S9K_BACKUP_DIR")},
        "systemd": {"units": [u for u in os.environ.get(
            "S9K_HEALTH_UNITS", "s9-knowledge-viewer.service").split(",") if u]},
    }


# Registro nombre-de-componente -> callable(config_section) -> ComponentResult
_REGISTRY: Dict[str, Callable[[Dict[str, Any]], ComponentResult]] = {
    "viewer": lambda c: checks.check_viewer(**c),
    "neo4j": lambda c: checks.check_neo4j(**c),
    "ollama": lambda c: checks.check_ollama(**c),
    "nextcloud_rclone": lambda c: checks.check_nextcloud_rclone(**c),
    "job_store": lambda c: checks.check_job_store(**c),
    "auth_db": lambda c: checks.check_auth_db(**c),
    "external_ai": lambda c: checks.check_external_ai(**c),
    "burst": lambda c: checks.check_burst(**c),
    "filesystem": lambda c: checks.check_filesystem(**c),
    "backups": lambda c: checks.check_backups(**c),
    "systemd": lambda c: checks.check_systemd(**c),
}

COMPONENT_NAMES: List[str] = list(_REGISTRY.keys())


def run_component(name: str, config: Optional[Dict[str, Any]] = None) -> ComponentResult:
    if name not in _REGISTRY:
        raise KeyError(name)
    config = config or build_default_config()
    try:
        return _REGISTRY[name](config.get(name, {}))
    except Exception as exc:  # un check nunca debe tumbar el agregador
        return ComponentResult(name, HealthStatus.UNKNOWN,
                               message="check fallido: %s" % type(exc).__name__)


def run_report(config: Optional[Dict[str, Any]] = None,
               only: Optional[List[str]] = None) -> HealthReport:
    config = config or build_default_config()
    names = only or COMPONENT_NAMES
    return HealthReport(components=[run_component(n, config) for n in names])
