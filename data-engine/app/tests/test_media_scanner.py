"""Tests del scanner multimedia (con mocks de ffprobe)."""
from pathlib import Path
from unittest import mock

import pytest

from media.config import MediaConfig
from media.models import source_id_from_sha256
from media.probe import ProbeResult
from media.scanner import scan
from media.store import MediaJobStore


def _config(tmp_path: Path, dry_run: bool = False) -> MediaConfig:
    return MediaConfig(
        staging_dir=tmp_path / "staging",
        output_dir=tmp_path / "output" / "media",
        audio_dir=tmp_path / "output" / "audio",
        transcript_dir=tmp_path / "output" / "transcriptions",
        log_dir=tmp_path / "logs",
        default_workspace="leyenda",
        transcriber="stub",
        language="es",
        max_duration_seconds=7200,
        dry_run=dry_run,
        faster_whisper_model="small",
        faster_whisper_device="cpu",
        faster_whisper_compute_type="int8",
        jobstore_bridge=False,
    )


@pytest.fixture
def fake_probe():
    with mock.patch(
        "media.scanner.probe_media",
        return_value=ProbeResult(duration_seconds=42.0, media_format="mov,mp4",
                                 audio_codec="aac", video_codec="h264"),
    ) as m:
        yield m


def test_scanner_detects_mp4_and_ignores_txt(tmp_path, fake_probe):
    config = _config(tmp_path)
    staging = config.staging_dir
    staging.mkdir(parents=True)
    (staging / "sesion4.mp4").write_bytes(b"fake video bytes")
    (staging / "notas.txt").write_text("no soy multimedia")

    store = MediaJobStore(config.output_dir)
    result = scan(config, "leyenda", store=store)

    assert len(result.created) == 1
    assert result.created[0].source_kind == "video"
    assert result.created[0].original_filename == "sesion4.mp4"
    assert any("notas.txt" in p for p in result.ignored_files)


def test_scanner_stable_source_id(tmp_path, fake_probe):
    config = _config(tmp_path)
    staging = config.staging_dir
    staging.mkdir(parents=True)
    content = b"contenido de audio estable"
    (staging / "charla.mp3").write_bytes(content)

    store = MediaJobStore(config.output_dir)
    result = scan(config, "leyenda", store=store)

    import hashlib
    expected = source_id_from_sha256(hashlib.sha256(content).hexdigest())
    assert result.created[0].source_id == expected
    assert result.created[0].source_kind == "audio"


def test_scanner_dedup_skips_existing(tmp_path, fake_probe):
    config = _config(tmp_path)
    staging = config.staging_dir
    staging.mkdir(parents=True)
    (staging / "charla.mp3").write_bytes(b"mismo contenido")

    store = MediaJobStore(config.output_dir)
    first = scan(config, "leyenda", store=store)
    assert len(first.created) == 1

    # Segundo escaneo: mismo archivo, debe omitirse por source_id existente.
    second = scan(config, "leyenda", store=store)
    assert len(second.created) == 0
    assert len(second.skipped_existing) == 1


def test_scanner_dry_run_does_not_persist(tmp_path, fake_probe):
    config = _config(tmp_path, dry_run=True)
    staging = config.staging_dir
    staging.mkdir(parents=True)
    (staging / "video.mkv").write_bytes(b"algo")

    store = MediaJobStore(config.output_dir)
    result = scan(config, "leyenda", store=store, dry_run=True)

    assert len(result.created) == 1          # informa de lo que haría
    assert result.dry_run is True
    assert store.list("leyenda") == []       # pero no persiste nada


def test_scanner_ignores_temp_files(tmp_path, fake_probe):
    config = _config(tmp_path)
    staging = config.staging_dir
    staging.mkdir(parents=True)
    (staging / "descargando.mp4.part").write_bytes(b"parcial")

    store = MediaJobStore(config.output_dir)
    result = scan(config, "leyenda", store=store)
    assert len(result.created) == 0
