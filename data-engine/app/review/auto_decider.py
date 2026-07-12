"""Auto-decisor del pipeline de revisión.

Decide para cada candidato:
  auto_approve  — seguro, no necesita revisión humana
  needs_review  — dudoso, va a la cola de revisión
  auto_reject   — claramente inválido o de baja calidad

Umbrales:
  auto_approve  : conf >= 0.85 AND valid AND resolver claro (use_existing exacto
                  o create_new sin conflicto) AND evidence presente AND timestamps
                  válidos AND sin duplicado ambiguo AND NO stopword AND NO
                  single-token débil (salvo use_existing exacto o glossary_match)
                  AND workspace presente AND origin local o imported-validado
  needs_review  : 0.60 <= conf < 0.85 OR posible duplicado OR varios matches
                  OR tipo/relación dudosa OR evidence débil OR origin externo
                  OR single-token sin match exacto
  auto_reject   : conf < 0.60 OR schema inválido OR timestamp roto OR sin evidence
                  OR relación imposible OR segmento noise/intro_outro OR stopword
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

# Tipos de entidad que pueden ser single-token legítimos solo con match exacto o glosario
_SINGLE_TOKEN_TYPES = {"Character", "Location", "Faction", "Object"}

# ── Importación defensiva de stopwords ────────────────────────────────────────
try:
    from review.stopwords import is_stopword, is_weak_single_token  # type: ignore
except ImportError:
    _FALLBACK_STOPWORDS = {
        "todo", "como", "llevas", "llevás", "vale", "venga", "bueno", "entonces",
        "pues", "esto", "eso", "vamos", "mira", "claro", "si", "no", "pero",
        "porque", "cuando", "donde", "quien",
    }

    def is_stopword(term: str) -> bool:  # type: ignore
        return term.strip().lower() in _FALLBACK_STOPWORDS

    def is_weak_single_token(term: str) -> bool:  # type: ignore
        """Token único de <=2 palabras que está en la lista de débiles."""
        parts = term.strip().split()
        if len(parts) != 1:
            return False
        return is_stopword(term)


def _timestamps_valid(c: Candidate) -> bool:
    ts = c.timestamp_start
    te = c.timestamp_end
    if ts and not _TS_RE.match(ts):
        return False
    if te and not _TS_RE.match(te):
        return False
    return True


def _is_single_token(name: str) -> bool:
    """True si el nombre es una sola palabra (sin espacios)."""
    return len(name.strip().split()) == 1


def decide_one(
    c: Candidate,
    vr: ValidationResult,
    rr: ResolutionResult,
) -> Decision:
    """Toma la decisión final para un candidato.

    Rellena siempre decision_reason con razones legibles.
    """
    reasons: list[str] = []
    origin = getattr(c, "origin", "local") or "local"

    # ── AUTO_REJECT ────────────────────────────────────────────────────────────

    if c.confidence < CONF_NEEDS_REVIEW:
        reasons.append(f"low_confidence:{c.confidence:.2f}")
        return Decision(
            candidate_id=c.candidate_id,
            decision="auto_reject",
            reason=f"confidence demasiado baja ({c.confidence:.2f} < {CONF_NEEDS_REVIEW})",
            decision_reason=reasons,
            origin=origin,
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    if vr.valid == "invalid":
        reasons.append("invalid_schema")
        return Decision(
            candidate_id=c.candidate_id,
            decision="auto_reject",
            reason=f"validación inválida: {'; '.join(vr.issues)}",
            decision_reason=reasons,
            origin=origin,
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    if not c.evidence or not c.evidence.strip():
        reasons.append("weak_evidence")
        return Decision(
            candidate_id=c.candidate_id,
            decision="auto_reject",
            reason="sin evidence",
            decision_reason=reasons,
            origin=origin,
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    if not _timestamps_valid(c):
        reasons.append("invalid_timestamp")
        return Decision(
            candidate_id=c.candidate_id,
            decision="auto_reject",
            reason="timestamps inválidos",
            decision_reason=reasons,
            origin=origin,
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    if rr.action == "reject":
        reasons.append("resolver_rejected")
        return Decision(
            candidate_id=c.candidate_id,
            decision="auto_reject",
            reason=f"resolver rechazó: {rr.reason}",
            decision_reason=reasons,
            origin=origin,
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    # Stopword → auto_reject (nunca autoaprobar un término vacío de contenido)
    name = (c.name or "").strip()
    if name and is_stopword(name):
        reasons.append("stopword")
        return Decision(
            candidate_id=c.candidate_id,
            decision="auto_reject",
            reason=f"nombre es stopword: '{name}'",
            decision_reason=reasons,
            origin=origin,
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    # Flag weak explícito del extractor → auto_reject
    if getattr(c, "weak", False):
        reasons.append("stopword")
        return Decision(
            candidate_id=c.candidate_id,
            decision="auto_reject",
            reason=f"candidato marcado como débil (weak=True): '{name}'",
            decision_reason=reasons,
            origin=origin,
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    # ── NEEDS_REVIEW ───────────────────────────────────────────────────────────

    if c.confidence < CONF_AUTO_APPROVE:
        reasons.append(f"low_confidence:{c.confidence:.2f}")
        return Decision(
            candidate_id=c.candidate_id,
            decision="needs_review",
            reason=f"confidence media ({c.confidence:.2f})",
            decision_reason=reasons,
            origin=origin,
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    if vr.valid == "dubious":
        reasons.append("dubious_schema")
        return Decision(
            candidate_id=c.candidate_id,
            decision="needs_review",
            reason=f"validación dudosa: {'; '.join(vr.warnings)}",
            decision_reason=reasons,
            origin=origin,
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    # Origin externo o importado sin validación local → needs_review como mínimo
    if origin in ("external", "imported"):
        reasons.append("external_origin")
        return Decision(
            candidate_id=c.candidate_id,
            decision="needs_review",
            reason=f"origin={origin}: requiere validación local antes de auto-aprobar",
            decision_reason=reasons,
            origin=origin,
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    # Workspace ausente (doble guardia; validator ya lo detecta, pero para robustez)
    if not c.workspace or not c.workspace.strip():
        reasons.append("missing_workspace")
        return Decision(
            candidate_id=c.candidate_id,
            decision="needs_review",
            reason="workspace ausente",
            decision_reason=reasons,
            origin=origin,
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    if rr.action == "needs_review":
        reasons.append("possible_duplicate" if rr.alternatives else "resolver_needs_review")
        return Decision(
            candidate_id=c.candidate_id,
            decision="needs_review",
            reason=f"resolver: {rr.reason}",
            decision_reason=reasons,
            origin=origin,
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    if len(rr.alternatives) > 1:
        reasons.append("possible_duplicate")
        return Decision(
            candidate_id=c.candidate_id,
            decision="needs_review",
            reason=f"duplicado ambiguo: {len(rr.alternatives)} alternativas",
            decision_reason=reasons,
            origin=origin,
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    if not rr.neo4j_available:
        reasons.append("neo4j_unavailable")
        return Decision(
            candidate_id=c.candidate_id,
            decision="needs_review",
            reason="Neo4j no disponible; sin verificación de duplicados",
            decision_reason=reasons,
            origin=origin,
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    # Single-token débil sin use_existing exacto ni glosario → needs_review
    # (Aplica a tipos específicos que rara vez son single-token válidos)
    if name and c.entity_type in _SINGLE_TOKEN_TYPES and _is_single_token(name):
        has_exact_use_existing = (
            rr.action == "use_existing" and
            rr.match_type in ("exact", "alias")
        )
        has_glossary = getattr(c, "glossary_match", False)
        if not has_exact_use_existing and not has_glossary:
            reasons.append("single_token_candidate")
            return Decision(
                candidate_id=c.candidate_id,
                decision="needs_review",
                reason=f"single-token '{name}' de tipo {c.entity_type} sin match exacto ni glosario",
                decision_reason=reasons,
                origin=origin,
                candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
            )

    # ── AUTO_APPROVE ───────────────────────────────────────────────────────────
    # Llegamos aquí: conf >= 0.85, valid, resolver claro (use_existing|create_new),
    # evidence presente, timestamps ok, no stopword, no weak, no duplicado ambiguo,
    # origin local, workspace presente.
    if rr.action in ("use_existing", "create_new"):
        # Construir lista de razones positivas
        reasons.append("valid_schema")
        reasons.append("timestamp_valid")
        if c.confidence >= CONF_AUTO_APPROVE:
            reasons.append(f"high_confidence:{c.confidence:.2f}")
        if rr.action == "use_existing":
            reasons.append("resolver_exact_match")
        else:
            reasons.append("resolver_create_new")
        if name and not _is_single_token(name):
            reasons.append("strong_compound_name")
        if getattr(c, "glossary_match", False):
            reasons.append("glossary_match")
        reasons.append("not_stopword")

        return Decision(
            candidate_id=c.candidate_id,
            decision="auto_approve",
            reason=f"conf={c.confidence:.2f}, resolver={rr.action}",
            decision_reason=reasons,
            origin=origin,
            candidate=c.to_dict(), validation=vr.to_dict(), resolution=rr.to_dict(),
        )

    # Fallback: needs_review
    reasons.append("unexpected_resolver_action")
    return Decision(
        candidate_id=c.candidate_id,
        decision="needs_review",
        reason=f"resolver inesperado: {rr.action}",
        decision_reason=reasons,
        origin=origin,
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
