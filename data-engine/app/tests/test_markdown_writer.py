"""Tests del generador de Markdown revisable."""
from pathlib import Path

from media.markdown_writer import render_markdown, write_markdown
from media.models import MediaSource, TranscriptResult, TranscriptSegment


def _source() -> MediaSource:
    return MediaSource(
        source_id="media_abc123",
        source_kind="video",
        workspace="leyenda",
        original_path="/staging/sesion4.mp4",
        original_filename="sesion4.mp4",
        sha256="abc123def456",
        size_bytes=1048576,
        duration_seconds=3661.0,
        status="writing_markdown",
    )


def _transcript() -> TranscriptResult:
    return TranscriptResult(
        text="Texto completo de la sesión.",
        segments=[
            TranscriptSegment(start=0.0, end=5.0, text="Primer segmento."),
            TranscriptSegment(start=5.0, end=65.0, text="Segundo segmento."),
        ],
        language="es",
        engine="stub",
        model="stub",
        duration_seconds=65.0,
    )


def test_render_markdown_structure():
    md = render_markdown(_source(), _transcript())
    assert "# Transcripción — sesion4.mp4" in md
    assert "## Metadatos" in md
    assert "- Source ID: media_abc123" in md
    assert "- Source kind: video" in md
    assert "- SHA256: abc123def456" in md
    assert "- Preparado para ingesta: no" in md
    assert "## Transcripción con marcas de tiempo" in md
    assert "[00:00:00] Primer segmento." in md
    assert "[00:00:05] Segundo segmento." in md   # start=5s → 00:00:05
    assert "## Observaciones de calidad" in md
    assert "Revisión humana requerida: sí" in md


def test_render_markdown_duration_hhmmss():
    md = render_markdown(_source(), _transcript())
    assert "- Duración: 01:01:01" in md   # 3661s → 01:01:01


def test_write_markdown_creates_file(tmp_path):
    out = write_markdown(_source(), _transcript(), tmp_path)
    assert out.is_file()
    assert out.name == "media_abc123.md"
    assert out.parent.name == "leyenda"
    assert "# Transcripción" in out.read_text(encoding="utf-8")
