"""Ingesta aprobada en Neo4j.

REGLA ABSOLUTA: En esta fase --dry-run es obligatorio.
Sin --dry-run, aborta con mensaje de autorización requerida.

Además, aunque se invoque sin --dry-run, si la variable de entorno
S9K_ALLOW_REAL_INGEST != "true" → aborta con mensaje claro.

Guards adicionales de paquete (rechazan el payload completo):
  - sin workspace
  - sin schema_version
  - entidades sin evidence
  - relaciones inválidas (sin from_entity o to_entity)
  - timestamps rotos (start > end si ambos presentes)
  - origin=external sin validated_by_s9k=true

Lee approved_payload.json y escribe nodos/relaciones en Neo4j
incluyendo provenance completa.
"""
from __future__ import annotations
import json
import logging
import os
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

log = logging.getLogger(__name__)

_ENV_GUARD_ABORT_MSG = (
    "ABORTADO: ingest-approved con escritura real requiere "
    "S9K_ALLOW_REAL_INGEST=true en el entorno. "
    "Esta variable esta ausente o es distinta de 'true'. "
    "Para simular sin escritura usa --dry-run."
)

_DRY_RUN_ABORT_MSG = (
    "ABORTADO: ingest-approved requiere autorización explícita. "
    "Usa --dry-run para simular sin escribir en Neo4j. "
    "Para escritura real, obtén autorización explícita del administrador."
)


def _item_label(item):
    """Retorna etiqueta legible para un item del payload."""
    name = item.get("name") or item.get("candidate_id") or "?"
    return str(name)


def _validate_package(payload):
    """Valida el paquete completo. Retorna lista de errores (vacía = OK)."""
    errors = []

    workspace = payload.get("metadata", {}).get("workspace", "") or payload.get("workspace", "")
    if not workspace:
        errors.append("PAQUETE: workspace ausente en metadata")

    sv = payload.get("metadata", {}).get("schema_version", "") or payload.get("schema_version", "")
    if not sv:
        errors.append("PAQUETE: schema_version ausente en metadata (requerida >= '1.0')")

    approved = payload.get("approved", [])
    entities = [a for a in approved if a.get("kind") == "entity"]
    relations = [a for a in approved if a.get("kind") == "relation"]

    no_evidence = [_item_label(e) for e in entities if not str(e.get("evidence", "")).strip()]
    if no_evidence:
        errors.append("ENTIDADES sin evidence (%d): %s" % (len(no_evidence), no_evidence[:5]))

    bad_relations = []
    for r in relations:
        if not r.get("from_entity") or not r.get("to_entity"):
            bad_relations.append(_item_label(r))
    if bad_relations:
        errors.append("RELACIONES inválidas sin from/to (%d): %s" % (len(bad_relations), bad_relations[:5]))

    broken_ts = []
    for item in approved:
        ts_start = item.get("source_timestamp_start", "")
        ts_end = item.get("source_timestamp_end", "")
        if ts_start and ts_end:
            try:
                if ts_start > ts_end:
                    broken_ts.append("%s: %s>%s" % (_item_label(item), ts_start, ts_end))
            except Exception:
                broken_ts.append("%s (ts_parse_error)" % _item_label(item))
    if broken_ts:
        errors.append("TIMESTAMPS rotos (%d): %s" % (len(broken_ts), broken_ts[:3]))

    origin_pkg = payload.get("origin") or payload.get("metadata", {}).get("origin", "local")
    external_unvalidated = []
    for item in approved:
        item_origin = item.get("origin", origin_pkg)
        if item_origin == "external":
            if not item.get("validated_by_s9k", False):
                external_unvalidated.append(_item_label(item))
    if external_unvalidated:
        errors.append(
            "ORIGIN=external sin validated_by_s9k (%d): %s"
            % (len(external_unvalidated), external_unvalidated[:5])
        )

    return errors


def _build_merge_entity_query(item):
    etype = item.get("entity_type", "Concept")
    name = item.get("name", "")
    cypher = "MERGE (n:%s {canonical_name: $name}) SET n += $props" % etype
    props = {
        "source_id": item.get("source_id", ""),
        "source_kind": item.get("source_kind", "audio"),
        "source_document": item.get("source_document", ""),
        "source_timestamp_start": item.get("source_timestamp_start", ""),
        "source_timestamp_end": item.get("source_timestamp_end", ""),
        "workspace": item.get("workspace", ""),
        "review_status": "auto_approved",
        "knowledge_layer": "transcript",
        "visibility": "player",
        "confidence": item.get("confidence", 0.0),
        "evidence": item.get("evidence", ""),
    }
    return cypher, {"name": name, "props": props}


