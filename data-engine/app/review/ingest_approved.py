"""Ingesta aprobada en Neo4j.

REGLA ABSOLUTA: En esta fase --dry-run es obligatorio.
Sin --dry-run, aborta con mensaje de autorización requerida.

Lee approved_payload.json y escribe nodos/relaciones en Neo4j
incluyendo provenance completa: source_id, source_kind, source_document,
source_timestamp_start/end, workspace, review_status, knowledge_layer,
visibility, confidence, evidence.
"""
from __future__ import annotations
import json
import logging
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

log = logging.getLogger(__name__)

_DRY_RUN_ABORT_MSG = (
    "ABORTADO: ingest-approved requiere autorización explícita. "
    "Usa --dry-run para simular sin escribir en Neo4j. "
    "Para escritura real, obtén autorización explícita del administrador."
)


def _build_merge_entity_query(item: dict) -> tuple[str, dict]:
    """Genera la query Cypher para un nodo (solo para dry-run / logging)."""
    etype = item.get("entity_type", "Concept")
    name = item.get("name", "")
    cypher = (
        f"MERGE (n:{etype} {{canonical_name: $name}}) "
        "SET n += $props"
    )
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


def _build_merge_relation_query(item: dict) -> tuple[str, dict]:
    """Genera la query Cypher para una relación (solo para dry-run / logging)."""
    rel_type = item.get("relation_type", "RELATED_TO")
    cypher = (
        "MATCH (a {canonical_name: $from_name}), (b {canonical_name: $to_name}) "
        f"MERGE (a)-[r:{rel_type}]->(b) "
        "SET r += $props"
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


def ingest(
    approved_payload_path: Path,
    dry_run: bool,
    neo4j_uri: str = "bolt://127.0.0.1:7687",
    neo4j_user: str = "neo4j",
    neo4j_password: str = "",
) -> dict:
    """
    Ingesta el payload aprobado en Neo4j.

    FASE ACTUAL: --dry-run obligatorio. Sin él, aborta.
    """
    if not dry_run:
        raise RuntimeError(_DRY_RUN_ABORT_MSG)

    if not approved_payload_path.exists():
        raise FileNotFoundError(
            f"approved_payload.json no encontrado: {approved_payload_path}. "
            "Ejecuta primero: data_review.py run --dry-run"
        )

    with approved_payload_path.open(encoding="utf-8") as f:
        payload = json.load(f)

    approved = payload.get("approved", [])
    if not approved:
        log.info("[DRY-RUN] No hay candidatos aprobados en el payload.")
        return {"dry_run": True, "would_write": 0, "entities": 0, "relations": 0}

    entities = [a for a in approved if a.get("kind") == "entity"]
    relations = [a for a in approved if a.get("kind") == "relation"]

    print(f"\n[DRY-RUN] Simulación de ingesta — SIN escritura en Neo4j")
    print(f"  Payload: {approved_payload_path}")
    print(f"  Total aprobados: {len(approved)}")
    print(f"  Entidades: {len(entities)}")
    print(f"  Relaciones: {len(relations)}")
    print()

    if entities:
        print("  -- ENTIDADES (primeras 10) --")
        for item in entities[:10]:
            cypher, params = _build_merge_entity_query(item)
            print(f"  [{item.get('entity_type','?')}] {item.get('name','?')} (conf={item.get('confidence',0):.2f})")
            print(f"    Cypher: {cypher}")
            print(f"    Params.name: {params['name']}")
        if len(entities) > 10:
            print(f"  ... y {len(entities)-10} más")

    if relations:
        print()
        print("  -- RELACIONES (primeras 10) --")
        for item in relations[:10]:
            cypher, params = _build_merge_relation_query(item)
            print(f"  {item.get('from_entity','?')} -[{item.get('relation_type','?')}]-> {item.get('to_entity','?')} (conf={item.get('confidence',0):.2f})")
            print(f"    Cypher: {cypher}")
        if len(relations) > 10:
            print(f"  ... y {len(relations)-10} más")

    print()
    print("[DRY-RUN] Neo4j NO fue modificado.")

    return {
        "dry_run": True,
        "would_write": len(approved),
        "entities": len(entities),
        "relations": len(relations),
    }


def _load_neo4j_creds(repo_root: Path) -> tuple[str, str, str]:
    env_path = repo_root / "viewer" / ".env"
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


def run(workspace: str, source_id: str, repo_root: Path, dry_run: bool = True) -> dict:
    """Entry point para el CLI."""
    payload_path = (
        repo_root / "output" / "reviews" / workspace / source_id / "approved_payload.json"
    )
    uri, user, password = _load_neo4j_creds(repo_root)
    return ingest(payload_path, dry_run=dry_run, neo4j_uri=uri, neo4j_user=user, neo4j_password=password)
