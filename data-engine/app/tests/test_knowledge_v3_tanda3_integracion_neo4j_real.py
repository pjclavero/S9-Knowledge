# -*- coding: utf-8 -*-
"""TANDA 3 / INTEGRACION -- las tres garantias VIVAS A LA VEZ, y la nueva.

Cada equipo probo la suya por separado y nunca han corrido juntas. Eso es lo
que aqui se mide, contra un Neo4j real y efimero:

  R1  apply -> rollback -> cero residuos y `unrecoverable` honesto; y la
      evidencia COMPARTIDA por una asercion viva NO se borra.
  R2  la misma relacion semantica en capa juego y en `partida:otra`; deshacer
      una deja la otra INTACTA. Y el gemelo por NODO.
  B   fichero -> reconciliacion -> altas aprobadas una a una -> apply ->
      procedencia navegable, SIN sembrar nada por Cypher.

  NUEVA (nadie la habia probado): el carril B emite `CREATE_ENTITY` DE VERDAD,
      asi que el rollback de una entidad creada se ejercita por la RUTA REAL
      por primera vez -- y el documento incluye entidades que otras aserciones
      ya referencian, que es justo el caso de R1.

Saltadas por defecto (arrancan un contenedor):

    S9K_WRITER_NEO4J_REAL=1 python -m pytest \
        data-engine/app/tests/test_knowledge_v3_tanda3_integracion_neo4j_real.py -q

No tocan produccion: levantan y destruyen su propio Neo4j.

DOS CAUTELAS DE MEDIDA, aplicadas en todo el fichero:

* nunca dos `MATCH` sueltos en la misma consulta (producto cartesiano, y a
  menudo cero filas que parecen un verde). Cada censo va en su consulta;
* antes de comparar dos conjuntos se comprueba que el de partida NO ESTA
  VACIO. Un `[] == []` no demuestra nada.
"""
from __future__ import annotations

import ast
import os
import pathlib

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("neo4j")

from test_knowledge_v3_writer_neo4j_real import (  # noqa: E402
    HASH_A,
    HASH_B,
    OUTCOME_APPLIED,
    WORKSPACE,
    GraphProbe,
    apply_request,
    create_assertion,
    link_existing,
    make_plan,
    supersede_assertion,
    neo4j_efimero_conexion,
    writer,
    _gemela_de_relacion,
    _instruccion,
)

from knowledge_v3.pipeline import entity_decisions, ingest_cli  # noqa: E402
from knowledge_v3.writer import bootstrap_writer_schema  # noqa: E402
from knowledge_v3.writer.provenance import trace  # noqa: E402
from knowledge_v3.writer.reads import list_entities  # noqa: E402
from knowledge_v3.writer.rollback import (  # noqa: E402
    ACTION_DELETE_NODE,
    ACTION_FORGET_APPLIED,
    ACTION_PURGE_PROVENANCE,
    RollbackDocument,
    RollbackInstruction,
    rollback_query,
)
from knowledge_v3.writer.rollback_provenance import execute_rollback  # noqa: E402
from knowledge_v3.writer.writer import (  # noqa: E402
    OUTCOME_INCONSISTENT,
    GraphWriter,
)
from knowledge_v3.writer.schema import (  # noqa: E402
    V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT,
    V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT_CYPHER,
)

LIVE = os.environ.get("S9K_WRITER_NEO4J_REAL", "").strip() == "1"
pytestmark = pytest.mark.skipif(
    not LIVE, reason="Neo4j real efimero: activar con S9K_WRITER_NEO4J_REAL=1"
)

RAIZ = pathlib.Path(__file__).resolve().parents[3]
EJEMPLOS = RAIZ / "examples" / "ingesta-v3"
FUENTE = EJEMPLOS / "nota-cofradia-de-ambar.md"
PERFIL = EJEMPLOS / "perfil-operador.json"
CATALOGO = EJEMPLOS / "catalogo-workspace.json"
WS_B = "ws-cofradia"
AHORA = "2026-09-06T10:00:00Z"


