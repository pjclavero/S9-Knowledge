"""Almacenamiento del último informe de health (JSON sanitizado)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from app import service_identity
from app.health.models import HealthReport


def default_report_path() -> Path:
    return Path(os.environ.get(
        "S9K_HEALTH_REPORT_PATH",
        "viewer/state/health/last_report.json"))


def save_report(report: HealthReport, path: Optional[Path] = None) -> Path:
    path = Path(path) if path else default_report_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=service_identity.dir_mode())
    tmp = path.with_suffix(path.suffix + ".tmp")
    # Privado desde el nacimiento (H-06): modo de la autoridad, sin ventana.
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, service_identity.file_mode())
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    os.replace(tmp, path)
    try:
        os.chmod(path, service_identity.file_mode())
    except OSError:
        pass
    return path


def load_last(path: Optional[Path] = None) -> Optional[dict]:
    path = Path(path) if path else default_report_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
