"""export_import.py — Paquetes de conocimiento S9 Knowledge v0.2.5b

Cuatro tipos de paquete (formato JSON):
  1. KnowledgePackage       — export completo de un source ya procesado
  2. ExternalReviewRequest  — solicitud de revision a agente/humano externo
  3. ExternalReviewResponse — respuesta externa validada/cargada
  4. ImportedCandidatePackage — candidatos generados fuera del pipeline

Reglas fundamentales:
  - Ninguna funcion escribe en Neo4j.
  - Los candidatos externos entran siempre por el pipeline
    (validate -> resolve -> auto_decide -> approved_payload -> ingest-approved).
  - La sanitizacion elimina rutas internas, IPs y secretos antes de exportar.

No hay subcomandos en cli/data_review.py — las funciones se integraran
desde ahi o mediante scripts externos en la siguiente fase.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── Constantes de version ─────────────────────────────────────────────────────

PACKAGE_SCHEMA_VERSION = "0.2.5"
PRODUCER = "s9-knowledge"


# ─────────────────────────────────────────────────────────────────────────────
# Utilidades comunes
# ─────────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Any:
    """Lee un JSON con manejo de error claro."""
    if not path.exists():
        raise FileNotFoundError(f"No existe: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON invalido en {path}: {exc}") from exc


def _workspace_dir(repo_root: Path, workspace: str, source_id: str) -> Path:
    return repo_root / "output" / "reviews" / workspace / source_id


# ─────────────────────────────────────────────────────────────────────────────
# SANITIZACION — obligatoria antes de cualquier export externo
# ─────────────────────────────────────────────────────────────────────────────

def _build_redact_patterns():
    """Construye la lista de patrones de redaccion."""
    pairs = []
    # Rutas absolutas de despliegue
    pairs.append((re.compile(r"/opt/[^\s\x22\x27>,]+"), "[RUTA_INTERNA]"))
    pairs.append((re.compile(r"/mnt/[^\s\x22\x27>,]+"), "[RUTA_INTERNA]"))
    pairs.append((re.compile(r"/home/[^\s\x22\x27>,]+"), "[RUTA_INTERNA]"))
    pairs.append((re.compile(r"/var/[^\s\x22\x27>,]+"), "[RUTA_INTERNA]"))
    # IPs de red privada
    pairs.append((re.compile(r"192\.168\.\d{1,3}\.\d{1,3}"), "[IP_INTERNA]"))
    pairs.append((re.compile(r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}"), "[IP_INTERNA]"))
    pairs.append((re.compile(r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"), "[IP_INTERNA]"))
    # Hostnames internos reconocibles
    pairs.append((re.compile(r"knowledge\.seccionnueve[^\s\x22\x27>,]*"), "[HOST_INTERNO]"))
    # Tokens/secrets tipicos
    pairs.append((re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-_.~+/]+=*"), r"\1[TOKEN_REDACTADO]"))
    pairs.append((re.compile(r"(?i)(api[_-]?key[\s=:]+)[^\s,;\x22\x27]+"), r"\1[API_KEY_REDACTADA]"))
    pairs.append((re.compile(r"(?i)(password[\s=:]+)[^\s,;\x22\x27]+"), r"\1[PASSWORD_REDACTADA]"))
    pairs.append((re.compile(r"(?i)(secret[\s=:]+)[^\s,;\x22\x27]+"), r"\1[SECRET_REDACTADO]"))
    pairs.append((re.compile(r"(?i)(token[\s=:]+)[^\s,;\x22\x27]+"), r"\1[TOKEN_REDACTADO]"))
    # Neo4j URIs
    pairs.append((re.compile(r"bolt://[^\s\x22\x27>,]+"), "[NEO4J_URI_REDACTADA]"))
    pairs.append((re.compile(r"neo4j://[^\s\x22\x27>,]+"), "[NEO4J_URI_REDACTADA]"))
    return pairs


_REDACT_PATTERNS = _build_redact_patterns()

# Tipos de kind validos
_VALID_KINDS = frozenset({
    "entity", "relation", "event", "alias", "location",
    "object", "rumor", "session_fact", "merge", "rejection", "type_change",
})

# Campos requeridos para ImportedCandidatePackage
_IMPORT_REQUIRED_FIELDS = ("workspace", "source_id", "schema_version", "candidates")


def sanitize_text(text: str) -> str:
    """Aplica todos los patrones de redaccion a un texto plano."""
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def sanitize_value(value: Any) -> Any:
    """Sanitiza recursivamente strings dentro de estructuras Python (dict/list/str)."""
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {k: sanitize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    return value


def sanitize_object(obj: dict) -> dict:
    """Sanitiza un objeto completo (alias de sanitize_value para dicts)."""
    return sanitize_value(obj)  # type: ignore[return-value]


# ─────────────────────────────────────────────────────────────────────────────
# TIPO 1 — KnowledgePackage
# ─────────────────────────────────────────────────────────────────────────────

class KnowledgePackage:
    """Paquete de exportacion completo de un source procesado.

    Contiene: manifest, workspace metadata, sources, entidades/relaciones/
    aliases/evidencias del approved_payload y quality_report opcional.
    Construido desde los JSON del pipeline; jamas consulta Neo4j.
    """

    PACKAGE_TYPE = "knowledge_package"

    @staticmethod
    def build(
        workspace: str,
        source_id: str,
        repo_root: Path,
        output_path: Path | None = None,
    ) -> dict:
        """Construye el paquete y lo guarda en output_path si se indica.

        Returns:
            dict con el paquete completo.
        """
        ws_dir = _workspace_dir(repo_root, workspace, source_id)

        # -- Pipeline state (obligatorio) --
        pipeline_state = _read_json(ws_dir / "pipeline_state.json")

        # -- Approved payload (obligatorio) --
        approved_raw = _read_json(ws_dir / "approved_payload.json")
        approved_items: list[dict] = approved_raw.get("approved", [])

        # Clasificar por kind
        entities = [a for a in approved_items if a.get("kind") == "entity"]
        relations = [a for a in approved_items if a.get("kind") == "relation"]
        aliases = [a for a in approved_items if a.get("kind") == "alias"]
        events = [a for a in approved_items if a.get("kind") == "event"]
        other = [
            a for a in approved_items
            if a.get("kind") not in {"entity", "relation", "alias", "event"}
        ]

        # Extraer evidencias
        evidence = [
            {
                "candidate_id": a.get("candidate_id"),
                "evidence": a.get("evidence", ""),
                "source_id": a.get("source_id", source_id),
                "timestamp_start": a.get("source_timestamp_start", a.get("timestamp_start", "")),
                "timestamp_end": a.get("source_timestamp_end", a.get("timestamp_end", "")),
            }
            for a in approved_items
            if a.get("evidence")
        ]

        # -- Review queue (items pendientes de revision humana) --
        review_queue: list[dict] = []
        rq_path = ws_dir / "review_queue.json"
        if rq_path.exists():
            review_queue = _read_json(rq_path)

        # -- Quality report (opcional) --
        quality_report: dict | None = None
        quality_dir = repo_root / "output" / "reviews" / workspace / "graph_quality"
        if quality_dir.exists():
            quality_report = {}
            for fname in [
                "duplicate_candidates.json",
                "bad_relations.json",
                "missing_metadata.json",
            ]:
                fpath = quality_dir / fname
                if fpath.exists():
                    quality_report[fname.replace(".json", "")] = _read_json(fpath)

        # -- Manifest --
        manifest = {
            "package_type": KnowledgePackage.PACKAGE_TYPE,
            "version": "1.0",
            "schema_version": PACKAGE_SCHEMA_VERSION,
            "created_at": _now_iso(),
            "workspace": workspace,
            "source_id": source_id,
            "producer": PRODUCER,
            "pipeline_completed": all(
                v.get("status") == "done"
                for v in pipeline_state.values()
            ),
            "counts": {
                "entities": len(entities),
                "relations": len(relations),
                "aliases": len(aliases),
                "events": len(events),
                "other": len(other),
                "total_approved": len(approved_items),
                "pending_review": len(review_queue),
            },
        }

        package = {
            "manifest": manifest,
            "workspace_metadata": {
                "workspace": workspace,
                "source_id": source_id,
                "pipeline_state": pipeline_state,
            },
            "entities": entities,
            "relations": relations,
            "aliases": aliases,
            "events": events,
            "other": other,
            "evidence": evidence,
            "review_queue": review_queue,
            "approved_payload": approved_raw,
            "quality_report": quality_report,
        }

        if output_path is not None:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(package, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info("[KnowledgePackage] Guardado en %s", output_path)

        return package


def build_knowledge_package(
    workspace: str,
    source_id: str,
    repo_root: Path,
    output_path: Path | None = None,
) -> dict:
    """Construye un KnowledgePackage desde los JSON del pipeline.

    No consulta Neo4j. Si output_path se indica, persiste el JSON.
    """
    return KnowledgePackage.build(workspace, source_id, repo_root, output_path)


# ─────────────────────────────────────────────────────────────────────────────
# TIPO 2 — ExternalReviewRequest
# ─────────────────────────────────────────────────────────────────────────────

class ExternalReviewRequest:
    """Paquete de solicitud de revision a agente/humano externo.

    La sanitizacion es OBLIGATORIA y se aplica automaticamente.
    """

    PACKAGE_TYPE = "external_review_request"

    @staticmethod
    def build(
        workspace: str,
        source_id: str,
        repo_root: Path,
        glossary_limit: int = 50,
        output_path: Path | None = None,
    ) -> dict:
        """Construye el request de revision externa (sanitizado)."""
        ws_dir = _workspace_dir(repo_root, workspace, source_id)

        # -- Segments --
        segments_raw = _read_json(ws_dir / "segments.json")

        # -- Review queue --
        review_queue: list[dict] = []
        rq_path = ws_dir / "review_queue.json"
        if rq_path.exists():
            review_queue = _read_json(rq_path)

        # -- Candidates --
        candidates_raw = _read_json(ws_dir / "candidates.json")

        # -- Glossary snapshot --
        glossary_snapshot: list[dict] = []
        try:
            _app_dir = Path(__file__).resolve().parents[1]
            if str(_app_dir) not in sys.path:
                sys.path.insert(0, str(_app_dir))
            from glossary.glossary_store import GlossaryStore
            gloss_db = repo_root / "state" / "glossary.db"
            if gloss_db.exists():
                store = GlossaryStore(gloss_db)
                terms = store.list_terms(workspace, enabled_only=True, limit=glossary_limit)
                glossary_snapshot = [
                    {
                        "canonical_term": t.canonical_term,
                        "term_type": t.term_type,
                        "aliases": t.aliases,
                        "priority": t.priority,
                        "frequency": t.frequency,
                    }
                    for t in terms
                ]
        except Exception as exc:
            log.warning("[ExternalReviewRequest] No se pudo cargar glosario: %s", exc)

        # -- Schema summary --
        entity_types_seen = list({
            c.get("entity_type") for c in candidates_raw if c.get("entity_type")
        })
        relation_types_seen = list({
            c.get("relation_type") for c in candidates_raw if c.get("relation_type")
        })
        schema_summary = {
            "entity_types": sorted(entity_types_seen),
            "relation_types": sorted(relation_types_seen),
            "kinds": [
                "entity", "relation", "event", "alias",
                "location", "object", "rumor", "session_fact",
            ],
        }

        # -- Source metadata (sin rutas internas) --
        source_metadata = {
            "workspace": workspace,
            "source_id": source_id,
            "source_kind": (
                candidates_raw[0].get("source_kind", "audio") if candidates_raw else "audio"
            ),
            "segment_count": len(segments_raw),
            "candidate_count": len(candidates_raw),
            "pending_review_count": len(review_queue),
        }

        instructions = (
            "Revisa los candidatos en review_queue y propone correcciones, nuevas entidades, "
            "relaciones, aliases o merges. Usa el formato ExternalReviewResponse. "
            "Todos los candidatos propuestos deben incluir evidence (texto fuente) y confidence (0.0-1.0). "
            "NO incluyas rutas de sistema, IPs, tokens ni credenciales en la respuesta."
        )

        request = {
            "package_type": ExternalReviewRequest.PACKAGE_TYPE,
            "schema_version": PACKAGE_SCHEMA_VERSION,
            "created_at": _now_iso(),
            "workspace": workspace,
            "source_id": source_id,
            "instructions": instructions,
            "source_metadata": source_metadata,
            "transcript_segments": segments_raw,
            "candidates": candidates_raw,
            "review_queue": review_queue,
            "glossary_snapshot": glossary_snapshot,
            "schema_summary": schema_summary,
        }

        # SANITIZACION OBLIGATORIA
        request = sanitize_object(request)

        if output_path is not None:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(request, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info("[ExternalReviewRequest] Guardado (sanitizado) en %s", output_path)

        return request


def build_external_review_request(
    workspace: str,
    source_id: str,
    repo_root: Path,
    glossary_limit: int = 50,
    output_path: Path | None = None,
) -> dict:
    """Construye un ExternalReviewRequest sanitizado. No consulta Neo4j."""
    return ExternalReviewRequest.build(
        workspace, source_id, repo_root, glossary_limit, output_path
    )


# ─────────────────────────────────────────────────────────────────────────────
# TIPO 3 — ExternalReviewResponse
# ─────────────────────────────────────────────────────────────────────────────

_ENTITY_REQUIRED = ("name", "entity_type")
_RELATION_REQUIRED = ("from_entity", "to_entity", "relation_type")


class ExternalReviewResponse:
    """Paquete de respuesta externa con candidatos propuestos.

    Validacion estricta. La carga devuelve candidatos con origin='external',
    nunca escribe en Neo4j.
    """

    PACKAGE_TYPE = "external_review_response"

    @staticmethod
    def validate(data: Any) -> tuple[bool, list[str]]:
        """Valida la estructura de una respuesta externa.

        Returns:
            (valid: bool, errors: list[str])
        """
        errors: list[str] = []

        if not isinstance(data, dict):
            return False, ["El paquete debe ser un dict JSON"]

        pkg_type = data.get("package_type", "")
        if pkg_type and pkg_type != ExternalReviewResponse.PACKAGE_TYPE:
            errors.append(f"package_type incorrecto: {pkg_type!r}")

        if not data.get("workspace"):
            errors.append("Falta campo obligatorio: workspace")

        if not data.get("schema_version"):
            errors.append("Falta campo obligatorio: schema_version")

        if "suggested_entities" not in data:
            errors.append("Falta campo obligatorio: suggested_entities")

        # Validar candidatos propuestos
        all_candidates = (
            data.get("suggested_entities", [])
            + data.get("suggested_relations", [])
            + data.get("suggested_aliases", [])
        )

        for i, cand in enumerate(all_candidates):
            if not isinstance(cand, dict):
                errors.append(f"Candidato[{i}] no es un dict")
                continue

            kind = cand.get("kind", "")
            if kind and kind not in _VALID_KINDS:
                errors.append(f"Candidato[{i}]: kind desconocido {kind!r}")

            if not cand.get("evidence"):
                errors.append(f"Candidato[{i}]: falta evidence (obligatorio)")

            conf = cand.get("confidence")
            if conf is not None and not isinstance(conf, (int, float)):
                errors.append(f"Candidato[{i}]: confidence debe ser numerico")
            elif conf is not None and not (0.0 <= float(conf) <= 1.0):
                errors.append(f"Candidato[{i}]: confidence fuera de rango [0,1]")

            if kind == "entity":
                for req in _ENTITY_REQUIRED:
                    if not cand.get(req):
                        errors.append(f"Candidato[{i}] entity: falta {req!r}")
            elif kind == "relation":
                for req in _RELATION_REQUIRED:
                    if not cand.get(req):
                        errors.append(f"Candidato[{i}] relation: falta {req!r}")

        return len(errors) == 0, errors

    @staticmethod
    def load(data: Any, workspace: str | None = None) -> list[dict]:
        """Valida y carga la respuesta, devolviendo candidatos con origin='external'.

        NUNCA escribe en Neo4j. La salida se inyecta al pipeline:
        validate -> resolve -> auto_decide -> approved_payload -> ingest-approved.

        Raises:
            ValueError: si la validacion falla
        """
        valid, errors = ExternalReviewResponse.validate(data)
        if not valid:
            raise ValueError(
                "ExternalReviewResponse invalida:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        pkg_workspace = data.get("workspace", "")
        if workspace and pkg_workspace and pkg_workspace != workspace:
            raise ValueError(
                f"Workspace no coincide: paquete={pkg_workspace!r}, esperado={workspace!r}"
            )

        return external_response_to_candidates(data)


def external_response_to_candidates(response: dict) -> list[dict]:
    """Convierte una ExternalReviewResponse validada en candidatos con origin='external'.

    Punto de entrada al pipeline para respuestas externas.
    Los candidatos pasan por: validate -> resolve -> auto_decide -> approved_payload -> ingest-approved.
    """
    workspace = response.get("workspace", "")
    source_id = response.get("source_id", "")
    now = _now_iso()
    candidates: list[dict] = []

    proposed = (
        [(c, "entity") for c in response.get("suggested_entities", [])]
        + [(c, "relation") for c in response.get("suggested_relations", [])]
        + [(c, "alias") for c in response.get("suggested_aliases", [])]
    )
    for merge in response.get("suggested_merges", []):
        proposed.append((merge, "merge"))
    for rejection in response.get("suggested_rejections", []):
        proposed.append((rejection, "rejection"))
    for tc in response.get("suggested_type_changes", []):
        proposed.append((tc, "type_change"))

    for raw, default_kind in proposed:
        if not isinstance(raw, dict):
            continue
        cand_id = raw.get("candidate_id") or f"ext_{uuid.uuid4().hex[:12]}"
        candidates.append({
            "candidate_id": cand_id,
            "source_id": raw.get("source_id", source_id),
            "segment_id": raw.get("segment_id", ""),
            "workspace": raw.get("workspace", workspace),
            "kind": raw.get("kind", default_kind),
            "name": raw.get("name"),
            "entity_type": raw.get("entity_type"),
            "from_entity": raw.get("from_entity"),
            "to_entity": raw.get("to_entity"),
            "from_type": raw.get("from_type"),
            "to_type": raw.get("to_type"),
            "relation_type": raw.get("relation_type"),
            "event_description": raw.get("event_description"),
            "confidence": float(raw.get("confidence", 0.7)),
            "evidence": raw.get("evidence", ""),
            "timestamp_start": raw.get("timestamp_start", ""),
            "timestamp_end": raw.get("timestamp_end", ""),
            "source_kind": raw.get("source_kind", "external"),
            "status": "pending",
            "origin": "external",
            "_external_warnings": response.get("warnings", []),
            "_external_confidence": response.get("confidence"),
            "_imported_at": now,
        })

    return candidates


def load_external_response(
    data: Any,
    workspace: str | None = None,
) -> list[dict]:
    """Valida y carga una respuesta externa como candidatos con origin='external'.

    Alias de alto nivel de ExternalReviewResponse.load().
    """
    return ExternalReviewResponse.load(data, workspace=workspace)


# ─────────────────────────────────────────────────────────────────────────────
# TIPO 4 — ImportedCandidatePackage
# ─────────────────────────────────────────────────────────────────────────────

class ImportedCandidatePackage:
    """Paquete de candidatos generado fuera del pipeline S9 Knowledge.

    Validacion: schema, workspace, timestamps, evidence.
    Todos los candidatos quedan marcados con origin='imported'.
    NUNCA escribe directamente en Neo4j.
    """

    PACKAGE_TYPE = "imported_candidate_package"

    @staticmethod
    def validate(data: Any) -> tuple[bool, list[str]]:
        """Valida la estructura del paquete importado."""
        errors: list[str] = []

        if not isinstance(data, dict):
            return False, ["El paquete debe ser un dict JSON"]

        pkg_type = data.get("package_type", "")
        if pkg_type and pkg_type != ImportedCandidatePackage.PACKAGE_TYPE:
            errors.append(f"package_type incorrecto: {pkg_type!r}")

        for field_name in _IMPORT_REQUIRED_FIELDS:
            if not data.get(field_name):
                errors.append(f"Falta campo obligatorio: {field_name!r}")

        candidates = data.get("candidates", [])
        if not isinstance(candidates, list):
            errors.append("candidates debe ser una lista")
            return False, errors

        for i, cand in enumerate(candidates):
            if not isinstance(cand, dict):
                errors.append(f"Candidato[{i}] no es un dict")
                continue

            kind = cand.get("kind", "")
            if kind and kind not in _VALID_KINDS:
                errors.append(f"Candidato[{i}]: kind desconocido {kind!r}")

            if not cand.get("evidence"):
                errors.append(f"Candidato[{i}]: falta evidence (obligatorio)")

            conf = cand.get("confidence")
            if conf is not None:
                try:
                    c = float(conf)
                    if not (0.0 <= c <= 1.0):
                        errors.append(f"Candidato[{i}]: confidence fuera de rango [0,1]")
                except (TypeError, ValueError):
                    errors.append(f"Candidato[{i}]: confidence no es numerico")

        return len(errors) == 0, errors

    @staticmethod
    def load(data: Any) -> list[dict]:
        """Valida y carga el paquete importado como candidatos con origin='imported'.

        Raises:
            ValueError: si la validacion falla
        """
        valid, errors = ImportedCandidatePackage.validate(data)
        if not valid:
            raise ValueError(
                "ImportedCandidatePackage invalido:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        workspace = data["workspace"]
        source_id = data["source_id"]
        now = _now_iso()
        candidates: list[dict] = []

        for raw in data.get("candidates", []):
            if not isinstance(raw, dict):
                continue
            cand_id = raw.get("candidate_id") or f"imp_{uuid.uuid4().hex[:12]}"
            candidates.append({
                "candidate_id": cand_id,
                "source_id": raw.get("source_id", source_id),
                "segment_id": raw.get("segment_id", ""),
                "workspace": raw.get("workspace", workspace),
                "kind": raw.get("kind", "entity"),
                "name": raw.get("name"),
                "entity_type": raw.get("entity_type"),
                "from_entity": raw.get("from_entity"),
                "to_entity": raw.get("to_entity"),
                "from_type": raw.get("from_type"),
                "to_type": raw.get("to_type"),
                "relation_type": raw.get("relation_type"),
                "event_description": raw.get("event_description"),
                "confidence": float(raw.get("confidence", 0.5)),
                "evidence": raw.get("evidence", ""),
                "timestamp_start": raw.get("timestamp_start", ""),
                "timestamp_end": raw.get("timestamp_end", ""),
                "source_kind": raw.get("source_kind", "imported"),
                "status": "pending",
                "origin": "imported",
                "_imported_at": now,
            })

        return candidates


def load_imported_package(data: Any) -> list[dict]:
    """Valida y carga un ImportedCandidatePackage como candidatos con origin='imported'."""
    return ImportedCandidatePackage.load(data)


def validate_imported_package(data: Any) -> tuple[bool, list[str]]:
    """Valida un ImportedCandidatePackage sin cargarlo."""
    return ImportedCandidatePackage.validate(data)
