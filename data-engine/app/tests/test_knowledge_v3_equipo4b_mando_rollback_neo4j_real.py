# -*- coding: utf-8 -*-
"""EQUIPO 4B -- lo que el producto aplica, el producto lo revierte EXACTO.

Una sola propiedad, medida contra un Neo4j real y por la RUTA DE OPERADOR:

    producto apply    -> genera el documento de rollback
    producto rollback -> lo EJECUTA de verdad

Antes de este bloque el segundo mando no existia. `execute_rollback` vivia en
la libreria y ningun CLI la exponia: el unico mando vecino
(`--forget-applied-keys`) dice literalmente que «no toca el grafo». Revertir
exigia escribir Python, es decir abandonar la ruta de operador. Los casos de
abajo no estaban fallados: estaban INALCANZABLES.

COMO SE MIDE (y por que asi)
----------------------------
* **Censo COMPLETO antes y despues**, no recuentos parciales. La huella de
  cada nodo y de cada arista se calcula con TODAS sus propiedades y SIN
  `elementId`: el `elementId` lleva dentro el UUID de la base, no es identidad
  de nada y no sobrevive a un restore.
* **Nunca dos `MATCH` sueltos en la misma consulta**: eso da producto
  cartesiano, a menudo cero filas, y un `[] == []` que parece un verde. Cada
  censo va en su propia consulta.
* **Se comprueba que el conjunto de partida NO esta vacio** antes de comparar
  nada.

Saltadas por defecto (levantan su propio Neo4j; no tocan produccion):

    S9K_WRITER_NEO4J_REAL=1 python -m pytest \
        data-engine/app/tests/test_knowledge_v3_equipo4b_mando_rollback_neo4j_real.py -q
"""
from __future__ import annotations

import contextlib
import json
import os

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("neo4j")

from test_knowledge_v3_writer_neo4j_real import (  # noqa: E402
    ConexionEfimera,
    neo4j_efimero_conexion,
)
from test_knowledge_v3_tanda3_integracion_neo4j_real import (  # noqa: E402
    WS_B,
    _b_completo,
)

from knowledge_v3.writer import cli_rollback  # noqa: E402
from knowledge_v3.writer.rollback import (  # noqa: E402
    ACTION_PURGE_PROVENANCE,
    SWEEP_OPERATION_ID,
)

LIVE = os.environ.get("S9K_WRITER_NEO4J_REAL", "").strip() == "1"
pytestmark = pytest.mark.skipif(
    not LIVE, reason="Neo4j real efimero: activar con S9K_WRITER_NEO4J_REAL=1"
)

ENTORNO_AUTORIZADO = {
    "S9K_ALLOW_REAL_INGEST": "1",
    "S9K_WRITER_WORKSPACE": WS_B,
}


# --- infraestructura --------------------------------------------------------
# Dos bases hacen falta (el caso E las exige) y por defecto cada una se levanta
# sola. En una maquina cargada eso da ROJOS FALSOS -- medido: con cuatro Neo4j
# ajenos y una pila de otro proyecto corriendo a la vez, el contenedor efimero
# no llego a aceptar conexiones en 180 s y las diez pruebas «fallaron» sin que
# el codigo tuviera nada que ver. Por eso se puede declarar una base ya viva:
#
#   S9K_4B_NEO4J_URI / _USER / _PASSWORD_FILE   (base principal)
#   S9K_4B_NEO4J_URI_B / ...                    (la SEGUNDA, para el caso E)
#
# La contrasena se declara por CAMINO de fichero, nunca por variable con el
# secreto dentro ni por linea de mando.
@contextlib.contextmanager
def _conexion_declarada(sufijo: str, prefijo_efimero: str):
    uri = os.environ.get(f"S9K_4B_NEO4J_URI{sufijo}")
    fichero = os.environ.get(f"S9K_4B_NEO4J_PASSWORD_FILE{sufijo}")
    if not uri or not fichero:
        with neo4j_efimero_conexion(prefijo_efimero) as cx:
            yield cx
        return
    import neo4j as _neo4j

    from knowledge_v3.driver_neo4j import read_secret
    from knowledge_v3.writer import bootstrap_writer_schema

    user = os.environ.get(f"S9K_4B_NEO4J_USER{sufijo}", "neo4j")
    driver = _neo4j.GraphDatabase.driver(uri, auth=(user, read_secret(fichero)))
    try:
        driver.verify_connectivity()
        bootstrap_writer_schema(driver)
        yield ConexionEfimera(driver=driver, uri=uri, user=user, password="")
    finally:
        driver.close()


