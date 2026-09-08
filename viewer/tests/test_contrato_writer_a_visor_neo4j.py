# -*- coding: utf-8 -*-
"""CONTRATO PRODUCTOR -> CONSUMIDOR: el writer REAL puebla, el visor REAL lee.

EL HUECO QUE ESTO CIERRA
========================
``test_contrato_paneles_neo4j.py`` mide la frontera Neo4j -> proveedor ->
politica -> plantilla contra una base de verdad, y eso sigue valiendo. Pero la
base la siembra EL PROPIO CONSUMIDOR, con `CREATE (n:Entity $props)` escrito a
mano y con las claves ya correctas. Un dataset que el consumidor se prepara a
su medida no puede demostrar que el PRODUCTOR entrega lo que el consumidor
consume: demuestra que el consumidor sabe leerse a si mismo.

Y por ese hueco paso el defecto entero. Medido por un supervisor independiente
sobre un grafo real de 29 nodos con ``neo4j_connected: true``::

    /api/status  ->  nodes:0, relationships:0, workspaces:[]
    /api/entities, /api/graph, /api/sources, /api/search  ->  VACIOS
    contraste mecanico:   :Entity = 0        :V3Entity = 3

Dos universos que no se encontraban nunca::

    tests del viewer  ->  fixture propia  ->  :Entity    ->  PASS
    producto writer   ->  datos reales    ->  :V3Entity  ->  viewer VACIO

AQUI NO SE SIEMBRA NI UNA LINEA DE CYPHER
=========================================
Todo lo que este fichero mide lo escribio el producto por su ruta de operador:
``ingest_cli.run_ingest`` (fichero -> reconciliacion -> altas aprobadas ->
apply, CON procedencia) y un segundo plan V3 SELLADO por ``seal_plan`` que
aplica ``GraphWriter``. El unico Cypher que este fichero emite es de CENSO
(``MATCH ... RETURN count``) y el de la ABLACION calibrada de la seccion final,
que es la prueba de que esto puede ponerse rojo.

    plan V3 -> writer REAL -> Neo4j efimero -> provider REAL -> authz REAL -> API

LO QUE NO SE RELAJA
===================
La ultima linea es innegociable: LO NO AUTORIZADO SIGUE SIN VERSE. La
autorizacion del visor se decide por PROPIEDADES (``scope``, ``visibility``,
``known_by``, ``partida_id``, ``workspace``), no por la etiqueta del nodo, asi
que alinear la etiqueta no puede abrir nada -- y aqui se comprueba con un
lector LEGITIMO sin derechos, no razonando. El writer estampa
``visibility='secret'`` con ``visibility_source='default_fail_closed'``: un
lector sin ``can_view_secret`` no ve ni uno de estos nodos, y eso se exige.

Tampoco se abre la procedencia: ``V3Source`` / ``V3Episode`` / ``V3Evidence``
se escriben SIN ``visibility`` ni ``known_by`` y son fail-closed a proposito
(hay politica decidida para V3.2: ver una assertion NO da acceso a toda su
fuente). Que sigan fuera del alcance del visor es un INVARIANTE que este
fichero afirma, no una carencia que venga a tapar.

NUNCA PRODUCCION. Solo instancia efimera y local.
"""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

URI = os.environ.get("NEO4J_TEST_URI")
USER = os.environ.get("NEO4J_TEST_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD")

pytestmark = pytest.mark.skipif(
    not URI or not PASSWORD,
    reason="sin Neo4j efimero (define NEO4J_TEST_URI y NEO4J_TEST_PASSWORD)",
)

pytest.importorskip("jsonschema")
pytest.importorskip("neo4j")

#: Lista BLANCA. Esta suite BORRA nodos de su workspace; apuntarla a produccion
#: no puede depender de que nadie se equivoque de variable.
ANFITRIONES_EFIMEROS = frozenset({"localhost", "127.0.0.1", "::1", "neo4j"})


def _exigir_efimera(uri: str) -> None:
    host = (urlparse(uri).hostname or "").strip().lower()
    if host not in ANFITRIONES_EFIMEROS:
        raise RuntimeError(
            f"NEO4J_TEST_URI apunta a {host!r}, que no es una base efimera. "
            f"Anfitriones admitidos: {sorted(ANFITRIONES_EFIMEROS)}."
        )


