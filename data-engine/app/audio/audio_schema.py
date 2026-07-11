from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    speaker: Optional[str] = None
    confidence: Optional[float] = None


class TranscriptDocument(BaseModel):
    source_path: str
    workspace: str
    language: str = "es"
    duration_seconds: Optional[float] = None
    model: str = "small"
    segments: list[TranscriptSegment] = Field(default_factory=list)
    full_text: str = ""
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_markdown(self) -> str:
        lines = [f"# Transcripción: {Path(self.source_path).name}", ""]
        lines.append(f"**Idioma:** {self.language}")
        if self.duration_seconds:
            mins = int(self.duration_seconds // 60)
            secs = int(self.duration_seconds % 60)
            lines.append(f"**Duración:** {mins}m {secs}s")
        lines.append(f"**Modelo:** {self.model}")
        lines.append(f"**Fecha:** {self.created_at[:19].replace('T', ' ')} UTC")
        lines.append("")
        if self.segments:
            lines.append("## Segmentos")
            lines.append("")
            current_speaker = None
            for seg in self.segments:
                spk = seg.speaker or "Narrador"
                if spk != current_speaker:
                    current_speaker = spk
                    lines.append(f"**{spk}:**")
                ts = f"[{int(seg.start//60):02d}:{int(seg.start%60):02d}]"
                lines.append(f"{ts} {seg.text.strip()}")
            lines.append("")
        lines.append("## Texto completo")
        lines.append("")
        lines.append(self.full_text)
        return "\n".join(lines)


class AudioStateRecord(BaseModel):
    source_path: str
    sha256: str
    workspace: str
    status: str
    processed_at: Optional[str] = None
    output_markdown: Optional[str] = None
    output_json: Optional[str] = None
    duration_seconds: Optional[float] = None
    segments_count: int = 0
    word_count: int = 0
    error: Optional[str] = None
