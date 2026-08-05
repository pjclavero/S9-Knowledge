# -*- coding: utf-8 -*-
"""Pruebas ADVERSARIALES de M4 (supersesion local, `local_override_of`).

Complementa `test_knowledge_v3_writer_local_override.py` (las 19 pruebas de
M4) atacando exactamente lo que ese fichero no ejercita: el filo falsy del
chequeo `if payload.get("local_override_of")`, la autorreferencia, el orden
de escritura comparado con una creacion normal, dos overrides simultaneos
(misma partida y partidas distintas), la carrera "objetivo creado despues", y
si la ausencia de filtro de `status` en `list_visible_assertions_query`
produce inconsistencias cuando se combina con supersesion temporal
(docs/v3/49 §2.5, requisito 5.e del encargo del AGENTE-DE-TESTS).
"""
from __future__ import annotations

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.writer import codes  # noqa: E402
from knowledge_v3.writer.reads import list_visible_assertions  # noqa: E402
from knowledge_v3.writer.writer import OUTCOME_ABORTED, OUTCOME_APPLIED  # noqa: E402
from test_knowledge_v3_writer import (  # noqa: E402
    HASH_B,
    WORKSPACE,
    FakeDriver,
    admit,
    apply_request,
    ctx,
    game_scope,
    make_plan,
    op_create_assertion,
    partida_scope,
)
from test_knowledge_v3_writer_local_override import (  # noqa: E402
    _FakeReadDriver,
    op_local_override,
)

PARTIDA_A = "partida:brumal-01"
PARTIDA_B = "partida:brumal-02"


def make_writer_for(driver):
    from test_knowledge_v3_writer import make_writer

    return make_writer(driver)


def lore_node(version: int = 2, state_hash: str = HASH_B["value"]) -> dict:
    return {"version": version, "state_hash": state_hash}


def partida_node(partida_id: str, version: int = 2, state_hash: str = HASH_B["value"]) -> dict:
    return {"version": version, "state_hash": state_hash, "partida_id": partida_id}


# ==========================================================================
# 1. El filo FALSY: `if payload.get("local_override_of")` no distingue
#    "ausente" de "presente pero vacio" -- ambos casos saltan el chequeo.
# ==========================================================================
def test_override_vacio_bypassa_el_rechazo_estructural_de_capa_juego():
    """BUG (P1): `local_override_of=""` en un plan de CAPA JUEGO no dispara
    `PLAN_LOCAL_OVERRIDE_FROM_GAME_LAYER`, porque `_local_override_incoherence`
    comprueba `if payload.get("local_override_of")` -- una cadena vacia es
    falsy en Python, exactamente igual que `None` o la clave ausente. El plan
    se ADMITE cuando la intencion (declarar una divergencia local desde capa
    juego) es precisamente la que M4 dice prohibir."""
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:fantasma",
            "entity:daiki", "entity:casa-del-ciervo", "",
        )
    ]
    plan = make_plan(operations=ops, scope=game_scope())
    result = admit(plan, ctx())
    # Comportamiento HOY: se admite. Si esto cambia (endurecimiento futuro:
    # tratar cualquier valor no-None como declaracion de override), este
    # assert debe voltearse -- documentado aqui a proposito.
    assert result.admitted, (
        "si esto falla, el bypass ya esta cerrado: actualiza el hallazgo "
        f"del informe. codigos: {result.codes}"
    )