RAIZ = pathlib.Path(__file__).resolve().parents[2]
EJEMPLOS = RAIZ / "examples" / "ingesta-v3"
FUENTE = EJEMPLOS / "nota-cofradia-de-ambar.md"
PERFIL = EJEMPLOS / "perfil-operador.json"
CATALOGO = EJEMPLOS / "catalogo-workspace.json"

#: NO SE ELIGE: lo declara el material de ejemplo del producto
#: (`examples/ingesta-v3/perfil-operador.json` y `catalogo-workspace.json`).
#: Inventarse otro aqui era el primer fallo de este fichero: `reconcile()`
#: recibia un workspace y la ingesta escribia en otro, las altas aprobadas no
#: casaban con ninguna operacion y el plan salia `PLAN_NO_OPERATIONS` -- es
#: decir, el arnes «pasaba» sin escribir nada. Se lee del perfil, y la fixture
#: comprueba que es el que la ingesta usa de verdad.
#:
#: Es disjunto del de `test_contrato_paneles_neo4j.py` (`contrato:paneles`),
#: que comparte instancia: ni este fichero toca su material ni al reves.
import json as _json_mod  # noqa: E402
WS = _json_mod.loads(
    (pathlib.Path(__file__).resolve().parents[2]
     / "examples" / "ingesta-v3" / "perfil-operador.json").read_text()
)["workspace"]
PASSWORD_USUARIO = "ContratoWriter_1234567890!"
PREDICADO = "ALLY_OF"

#: El plan CADUCA. Fijar la fecha a mano arma una bomba de reloj que estalla
#: el dia que `plan_ttl_seconds` la alcanza y se atribuye al entorno; se deriva
#: del reloj, que es lo unico que no caduca.
AHORA_DT = datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


AHORA = _iso(AHORA_DT)


# ===========================================================================
# 0. EL PRODUCTOR. Ni una linea de siembra: esto lo escribe el producto.
# ===========================================================================

@pytest.fixture(scope="module")
def driver():
    from neo4j import GraphDatabase

    _exigir_efimera(URI)
    drv = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    drv.verify_connectivity()
    yield drv
    # Se lleva SOLO lo suyo: el workspace propio y su procedencia.
    with drv.session() as s:
        s.run("MATCH (n) WHERE n.workspace = $ws DETACH DELETE n", {"ws": WS})
    drv.close()


def _ingesta(driver, *, altas=(), apply=False, env=None):
    from knowledge_v3.pipeline import ingest_cli

    return ingest_cli.run_ingest(
        FUENTE,
        profile_path=PERFIL,
        catalog_path=CATALOGO,
        driver=driver,
        now=AHORA,
        ingested_at=AHORA,
        approved_altas=list(altas),
        apply=apply,
        operator_id="contrato-writer",
        writer_env=env,
    )


