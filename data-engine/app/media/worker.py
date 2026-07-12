"""Worker manual que procesa jobs multimedia pendientes.

Por cada job pending: sonda metadatos, extrae audio (si es vídeo) o normaliza
(si es audio), transcribe, escribe el Markdown revisable y marca el job como
complete. Si algo falla, marca failed con un mensaje controlado.

NO escribe en Neo4j. NO ejecuta ingesta al grafo. La salida es una fuente
revisable en output/transcriptions/.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from media.audio_extract import AudioExtractionError, extract_audio
from media.config import MediaConfig
from media.markdown_writer import write_markdown
from media.models import (
    MediaSource,
    STATUS_AUDIO_EXTRACTING,
    STATUS_COMPLETE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PROBING,
    STATUS_TRANSCRIBING,
    STATUS_WRITING_MARKDOWN,
    SOURCE_KIND_VIDEO,
)
from media.probe import probe_media
from media.store import MediaJobStore
from media.transcriber import Transcriber, TranscriberError, get_transcriber

log = logging.getLogger("media.worker")


@dataclass
class WorkerResult:
    processed: list[str]     # source_ids completados
    failed: list[str]        # source_ids fallidos
    skipped: list[str]       # source_ids omitidos (p.ej. dry-run)
    dry_run: bool


def _set_status(store, source, bridge, status, error_message=""):
    store.set_status(source, status, error_message=error_message)
    if bridge is not None and getattr(bridge, "enabled", False):
        bridge.sync_status(source, error_message=error_message)


def process_source(
    source: MediaSource,
    config: MediaConfig,
    store: MediaJobStore,
    transcriber: Transcriber,
    bridge=None,
) -> MediaSource:
    """Procesa una única fuente de principio a fin. Actualiza estado en el store."""
    # 1. Probing (rellena metadatos que falten)
    _set_status(store, source, bridge, STATUS_PROBING)
    try:
        probe = probe_media(Path(source.original_path))
        if probe.duration_seconds is not None:
            source.duration_seconds = probe.duration_seconds
        if probe.media_format:
            source.media_format = probe.media_format
        if probe.audio_codec:
            source.audio_codec = probe.audio_codec
        if probe.video_codec:
            source.video_codec = probe.video_codec

        # 2. Obtener el audio a transcribir
        _set_status(store, source, bridge, STATUS_AUDIO_EXTRACTING)
        audio_out = config.audio_dir / source.workspace / f"{source.source_id}.wav"
        extract_audio(
            Path(source.original_path),
            audio_out,
            max_duration_seconds=config.max_duration_seconds,
        )
        source.audio_path = str(audio_out)

        # 3. Transcribir
        _set_status(store, source, bridge, STATUS_TRANSCRIBING)
        transcript = transcriber.transcribe(audio_out, language=config.language)
        source.transcriber_engine = transcript.engine
        source.transcriber_model = transcript.model
        source.language = transcript.language

        # Guardar el JSON de transcripción (junto al markdown, revisable)
        json_dir = config.transcript_dir / source.workspace
        json_dir.mkdir(parents=True, exist_ok=True)
        json_path = json_dir / f"{source.source_id}.json"
        json_path.write_text(
            json.dumps(transcript.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        source.output_transcript_json = str(json_path)

        # 4. Markdown revisable
        _set_status(store, source, bridge, STATUS_WRITING_MARKDOWN)
        md_path = write_markdown(source, transcript, config.transcript_dir)
        source.output_markdown = str(md_path)

        # 5. Completo
        _set_status(store, source, bridge, STATUS_COMPLETE)
        log.info("Fuente completada: %s (%s)", source.original_filename, source.source_id)
    except (AudioExtractionError, TranscriberError) as exc:
        _set_status(store, source, bridge, STATUS_FAILED, error_message=str(exc))
        log.error("Fuente fallida %s: %s", source.source_id, exc)
    except Exception as exc:  # noqa: BLE001 - cualquier error deja el job en failed
        _set_status(store, source, bridge, STATUS_FAILED, error_message=f"error inesperado: {exc}")
        log.exception("Error inesperado procesando %s", source.source_id)
    return source


def run_worker(
    config: MediaConfig,
    workspace: str,
    limit: int = 1,
    source_id: str | None = None,
    dry_run: bool | None = None,
    store: MediaJobStore | None = None,
    transcriber: Transcriber | None = None,
    bridge=None,
) -> WorkerResult:
    """Procesa hasta `limit` jobs pending del workspace (o uno concreto)."""
    if store is None:
        store = MediaJobStore(config.output_dir)
    if dry_run is None:
        dry_run = config.dry_run
    if transcriber is None and not dry_run:
        transcriber = get_transcriber(config)

    processed: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []

    if source_id:
        one = store.get(workspace, source_id)
        candidates = [one] if one else []
    else:
        candidates = store.list(workspace, status=STATUS_PENDING)
        if limit and limit > 0:
            candidates = candidates[:limit]

    for source in candidates:
        if source is None:
            continue
        if source.status not in (STATUS_PENDING,) and not source_id:
            skipped.append(source.source_id)
            continue
        if dry_run:
            log.info("[dry-run] Procesaría: %s (%s)", source.original_filename, source.source_id)
            skipped.append(source.source_id)
            continue

        result = process_source(source, config, store, transcriber, bridge=bridge)
        if result.status == STATUS_COMPLETE:
            processed.append(result.source_id)
        else:
            failed.append(result.source_id)

    return WorkerResult(processed, failed, skipped, dry_run)
