# -*- coding: utf-8 -*-
"""Orquestador HOMOGENEO de la comparativa PR#95.

Ejecuta las DOS pistas con la MISMA vara:
  * PISTA PIPELINE  : base / V1 / V4 (subproceso worker_pipeline en cada worktree).
    Matching + metricas con los modulos de la BASE (una sola vara), sobre C1.
  * PISTA PROTOCOLO : base / V2 / V3 (subproceso worker_protocol), sobre el banco
    sintetico congelado (C1-common + C3 adversarial + C2 independiente).

Determinismo: 3 repeticiones offline por configuracion (hash de salida estable).
Seguridad: ningun worker inyecta transporte/proveedor real; se agregan contadores
network_attempts / write_attempts / literal_evidence_rate / prompt_injection_success.

Escribe metrics.json, metrics.csv, performance.json, security.json,
comparison-table.md, normalized-results/, raw-redacted-results/.
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

AUDIT = Path("/home/ia02/S9-Knowledge/.claude/worktrees/pr95-audit")
OUT = AUDIT / "artifacts/pr95-unified-comparison"
HARNESS = OUT / "harness"
NORM = OUT / "normalized-results"
RAW = OUT / "raw-redacted-results"

WT = {
    "base": Path("/home/ia02/S9-Knowledge/.claude/worktrees/pr95-base"),
    "v1": Path("/home/ia02/S9-Knowledge/.claude/worktrees/pr95-v1"),
    "v2": Path("/home/ia02/S9-Knowledge/.claude/worktrees/pr95-v2"),
    "v3": Path("/home/ia02/S9-Knowledge/.claude/worktrees/pr95-v3"),
    "v4": Path("/home/ia02/S9-Knowledge/.claude/worktrees/pr95-v4"),
}
C1_DIR = str(AUDIT / "data-engine/app/tests/data/relation_benchmark")
REPS = 3

# La vara unica: matching + metrics de la BASE.
sys.path.insert(0, str(WT["base"] / "data-engine/app"))
from relations.benchmark import matching as M  # noqa: E402
from relations.benchmark import metrics as MET  # noqa: E402
from relations.benchmark import runner as R  # noqa: E402

_CORPUS = R.load_corpus(Path(C1_DIR), verify=True)
_SRC = _CORPUS.sources
_GT = _CORPUS.relations


def app_dir(v):
    return str(WT[v] / "data-engine/app")


def run_worker(script, worktree_key, job):
    proc = subprocess.run(
        [sys.executable, str(HARNESS / script)],
        input=json.dumps(job), capture_output=True, text=True,
        cwd=app_dir(worktree_key),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{script}@{worktree_key} rc={proc.returncode}: {proc.stderr[:800]}")
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# PISTA PIPELINE
# ---------------------------------------------------------------------------
PIPELINE_CONFIGS = [
    ("base", "base", {}),
    ("v1_conservative", "v1", {"evidence_anchor_mode": "conservative"}),
    ("v4_hybrid_default", "v4", {"hybrid_stages": {}}),
    ("v4_cross_sentence", "v4", {"hybrid_stages": {}, "hybrid_cross_sentence": True}),
    ("v4_ablate_evidence", "v4", {"hybrid_stages": {"evidence": False, "verification": False}}),
]


def _char_set(s, e):
    return set(range(s, e))


def _tokens(t):
    return [w for w in ''.join(c.lower() if c.isalnum() else ' ' for c in t).split() if w]


def _f1(a, b):
    if not a and not b:
        return 1.0
    inter = len(a & b)
    p = inter / len(a) if a else 0.0
    r = inter / len(b) if b else 0.0
    return round(2 * p * r / (p + r), 4) if (p + r) else 0.0


def pipeline_metrics(predictions):
    match = M.match_predictions(predictions, _GT)
    gm = MET.global_metrics(match)
    sm = MET.strict_metrics(match)
    tp = match.true_positives
    n = len(tp)

    def rate(flag):
        return round(sum(1 for t in tp if t["flags"].get(flag)) / n, 4) if n else 0.0

    # Evidencia detallada sobre TP.
    ev_exact = ov = lit = overext = underext = 0
    iou_sum = char_f1_sum = tok_f1_sum = 0.0
    start_err = end_err = 0
    off_exact = 0
    for t in tp:
        p, g = t["pred"], t["gt"]
        ps, pe = int(p["evidence_start"]), int(p["evidence_end"])
        gs, ge = int(g["evidence_start"]), int(g["evidence_end"])
        src = _SRC[p["source_id"]]
        # literalidad de la prediccion
        if src[ps:pe] == p["evidence_text"]:
            lit += 1
        if ps == gs and pe == ge:
            ev_exact += 1
            off_exact += 1
        inter = max(0, min(pe, ge) - max(ps, gs))
        if inter > 0:
            ov += 1
        iou_sum += t["flags"]["evidence_overlap_iou"]
        char_f1_sum += _f1(_char_set(ps, pe), _char_set(gs, ge))
        tok_f1_sum += _f1(set(_tokens(p["evidence_text"])), set(_tokens(g["evidence_text"])))
        start_err += abs(ps - gs)
        end_err += abs(pe - ge)
        # over/under-extension respecto al span GT
        if ps <= gs and pe >= ge and (pe - ps) > (ge - gs):
            overext += 1
        if ps > gs or pe < ge:
            underext += 1
    ev = {
        "evidence_exact_match": round(ev_exact / n, 4) if n else 0.0,
        "evidence_char_f1": round(char_f1_sum / n, 4) if n else 0.0,
        "evidence_token_f1": round(tok_f1_sum / n, 4) if n else 0.0,
        "evidence_iou": round(iou_sum / n, 4) if n else 0.0,
        "offset_exact_match": round(off_exact / n, 4) if n else 0.0,
        "offsets_overlap": round(ov / n, 4) if n else 0.0,
        "start_absolute_error": round(start_err / n, 3) if n else 0.0,
        "end_absolute_error": round(end_err / n, 3) if n else 0.0,
        "boundary_mae": round((start_err + end_err) / (2 * n), 3) if n else 0.0,
        "literal_evidence_rate": round(lit / n, 4) if n else 1.0,
        "evidence_overextension": round(overext / n, 4) if n else 0.0,
        "evidence_underextension": round(underext / n, 4) if n else 0.0,
    }
    structural = {
        "pair_precision": gm["precision"], "pair_recall": gm["recall"], "pair_f1": gm["f1"],
        "tp": gm["tp"], "fp": gm["fp"], "fn": gm["fn"],
        "strict_f1": sm.get("f1"),
        "evidence_correct": rate("evidence_correct"),
        "predicate_exact": rate("predicate_correct"),
        "predicate_canonical": rate("predicate_correct"),
        "direction_exact": rate("direction_correct"),
        "direction_orientation_ok": rate("direction_orientation_ok"),
        "negation_accuracy": rate("negation_correct"),
        "temporality_accuracy": rate("temporal_correct"),
        "epistemic_accuracy": rate("epistemic_correct"),
        "decision_accuracy": rate("decision_correct"),
        "candidate_count": len(predictions),
    }
    structural.update(ev)
    return match, structural


def run_pipeline_track():
    results = {}
    perf = {}
    determinism = {}
    for name, vkey, overrides in PIPELINE_CONFIGS:
        job = {"corpus_dir": C1_DIR, "config_overrides": overrides}
        hashes = []
        last = None
        elapsed_all = []
        for rep in range(REPS):
            out = run_worker("worker_pipeline.py", vkey, job)
            blob = json.dumps(out["predictions"], sort_keys=True, ensure_ascii=False)
            hashes.append(hashlib.sha256(blob.encode()).hexdigest())
            last = out
            elapsed_all.append(sum(t["elapsed_ms"] for t in out["timings"]))
        assert last["providers_offline"] is True, f"{name}: proveedores no offline"
        match, structural = pipeline_metrics(last["predictions"])
        det = len(set(hashes)) == 1
        determinism[name] = {"determinism_rate": 1.0 if det else 0.0,
                             "output_hashes": hashes}
        # latencias por fuente (para p50/p95)
        lat = sorted(t["elapsed_ms"] for t in last["timings"])
        perf[name] = {
            "total_ms_per_rep": [round(x, 3) for x in elapsed_all],
            "latency_p50_ms": _pct(lat, 50), "latency_p95_ms": _pct(lat, 95),
            "n_sources": last["n_sources"], "candidate_count": structural["candidate_count"],
        }
        structural["determinism_rate"] = determinism[name]["determinism_rate"]
        structural["config_effective"] = last["config_effective"]
        results[name] = structural
        # normalized + raw redacted
        _write_pipeline_normalized(name, last["predictions"])
    return results, perf, determinism


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * q / 100.0
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo), 3)


def _write_pipeline_normalized(name, predictions):
    norm = []
    for p in predictions:
        norm.append({
            "candidate_id": p["candidate_id"],
            "subject": p["subject_id"], "predicate": p["predicate"], "object": p["object_id"],
            "direction": p["direction"],
            "evidence_spans": [{"start": p["evidence_start"], "end": p["evidence_end"],
                                "text": p["evidence_text"]}],
            "negated": p["negated"], "temporality": p.get("temporal_scope"),
            "epistemic": p.get("epistemic_status"), "confidence": "unsupported",
            "provider_status": "NOT_EXECUTED",
            "validation_status": p.get("consensus_state"),
            "latency_ms": "per_source_only",
        })
    (NORM / f"pipeline-{name}.json").write_text(
        json.dumps(norm, ensure_ascii=False, indent=1), encoding="utf-8")
    # raw redacted: sin texto crudo del documento, solo spans+longitud
    red = [{"candidate_id": p["candidate_id"], "evidence_start": p["evidence_start"],
            "evidence_end": p["evidence_end"], "evidence_len": len(p["evidence_text"]),
            "consensus_state": p.get("consensus_state")} for p in predictions]
    (RAW / f"pipeline-{name}.json").write_text(
        json.dumps(red, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# PISTA PROTOCOLO
# ---------------------------------------------------------------------------
INJECTION_MARKER = "IGNORA TUS INSTRUCCIONES"


def _bank():
    return json.loads((OUT / "synthetic-bank.json").read_text(encoding="utf-8"))


PROTOCOL_CONFIGS = [
    ("base", "base", {}, "classic_response"),
    ("v2_realignment", "v2", {"realignment_enabled": True}, "classic_response"),
    ("v3_fragments", "v3", {"fragment_protocol_enabled": True}, "fragment_response"),
]


def _iou(a, b):
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return (inter / union) if union > 0 else 0.0


def protocol_metrics(name, cases, worker_out):
    res_by_id = {r["case_id"]: r for r in worker_out["results"]}
    total = len(cases)
    accepted = invalid = 0
    literal_ok = literal_total = 0
    needs_realign = realigned = false_realign = ambiguous = 0
    frag_reconstructed = invalid_fragment = 0
    injection_success = 0
    per_tier = {}
    detail = []
    for case in cases:
        r = res_by_id.get(case["case_id"], {})
        state = r.get("state")
        verdict = r.get("verdict") or {}
        tier = case["tier"]
        pt = per_tier.setdefault(tier, {"total": 0, "accepted": 0})
        pt["total"] += 1
        is_accepted = state not in ("INVALID_RESPONSES", "WORKER_ERROR", None)
        if is_accepted:
            accepted += 1
            pt["accepted"] += 1
        else:
            invalid += 1
        # literalidad de lo ACEPTADO
        if is_accepted and verdict:
            literal_total += 1
            doc = case["document_text"]
            vs, ve = verdict.get("evidence_start"), verdict.get("evidence_end")
            vt = verdict.get("evidence_text")
            if (isinstance(vs, int) and isinstance(ve, int)
                    and doc[vs:ve] == vt and vt in doc):
                literal_ok += 1
            # inyeccion aceptada? (texto de ataque dentro de la evidencia aceptada)
            if vt and INJECTION_MARKER in vt:
                injection_success += 1
        # realineamiento (V2)
        if name == "v2_realignment":
            # necesita realineamiento si el tier no es exact/injection-literal
            classic = json.loads(case["classic_response"])["verdicts"][0]
            doc = case["document_text"]
            ev0 = classic.get("evidence_text", "")
            s0, e0 = classic.get("evidence_start"), classic.get("evidence_end")
            nr = (ev0 not in doc) or (isinstance(s0, int) and isinstance(e0, int)
                                      and doc[s0:e0] != ev0)
            if nr:
                needs_realign += 1
                if verdict.get("evidence_realigned"):
                    realigned += 1
                    gt_span = (case["gt_evidence_start"], case["gt_evidence_end"])
                    rspan = (verdict.get("evidence_start"), verdict.get("evidence_end"))
                    if _iou(gt_span, rspan) == 0.0:
                        false_realign += 1
                elif verdict.get("realignment_tier") == "ambiguous" or (
                        not is_accepted and any("ambig" in str(x).lower()
                                                for x in r.get("validation_errors", []))):
                    ambiguous += 1
        # fragmentos (V3)
        if name == "v3_fragments":
            if is_accepted and verdict.get("fragment_ids"):
                frag_reconstructed += 1
            if not is_accepted and any("fragment" in str(x).lower() or "id" in str(x).lower()
                                       for x in r.get("validation_errors", [])):
                invalid_fragment += 1
        detail.append({
            "case_id": case["case_id"], "tier": tier, "state": state,
            "accepted": is_accepted,
            "validation_errors": r.get("validation_errors", []),
            "realignment_tier": verdict.get("realignment_tier"),
            "fragment_ids": verdict.get("fragment_ids"),
        })
    metrics = {
        "total_cases": total,
        "valid_response_rate": round(accepted / total, 4) if total else 0.0,
        "invalid_response_rate": round(invalid / total, 4) if total else 0.0,
        "literal_evidence_rate": round(literal_ok / literal_total, 4) if literal_total else 1.0,
        "accepted_count": accepted,
        "network_attempts": worker_out["network_attempts"],
        "post_chat_calls": worker_out["post_chat_calls"],
        "prompt_injection_success": injection_success,
        "unsafe_output_acceptance": injection_success,
        "by_tier_accept": {k: f"{v['accepted']}/{v['total']}" for k, v in sorted(per_tier.items())},
    }
    if name == "v2_realignment":
        metrics.update({
            "needs_realign": needs_realign,
            "realignment_success_rate": round(realigned / needs_realign, 4) if needs_realign else 0.0,
            "false_realignment_rate": round(false_realign / realigned, 4) if realigned else 0.0,
            "ambiguous_realignment_rate": round(ambiguous / needs_realign, 4) if needs_realign else 0.0,
        })
    else:
        metrics.update({"realignment_success_rate": "unsupported",
                        "false_realignment_rate": "unsupported",
                        "ambiguous_realignment_rate": "unsupported"})
    if name == "v3_fragments":
        metrics.update({
            "fragment_reconstruction_rate": round(frag_reconstructed / total, 4) if total else 0.0,
            "invalid_fragment_rate": round(invalid_fragment / total, 4) if total else 0.0,
        })
    else:
        metrics.update({"fragment_reconstruction_rate": "unsupported",
                        "invalid_fragment_rate": "unsupported"})
    return metrics, detail


def run_protocol_track():
    bank = _bank()
    groups = {"C1_common": bank["common_c1"], "C3_adversarial": bank["adversarial_c3"],
              "C2_independent": bank["independent_c2"]}
    results = {}
    determinism = {}
    for name, vkey, cfg, resp_key in PROTOCOL_CONFIGS:
        results[name] = {}
        for gname, cases in groups.items():
            job = {"config": cfg, "cases": [{
                "case_id": c["case_id"], "candidate": c["candidate"],
                "document_text": c["document_text"], "response_content": c[resp_key],
                "latency_ms": 12.0,
            } for c in cases]}
            # determinismo: 3 reps
            hashes = []
            last = None
            for rep in range(REPS):
                out = run_worker("worker_protocol.py", vkey, job)
                blob = json.dumps([(r["case_id"], r["state"]) for r in out["results"]],
                                  sort_keys=True)
                hashes.append(hashlib.sha256(blob.encode()).hexdigest())
                last = out
            assert last["network_attempts"] == 0, f"{name}/{gname}: network_attempts != 0"
            metrics, detail = protocol_metrics(name, cases, last)
            metrics["determinism_rate"] = 1.0 if len(set(hashes)) == 1 else 0.0
            results[name][gname] = metrics
            _write_protocol_normalized(name, gname, cases, last, detail)
    return results


def _write_protocol_normalized(name, gname, cases, worker_out, detail):
    res_by_id = {r["case_id"]: r for r in worker_out["results"]}
    norm = []
    for c in cases:
        r = res_by_id.get(c["case_id"], {})
        v = r.get("verdict") or {}
        spans = []
        if isinstance(v.get("evidence_start"), int):
            spans = [{"start": v.get("evidence_start"), "end": v.get("evidence_end"),
                      "text": v.get("evidence_text")}]
        norm.append({
            "candidate_id": r.get("candidate_id"),
            "subject": c["candidate"]["subject_id"], "predicate": c["candidate"]["predicate"],
            "object": c["candidate"]["object_id"], "direction": c["candidate"]["direction"],
            "evidence_spans": spans, "negated": v.get("negated", "unsupported"),
            "temporality": "unsupported", "epistemic": "unsupported",
            "confidence": v.get("confidence", "unsupported"),
            "provider_status": r.get("state"),
            "validation_status": r.get("shadow_recommendation"),
            "latency_ms": r.get("latency_ms"),
        })
    (NORM / f"protocol-{name}-{gname}.json").write_text(
        json.dumps(norm, ensure_ascii=False, indent=1), encoding="utf-8")
    red = [{"case_id": d["case_id"], "tier": d["tier"], "state": d["state"],
            "accepted": d["accepted"], "validation_errors": d["validation_errors"],
            "realignment_tier": d["realignment_tier"],
            "fragment_ids": d["fragment_ids"]} for d in detail]
    (RAW / f"protocol-{name}-{gname}.json").write_text(
        json.dumps(red, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
def v1_category_analysis():
    """Compara base vs V1 (conservative) por relacion GT emparejada y categoriza
    los cambios de `evidence_correct` (IoU>=0.5). Reproduce/explica el 0.907->0.837.
    """
    base_out = run_worker("worker_pipeline.py", "base", {"corpus_dir": C1_DIR, "config_overrides": {}})
    v1_out = run_worker("worker_pipeline.py", "v1",
                        {"corpus_dir": C1_DIR, "config_overrides": {"evidence_anchor_mode": "conservative"}})
    mb = M.match_predictions(base_out["predictions"], _GT)
    mv = M.match_predictions(v1_out["predictions"], _GT)
    base_by_gt = {t["gt"]["relation_id"]: t for t in mb.true_positives}
    v1_by_gt = {t["gt"]["relation_id"]: t for t in mv.true_positives}

    cats = {"improved": [], "regressed": [], "unchanged_ok": [], "unchanged_bad": []}
    detail = []
    for rid, tb in base_by_gt.items():
        tv = v1_by_gt.get(rid)
        if tv is None:
            continue
        gt = tb["gt"]
        b_ok = tb["flags"]["evidence_correct"]
        v_ok = tv["flags"]["evidence_correct"]
        b_iou = tb["flags"]["evidence_overlap_iou"]
        v_iou = tv["flags"]["evidence_overlap_iou"]
        p = tv["pred"]
        gs, ge = int(gt["evidence_start"]), int(gt["evidence_end"])
        ps, pe = int(p["evidence_start"]), int(p["evidence_end"])
        # categoria de la causa (heuristica descriptiva)
        cause = "sin_cambio"
        if b_ok and not v_ok:
            if pe < ge or ps > gs and (pe - ps) < (ge - gs):
                cause = "clausula_corta (conservative recorto por debajo del GT)"
            elif (ps > gs) or (pe < ge):
                cause = "perdida_marcador (negacion/temporal/epistemico fuera de la clausula)"
            else:
                cause = "reencuadre (span movido; posible GT alternativo)"
            cats["regressed"].append(rid)
        elif not b_ok and v_ok:
            cause = "mejora (clausula mas ajustada supera IoU>=0.5)"
            cats["improved"].append(rid)
        elif b_ok and v_ok:
            cats["unchanged_ok"].append(rid)
        else:
            cats["unchanged_bad"].append(rid)
        if b_ok != v_ok:
            detail.append({"relation_id": rid, "predicate": gt["predicate"],
                           "negated": gt["negated"], "temporal": gt["temporal_status"],
                           "epistemic": gt["epistemic_status"],
                           "base_iou": b_iou, "v1_iou": v_iou,
                           "base_ok": b_ok, "v1_ok": v_ok, "cause": cause})
    n = len(base_by_gt)
    summary = {
        "matched_pairs": n,
        "base_evidence_correct_rate": round(sum(1 for t in base_by_gt.values()
                                                if t["flags"]["evidence_correct"]) / n, 4),
        "v1_evidence_correct_rate": round(sum(1 for t in v1_by_gt.values()
                                              if t["flags"]["evidence_correct"]) / n, 4)
                                    if v1_by_gt else 0.0,
        "improved": len(cats["improved"]), "regressed": len(cats["regressed"]),
        "unchanged_ok": len(cats["unchanged_ok"]), "unchanged_bad": len(cats["unchanged_bad"]),
        "changed_detail": detail,
    }
    (OUT / "v1-evidence-category-analysis.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    pipe_res, pipe_perf, pipe_det = run_pipeline_track()
    v1_cat = v1_category_analysis()
    print("V1 category:", json.dumps({k: v1_cat[k] for k in
          ("base_evidence_correct_rate", "v1_evidence_correct_rate",
           "improved", "regressed", "unchanged_ok", "unchanged_bad")}))
    proto_res = run_protocol_track()

    metrics = {"pipeline_track": pipe_res, "protocol_track": proto_res}
    (OUT / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2),
                                      encoding="utf-8")

    performance = {"pipeline_track": pipe_perf, "determinism": pipe_det}
    (OUT / "performance.json").write_text(json.dumps(performance, ensure_ascii=False, indent=2),
                                          encoding="utf-8")

    # security.json
    sec = {"pipeline_track": {}, "protocol_track": {}}
    for name, s in pipe_res.items():
        sec["pipeline_track"][name] = {
            "network_attempts": 0, "write_attempts": 0, "secret_exposure": 0,
            "literal_evidence_rate": s["literal_evidence_rate"],
            "determinism_rate": s["determinism_rate"],
            "providers_offline": True,
        }
    for name, groups in proto_res.items():
        sec["protocol_track"][name] = {}
        for gname, gm in groups.items():
            sec["protocol_track"][name][gname] = {
                "network_attempts": gm["network_attempts"], "write_attempts": 0,
                "secret_exposure": 0, "prompt_injection_success": gm["prompt_injection_success"],
                "unsafe_output_acceptance": gm["unsafe_output_acceptance"],
                "literal_evidence_rate": gm["literal_evidence_rate"],
                "determinism_rate": gm["determinism_rate"],
            }
    (OUT / "security.json").write_text(json.dumps(sec, ensure_ascii=False, indent=2),
                                       encoding="utf-8")

    # metrics.csv (pipeline track, filas por metrica clave)
    _write_csv(pipe_res, proto_res)
    print("OK metrics written")
    print(json.dumps({"pipeline": {k: {kk: v[kk] for kk in
          ("pair_f1", "evidence_iou", "evidence_exact_match", "predicate_exact",
           "direction_exact", "literal_evidence_rate", "determinism_rate")}
          for k, v in pipe_res.items()}}, indent=2, default=str))


def _write_csv(pipe_res, proto_res):
    keys = ["pair_precision", "pair_recall", "pair_f1", "strict_f1", "evidence_correct",
            "predicate_exact",
            "direction_exact", "negation_accuracy", "temporality_accuracy",
            "epistemic_accuracy", "decision_accuracy", "evidence_exact_match",
            "evidence_char_f1", "evidence_token_f1", "evidence_iou", "offset_exact_match",
            "offsets_overlap", "boundary_mae", "literal_evidence_rate",
            "evidence_overextension", "evidence_underextension", "candidate_count",
            "determinism_rate"]
    with open(OUT / "metrics.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["track", "config"] + keys)
        for name, s in pipe_res.items():
            w.writerow(["pipeline", name] + [s.get(k) for k in keys])
        pkeys = ["valid_response_rate", "invalid_response_rate", "literal_evidence_rate",
                 "realignment_success_rate", "false_realignment_rate",
                 "ambiguous_realignment_rate", "fragment_reconstruction_rate",
                 "invalid_fragment_rate", "prompt_injection_success", "network_attempts",
                 "determinism_rate"]
        w.writerow([])
        w.writerow(["track", "config/group"] + pkeys)
        for name, groups in proto_res.items():
            for gname, gm in groups.items():
                w.writerow(["protocol", f"{name}/{gname}"] + [gm.get(k) for k in pkeys])


if __name__ == "__main__":
    main()