def _plan_de_relacion(sujeto: dict, objeto: dict, snapshot: str) -> dict:
    """UN plan V3 sellado por el producto (`seal_plan`), no un CREATE a mano.

    Hace falta un plan aparte porque la arista entidad<->entidad la produce
    `LINK_EXISTING` / `PROJECT_RELATION` (`executor.RELATION_TYPES`), y
    `expected_version` / `expected_hash` de su objetivo solo existen DESPUES de
    que el writer haya creado la entidad. Los dos valores se leen del grafo, no
    se inventan: si no coincidieran, el control optimista rechazaria el plan y
    este fichero no mediria nada.
    """
    from knowledge_v3.contracts.base import seal_plan

    decision_id = "decision:contrato-rel"
    doc = {
        "contract_id": "graph-mutation-plan/v3-internal-v1",
        "contract_version": "1.0.0",
        "workspace": WS,
        "source_asset_id": "asset:contrato-writer-a-visor",
        "source_hash": {"algorithm": "sha256", "value": "d" * 64},
        "provider_trace": [
            {
                "step": "engine.plan",
                "provider": "local",
                "name": "s9k.knowledge_v3",
                "version": "3.0.0",
                "model": None,
                "produced": ["decisions", "mutation_operations"],
            }
        ],
        "produced_by_step": "engine.plan",
        "plan_id": "plan:contrato-writer:" + uuid.uuid4().hex[:8],
        "plan_hash": {"algorithm": "sha256", "value": "0" * 64},
        "snapshot_id": snapshot,
        "engine_version": "3.0.0",
        "ontology_version": "core-1.4.0",
        "game_profile": "generic",
        "collection_id": "collection:" + WS,
        "created_at": AHORA,
        "expires_at": _iso(AHORA_DT + timedelta(hours=2)),
        "decisions": [
            {
                "decision_id": decision_id,
                "claim_id": "claim:contrato-rel",
                "decision": "ACCEPT",
                "predicate": PREDICADO,
                "direction": "SUBJECT_TO_OBJECT",
                "subject_entity_id": sujeto["id"],
                "object_entity_id": objeto["id"],
                "epistemic_status": "ASSERTED",
                "negated": False,
                "confidence": 0.81,
                "reason_codes": ["LOCAL_APPROVED"],
                "evidence_fragment_ids": ["fragment:contrato-rel"],
            }
        ],
        "mutation_operations": [
            {
                "operation_id": "op-contrato-rel",
                "operation_type": "LINK_EXISTING",
                "decision_id": decision_id,
                "target_entity_id": sujeto["id"],
                "payload": {
                    "subject_entity_id": sujeto["id"],
                    "object_entity_id": objeto["id"],
                    "predicate": PREDICADO,
                },
                "expected_state": "WOULD_LINK_EXISTING",
                "expected_version": sujeto["version"],
                "expected_hash": {"algorithm": "sha256", "value": sujeto["state_hash"]},
                "evidence_fragment_ids": ["fragment:contrato-rel"],
                "idempotency_key": "idem:sha256:" + "1" * 64,
            }
        ],
        "local_approval": {
            "approved": True,
            "decision_hash": {"algorithm": "sha256", "value": "0" * 64},
            "validator_chain": [
                {"validator": "structural", "version": "3.0.0", "result": "PASS"},
                {"validator": "semantic", "version": "3.0.0", "result": "PASS"},
            ],
            "created_at": AHORA,
            "approved_by": {
                "provider": "local",
                "name": "s9k.engine.local",
                "version": "3.0.0",
            },
        },
    }
    return seal_plan(doc)


@pytest.fixture(scope="module")
def escrito_por_el_writer(driver):
    """LA PREMISA DE TODO EL FICHERO: el grafo lo puebla el writer REAL.

    Devuelve lo que el PRODUCTOR dice haber escrito. Todas las comprobaciones
    de mas abajo comparan la vista del consumidor contra ESTO, no contra una
    constante escrita a mano: asi «coinciden» significa que las dos mitades se
    encontraron, y no que dos literales del mismo fichero son iguales.
    """
    from knowledge_v3.pipeline import entity_decisions
    from knowledge_v3.writer import (
        InMemoryAppliedKeys,
        InMemoryAuditSink,
        OperatorRequest,
        bootstrap_writer_schema,
    )
    from knowledge_v3.writer.writer import GraphWriter

    with driver.session() as s:
        s.run("MATCH (n) WHERE n.workspace = $ws DETACH DELETE n", {"ws": WS})
    bootstrap_writer_schema(driver)

    # --- ruta de operador entera: fichero -> reconciliar -> aprobar -> apply
    primera = _ingesta(driver)
    ledger = entity_decisions.reconcile(
        resolutions=(
            primera["candidates"]["link_existing"]
            + primera["candidates"]["create_entity"]
        ),
        graph_entity_ids=[],
        workspace=WS,
        source_path=str(FUENTE),
        names_by_mention={},
        catalog_by_entity={},
    )
    assert ledger.altas, "sin altas pendientes no hay alta que aprobar"
    aprobado = entity_decisions.approve(
        ledger, [d.entity_id for d in ledger.altas], reviewer="contrato-writer", at=AHORA
    )
    altas = entity_decisions.approved_snapshot_entities(aprobado)
    assert altas, "sin altas aprobadas el plan no traeria CREATE_ENTITY"
    informe = _ingesta(
        driver,
        altas=altas,
        apply=True,
        env={"S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": WS},
    )
    assert informe["write"]["outcome"] == "APPLIED", informe["write"]
    assert informe["write"]["applied_operations"] > 0, informe["write"]

    # --- segundo plan: la ARISTA entidad<->entidad, por la ruta real
    with driver.session() as s:
        creadas = [
            r.data()
            for r in s.run(
                "MATCH (n:V3Entity {workspace:$ws}) "
                "RETURN n.entity_id AS id, n.version AS version, "
                "n.state_hash AS state_hash, n.canonical_name AS canonical_name, "
                "n.source_document AS source_document ORDER BY id",
                {"ws": WS},
            )
        ]
    assert len(creadas) >= 2, (
        f"el writer dijo APPLIED y dejo {len(creadas)} entidades: sin dos extremos "
        "no hay arista que enlazar y este fichero no puede medir /api/graph"
    )
    snapshot = "snapshot:sha256:" + "e" * 64
    plan = _plan_de_relacion(creadas[0], creadas[1], snapshot)
    escritor = GraphWriter(
        workspace=WS,
        driver=driver,
        audit=InMemoryAuditSink(),
        applied_keys=InMemoryAppliedKeys(),
    )
    resultado = escritor.write(
        plan,
        OperatorRequest(
            apply=True,
            operator_id="contrato-writer",
            workspace=WS,
            expected_plan_hash=plan["plan_hash"]["value"],
            max_operations=50,
            current_snapshot_id=snapshot,
            env={"S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": WS},
        ),
    )
    assert resultado.outcome == "APPLIED", (
        f"el plan de relacion no se aplico: {resultado.outcome} "
        f"{getattr(resultado, 'rejections', None)}"
    )

    return {
        "entidades": {c["id"] for c in creadas},
        "canonical_names": {c["canonical_name"] for c in creadas},
        "fuentes": {c["source_document"] for c in creadas},
        "arista": (creadas[0]["id"], PREDICADO, creadas[1]["id"]),
    }


