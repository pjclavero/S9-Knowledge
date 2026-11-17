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
    # H-1 (ronda 2): root no escribe el informe dentro del estado vivo (un health.json
    # root:root deja al healthcheck del servicio sin poder reemplazarlo), y cada
    # directorio que falte nace con el modo EXACTO de la autoridad, no con la umask.
    service_identity.refuse_root_state_write(path)
    service_identity.ensure_private_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # Privado desde el nacimiento (H-06): el temporal YA es 0600 (fchmod en la
    # autoridad) antes de publicarse con `os.replace`; ninguna ventana 0644.
    fd = service_identity.service_state().open_private_write(tmp)
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
