"""
Corrector opcional de transcripciones con Ollama (qwen2.5:7b).

Corrige errores de reconocimiento de voz conservando marcas de tiempo. Valida la
salida: mismo número de timestamps, longitud dentro del ±20%, sin meta-explicaciones.
Si falla la validación, conserva normalized.md y marca llm_correction_failed.
"""
from __future__ import annotations
import argparse, json, re, urllib.request, datetime
from pathlib import Path

TS_RE = re.compile(r'(\*\*\[\d{2}:\d{2}:\d{2}\]\*\*|\[\d{2}:\d{2}:\d{2}\])')

PROMPT_RULES = """Corrige errores de reconocimiento de voz en esta transcripcion automatica de una partida de La Leyenda de los Cinco Anillos.

Reglas:
1. Conserva todas las marcas de tiempo exactamente como estan.
2. No resumas.
3. No elimines contenido.
4. No inventes dialogo.
5. No conviertas la transcripcion en narracion literaria.
6. Corrige puntuacion y errores foneticos evidentes.
7. Usa unicamente el glosario proporcionado para normalizar nombres propios y terminos especializados.
8. Conserva numeros, reglas, tiradas y resultados.
9. Si una palabra no puede determinarse con seguridad, conserva el texto original.
10. Devuelve unicamente la transcripcion corregida, sin explicaciones ni comentarios.
"""

def ollama_generate(host, model, prompt, temperature=0.1, timeout=300):
    data = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": temperature}}).encode()
    req = urllib.request.Request(host + "/api/generate", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())["response"]

def correct(input_md, output_dir, glossary_json, host, model):
    src = Path(input_md)
    text = src.read_text(encoding="utf-8")
    ts_in = len(TS_RE.findall(text))

    terms = []
    gj = Path(glossary_json)
    if gj.exists():
        data = json.loads(gj.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("terms", [])
        for t in items[:80]:
            c = t.get("canonical_term") or t.get("canonical") or t.get("term")
            if c: terms.append(c)
    glossary_block = ", ".join(dict.fromkeys(terms))

    prompt = f"{PROMPT_RULES}\n\nGlosario: {glossary_block}\n\nTranscripcion:\n{text}\n\nTranscripcion corregida:"
    corrected = ollama_generate(host, model, prompt).strip()

    ts_out = len(TS_RE.findall(corrected))
    len_ratio = len(corrected) / max(1, len(text))
    lowered = corrected.lower()
    meta = any(m in lowered for m in ["aqui tienes", "aqui esta", "he corregido", "correccion:", "nota:"])

    validation = {
        "timestamps_in": ts_in, "timestamps_out": ts_out,
        "timestamps_ok": ts_in == ts_out,
        "length_ratio": round(len_ratio, 3),
        "length_ok": 0.8 <= len_ratio <= 1.2,
        "no_meta_explanations": not meta,
    }
    passed = validation["timestamps_ok"] and validation["length_ok"] and validation["no_meta_explanations"]

    outdir = Path(output_dir); outdir.mkdir(parents=True, exist_ok=True)
    stem = src.name[:-3] if src.name.endswith(".md") else src.name
    stem = stem.replace(".normalized", "")
    corr_path = outdir / (stem + ".corrected.md")
    meta_path = outdir / (stem + ".corrected.review.json")

    if passed:
        corr_path.write_text(corrected, encoding="utf-8")
        status = "ok"
    else:
        # conservar normalized como corrected fallback, marcar fallo
        corr_path.write_text(text, encoding="utf-8")
        status = "llm_correction_failed"

    review = {
        "source": str(src), "model": model, "ollama_host": host,
        "status": status, "validation": validation,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "corrected_file": str(corr_path),
    }
    meta_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"status={status}")
    print(f"validation={json.dumps(validation)}")
    print(f"corrected -> {corr_path}")
    return status

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--glossary-json", default="")
    ap.add_argument("--host", default="http://192.168.1.157:11434")
    ap.add_argument("--model", default="qwen2.5:7b")
    a = ap.parse_args()
    correct(a.input, a.output_dir, a.glossary_json, a.host, a.model)
