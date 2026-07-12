"""
Normalizador determinista de transcripciones L5A.

Aplica error_forms del glosario (glossary.db) sobre una transcripción markdown,
conservando las marcas de tiempo y registrando cada sustitución. NO usa str.replace
bruto: aplica límites de palabra con regex. ready_for_ingestion siempre False en
esta fase (requiere revisión humana).
"""
from __future__ import annotations
import argparse, json, re, sqlite3, sys, datetime
from pathlib import Path

# Marca de tiempo: soporta [HH:MM:SS] y **[HH:MM:SS]**
TS_RE = re.compile(r'(\*\*\[\d{2}:\d{2}:\d{2}\]\*\*|\[\d{2}:\d{2}:\d{2}\])')

# Umbrales de confianza
TH_AUTO = 0.95      # >=0.95 auto_replace
TH_CONTEXT = 0.85   # 0.85-0.94 needs_context
TH_REVIEW = 0.70    # 0.70-0.84 needs_review


def load_error_forms(db_path: str, workspace: str):
    """Devuelve lista (error_form, canonical, confidence) ordenada por longitud desc."""
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(
        "SELECT canonical_term, error_forms_json, confidence FROM glossary_terms "
        "WHERE workspace=? AND enabled=1", (workspace,))
    pairs = {}
    for canonical, efj, conf in cur.fetchall():
        for ef in json.loads(efj or "[]"):
            ef = ef.strip()
            if not ef or ef.lower() == canonical.lower():
                continue
            # nos quedamos con la mayor confianza vista para ese error_form
            prev = pairs.get(ef.lower())
            if prev is None or (conf or 0) > prev[2]:
                pairs[ef.lower()] = (ef, canonical, conf if conf is not None else 0.9)
    con.close()
    out = list(pairs.values())
    out.sort(key=lambda t: len(t[0]), reverse=True)  # frases largas primero
    return out


def split_timestamp(line: str):
    """Separa (prefijo_con_timestamp, texto) para no tocar la marca de tiempo."""
    m = TS_RE.match(line.strip())
    if not m:
        return "", line
    idx = line.find(m.group(0)) + len(m.group(0))
    return line[:idx], line[idx:]


def normalize_text(text: str, error_forms, line_no: int):
    """Aplica error_forms con límites de palabra. Devuelve (texto_nuevo, [replacements])."""
    replacements = []
    new = text
    for ef, canonical, conf in error_forms:
        if conf < TH_AUTO:
            continue  # en esta fase solo auto_replace con error_forms exactos (>=0.95)
        pattern = re.compile(r'(?<![\w])' + re.escape(ef) + r'(?![\w])', re.IGNORECASE)
        def _sub(mo):
            replacements.append({
                "line": line_no,
                "from": mo.group(0),
                "to": canonical,
                "confidence": round(conf, 3),
                "action": "auto_replace",
            })
            return canonical
        new = pattern.sub(_sub, new)
    return new, replacements


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--workspace", default="leyenda")
    ap.add_argument("--db", default=None)
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    db_path = args.db or str(repo_root / "state" / "glossary.db")

    error_forms = load_error_forms(db_path, args.workspace)

    src = Path(args.input)
    raw = src.read_text(encoding="utf-8")
    raw_lines = raw.splitlines()

    ts_before = len(TS_RE.findall(raw))

    out_lines = []
    all_repl = []
    for i, line in enumerate(raw_lines, 1):
        prefix, text = split_timestamp(line)
        if prefix:
            new_text, repl = normalize_text(text, error_forms, i)
            out_lines.append(prefix + new_text)
            all_repl.extend(repl)
        else:
            out_lines.append(line)

    normalized = "\n".join(out_lines)
    ts_after = len(TS_RE.findall(normalized))

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = src.name
    if stem.endswith(".md"):
        stem = stem[:-3]
    norm_path = outdir / (stem + ".normalized.md")
    review_path = outdir / (stem + ".review.json")

    norm_path.write_text(normalized, encoding="utf-8")

    validation_errors = []
    if ts_before != ts_after:
        validation_errors.append(f"timestamps cambiaron: {ts_before} -> {ts_after}")

    review = {
        "source_id": src.stem,
        "workspace": args.workspace,
        "input_file": str(src),
        "normalized_file": str(norm_path),
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "glossary_db": db_path,
        "glossary_error_forms_loaded": len(error_forms),
        "timestamps_in": ts_before,
        "timestamps_out": ts_after,
        "timestamps_preserved": ts_before == ts_after,
        "replacements": all_repl,
        "replacements_count": len(all_repl),
        "ambiguous_matches": [],
        "unknown_terms": [],
        "validation_errors": validation_errors,
        "ready_for_ingestion": False,
    }
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"normalized -> {norm_path}")
    print(f"review     -> {review_path}")
    print(f"error_forms cargados: {len(error_forms)}")
    print(f"sustituciones: {len(all_repl)}")
    print(f"timestamps: {ts_before} -> {ts_after} (preservados={ts_before==ts_after})")
    for r in all_repl:
        print(f"  L{r['line']}: {r['from']} -> {r['to']} (conf {r['confidence']})")


if __name__ == "__main__":
    main()
