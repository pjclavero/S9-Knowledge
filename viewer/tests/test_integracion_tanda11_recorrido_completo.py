# -*- coding: utf-8 -*-
"""INTEGRACION TANDA 11 -- el recorrido entero, y lo que EL VISOR ve en cada paso.

POR QUE ESTE FICHERO EXISTE
===========================
Los dos carriles de la tanda 11 demuestran mitades distintas y ninguno cruza
la costura:

* 11A recorre ``apply -> repeat -> rollback -> re-apply`` contra Neo4j real,
  pero A NIVEL DE GRAFO: su plan es sintetico y el visor no aparece.
* 11B lleva el material del writer REAL hasta la API del visor, pero NO recorre
  los cuatro pasos: mide un estado, no una historia. Y para tener una arista
  entidad->entidad monta un SEGUNDO plan (``LINK_EXISTING``), porque cuando se
  escribio, el primer apply no la materializaba.

Lo que ninguno responde es la pregunta de la integracion: **cuando el operador
deshace y rehace, ¿el visor lo refleja?** Un rollback que limpia el grafo pero
deja al visor enseñando lo borrado no es un rollback: es una mentira con dos
sistemas de acuerdo en silencio.

    Neo4j vacio -> schema init -> fuente real -> review/promocion
       -> UN SOLO apply -> relacion YA presente + procedencia + EL VISOR LA VE
    repeat apply -> REJECTED [PLAN_NOT_APPROVED, PLAN_NO_OPERATIONS]
                 -> cero escrituras -> visor IDENTICO
    rollback     -> el conocimiento desaparece -> EL VISOR LO REFLEJA -> 0 marcas
    re-apply     -> el conocimiento vuelve     -> EL VISOR VUELVE A VERLO

LA COSTURA, MEDIDA Y NO LEIDA
=============================
11A avisa de que la forma del plan cambia y de que la arista existe YA tras el
primer apply. Aqui no se acepta de palabra: el paso 1 CUENTA las aristas
entidad->entidad despues de UN unico apply por la ruta de operador, y exige que
sean > 0 sin que este fichero haya emitido un solo plan de relacion aparte.

11B avisa por su lado de que sus nodos llevan AHORA DOS etiquetas y de que un
censo de residuos que cuente por ``:Entity`` vera tambien los del writer. El
paso 3 cuenta las marcas ``V3AppliedOperation`` y exige CERO.

NI UNA LINEA DE CYPHER DE ESCRITURA
===================================
Todo lo escribe el producto por la ruta de operador: ``ingest_cli.run_ingest``
(fichero -> reconciliar -> aprobar -> apply, con procedencia) y
``execute_rollback`` para deshacer. El unico Cypher de este fichero es de CENSO
(``MATCH ... RETURN count``) y el del borrado de su propio workspace al acabar.

UNA CONSULTA POR CADA COSA CONTADA. Dos ``MATCH`` sueltos en la misma consulta
dan producto cartesiano y a menudo cero filas que parecen un verde.

LO NO AUTORIZADO SIGUE SIN VERSE, EN CADA PASO
==============================================
No basta con mirar al lector con derechos. En CADA uno de los cuatro pasos se
comprueba tambien que un lector legitimo SIN derechos no ve nada -- y, con el
control de colapso que dejo 11B, que ese cero es de AUTORIZACION y no de que la
base este vacia: ``«no veo nada»`` y ``«no hay nada»`` son indistinguibles
desde fuera, y sin distinguirlos un rollback exitoso y una politica rota dan la
misma respuesta.

NUNCA PRODUCCION. Solo instancia efimera y local.
"""
from __future__ import annotations

import json
import os
import pathlib
from datetime import datetime, timezone
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

ANFITRIONES_EFIMEROS = frozenset({"localhost", "127.0.0.1", "::1", "neo4j"})


def _exigir_efimera(uri: str) -> None:
    """Lista BLANCA. Esta suite BORRA nodos: apuntarla a produccion no puede
    depender de que nadie se equivoque de variable."""
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

#: NO SE ELIGE: lo declara el material de ejemplo del producto. Inventarse otro
#: workspace hace que `reconcile()` y la ingesta trabajen en sitios distintos y
#: el plan salga vacio -- un arnes que «pasa» sin escribir nada.
WS = json.loads(PERFIL.read_text())["workspace"]
OPERADOR = "integracion-tanda11"
PASSWORD_USUARIO = "IntegracionTanda11_1234567890!"

#: El plan CADUCA. Fijar la fecha a mano arma una bomba de reloj; se deriva del
#: reloj, que es lo unico que no caduca.
AHORA = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ===========================================================================
# CENSO. Una consulta por cada cosa contada, y ninguna puede salir vacia por
# construccion sin que se note.
# ===========================================================================

