"""Auditor de calidad del grafo Neo4j (SOLO LECTURA).

Detecta:
  duplicate_candidate   — nodos con nombres muy similares (ej: "Tamori Family" / "Familia Tamori")
  bad_relation          — relaciones no en ALLOWED_RELATION_TYPES
  missing_source_id     — nodos sin source_id
  missing_source_kind   — nodos sin source_kind
  schema_violation      — nodos con tipo no en ALLOWED_NODE_TYPES
  low_confidence        — nodos con confidence < 0.5
  missing_evidence      — nodos sin evidence (campo vacío o ausente)
  missing_producer      — nodos sin producer o sin review_status
  old_schema_version    — nodos con schema_version presente pero antigua (< "1.0")
  missing_workspace     — nodos con workspace ausente o vacío
  local_vs_external     — pares de nodos con mismo canonical_name pero origin distinto

AUDITAR sí, CORREGIR no.
"""
from __future__ import annotations
import json
import logging
import sys
import unicodedata
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from schemas.rpg_schema import ALLOWED_NODE_TYPES, ALLOWED_RELATION_TYPES

log = logging.getLogger(__name__)

LOW_CONF_THRESHOLD = 0.5
CURRENT_SCHEMA_VERSION = "1.0"


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _get_driver(neo4j_uri: str, user: str, password: str):
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(neo4j_uri, auth=(user, password))
        with driver.session() as s:
            s.run("RETURN 1")
        return driver
    except Exception as e:
        log.warning("Neo4j no disponible para auditoría: %s", e)
        return None


def _find_duplicate_candidates(session) -> list[dict]:
    """Detecta nodos con nombres canónicos similares (normalizado)."""
    records = session.run(
        "MATCH (n) WHERE n.canonical_name IS NOT NULL "
        "RETURN n.canonical_name AS name, labels(n) AS labels "
        "LIMIT 5000"
    ).data()

    groups: dict[str, list[dict]] = {}
    for r in records:
        name = r.get("name", "")
        norm = _normalize(name)
        if norm not in groups:
            groups[norm] = []
        groups[norm].append({"canonical": name, "labels": r.get("labels", [])})

    duplicates = []
    for norm, nodes in groups.items():
        if len(nodes) > 1:
            duplicates.append({
                "normalized_key": norm,
                "candidates": nodes,
                "count": len(nodes),
            })

    return duplicates


def _find_bad_relations(session) -> list[dict]:
    """Detecta relaciones con tipo no en ALLOWED_RELATION_TYPES."""
    try:
        records = session.run(
            "MATCH ()-[r]->() "
            "WHERE NOT type(r) IN $allowed "
            "RETURN type(r) AS rel_type, count(r) AS count "
            "LIMIT 200",
            {"allowed": list(ALLOWED_RELATION_TYPES)},
        ).data()
    except Exception as e:
        log.warning("Error en query bad_relations: %s", e)
        records = []

    return [{"relation_type": r["rel_type"], "count": r["count"]} for r in records]


def _find_missing_metadata(session) -> dict:
    """Detecta nodos sin source_id, source_kind o con tipo inválido."""
    missing_source_id = []
    missing_source_kind = []
    schema_violations = []
    low_confidence = []

    try:
        recs = session.run(
            "MATCH (n) WHERE n.source_id IS NULL AND n.canonical_name IS NOT NULL "
            "RETURN n.canonical_name AS name, labels(n) AS labels LIMIT 100"
        ).data()
        missing_source_id = [{"name": r["name"], "labels": r["labels"]} for r in recs]
    except Exception as e:
        log.warning("Error en query missing_source_id: %s", e)

    try:
        recs = session.run(
            "MATCH (n) WHERE n.source_kind IS NULL AND n.canonical_name IS NOT NULL "
            "RETURN n.canonical_name AS name, labels(n) AS labels LIMIT 100"
        ).data()
        missing_source_kind = [{"name": r["name"], "labels": r["labels"]} for r in recs]
    except Exception as e:
        log.warning("Error en query missing_source_kind: %s", e)

    try:
        recs = session.run(
            "MATCH (n) WHERE n.canonical_name IS NOT NULL "
            "RETURN n.canonical_name AS name, labels(n) AS labels LIMIT 2000"
        ).data()
        for r in recs:
            labels = r.get("labels", [])
            user_labels = [l for l in labels if not l.startswith("_")]
            if not any(l in ALLOWED_NODE_TYPES for l in user_labels):
                schema_violations.append({"name": r["name"], "labels": labels})
    except Exception as e:
        log.warning("Error en query schema_violations: %s", e)

    try:
        recs = session.run(
            "MATCH (n) WHERE n.confidence IS NOT NULL AND n.confidence < $thresh "
            "RETURN n.canonical_name AS name, n.confidence AS conf, labels(n) AS labels LIMIT 200",
            {"thresh": LOW_CONF_THRESHOLD},
        ).data()
        low_confidence = [
            {"name": r["name"], "confidence": r["conf"], "labels": r["labels"]} for r in recs
        ]
    except Exception as e:
        log.warning("Error en query low_confidence: %s", e)

    return {
        "missing_source_id": missing_source_id,
        "missing_source_kind": missing_source_kind,
        "schema_violations": schema_violations,
        "low_confidence": low_confidence,
    }


