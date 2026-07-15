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

USE_EXISTING: verifica existencia sin modificar ninguna propiedad.
Requiere exactamente 1 coincidencia por canonical_name inequívoco.
Sin procedencia multifuente: el candidato debe estar marcado como
DEFERRED_USE_EXISTING_UNTIL_MULTI_SOURCE_PROVENANCE y excluido del payload.
"""
from __future__ import annotations
import json
import logging
import os
import sys
from pathlib import Path

try:
    from neo4j import GraphDatabase as GraphDatabase
except ImportError:
    GraphDatabase = None  # optional dependency, required only for real writes

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
    name = item.get("name") or item.get("candidate_id") or "?"
    return str(name)


def _is_use_existing(item: dict) -> bool:
    """Detecta si un item aprobado corresponde a USE_EXISTING."""
    return (
        item.get("review_action") == "use-existing"
        or item.get("resolver_action") == "use_existing"
        or item.get("recommendation") == "USE_EXISTING"
    )


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

    # USE_EXISTING no requiere evidence propio (el nodo existente ya lo tiene)
    no_evidence = [
        _item_label(e) for e in entities
        if not str(e.get("evidence", "")).strip() and not _is_use_existing(e)
    ]
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


# Allowlist de labels/tipos de entidad (no se interpola ningún tipo arbitrario en Cypher).
_ALLOWED_LABELS = ("Character", "Location", "Faction", "Object", "Event", "Concept")

# Propiedades de procedencia OBLIGATORIAS y explícitas para una entidad nueva
# (sin defaults silenciosos: audio/transcript/auto_approved/player quedan prohibidos).
_REQUIRED_NEW_ENTITY_FIELDS = (
    "source_id", "source_kind", "source_document", "workspace",
    "knowledge_layer", "visibility", "review_status",
    "reviewed_by", "reviewed_at", "review_action", "evidence", "confidence",
)


def _is_deferred(item: dict) -> bool:
    """Candidato aplazado (p. ej. DEFERRED_USE_EXISTING_UNTIL_MULTI_SOURCE_PROVENANCE)."""
    return item.get("deferred") is True or "DEFERRED" in str(item.get("review_action", "")).upper()


def _validate_write_provenance(payload) -> list:
    """Exige procedencia EXPLÍCITA por entidad nueva. Sin defaults silenciosos.
    USE_EXISTING y aplazados quedan exentos (no se escriben propiedades nuevas)."""
    errors = []
    for e in payload.get("approved", []):
        if e.get("kind") != "entity" or _is_use_existing(e) or _is_deferred(e):
            continue
        label = _item_label(e)
        for f in _REQUIRED_NEW_ENTITY_FIELDS:
            v = e.get(f)
            if f == "confidence":
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    errors.append("%s: falta 'confidence' explícita" % label)
            elif not str(v if v is not None else "").strip():
                errors.append("%s: falta propiedad obligatoria '%s'" % (label, f))
        et = e.get("entity_type")
        if et not in _ALLOWED_LABELS:
            errors.append("%s: entity_type '%s' no permitido (allowlist)" % (label, et))
        rs = str(e.get("review_status", "")).strip().lower()
        if rs == "auto_approved":
            errors.append("%s: review_status=auto_approved prohibido para revisión humana" % label)
    return errors


def _build_create_entity(item):
    """Devuelve (label, props) para CREATE-only. Valida el label contra la allowlist.
    Usa EXCLUSIVAMENTE valores explícitos del item (ningún default inventado)."""
    etype = item.get("entity_type")
    if etype not in _ALLOWED_LABELS:
        raise ValueError("entity_type no permitido para escritura: %r" % etype)
    props = {
        "canonical_name": item.get("name", ""),
        "source_id": item["source_id"],
        "source_kind": item["source_kind"],
        "source_document": item["source_document"],
        "source_timestamp_start": item.get("source_timestamp_start", ""),
        "source_timestamp_end": item.get("source_timestamp_end", ""),
        "workspace": item["workspace"],
        "entity_type": etype,
        "knowledge_layer": item["knowledge_layer"],
        "visibility": item["visibility"],
        "review_status": item["review_status"],
        "reviewed_by": item["reviewed_by"],
        "reviewed_at": item["reviewed_at"],
        "review_action": item["review_action"],
        "review_reason": item.get("review_reason", ""),
        "review_report_sha256": item.get("review_report_sha256", ""),
        "approval_mode": item.get("approval_mode", "human_approved"),
        "confidence": item["confidence"],
        "evidence": item["evidence"],
    }
    return etype, props


def _count_by_name(session, name: str) -> int:
    rec = session.run("MATCH (n {canonical_name: $name}) RETURN count(n) AS c", {"name": name}).single()
    return rec["c"] if rec else 0


def _neo4j_preflight(session, entities_new, entities_use_existing) -> dict:
    """Consulta Neo4j (lectura) y clasifica cada candidato. CREATE-only nunca
    actualiza ni sobrescribe: would_update / would_overwrite son siempre 0."""
    rep = {"would_create": 0, "would_verify_existing": 0, "conflict_existing": 0,
           "ambiguous_existing": 0, "would_update": 0, "would_overwrite": 0, "errors": []}
    for e in entities_new:
        c = _count_by_name(session, e.get("name", ""))
        if c == 0:
            rep["would_create"] += 1
        elif c == 1:
            rep["conflict_existing"] += 1
            rep["errors"].append("CONFLICT_EXISTING_NODE: '%s' ya existe pero se clasificó como nuevo" % e.get("name"))
        else:
            rep["ambiguous_existing"] += 1
            rep["errors"].append("AMBIGUOUS_EXISTING_NODES: '%s' (%d coincidencias)" % (e.get("name"), c))
    for e in entities_use_existing:
        c = _count_by_name(session, e.get("name", ""))
        if c == 1:
            rep["would_verify_existing"] += 1
        elif c == 0:
            rep["errors"].append("USE_EXISTING sin nodo: '%s'" % e.get("name"))
        else:
            rep["errors"].append("USE_EXISTING ambiguo: '%s' (%d)" % (e.get("name"), c))
    return rep


def _tx_create_all(tx, entities_new, entities_use_existing) -> int:
    """Transacción atómica (§9): reverifica dentro de la transacción y aborta
    (rollback total) ante cualquier conflicto; crea las entidades nuevas con
    CREATE (nunca MERGE ni SET +=). USE_EXISTING solo se verifica, sin mutar."""
    for e in entities_new:
        c = tx.run("MATCH (n {canonical_name: $name}) RETURN count(n) AS c",
                   {"name": e.get("name", "")}).single()["c"]
        if c != 0:
            raise RuntimeError("CONFLICT_EXISTING_NODE '%s': transacción completa abortada (rollback)" % e.get("name"))
    for e in entities_use_existing:
        c = tx.run("MATCH (n {canonical_name: $name}) RETURN count(n) AS c",
                   {"name": e.get("name", "")}).single()["c"]
        if c != 1:
            raise RuntimeError("USE_EXISTING '%s' cnt=%d: abortado" % (e.get("name"), c))
    created = 0
    for e in entities_new:
        label, props = _build_create_entity(e)  # label validado contra allowlist
        tx.run("CREATE (n:Entity:`%s`) SET n = $props" % label, {"props": props})
        created += 1
    return created


def _build_match_use_existing_query(item):
    """
    Genera consulta MATCH para USE_EXISTING.
    Verifica exactamente 1 coincidencia. NO modifica ninguna propiedad.

    Reglas aplicadas:
      1. MATCH por canonical_name (identificador inequívoco aprobado).
      2. Falla si no existe exactamente 1 nodo.
      3. No crea nodo nuevo (no usa MERGE).
      4. No cambia canonical_name, display_name, entity_type, description,
         confidence, aliases, created_at, source_document, source_kind, source_pages.
      5. No reemplaza aliases ni procedencia existente.
      6. Sin multisource -> el candidato debe estar APLAZADO antes de llegar aquí.
      7. No actualiza updated_at (sin mutación segura aplicable).
    """
    name = item.get("name", "")
    cypher_count = "MATCH (n {canonical_name: $name}) RETURN count(n) AS cnt"
    cypher_verify = (
        "MATCH (n {canonical_name: $name}) "
        "RETURN n.canonical_name AS canonical_name, labels(n) AS labels, "
        "n.entity_type AS entity_type"
    )
    return cypher_count, cypher_verify, {"name": name}


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
        if not str(item.get("evidence", "")).strip() and not _is_use_existing(item):
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
      2. Validación del paquete + procedencia de revisión.

    USE_EXISTING: rama separada que verifica existencia sin mutar ninguna propiedad.
    El candidato USE_EXISTING no debe llegar aquí si está marcado como APLAZADO
    (DEFERRED_USE_EXISTING_UNTIL_MULTI_SOURCE_PROVENANCE).
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

    if _review_policy_name() == "full_human_review":
        prov_errors = _validate_review_provenance(payload)
        if prov_errors:
            raise ValueError(
                "PROVENANCE RECHAZADA bajo full_human_review (SIN escritura en Neo4j):\n"
                + "\n".join("  - %s" % e for e in prov_errors[:15])
            )

    approved = payload.get("approved", [])
    deferred = [a for a in approved if _is_deferred(a)]
    approved = [a for a in approved if not _is_deferred(a)]
    if not approved:
        log.info("[DRY-RUN] No hay candidatos aprobados (tras excluir aplazados: %d).", len(deferred))
        return {"dry_run": True, "would_create": 0, "entities": 0, "relations": 0,
                "use_existing": 0, "deferred": len(deferred)}

    entities_new = [a for a in approved if a.get("kind") == "entity" and not _is_use_existing(a)]
    entities_use_existing = [a for a in approved if a.get("kind") == "entity" and _is_use_existing(a)]
    relations = [a for a in approved if a.get("kind") == "relation"]

    # Primera ingesta controlada: SOLO entidades. Cero relaciones (§3/§8).
    if relations:
        raise ValueError(
            "PAQUETE RECHAZADO: la primera ingesta controlada no admite relaciones (%d presentes)."
            % len(relations))

    # Procedencia EXPLÍCITA obligatoria para entidades nuevas (§6, sin defaults),
    # solo bajo la política de ingesta controlada full_human_review.
    if _review_policy_name() == "full_human_review":
        wp_errors = _validate_write_provenance(payload)
        if wp_errors:
            raise ValueError("PAQUETE RECHAZADO (procedencia incompleta):\n"
                             + "\n".join("  - %s" % e for e in wp_errors[:15]))

    # El dry-run debe conectarse a Neo4j en LECTURA (§3). Si Neo4j no está
    # disponible: el dry-run degrada a "no verificado" (safe_to_write=False, sin
    # crash); la ESCRITURA real mantiene el requisito duro + reverificación atómica.
    neo4j_ok = GraphDatabase is not None and bool(neo4j_password)
    if not neo4j_ok:
        if dry_run:
            print("[DRY-RUN] Neo4j NO disponible: verificación no realizada. safe_to_write=NO.")
            return {"dry_run": True, "neo4j_unavailable": True, "safe_to_write": False,
                    "would_create": len(entities_new), "would_verify_existing": 0,
                    "conflict_existing": 0, "ambiguous_existing": 0, "would_update": 0,
                    "would_overwrite": 0, "relations": len(relations), "deferred": len(deferred),
                    "entities": len(entities_new), "use_existing": len(entities_use_existing),
                    "would_write": len(entities_new),
                    "errors": ["neo4j_unavailable: dry-run no pudo verificar el grafo"]}
        raise RuntimeError("Neo4j no disponible para escritura real. Abortado sin escritura.")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    try:
        with driver.session() as session:
            rep = _neo4j_preflight(session, entities_new, entities_use_existing)
        rep.update({"relations": len(relations), "deferred": len(deferred),
                    "entities_new": len(entities_new), "use_existing": len(entities_use_existing),
                    "entities": len(entities_new), "would_write": len(entities_new)})
        safe = (rep["conflict_existing"] == 0 and rep["ambiguous_existing"] == 0
                and rep["would_update"] == 0 and rep["would_overwrite"] == 0
                and rep["relations"] == 0 and not rep["errors"])

        if dry_run:
            print("\n[DRY-RUN] Verificación conectada a Neo4j en LECTURA — SIN escritura")
            print("  would_create=%d  would_verify_existing=%d  conflict_existing=%d  "
                  "ambiguous_existing=%d  would_update=%d  would_overwrite=%d  relations=%d  deferred=%d"
                  % (rep["would_create"], rep["would_verify_existing"], rep["conflict_existing"],
                     rep["ambiguous_existing"], rep["would_update"], rep["would_overwrite"],
                     rep["relations"], rep["deferred"]))
            for err in rep["errors"]:
                print("  ! %s" % err)
            print("  SEGURO PARA ESCRITURA: %s" % ("SÍ" if safe else "NO"))
            print("[DRY-RUN] Neo4j NO fue modificado.")
            rep["dry_run"] = True
            rep["safe_to_write"] = safe
            return rep

        # --- ESCRITURA REAL: transacción atómica, create-only (§4/§9) ---
        if not safe:
            raise RuntimeError("ABORTADO: preflight no seguro: %s" % rep["errors"][:5])
        with driver.session() as session:
            created = session.execute_write(_tx_create_all, entities_new, entities_use_existing)
        log.info("Ingesta atómica completada: creados=%d verificados=%d",
                 created, len(entities_use_existing))
        return {"dry_run": False, "written": {"entities": created,
                "use_existing_verified": len(entities_use_existing), "relations": 0}}
    except Exception as e:
        log.error("Error/abortado en Neo4j (transacción revertida): %s", e)
        raise
    finally:
        driver.close()


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