"""Carga READ-ONLY de datasets de grafo (fixture JSON o Neo4j efímero).

Ninguna ruta de este módulo escribe. La lectura de Neo4j usa exclusivamente
`MATCH ... RETURN` y rechaza por defecto cualquier destino que parezca
producción.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .registry import ALIAS_DE_PROYECCION

#: Destinos vetados de raíz para este encargo (producción S9K, VM105).
HOSTS_PROHIBIDOS = ("192.168.1.205", "vm105", "knowledge.seccionnueve")


class DatasetError(RuntimeError):
    """Error irrecuperable al cargar el dataset (nunca degrada a 'vacío')."""


@dataclass
class Dataset:
    origen: str
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)

    def node_field(self, node: dict[str, Any], name: str) -> Any:
        """Valor canónico de un campo, resolviendo alias de proyección."""
        if name in node:
            return node[name]
        for alias, canonico in ALIAS_DE_PROYECCION.items():
            if canonico == name and alias in node:
                return node[alias]
        return None

    def node_id(self, node: dict[str, Any]) -> str:
        v = self.node_field(node, "entity_id")
        return "" if v is None else str(v)


def _as_list(value: Any, campo: str, origen: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
        raise DatasetError(f"{origen}: '{campo}' no es una lista de objetos")
    return value


def load_json(path: str | Path) -> Dataset:
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DatasetError(f"fixture inexistente: {p}") from exc
    except json.JSONDecodeError as exc:
        raise DatasetError(f"fixture con JSON inválido: {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise DatasetError(f"{p}: se esperaba un objeto con 'nodes'/'edges'")
    nodes = _as_list(raw.get("nodes"), "nodes", str(p))
    edges = _as_list(
        raw.get("edges") if raw.get("edges") is not None else raw.get("relationships"),
        "edges",
        str(p),
    )
    if not nodes and not edges:
        raise DatasetError(f"{p}: dataset sin nodos ni relaciones (¿fichero equivocado?)")
    return Dataset(origen=str(p), nodes=nodes, edges=edges)


def load_neo4j(uri: str, user: str, password: str, permitir_destino: bool = False) -> Dataset:
    """Lee un Neo4j EFÍMERO. Solo MATCH/RETURN; nunca CREATE/MERGE/SET/DELETE."""
    destino = uri.lower()
    if not permitir_destino:
        for prohibido in HOSTS_PROHIBIDOS:
            if prohibido in destino:
                raise DatasetError(
                    f"destino vetado en este comprobador (parece producción): {uri}"
                )
    try:
        from neo4j import GraphDatabase  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise DatasetError(f"driver neo4j no disponible: {exc}") from exc

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as s:
            nodes = [
                dict(r["n"]) for r in s.run("MATCH (n:Entity) RETURN n")
            ]
            edges = []
            for r in s.run(
                "MATCH (a:Entity)-[rel]->(b:Entity) "
                "RETURN a.entity_id AS f, b.entity_id AS t, type(rel) AS ty, rel AS rel"
            ):
                props = dict(r["rel"])
                props.update({"from": r["f"], "to": r["t"], "type": r["ty"]})
                edges.append(props)
    finally:
        driver.close()
    return Dataset(origen=f"neo4j:{uri}", nodes=nodes, edges=edges)


def load_from_env_or_path(path: str | None) -> Dataset:
    if path:
        return load_json(path)
    uri = os.environ.get("S9K_HEALTH_NEO4J_URI")
    if not uri:
        raise DatasetError("no se indicó fixture ni S9K_HEALTH_NEO4J_URI")
    return load_neo4j(
        uri,
        os.environ.get("S9K_HEALTH_NEO4J_USER", "neo4j"),
        os.environ.get("S9K_HEALTH_NEO4J_PASSWORD", ""),
        permitir_destino=os.environ.get("S9K_HEALTH_ALLOW_TARGET") == "1",
    )