#: `marcas` es la linea que 11B señalo: si el censo contase por `:Entity`
#: mezclaria las marcas del writer con las entidades publicas.
CONSULTAS_CENSO = {
    "nodos": "MATCH (n) RETURN count(n) AS c",
    "entidades_v3": "MATCH (n:V3Entity {workspace:$ws}) RETURN count(n) AS c",
    "entidades_publicas": "MATCH (n:Entity {workspace:$ws}) RETURN count(n) AS c",
    "entidades_ambas": (
        "MATCH (n:Entity {workspace:$ws}) WHERE n:V3Entity RETURN count(n) AS c"
    ),
    "aserciones": "MATCH (n:V3Assertion {workspace:$ws}) RETURN count(n) AS c",
    "marcas": "MATCH (n:V3AppliedOperation) RETURN count(n) AS c",
    "fuentes": "MATCH (n:V3Source {workspace:$ws}) RETURN count(n) AS c",
    "episodios": "MATCH (n:V3Episode {workspace:$ws}) RETURN count(n) AS c",
    "evidencias": "MATCH (n:V3Evidence {workspace:$ws}) RETURN count(n) AS c",
    "aristas_ent_ent": (
        "MATCH (:V3Entity {workspace:$ws})-[r]->(:V3Entity {workspace:$ws}) "
        "RETURN count(r) AS c"
    ),
}


def censo(driver) -> dict:
    salida = {}
    with driver.session() as s:
        for nombre, consulta in CONSULTAS_CENSO.items():
            fila = s.run(consulta, {"ws": WS}).single()
            assert fila is not None, f"el censo de {nombre!r} no devolvio fila"
            salida[nombre] = fila["c"]
    return salida


def aristas(driver) -> list:
    """Por IDENTIDAD DURABLE (`entity_id`), nunca por `elementId` ni por
    posicion: el `elementId` cambia en cada re-apply y comparar por el haria
    fallar el paso 4 por una razon que no es la que se mide."""
    with driver.session() as s:
        return [
            (r["tipo"], r["desde"], r["hasta"])
            for r in s.run(
                "MATCH (a:V3Entity {workspace:$ws})-[r]->(b:V3Entity {workspace:$ws}) "
                "RETURN type(r) AS tipo, a.entity_id AS desde, b.entity_id AS hasta "
                "ORDER BY tipo, desde, hasta",
                {"ws": WS},
            )
        ]


def seguimiento(driver) -> list:
    """Tabla de seguimiento de valores, leida del grafo.

    `partida_id`/`known_from_session` van a `None` A PROPOSITO para material de
    `scope='juego'`: el contrato de visibilidad EXIGE `known_from_session` solo
    para contenido de partida (`writer/visibility.py`). Un `None` aqui es un
    valor medido y correcto, no una medicion que falta -- y por eso se afirma
    que `scope` SI es no nulo y distinto de `partida`.
    """
    with driver.session() as s:
        return [
            dict(r)
            for r in s.run(
                "MATCH (n:V3Entity {workspace:$ws}) RETURN n.entity_id AS entity_id, "
                "n.entity_type AS entity_type, n.scope AS scope, "
                "n.partida_id AS partida_id, n.known_from_session AS known_from_session, "
                "n.visibility AS visibility, n.visibility_source AS visibility_source, "
                "n.evidence_fragment_ids AS evidence_fragment_ids, "
                "n.written_by_operator AS operator, "
                "n.written_by_plan_hash AS plan_hash, n.version AS version "
                "ORDER BY n.entity_id",
                {"ws": WS},
            )
        ]


# ===========================================================================
# EL PRODUCTOR: la ruta de operador entera. Ni una linea de siembra.
# ===========================================================================

@pytest.fixture(scope="module")
def driver():
    from neo4j import GraphDatabase

    _exigir_efimera(URI)
    drv = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    drv.verify_connectivity()
    # Se lleva SOLO lo suyo, antes y despues: comparte instancia con las otras
    # suites de contrato y no puede pisarles el material.
    with drv.session() as s:
        s.run("MATCH (n) WHERE n.workspace = $ws DETACH DELETE n", {"ws": WS})
    yield drv
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
        operator_id=OPERADOR,
        writer_env=env,
    )


def _altas_aprobadas(driver):
    """REVIEW / PROMOCION por la ruta del producto: reconciliar -> aprobar."""
    from knowledge_v3.pipeline import entity_decisions

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
    assert ledger.altas, "sin altas pendientes no hay nada que promocionar"
    aprobado = entity_decisions.approve(
        ledger, [d.entity_id for d in ledger.altas], reviewer=OPERADOR, at=AHORA
    )
    altas = entity_decisions.approved_snapshot_entities(aprobado)
    assert altas, "sin altas aprobadas el plan no traeria CREATE_ENTITY"
    return altas


def _aplicar(driver, altas):
    return _ingesta(
        driver,
        altas=altas,
        apply=True,
        env={"S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": WS},
    )


