"""Tests del transcriptor stub y de la fábrica de transcriptores."""
from pathlib import Path

import pytest

from media.config import MediaConfig
from media.transcriber import (
    FasterWhisperTranscriber,
    StubTranscriber,
    TranscriberError,
    get_transcriber,
)


def _config(transcriber: str) -> MediaConfig:
    return MediaConfig(
        staging_dir=Path("staging"), output_dir=Path("out"), audio_dir=Path("a"),
        transcript_dir=Path("t"), log_dir=Path("l"), default_workspace="leyenda",
        transcriber=transcriber, language="es", max_duration_seconds=7200, dry_run=False,
        faster_whisper_model="small", faster_whisper_device="cpu",
        faster_whisper_compute_type="int8", jobstore_bridge=False,
    )


def test_stub_transcriber_returns_segments():
    result = StubTranscriber().transcribe(Path("charla.wav"), language="es")
    assert result.engine == "stub"
    assert result.language == "es"
    assert len(result.segments) >= 1
    assert "charla.wav" in result.text
    for seg in result.segments:
        assert seg.end >= seg.start


def test_get_transcriber_defaults_to_stub():
    assert isinstance(get_transcriber(_config("stub")), StubTranscriber)
    assert isinstance(get_transcriber(_config("")), StubTranscriber)


def test_get_transcriber_faster_whisper_lazy():
    # No debe intentar cargar el modelo hasta transcribe(); solo instanciar.
    t = get_transcriber(_config("faster-whisper"))
    assert isinstance(t, FasterWhisperTranscriber)
    assert t.compute_type == "int8"


def test_get_transcriber_unknown_raises():
    with pytest.raises(TranscriberError):
        get_transcriber(_config("motor-inexistente"))


def test_external_transcriber_documented_but_not_implemented():
    with pytest.raises(TranscriberError):
        get_transcriber(_config("external"))
