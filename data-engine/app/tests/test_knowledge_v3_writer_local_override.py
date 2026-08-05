# -*- coding: utf-8 -*-
"""Pruebas de M4: supersesion LOCAL (`local_override_of`).

docs/v3/49-multipartida-diseno.md §2.5 y "M4 implementado". El hecho de
partida diverge del lore de capa juego sin mutarlo jamas: el puntero es
`local_override_of` (propiedad plana, mismo patron que `superseded_by`), la
razon canonica es `LOCAL_DIVERGENCE`, y la admision/ejecucion cierran los dos
filos del Invariante 2 exactamente como ya lo hacen para `scope`/`partida_id`
(M3): coherencia estructural en `admission.py`, cruce contra el ESTADO real
en `executor.py` (lectura acotada, nunca en Python).

Reutiliza el driver falso y los constructores de plan de
`test_knowledge_v3_writer.py` -- el mismo criterio que ya sigue
`test_knowledge_v3_writer_mutation.py` para no divergir de la fixture
canonica del writer.
"""
from __future__ import annotations

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.writer import codes  # noqa: E402
from knowledge_v3.writer.reads import VisibleAssertion, list_visible_assertions  # noqa: E402
from knowledge_v3.writer.writer import OUTCOME_ABORTED, OUTCOME_APPLIED, OUTCOME_REJECTED  # noqa: E402
from knowledge_v3.writer import cypher  # noqa: E402
from test_knowledge_v3_writer import (  # noqa: E402
    HASH_A,
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

PARTIDA = "partida:brumal-01"
PARTIDA_OTRA = "partida:brumal-OTRA"


def op_local_override(
    op_id: str,
    decision_id: str,
    assertion_id: str,
    subject: str,
    obj: str,
    local_override_of: str,
    *,
    reason_code: "str | None" = "LOCAL_DIVERGENCE",
) -> dict:
    """`CREATE_ASSERTION` con el puntero de M4 en el payload."""
    op = op_create_assertion(op_id, decision_id, assertion_id, subject, obj)
    op["payload"]["local_override_of"] = local_override_of
    if reason_code is not None:
        op["payload"]["reason_code"] = reason_code
    return op


def lore_node(version: int = 2, state_hash: str = HASH_B["value"]) -> dict:
    """Nodo de CAPA JUEGO: sin `partida_id` en absoluto (mismo criterio del
    resto del harness: ausencia de la clave == `None` == capa juego)."""
    return {"version": version, "state_hash": state_hash}


def partida_node(partida_id: str, version: int = 2, state_hash: str = HASH_B["value"]) -> dict:
    return {"version": version, "state_hash": state_hash, "partida_id": partida_id}


# ==========================================================================
# 1. Admision estructural: PLAN_LOCAL_OVERRIDE_FROM_GAME_LAYER
# ==========================================================================
def test_admision_rechaza_override_declarado_desde_capa_juego():
    """(b) Rechazo: la aserción que intenta el override no es de tipo PARTIDA."""
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:divergencia",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:lore-daiki-vivo",
        )
    ]
    plan = make_plan(operations=ops, scope=game_scope())
    result = admit(plan, ctx())
    assert not result.admitted
    assert codes.PLAN_LOCAL_OVERRIDE_FROM_GAME_LAYER in result.codes


def test_admision_rechaza_override_sin_scope_declarado_ni_partida_id():
    """Mismo rechazo cuando el plan es legado (sin `scope` ni `partida_id`
    en absoluto): capa juego implicita, igual de invalida para un override."""
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:divergencia",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:lore-daiki-vivo",
        )
    ]
    plan = make_plan(operations=ops)
    result = admit(plan, ctx())
    assert not result.admitted
    assert codes.PLAN_LOCAL_OVERRIDE_FROM_GAME_LAYER in result.codes


def test_admision_admite_override_declarado_desde_partida():
    """Estructuralmente coherente: admision no puede saber (ni le toca) si el
    objetivo es de verdad capa juego -- eso es ejecucion (test siguiente)."""
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:divergencia",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:lore-daiki-vivo",
        )
    ]
    plan = make_plan(operations=ops, partida_id=PARTIDA, scope=partida_scope(PARTIDA))
    result = admit(plan, ctx())
    assert result.admitted, result.codes


