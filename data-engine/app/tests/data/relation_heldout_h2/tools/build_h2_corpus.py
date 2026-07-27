# -*- coding: utf-8 -*-
"""Generador DETERMINISTA del corpus held-out H2 (material REAL).

H2 se construye a partir de material con DERECHOS DE AUTOR que **no** vive en este
repositorio (tres manuales de rol y la transcripcion de una partida). Este script
documenta el procedimiento completo y es reejecutable por quien tenga el material
original en `--material-root`; el repositorio guarda UNICAMENTE los fragmentos
seleccionados (citas cortas, <= 400 caracteres cada una), sus hashes y el ground truth.

Muestreo: semilla fija `SEED = 20260727`, ver `README.md` §2.

Uso (solo para regenerar; el corpus versionado ya esta sellado):
    python3 build_h2_corpus.py --material-root /ruta/al/material --annotations /ruta/annotations.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

SEED = 20260727
MAX_FRAGMENT_CHARS = 400
CORPUS_VERSION = "1.0.0"

HERE = Path(__file__).resolve().parent
CORPUS_DIR = HERE.parent


def _norm_index(text: str):
    """Devuelve (cadena_normalizada, mapa_de_indices) ignorando todo lo que no sea alfanumerico.

    Permite localizar una cita aunque el texto extraido del PDF contenga artefactos
    de guionado o espacios espurios ('arraiga - dos', 'o dian', 'Po der').
    """
    out, idx = [], []
    for i, ch in enumerate(text):
        c = unicodedata.normalize("NFKD", ch)
        c = "".join(x for x in c if not unicodedata.combining(x)).lower()
        if c.isalnum():
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def locate(fragment: str, needle: str, *, unique: bool = True,
           span: tuple[int, int] | None = None) -> tuple[int, int]:
    """Offsets de caracter EXACTOS de `needle` dentro de `fragment` (tolerante a artefactos).

    `unique=True` (evidencia) exige que la cita aparezca UNA sola vez. Para menciones
    de sujeto/objeto se usa `unique=False` con la misma regla que aplica el arnes:
    primero dentro del span de evidencia, y si no aparece ahi, primera aparicion en
    el fragmento completo.
    """
    nf, imap = _norm_index(fragment)
    nn, _ = _norm_index(needle)
    if not nn:
        raise ValueError(f"cita vacia: {needle!r}")
    starts = []
    pos = nf.find(nn)
    while pos >= 0:
        starts.append(pos)
        pos = nf.find(nn, pos + 1)
    if not starts:
        raise ValueError(f"cita NO encontrada en el fragmento: {needle!r}")
    if unique and len(starts) > 1:
        raise ValueError(f"cita AMBIGUA (aparece mas de una vez): {needle!r}")
    chosen = starts[0]
    if span is not None:
        inside = [p for p in starts
                  if span[0] <= imap[p] and imap[p + len(nn) - 1] + 1 <= span[1]]
        if inside:
            chosen = inside[0]
    return imap[chosen], imap[chosen + len(nn) - 1] + 1


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool-books", required=True)
    ap.add_argument("--pool-transcript", required=True)
    ap.add_argument("--annotations", required=True)
    args = ap.parse_args()

    sys.path.insert(0, str(Path(args.annotations).resolve().parent))
    ann = __import__(Path(args.annotations).stem)

    pool = json.loads(Path(args.pool_books).read_text(encoding="utf-8"))
    tr = json.loads(Path(args.pool_transcript).read_text(encoding="utf-8"))
    by_ref = {(c["book"], c["page"], c["sent_i"], c["w"]): c["text"] for c in pool}
    by_tr = {c["sent_i"]: c["text"] for c in tr}

    src_dir = CORPUS_DIR / "sources"
    src_dir.mkdir(parents=True, exist_ok=True)
    for old in src_dir.glob("*.txt"):
        old.unlink()

    texts, manifest_sources = {}, []
    slug = re.compile(r"[^a-z0-9]+")
    for sid, ws, ref, title in ann.SOURCES:
        book, page, si, w = ref
        text = by_tr[si] if book == "transcripcion" else by_ref[(book, page, si, w)]
        if len(text) > MAX_FRAGMENT_CHARS:
            raise SystemExit(f"{sid}: fragmento de {len(text)} chars supera el limite legal")
        name = slug.sub("-", unicodedata.normalize("NFKD", title.lower())
                        .encode("ascii", "ignore").decode()).strip("-")
        path = f"sources/{sid}-{name}.txt"
        (CORPUS_DIR / path).write_text(text, encoding="utf-8")
        texts[sid] = text
        manifest_sources.append({
            "id": sid, "path": path, "title": title, "workspace": ws,
            "encoding": "utf-8", "bytes": len(text.encode("utf-8")), "chars": len(text),
            "sha256": sha256_text(text),
            "provenance": {"work": book, "page": page, "window_start_sentence": si,
                           "window_sentences": w},
        })

    relations = []
    for n, r in enumerate(ann.REL, start=1):
        (src, s_txt, s_id, s_ty, pred, o_txt, o_id, o_ty, evid,
         neg, temp, epi, direction, decision, notes) = r
        frag = texts[src]
        es, ee = locate(frag, evid)
        ss, se = locate(frag, s_txt, unique=False, span=(es, ee))
        os_, oe = locate(frag, o_txt, unique=False, span=(es, ee))
        ws = next(m["workspace"] for m in manifest_sources if m["id"] == src)
        relations.append({
            "relation_id": f"rel-{n:03d}", "source_id": src, "workspace": ws,
            "segment_id": f"{src}#s1",
            "subject_id": s_id, "subject_text": frag[ss:se], "subject_type": s_ty,
            "predicate": pred,
            "object_id": o_id, "object_text": frag[os_:oe], "object_type": o_ty,
            "evidence_text": frag[es:ee], "evidence_start": es, "evidence_end": ee,
            "negated": neg, "temporal_status": temp, "epistemic_status": epi,
            "direction": direction, "expected_decision": decision,
            "annotator_notes": notes,
        })

    gt = {
        "corpus_version": CORPUS_VERSION,
        "description": (
            "Ground truth del corpus HELD-OUT H2 (material REAL: tres manuales de rol y una "
            "transcripcion de partida). ANOTACION DE UN SOLO PASE, sin segundo anotador y sin "
            "medida de acuerdo; las notas por relacion documentan cada decision. NO se usa para "
            "escribir reglas ni para ajustar expresiones del motor: ver "
            "docs/relation-engine-v2e/HELDOUT_POLICY.md."
        ),
        "temporal_status_values": ["PAST", "PRESENT", "FUTURE", "ONGOING", "ENDED", "ATEMPORAL"],
        "expected_decision_values": ["ACCEPT", "REJECT", "REVIEW"],
        "relations": relations,
    }
    gt_path = CORPUS_DIR / "ground_truth" / "relations.json"
    gt_path.parent.mkdir(exist_ok=True)
    gt_txt = json.dumps(gt, ensure_ascii=False, indent=2) + "\n"
    gt_path.write_text(gt_txt, encoding="utf-8")

    by_src: dict = {}
    for r in relations:
        by_src.setdefault(r["source_id"], []).append(r["relation_id"])
    cases_doc = {
        "corpus_version": CORPUS_VERSION,
        "description": (
            "Indice de CASOS del held-out H2 (material real). Este fichero es METADATO: el "
            "arnes `relations/benchmark/` no lo lee. Cada caso equivale a un fragmento "
            "muestreado y sus etiquetas de cobertura lingueistica."
        ),
        "cases": [
            {
                "case_id": f"H2-{i:02d}",
                "title": m["title"],
                "work": m["provenance"]["work"],
                "workspace": m["workspace"],
                "coverage": ann.TAGS[m["id"]],
                "sources": [m["id"]],
                "relations": by_src.get(m["id"], []),
            }
            for i, m in enumerate(manifest_sources, start=1)
        ],
    }
    cases_txt = json.dumps(cases_doc, ensure_ascii=False, indent=2) + "\n"
    (CORPUS_DIR / "cases").mkdir(exist_ok=True)
    (CORPUS_DIR / "cases" / "cases.json").write_text(cases_txt, encoding="utf-8")

    manifest = {
        "corpus": "relation-benchmark",
        "corpus_role": "held-out",
        "version": CORPUS_VERSION,
        "synthetic": False,
        "contains_private_corpus": False,
        "material_policy": (
            "Fragmentos CITADOS de obra con derechos de autor y de una grabacion de partida. "
            "Solo se versionan citas cortas (<= 400 caracteres) imprescindibles como evidencia; "
            "los originales NO estan en el repositorio."
        ),
        "sampling_seed": SEED,
        "workspaces": sorted({m["workspace"] for m in manifest_sources}),
        "encoding": "utf-8",
        "source_count": len(manifest_sources),
        "relation_count": len(relations),
        "sources": manifest_sources,
        "ground_truth": {"path": "ground_truth/relations.json", "sha256": sha256_text(gt_txt)},
        "cases": {"path": "cases/cases.json", "sha256": sha256_text(cases_txt)},
    }
    man_txt = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    (CORPUS_DIR / "manifest.json").write_text(man_txt, encoding="utf-8")

    seal = {
        "seal_version": "heldout-seal-1",
        "corpus": "relation-heldout-h2",
        "corpus_version": CORPUS_VERSION,
        "sealed_at": "2026-07-27",
        "sealed_by": "Bloque H2 - responsable del corpus real",
        "declaration": (
            "Corpus sellado ANTES de ejecutar el arnes. Anotacion de UN SOLO PASE. Si un fichero "
            "cambia, el hash cambia y el corpus queda QUEMADO (HELDOUT_POLICY.md)."
        ),
        "manifest_sha256": sha256_text(man_txt),
        "ground_truth_sha256": sha256_text(gt_txt),
        "cases_sha256": sha256_text(cases_txt),
        "sources_sha256": {m["id"]: m["sha256"] for m in manifest_sources},
    }
    (CORPUS_DIR / "SEAL.json").write_text(
        json.dumps(seal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"H2: {len(manifest_sources)} fuentes, {len(relations)} relaciones, "
          f"{sum(m['chars'] for m in manifest_sources)} chars citados")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