def _rehidratar_rollback(doc: dict):
    """El informe entrega la poliza como DICCIONARIO y `execute_rollback` pide
    el objeto. Se reconstruye con las dataclases DEL PRODUCTO, no con una copia
    local del formato."""
    from knowledge_v3.writer.rollback import (
        APPLY_ID_FIELD,
        OWNERSHIP_ID_FIELD,
        RollbackDocument,
        RollbackInstruction,
    )

    instrucciones = []
    for i in doc.get("instructions") or []:
        campos = {f.name for f in RollbackInstruction.__dataclass_fields__.values()}
        instrucciones.append(
            RollbackInstruction(**{k: v for k, v in i.items() if k in campos})
        )
    return RollbackDocument(
        workspace=doc["workspace"],
        snapshot_id=doc["snapshot_id"],
        plan_hash=doc["plan_hash"],
        apply_id=doc.get(APPLY_ID_FIELD),
        ownership_id=doc.get(OWNERSHIP_ID_FIELD),
        instructions=instrucciones,
        unrecoverable=list(doc.get("unrecoverable") or []),
    )


# ===========================================================================
# EL CONSUMIDOR: el visor REAL, por HTTP, con la autorizacion de verdad.
# ===========================================================================

@pytest.fixture
def app_real():
    from app.main import app

    return app


@pytest.fixture
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
def proveedor(app_real):
    """El `Neo4jGraphProvider` REAL como proveedor BASE: se sustituye el base y
    no el filtrado, asi que la cadena entera (`get_filtered_provider` ->
    `build_viewer_context` -> `PolicyFilteredProvider` -> `VisibilityPolicy`)
    se atraviesa en cada peticion."""
    import app.deps as deps
    from app.providers.neo4j_provider import Neo4jGraphProvider

    _exigir_efimera(URI)
    prov = Neo4jGraphProvider(URI, USER, PASSWORD)
    app_real.dependency_overrides[deps.get_provider] = lambda: prov
    yield prov
    app_real.dependency_overrides.pop(deps.get_provider, None)
    prov._driver.close()


def _usuario(db_path: Path, nombre: str, rol: str) -> str:
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db.get_conn(db_path) as conn:
        u = auth_db.create_user(
            conn,
            username=nombre,
            display_name=nombre.title(),
            password_hash=hash_password(PASSWORD_USUARIO),
            role=rol,
        )
        auth_db.update_user(conn, u.id, must_change_password=False)
        u = auth_db.get_user_by_id(conn, u.id)
        token, _ = create_session(conn, u)
    return token


def _cliente(app, cookie: str) -> TestClient:
    from app.auth.config import get_auth_settings

    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, cookie)
    return c


def vista(cliente) -> dict:
    """LO QUE EL VISOR VE, por sus rutas publicas.

    Se recogen los CODIGOS ademas de los cuerpos: un 403 y un 200 con lista
    vacia son estados distintos y confundirlos es justo el fallo que el control
    de colapso persigue.
    """
    def pedir(ruta, params):
        r = cliente.get(ruta, params=params)
        cuerpo = r.json() if r.status_code == 200 else None
        return r.status_code, cuerpo

    ce, entidades = pedir("/api/entities", {"workspace": WS})
    cg, grafo = pedir("/api/graph", {"workspace": WS, "limit": 2000})
    cf, fuentes = pedir("/api/sources", {"workspace": WS})
    cs, estado = pedir("/api/status", {})

    def extremos(e):
        # El serializador publica `from`/`to`, con respaldo `source`/`target`.
        return (e.get("from") or e.get("source"), e.get("to") or e.get("target"))

    return {
        "codigos": {"entities": ce, "graph": cg, "sources": cf, "status": cs},
        "entidades": sorted(
            i.get("id") for i in ((entidades or {}).get("items") or [])
        ),
        "nodos_grafo": sorted(n.get("id") for n in ((grafo or {}).get("nodes") or [])),
        "aristas_grafo": sorted(
            extremos(e) for e in ((grafo or {}).get("edges") or [])
        ),
        "fuentes": sorted(
            f.get("source_id") for f in ((fuentes or {}).get("sources") or [])
        ),
    }


def _no_ve_nada(v: dict) -> bool:
    """Sin derechos: o le cierran la puerta (403) o le entregan el vacio."""
    return not v["entidades"] and not v["nodos_grafo"] and not v["aristas_grafo"]


# ===========================================================================
# EL RECORRIDO. Un solo test porque es UNA historia: cada paso solo significa
# algo respecto del anterior, y trocearlo en cuatro tests independientes
# obligaria a rehacer el estado y dejaria de medir la transicion.
# ===========================================================================

