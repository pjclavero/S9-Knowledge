"""Auditoría de posibles nodos duplicados en el grafo de conocimiento Neo4j.

*** SCRIPT DE SOLO LECTURA ***
Este script es de solo lectura. Nunca ejecuta CREATE, SET, DELETE ni MERGE.
Todas las consultas Cypher usadas aquí son `MATCH ... RETURN`. No modifica
Neo4j de ninguna forma, no fusiona nodos y no borra nada. Solo detecta
candidatos a duplicado y escribe un informe Markdown para revisión humana.

Uso:
    python data-engine/app/tools/audit_duplicates.py --workspace leyenda

Configuración (variables de entorno, mismo esquema que el resto del proyecto):
    S9K_NEO4J_URI              default: bolt://127.0.0.1:7687
    S9K_NEO4J_USER             default: neo4j
    S9K_NEO4J_PASSWORD         contraseña en texto plano (opcional)
    S9K_NEO4J_PASSWORD_FILE    ruta a archivo con la contraseña (prioridad sobre
                                S9K_NEO4J_PASSWORD)

Requiere un túnel SSH activo hacia VM105 (o acceso directo a Neo4j) para poder
conectar. Si la conexión falla, el script lo reporta de forma clara por
stdout/stderr y NO genera ningún informe con datos falsos o inventados.

Salida: viewer/reports/duplicate_candidates.md
"""
from __future__ import annotations

import argparse
import difflib
import os
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from neo4j import GraphDatabase
    from neo4j.exceptions import Neo4jError, ServiceUnavailable
except ImportError:  # pragma: no cover - mensaje explicativo si falta la librería
    print(
        "ERROR: falta la librería 'neo4j'. Instálala con: pip install neo4j",
        file=sys.stderr,
    )
    sys.exit(1)


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = REPO_ROOT / "viewer" / "reports" / "duplicate_candidates.md"

# Similitud mínima (difflib) para considerar dos nombres normalizados como
# candidatos a duplicado cuando no coinciden exactamente token a token.
SIMILARITY_THRESHOLD = 0.75

# Pares de palabras equivalentes ES/EN de uso común en nombres de facciones,
# clanes y familias. No es un diccionario exhaustivo, solo cubre los casos
# más comunes observados en el grafo (ver docs/11-data-quality-review.md).
_EQUIVALENT_TOKENS: dict[str, str] = {
    "family": "familia",
    "clan": "clan",
    "faction": "faccion",
    "school": "escuela",
    "house": "casa",
    "temple": "templo",
    "order": "orden",
    "guild": "gremio",
    "brotherhood": "hermandad",
}


def _strip_accents(s: str) -> str:
    """Elimina tildes y diacríticos para comparación robusta.

    Reimplementación local e independiente de la función homónima privada en
    ``data-engine/app/schemas/rpg_schema.py`` (no se importa por ser privada
    y porque este script debe ser independiente del schema).
    """
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _normalize_key(s: str) -> str:
    """Normaliza un nombre a minúsculas, sin tildes, sin puntuación."""
    s = (s or "").lower().strip()
    s = _strip_accents(s)
    for ch in ".,;:!?'\"()[]{}_-":
        s = s.replace(ch, " ")
    return " ".join(s.split())


def _normalize_token(tok: str) -> str:
    """Normaliza un token individual, mapeando pares EN/ES equivalentes."""
    return _EQUIVALENT_TOKENS.get(tok, tok)


def _token_set(name: str) -> frozenset[str]:
    """Devuelve el conjunto de tokens normalizados (con equivalencia EN/ES)."""
    normalized = _normalize_key(name)
    return frozenset(_normalize_token(tok) for tok in normalized.split())


def _similarity(a: str, b: str) -> float:
    """Similitud simple entre dos nombres ya normalizados (difflib)."""
    return difflib.SequenceMatcher(None, a, b).ratio()


