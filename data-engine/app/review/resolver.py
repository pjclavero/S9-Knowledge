"""Resolver de entidades contra Neo4j (SOLO LECTURA).

Por cada candidato de tipo 'entity' busca:
1. Match exacto de nombre canónico
2. Match exacto de alias
3. Match normalizado (sin tildes, lowercase)
4. Similitud básica EN/ES

Acciones resultantes:
  use_existing  — match exacto fuerte y tipo compatible
  create_new    — sin match y confidence alta
  needs_review  — varios matches, tipo contradictorio, o ambigüedad
  reject        — tipo incompatible claro

Degrada con gracia si Neo4j no responde: marca needs_review, no crashea.
"""
from __future__ import annotations
import json
import logging
import re
import sys
import unicodedata
from pathlib import Path
from typing import Optional

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review.models import Candidate, ValidationResult, ResolutionResult

log = logging.getLogger(__name__)

# ── Utilidades de normalización ───────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Minúsculas sin tildes."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _get_neo4j_driver(neo4j_uri: str, user: str, password: str):
    """Importa y crea driver Neo4j. Retorna None si no disponible."""
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(neo4j_uri, auth=(user, password))
        # Test de conexión
        with driver.session() as session:
            session.run("RETURN 1")
        return driver
    except Exception as e:
        log.warning("Neo4j no disponible: %s", e)
        return None


def _search_neo4j(driver, name: str, entity_type: Optional[str]) -> list[dict]:
    """Busca en Neo4j por nombre canónico, alias y normalizado. Solo lectura."""
    if driver is None:
        return []

    name_norm = _normalize(name)
    results: list[dict] = []

    queries = [
        # Exact canonical
        ("exact", "MATCH (n) WHERE n.canonical_name = $name RETURN n.canonical_name AS canonical, labels(n) AS labels, 1.0 AS score LIMIT 5"),
        # Alias
        ("alias", "MATCH (n) WHERE $name IN coalesce(n.aliases, []) RETURN n.canonical_name AS canonical, labels(n) AS labels, 0.95 AS score LIMIT 5"),
        # Normalized name property
        ("normalized", "MATCH (n) WHERE toLower(n.canonical_name) = $name_norm RETURN n.canonical_name AS canonical, labels(n) AS labels, 0.85 AS score LIMIT 5"),
    ]

    try:
        with driver.session() as session:
            for match_type, cypher in queries:
                params = {"name": name, "name_norm": name_norm}
                records = session.run(cypher, params).data()
                for r in records:
                    results.append({
                        "canonical": r.get("canonical", ""),
                        "labels": r.get("labels", []),
                        "score": r.get("score", 0.5),
                        "match_type": match_type,
                    })
    except Exception as e:
        log.warning("Error en consulta Neo4j para '%s': %s", name, e)

    # Deduplicar por canonical
    seen: set[str] = set()
    unique: list[dict] = []
    for r in results:
        if r["canonical"] not in seen:
            seen.add(r["canonical"])
            unique.append(r)

    return unique


