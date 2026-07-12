#!/usr/bin/env python3
"""Prueba de transcripción de vídeo — S9 Knowledge (no ingestar al grafo)."""
import sys
import datetime
from pathlib import Path

def transcribe(audio_path: str, language: str = "es", model: str = "small") -> dict:
    from faster_whisper import WhisperModel
    print(f"[INFO] Cargando modelo {model}...")
    wm = WhisperModel(model, device="cpu", compute_type="int8")
    print(f"[INFO] Transcribiendo {audio_path}...")
    segments, info = wm.transcribe(audio_path, language=language, beam_size=5, vad_filter=True)
    result = {"language": info.language, "segments": []}
    for seg in segments:
        result["segments"].append({
            "start": seg.start, "end": seg.end, "text": seg.text.strip()
        })
        print(f"[{seg.start:.1f}s-{seg.end:.1f}s] {seg.text.strip()[:80]}")
    return result

def format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

def write_outputs(result: dict, audio_path: str, video_name: str, out_dir: str):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    full_text = " ".join(s["text"] for s in result["segments"])

    # .txt
    txt_path = out / f"{video_name}.txt"
    with open(txt_path, "w") as f:
        for seg in result["segments"]:
            f.write(f"[{format_timestamp(seg['start'])}-{format_timestamp(seg['end'])}] {seg['text']}\n")
    print(f"[OK] TXT: {txt_path}")

    # .md
    md_path = out / f"{video_name}.md"
    with open(md_path, "w") as f:
        f.write(f"# Transcripción — {video_name}\n\n")
        f.write(f"## Metadatos\n\n")
        f.write(f"- Archivo original: test_video.mp4\n")
        f.write(f"- Audio procesado: {audio_path}\n")
        f.write(f"- Fecha de transcripción: {now}\n")
        f.write(f"- Motor: faster-whisper\n")
        f.write(f"- Modelo: small\n")
        f.write(f"- Idioma detectado: {result['language']}\n")
        f.write(f"- Source kind: video\n")
        f.write(f"- Estado: prueba\n\n")
        f.write(f"## Transcripción con marcas de tiempo\n\n")
        for seg in result["segments"]:
            f.write(f"[{format_timestamp(seg['start'])}-{format_timestamp(seg['end'])}] {seg['text']}\n\n")
        f.write(f"## Observaciones de calidad\n\n")
        f.write(f"- Segmentos totales: {len(result['segments'])}\n")
        f.write(f"- Texto total aprox: {len(full_text)} caracteres\n")
        if len(result["segments"]) == 0:
            f.write(f"- Nota: Audio es solo tono sine (no hay habla), por lo que la transcripción está vacía.\n")
    print(f"[OK] MD: {md_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python transcribe_video_sample.py <audio.wav> [video_name] [language]")
        sys.exit(1)
    audio = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else Path(audio).stem
    lang = sys.argv[3] if len(sys.argv) > 3 else "es"
    out_dir = "/opt/knowledge-services/s9-knowledge-repo/output/transcriptions/video-test"
    result = transcribe(audio, language=lang)
    write_outputs(result, audio, name, out_dir)
    print("[OK] Transcripción completada.")