def test_override_vacio_bypassa_tambien_el_chequeo_de_ejecucion_y_se_escribe():
    """BUG (P1), el otro extremo: como `_check_local_override` usa el MISMO
    chequeo falsy (`if not target: return`), el payload con
    `local_override_of=""` no solo pasa admision -- tambien pasa ejecucion
    SIN NINGUNA validacion contra el estado real, y la cadena vacia queda
    escrita tal cual en la asercion de CAPA JUEGO resultante. Ademas
    `reason_code` tampoco se exige (el chequeo entero se salta), asi que ni
    siquiera hace falta `LOCAL_DIVERGENCE`."""
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:fantasma",
            "entity:daiki", "entity:casa-del-ciervo", "",
            reason_code=None,
        )
    ]
    plan = make_plan(operations=ops, scope=game_scope())
    driver = FakeDriver(nodes={})
    result = make_writer_for(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_APPLIED, result.codes

    create_write = next(
        (q, p) for q, p in driver.writes
        if p.get("props", {}).get("assertion_id") == "assertion:fantasma"
    )
    # La propiedad queda grabada, con el valor vacio, en un nodo SIN
    # `partida_id` -- es decir, en capa juego. `local_override_of=""` en un
    # hecho de capa juego no tiene ningun significado valido segun el diseno
    # (M4 dice: solo una PARTIDA declara divergencia), pero aqui esta.
    assert create_write[1]["props"]["local_override_of"] == ""
    assert create_write[1]["props"]["partida_id"] is None


# ==========================================================================
# 2. Autorreferencia: una asercion que se override-a a si misma.
# ==========================================================================
def test_override_autorreferencia_se_rechaza_pero_no_por_un_codigo_dedicado():
    """La aserción `assertion:auto` declara `local_override_of=assertion:auto`
    (a si misma). No hay ningun chequeo EXPLICITO de autorreferencia para
    `local_override_of` (a diferencia de `supersedes`/`superseded_by`, que si
    lo tienen en `validator.py` a nivel de contrato `fact-assertion`, pero eso
    no se aplica aqui: el writer trabaja sobre el PAYLOAD del plan, no sobre
    un `FactAssertion` ya validado). El rechazo ocurre solo porque, en el
    momento del chequeo, la aserción todavia no existe (es CREATE-only) --
    cae en `EXEC_LOCAL_OVERRIDE_TARGET_MISSING` por una razon incidental, no
    por deteccion de autorreferencia. Documentado como hallazgo: si algun dia
    el orden de chequeos cambia (p.ej. `_assert_absent` deja de ejecutarse
    antes), una autorreferencia dejaria de ser imposible por construccion."""
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:auto",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:auto",
        )
    ]
    plan = make_plan(operations=ops, partida_id=PARTIDA_A, scope=partida_scope(PARTIDA_A))
    driver = FakeDriver(nodes={})
    result = make_writer_for(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_LOCAL_OVERRIDE_TARGET_MISSING in result.codes


# ==========================================================================
# 3. Comparacion de escrituras: override vs creacion normal, MISMO patron.
# ==========================================================================
def test_override_y_creacion_normal_producen_el_mismo_patron_de_escritura():
    """La UNICA diferencia entre crear una asercion normal y crear una de
    override debe ser el contenido del payload (el puntero + el reason_code),
    nunca el NUMERO ni el TIPO de escrituras emitidas contra el driver."""
    normal_ops = [
        op_create_assertion("op:0001", "decision:0001", "assertion:normal", "entity:daiki", "entity:casa-del-ciervo")
    ]
    plan_normal = make_plan(operations=normal_ops, partida_id=PARTIDA_A, scope=partida_scope(PARTIDA_A))
    driver_normal = FakeDriver(nodes={})
    result_normal = make_writer_for(driver_normal).write(plan_normal, apply_request(plan_normal))
    assert result_normal.outcome == OUTCOME_APPLIED, result_normal.codes

    override_ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:divergencia",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:lore-daiki-vivo",
        )
    ]
    plan_override = make_plan(operations=override_ops, partida_id=PARTIDA_A, scope=partida_scope(PARTIDA_A))
    nodes = {("assertion", "assertion:lore-daiki-vivo"): lore_node()}
    driver_override = FakeDriver(nodes=nodes)
    result_override = make_writer_for(driver_override).write(plan_override, apply_request(plan_override))
    assert result_override.outcome == OUTCOME_APPLIED, result_override.codes

    # Mismo NUMERO de escrituras (una sola CREATE) en ambos casos: el
    # override no genera trafico extra de mutacion (solo una lectura extra
    # de verificacion, que no es una escritura).
    assert len(driver_normal.writes) == 1
    assert len(driver_override.writes) == 1

    normal_props = driver_normal.writes[0][1]["props"]
    override_props = driver_override.writes[0][1]["props"]
    keys_extra = set(override_props) - set(normal_props)
    # Las UNICAS claves de mas en el override son el puntero y su razon.
    assert keys_extra == {"local_override_of", "reason_code"}


