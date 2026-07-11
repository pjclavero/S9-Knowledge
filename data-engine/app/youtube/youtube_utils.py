"""Utilities for YouTube URL handling and yt-dlp integration."""
from __future__ import annotations

import re
import subprocess
import json
import shutil
import tempfile
from pathlib import Path
from typing import Optional

SUPPORTED_DOMAINS = ("youtube.com", "youtu.be", "www.youtube.com", "m.youtube.com")

PLAYLIST_PATTERNS = [
    r"[&?]list=",
    r"/playlist\?",
]


def validate_youtube_url(url: str) -> str:
    """Validate URL is a single YouTube video. Returns canonical URL."""
    for pattern in PLAYLIST_PATTERNS:
        if re.search(pattern, url):
            raise ValueError(f"Playlists not supported: {url}")
    
    # Accept youtu.be short links and youtube.com/watch
    if not any(domain in url for domain in SUPPORTED_DOMAINS):
        raise ValueError(f"Not a YouTube URL: {url}")
    
    if "youtu.be/" not in url and "watch?v=" not in url and "shorts/" not in url:
        raise ValueError(f"Cannot determine video ID from URL: {url}")
    
    return url


def extract_video_id(url: str) -> str:
    """Extract video ID from YouTube URL."""
    # youtu.be/XXXX
    m = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    # watch?v=XXXX
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    # shorts/XXXX
    m = re.search(r"shorts/([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    raise ValueError(f"Cannot extract video ID from: {url}")


def get_video_info(url: str, yt_dlp_bin: str = "yt-dlp") -> dict:
    """Get video metadata without downloading."""
    cmd = [
        yt_dlp_bin,
        "--dump-json",
        "--no-playlist",
        "--skip-download",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp metadata failed: {result.stderr[:500]}")
    return json.loads(result.stdout)


def fetch_subtitles(
    url: str,
    language: str,
    staging_dir: Path,
    yt_dlp_bin: str = "yt-dlp",
) -> Optional[Path]:
    """
    Try to download auto-generated or manual subtitles.
    Returns path to .vtt/.srt file, or None if unavailable.
    """
    out_template = str(staging_dir / "subtitle")
    cmd = [
        yt_dlp_bin,
        "--write-auto-subs",
        "--write-subs",
        "--sub-lang", language,
        "--sub-format", "vtt/srt/best",
        "--skip-download",
        "--no-playlist",
        "-o", out_template,
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    # yt-dlp writes subtitle files with name pattern: subtitle.<lang>.vtt
    for ext in (".vtt", ".srt"):
        candidates = list(staging_dir.glob(f"subtitle*.{ext[1:]}"))
        if candidates:
            return candidates[0]
    return None


def download_audio(
    url: str,
    staging_dir: Path,
    yt_dlp_bin: str = "yt-dlp",
    max_minutes: int = 120,
) -> Path:
    """
    Download audio-only stream to staging dir.
    Returns path to audio file.
    """
    out_template = str(staging_dir / "audio.%(ext)s")
    cmd = [
        yt_dlp_bin,
        "--extract-audio",
        "--audio-format", "m4a",
        "--audio-quality", "3",
        "--no-playlist",
        "--match-filter", f"duration < {max_minutes * 60}",
        "-o", out_template,
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp audio download failed: {result.stderr[:500]}")
    candidates = list(staging_dir.glob("audio.*"))
    if not candidates:
        raise RuntimeError("yt-dlp completed but no audio file found")
    return candidates[0]


def parse_vtt_to_text(vtt_path: Path) -> str:
    """Parse VTT subtitle file to plain text."""
    lines = vtt_path.read_text(encoding="utf-8").splitlines()
    texts = []
    skip_header = True
    for line in lines:
        line = line.strip()
        if skip_header:
            if line == "" or line.startswith("WEBVTT"):
                continue
            skip_header = False
        # Skip timestamp lines
        if re.match(r"^\d{2}:\d{2}", line) or re.match(r"^NOTE", line):
            continue
        # Skip cue identifiers (pure numbers)
        if re.match(r"^\d+$", line):
            continue
        # Strip HTML tags
        line = re.sub(r"<[^>]+>", "", line)
        if line:
            texts.append(line)
    # Deduplicate consecutive identical lines (common in auto-subs)
    deduped = []
    prev = None
    for t in texts:
        if t != prev:
            deduped.append(t)
        prev = t
    return "\n".join(deduped)


def sanitize_filename(name: str, max_len: int = 80) -> str:
    """Sanitize string for use as a filename."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name[:max_len]
