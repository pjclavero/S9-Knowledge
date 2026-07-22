# -*- coding: utf-8 -*-
"""Helper que corre en el worktree V3: dado un documento y una lista de spans GT,
devuelve, por span, los fragment_ids del protocolo V3 que CUBREN ese span (los
fragmentos cuyo [start,end) intersecta el span). Se usa SOLO para congelar el
banco sintetico (respuestas del protocolo de fragmentos). Determinista, sin red.

stdin JSON: {"doc": str, "spans": [[s,e], ...], "max_fragments": int}
stdout JSON: {"fragment_ids": [[...], ...], "n_fragments": int}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from relations.fragment_protocol import fragment_document  # noqa: E402


def main() -> None:
    job = json.loads(sys.stdin.read())
    doc = job["doc"]
    spans = job["spans"]
    max_fragments = int(job.get("max_fragments", 200))
    frags = fragment_document(doc, max_fragments=max_fragments)
    out_ids = []
    for s, e in spans:
        covering = [f.fragment_id for f in frags
                    if not (f.end <= s or f.start >= e)]
        if not covering and frags:
            # fallback determinista: el fragmento cuyo rango contiene el inicio
            for f in frags:
                if f.start <= s < f.end:
                    covering = [f.fragment_id]
                    break
        out_ids.append(covering)
    sys.stdout.write(json.dumps({"fragment_ids": out_ids, "n_fragments": len(frags)}))


if __name__ == "__main__":
    main()