@pytest.fixture
def recorrido(driver, app_real, proveedor, entorno):
    """Ejecuta los cuatro pasos y DEVUELVE LA EVIDENCIA de cada uno.

    Los `assert` fuertes viven en los tests de abajo; aqui solo se exige lo
    imprescindible para que un paso posterior signifique algo.
    """
    from knowledge_v3.writer import bootstrap_writer_schema
    from knowledge_v3.writer.rollback_provenance import execute_rollback

    admin = _cliente(app_real, _usuario(entorno, "t11-admin", "admin"))
    revisor = _cliente(app_real, _usuario(entorno, "t11-revisor", "reviewer"))
    lector = _cliente(app_real, _usuario(entorno, "t11-lector", "viewer"))

    pasos = {}

    def registrar(nombre):
        pasos[nombre] = {
            "censo": censo(driver),
            "aristas": aristas(driver),
            "seguimiento": seguimiento(driver),
            "visor_admin": vista(admin),
            "visor_revisor": vista(revisor),
            "visor_lector": vista(lector),
        }
        return pasos[nombre]

    # ---- S0: NEO4J VACIO -> SCHEMA INIT
    with driver.session() as s:
        s.run("MATCH (n) WHERE n.workspace = $ws DETACH DELETE n", {"ws": WS})
    bootstrap_writer_schema(driver)
    s0 = registrar("s0_vacio")
    assert s0["censo"]["entidades_v3"] == 0, "el recorrido tiene que empezar VACIO"

    # ---- PASO 1: fuente real -> review/promocion -> UN SOLO apply
    altas = _altas_aprobadas(driver)
    informe = _aplicar(driver, altas)
    assert informe["write"]["outcome"] == "APPLIED", informe["write"]
    poliza = informe.get("rollback")
    assert poliza is not None, "el apply no emitio poliza de rollback"
    registrar("s1_un_apply")

    # ---- PASO 2: repeat apply
    informe2 = _aplicar(driver, altas)
    registrar("s2_repeat")

    # ---- PASO 3: rollback
    with driver.session() as ses:
        reporte = execute_rollback(ses, _rehidratar_rollback(poliza))
    registrar("s3_rollback")

    # ---- PASO 4: re-apply
    informe3 = _aplicar(driver, _altas_aprobadas(driver))
    assert informe3["write"]["outcome"] == "APPLIED", informe3["write"]
    registrar("s4_reapply")

    return {
        "pasos": pasos,
        "informe1": informe,
        "informe2": informe2,
        "informe3": informe3,
        "poliza": poliza,
        "reporte_rollback": reporte,
    }


def test_paso1_un_solo_apply_deja_la_relacion_la_procedencia_y_el_visor_la_VE(recorrido):
    """LA COSTURA DE 11A, MEDIDA: la arista entidad->entidad existe tras el
    PRIMER apply, sin que este fichero haya emitido ningun plan de relacion."""
    s0 = recorrido["pasos"]["s0_vacio"]
    s1 = recorrido["pasos"]["s1_un_apply"]

    # --- el grafo
    assert s1["censo"]["entidades_v3"] > 0, "el apply no dejo ni una entidad"
    assert s1["censo"]["aristas_ent_ent"] > 0, (
        "el PRIMER apply creo las entidades pero NO materializo la relacion: "
        f"{s1['censo']}. Es exactamente el defecto que 11A cerro."
    )
    assert s1["aristas"], "no hay arista que comparar"

    # --- las dos etiquetas coinciden (costura de 11B)
    assert (
        s1["censo"]["entidades_publicas"]
        == s1["censo"]["entidades_v3"]
        == s1["censo"]["entidades_ambas"]
    ), (
        f"las superficies se han separado: {s1['censo']}. El visor leeria un "
        "universo que el writer no alimenta."
    )

    # --- procedencia presente en el grafo...
    assert s1["censo"]["fuentes"] > 0, "sin :V3Source no hay procedencia"
    assert s1["censo"]["evidencias"] > 0, "sin :V3Evidence no hay procedencia"
    assert s1["censo"]["marcas"] > 0, (
        "sin marcas :V3AppliedOperation el apply no dejo rastro de idempotencia"
    )

    # --- ...y EL VISOR LA VE
    admin = s1["visor_admin"]
    assert admin["codigos"]["entities"] == 200, admin["codigos"]
    ids_grafo = {e["entity_id"] for e in s1["seguimiento"]}
    assert set(admin["entidades"]) == ids_grafo, (
        f"el writer escribio {sorted(ids_grafo)} y el visor entrega "
        f"{admin['entidades']}"
    )
    assert admin["aristas_grafo"], (
        "el grafo tiene arista entidad->entidad y /api/graph no entrega ninguna: "
        "el visor NO refleja el primer apply"
    )
    esperadas = {(d, h) for (_t, d, h) in s1["aristas"]}
    assert esperadas <= set(admin["aristas_grafo"]), (
        f"el visor no entrega la arista aplicada: grafo={sorted(esperadas)} "
        f"visor={admin['aristas_grafo']}"
    )
    assert admin["fuentes"], "/api/sources no entrega la fuente que el writer creo"

    # --- el vacio de partida no era un falso verde
    assert s0["visor_admin"]["entidades"] == [], (
        "el visor ya veia entidades ANTES del apply: el paso 1 no mide nada"
    )


