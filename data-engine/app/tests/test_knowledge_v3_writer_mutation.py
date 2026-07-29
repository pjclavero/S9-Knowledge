# -*- coding: utf-8 -*-
"""Pruebas de MUTACION del writer.

Cada test de aqui existe para ponerse ROJO si alguien elimina una comprobacion
concreta. No comprueban que el writer funcione: comprueban que sigue negandose.

Dos familias:

* **Gate** — una tabla con las nueve condiciones. Cada fila incumple UNA sola y
  exige exactamente su codigo. Borrar la condicion del gate hace que la fila
  correspondiente devuelva `allowed=True` y el test caiga. El meta-test cierra
  la tabla: si alguien anade una condicion sin fila, tambien cae.
* **Campos no firmados** — la prohibicion del contrato sobre `created_at`,
  `plan_id`, `provider_trace` y `metadata`. Se demuestra por partida triple: la
  estructura no los contiene, el codigo no los nombra, y alterarlos y volver a
  sellar el plan produce EXACTAMENTE las mismas escrituras.

Las fixtures se reutilizan del modulo hermano: dos constructores del mismo
documento acabarian divergiendo y una de las dos suites probaria un plan que ya
no existe.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.contracts.base import seal_plan  # noqa: E402
from knowledge_v3.writer import codes  # noqa: E402
from knowledge_v3.writer.gate import evaluate  # noqa: E402
from knowledge_v3.writer.view import UNSIGNED_FIELDS, SignedView  # noqa: E402
from knowledge_v3.writer.writer import OUTCOME_APPLIED, OUTCOME_REJECTED  # noqa: E402
from test_knowledge_v3_writer import (  # noqa: E402
    SNAPSHOT,
    WORKSPACE,
    ExplodingDriver,
    FakeDriver,
    InMemoryAppliedKeys,
    OperatorRequest,
    admit,
    apply_env,
    apply_request,
    ctx,
    make_plan,
    make_writer,
    op_create_entity,
)


# ==========================================================================
# 1. Las nueve condiciones del gate, una a una
# ==========================================================================
def full_pass_request(plan: dict, **over) -> OperatorRequest:
    """Peticion que cumple las nueve condiciones. Cada fila rompe UNA."""
    base = dict(
        apply=True,
        operator_id="pjc",
        workspace=WORKSPACE,
        expected_plan_hash=plan["plan_hash"]["value"],
        max_operations=50,
        current_snapshot_id=SNAPSHOT,
        env=apply_env(),
    )
    base.update(over)
    return OperatorRequest(**base)


def view_of(plan: dict) -> SignedView:
    result = admit(plan, ctx())
    assert result.admitted, result.codes
    return result.view


#: (nombre, mutacion de la peticion, audit_available, codigo exigido)
GATE_MUTATIONS = [
    (
        "1-entorno",
        lambda plan: {"env": {"S9K_WRITER_WORKSPACE": WORKSPACE}},
        True,
        codes.GATE_ENV_NOT_ALLOWED,
    ),
    ("2-apply", lambda plan: {"apply": False}, True, codes.GATE_APPLY_NOT_REQUESTED),
    ("3-operador", lambda plan: {"operator_id": None}, True, codes.GATE_OPERATOR_MISSING),
    (
        "4-operador-invalido",
        lambda plan: {"operator_id": "pj c"},
        True,
        codes.GATE_OPERATOR_INVALID,
    ),
    (
        "5-hash",
        lambda plan: {"expected_plan_hash": "d" * 64},
        True,
        codes.GATE_PLAN_HASH_NOT_CONFIRMED,
    ),
    (
        "6-limite",
        lambda plan: {"max_operations": 0},
        True,
        codes.GATE_OPERATION_LIMIT_EXCEEDED,
    ),
    (
        "7-workspace-entorno",
        lambda plan: {"env": {"S9K_ALLOW_REAL_INGEST": "1"}},
        True,
        codes.GATE_WORKSPACE_NOT_DECLARED,
    ),
    (
        "8-workspace-discrepante",
        lambda plan: {"env": apply_env("otra-campana")},
        True,
        codes.GATE_WORKSPACE_DECLARATION_MISMATCH,
    ),
    ("9-auditoria", lambda plan: {}, False, codes.GATE_AUDIT_UNAVAILABLE),
]


def test_el_gate_permite_el_apply_cuando_se_cumplen_las_nueve():
    plan = make_plan()
    gate = evaluate(view_of(plan), full_pass_request(plan), audit_available=True)
    assert gate.allowed, gate.codes


@pytest.mark.parametrize(
    "nombre,mutacion,audit,codigo", GATE_MUTATIONS, ids=[m[0] for m in GATE_MUTATIONS]
)
def test_incumplir_una_sola_condicion_del_gate_bloquea(nombre, mutacion, audit, codigo):
    """Rojo si se elimina la condicion: sin ella el gate diria que si."""
    plan = make_plan()
    gate = evaluate(
        view_of(plan), full_pass_request(plan, **mutacion(plan)), audit_available=audit
    )
    assert not gate.allowed, f"{nombre} deberia bloquear"
    assert gate.codes == [codigo], f"{nombre}: {gate.codes}"


def test_la_tabla_de_mutaciones_cubre_las_nueve_condiciones():
    """Meta-test: una condicion nueva sin fila en la tabla tambien pone esto rojo."""
    cubiertos = {codigo for *_, codigo in GATE_MUTATIONS}
    assert cubiertos == set(codes.GATE_CODES)
    assert len(GATE_MUTATIONS) == 9


def test_todas_las_condiciones_incumplidas_a_la_vez_las_denuncia_todas():
    plan = make_plan()
    gate = evaluate(
        view_of(plan),
        full_pass_request(
            plan, apply=False, operator_id=None, expected_plan_hash=None,
            max_operations=0, env={},
        ),
        audit_available=False,
    )
    esperados = set(codes.GATE_CODES) - {codes.GATE_OPERATOR_INVALID,
                                         codes.GATE_WORKSPACE_DECLARATION_MISMATCH}
    assert esperados <= set(gate.codes)


# ==========================================================================
# 2. Admision: cada condicion, su mutacion
# ==========================================================================
#: (nombre, mutacion del plan o del contexto, codigo exigido)
def test_mutar_el_workspace_del_plan_lo_hace_inadmisible():
    assert codes.PLAN_WORKSPACE_MISMATCH in admit(make_plan(workspace="otra"), ctx()).codes


def test_mutar_el_snapshot_del_plan_lo_hace_inadmisible():
    plan = make_plan(snapshot_id="snapshot:neo4j:1999-01-01T00:00:00Z")
    assert codes.PLAN_SNAPSHOT_STALE in admit(plan, ctx()).codes


def test_mutar_la_aprobacion_lo_hace_inadmisible():
    assert codes.PLAN_NOT_APPROVED in admit(make_plan(approved=False), ctx()).codes


def test_adelantar_el_reloj_caduca_el_plan():
    from datetime import datetime, timezone

    plan = make_plan(expires_at="2026-07-28T10:30:00Z")
    tarde = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert codes.PLAN_EXPIRED in admit(plan, ctx(clock=lambda: tarde)).codes


def test_alargar_la_caducidad_sin_llegar_al_presente_sigue_caducado():
    """Un plan caducado sigue caducado aunque le alarguen la vida un rato: la
    caducidad se juzga contra el reloj, no contra la firma.

    Ojo con lo que este test NO dice: alargarla hasta DESPUES del reloj y
    resellar SI funciona (`test_resellar_de_verdad_revive_un_plan_caducado`).
    El resellado es una capacidad real de quien pueda escribir el documento, y
    el limite esta dicho en §9 de la documentacion, no disimulado aqui."""
    plan = make_plan(expires_at="2026-07-27T11:00:00Z")
    plan["expires_at"] = "2026-07-27T11:30:00Z"  # el reloj marca las 12:00
    plan = seal_plan(plan)  # firma impecable, plan igualmente caducado
    result = admit(plan, ctx())
    assert result.codes == [codes.PLAN_EXPIRED]


def test_resellar_de_verdad_revive_un_plan_caducado():
    """El limite real, demostrado en vez de descrito.

    Los hashes son sha256 SIN clave: quien pueda reescribir el documento puede
    volver a sellarlo, y entonces el plan es indistinguible de uno legitimo. La
    unica defensa hoy es la cadena de custodia — el plan no sale del proceso
    local — y los campos `signature`/`key_id`, reservados y sin usar."""
    plan = make_plan(expires_at="2026-07-27T11:00:00Z")
    assert admit(plan, ctx()).codes == [codes.PLAN_EXPIRED]
    plan["expires_at"] = "2030-01-01T00:00:00Z"
    plan = seal_plan(plan)
    assert admit(plan, ctx()).admitted  # y esto NO es un fallo del writer


def test_resellar_un_plan_de_otro_workspace_no_lo_hace_propio():
    """Resellar recalcula hashes; no cambia el workspace, que sigue siendo el
    del plan. Lo que este test descarta es que el resellado 'limpie' el
    documento de la marca que lo delata."""
    plan = make_plan(workspace="otra-campana")
    plan["engine_version"] = "9.9.9"  # manipulacion adicional, para forzar el sello
    plan = seal_plan(plan)
    result = admit(plan, ctx())
    assert codes.PLAN_WORKSPACE_MISMATCH in result.codes
    assert codes.PLAN_CONTRACT_INVALID not in result.codes  # el sello es valido


def test_un_plan_forjado_con_una_puerta_trasera_muere_en_la_confirmacion_del_hash():
    """El ataque del revisor: anadir una operacion propia y resellar.

    El plan resultante es VALIDO —los hashes cuadran, porque quien reescribe
    puede resellar— y la admision lo admite. Lo que lo para es la condicion 5
    del gate: el operador teclea el hash del plan que REVISO, y ese hash ya no
    es el de este. De ahi que §5.4 de la documentacion no pueda leer el hash del
    plan que se esta autorizando."""
    legitimo = make_plan()
    forjado = make_plan(
        operations=[
            op_create_entity("op:0001", "decision:0001", "entity:daiki"),
            op_create_entity("op:0666", "decision:0001", "entity:PUERTA-TRASERA"),
        ]
    )
    assert admit(forjado, ctx()).admitted  # sellado impecable: la admision pasa

    driver = FakeDriver()
    result = make_writer(driver).write(
        forjado,
        # El operador teclea el hash del plan que reviso, no el del que le dan.
        apply_request(forjado, expected_plan_hash=legitimo["plan_hash"]["value"]),
    )
    assert result.outcome != OUTCOME_APPLIED
    assert codes.GATE_PLAN_HASH_NOT_CONFIRMED in result.codes
    assert driver.writes == []


def test_leer_el_hash_del_plan_que_se_autoriza_anula_la_condicion_5():
    """Lo mismo, con el antipatron: el ataque pasa. Documentado como aviso, no
    como aprobacion — es la razon de existir de H1."""
    forjado = make_plan(
        operations=[
            op_create_entity("op:0001", "decision:0001", "entity:daiki"),
            op_create_entity("op:0666", "decision:0001", "entity:PUERTA-TRASERA"),
        ]
    )
    driver = FakeDriver()
    result = make_writer(driver).write(
        forjado, apply_request(forjado, expected_plan_hash=forjado["plan_hash"]["value"])
    )
    assert result.outcome == OUTCOME_APPLIED
    assert "entity:PUERTA-TRASERA" in result.created_ids


def test_cada_manipulacion_del_cuerpo_sin_resellar_rompe_el_hash():
    mutaciones = {
        "workspace": lambda p: p.update(workspace="otra"),
        "snapshot_id": lambda p: p.update(snapshot_id="snapshot:otro"),
        "expires_at": lambda p: p.update(expires_at="2030-01-01T00:00:00Z"),
        "engine_version": lambda p: p.update(engine_version="9.9.9"),
        "decision": lambda p: p["decisions"][0].update(confidence=0.99),
        "operacion": lambda p: p["mutation_operations"][0]["payload"].update(
            canonical_name="Otro"
        ),
        "aprobacion": lambda p: p["local_approval"].update(approved=False),
    }
    for nombre, mutar in mutaciones.items():
        plan = make_plan()
        mutar(plan)
        result = admit(plan, ctx())
        assert codes.PLAN_CONTRACT_INVALID in result.codes, nombre


# ==========================================================================
# 3. Campos fuera del decision_hash: no pueden decidir NADA
# ==========================================================================
#: Modulos que TOMAN decisiones de escritura. No pueden ni nombrar esos campos.
DECISION_MODULES = (
    "admission.py",
    "gate.py",
    "executor.py",
    "cypher.py",
    "rollback.py",
    "idempotency.py",
    "view.py",
)


def test_la_vista_firmada_no_contiene_los_campos_no_firmados():
    """Estructural: no es que el writer no deba leerlos, es que no los tiene."""
    plan = make_plan(metadata={"nota": "informativa"})
    view = view_of(plan)
    for campo in UNSIGNED_FIELDS:
        assert not hasattr(view, campo), campo


def test_los_modulos_que_deciden_no_nombran_los_campos_no_firmados():
    import knowledge_v3.writer as pkg

    raiz = Path(pkg.__file__).parent
    for nombre in DECISION_MODULES:
        texto = raiz.joinpath(nombre).read_text(encoding="utf-8")
        # `view.py` los declara en UNSIGNED_FIELDS: es su lista de prohibidos.
        cuerpo = texto.split("UNSIGNED_FIELDS")[-1] if nombre == "view.py" else texto
        for campo in ("provider_trace", "plan_id"):
            assert campo not in cuerpo, f"{nombre} nombra {campo}"


def test_alterar_los_campos_no_firmados_y_resellar_no_cambia_ni_una_escritura():
    """La prueba de fondo: mismo plan, cuatro campos informativos distintos,
    mismas consultas, mismos parametros, mismas claves de idempotencia."""
    base = make_plan()
    alterado = make_plan(
        created_at="2026-07-27T09:00:00Z",
        metadata={"origen": "otro", "nota": "esto no decide nada"},
    )
    alterado["plan_id"] = "plan:sustituido:9999"
    alterado["provider_trace"] = [
        {
            "step": "engine.plan",
            "provider": "local",
            "name": "otro.motor",
            "version": "0.0.1",
            "model": "modelo-inventado",
            "produced": ["decisions", "mutation_operations"],
        }
    ]
    alterado = seal_plan(alterado)
    assert alterado["plan_hash"] != base["plan_hash"]  # son documentos distintos

    escrituras = []
    for plan in (base, alterado):
        driver = FakeDriver()
        result = make_writer(driver, applied_keys=InMemoryAppliedKeys()).write(
            plan, apply_request(plan)
        )
        assert result.outcome == OUTCOME_APPLIED, result.codes
        escrituras.append(driver.writes)

    limpias = []
    for writes in escrituras:
        limpias.append(
            [
                (
                    q,
                    {
                        k: v
                        for k, v in p.get("props", p).items()
                        if k != "written_by_plan_hash"
                    },
                )
                for q, p in writes
            ]
        )
    assert limpias[0] == limpias[1]


def test_la_clave_de_idempotencia_no_depende_de_los_campos_no_firmados():
    base = make_plan()
    otro = make_plan(created_at="2026-07-27T09:00:00Z", metadata={"x": "y"})
    otro["plan_id"] = "plan:distinto:0002"
    otro = seal_plan(otro)
    assert (
        base["mutation_operations"][0]["idempotency_key"]
        == otro["mutation_operations"][0]["idempotency_key"]
    )


def test_una_metadata_hostil_no_altera_la_decision():
    plan = make_plan(
        metadata={"approved": "true", "workspace": "otra", "snapshot_id": "el-que-sea"}
    )
    plan = seal_plan(plan)
    driver = FakeDriver()
    result = make_writer(driver).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_APPLIED
    _, params = driver.writes[0]
    assert params["props"]["workspace"] == WORKSPACE


def test_una_metadata_hostil_no_rescata_un_plan_de_otro_workspace():
    plan = seal_plan(make_plan(workspace="otra", metadata={"workspace": WORKSPACE}))
    result = make_writer(ExplodingDriver()).write(plan, apply_request(plan))
    assert result.outcome == OUTCOME_REJECTED
    assert codes.PLAN_WORKSPACE_MISMATCH in result.codes


# ==========================================================================
# 4. Idempotencia: el replay no puede duplicar
# ==========================================================================
def test_el_replay_de_un_plan_completo_no_escribe_ni_una_vez_mas():
    ops = [
        op_create_entity(f"op:{i:04d}", "decision:0001", f"entity:e{i}")
        for i in range(3)
    ]
    plan = make_plan(operations=ops)
    keys = InMemoryAppliedKeys()
    primero = FakeDriver()
    make_writer(primero, applied_keys=keys).write(plan, apply_request(plan))
    assert len(primero.writes) == 3

    for _ in range(3):
        repetido = FakeDriver()
        result = make_writer(repetido, applied_keys=keys).write(plan, apply_request(plan))
        assert repetido.writes == []
        assert result.noop_operations == 3


def test_vaciar_el_almacen_de_claves_es_lo_unico_que_permite_reescribir():
    """Documenta la dependencia real: la idempotencia vive en el almacen. Si
    alguien lo borra, el writer vuelve a escribir. No se disimula."""
    plan = make_plan()
    keys = InMemoryAppliedKeys()
    make_writer(FakeDriver(), applied_keys=keys).write(plan, apply_request(plan))
    keys.entries.clear()
    driver = FakeDriver()
    result = make_writer(driver, applied_keys=keys).write(plan, apply_request(plan))
    assert result.applied_operations == 1
    assert len(driver.writes) == 1


# ==========================================================================
# 5. Codigos: nada de rechazos mudos
# ==========================================================================
def test_los_codigos_no_se_repiten_entre_familias():
    assert len(set(codes.ALL_CODES)) == len(codes.ALL_CODES)


def test_toda_familia_de_codigos_esta_en_all_codes():
    assert set(codes.ADMISSION_CODES) <= set(codes.ALL_CODES)
    assert set(codes.GATE_CODES) <= set(codes.ALL_CODES)
    assert set(codes.EXECUTION_CODES) <= set(codes.ALL_CODES)


def test_la_tabla_de_la_documentacion_cubre_todos_los_codigos():
    doc = Path(__file__).resolve().parents[3] / "docs" / "v3" / "09-writer.md"
    texto = doc.read_text(encoding="utf-8")
    faltan = [c for c in codes.ALL_CODES if c not in texto]
    assert not faltan, f"codigos sin documentar: {faltan}"
