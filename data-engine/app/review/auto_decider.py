"""Auto-decisor del pipeline de revisión.

Decide para cada candidato:
  auto_approve  — seguro, no necesita revisión humana
  needs_review  — dudoso, va a la cola de revisión
  auto_reject   — claramente inválido o de baja calidad

Umbrales:
  auto_approve  : conf >= 0.85 AND valid AND resolver claro (use_existing|create_new sin conflicto)
                  AND evidence no vacía AND timestamps válidos AND sin duplicado ambiguo
  needs_review  : 0.60 <= conf < 0.85 OR posible duplicado OR varios matches
                  OR tipo/relación dudosa OR evidence débil
  auto_reject   : conf < 0.60 OR schema inválido OR timestamp roto OR sin evidence
                  OR relación imposible OR segmento noise/intro_outro
"""
from __future__ import annotations
import json
import logging
import re
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review.models import Candidate, ValidationResult, ResolutionResult, Decision

log = logging.getLogger(__name__)

_TS_RE = re.compile(r'^\d{2}:\d{2}:\d{2}$')
CONF_AUTO_APPROVE = 0.85
CONF_NEEDS_REVIEW = 0.60


def _timestamps_valid(c: Candidate) -> bool:
    ts = c.timestamp_start
    te = c.timestamp_end
    if ts and not _TS_RE.match(ts):
        return False
    if te and not _TS_RE.match(te):
        return False
    return True


def decide_one(
    c: Candidate,
    vr: ValidationResult,
    rr: ResolutionResult,
) -> Decision:
    """Toma la decisión final para un candidato."""

    # ── AUTO_REJECT ────────────────────────────────────────────────────────────
    if c.confidence < CONF_NEEDS_REVIEW:
        return Decision(
            candidate_id=c.candidate_id,
            decision="auto_reject",
            reason=f"confidence demasiado baja ({c.confidence:.2f} < {CONF_NEEDS_REVIEW})",
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    if vr.valid == "invalid":
        return Decision(
            candidate_id=c.candidate_id,
            decision="auto_reject",
            reason=f"validación inválida: {'; '.join(vr.issues)}",
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    if not c.evidence or not c.evidence.strip():
        return Decision(
            candidate_id=c.candidate_id,
            decision="auto_reject",
            reason="sin evidence",
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    if not _timestamps_valid(c):
        return Decision(
            candidate_id=c.candidate_id,
            decision="auto_reject",
            reason="timestamps inválidos",
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    if rr.action == "reject":
        return Decision(
            candidate_id=c.candidate_id,
            decision="auto_reject",
            reason=f"resolver rechazó: {rr.reason}",
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    # ── NEEDS_REVIEW ───────────────────────────────────────────────────────────
    if c.confidence < CONF_AUTO_APPROVE:
        return Decision(
            candidate_id=c.candidate_id,
            decision="needs_review",
            reason=f"confidence media ({c.confidence:.2f})",
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    if vr.valid == "dubious":
        return Decision(
            candidate_id=c.candidate_id,
            decision="needs_review",
            reason=f"validación dudosa: {'; '.join(vr.warnings)}",
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    if rr.action == "needs_review":
        return Decision(
            candidate_id=c.candidate_id,
            decision="needs_review",
            reason=f"resolver: {rr.reason}",
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    if len(rr.alternatives) > 1:
        return Decision(
            candidate_id=c.candidate_id,
            decision="needs_review",
            reason=f"duplicado ambiguo: {len(rr.alternatives)} alternativas",
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    if not rr.neo4j_available:
        return Decision(
            candidate_id=c.candidate_id,
            decision="needs_review",
            reason="Neo4j no disponible; sin verificación de duplicados",
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    # ── AUTO_APPROVE ───────────────────────────────────────────────────────────
    # Llegamos aquí: conf >= 0.85, valid, resolver claro (use_existing|create_new), evidence, timestamps
    if rr.action in ("use_existing", "create_new"):
        return Decision(
            candidate_id=c.candidate_id,
            decision="auto_approve",
            reason=f"conf={c.confidence:.2f}, resolver={rr.action}",
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    # Fallback: needs_review
    return Decision(
        candidate_id=c.candidate_id,
        decision="needs_review",
        reason=f"resolver inesperado: {rr.action}",
        candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
    )


def decide_all(
    resolved: list[tuple[Candidate, ValidationResult, ResolutionResult]],
) -> list[Decision]:
    decisions = [decide_one(c, vr, rr) for c, vr, rr in resolved]
    n_approve = sum(1 for d in decisions if d.decision == "auto_approve")
    n_review = sum(1 for d in decisions if d.decision == "needs_review")
    n_reject = sum(1 for d in decisions if d.decision == "auto_reject")
    log.info(
        "Decisión: auto_approve=%d, needs_review=%d, auto_reject=%d",
        n_approve, n_review, n_reject,
    )
    return decisions


def run(workspace: str, source_id: str, repo_root: Path) -> Path:
    """Entry point: decide y guarda decisions.json."""
    in_path = repo_root / "output" / "reviews" / workspace / source_id / "resolved.json"
    if not in_path.exists():
        raise FileNotFoundError(f"resolved.json no encontrado: {in_path}")

    with in_path.open(encoding="utf-8") as f:
        raw = json.load(f)

    from review.models import Candidate, ValidationResult, ResolutionResult
    resolved = []
    for rec in raw:
        c = Candidate.from_dict(rec["candidate"])
        vr = ValidationResult.from_dict(rec["validation"])
        rr = ResolutionResult.from_dict(rec["resolution"])
        resolved.append((c, vr, rr))

    decisions = decide_all(resolved)

    out_path = in_path.parent / "decisions.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump([d.to_dict() for d in decisions], f, ensure_ascii=False, indent=2)

    log.info("decisions.json → %s", out_path)
    return out_path
