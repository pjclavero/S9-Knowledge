# -*- coding: utf-8 -*-
"""CARRIL M — el enmascarado de divergencia local contra Neo4j REAL.

POR QUE ESTE MODULO EXISTE APARTE
---------------------------------
`test_multipartida_divergencia_local_pantalla.py` demuestra el enmascarado por
la pantalla con un proveedor falso, y comprueba el eslabon de TRANSPORTE del
proveedor de Neo4j por CONTRATO (`_assertion_to_dict` sobre un nodo simulado).
Eso es suficiente para afirmar que el campo viaja, pero no ejecuta ni una
consulta: si el Cypher de `list_assertions` estuviera mal escrito --una
etiqueta cambiada, un `status` que no existe, un campo que Neo4j devuelve con
otro nombre-- el contrato seguiria verde.

Aqui se ejecuta de verdad. Un revisor independiente levanto un Neo4j en
contenedor y comprobo justo esto a mano; dejarlo escrito es lo que impide que
la regresion vuelva a ser invisible.

Se salta solo si no hay Neo4j efimero, igual que el resto de suites de este
repositorio. ADVERTENCIA: un `skipped` NO es un verde. Si este modulo se salta,
lo unico demostrado sobre Neo4j real es nada.
"""
from __future__ import annotations

import os
import uuid

import pytest

URI = os.environ.get("NEO4J_TEST_URI")
USER = os.environ.get("NEO4J_TEST_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD")

pytestmark = pytest.mark.skipif(
    not URI or not PASSWORD,
    reason="sin Neo4j efimero (define NEO4J_TEST_URI y NEO4J_TEST_PASSWORD)",
)

SUJETO = "dios-sol"
ID_LORE = "hecho-lore-dios-sol"
ID_DIV_B = "hecho-partidaB-dios-sol"
PARTIDA_B = "partida-B"


@pytest.fixture
def workspace_efimero():
    """Workspace propio por ejecucion, y se BORRA al salir.

    Nombre unico para no pisar material de otra suite que comparta la misma
    instancia, y borrado acotado a ese workspace: nunca un `DETACH DELETE`
    global, que se llevaria por delante lo de los demas.
    """
    from app.providers.neo4j_provider import Neo4jGraphProvider

    ws = f"juego:carril-m-{uuid.uuid4().hex[:10]}"
    proveedor = Neo4jGraphProvider(URI, USER, PASSWORD)
    with proveedor._driver.session() as s:
        s.run(
            "CREATE (a:V3Assertion {assertion_id:$l, workspace:$ws, "
            "predicate:'protege', subject_entity_id:$suj, status:'ASSERTED', "
            "scope:'juego', partida_id:null, visibility:'player'}) "
            "CREATE (b:V3Assertion {assertion_id:$d, workspace:$ws, "
            "predicate:'exige', subject_entity_id:$suj, status:'ASSERTED', "
            "scope:'partida', partida_id:$pb, visibility:'player', "
            "local_override_of:$l, known_from_session:0}) "
            "CREATE (c:V3Assertion {assertion_id:'hecho-retirado', workspace:$ws, "
            "predicate:'obsoleto', subject_entity_id:$suj, status:'RETRACTED', "
            "scope:'juego', partida_id:null, visibility:'player'})",
            {"l": ID_LORE, "d": ID_DIV_B, "ws": ws, "suj": SUJETO, "pb": PARTIDA_B},
        )
    yield ws, proveedor
    with proveedor._driver.session() as s:
        s.run("MATCH (n {workspace:$ws}) DETACH DELETE n", {"ws": ws})
    proveedor.close()


def test_el_cypher_lee_las_aserciones_y_transporta_local_override_of(
    workspace_efimero,
):
    """El Cypher de `list_assertions` FUNCIONA contra Neo4j real.

    No es lo mismo que la prueba de contrato: aquella simula un nodo, esta
    ejecuta la consulta. Aqui mueren los fallos que el contrato no puede ver:
    etiqueta equivocada, propiedad que no existe, alias mal puesto.
    """
    ws, proveedor = workspace_efimero
    filas = proveedor.list_assertions(ws, subject_entity_id=SUJETO)
    por_id = {f["assertion_id"]: f for f in filas}

    # Vigencia: el RETRACTED no sale. Control de que el filtro de estado actua.
    assert "hecho-retirado" not in por_id, "una asercion RETRACTED no es vigente"
    assert set(por_id) == {ID_LORE, ID_DIV_B}

    # El puntero VIAJA desde Neo4j real. Este es el eslabon que el contrato
    # afirma y que aqui se observa.
    assert por_id[ID_DIV_B]["local_override_of"] == ID_LORE
    assert por_id[ID_LORE]["local_override_of"] is None
    assert por_id[ID_DIV_B]["partida_id"] == PARTIDA_B
    assert por_id[ID_LORE]["partida_id"] is None


def test_ningun_campo_de_autorizacion_llega_vacio_desde_neo4j_real(
    workspace_efimero,
):
    """Un campo de autorizacion que no viaja apaga su barrera en silencio."""
    ws, proveedor = workspace_efimero
    filas = proveedor.list_assertions(ws, subject_entity_id=SUJETO)
    assert filas

    for fila in filas:
        for campo in ("workspace", "scope", "visibility", "status", "assertion_id"):
            assert fila.get(campo), f"{campo} llego vacio desde Neo4j real"
        # `partida_id` y `local_override_of` pueden ser `None` legitimamente
        # (capa juego), pero la CLAVE tiene que estar: ausente no es lo mismo
        # que inexistente.
        assert "partida_id" in fila
        assert "local_override_of" in fila


def test_el_enmascarado_sale_correcto_sobre_dato_real(workspace_efimero):
    """El cruce completo, de Neo4j real hasta el conjunto enmascarado.

    Se monta `PolicyFilteredProvider` sobre el proveedor REAL y se leen las
    dos partidas. Es el recorrido entero --Cypher, transporte, cascada,
    enmascarado-- sin ningun doble por el camino.
    """
    from app.authz.filtered_provider import PolicyFilteredProvider
    from app.policies.models import ViewerContext

    ws, proveedor = workspace_efimero

    def _ctx(partida):
        return ViewerContext(
            role="viewer",
            allowed_workspaces=frozenset({ws}),
            active_partida=partida,
            allowed_partida_ids=frozenset({partida}) if partida else frozenset(),
            max_visible_session=5,
            can_view_reference=True,
            can_view_lore=True,
            session_public=True,
        )

    def _vistos(partida):
        filtrado = PolicyFilteredProvider(proveedor, _ctx(partida))
        return {f["assertion_id"]
                for f in filtrado.list_assertions(ws, subject_entity_id=SUJETO)}

    # La partida que diverge ve SU version y no la original.
    assert _vistos(PARTIDA_B) == {ID_DIV_B}

    # Otra partida sigue viendo el lore comun intacto, y no lo de B.
    assert _vistos("partida-A") == {ID_LORE}

    # Y el dato de capa juego NO se ha tocado: sigue en el grafo, entero.
    crudo = {f["assertion_id"] for f in proveedor.list_assertions(ws)}
    assert ID_LORE in crudo and ID_DIV_B in crudo
