"""Segmentador de transcripciones.

Lee output/transcriptions/<workspace>/<source_id>.md y divide la transcripción
en bloques de 3-5 minutos conservando timestamps y segment_id estables.

Formato de entrada esperado:
  [HH:MM:SS] texto de la línea
"""
from __future__ import annotations
import json
import logging
import re
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review.models import Segment

log = logging.getLogger(__name__)

TS_RE = re.compile(r'^\[(\d{2}):(\d{2}):(\d{2})\]')
SEGMENT_DURATION_SEC = 240  # 4 minutos por defecto (3-5 min range)


def _ts_to_seconds(hh: str, mm: str, ss: str) -> int:
    return int(hh) * 3600 + int(mm) * 60 + int(ss)


def _seconds_to_ts(total: int) -> str:
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _detect_metadata(md_path: Path) -> dict:
    """Extrae metadatos del encabezado del fichero markdown."""
    meta = {}
    with md_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if line.startswith("- Source ID:"):
                meta["source_id"] = line.split(":", 1)[1].strip()
            elif line.startswith("- Source kind:"):
                meta["source_kind"] = line.split(":", 1)[1].strip()
            elif line.startswith("- Workspace:"):
                meta["workspace"] = line.split(":", 1)[1].strip()
            elif line.startswith("[") or line.startswith("**["):
                break  # Inicio de transcripción
    return meta


def segment_transcript(
    workspace: str,
    source_id: str,
    repo_root: Path,
    segment_duration_sec: int = SEGMENT_DURATION_SEC,
) -> list[Segment]:
    """Segmenta la transcripción y devuelve lista de Segment."""
    md_path = repo_root / "output" / "transcriptions" / workspace / f"{source_id}.md"
    if not md_path.exists():
        raise FileNotFoundError(f"Transcripción no encontrada: {md_path}")

    meta = _detect_metadata(md_path)
    src_kind = meta.get("source_kind", "audio")
    ws = meta.get("workspace", workspace)

    # Leer todas las líneas de transcripción (con timestamp)
    ts_lines: list[tuple[int, str]] = []  # (seconds, full_line)
    with md_path.open(encoding="utf-8") as f:
        in_transcript = False
        for line in f:
            line_s = line.rstrip()
            if line_s.startswith("## Transcripción"):
                in_transcript = True
                continue
            if not in_transcript:
                continue
            m = TS_RE.match(line_s)
            if m:
                secs = _ts_to_seconds(m.group(1), m.group(2), m.group(3))
                ts_lines.append((secs, line_s))

    if not ts_lines:
        log.warning("No se encontraron líneas con timestamp en %s", md_path)
        return []

    # Dividir en bloques de segment_duration_sec
    segments: list[Segment] = []
    block_start_sec = ts_lines[0][0]
    block_lines: list[str] = []
    seg_num = 1

    def _flush_block(lines: list[str], start_sec: int, end_sec: int) -> Segment:
        nonlocal seg_num
        seg_id = f"{source_id}_seg_{seg_num:04d}"
        text = " ".join(
            TS_RE.sub("", l).strip() for l in lines if TS_RE.sub("", l).strip()
        )
        s = Segment(
            segment_id=seg_id,
            source_id=source_id,
            source_kind=src_kind,
            workspace=ws,
            timestamp_start=_seconds_to_ts(start_sec),
            timestamp_end=_seconds_to_ts(end_sec),
            text=text,
            lines=lines,
        )
        seg_num += 1
        return s

    for i, (secs, line) in enumerate(ts_lines):
        block_lines.append(line)
        is_last = i == len(ts_lines) - 1
        elapsed = secs - block_start_sec

        if elapsed >= segment_duration_sec or is_last:
            end_sec = secs
            seg = _flush_block(block_lines, block_start_sec, end_sec)
            segments.append(seg)
            block_lines = []
            block_start_sec = secs

    log.info("Segmentación: %d segmentos de %s", len(segments), source_id)
    return segments


def run(workspace: str, source_id: str, repo_root: Path) -> Path:
    """Entry point: segmenta y guarda segments.json."""
    segments = segment_transcript(workspace, source_id, repo_root)
    out_dir = repo_root / "output" / "reviews" / workspace / source_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "segments.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump([s.to_dict() for s in segments], f, ensure_ascii=False, indent=2)
    log.info("segments.json → %s (%d segmentos)", out_path, len(segments))
    return out_path
