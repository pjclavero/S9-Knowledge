"""review_console — capa de servicio del panel de revisión v1 (Equipo B).

Consume los contratos ``contracts/review-ingest/v1`` SIN modificarlos y valida
todo lo que produce con el ``validator.py`` compartido. Produce ÚNICAMENTE
``review-decision`` v1 y ``review-audit-event`` v1, escritos en un almacén
LOCAL/temporal de laboratorio (JSONL append-only). NUNCA escribe en Neo4j, nunca
aplica un ingest-plan y nunca modifica el review original: cada decisión crea una
generación inmutable nueva.

Control de concurrencia (optimista): cada candidato tiene un hash calculado de
forma determinista sobre su contenido. La decisión declara
``expected_candidate_hash``; si no coincide con el hash actual del candidato, la
revisión está OBSOLETA (STALE_REVIEW) y NO se escribe la decisión: solo se
registra un evento de auditoría ``STALE_REVIEW_REJECTED``.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
_SERVICES_DIR = Path(__file__).resolve().parent
REPO_ROOT = _SERVICES_DIR.parents[2]  # services -> app -> viewer -> repo_root
CONTRACTS_V1_DIR = REPO_ROOT / "contracts" / "review-ingest" / "v1"
FIXTURES_DIR = _SERVICES_DIR / "review_console_fixtures"

# Producer/pipeline con los que el visor firma lo que produce.
VIEWER_PRODUCER = {
    "kind": "HUMAN_TOOL",
    "name": "s9k-viewer",
    "version": "0.3.0",
    "model": None,
}
VIEWER_PIPELINE_VERSION = "viewer-0.3.0"

# Códigos de razón por defecto para cada acción (el operador puede sobrescribir).
DEFAULT_REASON_CODE = {
    "APPROVE": "HUMAN_CONFIRMED",
    "EDIT": "EDITED_BY_REVIEWER",
    "USE_EXISTING": "SAME_AS_EXISTING",
    "DEFER": "DEFERRED_BY_REVIEWER",
    "REJECT": "REJECTED_BY_REVIEWER",
    "RESOLVE_CONFLICT": "CONFLICT_RESOLVED",
}

VALID_ACTIONS = set(DEFAULT_REASON_CODE)


class ReviewConsoleError(ValueError):
    """Error de uso del panel (entrada inválida, candidato inexistente…)."""


class StaleReviewError(ReviewConsoleError):
    """La revisión es obsoleta: expected_candidate_hash no coincide."""


# ---------------------------------------------------------------------------
# Puente con el validador compartido de contratos (carga sin modificarlo)
# ---------------------------------------------------------------------------
_validator_mod: Optional[ModuleType] = None
_validator_lock = threading.Lock()


def _load_validator() -> ModuleType:
    """Carga contracts/review-ingest/v1/validator.py como módulo aislado."""
    global _validator_mod
    if _validator_mod is not None:
        return _validator_mod
    with _validator_lock:
        if _validator_mod is not None:
            return _validator_mod
        path = CONTRACTS_V1_DIR / "validator.py"
        if not path.exists():
            raise ReviewConsoleError(f"validator de contratos no encontrado en {path}")
        spec = importlib.util.spec_from_file_location("_s9k_contract_validator_v1", path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _validator_mod = mod
        return mod


def validate_document(doc: dict[str, Any]) -> None:
    """Valida un documento v1 con el validador compartido. Lanza ContractError."""
    _load_validator().validate_document(doc)


def is_valid(doc: dict[str, Any]) -> bool:
    return _load_validator().is_valid(doc)


# ---------------------------------------------------------------------------
# Utilidades deterministas: canonicalización y hashes
# ---------------------------------------------------------------------------
def _canonical(obj: Any) -> str:
    """JSON canónico y estable (claves ordenadas, sin espacios)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash(value_hex: str) -> dict[str, str]:
    return {"algorithm": "sha256", "value": value_hex}


def candidate_hash(candidate: dict[str, Any]) -> dict[str, str]:
    """Hash determinista del contenido del candidato (control optimista).

    No depende del orden de las claves. Si el motor regenera el candidato con
    cualquier cambio semántico, el hash cambia y las decisiones previas quedan
    obsoletas.
    """
    return _hash(sha256_hex(_canonical(candidate)))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Almacén de laboratorio (JSONL append-only, NUNCA Neo4j)