# ===========================================================================
# 1. SUELO. Que el arnes no pueda pasar en vacio ni sobre material propio.
# ===========================================================================

def test_el_grafo_lo_poblo_el_writer_y_las_dos_etiquetas_coinciden(
        driver, escrito_por_el_writer):
    """UNA consulta por cada cosa contada. Dos `MATCH` sueltos dan producto
    cartesiano y a menudo cero filas que parecen un verde.

    Y el conjunto medido NO puede estar vacio por construccion: es exactamente
    el defecto que se persigue.
    """
    with driver.session() as s:
        v3 = s.run("MATCH (n:V3Entity {workspace:$ws}) RETURN count(n) AS c",
                   {"ws": WS}).single()["c"]
        publicas = s.run("MATCH (n:Entity {workspace:$ws}) RETURN count(n) AS c",
                         {"ws": WS}).single()["c"]
        ambas = s.run(
            "MATCH (n:Entity {workspace:$ws}) WHERE n:V3Entity RETURN count(n) AS c",
            {"ws": WS}).single()["c"]

    assert v3 > 0, "el writer no dejo ni una entidad: el arnes esta midiendo el vacio"
    assert publicas == v3 == ambas, (
        f":V3Entity={v3} pero :Entity={publicas} (con las dos: {ambas}). Las dos "
        "superficies han vuelto a separarse: el visor leera un universo que el "
        "writer no alimenta."
    )
    assert escrito_por_el_writer["entidades"], "el productor no declaro nada"


def test_la_procedencia_del_writer_NO_entra_en_la_superficie_publica(driver,
                                                                     escrito_por_el_writer):
    """INVARIANTE, no carencia. `V3Source`/`V3Episode`/`V3Evidence` se escriben
    sin `visibility` ni `known_by`: son fail-closed a proposito. Ninguno puede
    llevar la etiqueta publica, o el visor los alcanzaria y «ver una assertion»
    pasaria a dar acceso a toda su fuente.
    """
    with driver.session() as s:
        for etiqueta in ("V3Source", "V3Episode", "V3Evidence", "V3Assertion"):
            total = s.run(
                f"MATCH (n:{etiqueta} {{workspace:$ws}}) RETURN count(n) AS c",
                {"ws": WS}).single()["c"]
            colados = s.run(
                f"MATCH (n:{etiqueta} {{workspace:$ws}}) WHERE n:Entity "
                "RETURN count(n) AS c", {"ws": WS}).single()["c"]
            if etiqueta in ("V3Source", "V3Episode", "V3Evidence"):
                assert total > 0, (
                    f"no hay ni un nodo :{etiqueta}: este invariante no esta "
                    "midiendo nada"
                )
            assert colados == 0, (
                f"{colados} nodos :{etiqueta} llevan la etiqueta publica :Entity. "
                "La procedencia ha quedado al alcance del visor."
            )


