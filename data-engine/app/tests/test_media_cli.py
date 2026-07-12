"""Tests de la CLI multimedia (scan/list/worker/show) end-to-end con stub."""
from pathlib import Path
from unittest import mock

import pytest

from cli import media_jobs
from media.probe import ProbeResult


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("S9K_MEDIA_STAGING_DIR", str(tmp_path / "staging"))
    monkeypatch.setenv("S9K_MEDIA_OUTPUT_DIR", str(tmp_path / "output" / "media"))
    monkeypatch.setenv("S9K_MEDIA_AUDIO_DIR", str(tmp_path / "output" / "audio"))
    monkeypatch.setenv("S9K_MEDIA_TRANSCRIPT_DIR", str(tmp_path / "output" / "transcriptions"))
    monkeypatch.setenv("S9K_MEDIA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("S9K_MEDIA_TRANSCRIBER", "stub")
    monkeypatch.setenv("S9K_MEDIA_JOBSTORE_BRIDGE", "false")
    staging = tmp_path / "staging"
    staging.mkdir(parents=True)
    (staging / "sesion.mp3").write_bytes(b"contenido de audio para la cli")
    return tmp_path


def test_cli_scan_then_list(env, capsys):
    with mock.patch("media.scanner.probe_media",
                    return_value=ProbeResult(duration_seconds=30.0, audio_codec="mp3")):
        rc = media_jobs.main(["scan", "--workspace", "leyenda"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Nuevos jobs: 1" in out

    rc = media_jobs.main(["list", "--workspace", "leyenda"])
    assert rc == 0
    assert "leyenda" in capsys.readouterr().out


def test_cli_scan_dry_run_does_not_persist(env, capsys):
    with mock.patch("media.scanner.probe_media", return_value=ProbeResult()):
        rc = media_jobs.main(["scan", "--workspace", "leyenda", "--dry-run"])
    assert rc == 0
    assert "[dry-run]" in capsys.readouterr().out

    # list debe mostrar 0 porque el dry-run no persistió
    media_jobs.main(["list", "--workspace", "leyenda"])
    assert "0" in capsys.readouterr().out


def test_cli_worker_processes_with_stub(env, capsys):
    def fake_extract(input_path, output_path, max_duration_seconds=None, timeout=None):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"RIFFwav")
        return Path(output_path)

    with mock.patch("media.scanner.probe_media",
                    return_value=ProbeResult(duration_seconds=30.0, audio_codec="mp3")):
        media_jobs.main(["scan", "--workspace", "leyenda"])
    capsys.readouterr()

    with mock.patch("media.worker.probe_media",
                    return_value=ProbeResult(duration_seconds=30.0, audio_codec="mp3")), \
         mock.patch("media.worker.extract_audio", side_effect=fake_extract):
        rc = media_jobs.main(["worker", "--workspace", "leyenda", "--limit", "1"])
    assert rc == 0
    assert "Procesados: 1" in capsys.readouterr().out