def test_paso2_repeat_apply_se_RECHAZA_por_plan_vacio_y_el_visor_queda_IDENTICO(recorrido):
    s1 = recorrido["pasos"]["s1_un_apply"]
    s2 = recorrido["pasos"]["s2_repeat"]

    escritura = recorrido["informe2"]["write"]

    # LO QUE DE VERDAD PASA, dicho como es y no como quedaria mejor. El repeat
    # apply por la ruta de operador no sale `APPLIED` con cero operaciones: sale
    # REJECTED con `['PLAN_NOT_APPROVED', 'PLAN_NO_OPERATIONS']`. El material ya
    # esta en el grafo, la reconciliacion no deja altas pendientes y el plan sale
    # SIN operaciones, asi que el writer lo rechaza antes de ejecutar nada.
    #
    # Para lo que esta prueba mide --que el segundo apply NO termina el trabajo
    # del primero-- el desenlace importante es el EFECTO: cero operaciones
    # escritas y el grafo y el visor sin moverse. Eso es lo que se exige. Pero
    # llamarlo «NOOP» a secas seria maquillar un rechazo, asi que el codigo
    # concreto se fija aqui: si el dia de mañana el repeat apply pasa a escribir
    # algo, o a rechazar por OTRA razon, esta prueba se entera.
    assert escritura["applied_operations"] == 0, (
        f"el segundo apply escribio {escritura['applied_operations']} operacion(es) "
        f"{escritura.get('created_ids')}: estaba TERMINANDO el trabajo del primero, "
        "que es justo lo que el arreglo de 11A elimina"
    )
    assert escritura["outcome"] == "REJECTED", (
        f"el repeat apply salio {escritura['outcome']!r} y esta prueba estaba "
        "escrita sobre un REJECTED por plan vacio: si el desenlace cambia, hay "
        "que volver a mirar que significa aqui «no escribir nada»"
    )
    assert set(escritura.get("codes") or []) == {
        "PLAN_NOT_APPROVED",
        "PLAN_NO_OPERATIONS",
    }, (
        f"el repeat apply se rechaza por {escritura.get('codes')}, no por plan "
        "vacio: el motivo del cero ha cambiado y ya no es el que esto documenta"
    )
    assert s2["censo"] == s1["censo"], (
        f"el repeat apply movio el censo: {s1['censo']} -> {s2['censo']}"
    )
    assert s2["aristas"] == s1["aristas"], "el repeat apply cambio las aristas"
    assert s2["visor_admin"] == s1["visor_admin"], (
        "el visor NO es identico tras un apply que dice no haber escrito nada"
    )


def test_paso3_rollback_borra_el_conocimiento_el_visor_lo_refleja_y_CERO_marcas(recorrido):
    s3 = recorrido["pasos"]["s3_rollback"]
    reporte = recorrido["reporte_rollback"]

    # --- CERO marcas colgantes. La linea que 11B señalo: contar por :Entity
    # mezclaria las marcas con las entidades publicas, asi que se cuenta por
    # su propia etiqueta.
    assert s3["censo"]["marcas"] == 0, (
        f"quedan {s3['censo']['marcas']} marca(s) V3AppliedOperation tras el "
        "rollback: una marca superviviente hace la relacion irrecuperable"
    )
    assert not reporte.residues, f"el rollback declara residuos: {reporte.residues}"

    # --- el conocimiento desaparece SEGUN CONTRATO
    assert s3["censo"]["entidades_v3"] == 0, s3["censo"]
    assert s3["censo"]["entidades_publicas"] == 0, s3["censo"]
    assert s3["censo"]["aristas_ent_ent"] == 0, s3["censo"]
    assert s3["aristas"] == [], s3["aristas"]

    # --- `clean` tiene que describir el grafo REAL, no lo que el documento
    # nombra: un `clean:true` sobre marcas vivas es el `residues:[]` mentiroso
    # un nivel mas abajo.
    assert reporte.clean is (
        s3["censo"]["marcas"] == 0 and s3["censo"]["entidades_v3"] == 0
    ), f"clean={reporte.clean} no describe el grafo real {s3['censo']}"

    # --- EL VISOR LO REFLEJA
    admin = s3["visor_admin"]
    assert admin["codigos"]["entities"] == 200, (
        "el visor tiene que RESPONDER y entregar vacio, no romperse"
    )
    assert admin["entidades"] == [], (
        f"el rollback vacio el grafo y el visor SIGUE enseñando {admin['entidades']}"
    )
    assert admin["aristas_grafo"] == [], (
        f"el rollback borro la arista y el visor la sigue enseñando: "
        f"{admin['aristas_grafo']}"
    )