def _build_merge_relation_query(item):
    rel_type = item.get("relation_type", "RELATED_TO")
    cypher = (
        "MATCH (a {canonical_name: $from_name}), (b {canonical_name: $to_name}) "
        "MERGE (a)-[r:%s]->(b) SET r += $props" % rel_type
    )
    props = {
        "source_id": item.get("source_id", ""),
        "source_kind": item.get("source_kind", "audio"),
        "workspace": item.get("workspace", ""),
        "review_status": "auto_approved",
        "confidence": item.get("confidence", 0.0),
        "evidence": item.get("evidence", ""),
    }
    return cypher, {
        "from_name": item.get("from_entity", ""),
        "to_name": item.get("to_entity", ""),
        "props": props,
    }


_INVALID_REVIEWERS = {"", "system", "auto", "none", "null", "s9k"}


def _review_policy_name() -> str:
    return (os.environ.get("S9K_REVIEW_POLICY", "normal").strip().lower() or "normal")


def _validate_review_provenance(payload) -> list:
    """Bajo full_human_review, cada candidato aprobado debe acreditar revision
    humana explicita. Devuelve lista de errores (vacia si OK). No escribe nada."""
    errors = []
    for item in payload.get("approved", []):
        label = _item_label(item)
        rs = str(item.get("review_status", "")).strip().lower()
        if rs != "approved":
            errors.append(
                "%s: review_status='%s' (se exige 'approved' revisado por humano)"
                % (label, item.get("review_status"))
            )
            continue
        rb = str(item.get("reviewed_by", "")).strip().lower()
        if rb in _INVALID_REVIEWERS:
            errors.append("%s: reviewed_by invalido ('%s')" % (label, item.get("reviewed_by")))
        if not str(item.get("reviewed_at", "")).strip():
            errors.append("%s: reviewed_at ausente" % label)
        if not str(item.get("review_action", "")).strip():
            errors.append("%s: review_action ausente" % label)
        if not str(item.get("evidence", "")).strip():
            errors.append("%s: evidence ausente" % label)
        if not str(item.get("source_id", "")).strip():
            errors.append("%s: source_id ausente" % label)
    return errors