# ===========================================================================
# 2. EL CONSUMIDOR REAL, POR HTTP, CON LA AUTORIZACION DE VERDAD
# ===========================================================================

@pytest.fixture
def app_real():
    from app.main import app
    return app


@pytest.fixture(autouse=True)
def entorno(tmp_path):
    from app.auth.config import get_auth_settings
    from app.config import get_settings

    claves = ["S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_DEFAULT_WORKSPACE"]
    previos = {k: os.environ.get(k) for k in claves}

    os.environ["S9K_DEFAULT_WORKSPACE"] = WS
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(tmp_path / "auth.db")
    get_settings.cache_clear()
    get_auth_settings.cache_clear()

    from app.auth import db as auth_db
    auth_db.ensure_migrated(Path(os.environ["S9K_AUTH_DB_PATH"]))

    yield Path(os.environ["S9K_AUTH_DB_PATH"])

    for k, v in previos.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    get_settings.cache_clear()
    get_auth_settings.cache_clear()


@pytest.fixture
def proveedor(app_real, escrito_por_el_writer):
    """El `Neo4jGraphProvider` REAL como proveedor BASE.

    Se sustituye el BASE y no el filtrado: la cadena entera
    (`get_filtered_provider` -> `build_viewer_context` -> `PolicyFilteredProvider`
    -> `VisibilityPolicy`) se atraviesa en cada peticion.
    """
    import app.deps as deps
    from app.providers.neo4j_provider import Neo4jGraphProvider

    _exigir_efimera(URI)
    prov = Neo4jGraphProvider(URI, USER, PASSWORD)
    app_real.dependency_overrides[deps.get_provider] = lambda: prov
    yield prov
    app_real.dependency_overrides.pop(deps.get_provider, None)
    prov._driver.close()


def usuario(db_path: Path, nombre: str, rol: str) -> str:
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db.get_conn(db_path) as conn:
        u = auth_db.create_user(conn, username=nombre, display_name=nombre.title(),
                                password_hash=hash_password(PASSWORD_USUARIO), role=rol)
        auth_db.update_user(conn, u.id, must_change_password=False)
        u = auth_db.get_user_by_id(conn, u.id)
        token, _ = create_session(conn, u)
    return token


def cliente(app, cookie: str) -> TestClient:
    from app.auth.config import get_auth_settings

    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, cookie)
    return c


def _autorizado(app_real, entorno, nombre="autorizado") -> TestClient:
    """Lector CON derecho sobre este material.

    El writer estampa `visibility='secret'` (`visibility_source =
    'default_fail_closed'`), asi que quien lo ve es quien tiene
    `can_view_secret`. No se elige el rol por comodidad: se elige el UNICO que
    la politica admite para este material, y la seccion 3 comprueba que los
    demas NO lo ven.
    """
    return cliente(app_real, usuario(entorno, nombre, "admin"))


def _nombres_encontrados(datos) -> set:
    """Los IDs que /api/search devuelve, NO la respuesta cruda.

    Mirar `str(datos)` era un falso positivo: la respuesta hace ECO del termino
    buscado, asi que la aguja aparecia en el texto aunque la lista de
    resultados viniera vacia -- una comprobacion que no podia ponerse roja.
    """
    if not isinstance(datos, dict):
        return set()
    filas = datos.get("results") or datos.get("items") or datos.get("entities") or []
    return {f.get("id") or f.get("entity_id") for f in filas if isinstance(f, dict)}


def _json(r):
    assert r.status_code == 200, f"{r.request.url} respondio {r.status_code}"
    return r.json()


