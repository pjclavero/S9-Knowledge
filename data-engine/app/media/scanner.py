"""Escáner de la carpeta staging: detecta vídeo/audio y crea jobs pendientes.

- Recorre recursivamente el directorio de staging.
- Ignora archivos temporales/parciales y extensiones no soportadas.
- Calcula sha256 y deriva un source_id estable del contenido.
- Deduplica: si ya existe un job para ese source_id, lo omite.
- Sondea metadatos con ffprobe (degradación controlada si no está).
- En modo dry-run no persiste nada, solo informa de lo que haría.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from media.config import MediaConfig
from media.models import (
    IGNORED_SUFFIXES,
    MediaSource,
    STATUS_PENDING,
    detect_source_kind,
    is_supported_media,
    source_id_from_sha256,
)
from media.probe import probe_media
from media.store import MediaJobStore

log = logging.getLogger("media.scanner")


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


@dataclass
class ScanResult:
    created: list[MediaSource]
    skipped_existing: list[str]     # source_ids ya registrados
    ignored_files: list[str]        # rutas ignoradas (no soportadas/temporales)
    dry_run: bool


def iter_candidate_files(staging_dir: Path):
    """Genera rutas de archivos candidatos (soportados, no temporales)."""
    if not staging_dir.is_dir():
        return
    for path in sorted(staging_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in IGNORED_SUFFIXES:
            continue
        if path.name.startswith(".") or path.name.startswith("~"):
            continue
        if not is_supported_media(path.name):
            continue
        yield path


def scan(
    config: MediaConfig,
    workspace: str,
    store: MediaJobStore | None = None,
    dry_run: bool | None = None,
    bridge=None,
) -> ScanResult:
    """Escanea el staging y registra nuevos jobs multimedia."""
    if store is None:
        store = MediaJobStore(config.output_dir)
    if dry_run is None:
        dry_run = config.dry_run

    created: list[MediaSource] = []
    skipped_existing: list[str] = []
    ignored_files: list[str] = []

    staging = config.staging_dir
    if not staging.is_dir():
        log.warning("Directorio de staging no existe: %s", staging)
        return ScanResult(created, skipped_existing, ignored_files, dry_run)

    # Marcar como ignorados los archivos no soportados (para el informe).
    if staging.is_dir():
        for path in sorted(staging.rglob("*")):
            if path.is_file() and not is_supported_media(path.name):
                ignored_files.append(str(path))

    for path in iter_candidate_files(staging):
        kind = detect_source_kind(path.suffix)
        if kind is None:
            ignored_files.append(str(path))
            continue

        sha256 = _sha256_file(path)
        source_id = source_id_from_sha256(sha256)

        if store.exists(workspace, source_id):
            skipped_existing.append(source_id)
            log.info("Ya registrado, se omite: %s (%s)", path.name, source_id)
            continue

        probe = probe_media(path)
        source = MediaSource(
            source_id=source_id,
            source_kind=kind,
            workspace=workspace,
            original_path=str(path),
            original_filename=path.name,
            sha256=sha256,
            size_bytes=path.stat().st_size,
            duration_seconds=probe.duration_seconds,
            media_format=probe.media_format,
            audio_codec=probe.audio_codec,
            video_codec=probe.video_codec,
            status=STATUS_PENDING,
        )

        if dry_run:
            log.info("[dry-run] Crearía job: %s (%s, %s)", path.name, kind, source_id)
        else:
            store.save(source)
            if bridge is not None and getattr(bridge, "enabled", False):
                bridge.register(source)
            log.info("Job creado: %s (%s, %s)", path.name, kind, source_id)

        created.append(source)

    return ScanResult(created, skipped_existing, ignored_files, dry_run)
