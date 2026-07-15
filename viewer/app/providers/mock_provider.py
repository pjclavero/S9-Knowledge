"""Proveedor de grafo basado en un JSON local (examples/sample_graph.json).

Permite desarrollar y probar el visor sin conexión a Neo4j. Solo lectura:
el archivo se carga una vez en memoria y nunca se escribe.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.providers.base import GraphProvider


class MockGraphProvider(GraphProvider):
    name = "mock"

    def __init__(self, sample_path: str | Path):
        self._path = Path(sample_path)
        data = json.loads(self._path.read_text(encoding="utf-8"))
        workspace = data.get("workspace", "leyenda")

        self._nodes: list[dict[str, Any]] = []
        for n in data.get("nodes", []):
            node = dict(n)
            node.setdefault("workspace", workspace)
            self._nodes.append(node)

        self._edges: list[dict[str, Any]] = []
        for e in data.get("edges", []):
            edge = dict(e)
            edge.setdefault("workspace", workspace)
            self._edges.append(edge)

        self._nodes_by_id = {n["id"]: n for n in self._nodes}

    def is_connected(self) -> bool:
        return True

    def workspaces(self) -> list[str]:
        return sorted({n["workspace"] for n in self._nodes if n.get("workspace")})

    def counts(self, workspace: str | None = None) -> tuple[int, int]:
        nodes = self._nodes_in_workspace(workspace) if workspace else self._nodes
        edges = self._edges_in_workspace(workspace) if workspace else self._edges
        return len(nodes), len(edges)

    def entity_types(self, workspace: str) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for n in self._nodes_in_workspace(workspace):
            t = n.get("type")
            if t:
                counts[t] = counts.get(t, 0) + 1
        return [
            {"entity_type": t, "count": c}
            for t, c in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        ]

    def search(self, workspace: str, q: str, limit: int = 50) -> list[dict[str, Any]]:
        ql = q.strip().lower()
        if not ql:
            return []
        results = []
        for n in self._nodes_in_workspace(workspace):
            haystacks = [
                n.get("label", ""),
                n.get("description", ""),
                *(n.get("aliases") or []),
            ]
            if any(ql in str(h).lower() for h in haystacks):
                results.append(n)
        return results[:limit]

    def graph(
        self,
        workspace: str,
        limit: int = 300,
        entity_type: str | None = None,
        q: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        nodes = self._nodes_in_workspace(workspace)

        if entity_type:
            nodes = [n for n in nodes if n.get("type") == entity_type]

        if q:
            ql = q.strip().lower()
            nodes = [
                n
                for n in nodes
                if ql in n.get("label", "").lower()
                or ql in n.get("description", "").lower()
                or any(ql in str(a).lower() for a in (n.get("aliases") or []))
            ]

        nodes = nodes[:limit]
        node_ids = {n["id"] for n in nodes}

        edges = [
            e
            for e in self._edges_in_workspace(workspace)
            if e.get("from") in node_ids and e.get("to") in node_ids
        ]
        return nodes, edges

    def entity(self, entity_id: str) -> dict[str, Any] | None:
        return self._nodes_by_id.get(entity_id)

    def relations_for_entity(
        self, entity_id: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        outgoing = [e for e in self._edges if e.get("from") == entity_id]
        incoming = [e for e in self._edges if e.get("to") == entity_id]
        return outgoing, incoming

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
        nodes = self._nodes_in_workspace(workspace)
        if q:
            ql = q.strip().lower()
            nodes = [
                n for n in nodes
                if ql in (n.get("label") or n.get("canonical_name") or "").lower()
                or ql in (n.get("description") or "").lower()
                or any(ql in str(a).lower() for a in (n.get("aliases") or []))
            ]
        if entity_type:
            nodes = [n for n in nodes if n.get("type") == entity_type]
        if source_kind:
            nodes = [n for n in nodes if n.get("source_kind") == source_kind]
        if review_status:
            nodes = [n for n in nodes if n.get("review_status") == review_status]
        if visibility:
            nodes = [n for n in nodes if n.get("visibility") == visibility]
        if min_confidence is not None:
            nodes = [
                n for n in nodes
                if n.get("confidence") is not None and float(n.get("confidence", 0)) >= min_confidence
            ]
        # Ordenación
        _SORT_FIELDS = {"canonical_name", "confidence", "entity_type", "review_status", "created_at"}
        sort_key = sort if sort in _SORT_FIELDS else "canonical_name"
        reverse = order == "desc"
        nodes = sorted(
            nodes,
            key=lambda n: (n.get(sort_key) or n.get("label") or ""),
            reverse=reverse,
        )
        total = len(nodes)
        page = nodes[offset:offset + limit]
        return page, total

    def list_sources(self, workspace: str) -> list[dict[str, Any]]:
        source_ids: dict[str, int] = {}
        for n in self._nodes_in_workspace(workspace):
            sid = n.get("source_document") or n.get("source_id")
            if sid:
                source_ids[sid] = source_ids.get(sid, 0) + 1
        return [{"source_id": sid, "entity_count": cnt} for sid, cnt in sorted(source_ids.items())]

    def source_detail(self, workspace: str, source_id: str) -> dict[str, Any] | None:
        entities = [
            n for n in self._nodes_in_workspace(workspace)
            if (n.get("source_document") or n.get("source_id")) == source_id
        ]
        if not entities:
            return None
        return {
            "source_id": source_id,
            "workspace": workspace,
            "entity_count": len(entities),
            "entity_types": list({n.get("type") for n in entities if n.get("type")}),
        }

    def quality_metrics(self, workspace: str | None = None) -> dict[str, Any]:
        nodes = self._nodes_in_workspace(workspace) if workspace else self._nodes
        edges = self._edges_in_workspace(workspace) if workspace else self._edges

        total_entities = len(nodes)
        total_relations = len(edges)

        by_type: dict[str, int] = {}
        by_ws: dict[str, int] = {}
        by_review: dict[str, int] = {}
        by_visibility: dict[str, int] = {}
        confidence_high = confidence_mid = confidence_low = confidence_none = 0
        no_source = no_description = no_entity_type = 0

        for n in nodes:
            by_type[n.get("type") or ""] = by_type.get(n.get("type") or "", 0) + 1
            by_ws[n.get("workspace") or ""] = by_ws.get(n.get("workspace") or "", 0) + 1
            by_review[n.get("review_status") or ""] = by_review.get(n.get("review_status") or "", 0) + 1
            by_visibility[n.get("visibility") or ""] = by_visibility.get(n.get("visibility") or "", 0) + 1
            c = n.get("confidence")
            if c is None:
                confidence_none += 1
            elif float(c) >= 0.8:
                confidence_high += 1
            elif float(c) >= 0.5:
                confidence_mid += 1
            else:
                confidence_low += 1
            if not (n.get("source_document") or n.get("source_id")):
                no_source += 1
            if not n.get("description"):
                no_description += 1
            if not n.get("type"):
                no_entity_type += 1

        return {
            "workspace": workspace,
            "total_entities": total_entities,
            "total_relations": total_relations,
            "by_entity_type": by_type,
            "by_workspace": by_ws,
            "by_review_status": by_review,
            "by_visibility": by_visibility,
            "confidence_distribution": {
                "high_gte_0_8": confidence_high,
                "mid_gte_0_5": confidence_mid,
                "low_lt_0_5": confidence_low,
                "no_value": confidence_none,
            },
            "data_gaps": {
                "no_source_document": no_source,
                "no_description": no_description,
                "no_entity_type": no_entity_type,
            },
        }

    def _nodes_in_workspace(self, workspace: str) -> list[dict[str, Any]]:
        return [n for n in self._nodes if n.get("workspace") == workspace]

    def _edges_in_workspace(self, workspace: str) -> list[dict[str, Any]]:
        return [e for e in self._edges if e.get("workspace") == workspace]