# ==========================================================================
# 4. Carrera: objetivo de capa juego creado DESPUES del intento de override.
# ==========================================================================
def test_override_reordenado_no_deja_puntero_colgando_y_se_recupera_despues():
    """Si el plan de override llega ANTES de que exista su objetivo de capa
    juego (plan reordenado / carrera), el executor lo caza como
    `EXEC_LOCAL_OVERRIDE_TARGET_MISSING` y ABORTA -- transaccional, nada
    queda escrito ni marcado como aplicado. Una vez el objetivo existe de
    verdad, reintentar EL MISMO plan de override (misma `idempotency_key`)
    aplica limpio: el intento fallido no consumio la clave."""
    override_ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:divergencia",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:lore-tardio",
        )
    ]
    plan_override = make_plan(
        operations=override_ops, partida_id=PARTIDA_A, scope=partida_scope(PARTIDA_A)
    )
    driver = FakeDriver(nodes={})
    writer = make_writer_for(driver)

    first = writer.write(plan_override, apply_request(plan_override))
    assert first.outcome == OUTCOME_ABORTED
    assert codes.EXEC_LOCAL_OVERRIDE_TARGET_MISSING in first.codes
    assert not driver.committed
    assert driver.writes == []

    # Ahora el objetivo de capa juego "llega" (otro plan, capa juego).
    driver.nodes[("assertion", "assertion:lore-tardio")] = lore_node()

    second = writer.write(plan_override, apply_request(plan_override))
    assert second.outcome == OUTCOME_APPLIED, second.codes
    assert second.created_ids == ["assertion:divergencia"]


# ==========================================================================
# 5. Dos overrides sobre el MISMO hecho de lore.
# ==========================================================================
def _graph_dos_partidas_mismo_lore() -> dict[str, dict]:
    return {
        "assertion:lore-daiki-vivo": {
            "partida_id": None, "subject_entity_id": "entity:daiki", "status": "ASSERTED",
        },
        "assertion:divergencia-A": {
            "partida_id": PARTIDA_A, "subject_entity_id": "entity:daiki",
            "local_override_of": "assertion:lore-daiki-vivo", "status": "ASSERTED",
        },
        "assertion:divergencia-B": {
            "partida_id": PARTIDA_B, "subject_entity_id": "entity:daiki",
            "local_override_of": "assertion:lore-daiki-vivo", "status": "ASSERTED",
        },
    }


def test_dos_partidas_distintas_overridean_el_mismo_lore_cada_una_ve_el_suyo():
    """(d) Dos PARTIDAS DISTINTAS overridean el mismo hecho de lore: cada una
    ve unicamente SU PROPIO override, nunca el de la otra ni el lore comun."""
    driver = _FakeReadDriver(_graph_dos_partidas_mismo_lore())

    rows_a = list_visible_assertions(driver, WORKSPACE, PARTIDA_A)
    assert {r.assertion_id for r in rows_a} == {"assertion:divergencia-A"}

    rows_b = list_visible_assertions(driver, WORKSPACE, PARTIDA_B)
    assert {r.assertion_id for r in rows_b} == {"assertion:divergencia-B"}

    # La capa juego, ajena a ambas partidas, sigue viendo el lore intacto.
    rows_game = list_visible_assertions(driver, WORKSPACE, None)
    assert {r.assertion_id for r in rows_game} == {"assertion:lore-daiki-vivo"}