# ---------------------------------------------------------------------------
def lab_store_dir() -> Path:
    """Directorio del almacén de laboratorio.

    Configurable con ``S9K_REVIEW_LAB_DIR``. Por defecto un directorio temporal
    del sistema (fuera del repo y NUNCA producción). Los tests pasan su propio
    directorio temporal.
    """
    env = os.environ.get("S9K_REVIEW_LAB_DIR")
    base = Path(env) if env else Path(tempfile.gettempdir()) / "s9k_review_lab"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _decisions_path(store: Path) -> Path:
    return store / "decisions.jsonl"


def _audit_path(store: Path) -> Path:
    return store / "audit_events.jsonl"


def _append_jsonl(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(_canonical(doc) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def read_decisions(store: Optional[Path] = None) -> list[dict[str, Any]]:
    return _read_jsonl(_decisions_path(store or lab_store_dir()))


def read_audit_events(store: Optional[Path] = None) -> list[dict[str, Any]]:
    return _read_jsonl(_audit_path(store or lab_store_dir()))


# ---------------------------------------------------------------------------
# Carga de fixtures de contrato (documentos v1 sintéticos y ANONIMIZADOS)
# ---------------------------------------------------------------------------
def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def list_source_summaries(fixtures_dir: Optional[Path] = None) -> list[dict[str, Any]]:
    """Bandeja: todos los review-source-summary v1 disponibles (validados)."""
    base = (fixtures_dir or FIXTURES_DIR) / "summaries"
    if not base.exists():
        return []
    out = []
    for path in sorted(base.glob("*.json")):
        doc = _load_json(path)
        validate_document(doc)
        out.append(doc)
    return out


def get_source_summary(source_id: str, fixtures_dir: Optional[Path] = None) -> Optional[dict[str, Any]]:
    for summary in list_source_summaries(fixtures_dir):
        if summary["source_id"] == source_id:
            return summary
    return None


def list_candidates(source_id: str, fixtures_dir: Optional[Path] = None) -> list[dict[str, Any]]:
    """Candidatos v1 de una fuente (validados), con su hash de control incluido."""
    base = (fixtures_dir or FIXTURES_DIR) / "candidates" / source_id
    if not base.exists():
        return []
    out = []
    for path in sorted(base.glob("*.json")):
        doc = _load_json(path)
        validate_document(doc)
        out.append(doc)
    return out


def get_candidate(source_id: str, candidate_id: str,
                  fixtures_dir: Optional[Path] = None) -> Optional[dict[str, Any]]:
    for cand in list_candidates(source_id, fixtures_dir):
        if cand["candidate_id"] == candidate_id:
            return cand
    return None


def get_ingest_plan(source_id: str, fixtures_dir: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """ingest-plan v1 de la fuente (solo lectura, para preview)."""
    path = (fixtures_dir or FIXTURES_DIR) / "plans" / f"{source_id}.json"
    if not path.exists():
        return None
    doc = _load_json(path)
    validate_document(doc)
    return doc


def plan_preview(source_id: str, fixtures_dir: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """Resumen SOLO LECTURA del ingest-plan: WOULD_CREATE / DEFER / CONFLICT.

    NO autoriza ni aplica nada. Deriva los contadores del propio plan.
    """
    plan = get_ingest_plan(source_id, fixtures_dir)
    if plan is None:
        return None
    summary = plan.get("summary", {})
    return {
        "plan_id": plan.get("plan_id"),
        "status": plan.get("status"),
        "would_create": summary.get("would_create", 0),
        "would_update": summary.get("would_update", 0),
        "would_link_existing": summary.get("would_link_existing", 0),
        "deferred": summary.get("deferred", 0),
        "conflicts": summary.get("conflicts", 0),
        "relations": summary.get("relations", 0),
        "authorization_required": plan.get("authorization", {}).get("required", True),
        "authorization_granted": plan.get("authorization", {}).get("granted", False),
        "relations_enabled": plan.get("relations_enabled", False),
    }


# ---------------------------------------------------------------------------
# Construcción de documentos producidos por el panel
# ---------------------------------------------------------------------------
_ID_SAFE = re.compile(r"[^A-Za-z0-9._:-]")


def _stable_suffix(*parts: str) -> str:
    return sha256_hex(":".join(parts))[:16]


def _envelope(candidate: dict[str, Any]) -> dict[str, Any]:
    """Campos de envelope + procedencia derivados del candidato de origen."""
    return {
        "schema_version": "1.0.0",
        "workspace": candidate["workspace"],
        "source_id": candidate["source_id"],
        "source_hash": candidate["source_hash"],
        "review_generation": candidate["review_generation"],
        "producer": dict(VIEWER_PRODUCER),
        "provenance": {
            "source_id": candidate["source_id"],
            "source_hash": candidate["source_hash"],
            "review_generation": candidate["review_generation"],
            "pipeline_version": VIEWER_PIPELINE_VERSION,
            "producer": dict(VIEWER_PRODUCER),
        },
    }


def build_decision(
    candidate: dict[str, Any],
    action: str,
    reviewer_id: str,
    expected_candidate_hash: dict[str, Any],
    *,
    reviewer_type: str = "HUMAN",
    reason_code: Optional[str] = None,
    comment: Optional[str] = None,
    after: Optional[dict[str, Any]] = None,
    target_existing_id: Optional[str] = None,
    decided_at: Optional[str] = None,
) -> dict[str, Any]:
    """Construye y VALIDA un review-decision v1 (no lo persiste)."""
    if action not in VALID_ACTIONS:
        raise ReviewConsoleError(f"acción desconocida: {action!r}")

    ts = decided_at or _now_iso()
    decision_id = "dec_" + _stable_suffix(candidate["candidate_id"], action, ts, reviewer_id)

    doc: dict[str, Any] = {
        **_envelope(candidate),
        "document_type": "review-decision",
        "document_id": "review-decision_" + decision_id,
        "created_at": ts,
        "decision_id": decision_id,
        "candidate_id": candidate["candidate_id"],
        "action": action,
        "reviewer_type": reviewer_type,
        "reviewer_id": reviewer_id,
        "decided_at": ts,
        "reason_code": reason_code or DEFAULT_REASON_CODE[action],
        "expected_candidate_hash": expected_candidate_hash,
    }
    if comment:
        doc["comment"] = comment
    if action == "EDIT":
        # EDIT exige `after` (estado posterior propuesto).
        doc["after"] = after if after else {"canonical_name": candidate["canonical_name"]}
    if action == "USE_EXISTING":
        # USE_EXISTING exige target_existing_id (schema). Si no se pasa, se usa
        # el primer match existente del candidato.
        target = target_existing_id
        if not target and candidate.get("existing_matches"):
            target = candidate["existing_matches"][0]["entity_id"]
        if not target:
            raise ReviewConsoleError("USE_EXISTING requiere target_existing_id")
        doc["target_existing_id"] = target
    if action == "RESOLVE_CONFLICT" and target_existing_id:
        doc["target_existing_id"] = target_existing_id

    # decision_hash: hash determinista del propio documento sin el hash.
    body = {k: v for k, v in doc.items() if k != "decision_hash"}
    doc["decision_hash"] = _hash(sha256_hex(_canonical(body)))

    validate_document(doc)
    return doc


def build_audit_event(
    candidate: dict[str, Any],
    event_type: str,
    actor_id: str,
    *,
    actor_type: str = "HUMAN",
    before_hash: Optional[dict[str, Any]] = None,
    after_hash: Optional[dict[str, Any]] = None,
    request_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    timestamp: Optional[str] = None,
) -> dict[str, Any]:
    """Construye y VALIDA un review-audit-event v1 (no lo persiste)."""
    ts = timestamp or _now_iso()
    event_id = "evt_" + _stable_suffix(candidate["candidate_id"], event_type, ts, actor_id)
    doc: dict[str, Any] = {
        **_envelope(candidate),
        "document_type": "review-audit-event",
        "document_id": "review-audit-event_" + event_id,
        "created_at": ts,
        "event_id": event_id,
        "event_type": event_type,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "timestamp": ts,
        "candidate_id": candidate["candidate_id"],
        "plan_id": None,
        "request_id": request_id,
        "before_hash": before_hash,
        "after_hash": after_hash,
        "metadata": metadata or {"ui": "review-console"},
    }
    validate_document(doc)
    return doc


# ---------------------------------------------------------------------------
# Acción de revisión: control optimista + persistencia en laboratorio
# ---------------------------------------------------------------------------
class DecisionResult:
    """Resultado de una acción del panel."""

    def __init__(self, *, ok: bool, decision: Optional[dict[str, Any]],
                 audit_event: dict[str, Any], stale: bool = False,
                 current_hash: Optional[dict[str, Any]] = None):
        self.ok = ok
        self.decision = decision
        self.audit_event = audit_event
        self.stale = stale
        self.current_hash = current_hash


def submit_decision(
    source_id: str,
    candidate_id: str,
    action: str,
    reviewer_id: str,
    expected_candidate_hash: dict[str, Any],
    *,
    reviewer_type: str = "HUMAN",
    reason_code: Optional[str] = None,
    comment: Optional[str] = None,
    after: Optional[dict[str, Any]] = None,
    target_existing_id: Optional[str] = None,
    request_id: Optional[str] = None,
    fixtures_dir: Optional[Path] = None,
    store: Optional[Path] = None,
) -> DecisionResult:
    """Registra una decisión de revisión aplicando control optimista.

    - Si el candidato no existe → ReviewConsoleError.
    - Si ``expected_candidate_hash`` != hash actual → NO se escribe la decisión;
      se registra un audit-event ``STALE_REVIEW_REJECTED`` y ``ok=False``.
    - En caso normal: escribe review-decision + audit-event (DECISION_RECORDED)
      en el almacén de laboratorio (JSONL). NUNCA toca Neo4j ni el review original.
    """
    store = store or lab_store_dir()
    candidate = get_candidate(source_id, candidate_id, fixtures_dir)
    if candidate is None:
        raise ReviewConsoleError(f"candidato no encontrado: {source_id}/{candidate_id}")

    current = candidate_hash(candidate)

    # Control optimista: la revisión es obsoleta si el hash no coincide.
    if expected_candidate_hash != current:
        event = build_audit_event(
            candidate, "STALE_REVIEW_REJECTED", reviewer_id,
            actor_type=reviewer_type, before_hash=current,
            request_id=request_id,
            metadata={"ui": "review-console", "attempted_action": action,
                      "reason": "expected_candidate_hash_mismatch"},
        )
        _append_jsonl(_audit_path(store), event)
        return DecisionResult(ok=False, decision=None, audit_event=event,
                              stale=True, current_hash=current)

    decision = build_decision(
        candidate, action, reviewer_id, expected_candidate_hash,
        reviewer_type=reviewer_type, reason_code=reason_code, comment=comment,
        after=after, target_existing_id=target_existing_id,
    )
    event = build_audit_event(
        candidate, "DECISION_RECORDED", reviewer_id,
        actor_type=reviewer_type, before_hash=current,
        after_hash=decision["decision_hash"], request_id=request_id,
        metadata={"ui": "review-console", "action": action},
    )
    # Escritura append-only en laboratorio (decisión + auditoría).
    _append_jsonl(_decisions_path(store), decision)
    _append_jsonl(_audit_path(store), event)
    return DecisionResult(ok=True, decision=decision, audit_event=event,
                          current_hash=current)


# ---------------------------------------------------------------------------
# Vista enriquecida para plantillas
# ---------------------------------------------------------------------------
def candidate_view(candidate: dict[str, Any]) -> dict[str, Any]:
    """Proyección para la plantilla: campos clave + hash + acciones válidas."""
    ch = candidate_hash(candidate)
    matches = candidate.get("existing_matches", [])
    prov = candidate.get("provenance", {})
    return {
        "candidate_id": candidate["candidate_id"],
        "segment_id": candidate["segment_id"],
        "candidate_kind": candidate["candidate_kind"],
        "entity_type": candidate["entity_type"],
        "canonical_name": candidate["canonical_name"],
        "display_name": candidate["display_name"],
        "description": candidate.get("description", ""),
        "confidence": candidate["confidence"],
        "proposed_status": candidate["proposed_status"],
        "policy_reasons": candidate.get("policy_reasons", []),
        "existing_matches": matches,
        "has_matches": bool(matches),
        "provenance": {
            "source_id": prov.get("source_id"),
            "review_generation": prov.get("review_generation"),
            "pipeline_version": prov.get("pipeline_version"),
            "producer": prov.get("producer", {}).get("name"),
        },
        "candidate_hash": ch["value"],
        "candidate_hash_obj": ch,
        "actions": sorted(VALID_ACTIONS),
    }
