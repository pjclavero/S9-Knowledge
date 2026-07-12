"""Registro de jobs multimedia basado en archivos JSON (una fuente = un JSON).

Es el registro primario del pipeline multimedia: autocontenido, sin SQLite ni
Neo4j, y compatible con `.gitignore` (vive bajo `output/media/`, ignorado).
Guarda los metadatos ricos (sha256, duración, códecs, estados finos) que el
`job_store` SQLite genérico no modela.

La integración opcional con `jobs.db` (job_store SQLite) se hace aparte, en
`media/job_store_bridge.py`, para no acoplar este registro a SQLite.
"""
from __future__ import annotations

import json
from pathlib import Path

from media.models import MediaSource, now_iso


class MediaJobStore:
    """Almacena cada MediaSource como output/media/<workspace>/<source_id>.json."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    def _workspace_dir(self, workspace: str) -> Path:
        return self.base_dir / workspace

    def _path_for(self, workspace: str, source_id: str) -> Path:
        return self._workspace_dir(workspace) / f"{source_id}.json"

    def exists(self, workspace: str, source_id: str) -> bool:
        return self._path_for(workspace, source_id).is_file()

    def save(self, source: MediaSource) -> Path:
        source.updated_at = now_iso()
        path = self._path_for(source.workspace, source.source_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(source.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def get(self, workspace: str, source_id: str) -> MediaSource | None:
        path = self._path_for(workspace, source_id)
        if not path.is_file():
            return None
        return MediaSource.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list(self, workspace: str, status: str | None = None) -> list[MediaSource]:
        ws_dir = self._workspace_dir(workspace)
        if not ws_dir.is_dir():
            return []
        out: list[MediaSource] = []
        for p in sorted(ws_dir.glob("*.json")):
            try:
                src = MediaSource.from_dict(json.loads(p.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
            if status is None or src.status == status:
                out.append(src)
        return out

    def set_status(self, source: MediaSource, status: str, error_message: str = "") -> MediaSource:
        source.status = status
        if error_message:
            source.error_message = error_message
        self.save(source)
        return source
