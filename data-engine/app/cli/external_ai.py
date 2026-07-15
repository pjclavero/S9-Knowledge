# -*- coding: utf-8 -*-
"""CLI de IA externa (Fase A: revisión multi-modelo en modo sombra).

Subcomandos: health | review | adjudicate | calibrate | report.
TODAS las operaciones de revisión requieren --shadow. Nada escribe en Neo4j ni
activa S9K_ALLOW_REAL_INGEST. Los outputs van a
output/reviews/<ws>/<sid>/external_ai/ (fuera de Git).
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

_CLI_DIR = Path(__file__).resolve().parent
_APP_DIR = _CLI_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))
_REPO_ROOT = _APP_DIR.parents[1]

from external_ai import require_shadow, PROMPT_VERSION, SCHEMA_VERSION
from external_ai.errors import ShadowModeRequired
from external_ai import registry, security
from external_ai.models import ReviewItem, ReviewBatchRequest


def _anon(source_id: str) -> str:
    return "src_" + hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:12]


def _ext_dir(ws: str, sid: str) -> Path:
    d = _REPO_ROOT / "output" / "reviews" / ws / sid / "external_ai"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_json(p: Path, default=None):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def build_review_request(workspace: str, source_id: str, glossary_limit: int = 30) -> ReviewBatchRequest:
    """Construye un ReviewBatchRequest sanitizado desde los outputs locales."""
    base = _REPO_ROOT / "output" / "reviews" / workspace / source_id
    candidates = _load_json(base / "candidates.json", []) or []
    segs = _load_json(base / "segments.classified.json", []) or []
    resolved = _load_json(base / "resolved.json", []) or []
    seg_text = {s.get("segment_id"): s.get("text", "") for s in segs}
    res_by_id = {}
    for r in resolved:
        cid = r.get("candidate_id")
        rr = r.get("resolution", r)
        if cid:
            res_by_id[cid] = rr

    from review.export_import import sanitize_text
    items = []
    for c in candidates:
        if c.get("kind") != "entity":
            continue
        cid = c.get("candidate_id")
        matches = []
        rr = res_by_id.get(cid, {})
        for m in (rr.get("alternatives") or []):
            matches.append(sanitize_text(str(m)))  # solo nombres canónicos sanitizados
        items.append(ReviewItem(
            candidate_id=cid, kind="entity", name=c.get("name"),
            entity_type=c.get("entity_type"), evidence=sanitize_text(str(c.get("evidence", ""))),
            local_confidence=float(c.get("confidence") or 0.0),
            segment_text=sanitize_text(str(seg_text.get(c.get("segment_id"), c.get("evidence", "")))),
            neo4j_matches=matches,
        ))
    # glosario mínimo (nombres canónicos de las coincidencias)
    glossary = sorted({m for it in items for m in it.neo4j_matches})[:glossary_limit]
    return ReviewBatchRequest(
        workspace=workspace, source_id=_anon(source_id), items=items,
        glossary=glossary, schema_version=SCHEMA_VERSION, prompt_version=PROMPT_VERSION,
    )


def cmd_health(args):
    provider = registry.get_provider(args.provider, _REPO_ROOT)
    h = provider.healthcheck()
    print(json.dumps(h.to_dict(), ensure_ascii=False, indent=2))
    if not h.ok:
        sys.exit(2)


def _run_reviewer(provider, request, model, role, out_dir):
    resp = provider.review_candidates(request, model, reviewer_role=role)
    (out_dir / f"review.{model.replace('/', '_')}.json").write_text(
        json.dumps(resp.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return resp


def cmd_review(args):
    require_shadow(args.shadow)
    provider = registry.get_provider(args.provider, _REPO_ROOT)
    models = [m.strip() for m in (args.models or ",".join(registry.review_models())).split(",") if m.strip()]
    if len(models) < 2:
        print("ABORTADO: se requieren 2 modelos revisores independientes (--models A,B).", file=sys.stderr)
        sys.exit(1)
    request = build_review_request(args.workspace, args.source_id)
    out_dir = _ext_dir(args.workspace, args.source_id)
    # request sanitizado + guard de secretos
    req_dict = request.to_dict()
    security.assert_no_secrets(req_dict)
    (out_dir / "request.sanitized.json").write_text(
        json.dumps(req_dict, ensure_ascii=False, indent=2), encoding="utf-8")

    resp_a = _run_reviewer(provider, request, models[0], "reviewer_a", out_dir)
    resp_b = _run_reviewer(provider, request, models[1], "reviewer_b", out_dir)

    from external_ai.consensus import compute_consensus, summarize
    from external_ai.prompts import build_adjudication_prompt  # noqa: F401 (usado indirectamente)
    adj_model = registry.adjudicator_model()

    def adjudicate_fn(cid):
        if not adj_model:
            return None
        # adjudica solo ese candidato
        single = ReviewBatchRequest(workspace=request.workspace, source_id=request.source_id,
                                    items=[it for it in request.items if it.candidate_id == cid],
                                    glossary=request.glossary, schema_version=request.schema_version,
                                    prompt_version=request.prompt_version)
        r = provider.review_candidates(single, adj_model, reviewer_role="adjudicator")
        decs = r.by_candidate()
        return decs.get(cid)

    results = compute_consensus(resp_a, resp_b, request, adjudicate_fn=adjudicate_fn)
    consensus = {"shadow_mode": True, "summary": summarize(results),
                 "results": [r.to_dict() for r in results]}
    (out_dir / "consensus.json").write_text(
        json.dumps(consensus, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(consensus["summary"], ensure_ascii=False, indent=2))
    print(f"\nOutputs (fuera de Git): {out_dir}")


def cmd_adjudicate(args):
    require_shadow(args.shadow)
    print("La adjudicación se ejecuta automáticamente dentro de 'review' para los conflictos.")
    print("Ver consensus.json (estado MODEL_CONFLICT -> campo adjudication).")


def cmd_calibrate(args):
    require_shadow(args.shadow)
    out_dir = _ext_dir(args.workspace, args.source_id)
    consensus = _load_json(out_dir / "consensus.json")
    if not consensus:
        print("ABORTADO: no hay consensus.json. Ejecuta primero 'review'.", file=sys.stderr)
        sys.exit(1)
    human = _load_json(Path(args.human_decisions))
    if human is None:
        print(f"ABORTADO: no se pudo leer human-decisions: {args.human_decisions}", file=sys.stderr)
        sys.exit(1)
    # human puede ser lista de log append-only o dict
    human_map = {}
    if isinstance(human, list):
        for e in human:
            cid = e.get("candidate_id")
            if cid:
                human_map[cid] = {"action": e.get("action"), **e}
    elif isinstance(human, dict):
        human_map = human

    from external_ai.calibration import calibrate, render_markdown
    from external_ai.models import ConsensusResult
    results = [ConsensusResult(**{k: r.get(k) for k in
               ("candidate_id", "state", "shadow_recommendation", "reviewer_a", "reviewer_b", "adjudication", "reason")})
               for r in consensus.get("results", [])]
    metrics = calibrate(results, human_map, meta=None)
    (out_dir / "calibration_report.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "calibration_report.md").write_text(render_markdown(metrics), encoding="utf-8")
    print(json.dumps({k: metrics[k] for k in metrics if not isinstance(metrics[k], (dict, list))},
                     ensure_ascii=False, indent=2))
    print(f"\nCalibración (fuera de Git): {out_dir}/calibration_report.md")


def cmd_report(args):
    out_dir = _ext_dir(args.workspace, args.source_id)
    for name in ("consensus.json", "calibration_report.json"):
        d = _load_json(out_dir / name)
        if d:
            print(f"=== {name} ===")
            print(json.dumps(d.get("summary", d), ensure_ascii=False, indent=2)[:2000])


def main():
    ap = argparse.ArgumentParser(description="IA externa (Fase A: revisión multi-modelo, modo sombra)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(p, shadow=False):
        p.add_argument("--provider", default="nvidia")
        if shadow:
            p.add_argument("--shadow", action="store_true")

    ph = sub.add_parser("health"); add_common(ph); ph.set_defaults(func=cmd_health)
    pr = sub.add_parser("review"); add_common(pr, shadow=True)
    pr.add_argument("--workspace", required=True); pr.add_argument("--source-id", required=True, dest="source_id")
    pr.add_argument("--models", default=None); pr.set_defaults(func=cmd_review)
    pa = sub.add_parser("adjudicate"); add_common(pa, shadow=True)
    pa.add_argument("--workspace", required=True); pa.add_argument("--source-id", required=True, dest="source_id")
    pa.set_defaults(func=cmd_adjudicate)
    pc = sub.add_parser("calibrate"); add_common(pc, shadow=True)
    pc.add_argument("--workspace", required=True); pc.add_argument("--source-id", required=True, dest="source_id")
    pc.add_argument("--human-decisions", required=True, dest="human_decisions"); pc.set_defaults(func=cmd_calibrate)
    prp = sub.add_parser("report"); add_common(prp)
    prp.add_argument("--workspace", required=True); prp.add_argument("--source-id", required=True, dest="source_id")
    prp.set_defaults(func=cmd_report)

    args = ap.parse_args()
    try:
        args.func(args)
    except ShadowModeRequired as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
