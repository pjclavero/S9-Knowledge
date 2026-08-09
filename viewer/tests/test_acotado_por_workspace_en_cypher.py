"""El acotado por workspace DENTRO del Cypher (H6-11).

El registro declara para `workspace` una doble barrera: "acotado en Cypher y
comprobado despues por la politica". La segunda mitad estaba probada; la
primera, declarada y no. Y la diferencia importa: si la consulta trae nodos de
otro workspace y solo los descarta el filtro posterior, cualquier camino que se
salte el filtro --un endpoint nuevo, un conteo, una agregacion hecha en la
consulta-- devuelve material ajeno. Es la forma exacta de H1.

No hace falta un Neo4j: se inyecta un driver falso que captura la consulta y
los parametros. Lo que se comprueba es que el acotado esta EN LA CONSULTA.
"""
from __future__ import annotations

import pytest

from app.providers import neo4j_provider as mod


class _Sesion:
    def __init__(self, registro):
        self._registro = registro

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, params=None, **kw):
        self._registro.append((query, params if params is not None else kw))
        return _Resultado()


class _Registro(dict):
    """Fila falsa: cualquier columna vale 0."""

    def __missing__(self, k):
        return 0


class _Resultado:
    def single(self):
        return _Registro()

    def __iter__(self):
        return iter(())


class _Driver:
    def __init__(self, registro):
        self._registro = registro

    def session(self):
        return _Sesion(self._registro)


@pytest.fixture
def proveedor():
    registro: list = []
    p = mod.Neo4jGraphProvider.__new__(mod.Neo4jGraphProvider)
    p._driver = _Driver(registro)
    return p, registro


def test_el_acceso_por_ID_acota_el_workspace_en_la_consulta(proveedor):
    p, registro = proveedor
    p.entity("abc", workspaces=frozenset({"juego:uno", "juego:dos"}))
    query, params = registro[-1]
    assert "n.workspace IN $workspaces" in query, (
        "el acotado por workspace no viaja en el Cypher: el aislamiento "
        "dependeria por completo del filtro posterior"
    )
    assert params["workspaces"] == ["juego:dos", "juego:uno"]


def test_el_listado_acota_el_workspace_en_la_consulta(proveedor):
    p, registro = proveedor
    p.list_entities("juego:uno", limit=10)
    consultas = [q for q, _ in registro]
    assert all("n.workspace = $workspace" in q for q in consultas), consultas
    assert all(par.get("workspace") == "juego:uno" for _, par in registro)


def test_la_busqueda_acota_el_workspace_en_la_consulta(proveedor):
    p, registro = proveedor
    p.search("juego:uno", "algo")
    query, params = registro[-1]
    assert "{workspace:$workspace}" in query.replace(" ", "")
    assert params["workspace"] == "juego:uno"


def test_el_conteo_acota_el_workspace_en_la_consulta(proveedor):
    """Un conteo se calcula EN la consulta: si no acota, el numero ya delata
    material ajeno aunque el filtro posterior oculte los nodos."""
    p, registro = proveedor
    p.counts(workspace="juego:uno")
    for query, params in registro:
        assert "workspace:$workspace" in query.replace(" ", ""), query
        assert params["workspace"] == "juego:uno"


def test_las_metricas_de_calidad_acotan_el_workspace(proveedor):
    p, registro = proveedor
    p.quality_metrics(workspace="juego:uno")
    assert registro, "no se ejecuto ninguna consulta"
    for query, params in registro:
        assert "n.workspace = $workspace" in query, query
        assert params.get("workspace") == "juego:uno"
