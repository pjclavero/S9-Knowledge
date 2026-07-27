# -*- coding: utf-8 -*-
"""Driver de la CADENA COMPLETA: extractor REAL de entidades -> motor de relaciones.

QUE MIDE ESTO Y POR QUE EXISTE
------------------------------
El arnes autoritativo de relaciones (`relations/benchmark/`) alimenta el pipeline
R8 con entidades DERIVADAS DEL GROUND TRUTH (`runner.derive_entities`): le regala
al motor las menciones perfectas, con su `id`, su `type` y sus offsets exactos.
Todas las cifras publicadas (B1, H1, H2) son, por tanto, una COTA OPTIMISTA: nadie
habia medido que ocurre cuando las entidades las produce el extractor real.

Este driver hace exactamente esa ablacion, sobre los MISMOS corpus y con las
MISMAS funciones de puntuacion:

    A) `gt_perfect`      -> entidades de `runner.derive_entities` (CONTROL, ya medido)
    B) `extractor_strict`-> entidades REALES del extractor, politica de ids ESTRICTA
    C) `extractor_lax`   -> entidades REALES del extractor, politica de ids LAXA

REGLAS DE CONSTRUCCION (lo que este fichero NO hace)
----------------------------------------------------
  * NO modifica `relations/benchmark/` ni ningun corpus ni ningun umbral.
  * NO reimplementa metricas: importa `benchmark.matching` y `benchmark.metrics`
    a traves de `benchmark.report.build_report`, que es el mismo ensamblador que
    usa la CLI autoritativa.
  * NO reimplementa el motor: llama a `relations.pipeline.run_pipeline`.
  * NO reimplementa el extractor: llama a `review.extractor.extract_from_segments`.
  * NO abre red: proveedores SIEMPRE deshabilitados (solo modos de `runner.MODES`).

DECISIONES METODOLOGICAS (todas sesgadas EN CONTRA de una cifra bonita, salvo
donde se dice explicitamente lo contrario)
-------------------------------------------------------------------------------
1. SEGMENTACION. Igual que el arnes: UN segmento por fuente, `segment_id ==
   source_id`, texto completo. Asi la unica variable que cambia entre A y B/C es
   la PROCEDENCIA DE LAS ENTIDADES. No se ejecutan el segmentador ni el
   clasificador reales: el segmento se construye ya clasificado con
   `should_extract=True`. Esto FAVORECE al extractor (no puede perder texto por
   una mala clasificacion).

2. OFFSETS. El extractor NO emite offsets de caracter: `review.models.Candidate`
   solo lleva `name`, `entity_type`, `confidence` y `evidence` (200 primeros
   caracteres del segmento). Se RECUPERAN localizando el `name` emitido en el
   texto de la fuente con `re.finditer(re.escape(name))`, sensible a mayusculas,
   y generando UNA MENCION POR OCURRENCIA. Es el analogo mas fiel del control,
   que tambien coloca varias menciones del mismo id en varias posiciones.
   SESGO: favorece al extractor (le regala la localizacion exacta de todas sus
   menciones, que en un sistema real habria que resolver).

3. DES-SOLAPAMIENTO. Un conjunto de menciones con spans solapados no es una
   entrada valida para `relations.pairs` (dos "entidades" distintas en la misma
   posicion producen pares espurios de distancia 0). El extractor SI produce
   nombres solapados (p.ej. "Clan Escorpion" por regex y "Clan Escorpión" por la
   tabla de clanes). Regla determinista: ante spans solapados se conserva el MAS
   LARGO; a igual longitud, el de nombre alfabeticamente menor. Los descartados
   se registran en `derivation_notes` con `reason="overlapping_span"`.

4. TIPOS. El extractor emite `Character | Location | Faction | Clan`.
   `Clan` NO pertenece a `relations.contracts.ALLOWED_ENTITY_TYPES` y el pipeline
   lo rechazaria, asi que se mapea `Clan -> Faction` (equivalencia semantica
   directa: los clanes del GT estan anotados como `Faction`). Cualquier otro tipo
   fuera del vocabulario permitido se pasa como `None` (el pipeline lo acepta) y
   se registra. SESGO: `Clan -> Faction` FAVORECE al extractor en
   `types_correct`; sin ese mapeo el pipeline fallaria el segmento entero.
   El extractor NUNCA produce `Object`, `Event` ni `Concept`: esos tipos del GT
   son inalcanzables por construccion.

5. GLOSARIO. `review.extractor._load_glossary` lee `state/glossary.db`, que es
   estado de ejecucion (gitignored) y NO existe en este entorno. El extractor
   corre por tanto SIN GLOSARIO, que es su modo mas conservador. SESGO: en contra
   del extractor respecto a una produccion con glosario poblado.

6. POLITICA DE IDS -- LA DECISION MAS DELICADA. El ground truth referencia
   entidades por `id` (`ysolde`, `clan-roble`). El extractor no produce ids: solo
   cadenas de texto. Sin una politica de emparejamiento, CERO predicciones
   podrian emparejar y el resultado seria trivialmente 0. Se miden DOS politicas
   que ACOTAN la verdad por abajo y por arriba:

     * ESTRICTA (`strict`): una mencion del extractor recibe el id de una mencion
       del GT si y solo si su span coincide EXACTAMENTE (`start` y `end`
       identicos). Es el limite inferior: exige que el extractor delimite la
       mencion con precision de caracter.
     * LAXA (`lax`): una mencion del extractor recibe el id de la mencion del GT
       con la que MAS caracteres solapa (cualquier solape > 0 basta). Es el
       limite superior: cualquier trozo de la mencion correcta vale.

   En AMBAS politicas, una mencion sin correspondencia recibe un id sintetico
   `xx::<slug>` que NUNCA puede emparejar con el GT: contribuye a falsos
   positivos, nunca a verdaderos positivos.

   ADVERTENCIA CAPITAL DE HONESTIDAD: las dos politicas usan el GROUND TRUTH para
   asignar ids. Es un ORACULO DE RESOLUCION DE ENTIDADES que el sistema real no
   tiene (`review/resolver.py` no interviene aqui). Por tanto B y C siguen siendo
   COTAS OPTIMISTAS: miden la degradacion que aporta la DETECCION de entidades,
   con el ENLAZADO regalado. La cadena completa real sera igual o peor.

SALIDA
------
JSON con un informe `report.build_report` por (corpus, modo, selector, condicion),
mas el detalle de la derivacion de entidades. Sin red, sin Neo4j, sin ingesta.

Uso:
    python data-engine/app/tools/chain_benchmark.py \
        --corpus B1 H1 H2 --selector v1 v2 --mode baseline1 \
        --out /ruta/chain.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Optional

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

_REPO_ROOT = _APP_DIR.parents[1]

# --- Arnes autoritativo de relaciones (IMPORTADO, jamas modificado) ---------
from relations.benchmark import runner as _runner
from relations.benchmark import report as _report
from relations.benchmark import matching as _matching  # noqa: F401  (via build_report)
from relations.benchmark import metrics as _bench_metrics  # noqa: F401  (via build_report)
from relations.contracts import ALLOWED_ENTITY_TYPES
from relations.pipeline import run_pipeline as _run_pipeline

# --- Extractor REAL (IMPORTADO, jamas modificado) ---------------------------
from review import extractor as _extractor

# Corpus disponibles (los tres del programa).
CORPORA = {
    "B1": _APP_DIR / "tests" / "data" / "relation_benchmark",
    "H1": _APP_DIR / "tests" / "data" / "relation_heldout",
    "H2": _APP_DIR / "tests" / "data" / "relation_heldout_h2",
}

CONDITIONS = ("gt_perfect", "extractor_strict", "extractor_lax")

# Mapa de tipos del extractor -> vocabulario del motor. Ver decision 4.
EXTRACTOR_TYPE_MAP = {
    "Character": "Character",
    "Location": "Location",
    "Faction": "Faction",
    "Clan": "Faction",
}

# Prefijo de los ids sinteticos (menciones sin correspondencia en el GT).
UNMATCHED_PREFIX = "xx::"


# ---------------------------------------------------------------------------
# Extractor real -> menciones con offsets
# ---------------------------------------------------------------------------
def _slug(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-") or "vacio"


def build_classified_segment(source_id: str, text: str, workspace: str) -> dict:
    """Segmento YA CLASIFICADO equivalente al del arnes (uno por fuente).

    No se ejecutan `review.segmenter` ni `review.classifier`: se fija
    `should_extract=True` para que la comparacion aisle la extraccion de
    entidades y no la segmentacion. Esto FAVORECE al extractor.
    """
    return {
        "segment_id": source_id,
        "source_id": source_id,
        "source_kind": "text",
        "workspace": workspace,
        "timestamp_start": "",
        "timestamp_end": "",
        "text": text,
        "lines": text.splitlines(),
        "category": "lore",
        "should_extract": True,
        "category_scores": {},
    }


def extractor_mentions(source_id: str, text: str, workspace: str) -> tuple[list[dict], list[dict]]:
    """Llama al EXTRACTOR REAL y devuelve (menciones_con_offsets, notas).

    Cada mencion es `{"name", "type", "start", "end"}` (sin `id`: lo asigna la
    politica de emparejamiento). Ver decisiones 2, 3, 4 y 5 del docstring.
    """
    seg = build_classified_segment(source_id, text, workspace)
    glossary = _extractor._load_glossary(_REPO_ROOT, workspace)
    candidates = _extractor.extract_from_segments([seg], glossary)

    notes: list[dict] = []
    raw: list[dict] = []
    for cand in candidates:
        if cand.kind != "entity" or not cand.name:
            continue
        name = cand.name
        etype = EXTRACTOR_TYPE_MAP.get(cand.entity_type or "", None)
        if etype is None:
            notes.append({"source_id": source_id, "name": name,
                          "extractor_type": cand.entity_type,
                          "reason": "type_out_of_vocabulary",
                          "allowed": list(ALLOWED_ENTITY_TYPES)})
        spans = [m.span() for m in re.finditer(re.escape(name), text)]
        if not spans:
            # El extractor canonicalizo el nombre (tabla de clanes / glosario) y
            # la cadena resultante no aparece literalmente en el texto: no se
            # inventa posicion.
            notes.append({"source_id": source_id, "name": name,
                          "reason": "name_not_found_in_text"})
            continue
        for start, end in spans:
            raw.append({"name": name, "type": etype, "start": start, "end": end,
                        "confidence": cand.confidence})

    # Deduplicacion exacta (mismo nombre y mismo span).
    dedup: dict[tuple, dict] = {}
    for m in raw:
        dedup.setdefault((m["start"], m["end"], m["name"]), m)
    ordered = sorted(dedup.values(), key=lambda m: (m["start"], -(m["end"] - m["start"]), m["name"]))

    # Des-solapamiento determinista (decision 3): se conserva el span mas largo.
    kept: list[dict] = []
    for m in ordered:
        clash = next((k for k in kept if m["start"] < k["end"] and k["start"] < m["end"]), None)
        if clash is None:
            kept.append(m)
        else:
            notes.append({"source_id": source_id, "name": m["name"],
                          "start": m["start"], "end": m["end"],
                          "reason": "overlapping_span",
                          "kept_instead": clash["name"]})
    kept.sort(key=lambda m: (m["start"], m["end"], m["name"]))
    return kept, notes


# ---------------------------------------------------------------------------
# Politicas de emparejamiento de ids (decision 6)
# ---------------------------------------------------------------------------
def assign_ids(mentions: list[dict], gt_entities: list[dict], policy: str) -> tuple[list[dict], list[dict]]:
    """Asigna un `id` a cada mencion del extractor segun la politica.

    `gt_entities` son las entidades del CONTROL (`runner.derive_entities`), que
    llevan el `id` real del ground truth y sus offsets.

    * `strict`: span EXACTAMENTE igual al de una mencion del GT.
    * `lax`   : maximo solape de caracteres con una mencion del GT (solape > 0).

    Sin correspondencia -> id sintetico `xx::<slug>`, que jamas empareja con el GT.
    Devuelve (entidades_para_el_pipeline, notas_de_emparejamiento).
    """
    if policy not in ("strict", "lax"):
        raise ValueError(f"politica de ids desconocida: {policy!r}")

    out: list[dict] = []
    notes: list[dict] = []
    for m in mentions:
        matched_id: Optional[str] = None
        if policy == "strict":
            exact = [g for g in gt_entities if g["start"] == m["start"] and g["end"] == m["end"]]
            if exact:
                matched_id = sorted(exact, key=lambda g: str(g["id"]))[0]["id"]
        else:
            best: Optional[tuple] = None
            for g in gt_entities:
                inter = min(m["end"], g["end"]) - max(m["start"], g["start"])
                if inter <= 0:
                    continue
                # Mayor solape; desempate determinista por span mas largo e id menor.
                rank = (-inter, -(g["end"] - g["start"]), str(g["id"]))
                if best is None or rank < best[0]:
                    best = (rank, g["id"])
            if best is not None:
                matched_id = best[1]

        if matched_id is None:
            matched_id = UNMATCHED_PREFIX + _slug(m["name"])
            notes.append({"name": m["name"], "start": m["start"], "end": m["end"],
                          "policy": policy, "reason": "no_gt_correspondence",
                          "assigned_id": matched_id})
        out.append({"id": matched_id, "text": m["name"], "type": m["type"],
                    "start": m["start"], "end": m["end"]})
    out.sort(key=lambda e: (e["start"], e["end"], e["id"], e["type"] or ""))
    return out, notes


# ---------------------------------------------------------------------------
# Metricas de DETECCION de entidades sobre el corpus de relaciones (diagnostico)
# ---------------------------------------------------------------------------
def entity_detection_metrics(mentions: list[dict], gt_entities: list[dict]) -> dict:
    """P/R/F1 de DETECCION de menciones (diagnostico, no es el arnes de docs/34).

    * `span_exact` : una mencion del extractor es TP si su span coincide
      exactamente con el de una mencion del GT (1:1, avaricioso determinista).
    * `span_overlap`: TP si solapa (>0 caracteres) con una mencion del GT.
    El denominador de recall son las menciones del GT (las que el motor recibe
    en el control), no las entidades unicas.
    """
    def _prf(tp: int, fp: int, fn: int) -> dict:
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / (tp + fn) if (tp + fn) else 0.0
        f = (2 * p * r / (p + r)) if (p + r) else 0.0
        return {"tp": tp, "fp": fp, "fn": fn,
                "precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4)}

    out = {}
    for label, exact in (("span_exact", True), ("span_overlap", False)):
        used: set[int] = set()
        tp = 0
        for m in sorted(mentions, key=lambda x: (x["start"], x["end"], x["name"])):
            hit = None
            for i, g in enumerate(gt_entities):
                if i in used:
                    continue
                if exact:
                    ok = g["start"] == m["start"] and g["end"] == m["end"]
                else:
                    ok = min(m["end"], g["end"]) - max(m["start"], g["start"]) > 0
                if ok:
                    hit = i
                    break
            if hit is not None:
                used.add(hit)
                tp += 1
        out[label] = _prf(tp, len(mentions) - tp, len(gt_entities) - tp)
    return out


# ---------------------------------------------------------------------------
# Ejecucion de una fuente en una condicion
# ---------------------------------------------------------------------------
def reachable_relations(corpus, source_id: str, entities: list[dict]) -> dict:
    """Techo de RECALL impuesto por el extractor, con independencia del motor.

    Una relacion del ground truth es ALCANZABLE si ambos extremos (`subject_id`
    y `object_id`) estan presentes entre los ids asignados a las entidades de
    entrada. Si no lo estan, el motor NO PUEDE emparejarla por construccion: es
    un fallo imputable integramente al extractor (o a la politica de ids), no al
    motor. Es una cota SUPERIOR: estar presentes no garantiza que el generador de
    pares los junte (contexto de frase, distancia...).
    """
    ids = {e["id"] for e in entities}
    total = 0
    reach = 0
    for r in corpus.relations:
        if r["source_id"] != source_id:
            continue
        total += 1
        if str(r["subject_id"]) in ids and str(r["object_id"]) in ids:
            reach += 1
    return {"total": total, "reachable": reach}


def run_source_condition(corpus, source_id: str, condition: str, *, mode: str,
                         predicate_selector: Optional[str]) -> tuple:
    """Ejecuta el pipeline REAL sobre una fuente en la condicion indicada.

    Devuelve (SourceRun, info_de_entidades). Para `gt_perfect` se delega
    integramente en `runner.run_source` (camino autoritativo, sin tocar nada).
    """
    text = corpus.sources[source_id]
    workspace = corpus.workspace_by_source[source_id]
    gt_entities, gt_notes = _runner.derive_entities(source_id, text, corpus.relations)

    if condition == "gt_perfect":
        sr = _runner.run_source(corpus, source_id, mode=mode,
                                predicate_selector=predicate_selector)
        info = {"condition": condition, "source_id": source_id,
                "n_entities_input": len(sr.entities),
                "n_gt_mentions": len(gt_entities),
                "extractor_notes": [], "id_notes": [],
                "entity_detection": None,
                "unmatched_mentions": 0, "matched_mentions": len(sr.entities),
                "distinct_gt_ids_recovered": len({e["id"] for e in sr.entities}),
                "distinct_gt_ids_total": len({e["id"] for e in gt_entities}),
                "reachable": reachable_relations(corpus, source_id, sr.entities)}
        return sr, info

    policy = "strict" if condition == "extractor_strict" else "lax"
    mentions, ext_notes = extractor_mentions(source_id, text, workspace)
    entities, id_notes = assign_ids(mentions, gt_entities, policy)

    payload = _runner.build_payload(source_id, text, workspace, entities)
    config = _runner._config_for_mode(mode, predicate_selector=predicate_selector)
    t0 = time.perf_counter()
    output = _run_pipeline(payload, config=config)  # proveedores off: jamas red
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    if _runner.uses_ensemble(mode):
        preds = _runner.extract_predictions_ensemble(output)
    else:
        preds = _runner.extract_predictions(output)

    sr = _runner.SourceRun(
        source_id=source_id, workspace=workspace, output=output, predictions=preds,
        entities=entities, derivation_notes=list(gt_notes) + ext_notes, elapsed_ms=elapsed_ms,
    )
    matched = sum(1 for e in entities if not e["id"].startswith(UNMATCHED_PREFIX))
    info = {
        "condition": condition, "source_id": source_id,
        "n_entities_input": len(entities), "n_gt_mentions": len(gt_entities),
        "extractor_notes": ext_notes, "id_notes": id_notes,
        "entity_detection": entity_detection_metrics(mentions, gt_entities),
        "unmatched_mentions": len(entities) - matched, "matched_mentions": matched,
        "distinct_gt_ids_recovered": len(
            {e["id"] for e in entities if not e["id"].startswith(UNMATCHED_PREFIX)}),
        "distinct_gt_ids_total": len({e["id"] for e in gt_entities}),
        "reachable": reachable_relations(corpus, source_id, entities),
    }
    return sr, info


def run_condition(corpus, condition: str, *, mode: str,
                  predicate_selector: Optional[str]) -> tuple:
    """Ejecuta TODAS las fuentes del corpus en una condicion y arma un BenchmarkRun."""
    source_runs = []
    infos = []
    versions: dict = {}
    for sid in sorted(corpus.sources):
        sr, info = run_source_condition(corpus, sid, condition, mode=mode,
                                        predicate_selector=predicate_selector)
        source_runs.append(sr)
        infos.append(info)
        if not versions:
            versions = dict(sr.output["versions"])
    run = _runner.BenchmarkRun(
        mode=mode,
        config=_runner._config_for_mode(mode, predicate_selector=predicate_selector).to_dict(),
        versions=versions,
        source_runs=source_runs,
        corpus_hashes=dict(corpus.corpus_hashes),
        code_sha=_runner._code_sha(),
        source_ids=sorted(corpus.sources),
        provider_status={},
        ensemble=_runner.uses_ensemble(mode),
    )
    return run, infos


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", nargs="+", default=["B1", "H1", "H2"], choices=sorted(CORPORA))
    ap.add_argument("--mode", nargs="+", default=["baseline1"], choices=sorted(_runner.MODES))
    ap.add_argument("--selector", nargs="+", default=["v1", "v2"], choices=["v1", "v2"])
    ap.add_argument("--condition", nargs="+", default=list(CONDITIONS), choices=CONDITIONS)
    ap.add_argument("--out", default=None, help="ruta del JSON de salida")
    args = ap.parse_args(argv)

    results = []
    for corpus_key in args.corpus:
        corpus = _runner.load_corpus(CORPORA[corpus_key], verify=True)
        for mode in args.mode:
            for selector in args.selector:
                for condition in args.condition:
                    run, infos = run_condition(corpus, condition, mode=mode,
                                               predicate_selector=selector)
                    rep = _report.build_report(corpus, run, check_determinism=False)
                    results.append({
                        "corpus": corpus_key,
                        "corpus_dir": str(CORPORA[corpus_key]),
                        "mode": mode,
                        "predicate_selector": selector,
                        "condition": condition,
                        "report": rep,
                        "entity_info": infos,
                    })
                    st = rep["metrics"]["structural_quality"]
                    ge = rep["metrics"]["global_existence"]
                    print(
                        f"{corpus_key:3s} {mode:12s} sel={selector} {condition:17s} "
                        f"pair_F1={ge['f1']:.4f} (TP={ge['tp']} FP={ge['fp']} FN={ge['fn']}) "
                        f"pred={st['predicate_correct']['rate']:.4f} "
                        f"dir={st['direction_correct']['rate']:.4f} "
                        f"tipos={st['types_correct']['rate']:.4f} "
                        f"strictF1={rep['metrics']['strict_predicate']['f1']:.4f}",
                        flush=True,
                    )

    payload = {
        "driver": "chain_benchmark-v1",
        "harness": "relations/benchmark (importado sin modificar)",
        "extractor": "review.extractor.extract_from_segments (heuristico real)",
        "providers": "NOT_EXECUTED (offline; sin red, sin Ollama, sin NVIDIA)",
        "results": results,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"\nJSON -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