def test_paso4_reapply_devuelve_el_conocimiento_y_el_visor_VUELVE_A_VERLO(recorrido):
    s1 = recorrido["pasos"]["s1_un_apply"]
    s4 = recorrido["pasos"]["s4_reapply"]

    assert s4["censo"] == s1["censo"], (
        f"el re-apply no reconstruye S1: {s1['censo']} -> {s4['censo']}"
    )
    # Por identidad durable (`entity_id`), NUNCA por `elementId`: el elementId
    # cambia en cada re-apply y no es identidad durable.
    assert s4["aristas"] == s1["aristas"], "el re-apply no rehace la relacion"
    assert s4["visor_admin"] == s1["visor_admin"], (
        "el conocimiento volvio al grafo pero el visor no lo vuelve a ver igual"
    )


def test_en_CADA_paso_lo_no_autorizado_sigue_sin_verse(recorrido):
    """La ultima linea es innegociable, y se comprueba en los cuatro pasos.

    Se usa un lector LEGITIMO sin derechos, no un razonamiento: el writer
    estampa `visibility='secret'` con `visibility_source='default_fail_closed'`,
    asi que quien no tiene `can_view_secret` no ve NI UNO de estos nodos.
    """
    for nombre, paso in recorrido["pasos"].items():
        assert _no_ve_nada(paso["visor_revisor"]), (
            f"[{nombre}] el revisor SIN derechos ve material: "
            f"{paso['visor_revisor']}"
        )
        assert _no_ve_nada(paso["visor_lector"]), (
            f"[{nombre}] el lector SIN derechos ve material: {paso['visor_lector']}"
        )


def test_el_control_de_autorizacion_COLAPSA_si_el_cero_no_es_de_autorizacion(recorrido):
    """«No veo nada» y «la base esta vacia» son indistinguibles desde fuera.

    Sin esta distincion, el test de arriba estaria igual de verde con la
    politica ROTA y el grafo vacio -- y tambien en el paso 3, donde el cero SI
    es por vacio. Aqui se exige que en los pasos CON material el cero del lector
    sin derechos conviva con un admin que SI ve: eso, y solo eso, prueba que el
    cero lo produce la autorizacion.
    """
    con_material = ("s1_un_apply", "s2_repeat", "s4_reapply")
    for nombre in con_material:
        paso = recorrido["pasos"][nombre]
        assert paso["visor_admin"]["entidades"], (
            f"[{nombre}] el admin tampoco ve nada: el cero del lector sin "
            "derechos no demuestra autorizacion, solo que no hay datos"
        )
        assert not paso["visor_lector"]["entidades"], (
            f"[{nombre}] el lector sin derechos VE material"
        )

    # Y en el paso 3 el cero es de VACIO, no de autorizacion. Declararlo evita
    # leer aquel cero como una prueba de politica que ahi no existe.
    s3 = recorrido["pasos"]["s3_rollback"]
    assert not s3["visor_admin"]["entidades"], (
        "tras el rollback ni siquiera el admin puede ver material"
    )


def test_la_procedencia_NO_entra_en_la_superficie_publica_en_ningun_paso(recorrido, driver):
    """INVARIANTE, no carencia: `V3Source`/`V3Episode`/`V3Evidence` son
    fail-closed a proposito (ver una assertion NO da acceso a toda su fuente).
    Que sigan fuera del alcance del visor se AFIRMA aqui."""
    with driver.session() as s:
        for etiqueta in ("V3Source", "V3Episode", "V3Evidence", "V3Assertion"):
            colados = s.run(
                f"MATCH (n:{etiqueta} {{workspace:$ws}}) WHERE n:Entity "
                "RETURN count(n) AS c",
                {"ws": WS},
            ).single()["c"]
            assert colados == 0, (
                f"{colados} nodos :{etiqueta} llevan la etiqueta publica :Entity: "
                "la procedencia ha quedado al alcance del visor"
            )


