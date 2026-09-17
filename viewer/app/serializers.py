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
        # Identificador ESTABLE de dominio, y solo eso.
        #
        # Deliberadamente NO cae hacia `id` ni hacia `element_id`: en Neo4j el
        # `element_id` no es identidad durable (se regenera al restaurar un
        # dump), asi que ofrecerlo como "identificador" seria mentir y, peor,
        # meterlo en el indice de busqueda del visor lo convertiria en un
        # identificador de recurso buscable que el dominio no reconoce.
        # Si el proveedor no entrega `entity_id`, aqui no hay `entity_id`.
        #
        # Esta regla NO vive solo en este comentario: la congelan cuatro pruebas
        # de servidor en `tests/test_serializers.py` (bloque «entity_id NO cae
        # hacia id ni element_id»). Anadir el fallback las pone en rojo.
        "entity_id": node.get("entity_id") or "",
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


def serialize_assertion(assertion: dict[str, Any]) -> dict[str, Any]:
    """Convierte un hecho (`:V3Assertion`) crudo en la forma humana de la UI.

    Lista EXPLICITA, como sus dos hermanas: lo que no esta aqui no sale.

    `local_override_of` NO se publica. Lo que se publica es un booleano
    derivado, `es_divergencia_local`, y la diferencia importa: el campo crudo
    es el `assertion_id` del hecho de capa juego que esta divergencia
    sustituye, y la pantalla no necesita ese identificador para decir lo unico
    que el requisito pide decir --"esto es una divergencia local de tu
    partida"--. Publicar el puntero seria entregar la identidad de un objeto
    que esta lectura acaba precisamente de RETIRAR de la vista.

    El booleano tampoco sustituye al enmascarado ni lo repite: para cuando un
    hecho llega aqui, `PolicyFilteredProvider` ya decidio que se enseña. Esto
    es la ETIQUETA de lo que se enseña, no la decision de si se enseña.
    """
    assertion = dict(assertion)
    confidence = assertion.get("confidence")
    destino = assertion.get("local_override_of")
    return {
        "assertion_id": assertion.get("assertion_id") or assertion.get("id") or "",
        "predicate": assertion.get("predicate") or "",
        "label": relation_label(
            assertion.get("predicate") or "", assertion.get("predicate_label_es")
        ),
        "subject_entity_id": assertion.get("subject_entity_id") or "",
        "object_entity_id": assertion.get("object_entity_id") or "",
        "status": assertion.get("status") or "",
        "es_divergencia_local": isinstance(destino, str) and bool(destino),
        "confidence": confidence,
        "confidence_label": _confidence_label(confidence),
        "visibility": assertion.get("visibility") or "",
        "visibility_label": visibility_label(assertion.get("visibility")),
        "review_status": assertion.get("review_status") or "",
        "review_status_label": review_status_label(assertion.get("review_status")),
    }


def serialize_graph(
    workspace: str,
    nodes: list[dict],
    edges: list[dict],
    view: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serializa el grafo y, si se le da, la DECLARACIÓN de parcialidad.

    `view` (ver `app.graph_view.vista_truncada`) lleva los contadores de lo
    mostrado y de lo total AUTORIZADO. Es opcional en la firma porque hay
    llamadas que no recortan nada, pero `/api/graph` lo pasa SIEMPRE: sin él,
    el cliente no puede distinguir "esto es todo" de "esto es un trozo", y por
    diseño el cliente trata su ausencia como vista posiblemente incompleta.
    """
    out: dict[str, Any] = {
        "workspace": workspace,
        "nodes": [serialize_node(n) for n in nodes],
        "edges": [serialize_edge(e) for e in edges],
    }
    if view is not None:
        out["view"] = view
    return out