def test_las_entidades_que_creo_el_writer_llegan_a_api_entities(
        app_real, proveedor, entorno, escrito_por_el_writer):
    c = _autorizado(app_real, entorno)
    datos = _json(c.get("/api/entities", params={"workspace": WS}))
    vistos = {i.get("id") for i in datos.get("items", [])}
    esperados = escrito_por_el_writer["entidades"]
    assert esperados, "el productor no declaro entidades: nada que comparar"
    assert vistos == esperados, (
        f"el writer escribio {sorted(esperados)} y /api/entities entrega "
        f"{sorted(vistos)}"
    )


def test_la_relacion_que_creo_el_writer_llega_a_api_graph(
        app_real, proveedor, entorno, escrito_por_el_writer):
    c = _autorizado(app_real, entorno)
    datos = _json(c.get("/api/graph", params={"workspace": WS, "limit": 2000}))
    sujeto, predicado, objeto = escrito_por_el_writer["arista"]

    nodos = {n.get("id") for n in datos.get("nodes", [])}
    assert escrito_por_el_writer["entidades"] <= nodos, (
        f"/api/graph no entrega los extremos: {sorted(nodos)}"
    )
    aristas = datos.get("edges", [])
    assert aristas, "/api/graph no entrega ni una arista y el writer aplico una"
    # El serializador publica los extremos como `from`/`to`
    # (`serializers.serialize_edge`), con respaldo `source`/`target`.
    def _extremos(e):
        return (e.get("from") or e.get("source"), e.get("to") or e.get("target"))

    assert any(_extremos(e) == (sujeto, objeto) for e in aristas), (
        f"la arista {sujeto} -[{predicado}]-> {objeto} que aplico el writer no "
        f"aparece en /api/graph: {aristas}"
    )


def test_la_fuente_que_creo_el_writer_llega_a_api_sources(
        app_real, proveedor, entorno, escrito_por_el_writer):
    c = _autorizado(app_real, entorno)
    datos = _json(c.get("/api/sources", params={"workspace": WS}))
    asas = {f["source_id"] for f in datos.get("sources", [])}
    esperadas = {f for f in escrito_por_el_writer["fuentes"] if f}
    assert esperadas, "el writer no publico ninguna fuente en sus entidades"
    assert asas == esperadas, (
        f"el writer publico {sorted(esperadas)} y /api/sources entrega {sorted(asas)}"
    )
    # El asa es ESTABLE y NO ES LA RUTA: misma regla que ya exige
    # `test_el_asa_de_una_fuente_es_estable_y_no_es_la_ruta`.
    for asa in asas:
        assert not asa.startswith("/") and "://" not in asa, (
            f"/api/sources publico una ruta de servidor como asa: {asa!r}"
        )


def test_api_status_cuenta_lo_que_el_writer_escribio(
        app_real, proveedor, entorno, escrito_por_el_writer, driver):
    c = _autorizado(app_real, entorno)
    datos = _json(c.get("/api/status"))
    assert WS in (datos.get("workspaces") or []), (
        f"el workspace del writer no aparece en /api/status: {datos.get('workspaces')}"
    )
    assert datos.get("nodes", 0) >= len(escrito_por_el_writer["entidades"]), (
        f"/api/status cuenta {datos.get('nodes')} nodos y el writer escribio "
        f"{len(escrito_por_el_writer['entidades'])}"
    )
    assert datos.get("relationships", 0) >= 1, (
        f"/api/status cuenta {datos.get('relationships')} relaciones y el writer "
        "aplico una"
    )


def test_la_busqueda_encuentra_lo_que_el_writer_nombro(
        app_real, proveedor, entorno, escrito_por_el_writer):
    """`search()` filtra por `canonical_name`/`display_name`/`description`.

    El writer escribe el nombre como `name`; sin la proyeccion publica la
    busqueda no encuentra NADA aunque la entidad este entregada por
    /api/entities -- un vacio que se leeria como «no hay material».
    """
    nombres = {n for n in escrito_por_el_writer["canonical_names"] if n}
    assert nombres, "las entidades del writer llegaron sin nombre publico"
    aguja = sorted(nombres)[0]
    c = _autorizado(app_real, entorno)
    datos = _json(c.get("/api/search", params={"workspace": WS, "q": aguja}))
    assert _nombres_encontrados(datos), (
        f"/api/search no encuentra {aguja!r}: {str(datos)[:400]}"
    )


