# -*- coding: utf-8 -*-
"""EQUIPO 6C -- `--partida` de extremo a extremo, y la SESION hasta Neo4j.

EL DEFECTO QUE CIERRA ESTE FICHERO
----------------------------------
`writer/visibility.py::revelacion_props` exige `known_from_session` para todo
lo que se escribe en ambito PARTIDA, y `writer/executor.py` lo busca en
`op["payload"]`. NINGUN constructor de operaciones lo ponia nunca ahi:
`known_from_session` no aparecia ni una vez en `pipeline/` ni en
`engine/planner.py`. Mientras la CLI no supo producir ambito de partida eso no
se notaba y se archivo como deuda declarada; en cuanto EQUIPO 5A abrio la
ruta `--partida`, TODO plan de partida abortaba con
`EXEC_REVELACION_NO_DECLARADA` y el ambito de partida era inalcanzable desde
el producto. La guardia estaba bien. Lo que no llegaba era el dato.

LA CORRECCION NO ES UN VALOR POR DEFECTO
----------------------------------------
No se estampa `0` ni nada inventado. La sesion de revelacion se DECLARA en el
contexto de ingesta (`--sesion N`), igual que el ambito y que `now`, porque es
un dato del mundo que ningun punto del software puede deducir del fichero: en
que sesion de juego puede revelarse lo que se esta ingiriendo. Y si falta en
ambito de partida, no se planifica --nunca se degrada a capa juego--.

La cadena que se recorre aqui, entera y contra Neo4j real:

    CLI --partida/--sesion -> run_ingest -> PipelineConfig -> engine.run
      -> PlanContext -> planner (payload de CADA operacion) -> writer
      -> visibility.stamp -> Neo4j

DISCIPLINA DE MEDIDA
--------------------
* El grafo arranca VACIO y se comprueba; no se presume.
* El esquema lo instala el PRODUCTO (`bootstrap_writer_schema`, dentro de la
  fixture efimera). Este fichero no ejecuta ni un `CREATE` propio: todo nodo
  y toda arista del grafo los escribe el writer por la ruta de la CLI.
* UNA consulta por cosa contada, y cada censo se afirma NO VACIO antes de
  compararlo. Dos `MATCH` sueltos dan producto cartesiano y, con un lado
  vacio, CERO filas: un verde que no mide nada.
* Se SIGUE EL DATO: las tres declaraciones son 3, 7 y 5, ninguna es `0` ni se
  repite entre ambitos. Un valor por defecto no puede coincidir con las tres.
* `elementId` no se usa jamas como identidad.
* `AHORA` es de HOY a proposito. Dos ficheros del repo llevan
  `2026-09-06T10:00:00Z` fijo con `plan_ttl_seconds=86400`; a partir del
  2026-09-07T10:00Z salen rojos con `PLAN_EXPIRED`, correctamente, y ese rojo
  no es de nadie mas.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import datetime, timezone

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("neo4j")

APP_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

LIVE = os.environ.get("S9K_WRITER_NEO4J_REAL", "").strip() == "1"
pytestmark = pytest.mark.skipif(
    not LIVE, reason="Neo4j real efimero: activar con S9K_WRITER_NEO4J_REAL=1"
)

from test_knowledge_v3_writer_neo4j_real import neo4j_efimero_conexion  # noqa: E402

from knowledge_v3.engine import planner as planner_mod  # noqa: E402
from knowledge_v3.engine.errors import EnginePlanError  # noqa: E402
from knowledge_v3.engine.planner import PlanContext  # noqa: E402
from knowledge_v3.pipeline import entity_decisions, graph_catalog as gc, ingest_cli  # noqa: E402
from knowledge_v3.pipeline.errors import PipelineError  # noqa: E402

RAIZ = APP_DIR.parents[1]
EJEMPLOS = RAIZ / "examples" / "ingesta-v3"
PERFIL = EJEMPLOS / "perfil-operador.json"
CATALOGO = EJEMPLOS / "catalogo-workspace.json"
WS = "ws-cofradia"
#: INTEGRACION TANDA 6. 6C neutralizo la bomba de reloj en SU fichero
#: adelantando la fecha a `2026-09-07T12:00:00Z`. Eso la desarmaba para el dia
#: de la entrega y la volvia a armar para el 2026-09-08T12:00Z: adelantar la
#: fecha REPROGRAMA la bomba, no la desactiva. Se deriva del reloj, igual que
#: en los otros dos ficheros que la llevaban.
AHORA = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

PARTIDA_A = "partida:A"
PARTIDA_B = "partida:B"
#: Las tres declaraciones. Distintas entre si y ninguna es 0: si lo que acaba
#: en Neo4j coincide con las tres, no puede ser un valor por defecto.
SESION_A1 = 3
SESION_B = 7
SESION_A2 = 5

ENV_APPLY = {"S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": WS}


# --- utillaje: la CLI, nada mas ---------------------------------------------
def _fuente(tmp_path: pathlib.Path, nombre: str, texto: str) -> pathlib.Path:
    ruta = tmp_path / nombre
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def _ingesta(fuente, driver, **kw):
    """Una corrida de la CLI. El catalogo declarado NO es opcional.

    MEDIDO: sin el, el resolutor no tiene vocabulario, todo sale provisional y
    el motor manda a revision cualquier hecho sobre una provisional -- cero
    operaciones y `PLAN_NO_OPERATIONS`, es decir, una prueba que no prueba.
    """
    return ingest_cli.run_ingest(
        fuente,
        profile_path=PERFIL,
        catalog_path=CATALOGO,
        driver=driver,
        now=AHORA,
        ingested_at=AHORA,
        **kw,
    )


def _altas_aprobadas(fuente, driver, partida, sesion):
    """Primera pasada en seco + aprobacion humana simulada de las altas.

    `names_by_mention` NO es decorativo: es lo que la CLI real pasa
    (`ingest_cli.main`). Sin el, el alta se crea con `name = entity_id`, y en
    la SIGUIENTE ingesta el resolutor ya no reconoce el nombre y todo vuelve
    provisional. Medido en este mismo carril antes de anadirlo.
    """
    seco = _ingesta(fuente, driver, partida_id=partida, known_from_session=sesion)
    ledger = entity_decisions.reconcile(
        resolutions=(seco["candidates"]["link_existing"] + seco["candidates"]["create_entity"]),
        graph_entity_ids=gc.entity_ids(gc.catalog_rows(driver, WS, partida)),
        workspace=WS,
        source_path=str(fuente),
        names_by_mention=ingest_cli._nombres_por_mencion(seco),
    )
    ids = sorted({
        d.entity_id for d in ledger.altas
        if not d.entity_id.startswith(("entity:prov:", "entity:new:"))
    })
    if not ids:
        return []
    aprobado = entity_decisions.approve(ledger, ids, reviewer="pjc", at=AHORA)
    return entity_decisions.approved_snapshot_entities(aprobado)


def _corre_partida(fuente, driver, partida, sesion):
    """La corrida completa de una partida: altas aprobadas + APPLY real."""
    altas = _altas_aprobadas(fuente, driver, partida, sesion)
    return _ingesta(
        fuente,
        driver,
        partida_id=partida,
        known_from_session=sesion,
        approved_altas=altas,
        apply=True,
        operator_id="pjc",
        writer_env=ENV_APPLY,
    )


def _filas(driver, cypher, **params):
    with driver.session() as s:
        return [r.data() for r in s.run(cypher, params)]


# --- fixtures ---------------------------------------------------------------
@pytest.fixture(scope="module")
def conexion():
    with neo4j_efimero_conexion("s9k-eq6c-sesion") as cx:
        yield cx


@pytest.fixture(scope="module")
def mundo(conexion, tmp_path_factory):
    """DESDE VACIO: dos partidas escritas por la CLI, y nada mas en el grafo.

    Se construye una sola vez porque es caro, y se comprueba el vacio ANTES de
    escribir: un grafo sucio heredado convertiria cualquier censo posterior en
    una medida de otra cosa.
    """
    driver = conexion.driver
    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    vacio = _filas(driver, "MATCH (n) RETURN count(n) AS c")
    assert vacio and vacio[0]["c"] == 0, "el grafo no arranca vacio"

    tmp = tmp_path_factory.mktemp("fuentes6c")
    fa1 = _fuente(tmp, "partida-A-s3.md",
                  "# Nota de sesion - partida A\n\n"
                  "Sela Marrec es miembro de la Cofradia de Ambar.\n")
    fb = _fuente(tmp, "partida-B-s7.md",
                 "# Nota de sesion - partida B\n\n"
                 "La Casa del Ciervo es aliada del Consejo de Umbra.\n")
    fa2 = _fuente(tmp, "partida-A-s5.md",
                  "# Nota de sesion - partida A, mas tarde\n\n"
                  "Sela Marrec lidera la Cofradia de Ambar.\n")

    informes = {
        "A1": _corre_partida(fa1, driver, PARTIDA_A, SESION_A1),
        "B": _corre_partida(fb, driver, PARTIDA_B, SESION_B),
        # Segunda corrida de A: sus dos entidades YA existen en el grafo, que
        # es la unica condicion en la que el planificador emite
        # `PROJECT_RELATION`. Sin ella no habria ni una relacion materializada
        # que censar, y el criterio 3 se quedaria a medias.
        "A2": _corre_partida(fa2, driver, PARTIDA_A, SESION_A2),
    }
    return {"driver": driver, "informes": informes, "tmp": tmp}


# --- criterio 1 y 2 ---------------------------------------------------------
def test_partida_a_con_su_sesion_aplica_de_verdad(mundo):
    """Antes de este carril esto era `EXEC_REVELACION_NO_DECLARADA` SIEMPRE."""
    write = mundo["informes"]["A1"].get("write")
    assert write is not None, "no hubo ni intento de escritura"
    assert write["outcome"] == "APPLIED", write
    assert "EXEC_REVELACION_NO_DECLARADA" not in (write.get("codes") or [])
    assert write["applied_operations"] > 0, write


def test_partida_b_aplica_y_no_reutiliza_las_operaciones_de_a(mundo):
    """Dos partidas, dos conjuntos de operaciones. Sin interseccion."""
    write = mundo["informes"]["B"].get("write")
    assert write is not None and write["outcome"] == "APPLIED", write
    assert write["applied_operations"] > 0

    filas = _filas(
        mundo["driver"],
        "MATCH (o:V3AppliedOperation) "
        "RETURN o.partida_id AS pid, o.idempotency_key AS ik ORDER BY ik",
    )
    assert filas, "no hay operaciones aplicadas que comparar"
    de_a = {f["ik"] for f in filas if f["pid"] == PARTIDA_A}
    de_b = {f["ik"] for f in filas if f["pid"] == PARTIDA_B}
    assert de_a, "la partida A no dejo ninguna operacion aplicada"
    assert de_b, "la partida B no dejo ninguna operacion aplicada"
    assert de_a.isdisjoint(de_b), sorted(de_a & de_b)


# --- criterio 3: el censo, una consulta por cosa contada --------------------
def test_censo_aserciones_con_ambito_y_sesion_reales(mundo):
    filas = _filas(
        mundo["driver"],
        "MATCH (n:V3Assertion {workspace:$ws}) "
        "RETURN n.assertion_id AS a, n.scope AS sc, n.partida_id AS pid, "
        "n.known_from_session AS k ORDER BY a",
        ws=WS,
    )
    assert filas, "censo vacio: no hay nada que este test pueda afirmar"
    por_partida = {}
    for f in filas:
        assert f["sc"] == "partida", f
        assert f["pid"] in (PARTIDA_A, PARTIDA_B), f
        por_partida.setdefault(f["pid"], set()).add(f["k"])
    # SEGUIR EL DATO: lo escrito es lo declarado, no un defecto que coincide.
    assert por_partida[PARTIDA_A] == {SESION_A1, SESION_A2}, por_partida
    assert por_partida[PARTIDA_B] == {SESION_B}, por_partida
    # Y los identificadores no se comparten entre ambitos.
    ids_a = {f["a"] for f in filas if f["pid"] == PARTIDA_A}
    ids_b = {f["a"] for f in filas if f["pid"] == PARTIDA_B}
    assert ids_a and ids_b and ids_a.isdisjoint(ids_b)


def test_censo_relaciones_materializadas_con_ambito_y_sesion(mundo):
    """La relacion proyectada tambien lleva su ambito y su sesion."""
    filas = _filas(
        mundo["driver"],
        "MATCH ()-[r]->() WHERE r.workspace = $ws "
        "RETURN type(r) AS t, r.scope AS sc, r.partida_id AS pid, "
        "r.known_from_session AS k ORDER BY t",
        ws=WS,
    )
    assert filas, "sin relaciones materializadas este censo no mide nada"
    for f in filas:
        assert f["sc"] == "partida", f
        assert f["pid"] == PARTIDA_A, f
        assert f["k"] == SESION_A2, f


def test_censo_entidades_no_cambia_de_identidad(mundo):
    """`(workspace, entity_id)` sigue siendo la identidad. No se toca.

    Lo que el ambito privatiza son aserciones, relaciones y operaciones. Aqui
    solo se comprueba que la entidad conserva su identidad de producto y que
    NINGUNA quedo sin declarar el ambito -- que es el fallo que
    `scope_props` existe para impedir.
    """
    filas = _filas(
        mundo["driver"],
        "MATCH (n:V3Entity {workspace:$ws}) "
        "RETURN n.entity_id AS e, n.scope AS sc, n.partida_id AS pid ORDER BY e",
        ws=WS,
    )
    assert filas, "censo de entidades vacio"
    assert len({f["e"] for f in filas}) == len(filas), "entity_id repetido en el workspace"
    for f in filas:
        assert f["sc"] in ("juego", "partida"), f
        assert (f["pid"] is None) == (f["sc"] == "juego"), f


# --- criterio 4: FAIL CLOSED, provocado -------------------------------------
def test_ambito_de_partida_sin_sesion_falla_cerrado_y_no_escribe(mundo, tmp_path):
    """El caso del defecto, ahora detenido ANTES de gastar la corrida."""
    driver = mundo["driver"]
    fuente = _fuente(tmp_path, "partida-C-sin-sesion.md",
                     "# Nota de sesion - partida C\n\n"
                     "Sela Marrec vive en Vado Alto.\n")
    antes = _filas(driver, "MATCH (n) RETURN count(n) AS c")[0]["c"]
    with pytest.raises(PipelineError) as exc:
        _ingesta(fuente, driver, partida_id="partida:C", apply=True,
                 operator_id="pjc", writer_env=ENV_APPLY)
    assert "PLAN_SESION_NO_DECLARADA" in str(exc.value)
    # No basta con que levante: el grafo no puede haberse movido.
    despues = _filas(driver, "MATCH (n) RETURN count(n) AS c")[0]["c"]
    assert despues == antes, (antes, despues)
    huerfanas = _filas(
        driver,
        "MATCH (n) WHERE n.partida_id = $p RETURN count(n) AS c",
        p="partida:C",
    )
    assert huerfanas[0]["c"] == 0


def test_el_motor_tambien_falla_cerrado_aunque_se_le_llame_por_dentro(mundo):
    """La guardia no vive solo en la CLI: `PlanContext` la repite.

    Si viviera solo en la CLI, cualquier otra ruta que construyese un contexto
    --un test, un script, el carril de otro equipo-- volveria a producir
    planes de partida sin sesion, que es exactamente como nacio el defecto.
    """
    with pytest.raises(EnginePlanError) as exc:
        PlanContext(
            workspace=WS, source_asset_id="x", source_hash={}, collection_id="c",
            game_profile="generic", ontology_version="core-1.4.0", snapshot=None,
            now=AHORA, partida_id=PARTIDA_A, known_from_session=None,
        )
    assert "PLAN_SESION_NO_DECLARADA" in str(exc.value)


# --- criterio 5: la degradacion silenciosa a JUEGO es imposible -------------
def test_no_hay_manera_de_degradar_a_juego(mundo):
    """Se INTENTA degradar por las dos vias posibles, y las dos se cierran."""
    # Via 1: declarar partida y omitir la sesion esperando capa juego. Ya
    # cubierto arriba; aqui se comprueba el EFECTO: ni una fila de capa juego
    # quedo en el grafo por esa via.
    juego = _filas(
        mundo["driver"],
        "MATCH (n:V3Assertion {workspace:$ws}) WHERE n.scope = 'juego' "
        "RETURN count(n) AS c",
        ws=WS,
    )
    assert juego[0]["c"] == 0, "una corrida de partida acabo en capa juego"

    # Via 2: declarar la sesion y omitir la partida, esperando que la sesion
    # "se cuele". Se rechaza en voz alta en vez de descartarse en silencio,
    # que es lo que haria `revelacion_props` para scope=juego.
    with pytest.raises(EnginePlanError) as exc:
        PlanContext(
            workspace=WS, source_asset_id="x", source_hash={}, collection_id="c",
            game_profile="generic", ontology_version="core-1.4.0", snapshot=None,
            now=AHORA, partida_id=None, known_from_session=4,
        )
    assert "PLAN_SESION_SIN_AMBITO" in str(exc.value)


# --- criterio 6: control negativo -------------------------------------------
def test_control_negativo_sin_la_propagacion_la_prueba_se_pone_roja(
    conexion, tmp_path, monkeypatch
):
    """Se QUITA la propagacion de 6C y se comprueba que vuelve el defecto.

    Es la unica forma de saber que el verde de este fichero lo produce el
    arreglo y no otra cosa. Se neutraliza el unico punto que estampa la sesion
    en el payload; todo lo demas --CLI, contexto, guardias-- sigue en pie.
    """
    driver = conexion.driver
    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    fuente = _fuente(tmp_path, "control-negativo.md",
                     "# Nota de sesion\n\n"
                     "Sela Marrec es miembro de la Cofradia de Ambar.\n")

    monkeypatch.setattr(planner_mod, "_stampar_revelacion",
                        lambda context, operations: operations)
    informe = _corre_partida(fuente, driver, PARTIDA_A, SESION_A1)
    write = informe.get("write")
    assert write is not None, "sin intento de escritura el control no mide nada"
    assert write["outcome"] != "APPLIED", write
    assert "EXEC_REVELACION_NO_DECLARADA" in (write.get("codes") or []), write
    # Y el grafo queda como estaba: el aborto no deja media escritura.
    assert _filas(driver, "MATCH (n:V3Entity) RETURN count(n) AS c")[0]["c"] == 0

    # El grafo se deja limpio para que ningun otro fichero herede este estado.
    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")


def test_la_sesion_declarada_viaja_en_el_payload_de_cada_operacion(mundo):
    """SIGUE EL DATO: lo que sale del planificador es lo que se declaro.

    Se mira el plan, no solo el grafo: si el valor llegase a Neo4j por
    cualquier otro camino que no fuese el payload de la operacion, este
    aserto seria el que lo dijese.
    """
    plan = mundo["informes"]["A2"].get("plan")
    assert plan and plan.get("mutation_operations"), "plan sin operaciones"
    vistos = {op["payload"].get("known_from_session")
              for op in plan["mutation_operations"]}
    assert vistos == {SESION_A2}, json.dumps(sorted(map(str, vistos)))
    assert plan["partida_id"] == PARTIDA_A
    assert plan["scope"]["layer"] == "PARTIDA"
