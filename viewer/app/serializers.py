"""Transforma nodos/relaciones "técnicos" (mock o Neo4j) en datos humanos.

Los proveedores (mock_provider, neo4j_provider) devuelven diccionarios con
claves más o menos crudas. Este módulo es el único responsable de decidir
qué se muestra por defecto y qué se relega a la sección "technical" (debug).
"""
from __future__ import annotations

from typing import Any

from app.labels import (
    entity_type_label,
    knowledge_layer_label,
    relation_label,
    review_status_label,
    visibility_label,
)

# Campos que NO se muestran en la ficha principal, solo en "technical".
_NODE_TECHNICAL_FIELDS = (
    "created_at",
    "updated_at",
    "extractor_version",
    "prompt_version",
    "source_hash",
)

_EDGE_TECHNICAL_FIELDS = (
    "created_at",
    "updated_at",
    "extractor_version",
    "prompt_version",
    "source_hash",
)


def _confidence_label(confidence: float | None) -> str:
    if confidence is None:
        return ""
    try:
        return f"{round(float(confidence) * 100)}%"
    except (TypeError, ValueError):
        return ""


def serialize_node(node: dict[str, Any]) -> dict[str, Any]:
    """Convierte un nodo crudo (mock o Neo4j) en la forma humana usada por la API/UI."""
    node = dict(node)
    entity_type = node.get("type") or node.get("entity_type") or ""
    name = node.get("label") or node.get("display_name") or node.get("canonical_name") or ""
    confidence = node.get("confidence")

    technical = {f: node[f] for f in _NODE_TECHNICAL_FIELDS if node.get(f) is not None}

    return {
        "id": node.get("id") or node.get("element_id"),
        "label": name,
        "type": entity_type,
        "type_label": node.get("type_label") or entity_type_label(entity_type),
        "description": node.get("description") or "",
        "short_summary": node.get("short_summary") or node.get("summary") or "",
        "aliases": node.get("aliases") or [],
        "workspace": node.get("workspace"),
        "source_document": node.get("source_document") or "",
        "source_pages": node.get("source_pages") or [],
        "source_kind": node.get("source_kind") or "",
        "confidence": confidence,
        "confidence_label": _confidence_label(confidence),
        "visibility": node.get("visibility") or "",
        "visibility_label": visibility_label(node.get("visibility")),
        "knowledge_layer": node.get("knowledge_layer") or "",
        "knowledge_layer_label": knowledge_layer_label(node.get("knowledge_layer")),
        "review_status": node.get("review_status") or "",
        "review_status_label": review_status_label(node.get("review_status")),
        "manual_review_required": node.get("manual_review_required"),
        "technical": technical,
    }


def serialize_edge(edge: dict[str, Any]) -> dict[str, Any]:
    """Convierte una relación cruda (mock o Neo4j) en la forma humana usada por la API/UI."""
    edge = dict(edge)
    relation_type = edge.get("type") or edge.get("relation_type") or ""
    confidence = edge.get("confidence")

    technical = {f: edge[f] for f in _EDGE_TECHNICAL_FIELDS if edge.get(f) is not None}

    return {
        "id": edge.get("id") or edge.get("element_id"),
        "from": edge.get("from") or edge.get("source"),
        "to": edge.get("to") or edge.get("target"),
        "type": relation_type,
        "label": relation_label(relation_type, edge.get("relation_label_es") or edge.get("label")),
        "description": edge.get("description") or edge.get("evidence") or "",
        "source_document": edge.get("source_document") or "",
        "source_pages": edge.get("source_pages") or [],
        "confidence": confidence,
        "confidence_label": _confidence_label(confidence),
        "review_status": edge.get("review_status") or "",
        "review_status_label": review_status_label(edge.get("review_status")),
        "technical": technical,
    }


def serialize_graph(workspace: str, nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    return {
        "workspace": workspace,
        "nodes": [serialize_node(n) for n in nodes],
        "edges": [serialize_edge(e) for e in edges],
    }