# ===========================================================================
# 3. LA LINEA INNEGOCIABLE: lo no autorizado SIGUE sin verse
# ===========================================================================

@pytest.mark.parametrize("rol", ["reviewer", "viewer"])
def test_un_lector_legitimo_sin_derechos_NO_ve_el_material_del_writer(
        app_real, proveedor, entorno, escrito_por_el_writer, rol):
    """Lectores REALES, autenticados y legitimos, sin `can_view_secret`.

    Si alinear la etiqueta hubiera abierto algo, se veria AQUI: es el mismo
    material, la misma base y la misma peticion que la seccion 2, cambiando
    solo quien pregunta.
    """
    c = cliente(app_real, usuario(entorno, f"sin_derechos_{rol}", rol))

    entidades = c.get("/api/entities", params={"workspace": WS})
    assert entidades.status_code in (200, 403), entidades.status_code
    if entidades.status_code == 200:
        vistos = {i.get("id") for i in entidades.json().get("items", [])}
        assert not (vistos & escrito_por_el_writer["entidades"]), (
            f"FUGA: el rol {rol} ve {sorted(vistos & escrito_por_el_writer['entidades'])}"
        )

    grafo = c.get("/api/graph", params={"workspace": WS, "limit": 2000})
    if grafo.status_code == 200:
        datos = grafo.json()
        nodos = {n.get("id") for n in datos.get("nodes", [])}
        assert not (nodos & escrito_por_el_writer["entidades"]), (
            f"FUGA por /api/graph: el rol {rol} ve {sorted(nodos)}"
        )
        assert not datos.get("edges"), (
            f"FUGA por /api/graph: el rol {rol} ve aristas {datos.get('edges')}"
        )

    fuentes = c.get("/api/sources", params={"workspace": WS})
    if fuentes.status_code == 200:
        asas = {f["source_id"] for f in fuentes.json().get("sources", [])}
        assert not (asas & {f for f in escrito_por_el_writer["fuentes"] if f}), (
            f"FUGA por /api/sources: el rol {rol} ve {sorted(asas)}"
        )

    estado = c.get("/api/status")
    if estado.status_code == 200:
        assert estado.json().get("nodes", 0) == 0, (
            f"FUGA por /api/status: el rol {rol} cuenta "
            f"{estado.json().get('nodes')} nodos"
        )


def test_el_control_de_autorizacion_COLAPSA(app_real, proveedor, entorno,
                                            escrito_por_el_writer):
    """CALIBRACION del test de arriba. Sin esta mitad, «el rol no ve nada»
    podria significar «la base esta vacia» o «el arnes no llega a la API», y el
    test de fuga saldria verde para siempre por el motivo equivocado.
    """
    autorizado = _autorizado(app_real, entorno, "colapso_ok")
    vistos = {
        i.get("id")
        for i in _json(autorizado.get("/api/entities", params={"workspace": WS})).get("items", [])
    }
    assert vistos & escrito_por_el_writer["entidades"], (
        "ni el lector autorizado ve nada: la comprobacion de fuga no distingue "
        "«denegado» de «vacio»"
    )


# ===========================================================================
# 4. CONTROL NEGATIVO: romper la correspondencia productor-consumidor
#    tiene que poner esto ROJO
# ===========================================================================

def _observacion_del_autorizado(app_real, entorno, nombre) -> tuple:
    c = _autorizado(app_real, entorno, nombre)
    ent = _json(c.get("/api/entities", params={"workspace": WS}))
    gra = _json(c.get("/api/graph", params={"workspace": WS, "limit": 2000}))
    src = _json(c.get("/api/sources", params={"workspace": WS}))
    return (
        len(ent.get("items", [])),
        len(gra.get("nodes", [])),
        len(gra.get("edges", [])),
        len(src.get("sources", [])),
    )


