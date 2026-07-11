"""
YouTube transcription module for property-graph knowledge pipeline.

Flow:
  URL → metadata → subtitles (if available) → audio download + whisper (fallback)
       → Markdown → SilverBullet → optional RPG extraction
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

# Allow running from repo root or installed
_HERE = Path(__file__).parent
_APP_DIR = _HERE.parent
sys.path.insert(0, str(_APP_DIR.parent))

from app.youtube.youtube_utils import (
    validate_youtube_url,
    extract_video_id,
    get_video_info,
    fetch_subtitles,
    download_audio,
    parse_vtt_to_text,
    sanitize_filename,
)

logger = logging.getLogger("property-graph-youtube")

# Exit codes
EXIT_OK = 0
EXIT_INPUT_ERROR = 1
EXIT_DOWNLOAD_ERROR = 2
EXIT_TRANSCRIPTION_ERROR = 3
EXIT_OUTPUT_ERROR = 4
EXIT_SKIPPED = 64
EXIT_PLAYLIST = 65


# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG_PATH = Path("/opt/knowledge-services/property-graph/config/settings.yaml")


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


# ── State ─────────────────────────────────────────────────────────────────────

def _state_path(state_dir: Path, url: str) -> Path:
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    return state_dir / f"youtube_{url_hash}.json"


def load_state(state_dir: Path, url: str) -> Optional[dict]:
    p = _state_path(state_dir, url)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return None


def save_state(state_dir: Path, url: str, record: dict) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    p = _state_path(state_dir, url)
    with open(p, "w") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)


# ── Whisper transcription ─────────────────────────────────────────────────────

def transcribe_with_whisper(audio_path: Path, language: str, config: dict) -> str:
    """Transcribe audio file using faster-whisper. Returns plain text."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("faster-whisper not installed in venv")

    audio_cfg = config.get("audio", {})
    model_name = audio_cfg.get("model", "small")
    device = audio_cfg.get("device", "cpu")
    compute_type = audio_cfg.get("compute_type", "int8")
    beam_size = audio_cfg.get("beam_size", 5)
    vad_filter = audio_cfg.get("vad_filter", True)

    logger.info(f"Loading Whisper model '{model_name}' on {device}/{compute_type}")
    model = WhisperModel(model_name, device=device, compute_type=compute_type)

    logger.info(f"Transcribing {audio_path.name} ...")
    segments, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=beam_size,
        vad_filter=vad_filter,
    )
    texts = [seg.text.strip() for seg in segments if seg.text.strip()]
    return "\n".join(texts)


# ── Markdown generation ───────────────────────────────────────────────────────

def generate_markdown(
    url: str,
    title: str,
    language: str,
    workspace: str,
    transcript_text: str,
    source_method: str,
    video_id: str,
    channel: str = "",
    duration_seconds: float = 0,
    upload_date: str = "",
) -> str:
    now = datetime.now(timezone.utc).isoformat()
    duration_str = ""
    if duration_seconds:
        m, s = divmod(int(duration_seconds), 60)
        h, m = divmod(m, 60)
        duration_str = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    header = f"""---
generated_by: property-graph-youtube
workspace: {workspace}
source_type: youtube
source_url: "{url}"
video_id: "{video_id}"
title: "{title}"
language: {language}
source_method: {source_method}
status: draft_needs_review
reviewed: false
created_at: {now}
---

# {title}

> Transcripción automática desde YouTube. Revisar antes de usar como canon.

## Fuente

- URL: {url}
- Canal: {channel}
- Duración: {duration_str}
- Fecha de subida: {upload_date}
- Método: {source_method}

## Transcripción

"""
    return header + transcript_text + "\n"


# ── SilverBullet export ───────────────────────────────────────────────────────

def export_to_silverbullet(
    workspace: str,
    video_id: str,
    title: str,
    markdown: str,
    force: bool = False,
) -> Path:
    spaces_base = Path("/opt/knowledge-services/spaces")
    out_dir = spaces_base / workspace / "Transcripciones" / "Youtube"
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_title = sanitize_filename(title)
    filename = f"{video_id}_{safe_title}.md"
    out_path = out_dir / filename

    if out_path.exists() and not force:
        raise FileExistsError(
            f"Markdown already exists: {out_path}. Use --force to overwrite."
        )

    out_path.write_text(markdown, encoding="utf-8")
    logger.info(f"Exported to SilverBullet: {out_path}")
    return out_path