@pytest.fixture(scope="module")
def conexion():
    with _conexion_declarada("", "s9k-4b-rollback") as cx:
        yield cx


@pytest.fixture()
def limpio(conexion):
    with conexion.driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    return conexion


# --- CENSO COMPLETO, sin elementId -----------------------------------------
def _consulta(driver, cypher, params=None):
    with driver.session() as s:
        return [r.data() for r in s.run(cypher, params or {})]


def _huella_nodos(driver) -> list[str]:
    """Un renglon por nodo: etiquetas + TODAS sus propiedades, ordenadas.

    Sin `elementId` y sin `id(n)`. Consulta unica sobre `(n)`, sin segundo
    patron: nada de producto cartesiano.
    """
    filas = _consulta(
        driver,
        "MATCH (n) RETURN labels(n) AS etiquetas, properties(n) AS props",
    )
    return sorted(
        json.dumps(
            {"labels": sorted(f["etiquetas"]), "props": f["props"]},
            sort_keys=True, ensure_ascii=False, default=str,
        )
        for f in filas
    )


def _huella_aristas(driver) -> list[str]:
    """Un renglon por arista: tipo + propiedades + huella de los DOS extremos.

    Los extremos se identifican por sus propiedades, no por `elementId`, para
    que la huella sea comparable entre bases distintas.
    """
    filas = _consulta(
        driver,
        "MATCH (a)-[r]->(b) RETURN type(r) AS tipo, properties(r) AS props, "
        "labels(a) AS la, properties(a) AS pa, labels(b) AS lb, properties(b) AS pb",
    )
    return sorted(
        json.dumps(
            {
                "type": f["tipo"], "props": f["props"],
                "from": {"labels": sorted(f["la"]), "props": f["pa"]},
                "to": {"labels": sorted(f["lb"]), "props": f["pb"]},
            },
            sort_keys=True, ensure_ascii=False, default=str,
        )
        for f in filas
    )


def censo(driver) -> dict:
    """El estado COMPLETO del grafo por contenido. Es lo que se compara."""
    return {"nodos": _huella_nodos(driver), "aristas": _huella_aristas(driver)}


def _por_etiqueta(driver) -> dict:
    filas = _consulta(
        driver,
        "MATCH (n) UNWIND labels(n) AS e RETURN e AS etiqueta, count(*) AS c",
    )
    return {f["etiqueta"]: f["c"] for f in filas}


def _evidencias_huerfanas(driver, ws: str) -> list[str]:
    """Evidencia que sigue en el grafo y NADIE vivo sostiene.

    `OPTIONAL MATCH` encadenado sobre la MISMA `ev`: una sola consulta, sin
    segundo patron suelto.
    """
    filas = _consulta(
        driver,
        "MATCH (ev:V3Evidence {workspace:$ws}) "
        "OPTIONAL MATCH (a:V3Assertion)-[:SUPPORTED_BY]->(ev) "
        "WITH ev, count(a) AS vivas WHERE vivas = 0 "
        "RETURN ev.fragment_id AS fid",
        {"ws": ws},
    )
    return sorted(f["fid"] for f in filas)


# --- el mando de operador ---------------------------------------------------
def ejecutar_mando(driver, doc_path, *, execute=True, env=ENTORNO_AUTORIZADO,
                   workspace=WS_B, capsys=None):
    """Invoca el MANDO, no la libreria. `driver_factory` sustituye la conexion.

    Lo que se sustituye es solo COMO se llega al servidor; el resto del mando
    --autorizacion, ambito fail-closed, desenlace y rc-- corre entero. La
    lectura del secreto de fichero 0600 se prueba aparte, sin Neo4j.
    """
    argv = [str(doc_path), "--workspace", workspace, "--operator", "pjc"]
    if execute:
        argv.append("--execute")
    rc = cli_rollback.main(argv, driver_factory=lambda: driver, env=dict(env))
    salida = capsys.readouterr().out if capsys is not None else ""
    return rc, (json.loads(salida) if salida else None)