@dataclass
class NodeInfo:
    element_id: str
    canonical_name: str
    display_name: str
    entity_type: str
    source_document: str
    source_pages: list[int] = field(default_factory=list)
    confidence: float | None = None


def _resolve_password() -> str:
    password_file = os.environ.get("S9K_NEO4J_PASSWORD_FILE", "")
    if password_file:
        path = Path(password_file)
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return os.environ.get("S9K_NEO4J_PASSWORD", "")


def _connect():
    uri = os.environ.get("S9K_NEO4J_URI", "bolt://127.0.0.1:7687")
    user = os.environ.get("S9K_NEO4J_USER", "neo4j")
    password = _resolve_password()

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
    except Exception as exc:  # noqa: BLE001 - queremos capturar cualquier fallo de conexión
        driver.close()
        raise ConnectionError(
            f"No se pudo conectar a Neo4j en {uri}: {exc}. "
            "Este script requiere el túnel SSH activo hacia VM105 "
            "(o acceso directo a la instancia de Neo4j)."
        ) from exc
    return driver, uri


def _fetch_nodes(driver, workspace: str) -> list[NodeInfo]:
    """MATCH de solo lectura: trae todos los nodos Entity del workspace."""
    query = """
    MATCH (n:Entity {workspace: $workspace})
    RETURN elementId(n) AS id,
           coalesce(n.canonical_name, '') AS canonical_name,
           coalesce(n.display_name, '') AS display_name,
           coalesce(n.entity_type, '') AS entity_type,
           coalesce(n.source_document, '') AS source_document,
           coalesce(n.source_pages, []) AS source_pages,
           n.confidence AS confidence
    """
    nodes: list[NodeInfo] = []
    with driver.session() as session:
        result = session.run(query, workspace=workspace)
        for record in result:
            nodes.append(
                NodeInfo(
                    element_id=record["id"],
                    canonical_name=record["canonical_name"],
                    display_name=record["display_name"],
                    entity_type=record["entity_type"],
                    source_document=record["source_document"],
                    source_pages=list(record["source_pages"] or []),
                    confidence=record["confidence"],
                )
            )
    return nodes


def _fetch_relations(driver, workspace: str, element_ids: list[str]) -> list[dict[str, Any]]:
    """MATCH de solo lectura: relaciones que involucran a los nodos candidatos."""
    if not element_ids:
        return []
    query = """
    MATCH (a:Entity {workspace: $workspace})-[r]->(b:Entity {workspace: $workspace})
    WHERE elementId(a) IN $ids OR elementId(b) IN $ids
    RETURN coalesce(a.display_name, a.canonical_name) AS a_name,
           type(r) AS rel_type,
           coalesce(b.display_name, b.canonical_name) AS b_name
    """
    rels: list[dict[str, Any]] = []
    with driver.session() as session:
        result = session.run(query, workspace=workspace, ids=element_ids)
        for record in result:
            rels.append(
                {
                    "a_name": record["a_name"],
                    "rel_type": record["rel_type"],
                    "b_name": record["b_name"],
                }
            )
    return rels


def _pages_overlap(a: list[int], b: list[int]) -> bool:
    return bool(set(a) & set(b))


def _find_duplicate_groups(nodes: list[NodeInfo]) -> list[list[NodeInfo]]:
    """Agrupa nodos candidatos a duplicado por nombre normalizado / tokens / similitud."""
    n = len(nodes)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    norm_names = [_normalize_key(node.canonical_name or node.display_name) for node in nodes]
    token_sets = [_token_set(node.canonical_name or node.display_name) for node in nodes]

    for i in range(n):
        for j in range(i + 1, n):
            if not norm_names[i] or not norm_names[j]:
                continue
            same_tokens = token_sets[i] and token_sets[i] == token_sets[j]
            near_tokens = (
                token_sets[i]
                and token_sets[j]
                and len(token_sets[i] & token_sets[j]) >= max(1, min(len(token_sets[i]), len(token_sets[j])) - 1)
                and token_sets[i] != frozenset()
            )
            similar = _similarity(norm_names[i], norm_names[j]) >= SIMILARITY_THRESHOLD
            if norm_names[i] == norm_names[j] or same_tokens or (near_tokens and similar) or similar:
                union(i, j)

    groups: dict[int, list[NodeInfo]] = defaultdict(list)
    for idx, node in enumerate(nodes):
        groups[find(idx)].append(node)

    return [g for g in groups.values() if len(g) > 1]


