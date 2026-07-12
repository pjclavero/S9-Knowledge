"""Tests de extracción de audio (mock de subprocess/ffmpeg, sin ffmpeg real)."""
from pathlib import Path
from unittest import mock

import pytest

from media.audio_extract import (
    AudioExtractionError,
    build_ffmpeg_command,
    extract_audio,
)


def test_build_ffmpeg_command_basic():
    cmd = build_ffmpeg_command(Path("in.mp4"), Path("out.wav"))
    assert cmd[0] == "ffmpeg"
    assert "-vn" in cmd
    assert "-ac" in cmd and "1" in cmd
    assert "-ar" in cmd and "16000" in cmd
    assert "-c:a" in cmd and "pcm_s16le" in cmd
    assert cmd[-1] == "out.wav"
    assert "-t" not in cmd  # sin límite de duración


def test_build_ffmpeg_command_with_max_duration():
    cmd = build_ffmpeg_command(Path("in.mp4"), Path("out.wav"), max_duration_seconds=120)
    assert "-t" in cmd
    idx = cmd.index("-t")
    assert cmd[idx + 1] == "00:02:00"


def test_extract_audio_success(tmp_path):
    src = tmp_path / "video.mp4"
    src.write_bytes(b"fake")
    dst = tmp_path / "out" / "audio.wav"

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(cmd[-1]).write_bytes(b"RIFFfakewav")
        return mock.Mock(returncode=0, stderr="")

    with mock.patch("media.audio_extract.ffmpeg_available", return_value=True), \
         mock.patch("media.audio_extract.subprocess.run", side_effect=fake_run):
        out = extract_audio(src, dst)

    assert out == dst
    assert dst.is_file()
    assert src.is_file()  # no borra el original


def test_extract_audio_ffmpeg_failure_raises(tmp_path):
    src = tmp_path / "video.mp4"
    src.write_bytes(b"fake")
    dst = tmp_path / "audio.wav"

    with mock.patch("media.audio_extract.ffmpeg_available", return_value=True), \
         mock.patch("media.audio_extract.subprocess.run",
                    return_value=mock.Mock(returncode=1, stderr="boom")):
        with pytest.raises(AudioExtractionError):
            extract_audio(src, dst)


def test_extract_audio_no_ffmpeg_raises(tmp_path):
    src = tmp_path / "video.mp4"
    src.write_bytes(b"fake")
    with mock.patch("media.audio_extract.ffmpeg_available", return_value=False):
        with pytest.raises(AudioExtractionError):
            extract_audio(src, tmp_path / "out.wav")