def _resolve_one(
    c: Candidate,
    vr: ValidationResult,
    driver,
) -> ResolutionResult:
    """Resuelve un único candidato."""
    # Solo resolvemos entidades con validación no inválida
    if vr.valid == "invalid":
        return ResolutionResult(
            candidate_id=c.candidate_id,
            action="reject",
            reason=f"validación inválida: {'; '.join(vr.issues)}",
            neo4j_available=(driver is not None),
        )

    if c.kind != "entity" or not c.name:
        # Relaciones y otros: sin match Neo4j, usar create_new si conf>=0.70
        action = "create_new" if c.confidence >= 0.70 else "needs_review"
        return ResolutionResult(
            candidate_id=c.candidate_id,
            action=action,
            reason=f"kind={c.kind}, no se busca en Neo4j",
            neo4j_available=(driver is not None),
        )

    if driver is None:
        # Neo4j no disponible: marcar needs_review
        return ResolutionResult(
            candidate_id=c.candidate_id,
            action="needs_review",
            reason="Neo4j no disponible; requiere revisión manual",
            neo4j_available=False,
        )

    matches = _search_neo4j(driver, c.name, c.entity_type)

    if not matches:
        # Sin match: create_new si confidence >= 0.75
        action = "create_new" if c.confidence >= 0.75 else "needs_review"
        return ResolutionResult(
            candidate_id=c.candidate_id,
            action=action,
            reason="sin match en Neo4j",
            match_type="none",
            neo4j_available=True,
        )

    # Un solo match exacto fuerte
    best = max(matches, key=lambda x: x["score"])
    if len(matches) == 1 and best["score"] >= 0.90:
        # Verificar tipo compatible
        expected_label = c.entity_type or ""
        neo4j_labels = best.get("labels", [])
        type_ok = not expected_label or expected_label in neo4j_labels or \
                  any(expected_label.lower() in lbl.lower() for lbl in neo4j_labels)
        if type_ok:
            return ResolutionResult(
                candidate_id=c.candidate_id,
                action="use_existing",
                matched_canonical=best["canonical"],
                match_score=best["score"],
                match_type=best["match_type"],
                reason="match exacto único y tipo compatible",
                neo4j_available=True,
            )
        else:
            return ResolutionResult(
                candidate_id=c.candidate_id,
                action="needs_review",
                matched_canonical=best["canonical"],
                match_score=best["score"],
                match_type=best["match_type"],
                reason=f"match existente pero tipo contradictorio: {neo4j_labels} vs {expected_label}",
                neo4j_available=True,
            )

    # Varios matches: needs_review
    alternatives = [m["canonical"] for m in matches]
    return ResolutionResult(
        candidate_id=c.candidate_id,
        action="needs_review",
        matched_canonical=best["canonical"],
        match_score=best["score"],
        match_type=best["match_type"],
        alternatives=alternatives,
        reason=f"múltiples matches ({len(matches)}): {alternatives[:3]}",
        neo4j_available=True,
    )


def resolve_candidates(
    validated: list[tuple[Candidate, ValidationResult]],
    neo4j_uri: str = "bolt://127.0.0.1:7687",
    neo4j_user: str = "neo4j",
    neo4j_password: str = "",
) -> list[tuple[Candidate, ValidationResult, ResolutionResult]]:
    driver = _get_neo4j_driver(neo4j_uri, neo4j_user, neo4j_password)
    if driver:
        log.info("Resolver: conectado a Neo4j %s", neo4j_uri)
    else:
        log.warning("Resolver: Neo4j no disponible, todos los candidatos → needs_review")

    results = []
    for c, vr in validated:
        rr = _resolve_one(c, vr, driver)
        results.append((c, vr, rr))

    if driver:
        driver.close()

    n_use = sum(1 for _, _, rr in results if rr.action == "use_existing")
    n_create = sum(1 for _, _, rr in results if rr.action == "create_new")
    n_review = sum(1 for _, _, rr in results if rr.action == "needs_review")
    n_reject = sum(1 for _, _, rr in results if rr.action == "reject")
    log.info(
        "Resolución: use_existing=%d, create_new=%d, needs_review=%d, reject=%d",
        n_use, n_create, n_review, n_reject,
    )
    return results


def _load_neo4j_creds(repo_root: Path) -> tuple[str, str, str]:
    """Carga credenciales de viewer/.env."""
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


def run(workspace: str, source_id: str, repo_root: Path) -> Path:
    """Entry point: resuelve y guarda resolved.json."""
    in_path = repo_root / "output" / "reviews" / workspace / source_id / "validated.json"
    if not in_path.exists():
        raise FileNotFoundError(f"validated.json no encontrado: {in_path}")

    with in_path.open(encoding="utf-8") as f:
        raw = json.load(f)

    validated = []
    for rec in raw:
        from review.models import Candidate, ValidationResult
        c = Candidate.from_dict(rec["candidate"])
        vr = ValidationResult.from_dict(rec["validation"])
        validated.append((c, vr))

    uri, user, password = _load_neo4j_creds(repo_root)
    results = resolve_candidates(validated, uri, user, password)

    out_records = []
    for c, vr, rr in results:
        out_records.append({
            "candidate": c.to_dict(),
            "validation": vr.to_dict(),
            "resolution": rr.to_dict(),
        })

    out_path = in_path.parent / "resolved.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out_records, f, ensure_ascii=False, indent=2)

    log.info("resolved.json → %s", out_path)
    return out_path
