#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Setup path
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "app"))

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML no instalado", file=sys.stderr)
    sys.exit(1)

from audio.audio_schema import AudioStateRecord, TranscriptDocument, TranscriptSegment
from audio.audio_utils import (
    SUPPORTED_EXTENSIONS, convert_to_wav, detect_speakers_simple,
    get_audio_duration, sha256_file, validate_audio_path,
)

log = logging.getLogger("audio")

EXIT_OK = 0
EXIT_INPUT_ERROR = 1
EXIT_TRANSCRIPTION_ERROR = 2
EXIT_OUTPUT_ERROR = 3
EXIT_SKIPPED = 64
EXIT_TOO_LARGE = 65


def load_config(config_path: Path) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def setup_logging(log_dir: Path, workspace: str) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d")
    log_file = log_dir / f"audio_{workspace}_{ts}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )


def load_state(state_dir: Path, sha256: str) -> dict | None:
    state_file = state_dir / f"{sha256}.json"
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except Exception:
            return None
    return None


def save_state(state_dir: Path, record: AudioStateRecord) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / f"{record.sha256}.json"
    state_file.write_text(record.model_dump_json(indent=2))


def transcribe_file(audio_path: Path, config: dict, args) -> int:
    audio_cfg = config.get("audio", {})
    state_dir = Path(audio_cfg.get("state_dir", "/opt/knowledge-services/property-graph/state/audio"))
    output_dir = Path(audio_cfg.get("output_dir", "/opt/knowledge-services/property-graph/output/audio"))
    staging_dir = Path(audio_cfg.get("staging_dir", "/opt/knowledge-services/property-graph/staging/audio"))
    log_dir = Path(audio_cfg.get("log_dir", "/opt/knowledge-services/property-graph/logs/audio"))

    setup_logging(log_dir, args.workspace)

    try:
        max_mb = audio_cfg.get("max_audio_mb", 500)
        validate_audio_path(audio_path, max_mb=max_mb)
    except (FileNotFoundError, ValueError) as e:
        log.error("Error de validación: %s", e)
        return EXIT_INPUT_ERROR

    file_hash = sha256_file(audio_path)

    if not getattr(args, "force", False):
        existing = load_state(state_dir, file_hash)
        if existing and existing.get("status") == "success":
            log.info("Ya procesado (sha256=%s). Usa --force para reprocesar.", file_hash[:12])
            return EXIT_SKIPPED

    # Copiar a staging
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_copy = staging_dir / audio_path.name
    try:
        shutil.copy2(audio_path, staging_copy)
    except Exception:
        shutil.copy(audio_path, staging_copy)

    record = AudioStateRecord(
        source_path=str(audio_path),
        sha256=file_hash,
        workspace=args.workspace,
        status="processing",
        duration_seconds=get_audio_duration(staging_copy),
    )
    save_state(state_dir, record)

    try:
        # Convertir a WAV mono 16kHz
        wav_path = staging_dir / f"{file_hash}_16k.wav"
        log.info("Convirtiendo a WAV: %s", audio_path.name)
        convert_to_wav(staging_copy, wav_path)

        # Cargar faster-whisper
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            log.error("faster-whisper no instalado. Instala con: pip install faster-whisper")
            record.status = "error"
            record.error = "faster-whisper not installed"
            save_state(state_dir, record)
            return EXIT_TRANSCRIPTION_ERROR

        model_size = audio_cfg.get("model", "small")
        device = audio_cfg.get("device", "cpu")
        compute_type = audio_cfg.get("compute_type", "int8")
        language = audio_cfg.get("language", "es")
        vad_filter = audio_cfg.get("vad_filter", True)
        beam_size = audio_cfg.get("beam_size", 5)

        log.info("Cargando modelo %s en %s (%s)...", model_size, device, compute_type)
        model = WhisperModel(model_size, device=device, compute_type=compute_type)

        log.info("Transcribiendo %s...", audio_path.name)
        segments_iter, info = model.transcribe(
            str(wav_path),
            language=language,
            vad_filter=vad_filter,
            beam_size=beam_size,
            task=audio_cfg.get("task", "transcribe"),
        )
        raw_segments = list(segments_iter)
        log.info("Transcripción completada: %d segmentos, idioma detectado: %s",
                 len(raw_segments), info.language)

        # Detección de hablantes (heurística)
        profile = getattr(args, "profile", "transcript")
        if profile == "transcript":
            enriched = detect_speakers_simple(raw_segments)
        else:
            enriched = [{"start": s.start, "end": s.end, "text": s.text, "speaker": None}
                        for s in raw_segments]

        transcript_segs = [TranscriptSegment(**s) for s in enriched]
        full_text = " ".join(s["text"].strip() for s in enriched)

        doc = TranscriptDocument(
            source_path=str(audio_path),
            workspace=args.workspace,
            language=info.language,
            duration_seconds=info.duration,
            model=model_size,
            segments=transcript_segs,
            full_text=full_text,
        )

        # Guardar salidas
        output_dir.mkdir(parents=True, exist_ok=True)
        base_name = audio_path.stem

        md_path = output_dir / f"{base_name}.md"
        md_path.write_text(doc.to_markdown(), encoding="utf-8")
        log.info("Markdown guardado: %s", md_path)

        json_path = output_dir / f"{base_name}.json"
        json_path.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
        log.info("JSON guardado: %s", json_path)

        # Copiar a espacio SilverBullet si está configurado
        spaces = audio_cfg.get("spaces", {})
        sb_dir = spaces.get(args.workspace)
        if sb_dir:
            sb_path = Path(sb_dir)
            sb_path.mkdir(parents=True, exist_ok=True)
            sb_file = sb_path / f"{base_name}.md"
            shutil.copy2(md_path, sb_file)
            log.info("Exportado a SilverBullet: %s", sb_file)

        # Actualizar estado
        record.status = "success"
        record.processed_at = datetime.now(timezone.utc).isoformat()
        record.output_markdown = str(md_path)
        record.output_json = str(json_path)
        record.duration_seconds = info.duration
        record.segments_count = len(transcript_segs)
        record.word_count = len(full_text.split())
        save_state(state_dir, record)

        # Limpiar staging
        if audio_cfg.get("delete_staging_on_success", True):
            try:
                staging_copy.unlink(missing_ok=True)
                wav_path.unlink(missing_ok=True)
            except Exception:
                pass

        log.info("OK: %s — %d seg, %d palabras", audio_path.name,
                 len(transcript_segs), record.word_count)
        return EXIT_OK

    except Exception as e:
        log.error("Error transcribiendo %s: %s", audio_path.name, e, exc_info=True)
        record.status = "error"
        record.error = str(e)[:500]
        record.processed_at = datetime.now(timezone.utc).isoformat()
        save_state(state_dir, record)
        if not audio_cfg.get("retain_staging_on_error", True):
            try:
                staging_copy.unlink(missing_ok=True)
            except Exception:
                pass
        return EXIT_TRANSCRIPTION_ERROR