# ── Nuevas detecciones (TAREA 4) ─────────────────────────────────────────────

def _find_missing_evidence(session) -> list[dict]:
    """Detecta nodos sin evidence (campo ausente o vacío)."""
    results = []
    try:
        recs = session.run(
            "MATCH (n) WHERE n.canonical_name IS NOT NULL "
            "AND (n.evidence IS NULL OR n.evidence = '') "
            "RETURN n.canonical_name AS name, labels(n) AS labels LIMIT 200"
        ).data()
        results = [{"name": r["name"], "labels": r["labels"]} for r in recs]
    except Exception as e:
        log.warning("Error en query missing_evidence: %s", e)
    return results


def _find_missing_producer(session) -> dict:
    """Detecta nodos sin producer o sin review_status."""
    missing_producer = []
    missing_review_status = []
    try:
        recs = session.run(
            "MATCH (n) WHERE n.canonical_name IS NOT NULL "
            "AND (n.producer IS NULL OR n.producer = '') "
            "RETURN n.canonical_name AS name, labels(n) AS labels LIMIT 200"
        ).data()
        missing_producer = [{"name": r["name"], "labels": r["labels"]} for r in recs]
    except Exception as e:
        log.warning("Error en query missing_producer: %s", e)

    try:
        recs = session.run(
            "MATCH (n) WHERE n.canonical_name IS NOT NULL "
            "AND (n.review_status IS NULL OR n.review_status = '') "
            "RETURN n.canonical_name AS name, labels(n) AS labels LIMIT 200"
        ).data()
        missing_review_status = [{"name": r["name"], "labels": r["labels"]} for r in recs]
    except Exception as e:
        log.warning("Error en query missing_review_status: %s", e)

    return {
        "missing_producer": missing_producer,
        "missing_review_status": missing_review_status,
    }


def _find_old_schema_version(session) -> list[dict]:
    """Detecta nodos con schema_version presente pero antigua (< CURRENT_SCHEMA_VERSION)."""
    results = []
    try:
        recs = session.run(
            "MATCH (n) WHERE n.schema_version IS NOT NULL "
            "AND n.schema_version < $current "
            "RETURN n.canonical_name AS name, n.schema_version AS sv, labels(n) AS labels LIMIT 200",
            {"current": CURRENT_SCHEMA_VERSION},
        ).data()
        results = [
            {"name": r["name"], "schema_version": r["sv"], "labels": r["labels"]}
            for r in recs
        ]
    except Exception as e:
        log.warning("Error en query old_schema_version: %s", e)
    return results


def _find_missing_workspace(session) -> list[dict]:
    """Detecta nodos con workspace ausente o vacío."""
    results = []
    try:
        recs = session.run(
            "MATCH (n) WHERE n.canonical_name IS NOT NULL "
            "AND (n.workspace IS NULL OR n.workspace = '') "
            "RETURN n.canonical_name AS name, labels(n) AS labels LIMIT 200"
        ).data()
        results = [{"name": r["name"], "labels": r["labels"]} for r in recs]
    except Exception as e:
        log.warning("Error en query missing_workspace: %s", e)
    return results


