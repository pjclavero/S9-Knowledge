# -*- coding: utf-8 -*-
"""TANDA 3 / INTEGRACION -- el contrato REAL de identidad de `Assertion`.

    workspace W · partida A · assertion_id X
    workspace W · partida B · assertion_id X

Se contesta MIDIENDO, no interpretando:

  1. que EXIGE el contrato (contratos congelados + esquemas + diseno);
  2. que PERMITE de verdad el writer, y que permite el ESQUEMA, contra Neo4j
     real -- con la restriccion puesta Y sin ella, porque la base productiva
     no tiene ni una restriccion y sin retirarla no se reproduce;
  3. si coinciden.

La trampa que se evita a proposito: «el writer no lo permite» NO es «el
contrato lo prohibe». Son cosas distintas, y por eso se miden por separado --
el writer con su puerta de creacion, y el esquema con Cypher crudo, que no
pasa por ninguna puerta del writer.

    S9K_WRITER_NEO4J_REAL=1 python3 \
        artifacts/tanda3-integracion/reproduccion_identidad_assertion.py

No toca produccion: levanta y destruye su propio contenedor. La restriccion se
retira sobre esa base EFIMERA, nunca sobre otra, y se REPONE al salir --
verificandolo, no dandolo por hecho.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
APP = RAIZ / "data-engine" / "app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "tests"))
os.environ.setdefault("S9K_WRITER_NEO4J_REAL", "1")

import test_knowledge_v3_writer_neo4j_real as W  # noqa: E402

from knowledge_v3.writer import bootstrap_writer_schema, codes  # noqa: E402
from knowledge_v3.writer.schema import (  # noqa: E402
    V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT,
    V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT_CYPHER,
)

WS = W.WORKSPACE
FALLOS: list[str] = []
HALLAZGOS: dict[str, object] = {}


def comprobar(condicion: bool, titulo: str) -> bool:
    print("   [%s] %s" % ("OK " if condicion else "FALLO", titulo))
    if not condicion:
        FALLOS.append(titulo)
    return condicion


def _restricciones(probe) -> list[str]:
    """Que restricciones hay AHORA. Se pregunta, no se supone."""
    return [
        f["name"]
        for f in probe.run("SHOW CONSTRAINTS YIELD name RETURN name ORDER BY name")
    ]


def _aserciones(probe) -> list[dict]:
    return probe.run(
        "MATCH (n:V3Assertion {workspace: $ws, assertion_id: 'assertion:x'}) "
        "RETURN n.partida_id AS partida ORDER BY partida",
        {"ws": WS},
    )


def _crear_por_cypher(probe, partida) -> tuple[bool, str]:
    """Creacion CRUDA. No pasa por ninguna puerta del writer: lo que aqui
    ocurra lo decide el ESQUEMA y solo el esquema."""
    try:
        probe.run(
            "CREATE (n:V3Assertion {assertion_id:'assertion:x', workspace:$ws, "
            "partida_id:$p, idempotency_key:'idem:manual'})",
            {"ws": WS, "p": partida},
        )
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__ + ": " + str(exc)[:160]


def _crear_por_writer(graph, partida, decision: str = "decision:1") -> tuple[bool, str]:
    """Creacion por la PUERTA DEL WRITER (`_assert_absent` incluida).

    `decision` existe para poder separar DOS barreras que se confunden con
    facilidad. Con la misma `decision_id`, dos planes de partidas distintas
    con la misma identidad logica producen la MISMA `idempotency_key` (es
    conocido y esta documentado en docs/v3/49 y en `validator.py`), asi que el
    rechazo llega por `EXEC_IDEMPOTENCY_CONFLICT` -- que es fail-closed, pero
    NO es la barrera de unicidad del `assertion_id`. Cambiando la decision
    cambia la clave, la barrera de idempotencia deja de aplicar, y lo que
    responda entonces es `_assert_absent`: la barrera que aqui se quiere medir.
    """
    plan = W.make_plan(
        [
            W.create_assertion(
                "op:0001", "assertion:x", "entity:a", "entity:b", decision
            )
        ]
    )
    if partida is not None:
        plan["partida_id"] = partida
        # `game_id` es OBLIGATORIO en `mutation_plan_scope`. Sin el, el plan
        # se cae en admision con `PLAN_CONTRACT_INVALID` y NUNCA llega a la
        # puerta de creacion del writer: la medida seria un rojo prestado que
        # parece decir «el writer lo rechaza» cuando lo rechazo el validador
        # de contrato por otro motivo.
        plan["scope"] = {
            "layer": "PARTIDA",
            "game_id": plan["workspace"],
            "partida_id": partida,
        }
        from knowledge_v3.contracts.base import seal_plan

        plan = seal_plan(plan)
    try:
        resultado = W.writer(graph.driver).write(plan, W.apply_request(plan))
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__ + ": " + str(exc)[:160]
    if resultado.outcome != W.OUTCOME_APPLIED:
        return False, f"{resultado.outcome} {resultado.codes}"
    return True, "APPLIED"


#: Codigos que significan «la puerta de CREACION del writer dijo que no».
#: Cualquier otro rechazo (p.ej. `PLAN_CONTRACT_INVALID`) seria un rojo
#: PRESTADO: el plan ni siquiera habria llegado a `_assert_absent`.
#: Se toman del modulo, NO se escriben a mano: un codigo mal tecleado no casa
#: nunca y convierte la comprobacion en un verde (o un rojo) inventado. Fue
#: exactamente lo que paso en la primera pasada de este arnes, con
#: `EXEC_TARGET_EXISTS`, que no existe -- el real es
#: `EXEC_TARGET_ALREADY_EXISTS`.
CODIGO_ID_YA_EXISTE = codes.EXEC_TARGET_ALREADY_EXISTS
CODIGO_IDEMPOTENCIA = codes.EXEC_IDEMPOTENCY_CONFLICT
CODIGOS_DE_LA_PUERTA = (CODIGO_ID_YA_EXISTE, CODIGO_IDEMPOTENCIA)


def main() -> int:
    print("=" * 78)
    print("1. QUE EXIGE EL CONTRATO (leido, no supuesto)")
    print("=" * 78)

    esquema = json.loads(
        (RAIZ / "contracts/knowledge-v3/v1/fact-assertion-v3.schema.json").read_text(
            encoding="utf-8"
        )
    )
    props = esquema.get("properties", {})
    sin_ambito = "partida_id" not in props and "scope" not in props
    cerrado = esquema.get("additionalProperties") is False
    print("   fact-assertion-v3.schema.json (CONGELADO)")
    print("     additionalProperties : %s" % esquema.get("additionalProperties"))
    print("     partida_id en props  : %s" % ("partida_id" in props))
    print("     scope en props       : %s" % ("scope" in props))
    comprobar(
        sin_ambito and cerrado,
        "el contrato de FactAssertion NO tiene campo de ambito y es cerrado: "
        "una asercion no puede ni declarar en que partida vive",
    )
    HALLAZGOS["contrato_sin_ambito"] = sin_ambito and cerrado

    # La regla, dicha con todas las letras en el diseno congelado.
    diseno = (RAIZ / "docs/v3/49-multipartida-diseno.md").read_text(encoding="utf-8")
    regla = (
        "un `entity_id`/`assertion_id` es único en TODO el\n"
        "workspace, cruzando capa juego y todas sus partidas"
    )
    comprobar(
        regla in diseno,
        "docs/v3/49 lo dice literalmente: el id es unico en TODO el workspace, "
        "cruzando capa juego y todas sus partidas",
    )
    HALLAZGOS["regla_en_diseno"] = regla in diseno

    print()
    print("=" * 78)
    print("2. QUE PERMITEN DE VERDAD EL WRITER Y EL ESQUEMA (Neo4j real)")
    print("=" * 78)

    with W.neo4j_efimero_conexion("s9k-identidad-assertion") as cx:
        probe = W.GraphProbe(cx.driver)
        bootstrap_writer_schema(cx.driver)

        antes = _restricciones(probe)
        puesta = V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT in antes
        comprobar(puesta, "la restriccion de identidad de asercion esta puesta")
        print("     restricciones: %d" % len(antes))

        # --- 2A. CON la restriccion -------------------------------------
        print("\n   --- 2A. CON la restriccion puesta ---")
        probe.run("MATCH (n) DETACH DELETE n")
        probe.seed_entity("entity:a", version=1, state_hash=W.HASH_A["value"])
        probe.seed_entity("entity:b", version=1, state_hash=W.HASH_B["value"])
        ok, detalle = _crear_por_writer(probe, None)
        comprobar(ok, "capa juego: el writer crea assertion:x (%s)" % detalle)

        ok_gemelo, detalle_gemelo = _crear_por_cypher(probe, "partida:otra")
        print("     gemelo por Cypher crudo -> %s" % (detalle_gemelo or "CREADO"))
        comprobar(
            not ok_gemelo,
            "CON restriccion, el ESQUEMA rechaza el gemelo de otra partida",
        )
        con_restriccion = _aserciones(probe)
        print("     aserciones assertion:x: %s" % con_restriccion)
        comprobar(len(con_restriccion) == 1, "queda UNA sola assertion:x")
        HALLAZGOS["con_restriccion_gemelo_creado"] = ok_gemelo

        # --- 2B. SIN la restriccion (reproduce la base productiva) -------
        print("\n   --- 2B. SIN la restriccion (como la base real) ---")
        probe.run(f"DROP CONSTRAINT {V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT}")
        retirada = V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT not in _restricciones(probe)
        comprobar(retirada, "la restriccion se retiro de verdad (medido, no supuesto)")

        probe.run("MATCH (n) DETACH DELETE n")
        probe.seed_entity("entity:a", version=1, state_hash=W.HASH_A["value"])
        probe.seed_entity("entity:b", version=1, state_hash=W.HASH_B["value"])
        ok, detalle = _crear_por_writer(probe, None)
        comprobar(ok, "capa juego: el writer crea assertion:x (%s)" % detalle)

        # (i) por Cypher crudo: sin esquema que lo impida, ENTRA.
        ok_crudo, detalle_crudo = _crear_por_cypher(probe, "partida:otra")
        sin_restriccion = _aserciones(probe)
        print("     gemelo por Cypher crudo -> %s" % (detalle_crudo or "CREADO"))
        print("     aserciones assertion:x: %s" % sin_restriccion)
        comprobar(
            ok_crudo and len(sin_restriccion) == 2,
            "SIN restriccion el esquema NO lo impide: el gemelo entra por Cypher. "
            "Esto es exactamente lo que hoy admitiria la base productiva",
        )
        HALLAZGOS["sin_restriccion_gemelo_creado"] = ok_crudo

        # (ii) por el WRITER: la puerta de creacion sigue mandando aunque el
        #      esquema ya no diga nada. Aqui esta la distincion que pedia el
        #      operador: writer y esquema son DOS barreras distintas.
        probe.run("MATCH (n) DETACH DELETE n")
        probe.seed_entity("entity:a", version=1, state_hash=W.HASH_A["value"])
        probe.seed_entity("entity:b", version=1, state_hash=W.HASH_B["value"])
        _crear_por_writer(probe, None)
        ok_writer, detalle_writer = _crear_por_writer(probe, "partida:otra")
        por_writer = _aserciones(probe)
        print("     gemelo por el WRITER -> %s" % detalle_writer)
        print("     aserciones assertion:x: %s" % por_writer)
        de_la_puerta = any(c in detalle_writer for c in CODIGOS_DE_LA_PUERTA)
        comprobar(
            not ok_writer and len(por_writer) == 1,
            "SIN restriccion, el WRITER sigue rechazando el gemelo: "
            "las barreras del writer no dependen del esquema",
        )
        comprobar(
            de_la_puerta,
            "y lo rechaza LA PUERTA DE CREACION (%s), no el validador de "
            "contrato: sin esto el rojo seria prestado"
            % ", ".join(CODIGOS_DE_LA_PUERTA),
        )
        HALLAZGOS["rechazo_es_de_la_puerta"] = de_la_puerta
        HALLAZGOS["codigo_misma_decision"] = detalle_writer

        # (iii) LAS DOS BARRERAS, SEPARADAS. Arriba el rechazo llego por
        #       idempotencia, porque dos partidas con la misma identidad
        #       logica comparten clave. Eso es fail-closed, pero no demuestra
        #       nada sobre la unicidad del `assertion_id`. Con otra decision
        #       la clave cambia y la barrera de idempotencia deja de aplicar:
        #       lo que conteste ahora es `_assert_absent`.
        probe.run("MATCH (n) DETACH DELETE n")
        probe.seed_entity("entity:a", version=1, state_hash=W.HASH_A["value"])
        probe.seed_entity("entity:b", version=1, state_hash=W.HASH_B["value"])
        _crear_por_writer(probe, None)
        ok_id, detalle_id = _crear_por_writer(probe, "partida:otra", "decision:2")
        solo_una = _aserciones(probe)
        print("     gemelo por el WRITER con OTRA decision -> %s" % detalle_id)
        print("     aserciones assertion:x: %s" % solo_una)
        es_de_absent = CODIGO_ID_YA_EXISTE in detalle_id
        comprobar(
            not ok_id and len(solo_una) == 1,
            "con la clave de idempotencia YA DISTINTA, el writer sigue "
            "rechazando el gemelo",
        )
        comprobar(
            es_de_absent,
            "y ahora el motivo es %s, es decir `_assert_absent`: la barrera de "
            "UNICIDAD DEL ID, separada de la de idempotencia" % CODIGO_ID_YA_EXISTE,
        )
        HALLAZGOS["assert_absent_rechaza_por_id"] = es_de_absent
        HALLAZGOS["codigo_otra_decision"] = detalle_id
        HALLAZGOS["sin_restriccion_writer_rechaza"] = not ok_writer
        HALLAZGOS["motivo_rechazo_writer"] = detalle_writer

        # --- 2C. reponer, y VERIFICARLO --------------------------------
        print("\n   --- 2C. reponer la restriccion ---")
        probe.run("MATCH (n) DETACH DELETE n")  # el gemelo impediria recrearla
        probe.run(V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT_CYPHER)
        final = _restricciones(probe)
        comprobar(
            V3_ASSERTION_DURABLE_IDENTITY_CONSTRAINT in final,
            "la restriccion esta REPUESTA (verificado preguntando a la base)",
        )
        comprobar(
            sorted(final) == sorted(antes),
            "el juego de restricciones quedo como estaba: %d -> %d"
            % (len(antes), len(final)),
        )

    print()
    print("=" * 78)
    print("3. COINCIDEN?")
    print("=" * 78)
    coinciden = (
        HALLAZGOS.get("contrato_sin_ambito")
        and HALLAZGOS.get("regla_en_diseno")
        and not HALLAZGOS.get("con_restriccion_gemelo_creado")
        and HALLAZGOS.get("sin_restriccion_writer_rechaza")
        and HALLAZGOS.get("assert_absent_rechaza_por_id")
    )
    comprobar(
        bool(coinciden),
        "contrato, writer y esquema norman LO MISMO: `assertion_id` es unico "
        "por `workspace`, cruzando capa juego y todas las partidas",
    )
    print()
    print("   VEREDICTO: `assertion_id` es UNICO POR WORKSPACE **POR CONTRATO**.")
    print("     -> la restriccion (workspace, assertion_id) es CORRECTA")
    print("     -> `partida_id` es atributo / contexto, NO identidad")
    print("     -> NO bloquea el Vertical Slice 1")
    print("     -> y NO hay asimetria con `entity`: la clave de producto es")
    print("        `(workspace, entity_id)`, exactamente la misma forma.")
    print()
    print("   MATIZ MEDIDO, que no cambia el veredicto pero conviene decir:")
    print("     el ESQUEMA y el WRITER son dos barreras distintas. Sin la")
    print("     restriccion --que es como esta HOY la base productiva-- el")
    print("     esquema admite el gemelo por Cypher crudo; solo el writer lo")
    print("     frena. Todo lo que no entre por el writer queda sin cubrir.")
    print()
    print("=" * 78)
    if FALLOS:
        print("FALLOS (%d):" % len(FALLOS))
        for f in FALLOS:
            print("  - " + f)
        return 1
    print("TODAS LAS COMPROBACIONES EN VERDE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
