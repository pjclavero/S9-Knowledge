"""Doble de driver Neo4j para CONTAR consultas Cypher sin servidor.

Por qué existe: en esta máquina no hay Neo4j accesible (el socket de Docker
está denegado para el usuario), así que no se puede medir latencia real de la
base. Lo que sí se puede medir sin servidor, y es lo que de verdad delata un
N+1, es **cuántas consultas Cypher emite cada operación y cómo crece ese número
con el tamaño del dataset**.

Este doble ejecuta el código real de ``Neo4jGraphProvider`` (no una copia),
registra cada ``session.run`` con su Cypher, y devuelve filas sintéticas con la
forma mínima que el proveedor espera.

LÍMITES, explícitos:
  * No ejecuta Cypher: salvo las consultas ancladas a un identificador de nodo
    —que sí se filtran de verdad, porque de ellas depende el recuento de la
    ficha de entidad— las filas se deciden por la cláusula RETURN y no por el
    patrón MATCH. Los conteos de filas son plausibles, no exactos.
  * No mide latencia, ni plan de ejecución, ni uso de índices.
  * Sirve para contar consultas y detectar crecimiento por elemento (N+1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator


class FakeNode:
    def __init__(self, element_id: str, props: dict[str, Any]):
        self.element_id = element_id
        self._props = props

    def keys(self) -> Any:
        return self._props.keys()

    def __getitem__(self, k: str) -> Any:
        return self._props[k]

    def __iter__(self) -> Iterator[str]:
        return iter(self._props)


class FakeRel:
    def __init__(self, element_id: str, tipo: str, props: dict[str, Any], start: FakeNode, end: FakeNode):
        self.element_id = element_id
        self.type = tipo
        self._props = props
        self.start_node = start
        self.end_node = end

    def keys(self) -> Any:
        return self._props.keys()

    def __getitem__(self, k: str) -> Any:
        return self._props[k]

    def __iter__(self) -> Iterator[str]:
        return iter(self._props)


@dataclass
class Registro:
    cypher: str
    params: dict[str, Any]
    filas: int


@dataclass
class Corpus:
    nodos: list[FakeNode]
    relaciones: list[FakeRel]
    workspaces: list[str] = field(default_factory=lambda: ["perflab"])

    @classmethod
    def desde_grafo(cls, grafo: dict[str, Any]) -> "Corpus":
        nodos = {}
        for n in grafo["nodes"]:
            props = dict(n)
            props["display_name"] = props.get("label")
            props["canonical_name"] = props.get("canonical_name") or props.get("label")
            nodos[n["id"]] = FakeNode(n["id"], props)
        rels = []
        for e in grafo["edges"]:
            a, b = nodos.get(e["from"]), nodos.get(e["to"])
            if a is None or b is None:
                continue
            rels.append(FakeRel(e["id"], e["type"], dict(e), a, b))
        return cls(list(nodos.values()), rels, [grafo.get("workspace", "perflab")])


class FakeResult:
    def __init__(self, filas: list[dict[str, Any]]):
        self._filas = filas

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self._filas)

    def single(self) -> dict[str, Any] | None:
        return self._filas[0] if self._filas else None


class FakeSession:
    def __init__(self, driver: "FakeDriver"):
        self._driver = driver

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def run(self, query: str, params: dict[str, Any] | None = None) -> FakeResult:
        return self._driver._ejecutar(query, params or {})


class FakeDriver:
    """Cuenta consultas. ``registros`` guarda el Cypher exacto, en orden."""

    def __init__(self, corpus: Corpus):
        self.corpus = corpus
        self.registros: list[Registro] = []

    # -- API que usa el proveedor --------------------------------------------
    def session(self) -> FakeSession:
        return FakeSession(self)

    def verify_connectivity(self) -> None:
        return None

    def close(self) -> None:
        return None

    # -- control de la medida -------------------------------------------------
    def reset(self) -> None:
        self.registros = []

    @property
    def n_consultas(self) -> int:
        return len(self.registros)

    # -- "ejecución" ----------------------------------------------------------
    def _ejecutar(self, query: str, params: dict[str, Any]) -> FakeResult:
        filas = self._filas_para(query, params)
        self.registros.append(Registro(" ".join(query.split()), dict(params), len(filas)))
        return FakeResult(filas)

    def _filas_para(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        q = " ".join(query.split())
        ret = q.upper().split("RETURN", 1)[-1]
        limite = params.get("limit")
        offset = params.get("offset") or 0

        agregado = re.search(r"COUNT\((\w)\)\s+AS\s+(\w+)", ret)
        proyecciones = re.findall(r"[NM]\.(\w+)\s+AS\s+(\w+)", ret)

        if agregado and proyecciones:
            # Agrupación: RETURN n.<prop> AS x[, ...], count(n) AS c
            alias_cnt = agregado.group(2).lower()
            grupos = 8
            por_grupo = max(1, len(self.corpus.nodos) // grupos)
            filas = []
            for i in range(grupos):
                fila: dict[str, Any] = {alias_cnt: por_grupo}
                for _prop, alias in proyecciones:
                    fila[alias.lower()] = f"g{i}"
                filas.append(fila)
            return filas

        if agregado:
            # Escalar: RETURN count(n) AS c / AS total
            alias = agregado.group(2).lower()
            base = (
                len(self.corpus.relaciones)
                if agregado.group(1).upper() == "R"
                else len(self.corpus.nodos)
            )
            return [{alias: base}]

        # DISTINCT workspace
        if "DISTINCT" in ret and "WORKSPACE" in ret:
            return [{"workspace": w} for w in self.corpus.workspaces]

        # Consultas ancladas a un nodo por identificador. Éstas SÍ se filtran de
        # verdad: si no, `relations_for_entity` recibiría las relaciones del
        # grafo entero y el recuento de consultas de la ficha de entidad
        # quedaría inflado por el doble, no por el visor.
        ident = params.get("id")
        if ident is not None:
            if ret.strip().startswith("R"):
                saliente = "<-" not in q  # MATCH (n)-[r]->(m) frente a (n)<-[r]-(m)
                rels = [
                    r for r in self.corpus.relaciones
                    if (r.start_node.element_id if saliente else r.end_node.element_id) == ident
                ]
                return [{"r": r} for r in rels]
            nodo = next((n for n in self.corpus.nodos if n.element_id == ident), None)
            return [{"n": nodo}] if nodo is not None else []

        # Triples n, r, m
        if re.search(r"^\s*N, R, M", ret):
            rels = self.corpus.relaciones[: limite or len(self.corpus.relaciones)]
            return [{"n": r.start_node, "r": r, "m": r.end_node} for r in rels]

        # Sólo relaciones
        if ret.strip().startswith("R"):
            return [{"r": r} for r in self.corpus.relaciones[: limite or len(self.corpus.relaciones)]]

        # Sólo nodos
        if ret.strip().startswith("N") or " N " in f" {ret.strip()} ":
            nodos = self.corpus.nodos[offset:]
            return [{"n": n} for n in nodos[: limite or len(nodos)]]

        return []


def proveedor_neo4j_falso(grafo: dict[str, Any]):
    """``(provider, driver)`` — el proveedor Neo4j REAL sobre un driver doble."""
    from app.providers.neo4j_provider import Neo4jGraphProvider

    driver = FakeDriver(Corpus.desde_grafo(grafo))
    provider = Neo4jGraphProvider.__new__(Neo4jGraphProvider)
    provider._driver = driver  # noqa: SLF001 - inyección deliberada en la medida
    return provider, driver