def _score_group(group: list[NodeInfo]) -> int:
    """Prioriza grupos donde además coincide source_document y hay solape de páginas."""
    score = 0
    for i in range(len(group)):
        for j in range(i + 1, len(group)):
            a, b = group[i], group[j]
            if a.source_document and a.source_document == b.source_document:
                score += 1
                if _pages_overlap(a.source_pages, b.source_pages):
                    score += 2
    return score


def _render_report(groups_with_rels: list[tuple[list[NodeInfo], list[dict[str, Any]]]], workspace: str) -> str:
    lines: list[str] = ["# Candidatos a duplicado", ""]
    lines.append(f"Workspace: `{workspace}`")
    lines.append("")
    lines.append(
        "Generado por `data-engine/app/tools/audit_duplicates.py` (solo lectura). "
        "Ningún dato ha sido fusionado ni modificado en Neo4j."
    )
    lines.append("")

    if not groups_with_rels:
        lines.append("No se detectaron candidatos a duplicado en este workspace.")
        lines.append("")
        return "\n".join(lines)

    for group, rels in groups_with_rels:
        title = " / ".join(node.canonical_name or node.display_name for node in group)
        lines.append(f"## {title}")
        lines.append("")
        for idx, node in enumerate(group):
            label = chr(ord("A") + idx)
            name = node.display_name or node.canonical_name
            lines.append(f"- Nodo {label}: {name}")
            lines.append(f"  - type: {node.entity_type}")
            lines.append(f"  - source: {node.source_document}")
            lines.append(f"  - pages: {node.source_pages}")
        lines.append("")
        lines.append("Relaciones afectadas:")
        if rels:
            for rel in rels:
                lines.append(f"- {rel['a_name']} {rel['rel_type']} {rel['b_name']}")
        else:
            lines.append("- (ninguna relación encontrada para estos nodos)")
        lines.append("")
        lines.append("Recomendación:")
        lines.append("- revisar manualmente antes de fusionar.")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Auditoría de solo lectura de posibles nodos duplicados en el grafo "
            "S9 Knowledge. Nunca escribe en Neo4j."
        )
    )
    parser.add_argument(
        "--workspace",
        default="leyenda",
        help="Workspace a auditar (default: leyenda)",
    )
    args = parser.parse_args()

    try:
        driver, uri = _connect()
    except ConnectionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        print(f"Conectado a Neo4j en {uri}. Auditando workspace '{args.workspace}'...")
        nodes = _fetch_nodes(driver, args.workspace)
        print(f"Nodos encontrados: {len(nodes)}")

        groups = _find_duplicate_groups(nodes)
        groups.sort(key=_score_group, reverse=True)
        print(f"Grupos candidatos a duplicado: {len(groups)}")

        groups_with_rels: list[tuple[list[NodeInfo], list[dict[str, Any]]]] = []
        for group in groups:
            ids = [node.element_id for node in group]
            rels = _fetch_relations(driver, args.workspace, ids)
            groups_with_rels.append((group, rels))

        report = _render_report(groups_with_rels, args.workspace)

        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report, encoding="utf-8")
        print(f"Informe escrito en: {REPORT_PATH}")
        return 0
    except (Neo4jError, ServiceUnavailable) as exc:
        print(f"ERROR: fallo al consultar Neo4j: {exc}", file=sys.stderr)
        return 1
    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