def test_la_tabla_de_seguimiento_trae_valores_medidos_y_no_nulos(recorrido):
    """Los campos de seguimiento, leidos del grafo tras el primer apply.

    `partida_id` y `known_from_session` salen a `None` A PROPOSITO: el material
    de ejemplo es de `scope='juego'` y el contrato de visibilidad solo exige
    `known_from_session` para contenido de partida. Se afirma lo que SI tiene
    que venir con valor, y se afirma que el `None` de partida va ACOMPAÑADO del
    `scope` que lo justifica -- que es la diferencia entre un nulo correcto y
    un campo que nadie escribio.
    """
    filas = recorrido["pasos"]["s1_un_apply"]["seguimiento"]
    assert filas, "la tabla de seguimiento esta vacia: no mide nada"

    obligatorios = (
        "entity_id",
        "entity_type",
        "scope",
        "visibility",
        "visibility_source",
        "operator",
        "plan_hash",
    )
    for fila in filas:
        for campo in obligatorios:
            assert fila.get(campo) not in (None, "", []), (
                f"{fila.get('entity_id')}: campo {campo!r} sin valor -> {fila}"
            )
        assert fila["evidence_fragment_ids"], (
            f"{fila['entity_id']} sin ids de evidencia: no hay procedencia que seguir"
        )
        assert fila["operator"] == OPERADOR, (
            f"el operador registrado es {fila['operator']!r} y no {OPERADOR!r}"
        )
        assert fila["visibility"] == "secret", fila
        assert fila["visibility_source"] == "default_fail_closed", fila
        # El nulo de partida va JUSTIFICADO por el scope, no suelto.
        if fila["partida_id"] is None:
            assert fila["scope"] != "partida", (
                f"{fila['entity_id']} dice scope='partida' y no trae partida_id"
            )
            assert fila["known_from_session"] is None, fila

    # VALORES DISTINTOS: si todas las filas fuesen iguales, la tabla no
    # distinguiria una entidad de otra y comparar por ella seria comparar nada.
    assert len({f["entity_id"] for f in filas}) == len(filas), (
        "hay entity_id repetidos en la tabla de seguimiento"
    )
    assert len({f["entity_type"] for f in filas}) >= 1
    ownership = recorrido["poliza"].get("ownership_id")
    apply_id = recorrido["poliza"].get("apply_id")
    assert ownership, f"la poliza no trae ownership_id: {sorted(recorrido['poliza'])}"
    assert apply_id, "la poliza no trae apply_id"
    assert ownership != apply_id, (
        "ownership_id y apply_id coinciden: uno identifica el INTENTO y el otro "
        "la PROPIEDAD durable de los efectos; si son el mismo valor, uno de los "
        "dos no se esta calculando"
    )


# ===========================================================================
# TAREA 3 -- LA REPRODUCCION VIVA QUE 11A DECLARO COMO PARCIAL
# ===========================================================================
# 11A dejo escrito, con todas las letras:
#
#   «La reproduccion VIVA de la marca colgante no llego a dispararse: en el
#   escenario B el segundo apply aborta con EXEC_VERSION_MISMATCH ANTES de
#   escribir la proyeccion, asi que nunca se creo la marca de otro plan_hash.
#   El arreglo de `residues` esta razonado sobre el codigo y cubierto por la
#   asercion de rollback, PERO NO POR UNA REPRODUCCION VIVA.»
#
# AQUI SE REPRODUCE. Y la ruta no era la del segundo apply --por ahi sigue sin
# poder provocarse, ver la nota del final-- sino la de DOS PLANES DISTINTOS
# escribiendo sobre el mismo material: el de la ingesta y el plan de relacion
# sellado por el producto. Cada uno deja marcas con SU `plan_hash`; al revertir
# el primero, la marca del segundo se queda colgando.
#
# POR QUE IMPORTA Y NO ES UN TECNICISMO: una marca `V3AppliedOperation` viva
# afirma «esta operacion ya se aplico». Si sobrevive al rollback del material
# que la sostenia, el siguiente apply la cree y SE SALTA la operacion: la
# relacion queda irrecuperable y el grafo, silenciosamente incompleto. Un
# `clean: true, residues: []` encima de eso es la peor respuesta posible,
# porque cierra el incidente.
#
# CALIBRADO POR EL INTEGRADOR, que es lo que convierte esto en evidencia: con
# `rollback_provenance.py` en la version BASE (tanda 10) y todo lo demas igual,
# este mismo escenario devuelve `clean: True` y `residues: []` con la marca
# colgante viva delante. Con el arreglo de 11A devuelve `clean: False` y la
# denuncia. La prueba PUEDE ponerse roja.

