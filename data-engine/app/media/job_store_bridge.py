"""Adaptador opcional entre el pipeline multimedia y el job_store SQLite (jobs.db).

El registro primario de los jobs multimedia es `MediaJobStore` (JSON). Este
bridge refleja el ciclo de vida en el `job_store` genérico del proyecto para
que la cola SQLite tenga también constancia de los trabajos multimedia, sin
duplicar los metadatos ricos (que se quedan en el JSON, como "payload").

Se activa con `S9K_MEDIA_JOBSTORE_BRIDGE=true` (MediaConfig.jobstore_bridge).
Está desacoplado a propósito: si el bridge está desactivado o el import de
job_store falla, el pipeline multimedia sigue funcionando igual.

Nunca escribe en Neo4j.
"""
from __future__ import annotations

import logging

from media.models import (
    MediaSource,
    STATUS_AUDIO_EXTRACTING,
    STATUS_COMPLETE,
    STATUS_FAILED,
    STATUS_PROBING,
    STATUS_SKIPPED,
    STATUS_TRANSCRIBING,
    STATUS_WRITING_MARKDOWN,
)

log = logging.getLogger("media.bridge")

# Mapa estado-multimedia → estado del job_store genérico.
_STATUS_MAP = {
    STATUS_PROBING: "processing",
    STATUS_AUDIO_EXTRACTING: "extracting",
    STATUS_TRANSCRIBING: "transcribing",
    STATUS_WRITING_MARKDOWN: "processing",
    STATUS_COMPLETE: "completed",
    STATUS_FAILED: "failed",
    STATUS_SKIPPED: "ignored",
}


def map_status(media_status: str) -> str | None:
    """Traduce un estado multimedia al vocabulario de job_store (o None)."""
    return _STATUS_MAP.get(media_status)


class JobStoreBridge:
    """Envuelve el job_store SQLite; degrada a no-op si no está disponible."""

    def __init__(self, db_path: str | None = None):
        self._enabled = False
        self._store = None
        self._db_path = db_path
        # source_id (media) → job_id (job_store)
        self._id_map: dict[str, str] = {}
        try:
            from jobs import job_store as _js

            self._js = _js
            self._store = _js.JobStore(db_path) if db_path else _js.JobStore()
            self._enabled = True
        except Exception as exc:  # noqa: BLE001 - el bridge nunca debe romper el pipeline
            log.warning("job_store no disponible, bridge desactivado: %s", exc)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def register(self, source: MediaSource) -> str | None:
        """Crea (o localiza) un job en jobs.db para esta fuente multimedia."""
        if not self._enabled:
            return None
        try:
            job_id = self._store.create_job(
                workspace=source.workspace,
                source_kind=source.source_kind,  # "video" | "audio"
                source_path=source.original_path,
                source_title=source.original_filename,
                status="pending",
            )
            self._id_map[source.source_id] = job_id
            return job_id
        except Exception as exc:  # noqa: BLE001
            log.warning("bridge.register falló para %s: %s", source.source_id, exc)
            return None

    def sync_status(self, source: MediaSource, error_message: str = "") -> None:
        """Refleja el estado actual de la fuente en el job de jobs.db."""
        if not self._enabled:
            return
        job_id = self._id_map.get(source.source_id)
        if not job_id:
            return
        mapped = map_status(source.status)
        if mapped is None:
            return
        try:
            self._store.set_status(job_id, mapped, error_message=error_message or None)
            fields = {}
            if source.output_markdown:
                fields["output_markdown_path"] = source.output_markdown
            if source.output_transcript_json:
                fields["output_transcript_path"] = source.output_transcript_json
            if fields:
                self._store.update_job(job_id, **fields)
        except Exception as exc:  # noqa: BLE001
            log.warning("bridge.sync_status falló para %s: %s", source.source_id, exc)