def _guardar(tmp_path, informe, nombre="rollback.json"):
    destino = tmp_path / nombre
    destino.write_text(
        json.dumps(informe["rollback"], ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return destino


def _fragmento_compartido(driver, ws: str) -> str:
    """Un `fragment_id` que el apply creo y que alguna asercion CITA."""
    filas = _consulta(
        driver,
        "MATCH (a:V3Assertion {workspace:$ws})-[:SUPPORTED_BY]->(ev:V3Evidence) "
        "RETURN ev.fragment_id AS fid LIMIT 1",
        {"ws": ws},
    )
    assert filas, "ninguna asercion cita evidencia: no hay caso compartido que probar"
    return filas[0]["fid"]


def _asercion_ajena_viva(driver, ws: str, fragment_id: str) -> None:
    """Otra asercion VIVA apuntando a esa evidencia.

    Se escribe por Cypher a proposito y se dice: representa un apply ANTERIOR
    de otro plan que comparte fuente. El producto no tiene un mando para
    fabricar un segundo apply sobre la misma evidencia dentro de una prueba, y
    fingirlo con un segundo `run_ingest` mediria otra cosa (la idempotencia,
    que es de 4A). Lo que aqui se mide es la CONSERVACION, y para eso basta
    con que exista un referente vivo que el rollback no creo.
    """
    _consulta(
        driver,
        "MATCH (ev:V3Evidence {workspace:$ws, fragment_id:$fid}) "
        "CREATE (a:V3Assertion {workspace:$ws, assertion_id:'assertion:ajena:4b', "
        "partida_id: ev.partida_id}) "
        "CREATE (a)-[:SUPPORTED_BY {workspace:$ws}]->(ev) "
        "RETURN a.assertion_id AS id",
        {"ws": ws, "fid": fragment_id},
    )


# ===========================================================================
# LA PROPIEDAD: apply -> rollback por mando -> S0 EXACTO
# ===========================================================================
def test_el_mando_de_operador_devuelve_el_grafo_a_S0_exacto(limpio, tmp_path, capsys):
    driver = limpio.driver
    s0 = censo(driver)

    informe = _b_completo(driver)
    assert informe["write"]["outcome"] == "APPLIED", informe["write"]
    s1 = censo(driver)
    # El conjunto de partida NO esta vacio: sin esto la comparacion final no
    # mediria nada (`[] == []` demuestra cualquier cosa).
    assert s1["nodos"], "el apply dijo APPLIED y el grafo esta vacio"
    assert len(s1["nodos"]) > len(s0["nodos"])
    assert s1["aristas"], "sin aristas no hay cadena de procedencia que revertir"

    doc = _guardar(tmp_path, informe)
    rc, salida = ejecutar_mando(driver, doc, capsys=capsys)

    assert salida["outcome"] == "ROLLED_BACK", salida
    assert rc == 0, salida
    assert salida["report"]["residues"] == [], salida["report"]["residues"]
    assert salida["report"]["unrecoverable"] == [], salida["report"]["unrecoverable"]

    s2 = censo(driver)
    assert s2 == s0, {
        "nodos_de_mas": [n for n in s2["nodos"] if n not in s0["nodos"]],
        "aristas_de_mas": [a for a in s2["aristas"] if a not in s0["aristas"]],
    }


# ===========================================================================
# EL DEFECTO SOSPECHADO: PURGE_PROVENANCE llevaba UN solo fragment_id
# ===========================================================================
def test_el_documento_cubre_TODA_la_procedencia_que_el_apply_persistio(limpio, tmp_path):
    """La sospecha del supervisor, confirmada y cerrada.

    Medido: el apply persiste TODOS los fragmentos y episodios de la corrida
    (`provenance.persist_provenance`), los cite una asercion o no, mientras
    `build_rollback` solo sabe de los que cada asercion CITA. Sin el barrido,
    el documento nombraba un subconjunto y el rollback dejaba el resto
    huerfano -- con el literal de la fuente dentro.
    """
    driver = limpio.driver
    informe = _b_completo(driver)
    doc = informe["rollback"]

    en_grafo = {
        f["fid"]
        for f in _consulta(
            driver,
            "MATCH (ev:V3Evidence {workspace:$ws}) RETURN ev.fragment_id AS fid",
            {"ws": WS_B},
        )
    }
    assert en_grafo, "el apply no persistio evidencia: no hay nada que cubrir"

    citados = set()
    barridos = set()
    for i in doc["instructions"]:
        if i["action"] != ACTION_PURGE_PROVENANCE:
            continue
        destino = barridos if i["operation_id"] == SWEEP_OPERATION_ID else citados
        destino.update(i["detail"]["fragment_ids"])

    # La forma del defecto: lo CITADO es un subconjunto propio de lo persistido.
    assert citados < en_grafo, (
        "este corpus no reproduce el defecto (todo lo persistido esta citado); "
        f"citados={sorted(citados)} en_grafo={sorted(en_grafo)}"
    )
    # Y el barrido lo cubre entero.
    assert barridos >= en_grafo, sorted(en_grafo - barridos)


def test_sin_el_barrido_el_rollback_deja_procedencia_huerfana(limpio, tmp_path, capsys):
    """CALIBRACION: la prueba anterior se pone ROJA si se quita el barrido.

    Se ejecuta el MISMO documento con la instruccion de barrido retirada. Si
    tras eso no quedase procedencia huerfana, la garantia no estaria sostenida
    por el barrido y esta prueba no mediria nada.
    """
    driver = limpio.driver
    informe = _b_completo(driver)
    mutilado = dict(informe["rollback"])
    mutilado["instructions"] = [
        i for i in mutilado["instructions"]
        if i["operation_id"] != SWEEP_OPERATION_ID
    ]
    destino = tmp_path / "sin-barrido.json"
    destino.write_text(json.dumps(mutilado, ensure_ascii=False), encoding="utf-8")

    rc, salida = ejecutar_mando(driver, destino, capsys=capsys)

    huerfanas = _evidencias_huerfanas(driver, WS_B)
    assert huerfanas, "sin barrido NO quedo nada huerfano: el barrido no sostiene nada"
    # Y el mando NO miente sobre ello: ni desenlace limpio ni rc=0.
    assert salida["outcome"] == "INCOMPLETE", salida
    assert rc != 0
    assert any("HUERFANA" in u for u in salida["report"]["unrecoverable"]), salida


# ===========================================================================
# LOS SEIS CASOS, con censo completo antes y despues
# ===========================================================================
def test_casos_A_B_C_D_conservacion_y_limpieza(limpio, tmp_path, capsys):
    """A + B + C + D en la MISMA corrida, que es como conviven de verdad.

    A. procedencia EXCLUSIVA del apply      -> desaparece
    B. Evidence compartida por otra viva    -> permanece (y se DECLARA)
    C. Episode/Source sin referencias vivas -> desaparece
    D. Episode/Source aun compartido        -> permanece
    """
    driver = limpio.driver
    s0 = censo(driver)
    informe = _b_completo(driver)
    assert informe["write"]["outcome"] == "APPLIED"

    compartido = _fragmento_compartido(driver, WS_B)
    _asercion_ajena_viva(driver, WS_B, compartido)

    antes = censo(driver)
    antes_etiquetas = _por_etiqueta(driver)
    assert antes_etiquetas.get("V3Evidence", 0) > 1, antes_etiquetas
    assert antes_etiquetas.get("V3Episode", 0) >= 1, antes_etiquetas
    assert antes_etiquetas.get("V3Source", 0) >= 1, antes_etiquetas

    # Episodio y fuente del fragmento compartido: son los que deben SOBREVIVIR.
    ancestros = _consulta(
        driver,
        "MATCH (src:V3Source)-[:HAS_EPISODE]->(ep:V3Episode)-[:HAS_FRAGMENT]->"
        "(ev:V3Evidence {workspace:$ws, fragment_id:$fid}) "
        "RETURN ep.episode_id AS ep, src.source_asset_id AS src",
        {"ws": WS_B, "fid": compartido},
    )
    assert ancestros, "el fragmento compartido no tiene cadena: no hay caso D"
    episodio_vivo = ancestros[0]["ep"]
    fuente_viva = ancestros[0]["src"]

    doc = _guardar(tmp_path, informe)
    rc, salida = ejecutar_mando(driver, doc, capsys=capsys)

    despues = censo(driver)
    etiquetas = _por_etiqueta(driver)
    purgas = salida["report"]["purges"]
    borradas = {f for p in purgas for f in p["deleted_evidence"]}
    conservadas = {f for p in purgas for f in p["retained_evidence"]}

    # --- B: la evidencia compartida SIGUE, y el informe lo declara ----------
    assert compartido in conservadas, purgas
    quedan = {
        f["fid"] for f in _consulta(
            driver,
            "MATCH (ev:V3Evidence {workspace:$ws}) RETURN ev.fragment_id AS fid",
            {"ws": WS_B},
        )
    }
    assert compartido in quedan, "la evidencia COMPARTIDA se borro"
    assert any("ROLLBACK_RETAINED_SHARED" in u for u in salida["report"]["unrecoverable"])

    # --- A: la exclusiva desaparecio ---------------------------------------
    assert borradas, "no se borro ninguna evidencia: el caso A no se midio"
    assert not (borradas & quedan), sorted(borradas & quedan)

    # --- D: el episodio y la fuente del compartido SIGUEN -------------------
    assert episodio_vivo in {
        f["id"] for f in _consulta(
            driver, "MATCH (n:V3Episode {workspace:$ws}) RETURN n.episode_id AS id",
            {"ws": WS_B})
    }
    assert fuente_viva in {
        f["id"] for f in _consulta(
            driver, "MATCH (n:V3Source {workspace:$ws}) RETURN n.source_asset_id AS id",
            {"ws": WS_B})
    }

    # --- C: los episodios que se quedaron sin fragmentos desaparecieron -----
    assert etiquetas.get("V3Episode", 0) < antes_etiquetas["V3Episode"], {
        "antes": antes_etiquetas, "despues": etiquetas,
    }
    borrados_ep = {e for p in purgas for e in p["deleted_episodes"]}
    assert borrados_ep, purgas
    assert episodio_vivo not in borrados_ep

    # --- el desenlace NO es limpio, y el rc lo dice -------------------------
    assert salida["outcome"] == "INCOMPLETE", salida
    assert rc != 0
    assert "NO es una reversion limpia" in salida["human"]

    # --- censo completo: lo unico que sobra respecto de S0 es lo compartido --
    sobran = [n for n in despues["nodos"] if n not in s0["nodos"]]
    assert sobran, "nada sobrevivio: el caso de conservacion no se midio"
    etiquetas_sobrantes = {
        e for n in sobran for e in json.loads(n)["labels"]
    }
    assert etiquetas_sobrantes <= {
        "V3Evidence", "V3Episode", "V3Source", "V3Assertion",
    }, etiquetas_sobrantes
    assert len(despues["nodos"]) < len(antes["nodos"])


def test_caso_E_el_documento_se_ejecuta_contra_OTRA_base(limpio, tmp_path, capsys):
    """E. Ninguna consulta depende de `elementId`.

    Demostrado ejecutando el documento de UNA base contra OTRA DISTINTA. Dentro
    de la misma base los ids se reutilizan y la comparacion no mediria nada: el
    `elementId` lleva el UUID de la base, asi que solo cambiando de base se
    garantiza que ninguno coincide.
    """
    driver_a = limpio.driver
    informe_a = _b_completo(driver_a)
    assert informe_a["write"]["outcome"] == "APPLIED"
    doc = _guardar(tmp_path, informe_a)
    ids_a = {
        f["eid"] for f in _consulta(
            driver_a, "MATCH (n) RETURN elementId(n) AS eid")
    }
    assert ids_a, "base A vacia"

    with _conexion_declarada("_B", "s9k-4b-otra-base") as otra:
        driver_b = otra.driver
        s0_b = censo(driver_b)
        informe_b = _b_completo(driver_b)
        assert informe_b["write"]["outcome"] == "APPLIED"
        s1_b = censo(driver_b)
        assert s1_b["nodos"], "base B vacia tras el apply"

        ids_b = {
            f["eid"] for f in _consulta(
                driver_b, "MATCH (n) RETURN elementId(n) AS eid")
        }
        # La premisa de la prueba, OBSERVADA: ningun elementId se repite.
        assert not (ids_a & ids_b), sorted(ids_a & ids_b)

        # El documento de A, tal cual, ejecutado sobre B.
        rc, salida = ejecutar_mando(driver_b, doc, capsys=capsys)
        assert salida["outcome"] == "ROLLED_BACK", salida
        assert rc == 0
        assert censo(driver_b) == s0_b, salida


def test_caso_F_el_mando_ejecutado_dos_veces_es_seguro(limpio, tmp_path, capsys):
    """F. Segunda pasada: ni corrupcion ni exito falso."""
    driver = limpio.driver
    s0 = censo(driver)
    informe = _b_completo(driver)
    doc = _guardar(tmp_path, informe)

    rc1, salida1 = ejecutar_mando(driver, doc, capsys=capsys)
    assert rc1 == 0 and salida1["outcome"] == "ROLLED_BACK", salida1
    tras_primera = censo(driver)
    assert tras_primera == s0

    rc2, salida2 = ejecutar_mando(driver, doc, capsys=capsys)
    # No corrompe: el grafo no se movio.
    assert censo(driver) == tras_primera, salida2
    # No inventa exito: no dice haber borrado nada la segunda vez.
    borrados2 = sum(
        len(p["deleted_evidence"]) + len(p["deleted_episodes"]) + len(p["deleted_sources"])
        for p in salida2["report"]["purges"]
    )
    assert borrados2 == 0, salida2["report"]["purges"]
    # Y los fragmentos que ya no estaban se declaran ausentes, no borrados.
    assert any(p["absent"] for p in salida2["report"]["purges"]), salida2
    assert rc2 == 0 and salida2["outcome"] == "ROLLED_BACK", salida2


# ===========================================================================
# Reglas de seguridad: las mismas que el APPLY, sin aflojar ninguna
# ===========================================================================
def test_sin_autorizacion_de_operador_el_mando_no_borra_nada(limpio, tmp_path, capsys):
    driver = limpio.driver
    informe = _b_completo(driver)
    antes = censo(driver)
    doc = _guardar(tmp_path, informe)

    rc, salida = ejecutar_mando(driver, doc, env={}, capsys=capsys)
    assert salida["outcome"] == "BLOCKED", salida
    assert salida["code"] == "CLI_ROLLBACK_NOT_AUTHORIZED"
    assert rc != 0
    assert censo(driver) == antes, "BLOCKED y aun asi toco el grafo"


def test_workspace_distinto_del_documento_se_deniega(limpio, tmp_path, capsys):
    driver = limpio.driver
    informe = _b_completo(driver)
    antes = censo(driver)
    doc = _guardar(tmp_path, informe)

    rc, salida = ejecutar_mando(driver, doc, workspace="otro-ws", capsys=capsys)
    assert salida["outcome"] == "BLOCKED", salida
    assert salida["code"] == "CLI_ROLLBACK_WORKSPACE_MISMATCH"
    assert rc != 0
    assert censo(driver) == antes


def test_la_simulacion_no_toca_nada_y_sale_con_cero(limpio, tmp_path, capsys):
    driver = limpio.driver
    informe = _b_completo(driver)
    antes = censo(driver)
    doc = _guardar(tmp_path, informe)

    rc, salida = ejecutar_mando(driver, doc, execute=False, env={}, capsys=capsys)
    assert salida["outcome"] == "DRY_RUN", salida
    assert rc == 0
    assert salida["would_execute"], salida
    assert censo(driver) == antes


def test_ambito_ausente_falla_cerrado_y_no_ensucia_el_desenlace(limpio, tmp_path, capsys):
    """Fail-closed: una instruccion sin `partida_id` no se ejecuta, y se dice."""
    driver = limpio.driver
    informe = _b_completo(driver)
    mutilado = json.loads(json.dumps(informe["rollback"]))
    tocadas = 0
    for i in mutilado["instructions"]:
        if i["action"] == "DELETE_NODE":
            i["detail"].pop("partida_id", None)
            tocadas += 1
    assert tocadas, "no habia DELETE_NODE que mutilar"
    destino = tmp_path / "sin-ambito.json"
    destino.write_text(json.dumps(mutilado, ensure_ascii=False), encoding="utf-8")

    rc, salida = ejecutar_mando(driver, destino, capsys=capsys)
    assert salida["outcome"] == "INCOMPLETE", salida
    assert rc != 0
    assert any("fail-closed" in u for u in salida["report"]["unrecoverable"]), salida
    # Los nodos cuyo ambito no se declaro SIGUEN ahi: no se borro "donde sea".
    assert _por_etiqueta(driver).get("V3Assertion", 0) > 0