@pytest.fixture(scope="module")
def conexion():
    with neo4j_efimero_conexion("s9k-tanda3-integracion") as cx:
        yield cx


@pytest.fixture()
def graph(conexion):
    with conexion.driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    bootstrap_writer_schema(conexion.driver)
    return GraphProbe(conexion.driver)


@pytest.fixture()
def limpio(conexion):
    with conexion.driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    return conexion


# --- medida ----------------------------------------------------------------
def _censo_nodos(probe) -> dict:
    filas = probe.run(
        "MATCH (n) UNWIND labels(n) AS etiqueta "
        "RETURN etiqueta, count(*) AS c ORDER BY etiqueta"
    )
    return {f["etiqueta"]: f["c"] for f in filas}


def _censo_relaciones(probe) -> list[dict]:
    return probe.run(
        "MATCH ()-[r]->() RETURN type(r) AS tipo, r.workspace AS ws, "
        "r.partida_id AS partida, r.idempotency_key AS idem "
        "ORDER BY tipo, ws, partida, idem"
    )


def _doc_desde_dict(datos: dict) -> RollbackDocument:
    doc = RollbackDocument(
        workspace=datos["workspace"],
        snapshot_id=datos["snapshot_id"],
        plan_hash=datos["plan_hash"],
        unrecoverable=list(datos.get("unrecoverable") or []),
    )
    doc.instructions = [
        RollbackInstruction(
            operation_id=i["operation_id"],
            action=i["action"],
            target_id=i["target_id"],
            detail=i["detail"],
        )
        for i in datos["instructions"]
    ]
    return doc


class _Runner:
    """`.run(cypher, params)` sobre una sesion real, que es lo que pide
    `execute_rollback`. No abre conexiones: recibe el driver ya montado."""

    def __init__(self, driver):
        self._driver = driver

    def run(self, cypher, params=None):
        with self._driver.session() as s:
            return [r.data() for r in s.run(cypher, params or {})]


# --- LA COMBINACION NUEVA ---------------------------------------------------
def _ingesta(driver, *, altas=(), apply=False, env=None):
    return ingest_cli.run_ingest(
        FUENTE,
        profile_path=PERFIL,
        catalog_path=CATALOGO,
        driver=driver,
        now=AHORA,
        ingested_at=AHORA,
        approved_altas=list(altas),
        apply=apply,
        operator_id="pjc" if apply else None,
        writer_env=env,
    )


def _b_completo(driver):
    """La cadena de B entera: fichero -> reconciliar -> aprobar -> apply.

    Ni una linea de Cypher de siembra: lo que hay en el grafo despues de esto
    lo escribio el producto por su ruta de operador.
    """
    primera = _ingesta(driver)
    ledger = entity_decisions.reconcile(
        resolutions=(
            primera["candidates"]["link_existing"]
            + primera["candidates"]["create_entity"]
        ),
        graph_entity_ids=[],
        workspace=WS_B,
        source_path=str(FUENTE),
    )
    # Aprobadas UNA A UNA, con su revisor. Sin altas aprobadas el plan no trae
    # `CREATE_ENTITY` y este caso no mediria nada.
    assert ledger.altas, "sin altas pendientes no hay alta que aprobar"
    aprobado = entity_decisions.approve(
        ledger, [d.entity_id for d in ledger.altas], reviewer="pjc", at=AHORA
    )
    altas = entity_decisions.approved_snapshot_entities(aprobado)
    assert altas, "sin altas aprobadas el plan no traeria CREATE_ENTITY"
    return _ingesta(
        driver,
        altas=altas,
        apply=True,
        env={"S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": WS_B},
    )