def cmd_transcribe(argv=None):
    p = argparse.ArgumentParser(description="Transcribir audio con faster-whisper")
    p.add_argument("--audio", required=True, help="Ruta al archivo de audio")
    p.add_argument("--workspace", required=True, help="Workspace (leyenda, mundo_tinieblas…)")
    p.add_argument("--profile", choices=["transcript", "short"], default="transcript")
    p.add_argument("--force", action="store_true", help="Reprocesar aunque ya exista")
    p.add_argument("--config", default="/opt/knowledge-services/property-graph/config/settings.yaml")
    args = p.parse_args(argv)

    config = load_config(Path(args.config))
    audio_path = Path(args.audio)
    return transcribe_file(audio_path, config, args)


def cmd_scan(argv=None):
    p = argparse.ArgumentParser(description="Escanear directorio Nextcloud de audio")
    p.add_argument("--workspace", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--config", default="/opt/knowledge-services/property-graph/config/settings.yaml")
    args = p.parse_args(argv)

    config = load_config(Path(args.config))
    audio_cfg = config.get("audio", {})
    spaces_cfg = audio_cfg.get("spaces", {})
    state_dir = Path(audio_cfg.get("state_dir", "/opt/knowledge-services/property-graph/state/audio"))

    # Buscar archivos de audio en Nextcloud para el workspace
    nextcloud_base = Path("/mnt/nextcloud-rol")
    workspace_dir = nextcloud_base / args.workspace
    if not workspace_dir.exists():
        print(f"ERROR: Directorio Nextcloud no encontrado: {workspace_dir}", file=sys.stderr)
        sys.exit(1)

    found = []
    for ext in SUPPORTED_EXTENSIONS:
        found.extend(workspace_dir.rglob(f"*{ext}"))

    if not found:
        print(f"No se encontraron audios en {workspace_dir}")
        return 0

    print(f"Encontrados {len(found)} archivos de audio:")
    pending = []
    for f in sorted(found, key=lambda x: x.stat().st_size):
        size_mb = f.stat().st_size / (1024 * 1024)
        file_hash = sha256_file(f)
        existing = load_state(state_dir, file_hash)
        status = existing.get("status", "pending") if existing else "pending"
        marker = "✓" if status == "success" else "○" if status == "pending" else "✗"
        print(f"  {marker} {f.name} ({size_mb:.1f} MB) [{status}]")
        if status == "pending":
            pending.append(f)

    if args.dry_run:
        print(f"\n--dry-run: {len(pending)} pendientes, no se procesa nada.")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(cmd_transcribe())