def test_la_marca_colgante_de_OTRO_plan_hash_se_cuenta_como_residuo(driver):
    """Reproduccion VIVA, no razonada: dos `plan_hash`, uno revertido."""
    import test_contrato_writer_a_visor_neo4j as B
    from knowledge_v3.writer import (
        InMemoryAppliedKeys,
        InMemoryAuditSink,
        OperatorRequest,
        bootstrap_writer_schema,
    )
    from knowledge_v3.writer.rollback_provenance import execute_rollback
    from knowledge_v3.writer.writer import GraphWriter

    with driver.session() as s:
        s.run("MATCH (n) WHERE n.workspace = $ws DETACH DELETE n", {"ws": WS})
    bootstrap_writer_schema(driver)

    # --- APPLY A: la ruta de operador
    informe = _aplicar(driver, _altas_aprobadas(driver))
    assert informe["write"]["outcome"] == "APPLIED", informe["write"]
    plan_hash_a = informe["rollback"]["plan_hash"]

    # --- APPLY B: OTRO plan, sellado por el producto -> OTRO plan_hash
    with driver.session() as s:
        creadas = [
            r.data()
            for r in s.run(
                "MATCH (n:V3Entity {workspace:$ws}) RETURN n.entity_id AS id, "
                "n.version AS version, n.state_hash AS state_hash ORDER BY id",
                {"ws": WS},
            )
        ]
    assert len(creadas) >= 2, "sin dos extremos no hay segundo plan que aplicar"
    snapshot = "snapshot:sha256:" + "e" * 64
    plan_b = B._plan_de_relacion(creadas[0], creadas[1], snapshot)
    plan_hash_b = plan_b["plan_hash"]["value"]
    assert plan_hash_b != plan_hash_a, (
        "los dos planes comparten plan_hash: el escenario no reproduce nada"
    )

    resultado_b = GraphWriter(
        workspace=WS,
        driver=driver,
        audit=InMemoryAuditSink(),
        applied_keys=InMemoryAppliedKeys(),
    ).write(
        plan_b,
        OperatorRequest(
            apply=True,
            operator_id=OPERADOR,
            workspace=WS,
            expected_plan_hash=plan_hash_b,
            max_operations=50,
            current_snapshot_id=snapshot,
            env={"S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": WS},
        ),
    )
    assert resultado_b.outcome == "APPLIED", (resultado_b.outcome, resultado_b.codes)

    # El escenario solo vale si de verdad conviven DOS plan_hash en las marcas.
    with driver.session() as s:
        hashes = {
            r["ph"]
            for r in s.run(
                "MATCH (m:V3AppliedOperation {workspace:$ws}) "
                "RETURN DISTINCT m.plan_hash AS ph",
                {"ws": WS},
            )
        }
    assert {plan_hash_a, plan_hash_b} <= hashes, (
        f"no conviven los dos plan_hash en las marcas: {hashes}"
    )

    # --- ROLLBACK DE A: la marca de B se queda COLGANDO
    with driver.session() as ses:
        reporte = execute_rollback(ses, _rehidratar_rollback(informe["rollback"]))

    with driver.session() as s:
        vivas = [
            dict(r)
            for r in s.run(
                "MATCH (m:V3AppliedOperation {workspace:$ws}) "
                "RETURN m.plan_hash AS ph, m.operation_id AS op "
                "ORDER BY m.operation_id",
                {"ws": WS},
            )
        ]
        entidades = s.run(
            "MATCH (n:V3Entity {workspace:$ws}) RETURN count(n) AS c", {"ws": WS}
        ).single()["c"]

    colgantes = [m for m in vivas if m["ph"] == plan_hash_b]
    assert entidades == 0, (
        f"el rollback de A dejo {entidades} entidad(es): sin grafo vacio la marca "
        "de B no esta colgando y el escenario no reproduce nada"
    )
    assert colgantes, (
        "la marca del plan B no sobrevivio: el escenario ya no reproduce la marca "
        "colgante y este test deja de medir lo que dice medir"
    )

    # --- LO QUE SE MIDE: `residues` cuenta TODA marca colgante, no solo las de
    # su propio plan_hash. Es el arreglo de 11A, ahora con reproduccion viva.
    denunciadas = [
        r
        for r in reporte.residues
        if (r.get("detail") or {}).get("plan_hash") == plan_hash_b
    ]
    assert denunciadas, (
        f"hay una marca colgante del plan {plan_hash_b} y `residues` no la "
        f"denuncia: {reporte.residues}. Es exactamente el `residues: []` mentiroso "
        "que 11A cerro -- y con la version BASE de `rollback_provenance.py` este "
        "assert se pone ROJO (calibrado por el integrador)."
    )
    # Y no se declara propio lo que no lo es: la marca es de OTRO apply.
    assert (denunciadas[0].get("detail") or {}).get("de_este_apply") is False, (
        f"la marca de otro plan_hash se declara como propia: {denunciadas[0]}"
    )
    assert reporte.clean is False, (
        "`clean` dice True con una marca colgante viva: el mismo `residues: []` "
        "mentiroso un nivel mas arriba"
    )

    with driver.session() as s:
        s.run("MATCH (n) WHERE n.workspace = $ws DETACH DELETE n", {"ws": WS})


# NOTA HONESTA sobre la ruta que 11A describio y que sigue SIN reproducirse
# ------------------------------------------------------------------------
# Por la ruta que 11A nombra --un SEGUNDO apply de la misma ingesta-- la marca
# colgante de otro `plan_hash` SIGUE sin poder provocarse, y conviene decirlo
# en vez de dar por bueno que «ya esta cubierto». Lo que cambia con el arreglo
# es el MOTIVO del corte, no el hecho de que corte: MEDIDO en esta integracion,
# el segundo apply sale `REJECTED` con `['PLAN_NOT_APPROVED',
# 'PLAN_NO_OPERATIONS']` --el material ya esta en el grafo, no quedan altas
# pendientes y el plan sale sin operaciones-- en lugar del
# `EXEC_VERSION_MISMATCH` que veia 11A. En los dos casos se aborta ANTES de
# escribir marca alguna, asi que ese escenario NO es capaz de producirla. La
# reproduccion viva de arriba llega por otra ruta (dos planes distintos), que
# es la que si la produce.