def test_misma_partida_dos_overrides_del_mismo_lore_ambos_visibles_sin_desempate():
    """(d) HALLAZGO (P1): nada impide que la MISMA partida cree DOS
    aserciones distintas con `local_override_of` apuntando al mismo hecho de
    lore (ni `admission.py` ni `executor.py` comprueban unicidad del
    objetivo dentro del ambito). El resultado en lectura es AMBIGUO: las dos
    quedan visibles simultaneamente, sin ningun criterio de desempate (ni
    "el mas reciente gana" ni "se rechaza el segundo") -- dos hechos
    supuestamente incompatibles del mismo sujeto conviven en la vista de una
    sola partida."""
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:divergencia-1",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:lore-daiki-vivo",
        ),
        op_local_override(
            "op:0002", "decision:0001", "assertion:divergencia-2",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:lore-daiki-vivo",
        ),
    ]
    plan = make_plan(operations=ops, partida_id=PARTIDA_A, scope=partida_scope(PARTIDA_A))
    nodes = {("assertion", "assertion:lore-daiki-vivo"): lore_node()}
    driver = FakeDriver(nodes=nodes)
    result = make_writer_for(driver).write(plan, apply_request(plan))
    # El writer los ADMITE Y APLICA a los dos: no hay invariante que lo impida.
    assert result.outcome == OUTCOME_APPLIED, result.codes
    assert set(result.created_ids) == {"assertion:divergencia-1", "assertion:divergencia-2"}

    graph = {
        "assertion:lore-daiki-vivo": {"partida_id": None, "subject_entity_id": "entity:daiki"},
        "assertion:divergencia-1": {
            "partida_id": PARTIDA_A, "subject_entity_id": "entity:daiki",
            "local_override_of": "assertion:lore-daiki-vivo",
        },
        "assertion:divergencia-2": {
            "partida_id": PARTIDA_A, "subject_entity_id": "entity:daiki",
            "local_override_of": "assertion:lore-daiki-vivo",
        },
    }
    read_driver = _FakeReadDriver(graph)
    rows = list_visible_assertions(read_driver, WORKSPACE, PARTIDA_A)
    ids = {r.assertion_id for r in rows}
    # Las DOS quedan visibles: no hay desempate.
    assert ids == {"assertion:divergencia-1", "assertion:divergencia-2"}