def _find_local_vs_external_conflicts(session) -> list[dict]:
    """Detecta pares de nodos con el mismo canonical_name pero origin distinto (local vs external)."""
    results = []
    try:
        recs = session.run(
            "MATCH (a) WHERE a.canonical_name IS NOT NULL AND a.origin IS NOT NULL "
            "WITH a.canonical_name AS name, collect({origin: a.origin, labels: labels(a)}) AS nodes "
            "WHERE size(nodes) > 1 "
            "RETURN name, nodes LIMIT 200"
        ).data()
        for r in recs:
            origins = list({n["origin"] for n in r["nodes"]})
            if len(origins) > 1:
                results.append({
                    "canonical_name": r["name"],
                    "origins": origins,
                    "nodes": r["nodes"],
                })
    except Exception as e:
        log.warning("Error en query local_vs_external: %s", e)
    return results


def audit(
    workspace: str,
    repo_root: Path,
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
) -> Path:
    """Ejecuta la auditoría y escribe los JSON y el review.md. SOLO LECTURA."""
    out_dir = repo_root / "output" / "reviews" / workspace / "graph_quality"
    out_dir.mkdir(parents=True, exist_ok=True)

    driver = _get_driver(neo4j_uri, neo4j_user, neo4j_password)
    if not driver:
        log.warning("Auditoría: Neo4j no disponible. Se genera informe vacío.")
        _write_quality_md(
            out_dir, workspace,
            duplicates=[], bad_rels={}, missing={},
            extra={},
            neo4j_available=False
        )
        return out_dir / "graph_quality_review.md"

    with driver.session() as session:
        duplicates = _find_duplicate_candidates(session)
        bad_rels = _find_bad_relations(session)
        missing = _find_missing_metadata(session)
        # Nuevas detecciones
        missing_evidence = _find_missing_evidence(session)
        missing_producer = _find_missing_producer(session)
        old_schema = _find_old_schema_version(session)
        missing_workspace = _find_missing_workspace(session)
        local_vs_external = _find_local_vs_external_conflicts(session)

    driver.close()

    extra = {
        "missing_evidence": missing_evidence,
        "missing_producer": missing_producer.get("missing_producer", []),
        "missing_review_status": missing_producer.get("missing_review_status", []),
        "old_schema_version": old_schema,
        "missing_workspace": missing_workspace,
        "local_vs_external_conflicts": local_vs_external,
    }

    # Escribir JSONs
    (out_dir / "duplicate_candidates.json").write_text(
        json.dumps(duplicates, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "bad_relations.json").write_text(
        json.dumps(bad_rels, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "missing_metadata.json").write_text(
        json.dumps(missing, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "audit_extra.json").write_text(
        json.dumps(extra, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _write_quality_md(out_dir, workspace, duplicates, bad_rels, missing, extra, neo4j_available=True)

    log.info(
        "audit-graph: duplicados=%d, bad_relations=%d, missing_source_id=%d, "
        "schema_violations=%d, low_conf=%d, missing_evidence=%d, "
        "missing_workspace=%d, local_vs_ext=%d",
        len(duplicates),
        len(bad_rels),
        len(missing.get("missing_source_id", [])),
        len(missing.get("schema_violations", [])),
        len(missing.get("low_confidence", [])),
        len(extra["missing_evidence"]),
        len(extra["missing_workspace"]),
        len(extra["local_vs_external_conflicts"]),
    )
    return out_dir / "graph_quality_review.md"


def _write_quality_md(
    out_dir: Path,
    workspace: str,
    duplicates: list[dict],
    bad_rels,
    missing: dict,
    extra: dict,
    neo4j_available: bool,
):
    # Normaliza bad_rels si es dict o list
    if isinstance(bad_rels, dict):
        bad_rels_list = list(bad_rels.values()) if bad_rels else []
    else:
        bad_rels_list = bad_rels or []

    lines = [
        f"# Auditoría de calidad del grafo — {workspace}",
        "",
    ]

    if not neo4j_available:
        lines += ["> Neo4j no disponible. Ejecuta cuando el servicio esté activo.", ""]
    else:
        miss_ev = extra.get("missing_evidence", [])
        miss_prod = extra.get("missing_producer", [])
        miss_rs = extra.get("missing_review_status", [])
        old_sv = extra.get("old_schema_version", [])
        miss_ws = extra.get("missing_workspace", [])
        lve = extra.get("local_vs_external_conflicts", [])

        lines += [
            "## Resumen",
            "",
            f"| Issue | Cantidad |",
            f"|-------|----------|",
            f"| Candidatos duplicados | {len(duplicates)} |",
            f"| Relaciones inválidas | {len(bad_rels_list)} |",
            f"| Sin source_id | {len(missing.get('missing_source_id', []))} |",
            f"| Sin source_kind | {len(missing.get('missing_source_kind', []))} |",
            f"| Violaciones de schema | {len(missing.get('schema_violations', []))} |",
            f"| Baja confianza (< {LOW_CONF_THRESHOLD}) | {len(missing.get('low_confidence', []))} |",
            f"| Sin evidence | {len(miss_ev)} |",
            f"| Sin producer | {len(miss_prod)} |",
            f"| Sin review_status | {len(miss_rs)} |",
            f"| schema_version antigua | {len(old_sv)} |",
            f"| Sin workspace | {len(miss_ws)} |",
            f"| Conflictos local vs external | {len(lve)} |",
            "",
        ]

        if duplicates:
            lines += ["## Candidatos duplicados", ""]
            for d in duplicates[:20]:
                names = [c["canonical"] for c in d["candidates"]]
                lines.append(f"- **{d['normalized_key']}**: {names}")
            lines.append("")

        if bad_rels_list:
            lines += ["## Relaciones inválidas", ""]
            for r in bad_rels_list:
                lines.append(f"- `{r.get('relation_type', r)}` ({r.get('count', '?')} instancias)")
            lines.append("")

        ms = missing.get("missing_source_id", [])
        if ms:
            lines += [f"## Nodos sin source_id ({len(ms)})", ""]
            for n in ms[:20]:
                lines.append(f"- {n['name']} {n['labels']}")
            lines.append("")

        sv_viol = missing.get("schema_violations", [])
        if sv_viol:
            lines += [f"## Violaciones de schema ({len(sv_viol)})", ""]
            for n in sv_viol[:20]:
                lines.append(f"- {n['name']} — labels: {n['labels']}")
            lines.append("")

        lc = missing.get("low_confidence", [])
        if lc:
            lines += [f"## Baja confianza ({len(lc)})", ""]
            for n in lc[:20]:
                lines.append(f"- {n['name']} — conf={n['confidence']:.2f}")
            lines.append("")

        # Nuevas secciones
        if miss_ev:
            lines += [f"## Sin evidence ({len(miss_ev)}) [NUEVO]", ""]
            for n in miss_ev[:20]:
                lines.append(f"- {n['name']} {n['labels']}")
            lines.append("")

        if miss_prod:
            lines += [f"## Sin producer ({len(miss_prod)}) [NUEVO]", ""]
            for n in miss_prod[:20]:
                lines.append(f"- {n['name']} {n['labels']}")
            lines.append("")

        if miss_rs:
            lines += [f"## Sin review_status ({len(miss_rs)}) [NUEVO]", ""]
            for n in miss_rs[:20]:
                lines.append(f"- {n['name']} {n['labels']}")
            lines.append("")

        if old_sv:
            lines += [f"## schema_version antigua ({len(old_sv)}) [NUEVO]", ""]
            for n in old_sv[:20]:
                lines.append(f"- {n['name']} — sv={n['schema_version']} {n['labels']}")
            lines.append("")

        if miss_ws:
            lines += [f"## Sin workspace ({len(miss_ws)}) [NUEVO]", ""]
            for n in miss_ws[:20]:
                lines.append(f"- {n['name']} {n['labels']}")
            lines.append("")

        if lve:
            lines += [f"## Conflictos local vs external ({len(lve)}) [NUEVO]", ""]
            for c in lve[:20]:
                lines.append(f"- `{c['canonical_name']}` — origins: {c['origins']}")
            lines.append("")

        lines += [
            "> AUDITAR sí, CORREGIR no. Este informe es de solo lectura.",
            "",
        ]

    (out_dir / "graph_quality_review.md").write_text("\n".join(lines), encoding="utf-8")


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


def run(workspace: str, repo_root: Path) -> Path:
    """Entry point para el CLI."""
    uri, user, password = _load_neo4j_creds(repo_root)
    return audit(workspace, repo_root, uri, user, password)