def test_b_la_ruta_real_escribe_create_entity_y_deja_procedencia_navegable(limpio):
    """B, entero, sobre el arbol INTEGRADO. Es la premisa de todo lo demas."""
    informe = _b_completo(limpio.driver)
    escritura = informe["write"]
    assert escritura["outcome"] == "APPLIED", escritura
    assert escritura["applied_operations"] > 0

    # El documento de rollback de esta escritura EXISTE y trae altas de verdad.
    doc = informe.get("rollback")
    assert doc is not None, "un APPLY que crea entidades sin documento de reversion"
    creaciones = [i for i in doc["instructions"] if i["action"] == ACTION_DELETE_NODE]
    assert creaciones, "ningun DELETE_NODE: no se creo nada, no hay combinacion que probar"

    entidades = [e.entity_id for e in list_entities(limpio.driver, WS_B)]
    assert entidades, "el APPLY dijo que escribio y el grafo esta vacio"

    with limpio.driver.session() as s:
        aserciones = [
            r.data()["id"]
            for r in s.run(
                "MATCH (n:V3Assertion {workspace:$ws}) RETURN n.assertion_id AS id",
                {"ws": WS_B},
            )
        ]
    assert aserciones, "sin aserciones no hay procedencia que recorrer"
    recorridos = {a: trace(limpio.driver, WS_B, a) for a in aserciones}
    assert any(filas for filas in recorridos.values()), recorridos


def test_nueva_rollback_de_entidad_creada_por_la_ruta_real_de_b(limpio):
    """LA COMBINACION QUE NADIE HABIA PROBADO.

    B crea entidades de verdad; el documento de reversion de ESAS creaciones
    se ejecuta ahora por el camino de recuperacion de R1, con el filtro de
    ambito de R2 dentro. Antes de esta integracion no existia un
    `CREATE_ENTITY` emitido por el producto que revertir: el rollback de nodo
    solo se habia ejercitado sobre planes escritos a mano en las pruebas.
    """
    informe = _b_completo(limpio.driver)
    assert informe["write"]["outcome"] == "APPLIED"
    doc = _doc_desde_dict(informe["rollback"])

    borrados = [i for i in doc.instructions if i.action == ACTION_DELETE_NODE]
    assert borrados, "sin DELETE_NODE no hay entidad creada que revertir"

    # 1. Cada instruccion de borrado de nodo declara ETIQUETA y AMBITO -- las
    #    dos mitades del merge, en el mismo detalle. Sin etiqueta, R2 deniega;
    #    sin ambito declarado, tambien.
    for instruccion in borrados:
        assert instruccion.detail["label"] in ("V3Entity", "V3Assertion"), instruccion.detail
        assert "partida_id" in instruccion.detail, (
            "el ambito tiene que VIAJAR: campo ausente es DENY, no capa juego"
        )
        consulta = rollback_query(instruccion)
        # R2 dentro: etiqueta en el patron y ambito en el WHERE.
        assert f":{instruccion.detail['label']}" in consulta.cypher
        assert "partida_id" in consulta.cypher
        assert "elementId" not in consulta.cypher

    # 2. R1 dentro: el documento retira ademas la marca de idempotencia.
    acciones = {i.action for i in doc.instructions}
    assert ACTION_FORGET_APPLIED in acciones, (
        "sin FORGET_APPLIED el grafo seguiria afirmando que esto esta aplicado"
    )

    antes = _censo_nodos(GraphProbe(limpio.driver))
    assert antes.get("V3Entity", 0) > 0, "nada que revertir: la medida seria vacia"

    # 3. Se EJECUTA el documento por el camino real de recuperacion.
    informe_rb = execute_rollback(_Runner(limpio.driver), doc)

    despues = _censo_nodos(GraphProbe(limpio.driver))
    assert despues.get("V3Entity", 0) < antes.get("V3Entity", 0), (
        f"el rollback no borro ninguna entidad creada: {antes} -> {despues}"
    )
    # 4. Y lo que NO pudo revertir lo DICE. Honesto, no `[]` por defecto.
    assert informe_rb.to_dict()["unrecoverable"] == doc.unrecoverable


