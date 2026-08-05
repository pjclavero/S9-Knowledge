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
def test_override_vacio_ya_no_bypassa_el_rechazo_estructural_de_capa_juego():
    """INVERTIDO en el rework (bug P1 corregido). Antes: `local_override_of=""`
    en un plan de CAPA JUEGO NO disparaba `PLAN_LOCAL_OVERRIDE_FROM_GAME_LAYER`,
    porque `_local_override_incoherence` comprobaba truthiness
    (`if payload.get(...)`) y la cadena vacia es falsy igual que `None` o que
    la clave ausente. Ahora la frontera es `declares_local_override()`
    (`... is not None`): declarar el campo con CUALQUIER valor cuenta como
    intencion de declarar divergencia, y la capa juego no puede declarar
    ninguna."""
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:fantasma",
            "entity:daiki", "entity:casa-del-ciervo", "",
        )
    ]
    plan = make_plan(operations=ops, scope=game_scope())
    result = admit(plan, ctx())
    assert not result.admitted
    assert codes.PLAN_LOCAL_OVERRIDE_FROM_GAME_LAYER in result.codes


def test_override_vacio_desde_capa_juego_no_llega_a_escribirse():
    """INVERTIDO (mismo bug P1, extremo de ESCRITURA). Antes el payload con
    `local_override_of=""` pasaba admision Y ejecucion sin ninguna validacion
    contra el estado real, y la cadena vacia quedaba escrita tal cual en un
    nodo de CAPA JUEGO, sin exigir siquiera `reason_code`. Ahora el plan muere
    en admision y el driver no recibe ni una escritura."""
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
    assert result.outcome != OUTCOME_APPLIED
    assert codes.PLAN_LOCAL_OVERRIDE_FROM_GAME_LAYER in result.codes
    assert driver.writes == []
    assert not driver.committed