# ==========================================================================
# 6. Supersesion del hecho de capa juego con un override colgando.
# ==========================================================================
def test_supersede_del_hecho_de_capa_juego_no_esta_bloqueado_por_overrides_colgantes():
    """No hay ninguna comprobacion de integridad referencial que impida
    supersedir (cerrar vigencia temporal, `SUPERSEDE_ASSERTION`) un hecho de
    capa juego que ya tiene una partida con un `local_override_of` apuntandolo.
    El puntero queda COLGANDO -- apunta a un `assertion_id` que sigue
    existiendo (M4 nunca borra), pero cuyo `status` ya no es el vigente."""
    from test_knowledge_v3_writer import op_supersede

    ops = [op_supersede("op:0001", "decision:0001", "assertion:lore-daiki-vivo")]
    plan = make_plan(operations=ops, scope=game_scope())
    nodes = {("assertion", "assertion:lore-daiki-vivo"): lore_node()}
    driver = FakeDriver(nodes=nodes)
    result = make_writer_for(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_APPLIED, result.codes


def test_hecho_de_capa_juego_ya_superseded_sigue_visible_porque_la_query_no_filtra_status():
    """HALLAZGO (P1/P2, relacionado con lo anterior): `list_visible_assertions_query`
    no filtra por `status` en absoluto (ni `LIVE_STATUSES`, ni excluye
    `SUPERSEDED`/`RETRACTED`). Una asercion de capa juego YA SUSTITUIDA por
    una supersesion temporal normal sigue apareciendo como "visible" en
    cualquier ambito que no la tenga overrideada -- el enmascarado de M4
    resuelve el filo de la DIVERGENCIA LOCAL, pero no sustituye al filtrado
    de vigencia que un consumidor real (M5) tendria que anadir aparte. Esto
    es coherente con que el modulo se declara 'lugar para demostrar el
    enmascarado', pero un consumidor de produccion que use esta funcion tal
    cual mostraria hechos ya superados como si siguieran vigentes."""
    graph = {
        "assertion:lore-daiki-vivo": {
            "partida_id": None, "subject_entity_id": "entity:daiki",
            "status": "SUPERSEDED", "superseded_by": "assertion:lore-daiki-vivo-v2",
        },
    }
    driver = _FakeReadDriver(graph)
    rows = list_visible_assertions(driver, WORKSPACE, PARTIDA_A)
    ids = {r.assertion_id for r in rows}
    # Sigue "visible" pese a estar SUPERSEDED: la funcion no lo filtra.
    assert ids == {"assertion:lore-daiki-vivo"}


# ==========================================================================
# 7. Override + supersesion temporal SIMULTANEOS dentro de la misma partida
#    (requisito 5.e del encargo).
# ==========================================================================
def test_override_superseded_dentro_de_la_partida_deja_lore_enmascarado_y_ambas_versiones_visibles():
    """(e) El hecho local A override-a al lore; luego, DENTRO de la misma
    partida, A es superseded por B (supersesion temporal normal, ej. nueva
    evidencia sobre el mismo hecho local). Semantica observada:

    - El lore de capa juego SIGUE enmascarado (el `NOT EXISTS` solo comprueba
      que EXISTA alguna asercion de la partida con `local_override_of`
      apuntando a el -- A la sigue teniendo aunque A este SUPERSEDED, porque
      M4 nunca toca `local_override_of` al cerrar una vigencia temporal).
    - Pero A (ya SUPERSEDED) y B (la version vigente) aparecen LAS DOS en la
      lista de visibles, porque la funcion no filtra `status` (ver hallazgo
      anterior). Una partida que consulte esta funcion veria DOS hechos del
      mismo sujeto donde debería ver solo uno (B) y el lore permanecería
      oculto por una versión que ya no es la vigente.

    Se documenta como semantica CUESTIONABLE, no como assert de "correcto":
    el AGENTE-DE-TESTS decide reportarlo, no dictaminar."""
    graph = {
        "assertion:lore-daiki-vivo": {
            "partida_id": None, "subject_entity_id": "entity:daiki", "status": "ASSERTED",
        },
        "assertion:divergencia-A": {
            "partida_id": PARTIDA_A, "subject_entity_id": "entity:daiki",
            "local_override_of": "assertion:lore-daiki-vivo",
            "status": "SUPERSEDED", "superseded_by": "assertion:divergencia-B",
        },
        "assertion:divergencia-B": {
            "partida_id": PARTIDA_A, "subject_entity_id": "entity:daiki",
            "status": "ASSERTED", "supersedes": "assertion:divergencia-A",
        },
    }
    driver = _FakeReadDriver(graph)
    rows = list_visible_assertions(driver, WORKSPACE, PARTIDA_A)
    ids = {r.assertion_id for r in rows}
    # Lore enmascarado (correcto, A sigue apuntandolo); A Y B ambas visibles
    # (cuestionable: A ya no deberia contar como "vigente").
    assert "assertion:lore-daiki-vivo" not in ids
    assert ids == {"assertion:divergencia-A", "assertion:divergencia-B"}


# ==========================================================================
# 8. Direccion unica: capa juego jamas ve material de partida via reads.py.
# ==========================================================================
def test_capa_juego_nunca_ve_overrides_ni_hechos_de_ninguna_partida():
    """Repite la garantia de direccion unica (Invariante 1/2) pero con VARIAS
    partidas mezcladas en el mismo grafo, para descartar que el filtro
    `partida_id IS NULL` se cuele con algun `OR` de mas cuando hay mas de una
    partida en juego."""
    graph = _graph_dos_partidas_mismo_lore()
    graph["assertion:solo-de-B"] = {
        "partida_id": PARTIDA_B, "subject_entity_id": "entity:daiki", "status": "ASSERTED",
    }
    driver = _FakeReadDriver(graph)
    rows = list_visible_assertions(driver, WORKSPACE, None)
    ids = {r.assertion_id for r in rows}
    assert ids == {"assertion:lore-daiki-vivo"}
