"""Orquestador del pipeline de revisión S9 Knowledge.

Ejecuta: segment → classify → extract → validate → resolve → decide → approved_writer

El paso de extracción soporta tres modos via env S9K_REVIEW_EXTRACTOR:
    heuristic  — extractor heurístico endurecido + glosario
    llm        — solo LLM (Ollama qwen2.5:7b)
    hybrid     — heurístico + LLM, dedupe por name+type (default si Ollama responde)

Si S9K_REVIEW_EXTRACTOR no está definido: intenta hybrid; si Ollama no responde,
degrada a heuristic con warning.

El pipeline es reproducible: cada paso lee su input del paso anterior
y sobreescribe su output.
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

log = logging.getLogger(__name__)

_VALID_MODES = {"heuristic", "llm", "hybrid"}


def _resolve_extractor_mode() -> str:
    """Determina el modo de extracción a partir de env S9K_REVIEW_EXTRACTOR."""
    env_mode = os.environ.get("S9K_REVIEW_EXTRACTOR", "").strip().lower()
    if env_mode in _VALID_MODES:
        return env_mode
    # Default: intentar hybrid; degradar a heuristic si Ollama no disponible
    from review.llm_extractor import is_ollama_available
    if is_ollama_available():
        log.info("[pipeline] Ollama disponible → modo hybrid")
        return "hybrid"
    else:
        log.warning("[pipeline] Ollama no disponible → modo heuristic")
        return "heuristic"


def _run_extract_step(
    workspace: str,
    source_id: str,
    repo_root: Path,
    mode: str,
    classified: list,
) -> list:
    """Ejecuta el paso de extracción en el modo indicado.

    Retorna la lista de candidatos (dicts).
    Guarda candidates.json en output/reviews/<workspace>/<source_id>/.
    """
    from review import extractor as heuristic_extractor
    from review.extractor import _load_glossary, _glossary_snapshot, extract_from_segments
    from review.models import Candidate

    out_dir = repo_root / "output" / "reviews" / workspace / source_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "candidates.json"

    glossary = _load_glossary(repo_root, workspace)
    all_candidates: list[Candidate] = []

    if mode in ("heuristic", "hybrid"):
        heuristic_cands = extract_from_segments(classified, glossary)
        all_candidates.extend(heuristic_cands)
        log.info("[pipeline] Heurístico: %d candidatos", len(heuristic_cands))

    if mode in ("llm", "hybrid"):
        try:
            from review.llm_extractor import extract_with_llm, is_ollama_available
            if not is_ollama_available():
                log.warning("[pipeline] Ollama no disponible en modo %s — omitiendo LLM", mode)
            else:
                gloss_snap = _glossary_snapshot(repo_root, workspace)
                _seed_env = os.environ.get("S9K_LLM_SEED", "")
                _seed = int(_seed_env) if _seed_env.strip().isdigit() else None
                llm_cands = extract_with_llm(classified, gloss_snap, workspace, seed=_seed)
                log.info("[pipeline] LLM: %d candidatos", len(llm_cands))

                if mode == "hybrid":
                    # Dedupe: entidades por name+type; relaciones por from+type+to
                    def _dedup_key(c: Candidate) -> str:
                        if c.name is not None:
                            return f"{c.name.lower().strip()}|{c.entity_type or ''}"
                        return (
                            f"{(c.from_entity or '').lower().strip()}"
                            f"|{c.relation_type or ''}"
                            f"|{(c.to_entity or '').lower().strip()}"
                        )

                    existing: dict[str, Candidate] = {}
                    for c in all_candidates:
                        existing[_dedup_key(c)] = c

                    merged_new = 0
                    for c in llm_cands:
                        key = _dedup_key(c)
                        if key not in existing:
                            existing[key] = c
                            merged_new += 1
                        else:
                            prev = existing[key]
                            if c.confidence > prev.confidence:
                                existing[key] = c
                            elif c.confidence == prev.confidence and len(c.evidence) > len(prev.evidence):
                                existing[key] = c
                    log.info("[pipeline] Hybrid merge: %d nuevos de LLM, total=%d", merged_new, len(existing))
                    all_candidates = list(existing.values())
                else:
                    # Modo llm puro: solo candidatos LLM
                    all_candidates = llm_cands

        except Exception as e:
            log.error("[pipeline] Error en extractor LLM: %s — usando solo heurístico", e)
            if mode == "llm":
                log.warning("[pipeline] Modo llm: degradando a heurístico tras error")
                all_candidates = extract_from_segments(classified, glossary)

    # Deduplicar por candidate_id final
    seen: set[str] = set()
    unique: list[Candidate] = []
    for c in all_candidates:
        if c.candidate_id not in seen:
            seen.add(c.candidate_id)
            unique.append(c)

    log.info("[pipeline] Extracción (%s): %d candidatos únicos totales", mode, len(unique))

    result_dicts = [c.to_dict() for c in unique]

    # Prioridad 2.1: normaliza extremos de relación (alias del source + glosario
    # de workspace + corrección de dirección). No consulta Neo4j.
    try:
        from review.relation_normalizer import normalize_relations
        from review.workspace_aliases import load_workspace_aliases
        ents = [d for d in result_dicts if d.get("kind") == "entity"]
        rels = [d for d in result_dicts if d.get("kind") == "relation"]
        if rels:
            normalize_relations(ents, rels, load_workspace_aliases(repo_root, workspace))
            log.info("[pipeline] relaciones normalizadas: %d", len(rels))
    except Exception as e:
        log.warning("[pipeline] normalización de relaciones omitida: %s", e)

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result_dicts, f, ensure_ascii=False, indent=2)

    return result_dicts


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
    from review import segmenter, classifier, validator, resolver, auto_decider, approved_writer
    from review.review_store import ReviewStore
    from review.models import Candidate, ValidationResult, ResolutionResult

    store = ReviewStore(repo_root)
    result: dict = {"workspace": workspace, "source_id": source_id, "steps": {}}

    # Determinar modo de extracción
    extractor_mode = _resolve_extractor_mode()
    log.info("[pipeline] Modo extractor: %s", extractor_mode)

    # ── 1. Segment ─────────────────────────────────────────────────────────────
    log.info("[pipeline] STEP 1: segment")
    seg_path = segmenter.run(workspace, source_id, repo_root)
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
    log.info("[pipeline] STEP 3: extract (mode=%s)", extractor_mode)
    candidates_raw = _run_extract_step(workspace, source_id, repo_root, extractor_mode, classified_raw)
    result["steps"]["extract"] = {
        "mode": extractor_mode,
        "count": len(candidates_raw),
    }
    store.save_step(workspace, source_id, "extract", "done", {"count": len(candidates_raw), "mode": extractor_mode})
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
    # Leer decisions.json y llamar write_outputs con la interfaz actualizada
    dec_path_aw = repo_root / "output" / "reviews" / workspace / source_id / "decisions.json"
    with dec_path_aw.open(encoding="utf-8") as f:
        decisions_for_writer = json.load(f)
    from review.models import Decision as DecisionModel
    decision_objs = [DecisionModel.from_dict(d) for d in decisions_for_writer]
    out_dir = repo_root / "output" / "reviews" / workspace / source_id
    counts = approved_writer.write_outputs(
        decision_objs, out_dir, workspace, source_id
    )
    result["steps"]["approved_writer"] = counts
    store.save_step(workspace, source_id, "approved_writer", "done", counts)

    result["summary"] = {
        "auto_approve": counts.get("auto_approve", 0),
        "needs_review": counts.get("needs_review", 0),
        "auto_reject": counts.get("auto_reject", 0),
        "total": counts.get("total", 0),
        "extractor_mode": extractor_mode,
    }

    log.info(
        "[pipeline] COMPLETADO (modo=%s): auto_approve=%d, needs_review=%d, auto_reject=%d",
        extractor_mode,
        counts.get("auto_approve", 0),
        counts.get("needs_review", 0),
        counts.get("auto_reject", 0),
    )
    return result