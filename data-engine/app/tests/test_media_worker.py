"""Tests del worker multimedia (stub + mocks de ffmpeg/ffprobe, sin Neo4j)."""
from pathlib import Path
from unittest import mock

import pytest

from media.audio_extract import AudioExtractionError
from media.config import MediaConfig
from media.models import (
    MediaSource,
    STATUS_COMPLETE,
    STATUS_FAILED,
    STATUS_PENDING,
)
from media.probe import ProbeResult
from media.store import MediaJobStore
from media.transcriber import StubTranscriber
from media.worker import run_worker


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
        faster_whisper_model="small", faster_whisper_device="cpu",
        faster_whisper_compute_type="int8", jobstore_bridge=False,
    )


def _seed_pending(store: MediaJobStore, tmp_path: Path) -> MediaSource:
    src_file = tmp_path / "staging" / "sesion.mp4"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_bytes(b"fake video")
    source = MediaSource(
        source_id="media_test0001",
        source_kind="video",
        workspace="leyenda",
        original_path=str(src_file),
        original_filename="sesion.mp4",
        sha256="test0001hash",
        size_bytes=10,
        status=STATUS_PENDING,
    )
    store.save(source)
    return source


def _fake_extract(input_path, output_path, max_duration_seconds=None, timeout=None):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(b"RIFFfakewav")
    return Path(output_path)


def test_worker_processes_job_with_stub(tmp_path):
    config = _config(tmp_path)
    store = MediaJobStore(config.output_dir)
    _seed_pending(store, tmp_path)

    with mock.patch("media.worker.probe_media",
                    return_value=ProbeResult(duration_seconds=12.0, audio_codec="aac")), \
         mock.patch("media.worker.extract_audio", side_effect=_fake_extract):
        result = run_worker(config, "leyenda", limit=1,
                            store=store, transcriber=StubTranscriber())

    assert result.processed == ["media_test0001"]
    assert result.failed == []
    done = store.get("leyenda", "media_test0001")
    assert done.status == STATUS_COMPLETE
    assert Path(done.output_markdown).is_file()
    md = Path(done.output_markdown).read_text(encoding="utf-8")
    assert "Preparado para ingesta: no" in md      # no toca Neo4j
    assert done.transcriber_engine == "stub"


def test_worker_marks_failed_on_ffmpeg_error(tmp_path):
    config = _config(tmp_path)
    store = MediaJobStore(config.output_dir)
    _seed_pending(store, tmp_path)

    with mock.patch("media.worker.probe_media", return_value=ProbeResult()), \
         mock.patch("media.worker.extract_audio",
                    side_effect=AudioExtractionError("ffmpeg reventó")):
        result = run_worker(config, "leyenda", limit=1,
                            store=store, transcriber=StubTranscriber())

    assert result.failed == ["media_test0001"]
    failed = store.get("leyenda", "media_test0001")
    assert failed.status == STATUS_FAILED
    assert "ffmpeg" in failed.error_message


def test_worker_dry_run_does_not_change_state(tmp_path):
    config = _config(tmp_path, dry_run=True)
    store = MediaJobStore(config.output_dir)
    _seed_pending(store, tmp_path)

    result = run_worker(config, "leyenda", limit=1, dry_run=True, store=store)

    assert result.processed == []
    assert result.skipped == ["media_test0001"]
    unchanged = store.get("leyenda", "media_test0001")
    assert unchanged.status == STATUS_PENDING   # sigue pendiente
