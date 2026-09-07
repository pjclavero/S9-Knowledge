# -*- coding: utf-8 -*-
"""El rollback y la procedencia: lo que borra, lo que conserva y lo que dice.

Estas pruebas no necesitan contenedor: corren SIEMPRE. Lo que miden es la
FORMA del documento, de las consultas y del informe. La demostracion contra un
Neo4j real (censo antes/despues en las dos direcciones) vive en
`artifacts/tanda3-r1/demostracion_rollback_procedencia.py`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from knowledge_v3.writer import codes
from knowledge_v3.writer.executor import AppliedOperation
from knowledge_v3.writer.idempotency import InMemoryAppliedKeys, JsonlAppliedKeys
from knowledge_v3.writer.rollback import (
    ACTION_FORGET_APPLIED,
    ACTION_PURGE_PROVENANCE,
    RollbackDocument,
    RollbackInstruction,
    RollbackNotReconstructible,
    build_rollback,
)
from knowledge_v3.writer.rollback_provenance import (
    ancestors_query,
    delete_orphan_episode_query,
    delete_orphan_evidence_query,
    delete_orphan_source_query,
    execute_purge,
    execute_rollback,
    forget_applied_query,
    live_references_query,
    residues,
    rollback_query_for,
)


class VistaFalsa:
    workspace = "leyenda"
    snapshot_id = "snapshot:neo4j:2026-09-01T00:00:00Z"
    plan_hash_value = "a" * 64
    partida_id = None


def _applied_assertion(**kwargs: Any) -> AppliedOperation:
    base = dict(
        operation_id="op:0001",
        operation_type="CREATE_ASSERTION",
        idempotency_key="idem:sha256:" + "b" * 64,
        kind="NODE",
        created_id="assertion:a1",
        target_id="assertion:a1",
        subject_id="entity:ilaria",
        object_id="entity:casa",
        evidence_fragment_ids=["fragment:f1", "fragment:f2"],
    )
    base.update(kwargs)
    return AppliedOperation(**base)


class RunnerFalso:
    """Runner con respuestas guionizadas por FRAGMENTO de consulta.

    Registra todo lo que se le pide: asi una prueba puede afirmar el ORDEN
    (censo de antepasados antes de borrar) y no solo el resultado.
    """

    def __init__(self, respuestas: dict[str, list[dict]] | None = None):
        self.respuestas = respuestas or {}
        self.vistas: list[str] = []

    def run(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict]:
        self.vistas.append(cypher)
        for marca, filas in self.respuestas.items():
            if marca in cypher:
                return list(filas)
        return []


# --- Que ENTRA en el documento --------------------------------------------
def test_el_documento_declara_la_purga_y_el_olvido_de_la_marca():
    doc = build_rollback(VistaFalsa(), [_applied_assertion()])
    acciones = [i.action for i in doc.instructions]
    assert acciones == ["DELETE_NODE", ACTION_PURGE_PROVENANCE, ACTION_FORGET_APPLIED]
    purga = doc.instructions[1]
    assert purga.detail["fragment_ids"] == ["fragment:f1", "fragment:f2"]
    assert purga.detail["workspace"] == "leyenda"


def test_el_delete_node_declara_las_aristas_que_su_detach_se_lleva():
    """El defecto original: el `DETACH DELETE` se llevaba tres tipos de arista
    de procedencia sin decirlo en ninguna parte."""
    doc = build_rollback(VistaFalsa(), [_applied_assertion()])
    tipos = [a["type"] for a in doc.instructions[0].detail["detaches_provenance"]]
    assert tipos == ["SUPPORTED_BY", "SUPPORTED_BY", "HAS_SUBJECT", "HAS_OBJECT"]


def test_sin_evidencia_no_se_inventa_una_purga():
    doc = build_rollback(VistaFalsa(), [_applied_assertion(evidence_fragment_ids=[])])
    assert [i.action for i in doc.instructions] == ["DELETE_NODE", ACTION_FORGET_APPLIED]


# --- Las consultas ---------------------------------------------------------
@pytest.mark.parametrize(
    "constructor",
    [
        lambda: ancestors_query("leyenda", ["fragment:f1"], None),
        lambda: live_references_query("leyenda", ["fragment:f1"], None),
        lambda: delete_orphan_evidence_query("leyenda", ["fragment:f1"], None),
        lambda: delete_orphan_episode_query("leyenda", ["episode:e1"], None),
        lambda: delete_orphan_source_query("leyenda", ["source:s1"], None),
        lambda: forget_applied_query("leyenda", "idem:sha256:" + "b" * 64),
    ],
)
def test_ninguna_consulta_menciona_element_id(constructor):
    query = constructor()
    assert "elementId" not in query.cypher
    assert query.params["ws"] == "leyenda"


def test_el_borrado_exige_cero_referencias_vivas():
    """La condicion NO se fia del censo previo: viaja en el propio borrado."""
    q = delete_orphan_evidence_query("leyenda", ["fragment:f1"], None)
    assert "NOT EXISTS" in q.cypher and "SUPPORTED_BY" in q.cypher
    assert "DETACH DELETE" in q.cypher


def test_el_ambito_falla_cerrado():
    """INTEGRACION tanda 3: el parametro se llama ahora `partida_id`.

    El filtro de ambito de este modulo ya no se define aqui: se llama a
    `rollback.scope_clause`, que es la UNICA definicion del criterio en todo el
    camino de recuperacion. El criterio es el MISMO (`IS NULL` para capa juego,
    igualdad exacta si hay partida); lo que cambia es el nombre del parametro,
    de `$partida` a `$partida_id`.
    """
    sin_partida = delete_orphan_evidence_query("leyenda", ["fragment:f1"], None)
    con_partida = delete_orphan_evidence_query("leyenda", ["fragment:f1"], "partida:1")
    assert "n.partida_id IS NULL" in sin_partida.cypher
    assert "partida_id" not in sin_partida.params
    assert "n.partida_id = $partida_id" in con_partida.cypher
    assert con_partida.params["partida_id"] == "partida:1"


def test_el_ambito_malformado_tambien_se_deniega():
    """Lo que la definicion unificada gana respecto a la que habia aqui.

    `_scope` aceptaba cualquier cosa que no fuese `None` y la metia tal cual
    como si fuese una partida. `scope_clause` valida: una cadena vacia o un
    tipo raro es un ambito incoherente, y un ambito incoherente se deniega.
    """
    for malo in ("", "   ", 7, [], {}):
        with pytest.raises(RollbackNotReconstructible):
            delete_orphan_evidence_query("leyenda", ["fragment:f1"], malo)


def test_el_encaminador_delega_lo_que_no_es_suyo():
    instruccion = RollbackInstruction(
        operation_id="op:0002",
        action="DELETE_RELATIONSHIP",
        target_id="entity:ilaria",
        detail={
            "subject": "entity:ilaria",
            "predicate": "MEMBER_OF",
            "object": "entity:casa",
            "workspace": "leyenda",
            # INTEGRACION tanda 3: el ambito es ahora OBLIGATORIO en el
            # detalle. `None` es la capa juego; el campo AUSENTE se deniega
            # (ver el caso de abajo). Antes del merge con R2 esta instruccion
            # no lo declaraba y aun asi se ejecutaba.
            "partida_id": None,
            "idempotency_key": "idem:sha256:" + "c" * 64,
        },
    )
    query = rollback_query_for(instruccion)
    assert "DELETE r" in query.cypher  # la genera `rollback.rollback_query`
    assert "r.partida_id IS NULL" in query.cypher


def test_el_encaminador_deniega_lo_que_no_declara_ambito():
    """La otra mitad del caso anterior, y la razon de que se le anadiera el
    campo: sin ambito declarado no se borra. Delegar no relaja el fail-closed
    de R2 -- el encaminador delega, y lo delegado deniega."""
    instruccion = RollbackInstruction(
        operation_id="op:0003",
        action="DELETE_RELATIONSHIP",
        target_id="entity:ilaria",
        detail={
            "subject": "entity:ilaria",
            "predicate": "MEMBER_OF",
            "object": "entity:casa",
            "workspace": "leyenda",
            "idempotency_key": "idem:sha256:" + "d" * 64,
        },  # sin `partida_id`: no dice en que ambito borra
    )
    with pytest.raises(RollbackNotReconstructible):
        rollback_query_for(instruccion)


# --- La purga: las dos direcciones -----------------------------------------
def _instruccion_purga(fragmentos: list[str]) -> RollbackInstruction:
    return RollbackInstruction(
        operation_id="op:0001",
        action=ACTION_PURGE_PROVENANCE,
        target_id="assertion:a1",
        detail={
            "workspace": "leyenda",
            "partida_id": None,
            "assertion_id": "assertion:a1",
            "fragment_ids": fragmentos,
            "idempotency_key": "idem:sha256:" + "b" * 64,
        },
    )


def test_la_purga_lee_los_antepasados_ANTES_de_borrar():
    """Si se leyeran despues, las aristas ya no estarian y no habria censo."""
    runner = RunnerFalso({
        "OPTIONAL MATCH (ep:V3Episode)": [
            {"fragment_id": "fragment:f1", "episode_id": "episode:e1",
             "source_asset_id": "source:s1"},
        ],
        "count(a) AS vivas": [
            {"fragment_id": "fragment:f1", "vivas": 0, "referrers": []},
        ],
    })
    execute_purge(runner, _instruccion_purga(["fragment:f1"]))
    primeras = [i for i, q in enumerate(runner.vistas) if "OPTIONAL MATCH (ep:V3Episode)" in q]
    borrados = [i for i, q in enumerate(runner.vistas) if "DETACH DELETE" in q]
    assert primeras and borrados and min(primeras) < min(borrados)


def test_direccion_A_la_evidencia_huerfana_se_borra():
    runner = RunnerFalso({
        "OPTIONAL MATCH (ep:V3Episode)": [
            {"fragment_id": "fragment:f1", "episode_id": "episode:e1",
             "source_asset_id": "source:s1"},
        ],
        "count(a) AS vivas": [
            {"fragment_id": "fragment:f1", "vivas": 0, "referrers": []},
        ],
    })
    informe = execute_purge(runner, _instruccion_purga(["fragment:f1"]))
    assert informe.deleted_evidence == ["fragment:f1"]
    assert informe.deleted_episodes == ["episode:e1"]
    assert informe.deleted_sources == ["source:s1"]
    assert informe.retained_evidence == {}


def test_direccion_B_la_evidencia_compartida_se_conserva_y_se_declara():
    """Lo que hoy pasa por accidente: aqui pasa por CONTAR referencias vivas."""
    runner = RunnerFalso({
        "OPTIONAL MATCH (ep:V3Episode)": [
            {"fragment_id": "fragment:compartido", "episode_id": "episode:e1",
             "source_asset_id": "source:s1"},
        ],
        "count(a) AS vivas": [
            {"fragment_id": "fragment:compartido", "vivas": 1,
             "referrers": ["assertion:viva"]},
        ],
        # El episodio sigue teniendo un fragmento, asi que sobrevive.
        "RETURN n.episode_id AS id": [{"id": "episode:e1"}],
        "RETURN n.source_asset_id AS id": [{"id": "source:s1"}],
    })
    informe = execute_purge(runner, _instruccion_purga(["fragment:compartido"]))
    assert informe.deleted_evidence == []
    assert informe.retained_evidence == {"fragment:compartido": ["assertion:viva"]}
    assert informe.deleted_episodes == [] and informe.deleted_sources == []
    # Y nunca se pidio borrar ese fragmento.
    # Y nunca se pidio borrar un nodo de evidencia: se mira el nodo APUNTADO
    # por el borrado, no que la palabra aparezca (aparece en la guarda del
    # episodio, que si se consulta).
    pedidos = [q for q in runner.vistas
               if "DETACH DELETE" in q and "MATCH (n:V3Evidence" in q]
    assert pedidos == []


# --- La honestidad de `unrecoverable` --------------------------------------
def _documento_con_purga() -> RollbackDocument:
    doc = RollbackDocument(workspace="leyenda", snapshot_id="s", plan_hash="a" * 64)
    doc.instructions = [_instruccion_purga(["fragment:compartido"])]
    return doc


def test_lo_conservado_se_declara_en_unrecoverable():
    runner = RunnerFalso({
        "OPTIONAL MATCH (ep:V3Episode)": [
            {"fragment_id": "fragment:compartido", "episode_id": "episode:e1",
             "source_asset_id": "source:s1"},
        ],
        "count(a) AS vivas": [
            {"fragment_id": "fragment:compartido", "vivas": 1,
             "referrers": ["assertion:viva"]},
        ],
        "RETURN n.episode_id AS id": [{"id": "episode:e1"}],
        "RETURN n.source_asset_id AS id": [{"id": "source:s1"}],
    })
    doc = _documento_con_purga()
    informe = execute_rollback(runner, doc)
    assert doc.unrecoverable, "el documento seguia diciendo `[]`"
    assert any(codes.ROLLBACK_RETAINED_SHARED in u for u in doc.unrecoverable)
    assert informe.residues == []  # compartida no es huerfana: no es residuo


def test_la_evidencia_huerfana_que_sobrevive_es_un_RESIDUO_declarado():
    """El defecto exacto: nodos de procedencia sin nada que los apunte."""
    runner = RunnerFalso({
        "count(a) AS vivas": [
            {"fragment_id": "fragment:compartido", "vivas": 0, "referrers": []},
        ],
        "'nodo' AS clase": [{"clase": "nodo", "cuantos": 0}],
    })
    doc = _documento_con_purga()
    fuera = residues(runner, doc)
    # EQUIPO 6B: sigue siendo RESIDUO --el defecto que este caso cubre no se
    # ha reabierto-- pero la frase ya no dice «HUERFANA». Ese adjetivo era
    # justo el defecto D3: se aplicaba a cualquier procedencia sin asercion
    # detras, incluida la alcanzable desde una `V3Source` viva de OTRO apply.
    # Este documento no declara `apply_id`, asi que PX se aproxima por lo que
    # el documento NOMBRA, y eso es lo que la frase dice ahora.
    assert any("NOMBRADA por el documento" in r["what"] for r in fuera)
    assert any(
        r["detail"].get("fragment_id") == "fragment:compartido" for r in fuera
    )


def test_una_marca_de_idempotencia_superviviente_es_residuo():
    runner = RunnerFalso({
        "'nodo' AS clase": [
            {"clase": "nodo", "cuantos": 0},
            {"clase": "arista", "cuantos": 0},
            {"clase": "marca", "cuantos": 1},
        ],
        "count(a) AS vivas": [],
    })
    doc = _documento_con_purga()
    fuera = residues(runner, doc)
    assert any("marca" in r["what"] for r in fuera)


# --- El almacen de claves: se puede OLVIDAR --------------------------------
def test_el_almacen_en_memoria_olvida():
    store = InMemoryAppliedKeys()
    store.record("k", {"a": 1})
    assert store.is_applied("k")
    assert store.forget("k") is True
    assert store.is_applied("k") is False
    assert store.forget("k") is False


def test_el_almacen_persistente_olvida_SIN_perder_el_rastro(tmp_path: Path):
    ruta = tmp_path / "keys.jsonl"
    store = JsonlAppliedKeys(ruta)
    store.record("k", {"workspace": "leyenda"})
    assert store.forget("k") is True
    lineas = [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lineas) == 2, "el registro append-only perdio historia"
    assert lineas[0]["workspace"] == "leyenda" and lineas[1]["forgotten"] is True
    # Y otra instancia, leyendo el fichero de cero, ve la clave como no aplicada.
    assert JsonlAppliedKeys(ruta).is_applied("k") is False


# --- La poliza no se destruye ----------------------------------------------
def test_un_documento_vacio_no_pisa_la_poliza_existente(tmp_path: Path):
    from knowledge_v3.writer.cli import save_rollback

    destino = tmp_path / "rollback.json"
    lleno = RollbackDocument(workspace="leyenda", snapshot_id="s", plan_hash="a" * 64)
    lleno.instructions = [_instruccion_purga(["fragment:f1"])]
    save_rollback(str(destino), lleno)
    antes = destino.read_text(encoding="utf-8")

    vacio = RollbackDocument(workspace="leyenda", snapshot_id="s", plan_hash="a" * 64)
    informe = save_rollback(str(destino), vacio)
    assert informe["code"] == codes.CLI_ROLLBACK_OUT_PRESERVED
    assert destino.read_text(encoding="utf-8") == antes


def test_el_mando_de_olvido_retira_las_claves_del_documento(tmp_path: Path):
    from knowledge_v3.writer.cli import forget_keys_from_rollback

    doc = RollbackDocument(workspace="leyenda", snapshot_id="s", plan_hash="a" * 64)
    doc.instructions = [_instruccion_purga(["fragment:f1"])]
    ruta = tmp_path / "rollback.json"
    ruta.write_text(json.dumps(doc.to_dict()), encoding="utf-8")

    store = InMemoryAppliedKeys()
    store.record("idem:sha256:" + "b" * 64, {})
    informe = forget_keys_from_rollback(str(ruta), store)
    assert informe["forgotten"] == ["idem:sha256:" + "b" * 64]
    assert store.is_applied("idem:sha256:" + "b" * 64) is False
