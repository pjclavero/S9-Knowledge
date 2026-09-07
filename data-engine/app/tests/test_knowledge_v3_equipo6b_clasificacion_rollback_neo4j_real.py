# -*- coding: utf-8 -*-
"""EQUIPO 6B -- el rollback OBSERVA el resultado real y lo CLASIFICA bien.

Ya no se trata de borrar lo correcto: eso funciona (un supervisor independiente
no logro alcanzar `P¬X` y el ciclo devuelve el grafo byte a byte). Se trata de
que la CLASIFICACION del resultado confundia estado legitimo con residuo.

LA DEFINICION QUE SE MIDE, TAL CUAL LA DA EL OPERADOR
-----------------------------------------------------
    PX       = elementos propiedad del apply X
    SHARED   = elementos de PX que siguen sostenidos por estado vivo
    RESIDUE  = elementos de PX que DEBERIAN haber desaparecido
               y siguen presentes

    rollback limpio  <=>  RESIDUE == vacio

LOS DOS DEFECTOS QUE CIERRAN ESTAS PRUEBAS
------------------------------------------
D3. Un rollback EXACTO se reportaba sucio, y el mensaje era falso. Revertir un
    apply dejaba el grafo IDENTICO al estado previo --diff vacio-- y el mando
    decia `UNEXPECTED_RESIDUE`, `clean: false`, `rc=1`, «6 residuos y 6 puntos
    no revertidos», con la frase «procedencia HUERFANA ... nada vivo la
    sostiene». Era falso: las 7 eran ALCANZABLES desde su `V3Source` por
    `HAS_EPISODE`/`HAS_FRAGMENT`. Consecuencia: en cualquier grafo con una
    fuente navegable TODO rollback correcto salia `rc=1`, y un runner no podia
    distinguirlo de uno sucio.

D4. `deleted_anything: true` sobre un grafo VACIO. Repetir el rollback con la
    base en 0 nodos devolvia `ok: true`, `executed: 6`, `deleted_anything:
    true`. No habia borrado nada. Era seguro, pero el HECHO estructurado era
    falso -- y es justo el campo del que la prosa se deriva.

COMO SE MIDE (reglas caras de este proyecto)
--------------------------------------------
* **Censo COMPLETO antes y despues, INCLUIDAS LAS MARCAS** `V3AppliedOperation`.
  Hubo un caso de `residues: []` con una marca viva dentro: misma familia de
  falso limpio, y el censo tiene que verla.
* **Una consulta por cosa contada.** Dos `MATCH` sueltos dan producto
  cartesiano y a menudo CERO filas; `[] == []` demuestra cualquier cosa.
* **Conjunto de partida NO vacio**, comprobado antes de comparar nada.
* Sin `elementId` en ninguna huella: lleva dentro el UUID de la base, no
  sobrevive a un restore y no es identidad de nada.
* **Control negativo**: cada garantia se rompe a proposito y se comprueba que
  la prueba se pone ROJA. Un verde que no puede fallar no prueba nada.

Saltadas por defecto (levantan su propio Neo4j; no tocan produccion)::

    S9K_WRITER_NEO4J_REAL=1 python -m pytest \\
        data-engine/app/tests/test_knowledge_v3_equipo6b_clasificacion_rollback_neo4j_real.py -q
"""
from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("neo4j")

from test_knowledge_v3_writer_neo4j_real import (  # noqa: E402
    neo4j_efimero_conexion,
)
from test_knowledge_v3_tanda3_integracion_neo4j_real import (  # noqa: E402
    WS_B,
    _b_completo,
)
from test_knowledge_v3_equipo4b_mando_rollback_neo4j_real import (  # noqa: E402
    _consulta,
    _guardar,
    ejecutar_mando,
)

from knowledge_v3.writer import cli_rollback  # noqa: E402
from knowledge_v3.writer import rollback_provenance  # noqa: E402
from knowledge_v3.writer.apply_identity import APPLY_ID_FIELD  # noqa: E402
from knowledge_v3.writer.rollback import (  # noqa: E402
    ACTION_PURGE_PROVENANCE,
    SWEEP_OPERATION_ID,
)

