# -*- coding: utf-8 -*-
"""Auditoria y MEDICION de la RESOLUCION DE ENTIDADES (correferencia / enlazado).

POR QUE EXISTE
--------------
Todas las cifras publicadas de la cadena (`chain_benchmark.py`, docs
`CADENA_COMPLETA_EXTRACTOR_MOTOR.md`) asignan ids con el GROUND TRUTH como
ORACULO: se da por hecho que "Kael" y "el Guardian" son la misma entidad. En el
sistema real esa decision no la toma nadie con esa informacion. Este modulo
audita QUE hace de verdad el repo y MIDE cuanto se pierde.

QUE HACE HOY EL REPO (auditoria de codigo, no opinion)
-------------------------------------------------------
1. `review/resolver.py` NO resuelve correferencia. Resuelve cada mencion contra
   NEO4J (grafo ya existente): nombre canonico exacto, alias exacto,
   `toLower(canonical_name)`, y una comprobacion de variante EN/ES por token
   compartido (`_is_cross_language_variant`) que solo sirve para MARCAR
   `needs_review`, nunca para fusionar. El propio docstring lo dice:
   "NO fusiona duplicados". Si Neo4j no responde, TODO va a `needs_review`.
2. No hay ningun paso de correferencia intra-documento en `review/pipeline.py`
   (segment -> classify -> extract -> validate -> resolve -> decide -> writer).
   Un pronombre o una descripcion definida ("el Guardian") jamas se enlaza con su
   antecedente.
3. La unica canonicalizacion por cadena que existe antes de Neo4j es:
     * `review/workspace_aliases.py`: tabla MANUAL `config/aliases/<ws>.json`,
       solo entradas `reviewed=true`, coincidencia EXACTA de cadena.
     * `review/hybrid_filter.py::_ekey`: dedupe por `name.lower()|type`.
     * `review/resolver.py::_normalize`: minusculas sin tildes.
     * glosario (`glossary/glossary_matcher.py`, con fuzzy difflib) que se
       alimenta de `state/glossary.db`, fichero GITIGNORADO y AUSENTE en este
       entorno, por lo que no aporta nada aqui (misma condicion que en todas las
       mediciones previas).
   La agrupacion REAL efectiva es, por tanto: alias manual -> minusculas sin
   tildes. Nada mas.

QUE MIDE ESTE MODULO
--------------------
Sobre las MENCIONES del ground truth de cada corpus (`runner.derive_entities`,
que ya lleva el id verdadero de cada mencion) compara dos particiones:

    * la VERDADERA          : menciones agrupadas por `id` del ground truth.
    * la del SISTEMA REAL   : menciones agrupadas por `surface_key` (alias manual
                              + `resolver._normalize`).

Metricas B-cubed (estandar de correferencia; P/R/F1 promediados por mencion):
    - B-cubed precision baja  -> el sistema FUSIONA entidades distintas.
    - B-cubed recall baja     -> el sistema PARTE una entidad en varios nodos.
Se acompanan de los recuentos crudos y del catalogo completo de fusiones y
divisiones, para que cada cifra sea auditable a mano.

Ambito: se mide por FUENTE (lo que ve un documento aislado) y GLOBAL por corpus
(lo que acaba en el grafo, que es donde importa: Neo4j es unico).

NO escribe nada persistente, no abre red, no toca Neo4j ni el corpus.

Uso:
    python data-engine/app/tools/resolution_audit.py --corpus B1 H1 H2 \
        --out /ruta/resolution.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

_REPO_ROOT = _APP_DIR.parents[1]

from relations.benchmark import runner as _runner
from review.workspace_aliases import load_workspace_aliases as _load_ws_aliases

from tools.chain_benchmark import CORPORA, surface_key


# ---------------------------------------------------------------------------
# B-cubed
# ---------------------------------------------------------------------------
def bcubed(items: list[tuple]) -> dict:
    """B-cubed P/R/F1 sobre una lista de (clave_verdadera, clave_del_sistema).

    Para cada mencion i:
        P_i = |{j : sistema_j == sistema_i y verdad_j == verdad_i}| / |{j : sistema_j == sistema_i}|
        R_i = mismo numerador / |{j : verdad_j == verdad_i}|
    Se promedian sobre todas las menciones. Es la definicion clasica de Bagga &
    Baldwin, la habitual para evaluar correferencia.
    """
    if not items:
        return {"n_mentions": 0, "precision": 0.0, "recall": 0.0, "f1": 0.0}
    true_sizes: dict = {}
    sys_sizes: dict = {}
    inter: dict = {}
    for t, s in items:
        true_sizes[t] = true_sizes.get(t, 0) + 1
        sys_sizes[s] = sys_sizes.get(s, 0) + 1
        inter[(t, s)] = inter.get((t, s), 0) + 1
    p = sum(inter[(t, s)] / sys_sizes[s] for t, s in items) / len(items)
    r = sum(inter[(t, s)] / true_sizes[t] for t, s in items) / len(items)
    f = (2 * p * r / (p + r)) if (p + r) else 0.0
    return {"n_mentions": len(items), "n_true_clusters": len(true_sizes),
            "n_system_clusters": len(sys_sizes),
            "precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4)}


# ---------------------------------------------------------------------------
# Auditoria de un corpus
# ---------------------------------------------------------------------------
def audit_corpus(corpus_key: str) -> dict:
    corpus = _runner.load_corpus(CORPORA[corpus_key], verify=True)
    alias_by_ws: dict[str, dict] = {}

    per_source: list[dict] = []
    global_items: list[tuple] = []
    global_items_raw: list[tuple] = []  # sin normalizar (solo cadena literal)
    surface_to_ids: dict[str, set] = {}
    id_to_surfaces: dict[str, set] = {}

    for sid in sorted(corpus.sources):
        text = corpus.sources[sid]
        ws = corpus.workspace_by_source[sid]
        if ws not in alias_by_ws:
            alias_by_ws[ws] = _load_ws_aliases(_REPO_ROOT, ws)
        aliases = alias_by_ws[ws]

        mentions, _notes = _runner.derive_entities(sid, text, corpus.relations)
        items = []
        for m in mentions:
            key = surface_key(m["text"], aliases)
            items.append((str(m["id"]), key))
            global_items.append((str(m["id"]), key))
            global_items_raw.append((str(m["id"]), m["text"]))
            surface_to_ids.setdefault(key, set()).add(str(m["id"]))
            id_to_surfaces.setdefault(str(m["id"]), set()).add(key)
        per_source.append({"source_id": sid, "workspace": ws,
                           "bcubed": bcubed(items)})

    merges = {k: sorted(v) for k, v in surface_to_ids.items() if len(v) > 1}
    splits = {k: sorted(v) for k, v in id_to_surfaces.items() if len(v) > 1}

    n_src = len(per_source)
    macro = {}
    for metric in ("precision", "recall", "f1"):
        macro[metric] = round(
            sum(s["bcubed"][metric] for s in per_source) / n_src, 4) if n_src else 0.0

    return {
        "corpus": corpus_key,
        "n_sources": n_src,
        "aliases_cargados": {ws: len(a) for ws, a in alias_by_ws.items()},
        "glossary_db_presente": (_REPO_ROOT / "state" / "glossary.db").exists(),
        "bcubed_global": bcubed(global_items),
        "bcubed_global_sin_normalizar": bcubed(global_items_raw),
        "bcubed_macro_por_fuente": macro,
        "por_fuente": per_source,
        "fusiones": {"n": len(merges), "detalle": merges},
        "divisiones": {"n": len(splits), "detalle": splits},
    }


# ---------------------------------------------------------------------------
# Segunda medicion: alias del ground truth del EXTRACTOR (docs/33-34-36)
# ---------------------------------------------------------------------------
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "benchmark"


def audit_extractor_aliases() -> dict:
    """Mide la cobertura REAL de los alias anotados en el corpus del extractor.

    El corpus de `tests/fixtures/benchmark/` SI trae anotacion explicita de
    correferencia superficial: cada entidad esperada lleva su lista de `aliases`
    (`annotation_pass` 2 o 3, `reviewed=true`). El comparador oficial
    (`cli/benchmark_comparator.py::is_match`) ACEPTA cualquiera de esos alias como
    acierto -- es decir, tambien usa el ground truth como oraculo de enlazado.

    Aqui se comprueba, alias por alias, si la cadena de canonicalizacion REAL del
    repo lo resolveria hasta su nombre canonico:
        * `alias_table`  -> esta en `config/aliases/<ws>.json` con `reviewed=true`
        * `normalizacion`-> coincide tras `resolver._normalize` (tildes/mayusculas)
        * `no_resuelto`  -> nada del sistema actual lo enlaza (haria falta el
                            glosario con fuzzy, que exige `state/glossary.db`, o
                            correferencia real, que no existe)
    """
    rows: list[dict] = []
    per_source: list[dict] = []
    for gt_path in sorted(_FIXTURES.glob("*/ground-truth.json")):
        data = json.loads(gt_path.read_text(encoding="utf-8"))
        source_id = gt_path.parent.name
        ws = None
        ents = [e for e in data.get("entities", []) if e.get("expected", True)]
        n_alias_ent = 0
        for e in ents:
            ws = e.get("workspace", ws) or "leyenda"
            aliases = e.get("aliases", []) or []
            if aliases:
                n_alias_ent += 1
            table = _load_ws_aliases(_REPO_ROOT, ws)
            for al in aliases:
                canonical = e.get("canonical_name") or e["name"]
                if al in table and table[al] == canonical:
                    verdict = "alias_table"
                elif surface_key(al, table) == surface_key(canonical, table):
                    verdict = "normalizacion"
                else:
                    verdict = "no_resuelto"
                rows.append({"source_id": source_id, "workspace": ws,
                             "alias": al, "canonical": canonical, "resuelto_por": verdict})
        per_source.append({"source_id": source_id,
                           "annotation_pass": data.get("annotation_pass"),
                           "reviewed": data.get("reviewed"),
                           "n_entidades_esperadas": len(ents),
                           "n_entidades_con_alias": n_alias_ent})

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["resuelto_por"]] = counts.get(r["resuelto_por"], 0) + 1
    return {
        "corpus": "extractor (tests/fixtures/benchmark)",
        "n_alias_anotados": len(rows),
        "resueltos_por": counts,
        "tasa_resolucion": round(
            (len(rows) - counts.get("no_resuelto", 0)) / len(rows), 4) if rows else 0.0,
        "por_fuente": per_source,
        "detalle": rows,
    }


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", nargs="+", default=["B1", "H1", "H2"], choices=sorted(CORPORA))
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    out = []
    for key in args.corpus:
        rep = audit_corpus(key)
        out.append(rep)
        g = rep["bcubed_global"]
        gr = rep["bcubed_global_sin_normalizar"]
        print(f"{key:3s} menciones={g['n_mentions']:4d} ids_reales={g['n_true_clusters']:3d} "
              f"grupos_sistema={g['n_system_clusters']:3d} | "
              f"B3 P={g['precision']:.4f} R={g['recall']:.4f} F1={g['f1']:.4f} | "
              f"(cadena literal: F1={gr['f1']:.4f}) | "
              f"fusiones={rep['fusiones']['n']} divisiones={rep['divisiones']['n']}",
              flush=True)

    ext = audit_extractor_aliases()
    print(f"\nAlias anotados en el corpus del extractor: {ext['n_alias_anotados']} | "
          f"{ext['resueltos_por']} | tasa de resolucion real = {ext['tasa_resolucion']:.4f}")

    payload = {"tool": "resolution_audit-v1",
               "extractor_gt_aliases": ext,
               "resolucion_real": "workspace_aliases (reviewed) + resolver._normalize",
               "correferencia": "NO EXISTE en el pipeline (auditado)",
               "neo4j": "NO CONSULTADO",
               "corpora": out}
    if args.out:
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"\nJSON -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
