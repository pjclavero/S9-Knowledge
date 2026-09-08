# -*- coding: utf-8 -*-
"""INTEGRACION tanda 8: orden canonico de los alias + propiedad durable.

Dos cosas se MIDEN aqui, y ninguna se presume.

1. EL ORDEN DE LOS ALIAS NO PUEDE MOVER LA PROPIEDAD
   -------------------------------------------------
   8A persiste los alias de la entidad DENTRO del `payload`, y `payload` esta
   en `IDEMPOTENCY_KEY_FIELDS`. Luego los alias entran en la
   `idempotency_key`, y por ella en el `ownership_id` que 8B deriva del
   CONJUNTO de claves del apply.

   Que la propiedad NOTE el payload no es un fallo: un payload distinto es una
   operacion logica distinta. El riesgo es otro y es SILENCIOSO: si la lista
   de alias no va canonicamente ordenada, dos corridas del MISMO apply logico
   cuyo catalogo enumere los alias en otro orden producen `ownership_id`
   distintos, y reintroducen el defecto que 8B acaba de cerrar sin romper
   ningun hash visible.

   Se mide extremo a extremo por el planificador REAL (`build_plan` ->
   `seal_plan` -> `compute_idempotency_key` -> `compute_ownership_id`), no
   sobre un payload escrito a mano.

2. LA CALIBRACION
   --------------
   Una prueba de invariancia que no puede ponerse roja no mide nada: si el
   `ownership_id` fuese constante por cualquier otra razon, «sale igual»
   seria vacio. Por eso se comprueba ademas que el mismo montaje SI distingue
   (a) un conjunto de alias distinto y (b) el orden cuando se retira la
   canonizacion. Solo con (a) y (b) rojas significa algo que (1) salga verde.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from knowledge_v3.contracts.base import compute_idempotency_key  # noqa: E402
from knowledge_v3.engine import DEFAULT_CONFIG  # noqa: E402
from knowledge_v3.engine.ontology import ProfileIndex  # noqa: E402
from knowledge_v3.engine.planner import PlanContext, build_plan  # noqa: E402
from knowledge_v3.engine.snapshot import (  # noqa: E402
    InMemoryGraphSnapshot,
    SnapshotEntity,
)
from knowledge_v3.writer.ownership_identity import (  # noqa: E402
    compute_ownership_id,
)
from test_knowledge_v3_engine_gold import (  # noqa: E402,I100
    ASSET_ID,
    COLLECTION_ID,
    GOLD_ENTITIES,
    NOW,
    ONTOLOGY,
    PROFILE_ID,
    SNAPSHOT_ID,
    SOURCE_HASH,
    WORKSPACE,
    claim,
    profile,
    run,
)

#: Las dos superficies del defecto original: el nombre CANONICO y la forma con
#: articulo con la que el texto la nombra. Son justo las que 8A hace persistir.
ALIAS_A = "Cofradia de Ambar"
ALIAS_B = "la Cofradia de Ambar"
ALIAS_C = "Cofradia del Ambar"


def _snapshot_con_alias(alias: tuple[str, ...]) -> InMemoryGraphSnapshot:
    """Snapshot gold donde `entity:casa-ciervo` nace con esos alias, EN ESE ORDEN.

    `pending_creation` es lo unico que enciende un `CREATE_ENTITY`, y solo lo
    enciende una aprobacion humana. Aqui se fija a mano porque lo que se mide
    es el planificador, no la aprobacion.
    """
    nodos = []
    for entity_id, entity_type, version in GOLD_ENTITIES:
        if entity_id == "entity:casa-ciervo":
            nodos.append(
                SnapshotEntity.of(
                    entity_id,
                    entity_type,
                    version,
                    pending_creation=True,
                    canonical_name=ALIAS_A,
                    aliases=alias,
                )
            )
        else:
            nodos.append(SnapshotEntity.of(entity_id, entity_type, version))
    return InMemoryGraphSnapshot.build(
        snapshot_id=SNAPSHOT_ID,
        workspace=WORKSPACE,
        entities=nodos,
        assertions=(),
    )


def _plan_sellado(alias: tuple[str, ...]) -> dict:
    """El plan REAL que el producto emitiria con esos alias descubiertos."""
    snap = _snapshot_con_alias(alias)
    context = PlanContext(
        workspace=WORKSPACE,
        source_asset_id=ASSET_ID,
        source_hash=SOURCE_HASH,
        collection_id=COLLECTION_ID,
        game_profile=PROFILE_ID,
        ontology_version=ONTOLOGY,
        snapshot=snap,
        now=NOW,
    )
    decisions = run([claim()], snap=snap).decisions
    build = build_plan(context, decisions, ProfileIndex(profile()), DEFAULT_CONFIG)
    assert build.plan is not None, "sin plan no hay nada que medir"
    return build.plan.to_dict()


def _ownership_de(plan: dict) -> str:
    """`ownership_id` del apply logico que ese plan describe.

    Mismo material que `writer/apply.py`: workspace + snapshot + el CONJUNTO
    de `idempotency_key` de las operaciones. Nada de reloj.
    """
    return compute_ownership_id(
        workspace=plan["workspace"],
        snapshot_id=plan["snapshot_id"],
        idempotency_keys=[
            compute_idempotency_key(plan, op) for op in plan["mutation_operations"]
        ],
    )


def _alta_de(plan: dict) -> dict:
    altas = [
        op for op in plan["mutation_operations"] if op["operation_type"] == "CREATE_ENTITY"
    ]
    assert altas, "el plan no trae ningun CREATE_ENTITY: no hay alias que medir"
    return altas[0]


# --- LA PROPIEDAD DEL ENUNCIADO -------------------------------------------
def test_el_orden_de_descubrimiento_de_los_alias_no_mueve_el_ownership_id():
    """MISMO apply logico, alias descubiertos en ORDEN DISTINTO -> MISMO `ownership_id`.

    Es la demostracion que pedia 8B. El orden en que un catalogo enumere los
    alias no es un dato del mundo, y no puede decidir de quien son los efectos.
    """
    directo = _plan_sellado((ALIAS_A, ALIAS_B))
    inverso = _plan_sellado((ALIAS_B, ALIAS_A))

    # El conjunto no vacio se comprueba ANTES de comparar: dos planes sin alias
    # tambien saldrian iguales, y eso seria un verde que no mide nada.
    alias_directo = _alta_de(directo)["payload"].get("aliases")
    assert alias_directo, "el payload no lleva alias: la medida no toca el defecto"
    assert set(alias_directo) == {ALIAS_A, ALIAS_B}

    assert _alta_de(inverso)["payload"]["aliases"] == alias_directo, (
        "el planificador NO esta canonizando el orden de los alias"
    )
    assert _ownership_de(directo) == _ownership_de(inverso), (
        "dos corridas del mismo apply logico dan propiedad distinta segun el "
        "orden en que se enumeraron los alias: el defecto que 8B cerro esta "
        "reintroducido en silencio"
    )


# --- CALIBRACION: la medida ANTERIOR puede ponerse roja --------------------
def test_calibracion_un_conjunto_de_alias_distinto_SI_mueve_la_propiedad():
    """Control positivo (a): el montaje distingue cuando debe distinguir."""
    uno = _plan_sellado((ALIAS_A, ALIAS_B))
    otro = _plan_sellado((ALIAS_A, ALIAS_C))
    assert _ownership_de(uno) != _ownership_de(otro), (
        "si esto sale igual, `_ownership_de` no depende del payload y el test "
        "de invariancia de arriba es vacio"
    )


def test_calibracion_sin_canonizar_el_orden_la_propiedad_se_rompe():
    """Control positivo (b): la canonizacion es lo que compra la invariancia.

    Se retira el orden canonico del payload ya sellado --exactamente lo que
    pasaria si `_payload_alta` dejase de ordenar-- y se comprueba que la
    propiedad SE MUEVE. Esto es lo que hace que el verde de arriba signifique
    algo en vez de ser una tautologia.
    """
    plan = _plan_sellado((ALIAS_A, ALIAS_B))
    alias = list(_alta_de(plan)["payload"]["aliases"])
    assert len(alias) > 1, "con un solo alias no hay orden que romper"

    import copy

    revuelto = copy.deepcopy(plan)
    _alta_de(revuelto)["payload"]["aliases"] = list(reversed(alias))

    assert _ownership_de(plan) != _ownership_de(revuelto), (
        "el orden de la lista de alias NO llega al ownership_id; si esto "
        "cambia, revisar IDEMPOTENCY_KEY_FIELDS antes de relajar nada"
    )


def test_el_orden_canonico_es_el_de_sorted_y_deduplica():
    """Que orden es «el canonico» se DECLARA, no se deja al azar.

    Y el alias repetido no puede colarse dos veces: `["x", "x"]` y `["x"]` son
    el mismo conjunto de formas alternativas y deben dar la misma propiedad.
    """
    plan = _plan_sellado((ALIAS_B, ALIAS_A, ALIAS_A))
    alias = _alta_de(plan)["payload"]["aliases"]
    assert alias == sorted({ALIAS_A, ALIAS_B}), alias
    assert _ownership_de(plan) == _ownership_de(_plan_sellado((ALIAS_A, ALIAS_B)))


# --- MIGRACION DE `ownership_clause` A LA PROPIEDAD DURABLE ----------------
# La medida CONTRA GRAFO REAL de esta migracion vive en
# `tests/escenario_integracion_tanda8.py` (el mismo apply logico en una base
# restaurada sigue identificando exactamente su PX). Aqui se fija el
# PREDICADO, que es lo que aquella medida ejercita.
from knowledge_v3.writer.apply_identity import APPLY_ID_FIELD  # noqa: E402
from knowledge_v3.writer.ownership_identity import OWNERSHIP_ID_FIELD  # noqa: E402
from knowledge_v3.writer.rollback import RollbackNotReconstructible  # noqa: E402
from knowledge_v3.writer.rollback_provenance import (  # noqa: E402
    marca_de_detalle,
    ownership_clause,
)

OWN = "own:" + "a" * 32
APP = "apply:" + "b" * 32


def test_la_propiedad_se_reconoce_por_la_marca_DURABLE():
    """El predicado mira `ownership_id`, no solo `apply_id`.

    Es la migracion que 8B dejo declarada y no colada.
    """
    params: dict = {}
    clausula = ownership_clause(
        "n", marca_de_detalle({OWNERSHIP_ID_FIELD: OWN}), params, contexto="t"
    )
    assert f"n.{OWNERSHIP_ID_FIELD}" in clausula, clausula
    assert params["ownership_id"] == OWN


def test_un_grafo_ANTERIOR_a_la_marca_durable_sigue_siendo_clasificable():
    """Fail-OPEN evitado: sin esto, un residuo real dejaria de verse.

    Un nodo escrito antes de que existiera `ownership_id` lleva `apply_id` y
    no lleva la durable. Si el predicado mirase SOLO la durable, ese nodo no
    saldria del conjunto PX y el mando diria `clean` de algo que no lo esta.
    MEDIDO: con el filtro solo por la durable, el INCOMPLETE del equipo 6B
    pasaba de `UNEXPECTED_RESIDUE` a `ROLLED_BACK`.
    """
    params: dict = {}
    clausula = ownership_clause(
        "n", marca_de_detalle({APPLY_ID_FIELD: APP}), params, contexto="t"
    )
    assert f"n.{APPLY_ID_FIELD}" in clausula, clausula
    assert params["apply_id"] == APP


def test_con_las_dos_marcas_el_predicado_es_la_DISYUNCION_y_es_nulo_seguro():
    """Las dos marcas casan por separado, y un `NULL` no es propiedad.

    `NULL = $x` en Cypher es `NULL`, no `false`, y propagado por un `OR` deja
    de leerse a simple vista. Se decide explicitamente con `coalesce`.
    """
    params: dict = {}
    clausula = ownership_clause(
        "n",
        marca_de_detalle({OWNERSHIP_ID_FIELD: OWN, APPLY_ID_FIELD: APP}),
        params,
        contexto="t",
    )
    assert " OR " in clausula, clausula
    assert clausula.count("coalesce(") == 2, clausula
    assert params == {"ownership_id": OWN, "apply_id": APP}


def test_sin_marca_el_radio_es_el_ANTIGUO_y_no_se_disfraza():
    """`true` es el radio `run`. La propiedad solo estrecha; nunca amplia."""
    assert ownership_clause("n", marca_de_detalle({}), {}, contexto="t") == "true"


def test_una_marca_malformada_NO_autoriza_a_borrar():
    """Filtrar por una marca que no distingue nada es peor que no filtrar:
    pareceria acotado. Fail-closed."""
    with pytest.raises(RollbackNotReconstructible):
        ownership_clause("n", "own:no-es-un-resumen", {}, contexto="t")


def test_la_marca_que_ROTULA_el_informe_es_la_durable():
    """Un residuo anunciado bajo `apply_id` diria que pertenece a un INTENTO
    concreto, que es justo lo que la propiedad dejo de ser."""
    prop = marca_de_detalle({OWNERSHIP_ID_FIELD: OWN, APPLY_ID_FIELD: APP})
    assert prop.principal == OWN
    assert set(prop.marcas) == {OWN, APP}