# ==========================================================================
# 2. Ejecucion: el otro filo (cruce contra el ESTADO real)
# ==========================================================================
def test_override_partida_a_capa_juego_aplica_y_no_toca_el_hecho_de_juego():
    """(a) Camino feliz: override de partida->juego OK. El hecho de capa
    juego no cambia NI UNA SOLA propiedad."""
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:divergencia",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:lore-daiki-vivo",
        )
    ]
    plan = make_plan(operations=ops, partida_id=PARTIDA, scope=partida_scope(PARTIDA))
    nodes = {("assertion", "assertion:lore-daiki-vivo"): lore_node()}
    driver = FakeDriver(nodes=nodes)
    result = make_writer_for(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_APPLIED, result.codes
    assert result.created_ids == ["assertion:divergencia"]

    # El hecho de capa juego sigue EXACTAMENTE igual: ninguna escritura del
    # plan lo toca (ni SET, ni CREATE, ni ningun otro verbo).
    assert nodes[("assertion", "assertion:lore-daiki-vivo")] == lore_node()
    touched = [
        (q, p) for q, p in driver.writes
        if p.get("id") == "assertion:lore-daiki-vivo"
        or p.get("props", {}).get("assertion_id") == "assertion:lore-daiki-vivo"
    ]
    assert touched == []

    # El puntero SI viaja como propiedad plana de la asercion nueva.
    create_write = next(
        (q, p) for q, p in driver.writes
        if p.get("props", {}).get("assertion_id") == "assertion:divergencia"
    )
    assert create_write[1]["props"]["local_override_of"] == "assertion:lore-daiki-vivo"
    assert create_write[1]["props"]["reason_code"] == "LOCAL_DIVERGENCE"


def test_override_a_objetivo_inexistente_aborta_target_missing():
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:divergencia",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:no-existe",
        )
    ]
    plan = make_plan(operations=ops, partida_id=PARTIDA, scope=partida_scope(PARTIDA))
    driver = FakeDriver(nodes={})
    result = make_writer_for(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_LOCAL_OVERRIDE_TARGET_MISSING in result.codes
    assert not driver.committed


def test_override_a_objetivo_de_otra_partida_cross_partida_rechazado():
    """Rechazo cross-partida: partida A -> partida B. El objetivo existe,
    pero pertenece a OTRA partida, no a capa juego."""
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:divergencia",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:hecho-otra-partida",
        )
    ]
    plan = make_plan(operations=ops, partida_id=PARTIDA, scope=partida_scope(PARTIDA))
    nodes = {("assertion", "assertion:hecho-otra-partida"): partida_node(PARTIDA_OTRA)}
    driver = FakeDriver(nodes=nodes)
    result = make_writer_for(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_LOCAL_OVERRIDE_TARGET_NOT_GAME_LAYER in result.codes
    assert not driver.committed


def test_override_a_objetivo_de_la_propia_partida_juego_indebido_rechazado():
    """Rechazo juego<-partida (segundo filo): el objetivo existe, pero es de
    la PROPIA partida, no de capa juego -- tambien invalido."""
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:divergencia",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:hecho-propio",
        )
    ]
    plan = make_plan(operations=ops, partida_id=PARTIDA, scope=partida_scope(PARTIDA))
    nodes = {("assertion", "assertion:hecho-propio"): partida_node(PARTIDA)}
    driver = FakeDriver(nodes=nodes)
    result = make_writer_for(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_LOCAL_OVERRIDE_TARGET_NOT_GAME_LAYER in result.codes


def test_override_sin_reason_code_canonico_rechazado():
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:divergencia",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:lore-daiki-vivo",
            reason_code=None,
        )
    ]
    plan = make_plan(operations=ops, partida_id=PARTIDA, scope=partida_scope(PARTIDA))
    nodes = {("assertion", "assertion:lore-daiki-vivo"): lore_node()}
    driver = FakeDriver(nodes=nodes)
    result = make_writer_for(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_LOCAL_OVERRIDE_REASON_INVALID in result.codes


def test_override_con_reason_code_incorrecto_rechazado():
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:divergencia",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:lore-daiki-vivo",
            reason_code="SUPERSEDED_BY_NEWER",
        )
    ]
    plan = make_plan(operations=ops, partida_id=PARTIDA, scope=partida_scope(PARTIDA))
    nodes = {("assertion", "assertion:lore-daiki-vivo"): lore_node()}
    driver = FakeDriver(nodes=nodes)
    result = make_writer_for(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_LOCAL_OVERRIDE_REASON_INVALID in result.codes


# ==========================================================================
# 3. Cadenas de override (decision explicita de M4: sin cadenas)
# ==========================================================================
def test_override_de_un_override_ya_existente_es_rechazado_como_no_capa_juego():
    """(d) Override de un hecho que ya es a su vez un override: la afirmacion
    apuntada YA es de partida (aunque lleve su propio `local_override_of`),
    asi que cae en la misma regla que cualquier objetivo no-capa-juego. No
    hay "colapso al original" ni "resolucion al ultimo de la cadena": un
    override SIEMPRE apunta directamente al lore compartido."""
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:divergencia-2",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:divergencia-1",
        )
    ]
    plan = make_plan(operations=ops, partida_id=PARTIDA, scope=partida_scope(PARTIDA))
    # `assertion:divergencia-1` es en si misma una asercion de partida (fue
    # creada como override de otra cosa, pero eso es irrelevante aqui: lo
    # unico que importa es que NO es de capa juego).
    nodes = {("assertion", "assertion:divergencia-1"): partida_node(PARTIDA)}
    driver = FakeDriver(nodes=nodes)
    result = make_writer_for(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_ABORTED
    assert codes.EXEC_LOCAL_OVERRIDE_TARGET_NOT_GAME_LAYER in result.codes


# ==========================================================================
# 4. Retrocompatibilidad: la supersesion temporal (close_validity/
#    SUPERSEDE_ASSERTION) sigue intacta
# ==========================================================================
def test_supersesion_temporal_intra_ambito_sigue_intacta():
    """Regresion explicita (requisito 5.e): `SUPERSEDE_ASSERTION` dentro del
    mismo ambito (partida-supersede-partida) no se ve afectado por M4."""
    from test_knowledge_v3_writer import op_supersede

    ops = [op_supersede("op:0001", "decision:0001", "assertion:vieja")]
    plan = make_plan(operations=ops, partida_id=PARTIDA, scope=partida_scope(PARTIDA))
    nodes = {
        ("assertion", "assertion:vieja"): {
            "version": 2, "state_hash": HASH_B["value"], "partida_id": PARTIDA,
        },
    }
    driver = FakeDriver(nodes=nodes)
    result = make_writer_for(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_APPLIED, result.codes


# ==========================================================================
# 5. Idempotencia
# ==========================================================================
def test_aplicar_el_mismo_override_dos_veces_es_idempotente():
    """(f) Reaplicar el mismo plan no duplica ni corrompe: la segunda vez es
    un no-op contabilizado (misma disciplina que el resto del writer)."""
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:divergencia",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:lore-daiki-vivo",
        )
    ]
    plan = make_plan(operations=ops, partida_id=PARTIDA, scope=partida_scope(PARTIDA))
    nodes = {("assertion", "assertion:lore-daiki-vivo"): lore_node()}
    driver = FakeDriver(nodes=nodes)
    writer = make_writer_for(driver)

    first = writer.write(plan, apply_request(plan))
    assert first.outcome == OUTCOME_APPLIED, first.codes

    creates_after_first = [
        p for _, p in driver.writes
        if p.get("props", {}).get("assertion_id") == "assertion:divergencia"
    ]
    assert len(creates_after_first) == 1

    second = writer.write(plan, apply_request(plan))
    assert second.outcome == OUTCOME_APPLIED, second.codes

    creates_after_second = [
        p for _, p in driver.writes
        if p.get("props", {}).get("assertion_id") == "assertion:divergencia"
    ]
    # Ninguna escritura NUEVA de creacion: la segunda vuelta es un no-op.
    assert len(creates_after_second) == 1
    # El hecho de capa juego sigue intacto tambien tras la repeticion.
    assert nodes[("assertion", "assertion:lore-daiki-vivo")] == lore_node()