def test_override_vacio_desde_partida_muere_en_ejecucion_sin_escribir():
    """El otro filo del mismo bug: si quien declara `local_override_of=""` es
    una PARTIDA, admision no tiene nada estructural que objetar (es una
    partida, puede divergir), asi que el rechazo tiene que llegar contra el
    ESTADO real -- la cadena vacia no es ningun `assertion_id` de capa juego
    existente. El vacio NO se normaliza a "ausente" (eso lo dejaria pasar y
    escrito): se trata como declaracion invalida."""
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:fantasma",
            "entity:daiki", "entity:casa-del-ciervo", "",
        )
    ]
    plan = make_plan(operations=ops, partida_id=PARTIDA_A, scope=partida_scope(PARTIDA_A))
    driver = FakeDriver(nodes={})
    result = make_writer_for(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_LOCAL_OVERRIDE_TARGET_MISSING in result.codes
    assert driver.writes == []
    assert not driver.committed


def test_override_vacio_desde_partida_tampoco_esquiva_el_reason_code():
    """Y sin `reason_code` canonico muere antes todavia: el chequeo entero ya
    no se salta por truthiness, asi que la exigencia R1 del ledger aplica
    tambien al valor vacio."""
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:fantasma",
            "entity:daiki", "entity:casa-del-ciervo", "",
            reason_code=None,
        )
    ]
    plan = make_plan(operations=ops, partida_id=PARTIDA_A, scope=partida_scope(PARTIDA_A))
    driver = FakeDriver(nodes={})
    result = make_writer_for(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_LOCAL_OVERRIDE_REASON_INVALID in result.codes
    assert driver.writes == []


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


def test_misma_partida_dos_overrides_del_mismo_lore_se_rechaza_el_segundo():
    """INVERTIDO en el rework (hallazgo P1 corregido). Antes: nada impedia que
    la MISMA partida creara DOS aserciones con `local_override_of` apuntando al
    mismo hecho de lore, y las dos quedaban visibles a la vez sin ningun
    criterio de desempate. Ahora hay unicidad estricta
    `(workspace, partida_id, local_override_of)`: el segundo intento es un
    CONFLICTO (`EXEC_LOCAL_OVERRIDE_ALREADY_DECLARED`), no una fusion ni una
    cadena -- el mismo criterio CREATE-only de `_assert_absent`. Como el
    writer es transaccional, el primero tampoco queda escrito."""
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
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_LOCAL_OVERRIDE_ALREADY_DECLARED in result.codes
    assert not driver.committed


def test_segundo_override_del_mismo_lore_en_OTRO_plan_tambien_se_rechaza():
    """La unicidad no depende de que los dos overrides viajen en el mismo
    plan: un plan posterior, contra el estado YA escrito, cae igual. Y el
    hecho de capa juego sigue sin tocarse ni en el intento fallido."""
    def _plan(op_id, assertion_id, decision):
        ops = [
            op_local_override(
                op_id, decision, assertion_id,
                "entity:daiki", "entity:casa-del-ciervo", "assertion:lore-daiki-vivo",
            )
        ]
        return make_plan(
            operations=ops, partida_id=PARTIDA_A, scope=partida_scope(PARTIDA_A)
        )

    nodes = {("assertion", "assertion:lore-daiki-vivo"): lore_node()}
    driver = FakeDriver(nodes=nodes)
    writer = make_writer_for(driver)

    primero = _plan("op:0001", "assertion:divergencia-1", "decision:0001")
    r1 = writer.write(primero, apply_request(primero))
    assert r1.outcome == OUTCOME_APPLIED, r1.codes

    segundo = _plan("op:0002", "assertion:divergencia-2", "decision:0002")
    r2 = writer.write(segundo, apply_request(segundo))
    assert r2.outcome == OUTCOME_ABORTED
    assert codes.EXEC_LOCAL_OVERRIDE_ALREADY_DECLARED in r2.codes
    assert nodes[("assertion", "assertion:lore-daiki-vivo")] == lore_node()


def test_otra_partida_puede_declarar_su_propio_override_del_mismo_lore():
    """La unicidad es POR PARTIDA, no global: que `partida A` haya divergido
    de un hecho del lore no puede impedir que `partida B` diverja del mismo
    hecho (seria justo el acoplamiento entre partidas que el Invariante 1
    prohibe)."""
    ops_b = [
        op_local_override(
            "op:0002", "decision:0002", "assertion:divergencia-B",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:lore-daiki-vivo",
        )
    ]
    plan_b = make_plan(
        operations=ops_b, partida_id=PARTIDA_B, scope=partida_scope(PARTIDA_B)
    )
    nodes = {
        ("assertion", "assertion:lore-daiki-vivo"): lore_node(),
        # `partida A` ya diverge de ese mismo hecho.
        ("assertion", "assertion:divergencia-A"): {
            "version": 1, "state_hash": HASH_B["value"], "partida_id": PARTIDA_A,
            "local_override_of": "assertion:lore-daiki-vivo",
        },
    }
    driver = FakeDriver(nodes=nodes)
    result = make_writer_for(driver).write(plan_b, apply_request(plan_b))
    assert result.outcome == OUTCOME_APPLIED, result.codes


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


def test_hecho_de_capa_juego_ya_superseded_deja_de_estar_visible():
    """INVERTIDO en el rework (hallazgo P1 corregido). Antes
    `list_visible_assertions_query` no filtraba `status` en absoluto, asi que
    una asercion de capa juego YA SUSTITUIDA seguia apareciendo como
    "visible" -- la funcion prometia vigencia y no la cumplia. Ahora el WHERE
    lleva `n.status IN $live_statuses` (catalogo `LIVE_STATUSES` del ledger)
    y la version superada desaparece de la vista sin haber sido borrada del
    grafo."""
    graph = {
        "assertion:lore-daiki-vivo": {
            "partida_id": None, "subject_entity_id": "entity:daiki",
            "status": "SUPERSEDED", "superseded_by": "assertion:lore-daiki-vivo-v2",
        },
        "assertion:lore-daiki-vivo-v2": {
            "partida_id": None, "subject_entity_id": "entity:daiki", "status": "ASSERTED",
        },
    }
    driver = _FakeReadDriver(graph)
    rows = list_visible_assertions(driver, WORKSPACE, PARTIDA_A)
    ids = {r.assertion_id for r in rows}
    assert ids == {"assertion:lore-daiki-vivo-v2"}


def test_un_hecho_contradicho_sigue_visible_porque_contradecir_no_destruye():
    """El filtro es el catalogo del ledger, no "todo lo que no sea ASSERTED":
    `CONTRADICTED` sigue contando como conocimiento (marca, no destruye) y por
    tanto sigue viendose."""
    graph = {
        "assertion:lore-discutido": {
            "partida_id": None, "subject_entity_id": "entity:daiki",
            "status": "CONTRADICTED",
        },
        "assertion:lore-retractado": {
            "partida_id": None, "subject_entity_id": "entity:daiki",
            "status": "RETRACTED",
        },
    }
    driver = _FakeReadDriver(graph)
    rows = list_visible_assertions(driver, WORKSPACE, PARTIDA_A)
    assert {r.assertion_id for r in rows} == {"assertion:lore-discutido"}


# ==========================================================================
# 7. Override + supersesion temporal SIMULTANEOS dentro de la misma partida
#    (requisito 5.e del encargo).
# ==========================================================================
def test_override_superseded_dentro_de_la_partida_deja_lore_enmascarado_y_solo_B_visible():
    """(e) AJUSTADO en el rework. El hecho local A override-a al lore; luego,
    DENTRO de la misma partida, A es superseded por B (supersesion temporal
    normal). SEMANTICA ELEGIDA Y DOCUMENTADA (ver
    `cypher.list_visible_assertions_query`):

    - El lore de capa juego SIGUE enmascarado: el `NOT EXISTS` mira el
      PUNTERO, no el `status` del override. A lo sigue apuntando aunque este
      SUPERSEDED (cerrar una vigencia temporal nunca toca
      `local_override_of`).
    - A ya NO aparece: el filtro de vigencia la excluye. Solo B, la version
      vigente de la divergencia, queda visible.

    Se elige asi -- y no "solo enmascara un override vigente" -- por
    coherencia con la unicidad estricta: la partida declara su divergencia
    sobre ese hecho UNA vez, y lo que evoluciona despues es el contenido. Si
    el enmascarado dependiera del status, supersedir A haria REAPARECER el
    lore junto a B (dos hechos del mismo sujeto en la misma vista) y ademas
    no habria forma de volver a ocultarlo, porque la unicidad impide declarar
    un segundo override sobre el mismo objetivo."""
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
    # Lore enmascarado (A lo sigue apuntando) y solo la version vigente de la
    # divergencia visible.
    assert "assertion:lore-daiki-vivo" not in ids
    assert ids == {"assertion:divergencia-B"}


def test_LIMITE_retracted_deja_zona_muerta_lore_enmascarado_y_sin_reoverride():
    """LIMITE CONOCIDO Y ACEPTADO DE M4 -- se resuelve en M5, no aqui.

    Este test NO afirma que el comportamiento sea correcto: FIJA el estado
    actual para que nadie lo "arregle" por accidente sin una decision
    explicita de diseno.

    Escenario: `partida A` declaro una divergencia sobre un hecho de lore y
    despues la RETRACTO (`status=RETRACTED`, el lore sigue `ASSERTED`).
    Resultado hoy:

    - `list_visible_assertions` devuelve CONJUNTO VACIO para esa partida: el
      override ya no es vigente (filtro de status) pero sigue enmascarando el
      lore, porque el `NOT EXISTS` mira el PUNTERO, no el status.
    - `find_local_override` tampoco filtra status, asi que la partida NO puede
      declarar un override nuevo sobre ese hecho: choca contra el registro
      retractado (`EXEC_LOCAL_OVERRIDE_ALREADY_DECLARED`).

    Zona muerta: quien retracta su divergencia deja de ver NADA de ese hecho,
    para siempre. La semantica correcta distingue dos cosas que M4 trata
    igual: RETRACTAR es "retiro mi divergencia" (el lore deberia reaparecer y
    la unicidad deberia liberarse) mientras que SUPERSEDER es "sigo
    divergiendo, con otro contenido" (enmascarado correcto, ver el test de
    A->B). Implementar esa distincion exige el ciclo de vida completo de la
    divergencia, que es M5 -- no un parche aqui.
    """
    graph = {
        "assertion:lore-daiki-vivo": {
            "partida_id": None, "subject_entity_id": "entity:daiki", "status": "ASSERTED",
        },
        "assertion:divergencia-A": {
            "partida_id": PARTIDA_A, "subject_entity_id": "entity:daiki",
            "local_override_of": "assertion:lore-daiki-vivo", "status": "RETRACTED",
        },
    }
    driver = _FakeReadDriver(graph)
    rows = list_visible_assertions(driver, WORKSPACE, PARTIDA_A)
    # Ni el lore (enmascarado por el puntero) ni la divergencia (no vigente).
    assert rows == []
    # Otra partida y la capa juego siguen viendo el lore intacto: el limite
    # solo afecta a quien retracto.
    assert {r.assertion_id for r in list_visible_assertions(driver, WORKSPACE, PARTIDA_B)} == {
        "assertion:lore-daiki-vivo"
    }

    # Y la partida tampoco puede volver a declarar un override de ese hecho.
    ops = [
        op_local_override(
            "op:0002", "decision:0002", "assertion:divergencia-A2",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:lore-daiki-vivo",
        )
    ]
    plan = make_plan(operations=ops, partida_id=PARTIDA_A, scope=partida_scope(PARTIDA_A))
    nodes = {
        ("assertion", "assertion:lore-daiki-vivo"): lore_node(),
        ("assertion", "assertion:divergencia-A"): {
            "version": 2, "state_hash": HASH_B["value"], "partida_id": PARTIDA_A,
            "local_override_of": "assertion:lore-daiki-vivo", "status": "RETRACTED",
        },
    }
    write_driver = FakeDriver(nodes=nodes)
    result = make_writer_for(write_driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_LOCAL_OVERRIDE_ALREADY_DECLARED in result.codes


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