LIVE = os.environ.get("S9K_WRITER_NEO4J_REAL", "").strip() == "1"
pytestmark = pytest.mark.skipif(
    not LIVE, reason="Neo4j real efimero: activar con S9K_WRITER_NEO4J_REAL=1"
)


@pytest.fixture(autouse=True)
def _reloj_vivo(monkeypatch):
    """UN ROJO PRESTADO QUE NO ES MIO, y por eso se neutraliza aqui.

    `test_knowledge_v3_tanda3_integracion_neo4j_real` fija
    `AHORA = "2026-09-06T10:00:00Z"` y el plan tiene `plan_ttl_seconds = 86400`,
    asi que caduco el 2026-09-07T10:00Z: desde entonces CUALQUIER llamada a
    `_b_completo` sale `REJECTED` con `PLAN_EXPIRED` -- correctamente, y sin
    relacion alguna con la clasificacion del rollback. Medido: sin esto, la
    primera prueba de este fichero muere en el `apply`, antes de llegar a
    revertir nada.

    Se sustituye por la hora VIVA, que es lo que el mando ve en produccion. No
    se relaja ningun TTL ni se toca el fichero ajeno: se le da al plan un
    `now` que no esta caducado, que es lo unico que faltaba.
    """
    import datetime as _dt

    import test_knowledge_v3_tanda3_integracion_neo4j_real as tanda3

    ahora = (
        _dt.datetime.now(_dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    monkeypatch.setattr(tanda3, "AHORA", ahora)


@pytest.fixture(scope="module")
def conexion():
    with neo4j_efimero_conexion("s9k-6b-clasificacion") as cx:
        yield cx


@pytest.fixture()
def limpio(conexion):
    with conexion.driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    return conexion


# ===========================================================================
# CENSO COMPLETO -- incluidas las marcas
# ===========================================================================
def _huella_nodos(driver) -> list[str]:
    """Un renglon por nodo: etiquetas + TODAS sus propiedades. UNA consulta.

    `V3AppliedOperation` NO se excluye: es un nodo como cualquier otro y entra
    en la huella por construccion. Ese es el punto -- el censo que no la veia
    fue el que declaro `residues: []` con una marca viva dentro.
    """
    filas = _consulta(
        driver, "MATCH (n) RETURN labels(n) AS etiquetas, properties(n) AS props"
    )
    return sorted(
        json.dumps(
            {"labels": sorted(f["etiquetas"]), "props": f["props"]},
            sort_keys=True, ensure_ascii=False, default=str,
        )
        for f in filas
    )


def _huella_aristas(driver) -> list[str]:
    """Un renglon por arista, con los extremos por CONTENIDO. UNA consulta."""
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


def _marcas(driver) -> list[str]:
    """Las `V3AppliedOperation` vivas, por su clave. CONSULTA PROPIA.

    Va aparte de la huella general a proposito: asi un fallo dice «quedo una
    marca» en vez de «la huella difiere», que es lo que hace accionable el
    censo. Y sigue estando dentro de la huella, de modo que ninguna de las dos
    puede taparle el fallo a la otra.
    """
    filas = _consulta(
        driver,
        "MATCH (op:V3AppliedOperation) "
        "RETURN op.idempotency_key AS k, op.plan_hash AS ph",
    )
    return sorted(f"{f['k']}|{f['ph']}" for f in filas)


def censo(driver) -> dict:
    return {
        "nodos": _huella_nodos(driver),
        "aristas": _huella_aristas(driver),
        "marcas": _marcas(driver),
    }


def _cuenta(driver, cypher, params=None) -> int:
    """UNA consulta, UNA cifra. Nunca dos patrones sueltos en la misma."""
    filas = _consulta(driver, cypher, params or {})
    assert len(filas) == 1, f"la consulta de recuento devolvio {len(filas)} filas"
    return int(list(filas[0].values())[0])


# ===========================================================================
# La FUENTE AJENA: procedencia navegable que este apply NO creo
# ===========================================================================
AJENO_APPLY = "apply:6b-ajeno-0000000000000000000000000000000000000000000000"
FUENTE_AJENA = "source:6b-ajena"


def _sembrar_fuente_ajena(driver, ws: str, *, episodios: int = 3) -> None:
    """Una `V3Source` -> `V3Episode` -> `V3Evidence` COMPLETA de OTRO apply.

    Es exactamente la forma del defecto D3: procedencia legitima, navegable
    desde su fuente por `HAS_EPISODE`/`HAS_FRAGMENT`, y SIN ninguna
    `V3Assertion` detras -- porque las aserciones que la citaban ya no existen,
    o porque ese apply solo persistio procedencia. El barrido global la
    denunciaba como «HUERFANA ... nada vivo la sostiene», y era falso: la
    sostiene su fuente.

    Se escribe por Cypher y se DICE: representa un apply ANTERIOR. Fabricar un
    segundo apply real con el writer mediria otra cosa (la idempotencia). Lo
    que aqui se mide es la CLASIFICACION, y para eso basta con que exista
    procedencia navegable que este rollback no creo.
    """
    _consulta(
        driver,
        "CREATE (src:V3Source {workspace:$ws, source_asset_id:$src, "
        "  partida_id: null, apply_id:$aid}) "
        "WITH src UNWIND range(1, $n) AS i "
        "CREATE (src)-[:HAS_EPISODE {workspace:$ws}]->"
        "  (ep:V3Episode {workspace:$ws, episode_id:'episode:6b-ajeno-'+toString(i), "
        "   partida_id: null, apply_id:$aid}) "
        "CREATE (ep)-[:HAS_FRAGMENT {workspace:$ws}]->"
        "  (ev:V3Evidence {workspace:$ws, fragment_id:'fragment:6b-ajeno-'+toString(i), "
        "   partida_id: null, apply_id:$aid, text:'literal ajeno '+toString(i)}) "
        "RETURN count(*) AS c",
        {"ws": ws, "src": FUENTE_AJENA, "aid": AJENO_APPLY, "n": episodios},
    )


def _apply_id_del_documento(doc: dict) -> str:
    """El `apply_id` que el documento declara. Se LEE, no se presume."""
    for i in doc["instructions"]:
        if i["action"] != ACTION_PURGE_PROVENANCE:
            continue
        marca = (i.get("detail") or {}).get(APPLY_ID_FIELD)
        if marca:
            return marca
    pytest.fail(
        "el documento de rollback no declara apply_id en ninguna purga: sin "
        "propiedad declarada no hay conjunto PX que medir"
    )


# ===========================================================================
# CRITERIO 1 -- rollback EXACTO con fuentes AJENAS presentes -> clean, rc=0
# ===========================================================================
def test_rollback_exacto_sale_limpio_aunque_queden_fuentes_de_otros_apply(
    limpio, tmp_path, capsys
):
    """EL CASO QUE HOY FALLA (defecto D3), medido de punta a punta.

    El grafo lleva una fuente AJENA navegable y sin aserciones detras. Se
    aplica, se revierte por el MANDO, y se comprueba:

    * el grafo vuelve a S0 EXACTO --nodos, aristas y marcas--, y
    * el mando lo CLASIFICA como limpio: `ROLLED_BACK`, `clean: true`, `rc=0`.

    Antes de este bloque lo primero ya era cierto y lo segundo no: el mismo
    grafo identico salia `UNEXPECTED_RESIDUE` / `rc=1` denunciando la
    procedencia ajena. Es decir, el producto no podia distinguir un rollback
    correcto de uno sucio en cuanto habia una fuente navegable en la base.
    """
    driver = limpio.driver
    _sembrar_fuente_ajena(driver, WS_B)

    s0 = censo(driver)
    # El conjunto de partida NO esta vacio: sin esto la comparacion final no
    # mediria nada. Y cada cifra sale de SU consulta.
    fuentes_ajenas = _cuenta(
        driver,
        "MATCH (s:V3Source {workspace:$ws, source_asset_id:$id}) RETURN count(s) AS c",
        {"ws": WS_B, "id": FUENTE_AJENA},
    )
    assert fuentes_ajenas == 1, "no se sembro la fuente ajena"
    evidencias_ajenas = _cuenta(
        driver,
        "MATCH (e:V3Evidence {workspace:$ws}) WHERE e.apply_id = $a "
        "RETURN count(e) AS c",
        {"ws": WS_B, "a": AJENO_APPLY},
    )
    assert evidencias_ajenas == 3, evidencias_ajenas
    # Y son EXACTAMENTE la forma del defecto: sin asercion detras, pero
    # alcanzables desde su fuente. Dos consultas, una por cosa.
    sin_asercion = _cuenta(
        driver,
        "MATCH (e:V3Evidence {workspace:$ws}) WHERE e.apply_id = $a "
        "AND NOT EXISTS { MATCH (:V3Assertion)-[:SUPPORTED_BY]->(e) } "
        "RETURN count(e) AS c",
        {"ws": WS_B, "a": AJENO_APPLY},
    )
    assert sin_asercion == 3, sin_asercion
    alcanzables = _cuenta(
        driver,
        "MATCH (:V3Source {workspace:$ws, source_asset_id:$id})"
        "-[:HAS_EPISODE]->(:V3Episode)-[:HAS_FRAGMENT]->(e:V3Evidence) "
        "RETURN count(DISTINCT e) AS c",
        {"ws": WS_B, "id": FUENTE_AJENA},
    )
    assert alcanzables == 3, (
        "la procedencia ajena no es alcanzable desde su fuente: este caso no "
        "reproduce el defecto D3"
    )

    informe = _b_completo(driver)
    assert informe["write"]["outcome"] == "APPLIED", informe["write"]
    s1 = censo(driver)
    assert len(s1["nodos"]) > len(s0["nodos"]), "el apply dijo APPLIED y no crecio"
    assert s1["marcas"], "el apply no dejo ninguna marca: no hay nada que revertir"

    doc = _guardar(tmp_path, informe)
    rc, salida = ejecutar_mando(driver, doc, capsys=capsys)

    s2 = censo(driver)
    # 1. El grafo volvio a S0 EXACTO -- incluidas las MARCAS.
    assert s2 == s0, {
        "nodos_de_mas": [n for n in s2["nodos"] if n not in s0["nodos"]],
        "nodos_de_menos": [n for n in s0["nodos"] if n not in s2["nodos"]],
        "aristas_de_mas": [a for a in s2["aristas"] if a not in s0["aristas"]],
        "marcas_de_mas": [m for m in s2["marcas"] if m not in s0["marcas"]],
    }
    # 2. Y el mando lo clasifica bien. ESTO es lo que fallaba.
    assert salida["outcome"] == "ROLLED_BACK", salida
    assert rc == 0, salida
    assert salida["report"]["residues"] == [], salida["report"]["residues"]
    assert salida["hechos"]["clean"] is True, salida["hechos"]
    # 3. La procedencia ajena SIGUE ahi -- no se la llevo por delante.
    assert _cuenta(
        driver,
        "MATCH (e:V3Evidence {workspace:$ws}) WHERE e.apply_id = $a "
        "RETURN count(e) AS c",
        {"ws": WS_B, "a": AJENO_APPLY},
    ) == 3, "el rollback se llevo procedencia que no era suya"
    # 4. Y se VE, en el canal que no decide el desenlace.
    ajenas_observadas = [
        o for o in salida["report"]["observations"]
        if o["detail"].get("apply_id") == AJENO_APPLY
    ]
    assert ajenas_observadas, (
        "la procedencia ajena ni siquiera se observa: se perdio el recall del "
        "barrido en vez de reclasificarlo"
    )


def test_CONTROL_NEGATIVO_si_el_barrido_ajeno_vuelve_a_ser_residuo_sale_rojo(
    limpio, tmp_path, capsys, monkeypatch
):
    """CALIBRACION de la prueba anterior. Sin esto, aquel verde no prueba nada.

    Se restaura el comportamiento VIEJO --el barrido de ambito etiquetando como
    residuo toda procedencia sin asercion detras-- y se comprueba que el mismo
    rollback EXACTO se pone rojo: `UNEXPECTED_RESIDUE`, `rc != 0`. Si con el
    defecto reinyectado siguiese saliendo limpio, la prueba de arriba estaria
    midiendo otra cosa.
    """
    driver = limpio.driver
    _sembrar_fuente_ajena(driver, WS_B)
    informe = _b_completo(driver)
    doc = _guardar(tmp_path, informe)

    sanos = rollback_provenance.residues

    def residues_como_antes(runner, documento):
        # El defecto, reinyectado: lo observado vuelve a contar como residuo.
        return sanos(runner, documento) + rollback_provenance.observations(
            runner, documento
        )

    monkeypatch.setattr(rollback_provenance, "residues", residues_como_antes)
    rc, salida = ejecutar_mando(driver, doc, capsys=capsys)

    assert salida["report"]["residues"], (
        "con el defecto reinyectado NO aparece ningun residuo: la fuente ajena "
        "no llega al clasificador y la prueba de arriba no mide el defecto D3"
    )
    assert salida["outcome"] == cli_rollback.OUTCOME_UNEXPECTED_RESIDUE, salida
    assert rc != 0, salida


# ===========================================================================
# CRITERIO 2 -- algo de X, no compartido y presente -> INCOMPLETE, rc != 0
# ===========================================================================
def _episodio_propio_huerfano(driver, ws: str, apply_id: str, ident: str) -> None:
    """Un `V3Episode` que X creo, sin padre ni hijos. PX, no compartido.

    Por que este caso ES alcanzable y no un artificio: la cascada de
    `execute_purge` solo llega a los ANTEPASADOS de los fragmentos purgados
    (`ancestors_query`). Un episodio propio que no cuelga de ningun fragmento
    purgado no lo alcanza ninguna instruccion, asi que sobrevive a un rollback
    que se declara completo. Es exactamente «creado por X, no compartido y
    todavia presente» -> `INCOMPLETE`.
    """
    _consulta(
        driver,
        "CREATE (ep:V3Episode {workspace:$ws, episode_id:$id, partida_id: null, "
        "apply_id:$aid}) RETURN ep.episode_id AS id",
        {"ws": ws, "id": ident, "aid": apply_id},
    )


def test_algo_creado_por_X_no_compartido_y_presente_sale_INCOMPLETE(
    limpio, tmp_path, capsys
):
    """El otro lado de la definicion, provocado a proposito.

    Una `Source` o una `Evidence` compartida PUEDE y DEBE sobrevivir; pero algo
    creado por X, NO compartido y todavia presente es `INCOMPLETE`. Se
    comprueba que la reclasificacion no se ha comido esta mitad.
    """
    driver = limpio.driver
    informe = _b_completo(driver)
    doc_json = informe["rollback"]
    apply_id = _apply_id_del_documento(doc_json)
    doc = _guardar(tmp_path, informe)

    # Primera pasada: exacta y limpia. Es la referencia contra la que se mide.
    rc, salida = ejecutar_mando(driver, doc, capsys=capsys)
    assert rc == 0, salida
    assert salida["report"]["residues"] == [], salida["report"]["residues"]

    # Ahora sobrevive algo de X que nada sostiene.
    _episodio_propio_huerfano(driver, WS_B, apply_id, "episode:6b-superviviente")
    presentes = _cuenta(
        driver,
        "MATCH (ep:V3Episode {workspace:$ws, episode_id:$id}) RETURN count(ep) AS c",
        {"ws": WS_B, "id": "episode:6b-superviviente"},
    )
    assert presentes == 1, "no se provoco el superviviente"
    # Y es de X: la propiedad se LEE del grafo, no se presume.
    assert _cuenta(
        driver,
        "MATCH (ep:V3Episode {workspace:$ws, episode_id:$id}) "
        "WHERE ep.apply_id = $a RETURN count(ep) AS c",
        {"ws": WS_B, "id": "episode:6b-superviviente", "a": apply_id},
    ) == 1
    # Y NO esta compartido: ninguna fuente ajena lo cuelga, ninguna evidencia
    # ajena cuelga de el. Dos consultas, una por cosa.
    assert _cuenta(
        driver,
        "MATCH (:V3Source)-[:HAS_EPISODE]->(ep:V3Episode {workspace:$ws, episode_id:$id}) "
        "RETURN count(*) AS c",
        {"ws": WS_B, "id": "episode:6b-superviviente"},
    ) == 0
    assert _cuenta(
        driver,
        "MATCH (ep:V3Episode {workspace:$ws, episode_id:$id})-[:HAS_FRAGMENT]->() "
        "RETURN count(*) AS c",
        {"ws": WS_B, "id": "episode:6b-superviviente"},
    ) == 0

    rc2, salida2 = ejecutar_mando(driver, doc, capsys=capsys)

    assert salida2["outcome"] == cli_rollback.OUTCOME_UNEXPECTED_RESIDUE, salida2
    assert rc2 != 0, salida2
    residuos = salida2["report"]["residues"]
    assert any(
        r["detail"].get("id") == "episode:6b-superviviente" for r in residuos
    ), residuos
    assert salida2["hechos"]["clean"] is False, salida2["hechos"]
    # Y sigue presente: el mando denuncia, no borra a lo bruto.
    assert _cuenta(
        driver,
        "MATCH (ep:V3Episode {workspace:$ws, episode_id:$id}) RETURN count(ep) AS c",
        {"ws": WS_B, "id": "episode:6b-superviviente"},
    ) == 1


def test_CONTROL_NEGATIVO_si_PX_no_se_mide_el_INCOMPLETE_desaparece(
    limpio, tmp_path, capsys, monkeypatch
):
    """CALIBRACION del caso anterior: se rompe la medida de PX y sale rojo.

    Si `owned_residue_query` dejase de encontrar nada --un `WHERE false`, un
    ambito mal derivado, un filtro de mas-- el superviviente de X pasaria
    inadvertido y el mando diria `ROLLED_BACK`. Esta prueba EXIGE que eso
    ocurra al romperlo: demuestra que el verde de arriba lo sostiene de verdad
    la consulta de PX y no algun otro camino.
    """
    driver = limpio.driver
    informe = _b_completo(driver)
    apply_id = _apply_id_del_documento(informe["rollback"])
    doc = _guardar(tmp_path, informe)
    rc, _ = ejecutar_mando(driver, doc, capsys=capsys)
    assert rc == 0
    _episodio_propio_huerfano(driver, WS_B, apply_id, "episode:6b-superviviente")

    sana = rollback_provenance.owned_residue_query

    def rota(workspace, aid, partida_id, label):
        consulta = sana(workspace, aid, partida_id, label)
        # La mutacion: la consulta corre igual y no devuelve NADA.
        return rollback_provenance.RollbackQuery(
            consulta.cypher + " LIMIT 0", consulta.params
        )

    monkeypatch.setattr(rollback_provenance, "owned_residue_query", rota)
    rc2, salida2 = ejecutar_mando(driver, doc, capsys=capsys)

    assert salida2["outcome"] == "ROLLED_BACK", (
        "con la medida de PX rota el mando SIGUE denunciando el superviviente: "
        "entonces el INCOMPLETE no lo sostiene owned_residue_query y la prueba "
        "de arriba mide otra cosa"
    )
    assert rc2 == 0


# ===========================================================================
# CRITERIO 3 -- `deleted_anything` contra los contadores reales
# ===========================================================================
def test_deleted_anything_es_falso_sobre_un_grafo_vacio_y_cierto_cuando_borro(
    limpio, tmp_path, capsys
):
    """DEFECTO D4, medido en las dos direcciones en la MISMA corrida.

    Primera pasada: borra de verdad -> `deleted_anything: true` y contadores
    positivos. Segunda pasada sobre el grafo YA vacio: `executed` sigue siendo
    el mismo (las instrucciones se ejecutan igual) y `deleted_anything` tiene
    que ser FALSO, porque no se borro nada. Ese era el hecho estructurado que
    mentia -- y es el campo del que la prosa se deriva.
    """
    driver = limpio.driver
    informe = _b_completo(driver)
    doc = _guardar(tmp_path, informe)
    nodos_antes = _cuenta(driver, "MATCH (n) RETURN count(n) AS c")
    assert nodos_antes > 0, "el apply no dejo nada: no hay nada que borrar"

    rc1, s1 = ejecutar_mando(driver, doc, capsys=capsys)
    h1 = s1["hechos"]
    assert rc1 == 0, s1
    assert h1["deleted_anything"] is True, h1
    # Y coincide con los contadores, que es la regla literal.
    assert (
        h1["deleted_nodes"] > 0
        or h1["deleted_relationships"] > 0
        or h1["deleted_marks"] > 0
    ), h1
    assert h1["deleted_anything"] == bool(
        h1["deleted_nodes"] or h1["deleted_relationships"] or h1["deleted_marks"]
    )

    # El grafo esta vacio, medido, no supuesto.
    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    assert _cuenta(driver, "MATCH (n) RETURN count(n) AS c") == 0

    rc2, s2 = ejecutar_mando(driver, doc, capsys=capsys)
    h2 = s2["hechos"]
    assert rc2 == 0, s2
    # Las instrucciones SI se ejecutaron: por eso `executed` no sirve de fuente.
    assert h2["executed"] == h1["executed"], (h1["executed"], h2["executed"])
    assert h2["executed"] > 0, h2
    # Y sin embargo NO se borro nada. Este es el arreglo.
    assert h2["deleted_nodes"] == 0, h2
    assert h2["deleted_relationships"] == 0, h2
    assert h2["deleted_marks"] == 0, h2
    assert h2["deleted_anything"] is False, h2
    # La prosa no puede desmentir al hecho: sale de el.
    assert "no se borro NADA" in s2["human"], s2["human"]


def test_CONTROL_NEGATIVO_deleted_anything_derivado_de_executed_vuelve_a_mentir(
    limpio, tmp_path, capsys, monkeypatch
):
    """CALIBRACION del criterio 3: se reinyecta el defecto D4 y sale rojo.

    La causa exacta era `bool(borrados) or bool(report.executed)`: `executed`
    cuenta INSTRUCCIONES EJECUTADAS, no filas borradas. Se restaura esa formula
    y se comprueba que sobre el grafo vacio vuelve a decir `true`. Si no
    volviese a mentir, la prueba de arriba no estaria midiendo la formula.
    """
    driver = limpio.driver
    informe = _b_completo(driver)
    doc = _guardar(tmp_path, informe)
    rc1, _ = ejecutar_mando(driver, doc, capsys=capsys)
    assert rc1 == 0
    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")

    sanos = cli_rollback.rollback_facts

    def hechos_como_antes(outcome, report):
        h = dict(sanos(outcome, report))
        if report is not None:
            h["deleted_anything"] = bool(h["deleted_provenance_nodes"]) or bool(
                report.executed
            )
        return h

    monkeypatch.setattr(cli_rollback, "rollback_facts", hechos_como_antes)
    rc2, s2 = ejecutar_mando(driver, doc, capsys=capsys)

    assert s2["hechos"]["executed"] > 0, s2["hechos"]
    assert s2["hechos"]["deleted_anything"] is True, (
        "con la formula vieja NO vuelve a mentir sobre el grafo vacio: "
        "entonces la prueba del criterio 3 no mide la formula"
    )
    assert rc2 == 0


# ===========================================================================
# CRITERIO 4 -- ningun mensaje afirma algo que el grafo desmienta
# ===========================================================================
def test_ninguna_frase_del_mando_afirma_lo_que_el_grafo_desmiente(
    limpio, tmp_path, capsys
):
    """Se ataca la frase propia: se busca la que se pueda hacer mentir.

    La frase que se atacaba era «No queda nada de esa operacion en el grafo»,
    impresa junto a `clean: true`. Es falsa en cuanto algo de esa operacion se
    CONSERVA por estar compartido, que es legitimo. Ahora la frase solo afirma
    lo que `clean` sostiene --que no queda RESIDUO-- y lo conservado se declara
    aparte, con su cifra.

    Cada afirmacion se contrasta con una consulta al grafo, una por cosa.
    """
    driver = limpio.driver
    _sembrar_fuente_ajena(driver, WS_B)
    informe = _b_completo(driver)
    doc = _guardar(tmp_path, informe)
    rc, salida = ejecutar_mando(driver, doc, capsys=capsys)
    frase = salida["human"]
    hechos = salida["hechos"]
    assert rc == 0, salida

    # La frase vieja, la que podia mentir, ya no se imprime.
    assert "No queda nada de esa operacion en el grafo" not in frase, frase

    # Lo que SI afirma: que no queda residuo. Se contrasta con el grafo.
    assert "No queda ningun residuo de esta operacion en el grafo." in frase, frase
    apply_id = _apply_id_del_documento(informe["rollback"])
    for etiqueta in ("V3Evidence", "V3Episode", "V3Source"):
        vivos = _cuenta(
            driver,
            f"MATCH (n:{etiqueta} {{workspace:$ws}}) WHERE n.apply_id = $a "
            "RETURN count(n) AS c",
            {"ws": WS_B, "a": apply_id},
        )
        assert vivos == 0, (
            f"la frase dice que no queda residuo y quedan {vivos} {etiqueta} "
            f"de este apply"
        )

    # Y las cifras de la frase son las de los contadores, no otras.
    assert f"{hechos['deleted_nodes']} nodos" in frase, (frase, hechos)
    assert f"{hechos['deleted_relationships']} aristas" in frase, (frase, hechos)
    assert f"{hechos['deleted_marks']} marcas" in frase, (frase, hechos)

    # La palabra «limpia» solo puede aparecer negada si `clean` es falso.
    if hechos["clean"]:
        assert "NO es una reversion limpia" not in frase, frase


def test_el_censo_final_ve_una_marca_V3AppliedOperation_superviviente(
    limpio, tmp_path, capsys
):
    """La misma familia de falso limpio, ahora en las MARCAS.

    Hubo un caso de `residues: []` mientras quedaba una `V3AppliedOperation`
    viva: la marca sigue diciendo «esto ya esta aplicado», asi que la relacion
    no se puede reescribir y el grafo queda atascado. El censo tiene que verla,
    y el desenlace no puede salir limpio con ella dentro.
    """
    driver = limpio.driver
    informe = _b_completo(driver)
    doc = _guardar(tmp_path, informe)
    plan_hash = informe["rollback"].get("plan_hash")
    assert plan_hash, "el documento no trae plan_hash: no hay propiedad de la marca"

    rc, salida = ejecutar_mando(driver, doc, capsys=capsys)
    assert rc == 0, salida
    assert _marcas(driver) == [], "la primera pasada dejo marcas vivas"

    # Se reinyecta UNA marca de ESTE apply, colgante por construccion: no queda
    # ni un nodo ni una arista con su clave.
    _consulta(
        driver,
        "CREATE (op:V3AppliedOperation {workspace:$ws, "
        "idempotency_key:'key:6b-colgante', plan_hash:$ph, partida_id: null}) "
        "RETURN op.idempotency_key AS k",
        {"ws": WS_B, "ph": plan_hash},
    )
    assert _marcas(driver), "el censo de marcas no ve la marca que se acaba de crear"
    assert _cuenta(
        driver,
        "MATCH (n {workspace:$ws, idempotency_key:'key:6b-colgante'}) "
        "WHERE NOT n:V3AppliedOperation RETURN count(n) AS c",
        {"ws": WS_B},
    ) == 0, "la marca no esta colgante: hay conocimiento vivo con su clave"

    rc2, salida2 = ejecutar_mando(driver, doc, capsys=capsys)

    assert any(
        r["detail"].get("idempotency_key") == "key:6b-colgante"
        for r in salida2["report"]["residues"]
    ), salida2["report"]["residues"]
    assert salida2["outcome"] == cli_rollback.OUTCOME_UNEXPECTED_RESIDUE, salida2
    assert rc2 != 0, salida2
