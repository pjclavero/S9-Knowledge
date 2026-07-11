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

    def _nodes_in_workspace(self, workspace: str) -> list[dict[str, Any]]:
        return [n for n in self._nodes if n.get("workspace") == workspace]

    def _edges_in_workspace(self, workspace: str) -> list[dict[str, Any]]:
        return [e for e in self._edges if e.get("workspace") == workspace]