# ── RPG extraction ────────────────────────────────────────────────────────────

def run_rpg_extraction(workspace: str, markdown_path: Path) -> int:
    cmd = [
        "property-graph-rpg",
        "--workspace", workspace,
        "--text", str(markdown_path),
        "--profile", "transcript",
    ]
    logger.info(f"Running RPG extraction: {' '.join(cmd)}")
    result = subprocess.run(cmd, timeout=3600)
    return result.returncode


# ── Main pipeline ─────────────────────────────────────────────────────────────

def process_youtube(args: argparse.Namespace, config: dict) -> int:
    url = args.url.strip()

    # Validate URL
    try:
        url = validate_youtube_url(url)
        video_id = extract_video_id(url)
    except ValueError as e:
        logger.error(str(e))
        return EXIT_INPUT_ERROR

    # State check
    audio_cfg = config.get("audio", {})
    state_dir = Path(audio_cfg.get("state_dir", "/opt/knowledge-services/property-graph/state/audio"))
    state = load_state(state_dir, url)
    if state and state.get("status") == "ok" and not args.force:
        logger.info(f"Already processed (use --force to redo): {url}")
        logger.info(f"  Output: {state.get('output_markdown')}")
        return EXIT_SKIPPED

    # yt-dlp binary
    venv_bin = Path("/opt/knowledge-services/property-graph/.venv/bin")
    yt_dlp_bin = str(venv_bin / "yt-dlp") if (venv_bin / "yt-dlp").exists() else "yt-dlp"

    # Get metadata
    logger.info(f"Fetching metadata for {url}")
    try:
        info = get_video_info(url, yt_dlp_bin)
    except Exception as e:
        logger.error(f"Cannot get video info: {e}")
        return EXIT_DOWNLOAD_ERROR

    title = args.title or info.get("title", video_id)
    language = args.language
    channel = info.get("channel", info.get("uploader", ""))
    duration_seconds = info.get("duration", 0)
    upload_date = info.get("upload_date", "")
    if upload_date and len(upload_date) == 8:
        upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"

    logger.info(f"Title: {title}")
    logger.info(f"Duration: {duration_seconds}s | Channel: {channel}")

    # Staging dir
    staging_base = Path(audio_cfg.get("staging_dir", "/tmp/property-graph-staging"))
    staging_dir = staging_base / f"youtube_{video_id}"
    staging_dir.mkdir(parents=True, exist_ok=True)

    transcript_text = None
    source_method = "unknown"
    staging_cleanup = not args.keep_staging

    try:
        # Try subtitles first (unless --force-whisper)
        if not args.force_whisper and args.prefer_captions:
            logger.info("Attempting to fetch subtitles ...")
            try:
                subtitle_path = fetch_subtitles(url, language, staging_dir, yt_dlp_bin)
                if subtitle_path:
                    logger.info(f"Subtitles found: {subtitle_path.name}")
                    transcript_text = parse_vtt_to_text(subtitle_path)
                    source_method = "subtitles"
                else:
                    logger.info("No subtitles available, will download audio")
            except Exception as e:
                logger.warning(f"Subtitle fetch failed: {e} — falling back to audio")

        # Fallback: download audio + whisper
        if transcript_text is None:
            logger.info("Downloading audio ...")
            try:
                audio_path = download_audio(url, staging_dir, yt_dlp_bin)
            except Exception as e:
                logger.error(f"Audio download failed: {e}")
                if not args.keep_staging:
                    shutil.rmtree(staging_dir, ignore_errors=True)
                return EXIT_DOWNLOAD_ERROR

            logger.info(f"Audio saved: {audio_path}")
            try:
                transcript_text = transcribe_with_whisper(audio_path, language, config)
                source_method = "whisper"
            except Exception as e:
                logger.error(f"Whisper transcription failed: {e}")
                if not args.keep_staging:
                    shutil.rmtree(staging_dir, ignore_errors=True)
                return EXIT_TRANSCRIPTION_ERROR

        if not transcript_text:
            logger.error("Empty transcript — aborting")
            return EXIT_TRANSCRIPTION_ERROR

        logger.info(f"Transcript obtained ({len(transcript_text)} chars, method={source_method})")

        # Generate Markdown
        markdown = generate_markdown(
            url=url,
            title=title,
            language=language,
            workspace=args.workspace,
            transcript_text=transcript_text,
            source_method=source_method,
            video_id=video_id,
            channel=channel,
            duration_seconds=duration_seconds,
            upload_date=upload_date,
        )

        # Export to SilverBullet
        if args.export_markdown:
            try:
                md_path = export_to_silverbullet(
                    workspace=args.workspace,
                    video_id=video_id,
                    title=title,
                    markdown=markdown,
                    force=args.force,
                )
            except FileExistsError as e:
                logger.error(str(e))
                return EXIT_OUTPUT_ERROR
            except Exception as e:
                logger.error(f"SilverBullet export failed: {e}")
                return EXIT_OUTPUT_ERROR
        else:
            # Write to a temp location for RPG extraction if needed
            tmp_md = staging_dir / f"{video_id}.md"
            tmp_md.write_text(markdown, encoding="utf-8")
            md_path = tmp_md

        # Export JSON
        if args.export_json:
            json_path = md_path.with_suffix(".json")
            record = {
                "url": url,
                "video_id": video_id,
                "title": title,
                "language": language,
                "workspace": args.workspace,
                "source_method": source_method,
                "channel": channel,
                "duration_seconds": duration_seconds,
                "upload_date": upload_date,
                "transcript": transcript_text,
            }
            json_path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
            logger.info(f"JSON exported: {json_path}")

        # Export TXT
        if args.export_txt:
            txt_path = md_path.with_suffix(".txt")
            txt_path.write_text(transcript_text, encoding="utf-8")
            logger.info(f"TXT exported: {txt_path}")

        # Save state
        state_record = {
            "url": url,
            "video_id": video_id,
            "title": title,
            "workspace": args.workspace,
            "status": "ok",
            "source_method": source_method,
            "output_markdown": str(md_path),
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        save_state(state_dir, url, state_record)

        # Cleanup staging
        if staging_cleanup:
            shutil.rmtree(staging_dir, ignore_errors=True)
            logger.info("Staging dir cleaned up")

        # Optional RPG extraction
        if args.extract_rpg:
            rc = run_rpg_extraction(args.workspace, md_path)
            if rc != 0:
                logger.warning(f"RPG extraction returned code {rc}")

        logger.info(f"Done. Output: {md_path}")
        return EXIT_OK

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        if not args.keep_staging:
            shutil.rmtree(staging_dir, ignore_errors=True)
        save_state(state_dir, url, {
            "url": url,
            "video_id": video_id,
            "title": args.title or video_id,
            "workspace": args.workspace,
            "status": "error",
            "error": str(e),
            "processed_at": datetime.now(timezone.utc).isoformat(),
        })
        return EXIT_TRANSCRIPTION_ERROR


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="property-graph-youtube",
        description="Transcribe a YouTube video and export to SilverBullet.",
    )
    parser.add_argument("--workspace", required=True, help="SilverBullet workspace name")
    parser.add_argument("--url", required=True, help="YouTube video URL (single video only)")
    parser.add_argument("--title", help="Override video title")
    parser.add_argument("--language", default="es", help="Language code (default: es)")
    parser.add_argument(
        "--prefer-captions",
        action="store_true",
        default=True,
        help="Use subtitles/captions if available (default: True)",
    )
    parser.add_argument(
        "--force-whisper",
        action="store_true",
        help="Always use Whisper even if captions available",
    )
    parser.add_argument("--export-json", action="store_true", help="Export JSON metadata")
    parser.add_argument("--export-txt", action="store_true", help="Export plain text transcript")
    parser.add_argument("--export-markdown", action="store_true", help="Export Markdown to SilverBullet")
    parser.add_argument("--extract-rpg", action="store_true", help="Run RPG entity extraction after transcription")
    parser.add_argument("--keep-staging", action="store_true", help="Keep staging files after processing")
    parser.add_argument("--force", action="store_true", help="Re-process even if already done; overwrite existing output")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to settings.yaml",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    config = load_config(Path(args.config))
    sys.exit(process_youtube(args, config))


if __name__ == "__main__":
    main()