def test_nueva_la_evidencia_que_otra_asercion_viva_sostiene_no_se_borra(limpio):
    """La combinacion nueva EN EL CASO DE R1, sobre evidencia REAL de B.

    La evidencia la escribio la ruta de B, no una siembra. Lo que si se
    declara a mano es el COMPARTIR: una segunda asercion viva que apunta al
    mismo fragmento. Se hace explicito porque esta fuente no produce por si
    sola dos aserciones sobre un mismo fragmento, y sin dos referencias el
    caso no mide nada -- «no se borro» seria cierto por vacio.

    Lo que se mide sigue siendo lo de R1: al revertir UNA asercion, su
    evidencia NO se borra porque otra viva la sostiene, y eso se DECLARA.
    """
    informe = _b_completo(limpio.driver)
    assert informe["write"]["outcome"] == "APPLIED"
    doc = _doc_desde_dict(informe["rollback"])

    purgas = [i for i in doc.instructions if i.action == ACTION_PURGE_PROVENANCE]
    assert purgas, "B no dejo ninguna purga de procedencia: nada que medir"

    runner = _Runner(limpio.driver)
    purga = purgas[0]
    fragmentos = [f for f in (purga.detail.get("fragment_ids") or []) if f]
    assert fragmentos, "purga sin fragmentos: no habria referencia que contar"

    # La evidencia de B existe DE VERDAD antes de tocar nada.
    presentes = runner.run(
        "UNWIND $frs AS fid "
        "MATCH (ev:V3Evidence {fragment_id: fid, workspace: $ws}) "
        "RETURN ev.fragment_id AS fid",
        {"frs": fragmentos, "ws": WS_B},
    )
    assert presentes, "la evidencia que la purga nombra no esta en el grafo"
    objetivo = presentes[0]["fid"]

    # El COMPARTIR, declarado: otra asercion VIVA sobre el mismo fragmento.
    # No la revierte este documento, asi que sigue viva cuando la purga corre.
    runner.run(
        "MATCH (ev:V3Evidence {fragment_id: $fid, workspace: $ws}) "
        "CREATE (a:V3Assertion {assertion_id:'assertion:otra-viva', "
        "workspace:$ws, status:'ASSERTED'})-[:SUPPORTED_BY]->(ev)",
        {"fid": objetivo, "ws": WS_B},
    )
    vivas = runner.run(
        "MATCH (ev:V3Evidence {fragment_id: $fid, workspace: $ws}) "
        "OPTIONAL MATCH (a:V3Assertion)-[:SUPPORTED_BY]->(ev) "
        "RETURN count(a) AS vivas",
        {"fid": objetivo, "ws": WS_B},
    )
    assert vivas and int(vivas[0]["vivas"]) > 1, (
        f"el escenario no quedo montado, el fragmento no esta compartido: {vivas}"
    )

    parcial = RollbackDocument(
        workspace=doc.workspace, snapshot_id=doc.snapshot_id, plan_hash=doc.plan_hash
    )
    parcial.instructions = [purga]
    execute_rollback(runner, parcial)

    quedan = runner.run(
        "MATCH (ev:V3Evidence {fragment_id: $fid, workspace: $ws}) "
        "RETURN ev.fragment_id AS fid",
        {"fid": objetivo, "ws": WS_B},
    )
    assert [f["fid"] for f in quedan] == [objetivo], (
        "se borro evidencia que otra asercion VIVA sostiene"
    )
    assert any("NO se borro" in linea for linea in parcial.unrecoverable), (
        f"conservar la evidencia compartida no se DECLARO: {parcial.unrecoverable}"
    )


