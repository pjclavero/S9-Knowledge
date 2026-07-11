"""Proveedor de grafo sobre Neo4j real. Solo lectura: ninguna consulta escribe.

Preparado para cuando el visor se conecte a la instancia de VM105
(bolt://192.168.1.205:7687). No se ha probado contra un Neo4j real todavía;
se activa poniendo ``S9K_GRAPH_PROVIDER=neo4j`` en ``.env``.
"""
from __future__ import annotations

from typing import Any

from neo4j import GraphDatabase

from app.providers.base import GraphProvider


def _node_to_dict(record_node) -> dict[str, Any]:
    props = dict(record_node)
    return {
        "id": record_node.element_id,
        "label": props.get("display_name") or props.get("canonical_name") or "",
        "type": props.get("entity_type", ""),
        "description": props.get("description", ""),
        "aliases": props.get("aliases", []),
        "workspace": props.get("workspace"),
        "source_document": props.get("source_document", ""),
        "source_pages": props.get("source_pages", []),
        "source_kind": props.get("source_kind", ""),
        "confidence": props.get("confidence"),
        "visibility": props.get("visibility"),
        "knowledge_layer": props.get("knowledge_layer"),
        "review_status": props.get("review_status"),
        "manual_review_required": props.get("manual_review_required"),
        "created_at": props.get("created_at"),
        "updated_at": props.get("updated_at"),
        "extractor_version": props.get("extractor_version"),
        "prompt_version": props.get("prompt_version"),
        "source_hash": props.get("source_hash"),
    }


def _rel_to_dict(rel) -> dict[str, Any]:
    props = dict(rel)
    return {
        "id": rel.element_id,
        "from": rel.start_node.element_id,
        "to": rel.end_node.element_id,
        "type": rel.type,
        "label": props.get("relation_label_es", ""),
        "description": props.get("evidence") or props.get("description", ""),
        "source_document": props.get("source_document", ""),
        "source_pages": props.get("source_pages", []),
        "confidence": props.get("confidence"),
        "review_status": props.get("review_status"),
    }


class Neo4jGraphProvider(GraphProvider):
    name = "neo4j"

    def __init__(self, uri: str, user: str, password: str):
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self._driver.close()

    def is_connected(self) -> bool:
        try:
            self._driver.verify_connectivity()
            return True
        except Exception:
            return False

    def workspaces(self) -> list[str]:
        query = """
        MATCH (n:Entity)
        WHERE n.workspace IS NOT NULL
        RETURN DISTINCT n.workspace AS workspace
        ORDER BY workspace
        """
        with self._driver.session() as session:
            return [r["workspace"] for r in session.run(query)]

    def counts(self, workspace: str | None = None) -> tuple[int, int]:
        if workspace:
            node_q = "MATCH (n:Entity {workspace:$workspace}) RETURN count(n) AS c"
            rel_q = (
                "MATCH (:Entity {workspace:$workspace})-[r]->(:Entity {workspace:$workspace}) "
                "RETURN count(r) AS c"
            )
            params = {"workspace": workspace}
        else:
            node_q = "MATCH (n:Entity) RETURN count(n) AS c"
            rel_q = "MATCH (:Entity)-[r]->(:Entity) RETURN count(r) AS c"
            params = {}
        with self._driver.session() as session:
            nodes = session.run(node_q, params).single()["c"]
            rels = session.run(rel_q, params).single()["c"]
        return nodes, rels

    def entity_types(self, workspace: str) -> list[dict[str, Any]]:
        query = """
        MATCH (n:Entity {workspace:$workspace})
        WHERE n.entity_type IS NOT NULL
        RETURN n.entity_type AS entity_type, count(n) AS count
        ORDER BY count DESC
        """
        with self._driver.session() as session:
            return [
                {"entity_type": r["entity_type"], "count": r["count"]}
                for r in session.run(query, {"workspace": workspace})
            ]

    def search(self, workspace: str, q: str, limit: int = 50) -> list[dict[str, Any]]:
        query = """
        MATCH (n:Entity {workspace:$workspace})
        WHERE toLower(coalesce(n.canonical_name,'')) CONTAINS toLower($q)
           OR toLower(coalesce(n.display_name,'')) CONTAINS toLower($q)
           OR toLower(coalesce(n.description,'')) CONTAINS toLower($q)
        RETURN n
        LIMIT $limit
        """
        with self._driver.session() as session:
            return [
                _node_to_dict(r["n"])
                for r in session.run(query, {"workspace": workspace, "q": q, "limit": limit})
            ]

    def graph(
        self,
        workspace: str,
        limit: int = 300,
        entity_type: str | None = None,
        q: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rel_query = """
        MATCH (n:Entity {workspace:$workspace})-[r]->(m:Entity {workspace:$workspace})
        WHERE ($entity_type IS NULL OR n.entity_type = $entity_type OR m.entity_type = $entity_type)
        RETURN n, r, m
        LIMIT $limit
        """
        node_query = """
        MATCH (n:Entity {workspace:$workspace})
        WHERE ($entity_type IS NULL OR n.entity_type = $entity_type)
        RETURN n
        LIMIT $limit
        """
        params = {"workspace": workspace, "entity_type": entity_type, "limit": limit}

        nodes_by_id: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []

        with self._driver.session() as session:
            for record in session.run(rel_query, params):
                n_dict = _node_to_dict(record["n"])
                m_dict = _node_to_dict(record["m"])
                nodes_by_id[n_dict["id"]] = n_dict
                nodes_by_id[m_dict["id"]] = m_dict
                edges.append(_rel_to_dict(record["r"]))

            if len(nodes_by_id) < limit:
                for record in session.run(node_query, params):
                    n_dict = _node_to_dict(record["n"])
                    nodes_by_id.setdefault(n_dict["id"], n_dict)
                    if len(nodes_by_id) >= limit:
                        break

        nodes = list(nodes_by_id.values())[:limit]
        node_ids = {n["id"] for n in nodes}
        edges = [e for e in edges if e["from"] in node_ids and e["to"] in node_ids]
        return nodes, edges

    def entity(self, entity_id: str) -> dict[str, Any] | None:
        query = "MATCH (n:Entity) WHERE elementId(n) = $id RETURN n"
        with self._driver.session() as session:
            record = session.run(query, {"id": entity_id}).single()
            return _node_to_dict(record["n"]) if record else None

    def relations_for_entity(
        self, entity_id: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        out_query = """
        MATCH (n:Entity)-[r]->(m:Entity) WHERE elementId(n) = $id RETURN r
        """
        in_query = """
        MATCH (n:Entity)<-[r]-(m:Entity) WHERE elementId(n) = $id RETURN r
        """
        with self._driver.session() as session:
            outgoing = [_rel_to_dict(rec["r"]) for rec in session.run(out_query, {"id": entity_id})]
            incoming = [_rel_to_dict(rec["r"]) for rec in session.run(in_query, {"id": entity_id})]
        return outgoing, incoming