def ingest(
    approved_payload_path,
    dry_run,
    neo4j_uri="bolt://127.0.0.1:7687",
    neo4j_user="neo4j",
    neo4j_password="",
):
    """
    Ingesta el payload aprobado en Neo4j.

    DOBLE GUARD:
      1. Sin --dry-run, S9K_ALLOW_REAL_INGEST debe ser "true".
      2. Validación del paquete: workspace, schema_version, evidence, relations, timestamps, origin.
    """
    if not dry_run:
        allow_real = os.environ.get("S9K_ALLOW_REAL_INGEST", "").strip().lower()
        if allow_real != "true":
            raise RuntimeError(_ENV_GUARD_ABORT_MSG)

    approved_payload_path = Path(approved_payload_path)
    if not approved_payload_path.exists():
        raise FileNotFoundError(
            "approved_payload.json no encontrado: %s. "
            "Ejecuta primero: data_review.py run --dry-run" % approved_payload_path
        )

    with approved_payload_path.open(encoding="utf-8") as f:
        payload = json.load(f)

    pkg_errors = _validate_package(payload)
    if pkg_errors:
        msg = "PAQUETE RECHAZADO. Errores:\n" + "\n".join("  - %s" % e for e in pkg_errors)
        raise ValueError(msg)

    # Politica full_human_review: exige procedencia de revision humana explicita.
    # Rechaza autoaprobados y payloads sin reviewed_by/reviewed_at (sin escribir).
    if _review_policy_name() == "full_human_review":
        prov_errors = _validate_review_provenance(payload)
        if prov_errors:
            raise ValueError(
                "PROVENANCE RECHAZADA bajo full_human_review (SIN escritura en Neo4j):\n"
                + "\n".join("  - %s" % e for e in prov_errors[:15])
            )

    approved = payload.get("approved", [])
    if not approved:
        log.info("[DRY-RUN] No hay candidatos aprobados en el payload.")
        return {"dry_run": True, "would_write": 0, "entities": 0, "relations": 0}

    entities = [a for a in approved if a.get("kind") == "entity"]
    relations = [a for a in approved if a.get("kind") == "relation"]

    if dry_run:
        print("")
        print("[DRY-RUN] Simulación de ingesta — SIN escritura en Neo4j")
        print("  Payload: %s" % approved_payload_path)
        print("  Total aprobados: %d" % len(approved))
        print("  Entidades: %d" % len(entities))
        print("  Relaciones: %d" % len(relations))
        print()

        if entities:
            print("  -- ENTIDADES (primeras 10) --")
            for item in entities[:10]:
                cypher, params = _build_merge_entity_query(item)
                print("  [%s] %s (conf=%.2f)" % (
                    item.get("entity_type", "?"), item.get("name", "?"), item.get("confidence", 0)))
                print("    Cypher: %s" % cypher)
                print("    Params.name: %s" % params["name"])
            if len(entities) > 10:
                print("  ... y %d más" % (len(entities) - 10))

        if relations:
            print()
            print("  -- RELACIONES (primeras 10) --")
            for item in relations[:10]:
                cypher, params = _build_merge_relation_query(item)
                print("  %s -[%s]-> %s (conf=%.2f)" % (
                    item.get("from_entity", "?"), item.get("relation_type", "?"),
                    item.get("to_entity", "?"), item.get("confidence", 0)))
                print("    Cypher: %s" % cypher)
            if len(relations) > 10:
                print("  ... y %d más" % (len(relations) - 10))

        print()
        print("[DRY-RUN] Neo4j NO fue modificado.")

        return {
            "dry_run": True,
            "would_write": len(approved),
            "entities": len(entities),
            "relations": len(relations),
        }

    # Escritura real
    log.info("ESCRITURA REAL en Neo4j: %d entidades, %d relaciones", len(entities), len(relations))
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        written = {"entities": 0, "relations": 0}
        with driver.session() as session:
            for item in entities:
                cypher, params = _build_merge_entity_query(item)
                session.run(cypher, params)
                written["entities"] += 1
            for item in relations:
                cypher, params = _build_merge_relation_query(item)
                session.run(cypher, params)
                written["relations"] += 1
        driver.close()
        log.info("Ingesta completada: %s", written)
        return {"dry_run": False, "written": written}
    except Exception as e:
        log.error("Error en escritura Neo4j: %s", e)
        raise


def _load_neo4j_creds(repo_root):
    env_path = Path(repo_root) / "viewer" / ".env"
    uri, user, password = "bolt://127.0.0.1:7687", "neo4j", ""
    if not env_path.exists():
        return uri, user, password
    try:
        with env_path.open() as f:
            for line in f:
                line = line.strip()
                if line.startswith("S9K_NEO4J_URI="):
                    uri = line.split("=", 1)[1].strip()
                elif line.startswith("S9K_NEO4J_USER="):
                    user = line.split("=", 1)[1].strip()
                elif line.startswith("S9K_NEO4J_PASSWORD="):
                    val = line.split("=", 1)[1].strip()
                    if val:
                        password = val
                elif line.startswith("S9K_NEO4J_PASSWORD_FILE="):
                    pfile = Path(line.split("=", 1)[1].strip())
                    if pfile.exists():
                        password = pfile.read_text().strip()
    except Exception as e:
        log.warning("No se pudo leer viewer/.env: %s", e)
    return uri, user, password


def run(workspace, source_id, repo_root, dry_run=True):
    """Entry point para el CLI."""
    if not dry_run:
        allow_real = os.environ.get("S9K_ALLOW_REAL_INGEST", "").strip().lower()
        if allow_real != "true":
            raise RuntimeError(_ENV_GUARD_ABORT_MSG)

    approved_payload_path = (
        Path(repo_root) / "output" / "reviews" / workspace / source_id / "approved_payload.json"
    )
    neo4j_uri, neo4j_user, neo4j_password = _load_neo4j_creds(repo_root)
    return ingest(
        approved_payload_path, dry_run=dry_run,
        neo4j_uri=neo4j_uri, neo4j_user=neo4j_user, neo4j_password=neo4j_password,
    )