# ==========================================================================
# 5-bis. Marca de revision (M4 rework: exigencia minima del dictamen)
# ==========================================================================
def _plan_override_simple():
    ops = [
        op_local_override(
            "op:0001", "decision:0001", "assertion:divergencia",
            "entity:daiki", "entity:casa-del-ciervo", "assertion:lore-daiki-vivo",
        )
    ]
    return make_plan(operations=ops, partida_id=PARTIDA, scope=partida_scope(PARTIDA))


def test_escribir_una_divergencia_deja_marca_de_revision_en_el_resultado():
    """La divergencia se ESCRIBE (no se bloquea: la aprobacion humana es M5),
    pero el resultado la anuncia con un codigo consultable, sin obligar a
    nadie a saber buscar `local_override_of IS NOT NULL` en el grafo."""
    plan = _plan_override_simple()
    nodes = {("assertion", "assertion:lore-daiki-vivo"): lore_node()}
    driver = FakeDriver(nodes=nodes)
    result = make_writer_for(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_APPLIED, result.codes
    assert result.review_marks == [
        {
            "operation_id": "op:0001",
            "assertion_id": "assertion:divergencia",
            "code": codes.LOCAL_DIVERGENCE_PENDING_REVIEW,
            "local_override_of": "assertion:lore-daiki-vivo",
            "partida_id": PARTIDA,
        }
    ]
    # La marca NO es un rechazo: no contamina `rejections` ni el desenlace.
    assert result.rejections == []
    assert result.to_dict()["review_marks"] == result.review_marks
    # Y viaja tambien al rastro de auditoria del desenlace.
    assert result.audit_record["detail"]["review_marks"] == result.review_marks


def test_una_creacion_normal_no_deja_ninguna_marca_de_revision():
    """Solo la divergencia se marca: una asercion corriente de partida no
    tiene nada que revisar por este concepto."""
    ops = [
        op_create_assertion(
            "op:0001", "decision:0001", "assertion:normal",
            "entity:daiki", "entity:casa-del-ciervo",
        )
    ]
    plan = make_plan(operations=ops, partida_id=PARTIDA, scope=partida_scope(PARTIDA))
    driver = FakeDriver(nodes={})
    result = make_writer_for(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_APPLIED, result.codes
    assert result.review_marks == []


def test_el_dry_run_tambien_anuncia_la_divergencia_sin_escribir_nada():
    """Quien simula antes de aplicar tiene que poder ver que ESTE plan trae
    una divergencia local, sin aplicarlo."""
    plan = _plan_override_simple()
    driver = FakeDriver(nodes={})
    result = make_writer_for(driver).write(plan, apply_request(plan, apply=False))
    assert result.ok, result.codes
    assert [m["code"] for m in result.review_marks] == [
        codes.LOCAL_DIVERGENCE_PENDING_REVIEW
    ]
    assert driver.writes == []


# ==========================================================================
# 6. Cypher: el enmascarado de lectura (decision de coste, M4 §2.5)
# ==========================================================================
def test_query_de_capa_juego_no_lleva_enmascarado():
    """La capa juego jamas necesita `NOT EXISTS`: nadie que lea sin partida
    puede tener un override que aplicar."""
    q = cypher.list_visible_assertions_query(WORKSPACE, None)
    assert "NOT EXISTS" not in q.cypher
    assert "partida_id" not in q.params


def test_query_de_partida_lleva_enmascarado_acotado_a_su_propio_ambito():
    q = cypher.list_visible_assertions_query(WORKSPACE, PARTIDA)
    assert "NOT EXISTS" in q.cypher
    assert "o.partida_id = $partida_id" in q.cypher
    assert "o.local_override_of = n.assertion_id" in q.cypher
    assert q.params["partida_id"] == PARTIDA


def test_query_filtra_vigencia_con_el_catalogo_del_ledger():
    """M4 rework (P1 del dictamen): "visible" incluye AHORA la vigencia. El
    catalogo no se copia a mano: es `LIVE_STATUSES` del ledger, asi que
    `SUPERSEDED`/`RETRACTED` quedan fuera y `CONTRADICTED` dentro (una
    contradiccion marca, no destruye)."""
    from knowledge_v3.ledger.supersession import LIVE_STATUSES

    q = cypher.list_visible_assertions_query(WORKSPACE, PARTIDA)
    assert "n.status IN $live_statuses" in q.cypher
    assert set(q.params["live_statuses"]) == {s.value for s in LIVE_STATUSES}
    assert "SUPERSEDED" not in q.params["live_statuses"]
    assert "RETRACTED" not in q.params["live_statuses"]
    assert "CONTRADICTED" in q.params["live_statuses"]
    # Tambien en capa juego: la vigencia no es cosa de partidas.
    assert "n.status IN $live_statuses" in cypher.list_visible_assertions_query(
        WORKSPACE, None
    ).cypher


def test_query_de_unicidad_acota_workspace_partida_y_objetivo():
    """M4 rework: la unicidad se resuelve en Cypher, acotada a los tres
    campos que la definen, y es una LECTURA (`MATCH ... RETURN`, `LIMIT 1`)."""
    q = cypher.find_local_override(WORKSPACE, PARTIDA, "assertion:lore-daiki-vivo")
    assert "n.workspace = $ws" in q.cypher
    assert "n.partida_id = $partida_id" in q.cypher
    assert "n.local_override_of = $override_target" in q.cypher
    assert "LIMIT 1" in q.cypher
    assert q.params == {
        "ws": WORKSPACE,
        "partida_id": PARTIDA,
        "override_target": "assertion:lore-daiki-vivo",
    }


def test_query_filtra_por_sujeto_cuando_se_declara():
    q = cypher.list_visible_assertions_query(WORKSPACE, PARTIDA, subject_entity_id="entity:daiki")
    assert "n.subject_entity_id = $subject" in q.cypher
    assert q.params["subject"] == "entity:daiki"


# --------------------------------------------------------------------------
# `list_visible_assertions`: orquestacion de filas + enmascarado real
# --------------------------------------------------------------------------
class _FakeReadResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeReadSession:
    """Fake minimo que interpreta los `params` de `list_visible_assertions_query`
    con el MISMO criterio semantico que la consulta real (visibilidad + M3 +
    enmascarado M4), sin parsear Cypher. Independiente del `FakeTx` de
    mutacion: aqui no hay transaccion ni escritura, solo lectura."""

    def __init__(self, graph: dict[str, dict]):
        self.graph = graph

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher_text: str, params: dict):
        partida_id = params.get("partida_id")
        subject = params.get("subject")
        live = set(params.get("live_statuses") or ())
        visible = {
            aid: props
            for aid, props in self.graph.items()
            if props.get("partida_id") is None or props.get("partida_id") == partida_id
        }
        # M4 (rework): la consulta real filtra vigencia en el WHERE. El fake
        # honra el MISMO criterio -- y estrictamente: un nodo sin `status` no
        # es "vigente demostrable", igual que en Cypher `NULL IN [...]` no es
        # true.
        visible = {
            aid: props for aid, props in visible.items() if props.get("status") in live
        }
        if subject is not None:
            visible = {
                aid: props for aid, props in visible.items()
                if props.get("subject_entity_id") == subject
            }
        if partida_id is not None:
            overridden = {
                props["local_override_of"]
                for props in self.graph.values()
                if props.get("partida_id") == partida_id and props.get("local_override_of")
            }
            visible = {aid: props for aid, props in visible.items() if aid not in overridden}
        rows = [
            {"assertion_id": aid, "props": props}
            for aid, props in sorted(visible.items())
        ]
        return _FakeReadResult(rows)


class _FakeReadDriver:
    def __init__(self, graph: dict[str, dict]):
        self.graph = graph

    def session(self):
        return _FakeReadSession(self.graph)


def _fixture_graph() -> dict[str, dict]:
    return {
        "assertion:lore-daiki-vivo": {
            "partida_id": None, "subject_entity_id": "entity:daiki", "status": "ASSERTED",
        },
        "assertion:divergencia": {
            "partida_id": PARTIDA, "subject_entity_id": "entity:daiki",
            "local_override_of": "assertion:lore-daiki-vivo", "status": "ASSERTED",
        },
    }


def test_lectura_desde_partida_con_override_ve_el_hecho_local_no_el_lore():
    """(c) La partida CON el override ve el hecho de partida; el de lore
    queda enmascarado en ESTA vista (nunca borrado del grafo)."""
    driver = _FakeReadDriver(_fixture_graph())
    rows = list_visible_assertions(driver, WORKSPACE, PARTIDA)
    ids = {r.assertion_id for r in rows}
    assert ids == {"assertion:divergencia"}


def test_lectura_desde_otra_partida_ve_el_lore_intacto():
    """(c) Otra partida del mismo juego, sin el override propio, sigue viendo
    el hecho de capa juego sin cambios -- el override es invisible fuera de
    su propia partida."""
    driver = _FakeReadDriver(_fixture_graph())
    rows = list_visible_assertions(driver, WORKSPACE, PARTIDA_OTRA)
    ids = {r.assertion_id for r in rows}
    assert ids == {"assertion:lore-daiki-vivo"}


def test_lectura_desde_capa_juego_ve_el_lore_intacto():
    """(c) La propia capa juego (partida_id=None) tampoco ve nunca el
    override de ninguna partida."""
    driver = _FakeReadDriver(_fixture_graph())
    rows = list_visible_assertions(driver, WORKSPACE, None)
    ids = {r.assertion_id for r in rows}
    assert ids == {"assertion:lore-daiki-vivo"}


def test_visible_assertion_expone_assertion_id_y_props():
    driver = _FakeReadDriver(_fixture_graph())
    rows = list_visible_assertions(driver, WORKSPACE, PARTIDA)
    assert rows == [
        VisibleAssertion(
            assertion_id="assertion:divergencia",
            props=_fixture_graph()["assertion:divergencia"],
        )
    ]


# --------------------------------------------------------------------------
# helper local: writer con reloj/entorno consistentes con el resto del modulo
# --------------------------------------------------------------------------
def make_writer_for(driver):
    from test_knowledge_v3_writer import make_writer

    return make_writer(driver)
