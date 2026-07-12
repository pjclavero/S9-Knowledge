"""Orquestador del pipeline de revisión S9 Knowledge.

Ejecuta: segment → classify → extract → validate → resolve → decide → approved_writer

El pipeline es reproducible: cada paso lee su input del paso anterior
y sobreescribe su output.
"""
from __future__ import annotations
import logging
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

log = logging.getLogger(__name__)


def run_pipeline(
    workspace: str,
    source_id: str,
    repo_root: Path,
    dry_run: bool = True,
    stop_after: str | None = None,
) -> dict:
    """
    Ejecuta el pipeline completo.

    Args:
        workspace:  nombre del workspace (p. ej. "leyenda")
        source_id:  ID del source (p. ej. "media_2bdf6005fcffd476")
        repo_root:  raíz del repo
        dry_run:    siempre True en esta fase
        stop_after: detener tras este paso ("segment"|"classify"|"extract"|"validate"|"resolve"|"decide")

    Returns:
        dict con contadores y rutas de output.
    """
    from review import segmenter, classifier, extractor, validator, resolver, auto_decider, approved_writer
    from review.review_store import ReviewStore
    from review.models import Candidate, ValidationResult, ResolutionResult

    store = ReviewStore(repo_root)
    result: dict = {"workspace": workspace, "source_id": source_id, "steps": {}}

    # ── 1. Segment ─────────────────────────────────────────────────────────────
    log.info("[pipeline] STEP 1: segment")
    seg_path = segmenter.run(workspace, source_id, repo_root)
    import json
    with seg_path.open() as f:
        segments_raw = json.load(f)
    result["steps"]["segment"] = {"output": str(seg_path), "count": len(segments_raw)}
    store.save_step(workspace, source_id, "segment", "done", {"count": len(segments_raw)})
    if stop_after == "segment":
        return result

    # ── 2. Classify ────────────────────────────────────────────────────────────
    log.info("[pipeline] STEP 2: classify")
    cls_path = classifier.run(workspace, source_id, repo_root)
    with cls_path.open() as f:
        classified_raw = json.load(f)
    n_extract = sum(1 for c in classified_raw if c.get("should_extract"))
    result["steps"]["classify"] = {
        "output": str(cls_path),
        "total": len(classified_raw),
        "extractable": n_extract,
    }
    store.save_step(workspace, source_id, "classify", "done", {"extractable": n_extract})
    if stop_after == "classify":
        return result

    # ── 3. Extract ─────────────────────────────────────────────────────────────
    log.info("[pipeline] STEP 3: extract")
    ext_path = extractor.run(workspace, source_id, repo_root)
    with ext_path.open() as f:
        candidates_raw = json.load(f)
    result["steps"]["extract"] = {"output": str(ext_path), "count": len(candidates_raw)}
    store.save_step(workspace, source_id, "extract", "done", {"count": len(candidates_raw)})
    if stop_after == "extract":
        return result

    # ── 4. Validate ────────────────────────────────────────────────────────────
    log.info("[pipeline] STEP 4: validate")
    val_path = validator.run(workspace, source_id, repo_root)
    with val_path.open() as f:
        validated_raw = json.load(f)
    n_valid = sum(1 for r in validated_raw if r["validation"]["valid"] == "valid")
    n_invalid = sum(1 for r in validated_raw if r["validation"]["valid"] == "invalid")
    result["steps"]["validate"] = {
        "output": str(val_path),
        "valid": n_valid,
        "invalid": n_invalid,
    }
    store.save_step(workspace, source_id, "validate", "done", {"valid": n_valid, "invalid": n_invalid})
    if stop_after == "validate":
        return result

    # ── 5. Resolve ─────────────────────────────────────────────────────────────
    log.info("[pipeline] STEP 5: resolve")
    res_path = resolver.run(workspace, source_id, repo_root)
    with res_path.open() as f:
        resolved_raw = json.load(f)
    actions = {}
    for r in resolved_raw:
        a = r["resolution"]["action"]
        actions[a] = actions.get(a, 0) + 1
    result["steps"]["resolve"] = {"output": str(res_path), "actions": actions}
    store.save_step(workspace, source_id, "resolve", "done", {"actions": actions})
    if stop_after == "resolve":
        return result

    # ── 6. Decide ──────────────────────────────────────────────────────────────
    log.info("[pipeline] STEP 6: decide")
    dec_path = auto_decider.run(workspace, source_id, repo_root)
    with dec_path.open() as f:
        decisions_raw = json.load(f)
    decision_counts: dict[str, int] = {}
    for d in decisions_raw:
        dec = d["decision"]
        decision_counts[dec] = decision_counts.get(dec, 0) + 1
    result["steps"]["decide"] = {"output": str(dec_path), "decisions": decision_counts}
    store.save_step(workspace, source_id, "decide", "done", {"decisions": decision_counts})
    if stop_after == "decide":
        return result

    # ── 7. Approved Writer ─────────────────────────────────────────────────────
    log.info("[pipeline] STEP 7: approved_writer")
    counts = approved_writer.run(workspace, source_id, repo_root)
    result["steps"]["approved_writer"] = counts
    store.save_step(workspace, source_id, "approved_writer", "done", counts)

    result["summary"] = {
        "auto_approve": counts.get("auto_approve", 0),
        "needs_review": counts.get("needs_review", 0),
        "auto_reject": counts.get("auto_reject", 0),
        "total": counts.get("total", 0),
    }

    log.info(
        "[pipeline] COMPLETADO: auto_approve=%d, needs_review=%d, auto_reject=%d",
        counts.get("auto_approve", 0),
        counts.get("needs_review", 0),
        counts.get("auto_reject", 0),
    )
    return result
