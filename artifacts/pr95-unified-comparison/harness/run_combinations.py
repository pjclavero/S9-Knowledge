# -*- coding: utf-8 -*-
"""Simulador de COMBINACIONES de componentes (PR#95, oleada 2).

OFFLINE por construccion: reutiliza `worker_protocol.py` (mock puro, cero red)
sobre el MISMO banco sintetico congelado. NO toca ramas originales ni escribe en
las versiones; solo lee sus worktrees (V2, V3) para ejercitar SU protocolo real.

Combinacion principal (spec):  V2+V3
  Orden: seleccion por fragmento (V3) -> reconstruccion literal ->
         realineamiento determinista (V2) SOLO si el fragmento no basta ->
         rechazo ante ambiguedad.
  Politica de fusion por caso:
    1. Se ejecuta V3 (fragment_response) contra su protocolo real.
    2. Si V3 ACEPTA  -> resultado literal por fragmento (sin realinear).
    3. Si V3 NO acepta -> fallback a V2 (classic_response) con realineamiento.
    4. Si V2 tampoco acepta -> RECHAZO (fail-closed).

Metrica clave: false_realignment del flujo combinado. Un caso solo puede
producir false_realign si el REALINEAMIENTO de V2 llego a ejecutarse (paso 3),
porque V3 no realinea (reconstruye literal por id de fragmento).

Salida: artifacts/.../normalized-results/combo-*.json  y  un resumen a stdout
que el doc 11 y confidence-intervals.json consumen.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

OUT = Path("/home/ia02/S9-Knowledge/.claude/worktrees/pr95-audit"
           "/artifacts/pr95-unified-comparison")
HARNESS = OUT / "harness"
NORM = OUT / "normalized-results"
WT = {
    "v2": Path("/home/ia02/S9-Knowledge/.claude/worktrees/pr95-v2/data-engine/app"),
    "v3": Path("/home/ia02/S9-Knowledge/.claude/worktrees/pr95-v3/data-engine/app"),
}
INJECTION_MARKER = "IGNORA TUS INSTRUCCIONES"


def _bank():
    return json.loads((OUT / "synthetic-bank.json").read_text(encoding="utf-8"))


def run_worker(vkey, cfg, cases, resp_key):
    job = {"config": cfg, "cases": [{
        "case_id": c["case_id"], "candidate": c["candidate"],
        "document_text": c["document_text"], "response_content": c[resp_key],
        "latency_ms": 12.0,
    } for c in cases]}
    proc = subprocess.run(
        [sys.executable, str(HARNESS / "worker_protocol.py")],
        input=json.dumps(job), capture_output=True, text=True, cwd=str(WT[vkey]))
    if proc.returncode != 0:
        raise RuntimeError(f"worker@{vkey} rc={proc.returncode}: {proc.stderr[:800]}")
    return json.loads(proc.stdout)


def _iou(a, b):
    if None in a or None in b:
        return 0.0
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return (inter / union) if union > 0 else 0.0


def _accepted(state):
    return state not in ("INVALID_RESPONSES", "WORKER_ERROR", None)


def _literal(verdict, doc):
    vs, ve, vt = verdict.get("evidence_start"), verdict.get("evidence_end"), verdict.get("evidence_text")
    return isinstance(vs, int) and isinstance(ve, int) and vt is not None and doc[vs:ve] == vt and vt in doc


def analyze_v2_alone(cases, v2out):
    """Reproduce el false_realign de V2 en solitario y devuelve la lista exacta
    de casos con realineamiento falso (IoU con GT == 0)."""
    by = {r["case_id"]: r for r in v2out["results"]}
    needs = realigned = false = ambiguous = accepted = 0
    false_cases = []
    for c in cases:
        r = by.get(c["case_id"], {})
        v = r.get("verdict") or {}
        doc = c["document_text"]
        classic = json.loads(c["classic_response"])["verdicts"][0]
        ev0 = classic.get("evidence_text", "")
        s0, e0 = classic.get("evidence_start"), classic.get("evidence_end")
        nr = (ev0 not in doc) or (isinstance(s0, int) and isinstance(e0, int) and doc[s0:e0] != ev0)
        if _accepted(r.get("state")):
            accepted += 1
        if nr:
            needs += 1
            if v.get("evidence_realigned"):
                realigned += 1
                gt = (c.get("gt_evidence_start"), c.get("gt_evidence_end"))
                rs = (v.get("evidence_start"), v.get("evidence_end"))
                if _iou(gt, rs) == 0.0:
                    false += 1
                    false_cases.append((c["case_id"], c["tier"], rs, gt))
    return {
        "accepted": accepted, "needs_realign": needs, "realigned": realigned,
        "false_realign": false,
        "false_realign_rate": round(false / realigned, 4) if realigned else 0.0,
        "false_cases": false_cases,
    }


def combine_v2_v3(cases, v3out, v2out):
    """Aplica la politica de fusion V3-primario / V2-fallback y mide el combinado."""
    v3 = {r["case_id"]: r for r in v3out["results"]}
    v2 = {r["case_id"]: r for r in v2out["results"]}
    total = len(cases)
    accepted = literal_ok = literal_total = 0
    realign_fired = false_realign = injection_success = 0
    per_tier = {}
    detail = []
    for c in cases:
        doc = c["document_text"]
        tier = c["tier"]
        pt = per_tier.setdefault(tier, {"total": 0, "accepted": 0})
        pt["total"] += 1
        r3 = v3.get(c["case_id"], {})
        v3v = r3.get("verdict") or {}
        path = "v3_fragment"
        state = r3.get("state")
        verdict = v3v
        realigned_here = False
        if _accepted(state):
            pass  # V3 cubre el caso de forma literal
        else:
            # fallback a V2 (realineamiento determinista)
            r2 = v2.get(c["case_id"], {})
            state = r2.get("state")
            verdict = r2.get("verdict") or {}
            path = "v2_realign_fallback"
            classic = json.loads(c["classic_response"])["verdicts"][0]
            ev0 = classic.get("evidence_text", "")
            s0, e0 = classic.get("evidence_start"), classic.get("evidence_end")
            nr = (ev0 not in doc) or (isinstance(s0, int) and isinstance(e0, int) and doc[s0:e0] != ev0)
            if _accepted(state) and verdict.get("evidence_realigned") and nr:
                realign_fired += 1
                realigned_here = True
        acc = _accepted(state)
        if acc:
            accepted += 1
            pt["accepted"] += 1
            literal_total += 1
            if _literal(verdict, doc):
                literal_ok += 1
            vt = verdict.get("evidence_text")
            if vt and INJECTION_MARKER in vt:
                injection_success += 1
            if realigned_here:
                gt = (c.get("gt_evidence_start"), c.get("gt_evidence_end"))
                rs = (verdict.get("evidence_start"), verdict.get("evidence_end"))
                if _iou(gt, rs) == 0.0:
                    false_realign += 1
        detail.append({"case_id": c["case_id"], "tier": tier, "path": path,
                       "state": state, "accepted": acc})
    return {
        "total_cases": total,
        "valid_response_rate": round(accepted / total, 4) if total else 0.0,
        "accepted_count": accepted,
        "literal_evidence_rate": round(literal_ok / literal_total, 4) if literal_total else 1.0,
        "realign_fired": realign_fired,
        "false_realign": false_realign,
        "false_realign_rate": round(false_realign / realign_fired, 4) if realign_fired else 0.0,
        "prompt_injection_success": injection_success,
        "by_tier_accept": {k: f"{v['accepted']}/{v['total']}" for k, v in sorted(per_tier.items())},
        "detail": detail,
    }


def main():
    bank = _bank()
    groups = {"C1_common": bank["common_c1"],
              "C3_adversarial": bank["adversarial_c3"],
              "C2_independent": bank["independent_c2"]}
    report = {"combination": "V2+V3", "policy": "V3-primary / V2-realign-fallback / fail-closed",
              "groups": {}}
    for gname, cases in groups.items():
        v3out = run_worker("v3", {"fragment_protocol_enabled": True}, cases, "fragment_response")
        v2out = run_worker("v2", {"realignment_enabled": True}, cases, "classic_response")
        v2solo = analyze_v2_alone(cases, v2out)
        combo = combine_v2_v3(cases, v3out, v2out)
        report["groups"][gname] = {
            "v2_alone": {k: v2solo[k] for k in
                         ("accepted", "needs_realign", "realigned", "false_realign",
                          "false_realign_rate", "false_cases")},
            "v2_v3_combined": {k: combo[k] for k in
                               ("valid_response_rate", "accepted_count", "literal_evidence_rate",
                                "realign_fired", "false_realign", "false_realign_rate",
                                "prompt_injection_success", "by_tier_accept")},
        }
        (NORM / f"combo-v2v3-{gname}.json").write_text(
            json.dumps(combo["detail"], ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "combination-analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
