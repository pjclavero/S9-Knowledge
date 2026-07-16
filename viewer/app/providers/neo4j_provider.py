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

    # -----------------------------------------------------------------------
    # Métodos de paginación real y calidad (Tarea C — solo lectura)
    # -----------------------------------------------------------------------

    _SORT_ALLOWLIST: dict[str, str] = {
        "canonical_name": "n.canonical_name",
        "entity_type": "n.entity_type",
        "confidence": "n.confidence",
        "review_status": "n.review_status",
        "created_at": "n.created_at",
    }

    def list_entities(
        self,
        workspace: str,
        *,
        q: str = "",
        entity_type: str | None = None,
        source_kind: str | None = None,
        review_status: str | None = None,
        visibility: str | None = None,
        quality_status: str | None = None,
        min_confidence: float | None = None,
        sort: str = "canonical_name",
        order: str = "asc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Paginación real con SKIP/LIMIT en Neo4j. 0 escrituras."""
        sort_field = self._SORT_ALLOWLIST.get(sort, "n.canonical_name")
        order_dir = "DESC" if order == "desc" else "ASC"

        where_parts = ["n.workspace = $workspace"]
        params: dict[str, Any] = {"workspace": workspace, "limit": limit, "offset": offset}

        if q:
            where_parts.append(
                "(toLower(coalesce(n.canonical_name,'')) CONTAINS toLower($q)"
                " OR toLower(coalesce(n.display_name,'')) CONTAINS toLower($q)"
                " OR toLower(coalesce(n.description,'')) CONTAINS toLower($q))"
            )
            params["q"] = q
        if entity_type:
            where_parts.append("n.entity_type = $entity_type")
            params["entity_type"] = entity_type
        if source_kind:
            where_parts.append("n.source_kind = $source_kind")
            params["source_kind"] = source_kind
        if review_status:
            where_parts.append("n.review_status = $review_status")
            params["review_status"] = review_status
        if visibility:
            where_parts.append("n.visibility = $visibility")
            params["visibility"] = visibility
        if min_confidence is not None:
            where_parts.append("n.confidence >= $min_confidence")
            params["min_confidence"] = min_confidence

        where_clause = " AND ".join(where_parts)

        count_query = f"MATCH (n:Entity) WHERE {where_clause} RETURN count(n) AS total"
        items_query = (
            f"MATCH (n:Entity) WHERE {where_clause} "
            f"RETURN n ORDER BY {sort_field} {order_dir} "
            f"SKIP $offset LIMIT $limit"
        )

        with self._driver.session() as session:
            total = session.run(count_query, params).single()["total"]
            items = [
                _node_to_dict(rec["n"])
                for rec in session.run(items_query, params)
            ]
        return items, total

    def list_sources(self, workspace: str) -> list[dict[str, Any]]:
        """Fuentes distintas en el workspace (por source_document). Solo lectura."""
        query = """
        MATCH (n:Entity {workspace:$workspace})
        WHERE n.source_document IS NOT NULL AND n.source_document <> ''
        RETURN n.source_document AS source_id,
               n.source_kind AS source_kind,
               count(n) AS entity_count
        ORDER BY source_id
        """
        with self._driver.session() as session:
            return [
                {
                    "source_id": r["source_id"],
                    "source_kind": r["source_kind"],
                    "entity_count": r["entity_count"],
                }
                for r in session.run(query, {"workspace": workspace})
            ]

    def source_detail(self, workspace: str, source_id: str) -> dict[str, Any] | None:
        """Detalle de una fuente: counts por tipo, review_status. Solo lectura."""
        check_query = """
        MATCH (n:Entity {workspace:$workspace})
        WHERE n.source_document = $source_id
        RETURN count(n) AS total
        """
        with self._driver.session() as session:
            total = session.run(check_query, {"workspace": workspace, "source_id": source_id}).single()["total"]
            if total == 0:
                return None
            by_type_query = """
            MATCH (n:Entity {workspace:$workspace})
            WHERE n.source_document = $source_id AND n.entity_type IS NOT NULL
            RETURN n.entity_type AS entity_type, count(n) AS count
            ORDER BY count DESC
            """
            by_review_query = """
            MATCH (n:Entity {workspace:$workspace})
            WHERE n.source_document = $source_id AND n.review_status IS NOT NULL
            RETURN n.review_status AS review_status, count(n) AS count
            ORDER BY count DESC
            """
            by_type = [
                {"entity_type": r["entity_type"], "count": r["count"]}
                for r in session.run(by_type_query, {"workspace": workspace, "source_id": source_id})
            ]
            by_review = [
                {"review_status": r["review_status"], "count": r["count"]}
                for r in session.run(by_review_query, {"workspace": workspace, "source_id": source_id})
            ]
        return {
            "source_id": source_id,
            "workspace": workspace,
            "entity_count": total,
            "by_entity_type": by_type,
            "by_review_status": by_review,
        }

    def quality_metrics(self, workspace: str | None = None) -> dict[str, Any]:
        """Métricas de calidad de solo lectura. MATCH-only, 0 escrituras."""
        if workspace:
            base_filter = "n.workspace = $workspace"
            rel_filter = (
                "n.workspace = $workspace AND m.workspace = $workspace"
            )
            params: dict[str, Any] = {"workspace": workspace}
        else:
            base_filter = "true"
            rel_filter = "true"
            params = {}

        with self._driver.session() as session:
            # Totales
            total_entities = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} RETURN count(n) AS c", params
            ).single()["c"]
            total_relations = session.run(
                f"MATCH (n:Entity)-[r]->(m:Entity) WHERE {rel_filter} RETURN count(r) AS c", params
            ).single()["c"]

            # Por tipo
            by_type_rows = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND n.entity_type IS NOT NULL "
                f"RETURN n.entity_type AS k, count(n) AS c ORDER BY c DESC",
                params,
            )
            by_type = {r["k"]: r["c"] for r in by_type_rows}

            # Por workspace
            by_ws_rows = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND n.workspace IS NOT NULL "
                f"RETURN n.workspace AS k, count(n) AS c ORDER BY c DESC",
                params,
            )
            by_ws = {r["k"]: r["c"] for r in by_ws_rows}

            # Por review_status
            by_review_rows = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND n.review_status IS NOT NULL "
                f"RETURN n.review_status AS k, count(n) AS c ORDER BY c DESC",
                params,
            )
            by_review = {r["k"]: r["c"] for r in by_review_rows}

            # Por visibility
            by_vis_rows = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND n.visibility IS NOT NULL "
                f"RETURN n.visibility AS k, count(n) AS c ORDER BY c DESC",
                params,
            )
            by_vis = {r["k"]: r["c"] for r in by_vis_rows}

            # Distribución de confianza
            conf_high = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND n.confidence >= 0.8 RETURN count(n) AS c", params
            ).single()["c"]
            conf_mid = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND n.confidence >= 0.5 AND n.confidence < 0.8 RETURN count(n) AS c", params
            ).single()["c"]
            conf_low = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND n.confidence < 0.5 RETURN count(n) AS c", params
            ).single()["c"]
            conf_none = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND n.confidence IS NULL RETURN count(n) AS c", params
            ).single()["c"]

            # Gaps de datos
            no_source = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND "
                f"(n.source_document IS NULL OR n.source_document = '') RETURN count(n) AS c", params
            ).single()["c"]
            no_desc = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND "
                f"(n.description IS NULL OR n.description = '') RETURN count(n) AS c", params
            ).single()["c"]
            no_type = session.run(
                f"MATCH (n:Entity) WHERE {base_filter} AND "
                f"(n.entity_type IS NULL OR n.entity_type = '') RETURN count(n) AS c", params
            ).single()["c"]

        return {
            "workspace": workspace,
            "total_entities": total_entities,
            "total_relations": total_relations,
            "by_entity_type": by_type,
            "by_workspace": by_ws,
            "by_review_status": by_review,
            "by_visibility": by_vis,
            "confidence_distribution": {
                "high_gte_0_8": conf_high,
                "mid_gte_0_5": conf_mid,
                "low_lt_0_5": conf_low,
                "no_value": conf_none,
            },
            "data_gaps": {
                "no_source_document": no_source,
                "no_description": no_desc,
                "no_entity_type": no_type,
            },
        }