# --- R2 vive: el ambito, en el mismo arbol ----------------------------------
def test_r2_sigue_vivo_el_rollback_de_capa_juego_no_toca_otra_partida(graph):
    """El ataque de R2, corriendo en el arbol que ya lleva R1 y B dentro."""
    graph.seed_entity("entity:origen", version=1, state_hash=HASH_A["value"])
    graph.seed_entity("entity:destino", version=1, state_hash=HASH_B["value"])
    plan = make_plan([link_existing("op:0001", "entity:origen", "entity:destino")])
    result = writer(graph.driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_APPLIED, result.codes

    instruccion = _instruccion(result.rollback.to_dict(), "DELETE_RELATIONSHIP")
    assert instruccion.detail["partida_id"] is None  # capa juego, DECLARADA
    clave = instruccion.detail["idempotency_key"]
    _gemela_de_relacion(graph, partida_id="partida:otra", clave=clave)

    antes = _censo_relaciones(graph)
    ambitos = {f["partida"] for f in antes}
    assert {None, "partida:otra"} <= ambitos, f"el escenario no quedo montado: {antes}"

    consulta = rollback_query(instruccion)
    graph.run(consulta.cypher, consulta.params)

    despues = _censo_relaciones(graph)
    supervivientes = [f for f in despues if f["partida"] == "partida:otra"]
    assert supervivientes, "el rollback de capa juego se llevo la de otra partida"
    assert not [f for f in despues if f["partida"] is None and f["idem"] == clave], (
        "la de capa juego no se borro: el caso no probo nada"
    )


def test_r2_sigue_vivo_el_gemelo_por_NODO_de_otra_partida_no_se_borra(graph):
    """El mismo ataque, por nodo. Aqui entra la lista blanca de etiquetas de
    R2: sin ella, un `MATCH (n {workspace, idempotency_key})` alcanza cualquier
    nodo que comparta clave, incluido el de otra partida.

    LA RESTRICCION HAY QUE RETIRARLA, y conviene entender por que -- se midio
    en `artifacts/tanda3-integracion/reproduccion_identidad_assertion.py`:

    `(workspace, assertion_id) IS UNIQUE` NO incluye el ambito, y es CORRECTA
    asi: el contrato exige que un `assertion_id` sea unico en todo el
    workspace, cruzando capa juego y todas sus partidas. Es decir, este gemelo
    es un estado que el producto NO puede crear por su ruta -- el writer lo
    rechaza con `EXEC_TARGET_ALREADY_EXISTS` incluso sin restriccion.

    Entonces, ¿por que probarlo? Porque el preflight midio que la base
    PRODUCTIVA no tiene ni una restriccion, y ahi el gemelo si cabe: por una
    restauracion, una importacion o cualquier escritura que no pase por el
    writer. La consulta de reversion tiene que ser correcta tambien sobre ese
    grafo. Se reproduce esa base retirando la restriccion, y se REPONE al
    salir -- verificandolo.
    """
    graph.seed_entity("entity:a", version=1, state_hash=HASH_A["value"])
    graph.seed_entity("entity:b", version=1, state_hash=HASH_B["value"])
    plan = make_plan(
        [create_assertion("op:0001", "assertion:x", "entity:a", "entity:b")]
    )
    result = writer(graph.driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_APPLIED, result.codes

    instruccion = _instruccion(result.rollback.to_dict(), ACTION_DELETE_NODE)
    clave = instruccion.detail["idempotency_key"]
    assert instruccion.detail["label"] == "V3Assertion"
    assert instruccion.detail["partida_id"] is None

    def restricciones():
        return {
            f["name"]
            for f in graph.run("SHOW CONSTRAINTS YIELD name RETURN name")
        }

    assert V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT in restricciones()
    graph.run(
        f"DROP CONSTRAINT {V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT} IF EXISTS"
    )
    try:
        assert V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT not in restricciones(), (
            "no se retiro de verdad: el caso siguiente no mediria lo que dice"
        )
        graph.run(
            "CREATE (n:V3Assertion {assertion_id:'assertion:x', workspace:$ws, "
            "idempotency_key:$k, partida_id:'partida:otra', status:'ASSERTED'})",
            {"ws": WORKSPACE, "k": clave},
        )
        antes = graph.run(
            "MATCH (n:V3Assertion {assertion_id:'assertion:x', workspace:$ws}) "
            "RETURN n.partida_id AS partida ORDER BY partida",
            {"ws": WORKSPACE},
        )
        assert len(antes) == 2, f"el escenario no quedo montado: {antes}"

        consulta = rollback_query(instruccion)
        graph.run(consulta.cypher, consulta.params)

        despues = graph.run(
            "MATCH (n:V3Assertion {assertion_id:'assertion:x', workspace:$ws}) "
            "RETURN n.partida_id AS partida",
            {"ws": WORKSPACE},
        )
        assert [f["partida"] for f in despues] == ["partida:otra"], (
            f"el gemelo por nodo de otra partida no sobrevivio: {despues}"
        )
    finally:
        # El gemelo impediria recrear la restriccion: se limpia primero.
        graph.run("MATCH (n:V3Assertion) DETACH DELETE n")
        graph.run(V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT_CYPHER)
    assert V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT in restricciones(), (
        "la restriccion NO se repuso"
    )


def test_el_contrato_de_identidad_de_assertion_es_por_workspace_no_por_partida():
    """El hallazgo que R2 senalo al pasar, resuelto por el CONTRATO.

    Reproducido entero contra Neo4j real en
    `artifacts/tanda3-integracion/reproduccion_identidad_assertion.py`. Aqui
    queda la parte que no necesita base: lo que el contrato EXIGE.

    `FactAssertion` es un documento CERRADO que no tiene campo de ambito. Una
    asercion no puede ni declarar en que partida vive, asi que su identidad no
    puede incluir la partida. La clave es `(workspace, assertion_id)`, la misma
    forma que `(workspace, entity_id)`: no hay asimetria entre las dos.
    """
    import json

    esquema = json.loads(
        (RAIZ / "contracts/knowledge-v3/v1/fact-assertion-v3.schema.json").read_text(
            encoding="utf-8"
        )
    )
    props = esquema["properties"]
    assert esquema["additionalProperties"] is False
    assert "partida_id" not in props and "scope" not in props, (
        "si FactAssertion gana un campo de ambito, esta conclusion caduca y "
        "hay que rehacer la medida"
    )
    # Y las dos restricciones tienen la MISMA forma: workspace + id durable.
    assert "(n.workspace, n.assertion_id) IS UNIQUE" in (
        V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT_CYPHER
    )


# --- defecto encontrado AL JUNTAR LAS RAMAS ---------------------------------
def test_reaplicar_un_plan_de_solo_cierre_no_se_declara_INCONSISTENT(graph):
    """Regresion del defecto que sólo aparecio con las tres ramas juntas.

    La comprobacion de honestidad de R1 pregunta al grafo «¿queda algo con
    esta `idempotency_key`?» y, si no, declara INCONSISTENT. Presupone que
    toda operacion deja algo LLEVANDO su clave. Las que CIERRAN una vigencia
    no: `close_assertion_validity` hace `SET` sobre un nodo que ya existia y
    ese nodo conserva la clave de quien lo creo.

    Resultado antes del arreglo: reaplicar un plan de solo cierre se declaraba
    INCONSISTENT con el conocimiento INTACTO. Falso positivo.
    """
    graph.seed_assertion("assertion:lidera", version=1, state_hash=HASH_B["value"])
    plan = make_plan([supersede_assertion("op:0001", "assertion:lidera")])

    primero = writer(graph.driver).write(plan, apply_request(plan))
    assert primero.outcome == OUTCOME_APPLIED, primero.codes

    # El conocimiento sigue entero: se MIDE antes de afirmar nada del replay.
    vivo = graph.run(
        "MATCH (n:V3Assertion {assertion_id:'assertion:lidera', workspace:$ws}) "
        "RETURN n.status AS status",
        {"ws": WORKSPACE},
    )
    assert vivo and vivo[0]["status"] == "SUPERSEDED", vivo

    repetido = writer(graph.driver).write(plan, apply_request(plan))
    assert repetido.outcome != OUTCOME_INCONSISTENT, (
        "un cierre reaplicado sobre conocimiento INTACTO se declara "
        f"INCONSISTENT: {repetido.codes}"
    )
    assert repetido.outcome == OUTCOME_APPLIED, repetido.codes


def test_y_la_garantia_de_R1_sigue_mordiendo_donde_SI_se_puede_medir(graph):
    """CONTROL POSITIVO del arreglo anterior.

    Excluir los cierres no puede haber apagado la comprobacion entera. Sobre
    una CREACION --que si estampa su clave-- borrar el conocimiento y dejar la
    marca tiene que seguir dando INCONSISTENT, que es exactamente el caso que
    R1 vino a cerrar.
    """
    graph.seed_entity("entity:a", version=1, state_hash=HASH_A["value"])
    graph.seed_entity("entity:b", version=1, state_hash=HASH_B["value"])
    plan = make_plan(
        [create_assertion("op:0001", "assertion:creada", "entity:a", "entity:b")]
    )
    primero = writer(graph.driver).write(plan, apply_request(plan))
    assert primero.outcome == OUTCOME_APPLIED, primero.codes

    # Se borra el CONOCIMIENTO y se deja la MARCA: el estado que mentia.
    graph.run(
        "MATCH (n:V3Assertion {assertion_id:'assertion:creada', workspace:$ws}) "
        "DETACH DELETE n",
        {"ws": WORKSPACE},
    )
    quedan = graph.run(
        "MATCH (n:V3Assertion {assertion_id:'assertion:creada', workspace:$ws}) "
        "RETURN count(n) AS c",
        {"ws": WORKSPACE},
    )
    assert quedan[0]["c"] == 0, "el escenario no quedo montado"
    marca = graph.run(
        "MATCH (op:V3AppliedOperation {workspace:$ws}) RETURN count(op) AS c",
        {"ws": WORKSPACE},
    )
    assert marca[0]["c"] > 0, "sin marca superviviente no hay nada que detectar"

    repetido = writer(graph.driver).write(plan, apply_request(plan))
    assert repetido.outcome == OUTCOME_INCONSISTENT, (
        "la garantia de R1 dejo de morder sobre creaciones: "
        f"{repetido.outcome} {repetido.codes}"
    )
    assert "EXEC_NOOP_WITHOUT_GRAPH_EVIDENCE" in repetido.codes


# --- la frontera del merge, medida -----------------------------------------
def test_el_filtro_de_ambito_tiene_UNA_sola_definicion():
    """La condicion del merge: `rollback_provenance` NO define su propio
    criterio de ambito, llama al de `rollback`. Se comprueba parseando el
    modulo, no contando apariciones en el texto."""
    from knowledge_v3.writer import rollback as R
    from knowledge_v3.writer import rollback_provenance as RP

    fuente = pathlib.Path(RP.__file__).read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    definidas = {
        n.name
        for n in arbol.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_scope" not in definidas, (
        "rollback_provenance vuelve a definir su propio filtro de ambito"
    )
    llamadas = {
        n.func.id
        for n in ast.walk(arbol)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "scope_clause" in llamadas, "ya no llama al filtro compartido"
    assert RP.scope_clause is R.scope_clause


def test_la_guarda_de_referencias_vivas_NO_se_absorbio_en_el_builder_de_R2():
    """R2 se nego con razon: la condicion de cero referencias vivas viaja
    DENTRO del propio DELETE. Sacarla fuera abriria una ventana entre contar y
    borrar. Se comprueba en el Cypher que se GENERA, no en el codigo fuente."""
    from knowledge_v3.writer import rollback_provenance as RP
    from knowledge_v3.writer.rollback import DELETABLE_NODE_LABELS

    cuerpo = RP.delete_orphan_evidence_query("ws", ["frag:1"], None).cypher
    assert "SUPPORTED_BY" in cuerpo and "DETACH DELETE" in cuerpo, cuerpo
    assert cuerpo.index("SUPPORTED_BY") < cuerpo.index("DETACH DELETE"), (
        "la guarda de referencias vivas ya no precede al borrado en la MISMA "
        "consulta: hay ventana entre contar y borrar"
    )
    # Y el builder de R2 sigue SIN conocer V3Evidence: su via de borrado por
    # clave durable no lleva guarda, y la evidencia la necesita.
    assert "V3Evidence" not in DELETABLE_NODE_LABELS, (
        "V3Evidence entro en el builder de R2, que no lleva guarda de "
        "referencias vivas"
    )