def test_romper_la_correspondencia_PRODUCTOR_CONSUMIDOR_pone_esto_ROJO(
        app_real, proveedor, entorno, escrito_por_el_writer, driver):
    """ESTE ES EL CONTROL QUE NO EXISTIA.

    El defecto vivio con 8262 pruebas en verde porque ninguna podia ponerse
    roja: el visor devolvia vacio con 29 nodos reales delante. Aqui se
    REINTRODUCE el defecto exacto --se le quita a los nodos del writer la
    etiqueta que el consumidor lee-- y se exige que la observacion CAMBIE.

    Una comprobacion que no cambia al destruir lo que afirma cubrir no cubre
    nada, y entonces este test falla y hay que arreglar la comprobacion.

    Se restaura SIEMPRE, y la restauracion se VERIFICA contando en Neo4j: dejar
    la base mutilada envenenaria al resto del fichero con un fallo que parece
    de otro sitio.
    """
    antes = _observacion_del_autorizado(app_real, entorno, "neg_antes")
    assert all(v > 0 for v in antes), (
        f"el arnes ya observa vacio antes de romper nada: {antes}. Este control "
        "no puede demostrar que algo se pone rojo si nunca estuvo verde."
    )

    try:
        with driver.session() as s:
            quitados = s.run(
                "MATCH (n:Entity {workspace:$ws}) REMOVE n:Entity "
                "RETURN count(n) AS c", {"ws": WS}).single()["c"]
            assert quitados > 0, "la ablacion no toco ni un nodo: no ejerce nada"
            restantes = s.run(
                "MATCH (n:Entity {workspace:$ws}) RETURN count(n) AS c",
                {"ws": WS}).single()["c"]
            assert restantes == 0, (
                f"la ablacion dejo {restantes} nodos con la etiqueta publica"
            )

        despues = _observacion_del_autorizado(app_real, entorno, "neg_despues")
        assert despues == (0, 0, 0, 0), (
            f"SE QUITO la etiqueta que el consumidor lee y el visor sigue "
            f"entregando {despues}. La observacion no depende de lo que dice "
            "medir: esta comprobacion no puede ponerse roja y no vale."
        )
        assert despues != antes, "la ablacion no cambio nada observable"
    finally:
        with driver.session() as s:
            s.run("MATCH (n:V3Entity {workspace:$ws}) SET n:Entity", {"ws": WS})
            recuperados = s.run(
                "MATCH (n:Entity {workspace:$ws}) RETURN count(n) AS c",
                {"ws": WS}).single()["c"]
        assert recuperados == antes[0], (
            f"la restauracion dejo {recuperados} nodos publicos y habia "
            f"{antes[0]}: la base queda distinta de como se encontro"
        )

    # Y el mundo vuelve a estar como estaba, medido por la MISMA observacion.
    assert _observacion_del_autorizado(app_real, entorno, "neg_final") == antes


def test_quitar_la_proyeccion_del_nombre_deja_la_busqueda_CIEGA(
        app_real, proveedor, entorno, escrito_por_el_writer, driver):
    """Segunda mitad del control negativo: la ETIQUETA no es lo unico que hacia
    falta. El vocabulario publico tambien, y su ausencia es SILENCIOSA -- la
    entidad se lista y la busqueda no la encuentra.
    """
    nombres = {n for n in escrito_por_el_writer["canonical_names"] if n}
    aguja = sorted(nombres)[0]
    c = _autorizado(app_real, entorno, "ciega")

    antes = _nombres_encontrados(
        _json(c.get("/api/search", params={"workspace": WS, "q": aguja})))
    assert antes, "la busqueda ya estaba ciega antes de romper nada"

    try:
        with driver.session() as s:
            tocados = s.run(
                "MATCH (n:Entity {workspace:$ws}) REMOVE n.canonical_name "
                "RETURN count(n) AS c", {"ws": WS}).single()["c"]
            assert tocados > 0, "la ablacion no toco ni un nodo"
        despues = _nombres_encontrados(
            _json(c.get("/api/search", params={"workspace": WS, "q": aguja})))
        assert not despues, (
            "se borro `canonical_name` y la busqueda sigue encontrando el nombre: "
            "esta comprobacion no mide el campo que dice medir"
        )
    finally:
        with driver.session() as s:
            s.run(
                "MATCH (n:Entity {workspace:$ws}) WHERE n.canonical_name IS NULL "
                "SET n.canonical_name = n.name", {"ws": WS})
    assert _nombres_encontrados(
        _json(c.get("/api/search", params={"workspace": WS, "q": aguja}))
    ) == antes, "la restauracion no devolvio la busqueda a su estado"
