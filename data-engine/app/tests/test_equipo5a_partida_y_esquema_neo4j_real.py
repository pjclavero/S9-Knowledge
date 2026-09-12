# -*- coding: utf-8 -*-
"""EQUIPO 5A -- las tres propiedades, OBSERVADAS contra un Neo4j real.

Este fichero no comprueba que el codigo diga lo que queremos: comprueba lo que
el GRAFO tiene despues. Los tres defectos que ataca nacieron, los tres, de
presumir una propiedad en vez de mirarla.

  A. El ambito de partida se perdia: `partida_id` NULL en todo, misma
     `idempotency_key` para dos partidas, y la segunda reutilizando en
     silencio el nodo y la arista de la primera.
  B. Las constraints estaban DEFINIDAS y no INSTALADAS: `SHOW CONSTRAINTS`
     devolvia cero sobre un grafo con un apply real detras.
  C. Un alta APROBADA por una persona se descartaba sin mensaje por falta de
     `entity_type`.

CONTROL NEGATIVO: cada bloque trae su prueba de que sabe ponerse roja
(`test_*_control_negativo`). Una comprobacion que no puede fallar no es una
comprobacion.

Activar con S9K_WRITER_NEO4J_REAL=1, igual que el resto de la familia.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

LIVE = os.environ.get("S9K_WRITER_NEO4J_REAL", "").strip() == "1"
pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="Neo4j real: activar con S9K_WRITER_NEO4J_REAL=1",
)

from knowledge_v3.contracts.base import compute_idempotency_key  # noqa: E402
from knowledge_v3.pipeline import entity_decisions  # noqa: E402
from knowledge_v3.writer import codes, schema  # noqa: E402
from knowledge_v3.writer.writer import OUTCOME_ABORTED, OUTCOME_APPLIED  # noqa: E402

from test_knowledge_v3_estado_durable_neo4j_real import (  # noqa: E402,F401
    neo4j_driver,
    neo4j_driver_efimero,
    probe,
    writer,
)

from test_knowledge_v3_writer_neo4j_real import (  # noqa: E402,F401
    WORKSPACE,
    apply_request,
    create_assertion,
    create_entity,
    make_plan,
)

def _quitar_constraints(driver) -> None:
    """Deja el grafo SIN restricciones, como estaba el de produccion medido.

    `probe.clean()` borra nodos, no esquema: sin esto, la sesion compartida
    (que arranca haciendo `bootstrap_writer_schema`) haria que los tests de
    "faltan constraints" pasaran o fallaran por el estado que dejo otro
    fichero, no por lo suyo.
    """
    with driver.session() as s:
        for nombre in [r["name"] for r in s.run("SHOW CONSTRAINTS YIELD name RETURN name")]:
            s.run(f"DROP CONSTRAINT `{nombre}` IF EXISTS").consume()


@pytest.fixture()
def grafo_sin_esquema(probe):
    """Grafo vacio Y sin restricciones. Estado de partida de un Neo4j nuevo."""
    _quitar_constraints(probe.driver)
    yield probe.driver
    # Se devuelve el esquema para no dejar a los demas ficheros peor de lo
    # que estaban: la sesion lo instalo al arrancar.
    schema.bootstrap_writer_schema(probe.driver)


@pytest.fixture()
def grafo_con_esquema(probe):
    """Grafo vacio con el esquema requerido puesto y observado."""
    schema.bootstrap_writer_schema(probe.driver)
    assert schema.missing_required_constraints(probe.driver) == []
    return probe.driver


PARTIDA_Y = "partida:Y"
PARTIDA_Z = "partida:Z"


def _scope(partida_id: str) -> dict:
    return {"layer": "PARTIDA", "game_id": WORKSPACE, "partida_id": partida_id}


def _plan_de_partida(partida_id: str, *, sufijo: str) -> dict:
    """LA MISMA fuente y las MISMAS operaciones logicas, en dos ambitos.

    Los `entity_id`/`assertion_id` se separan por partida porque eso es lo
    que exige `executor._assert_absent` ("dos ambitos jamas comparten el
    mismo id"). Lo que queda IDENTICO entre las dos partidas es la identidad
    LOGICA que alimenta la `idempotency_key` salvo el ambito, que es el punto
    del test.
    """
    operaciones = [
        create_entity(f"op:e1:{sufijo}", f"entity:capitana:{sufijo}", "Ilva Roen"),
        create_entity(f"op:e2:{sufijo}", f"entity:nave:{sufijo}", "Alba"),
        create_assertion(
            f"op:a1:{sufijo}",
            f"assertion:manda:{sufijo}",
            f"entity:capitana:{sufijo}",
            f"entity:nave:{sufijo}",
        ),
    ]
    # T2: en ambito de PARTIDA, `known_from_session` es obligatorio por
    # operacion y su ausencia aborta con `EXEC_REVELACION_NO_DECLARADA`. Es
    # una regla real del producto (visibilidad, M5b) y este equipo no la
    # toca: se CUMPLE declarando la sesion, que es lo que el contrato pide.
    # Saltarsela habria sido relajar una barrera ajena para que pasara un
    # test propio.
    for operacion in operaciones:
        operacion["payload"]["known_from_session"] = 0
    return make_plan(
        operaciones,
        plan_id=f"plan:5a:{sufijo}",
        partida_id=partida_id,
        scope=_scope(partida_id),
    )


# ---------------------------------------------------------------------------
# B. El esquema: instalado y OBSERVADO, no declarado
# ---------------------------------------------------------------------------
def test_ensure_instala_las_constraints_y_se_observan(grafo_sin_esquema):
    """Grafo vacio -> ruta de esquema -> `SHOW CONSTRAINTS` las ve."""
    driver = grafo_sin_esquema
    assert schema.missing_required_constraints(driver) == list(
        schema.REQUIRED_CONSTRAINT_NAMES
    ), "el grafo de partida no estaba vacio de constraints: el test no mide lo que cree"

    schema.bootstrap_writer_schema(driver)

    # NO se pregunta al modulo: se pregunta AL SERVIDOR.
    with driver.session() as s:
        observadas = {r["name"] for r in s.run("SHOW CONSTRAINTS YIELD name RETURN name")}
    for nombre in schema.REQUIRED_CONSTRAINT_NAMES:
        assert nombre in observadas, f"{nombre} sigue sin instalarse"


def test_ensure_es_idempotente(grafo_sin_esquema):
    driver = grafo_sin_esquema
    schema.bootstrap_writer_schema(driver)
    with driver.session() as s:
        primera = {r["name"] for r in s.run("SHOW CONSTRAINTS YIELD name RETURN name")}
    schema.bootstrap_writer_schema(driver)  # segunda vez: no debe romper
    with driver.session() as s:
        segunda = {r["name"] for r in s.run("SHOW CONSTRAINTS YIELD name RETURN name")}
    assert primera == segunda and primera, "la segunda ejecucion cambio el censo"


def test_apply_falla_cerrado_sin_constraints(writer, grafo_sin_esquema):
    """CRITERIO 2. Sin esquema, `--apply` NO escribe: aborta y lo dice."""
    plan = _plan_de_partida(PARTIDA_Y, sufijo="sinesquema")
    resultado = writer.write(plan, apply_request(plan))
    assert resultado.outcome == OUTCOME_ABORTED
    assert codes.EXEC_SCHEMA_CONSTRAINTS_MISSING in resultado.codes
    # Y no ha escrito nada.
    with grafo_sin_esquema.session() as s:
        n = s.run(
            "MATCH (n:V3Entity {workspace: $ws}) RETURN count(n) AS n", ws=WORKSPACE
        ).single()["n"]
    assert n == 0, "aborto pero dejo nodos: no fallo cerrado"


def test_apply_falla_cerrado_control_negativo(writer, grafo_con_esquema):
    """CONTROL NEGATIVO de B: con el esquema puesto, ese codigo NO sale.

    Si saliera igualmente, la comprobacion de arriba estaria pasando por una
    razon que no es la suya.
    """
    plan = _plan_de_partida(PARTIDA_Y, sufijo="conesquema")
    resultado = writer.write(plan, apply_request(plan))
    assert codes.EXEC_SCHEMA_CONSTRAINTS_MISSING not in resultado.codes
    assert resultado.outcome == OUTCOME_APPLIED


# ---------------------------------------------------------------------------
# A. Dos partidas, cero reutilizacion
# ---------------------------------------------------------------------------
def test_dos_partidas_no_comparten_idempotency_key():
    """CRITERIO 3, primera mitad: la clave DISTINGUE ambito.

    Se compara la clave de la MISMA operacion logica calculada bajo dos
    ambitos. Antes de este trabajo las dos daban `idem:sha256:f49c49d1...`.
    """
    y = _plan_de_partida(PARTIDA_Y, sufijo="y")
    z = _plan_de_partida(PARTIDA_Z, sufijo="z")
    op_y = next(o for o in y["mutation_operations"] if o["operation_type"] == "CREATE_ENTITY")
    op_z = next(o for o in z["mutation_operations"] if o["operation_type"] == "CREATE_ENTITY")
    # Se neutraliza lo que ya diferia por construccion (los ids), para que la
    # unica diferencia que quede en juego sea el AMBITO. Si no, el test
    # pasaria por el motivo equivocado.
    op_z_igualada = dict(op_z)
    op_z_igualada["target_entity_id"] = op_y["target_entity_id"]
    op_z_igualada["decision_id"] = op_y["decision_id"]
    op_z_igualada["payload"] = op_y["payload"]

    clave_y = compute_idempotency_key(y, op_y)
    clave_z = compute_idempotency_key(z, op_z_igualada)
    assert clave_y != clave_z, (
        "dos partidas comparten idempotency_key: la fuga sigue abierta"
    )


def test_capa_juego_conserva_su_clave_historica():
    """CONTROL DE NO REGRESION: un plan SIN ambito no cambia de clave.

    Es lo que hace que este cambio no obligue a regenerar los 264+ documentos
    ya sellados de heldout/negation-battery/benchmarks. Se comprueba que la
    clave de un plan sin `partida_id` es exactamente la que sale del cuerpo
    historico (workspace + snapshot + identidad logica), sin `partida_id`.
    """
    from knowledge_v3.contracts.base import sha256_hash

    plan = make_plan(
        [create_entity("op:e1", "entity:lore", "Lore")], plan_id="plan:5a:lore"
    )
    assert "partida_id" not in plan and "scope" not in plan
    op = plan["mutation_operations"][0]
    cuerpo_historico = {
        "workspace": plan["workspace"],
        "snapshot_id": plan["snapshot_id"],
        "operation_type": op.get("operation_type"),
        "decision_id": op.get("decision_id"),
        "target_entity_id": op.get("target_entity_id"),
        "assertion_id": op.get("assertion_id"),
        "payload": op.get("payload"),
    }
    esperada = "idem:sha256:" + sha256_hash(cuerpo_historico)["value"]
    assert compute_idempotency_key(plan, op) == esperada


def test_dos_partidas_ninguna_reutiliza_el_objeto_de_la_otra(writer, grafo_con_esquema):
    """CRITERIO 3, segunda mitad: CENSO antes y despues, contra el grafo."""
    driver = grafo_con_esquema

    def censo() -> dict:
        with driver.session() as s:
            # UNA consulta por cosa contada. Dos MATCH sueltos en la misma
            # consulta dan producto cartesiano y, con un lado vacio, CERO
            # filas -- un censo que miente justo cuando mas importa.
            ent = s.run(
                "MATCH (n:V3Entity {workspace: $ws}) RETURN count(n) AS c", ws=WORKSPACE
            ).single()["c"]
            ase = s.run(
                "MATCH (n:V3Assertion {workspace: $ws}) RETURN count(n) AS c", ws=WORKSPACE
            ).single()["c"]
            ops = s.run(
                "MATCH (n:V3AppliedOperation {workspace: $ws}) RETURN count(n) AS c",
                ws=WORKSPACE,
            ).single()["c"]
            return {"entidades": ent, "aserciones": ase, "operaciones": ops}

    antes = censo()
    assert antes == {"entidades": 0, "aserciones": 0, "operaciones": 0}

    r_y = writer.write(_plan_de_partida(PARTIDA_Y, sufijo="y"),
                       apply_request(_plan_de_partida(PARTIDA_Y, sufijo="y")))
    assert r_y.outcome == OUTCOME_APPLIED, r_y.codes
    tras_y = censo()

    r_z = writer.write(_plan_de_partida(PARTIDA_Z, sufijo="z"),
                       apply_request(_plan_de_partida(PARTIDA_Z, sufijo="z")))
    assert r_z.outcome == OUTCOME_APPLIED, r_z.codes
    tras_z = censo()

    # La segunda partida CREA lo suyo. Si reutilizase, los censos serian
    # iguales y el conjunto de `noop` no estaria vacio.
    assert r_z.noop_operations == 0, "la segunda partida declaro no-op: esta reutilizando"
    for clave in ("entidades", "aserciones", "operaciones"):
        assert tras_z[clave] > tras_y[clave], (
            f"{clave}: la segunda partida no aporto nada nuevo "
            f"({tras_y[clave]} -> {tras_z[clave]})"
        )

    # Y cada objeto lleva SU ambito estampado -- incluida la marca de
    # operacion, que antes ni siquiera tenia la clave `partida_id`.
    with driver.session() as s:
        for etiqueta in ("V3Entity", "V3Assertion", "V3AppliedOperation"):
            filas = list(s.run(
                f"MATCH (n:{etiqueta} {{workspace: $ws}}) "
                "RETURN n.partida_id AS p", ws=WORKSPACE
            ))
            assert filas, f"censo vacio para {etiqueta}: no se esta midiendo nada"
            ambitos = {f["p"] for f in filas}
            assert ambitos == {PARTIDA_Y, PARTIDA_Z}, (
                f"{etiqueta} no lleva los dos ambitos estampados: {ambitos}"
            )


# ---------------------------------------------------------------------------
# C. Un alta aprobada no desaparece
# ---------------------------------------------------------------------------
def _ledger_con_alta(entity_type):
    d = entity_decisions.EntityDecision(
        resolution_id="res:1",
        decision=entity_decisions.CREATE_ENTITY_REQUIRED,
        entity_id="entity:new:ilva",
        entity_type=entity_type,
        name="Ilva Roen",
        aliases=(),
        mention_ids=("m1",),
        confidence=0.9,
        reason_codes=("AUSENTE_DEL_GRAFO",),
        review=entity_decisions.APROBADA,
        approved_by="pjc",
        approved_at="2026-09-06T00:00:00Z",
    )
    return entity_decisions.DecisionLedger(
        workspace=WORKSPACE, partida_id=PARTIDA_Y,
        source_path="fuente.md", generated_at="2026-09-06T00:00:00Z",
        decisions=(d,), carencias=(),
    )


def test_alta_aprobada_sin_tipo_no_desaparece_en_silencio():
    """CRITERIO 4. Antes devolvia [] y el mando seguia diciendo 'aprobadas: 1'."""
    with pytest.raises(entity_decisions.AltaAprobadaSinTipo) as exc:
        entity_decisions.approved_snapshot_entities(_ledger_con_alta(None))
    # El mensaje NOMBRA el alta y dice como resolverlo. Un error que no dice
    # cual es reproduce el problema con otra cara.
    assert "entity:new:ilva" in str(exc.value)
    assert "--tipo-alta" in str(exc.value)


def test_alta_aprobada_con_tipo_si_se_crea():
    """CONTROL NEGATIVO de C: con tipo, el alta pasa. La barrera discrimina."""
    salida = entity_decisions.approved_snapshot_entities(_ledger_con_alta("Character"))
    assert salida == [{
        "entity_id": "entity:new:ilva",
        "type": "Character",
        "name": "Ilva Roen",
        # EQUIPO 8A: los alias viajan con el alta hasta el nodo. Este ledger
        # de prueba no declara ninguno, asi que la lista sale VACIA -- y sale
        # explicitamente, no ausente: el dia que el alta traiga alias y no
        # lleguen al snapshot, esta comparacion exacta se pone roja.
        "aliases": [],
        "pending_creation": True,
    }]


def test_el_revisor_puede_declarar_el_tipo_al_aprobar():
    """La via que el producto ofrece cuando el resolutor no pudo inferirlo."""
    pendiente = entity_decisions.EntityDecision(
        resolution_id="res:1",
        decision=entity_decisions.CREATE_ENTITY_REQUIRED,
        entity_id="entity:new:ilva",
        entity_type=None,
        name="Ilva Roen",
        aliases=(),
        mention_ids=("m1",),
        confidence=0.9,
        reason_codes=("AUSENTE_DEL_GRAFO",),
        review=entity_decisions.PENDIENTE,
    )
    ledger = entity_decisions.DecisionLedger(
        workspace=WORKSPACE, partida_id=PARTIDA_Y,
        source_path="fuente.md", generated_at="2026-09-06T00:00:00Z",
        decisions=(pendiente,), carencias=(),
    )
    nuevo = entity_decisions.approve(
        ledger, ["entity:new:ilva"], reviewer="pjc", at="2026-09-06T00:00:00Z",
        entity_types={"entity:new:ilva": "Character"},
    )
    assert entity_decisions.approved_snapshot_entities(nuevo)[0]["type"] == "Character"
