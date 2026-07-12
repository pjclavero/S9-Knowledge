"""Generación del Markdown revisable a partir de una fuente + transcripción.

El Markdown es la salida principal de esta fase: una fuente revisable por un
humano, explícitamente marcada como NO preparada para ingesta al grafo.
"""
from __future__ import annotations

import logging
from pathlib import Path

from media.models import MediaSource, TranscriptResult, format_timestamp, now_iso

log = logging.getLogger("media.markdown_writer")


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _human_duration(seconds: float | None) -> str:
    if not seconds:
        return "desconocida"
    return format_timestamp(seconds)


def render_markdown(source: MediaSource, transcript: TranscriptResult) -> str:
    lines: list[str] = []
    lines.append(f"# Transcripción — {source.original_filename}")
    lines.append("")
    lines.append("## Metadatos")
    lines.append("")
    lines.append(f"- Source ID: {source.source_id}")
    lines.append(f"- Source kind: {source.source_kind}")
    lines.append(f"- Workspace: {source.workspace}")
    lines.append(f"- Archivo original: {source.original_filename}")
    lines.append(f"- SHA256: {source.sha256}")
    lines.append(f"- Tamaño: {_human_size(source.size_bytes)}")
    lines.append(f"- Duración: {_human_duration(source.duration_seconds)}")
    lines.append(f"- Fecha de procesado: {now_iso()}")
    lines.append(f"- Motor: {transcript.engine}")
    lines.append(f"- Modelo: {transcript.model or '—'}")
    lines.append(f"- Idioma: {transcript.language}")
    lines.append(f"- Estado: {source.status}")
    lines.append("- Preparado para ingesta: no")
    lines.append("")
    lines.append("## Resumen rápido")
    lines.append("")
    lines.append("Pendiente de resumen automático.")
    lines.append("")
    lines.append("## Transcripción con marcas de tiempo")
    lines.append("")
    if transcript.segments:
        for seg in transcript.segments:
            lines.append(f"[{format_timestamp(seg.start)}] {seg.text}")
    else:
        lines.append(f"[{format_timestamp(0)}] {transcript.text}")
    lines.append("")
    lines.append("## Observaciones de calidad")
    lines.append("")
    lines.append("- Ruido:")
    lines.append("- Cortes:")
    lines.append("- Varias voces:")
    lines.append("- Música:")
    lines.append("- Confianza aproximada:")
    lines.append("- Revisión humana requerida: sí")
    lines.append("")
    return "\n".join(lines)


def write_markdown(
    source: MediaSource,
    transcript: TranscriptResult,
    transcript_dir: Path,
) -> Path:
    """Escribe output/transcriptions/<workspace>/<source_id>.md y devuelve la ruta."""
    out_dir = Path(transcript_dir) / source.workspace
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{source.source_id}.md"
    out_path.write_text(render_markdown(source, transcript), encoding="utf-8")
    log.info("Markdown escrito: %s", out_path)
    return out_path
