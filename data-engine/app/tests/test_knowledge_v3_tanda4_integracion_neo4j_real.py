# -*- coding: utf-8 -*-
"""Tanda 4 integrada: las tres propiedades VIVAS A LA VEZ, y el ciclo cerrado.

QUE NO CUBRIA NADIE
-------------------
Cada equipo probo lo suyo por separado y las tres pruebas pasaban en ramas
distintas:

* **4A** -- `apply` deja `S1`; repetirlo deja `S1` EXACTO (huella del contenido,
  sin `elementId`).
* **4B** -- el mando `cli_rollback` ejecuta de verdad y deja `S0`.
* **4C** -- `BLOCKED` sale con `rc != 0`, un desenlace limpio con `rc = 0`, y
  ninguna frase afirma algo que no ocurrio.

Lo que nadie habia ejecutado es la COMBINACION, que es donde las tres se tocan:

    apply  ->  repeat apply  ->  rollback  ->  apply otra vez

Antes de 4A el segundo apply reventaba (`EXEC_IDEMPOTENCY_CONFLICT`), asi que
esta secuencia no llegaba ni a empezar. Antes de 4B el rollback no retiraba
`V3AppliedOperation`, asi que el ultimo apply se habria declarado `no-op` sobre
un grafo VACIO: el mando habria dicho "ya estaba aplicado" con el conocimiento
borrado. Las dos mitades juntas son las que hacen que el ciclo cierre, y eso es
justo lo que se mide aqui: **tras revertir se puede volver a aplicar desde cero
y el grafo vuelve a `S1`**.

COMO SE MIDE, PARA QUE EL VERDE SIGNIFIQUE ALGO
-----------------------------------------------
* `S1` se compara por HUELLA del contenido (`_huella` de 4A), que ignora el
  `elementId` a proposito: `elementId` no es identidad durable y cambia entre
  bases. La identidad de producto es `(workspace, entity_id)`.
* `S0` no se afirma con "no encontre nada": se cuenta, y ANTES se comprueba que
  el conjunto era no vacio. Un `MATCH` que devuelve cero filas por estar mal
  escrito es indistinguible de un grafo limpio si no se mide el antes.
* El `state_hash` de cada nodo se RECALCULA desde las propiedades leidas. No se
  comprueba que "hay un hash": se comprueba que DESCRIBE el nodo.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("neo4j")

LIVE = os.environ.get("S9K_WRITER_NEO4J_REAL", "").strip() == "1"
pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="Neo4j real: activar con S9K_WRITER_NEO4J_REAL=1",
)

from knowledge_v3.writer import cli_rollback, exit_codes  # noqa: E402
from knowledge_v3.writer.state import state_hash_value  # noqa: E402
from knowledge_v3.writer.writer import OUTCOME_APPLIED  # noqa: E402

from test_knowledge_v3_estado_durable_neo4j_real import (  # noqa: E402,F401
    _huella,
    neo4j_driver,
    neo4j_driver_efimero,
    probe,
    writer,
)
from test_knowledge_v3_writer_neo4j_real import (  # noqa: E402,F401
    WORKSPACE,
    GraphProbe,
    apply_request,
    create_assertion,
    create_entity,
    make_plan,
)

APP_DIR = Path(__file__).resolve().parent.parent


def _plan_ciclo() -> dict:
    """Dos entidades y una asercion que las une. Un `S1` con aristas."""
    return make_plan(
        [
            create_entity("op:e1", "entity:uno", "Uno"),
            create_entity("op:e2", "entity:dos", "Dos"),
            create_assertion("op:a1", "assertion:uno", "entity:uno", "entity:dos"),
        ],
        plan_id="plan:tanda4:ciclo",
    )


def _huella_conocimiento(probe: GraphProbe) -> str:
    """Huella del CONOCIMIENTO, sin la marca de idempotencia.

    POR QUE NO VALE `_huella` ENTERA PARA EL ULTIMO PASO
    ---------------------------------------------------
    Medido: entre el primer apply y el que sigue al rollback, lo unico que
    cambia en todo el grafo es el `claim_token` de cada `V3AppliedOperation`.
    Es un `uuid4` por reclamacion -- un nonce, no identidad durable: la clave
    durable de la marca es `(workspace, idempotency_key)`, y esa vuelve
    identica. Exigir el mismo `claim_token` seria exigir que dos reclamaciones
    distintas trajeran el mismo numero al azar, que es la misma clase de error
    que tratar el `elementId` como identidad.

    Asi que el ultimo paso se comprueba en dos mitades, y las DOS tienen que
    dar: el conocimiento vuelve EXACTO (esta huella) y las claves durables de
    las marcas vuelven IDENTICAS (`_claves_de_marcas`). Juntas dicen lo mismo
    que `_huella` sin exigir que un nonce se repita.
    """
    import hashlib

    nodos = probe.run(
        "MATCH (n) WHERE NOT n:V3AppliedOperation "
        "RETURN labels(n) AS l, properties(n) AS p"
    )
    rels = probe.run(
        "MATCH (a)-[r]->(b) RETURN type(r) AS t, properties(r) AS p, "
        "coalesce(a.entity_id, a.assertion_id) AS a, "
        "coalesce(b.entity_id, b.assertion_id) AS b"
    )
    assert nodos, "conjunto vacio: no habria nada que comparar"
    clave = lambda x: json.dumps(x, sort_keys=True, default=str)  # noqa: E731
    doc = {
        "nodos": sorted(
            [{"labels": sorted(n["l"]), "props": dict(n["p"])} for n in nodos],
            key=clave,
        ),
        "relaciones": sorted(
            [
                {"t": r["t"], "from": r["a"], "to": r["b"], "props": dict(r["p"])}
                for r in rels
            ],
            key=clave,
        ),
    }
    return hashlib.sha256(
        json.dumps(doc, sort_keys=True, default=str).encode()
    ).hexdigest()


def _claves_de_marcas(probe: GraphProbe) -> list[str]:
    """La identidad DURABLE de las marcas de idempotencia, ordenada."""
    filas = probe.run(
        "MATCH (n:V3AppliedOperation) RETURN n.idempotency_key AS k ORDER BY k"
    )
    return [f["k"] for f in filas]


def _censo(probe: GraphProbe) -> dict[str, int]:
    """Censo del grafo. Un solo MATCH por familia: nada de producto cartesiano.

    Dos `MATCH` sueltos en la misma consulta multiplican filas y, si una de las
    dos familias esta vacia, devuelven CERO -- que es exactamente el numero que
    un `S0` falso necesita para colarse.
    """
    nodos = probe.run("MATCH (n) RETURN count(n) AS c")[0]["c"]
    rels = probe.run("MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
    marcas = probe.run(
        "MATCH (n:V3AppliedOperation) RETURN count(n) AS c"
    )[0]["c"]
    return {"nodos": nodos, "relaciones": rels, "marcas": marcas}


def _state_hash_describe_el_nodo(probe: GraphProbe) -> int:
    """Cada `V3Entity` con `state_hash` lo tiene COHERENTE con sus props.

    Devuelve cuantas comprobo, para que quien lea el verde pueda ver que no
    comprobo ninguna (que seria un verde vacio).
    """
    filas = probe.run(
        "MATCH (n:V3Entity) WHERE n.state_hash IS NOT NULL "
        "RETURN properties(n) AS p"
    )
    for fila in filas:
        props = dict(fila["p"])
        assert props["state_hash"] == state_hash_value(props), (
            f"el state_hash guardado no describe el nodo {props.get('entity_id')!r}"
        )
    return len(filas)


def _documento_rollback(salida: Any, tmp_path: Path) -> Path:
    assert salida.rollback is not None, "el apply no produjo documento de rollback"
    destino = tmp_path / "rollback.json"
    destino.write_text(
        json.dumps(salida.rollback.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    return destino


def _mando_rollback(driver, doc: Path, capsys, *, execute: bool = True, env=None,
                    audit_log=None):
    """Ejecuta el mando de 4B tal cual, y devuelve `(rc, acta)`.

    LA AUDITORIA ES PRECONDICION REAL, NO DECORADO
    ----------------------------------------------
    `cli_rollback.authorize` bloquea con `GATE_AUDIT_UNAVAILABLE` cuando no hay
    un registro utilizable, y lo hace ANTES de abrir sesion contra Neo4j: sin
    rastro no se borra. Este arnes no declaraba `--audit-log`, asi que TODAS
    sus reversiones salian `NO_AUDIT` sin llegar nunca al grafo -- incluida la
    que debia clasificar residuos, que acertaba `rc != 0` por la razon
    equivocada (`assert 'NO_AUDIT' == 'INCOMPLETE'`).

    Lo que se aporta aqui es lo que el gate PIDE --una ruta escribible, bajo el
    `tmp_path` del propio documento--, no una rebaja de lo que el gate exige:
    `JsonlAuditSink.available()` sigue comprobando que el directorio sea
    creable y el fichero escribible, y sigue bloqueando si no lo es. El
    negativo explicito de esa precondicion vive, calibrado y con un driver
    prohibido que mide CERO escrituras, en
    `test_knowledge_v3_equipo4b_mando_rollback_seguridad.py`
    (`test_sin_audit_log_no_borra`, `test_audit_log_inservible_no_borra`).
    """
    destino_audit = audit_log or (doc.parent / "rollback-audit.jsonl")
    argv = [str(doc), "--workspace", WORKSPACE, "--operator", "tanda4",
            "--audit-log", str(destino_audit)]
    if execute:
        argv.append("--execute")
    entorno = {
        "S9K_ALLOW_REAL_INGEST": "1",
        "S9K_WRITER_WORKSPACE": WORKSPACE,
    } if env is None else env
    rc = cli_rollback.main(argv, driver_factory=lambda: driver, env=dict(entorno))
    return rc, json.loads(capsys.readouterr().out)


# --------------------------------------------------------------------------
# EL CICLO COMPLETO
# --------------------------------------------------------------------------
def test_ciclo_apply_repeat_rollback_apply_vuelve_a_S1(writer, probe, tmp_path, capsys):
    """`apply -> repeat -> rollback -> apply` y el grafo vuelve a `S1` EXACTO.

    Es la prueba que ninguna de las tres ramas podia dar por su cuenta.
    """
    plan = _plan_ciclo()

    # --- S0 de partida: se MIDE, no se presume ---------------------------
    assert _censo(probe) == {"nodos": 0, "relaciones": 0, "marcas": 0}

    # --- apply -> S1 ------------------------------------------------------
    primera = writer.write(plan, apply_request(plan))
    assert primera.outcome == OUTCOME_APPLIED, primera.codes
    assert primera.applied_operations == 3, primera.applied_operations
    s1 = _huella(probe)
    s1_conocimiento = _huella_conocimiento(probe)
    s1_marcas = _claves_de_marcas(probe)
    censo_s1 = _censo(probe)
    # El conjunto NO es vacio: si lo fuera, comparar huellas no probaria nada.
    assert censo_s1["nodos"] > 0 and censo_s1["marcas"] == 3, censo_s1
    assert len(s1_marcas) == 3 and all(s1_marcas), s1_marcas
    assert _state_hash_describe_el_nodo(probe) == 2

    # --- repeat apply -> sigue S1, y es no-op (4A) ------------------------
    segunda = writer.write(plan, apply_request(plan))
    assert segunda.outcome == OUTCOME_APPLIED, segunda.codes
    assert segunda.applied_operations == 0, "el segundo apply escribio"
    assert segunda.noop_operations == 3, segunda.noop_operations
    assert _huella(probe) == s1, "el segundo apply movio el grafo"

    # --- rollback por el MANDO (4B), con el rc de la tabla de 4C ----------
    doc = _documento_rollback(primera, tmp_path)
    rc, acta = _mando_rollback(probe.driver, doc, capsys)
    assert rc == exit_codes.EXIT_OK, acta
    assert acta["outcome"] == cli_rollback.OUTCOME_ROLLED_BACK, acta
    assert acta["code"] == "CLI_ROLLBACK_COMPLETE"
    # La frase humana sale del informe: no puede decir "revertido" sobre
    # residuos, Y NO PUEDE AFIRMAR MAS DE LO QUE `clean` SOSTIENE.
    #
    # EXPECTATIVA RETIRADA, NO GARANTIA PERDIDA
    # -----------------------------------------
    # Aqui se exigia la frase «No queda nada de esa operacion en el grafo.».
    # Esa frase derivaba de `bool(report.executed)` --«se intento borrar»-- y
    # se imprimia IDENTICA habiendo borrado cero, que es justo la clase de
    # afirmacion que esta tanda existe para impedir. Ademas seria FALSA en
    # cuanto algo de la operacion se conserve por estar COMPARTIDO, que es
    # legitimo y se mide en `retained` (`cli_rollback.describe`).
    #
    # Lo que la sustituye no afloja nada: se exige lo que `clean` SI sostiene
    # --que no queda RESIDUO-- y se exige contra el informe, no contra el
    # texto. La expectativa vieja la contradicen, medidas y por separado,
    # `equipo6b:636` y `equipo4b:408`.
    assert "No queda nada de esa operacion en el grafo" not in acta["human"], acta
    assert acta["report"]["clean"] is True, acta["report"]
    assert acta["report"]["residues"] == [], acta["report"]["residues"]
    assert "No queda ningun residuo de esta operacion en el grafo." in acta["human"], acta

    # --- S0: contado, y sabiendo que antes NO estaba vacio ----------------
    censo_s0 = _censo(probe)
    assert censo_s0 == {"nodos": 0, "relaciones": 0, "marcas": 0}, censo_s0
    assert censo_s1 != censo_s0, "el rollback no tenia nada que deshacer"

    # --- apply otra vez: DESDE CERO, no un no-op --------------------------
    # Esto es lo que 4B hace posible al retirar `V3AppliedOperation`. Sin eso,
    # este apply saldria `noop_operations == 3` sobre un grafo vacio: el mando
    # afirmando "ya aplicado" con el conocimiento borrado.
    tercera = writer.write(plan, apply_request(plan))
    assert tercera.outcome == OUTCOME_APPLIED, tercera.codes
    assert tercera.applied_operations == 3, (
        "tras el rollback el apply se declaro no-op: la marca de idempotencia "
        "sobrevivio al borrado del conocimiento que la sostenia"
    )
    assert tercera.noop_operations == 0, tercera.noop_operations
    # El conocimiento vuelve EXACTO...
    assert _huella_conocimiento(probe) == s1_conocimiento, (
        "el conocimiento reconstruido no es el mismo S1"
    )
    # ...y las marcas vuelven con la MISMA identidad durable. Lo unico que no
    # se repite es el `claim_token`, que es un nonce por reclamacion.
    assert _claves_de_marcas(probe) == s1_marcas
    assert _censo(probe) == censo_s1
    assert _state_hash_describe_el_nodo(probe) == 2


def test_el_state_hash_sigue_describiendo_el_nodo_despues_del_rollback(
    writer, probe, tmp_path, capsys
):
    """La costura que 4A senalo, medida en el grafo y no en el informe.

    4A aviso: si el rollback restaura o borra propiedades de un nodo que
    SOBREVIVE, tiene que recalcular el `state_hash`, o deja un hash que no
    describe el nodo -- peor que ninguno.

    Medido sobre el codigo integrado, el mando NO puede dejar ese hash rancio,
    y no porque recalcule: porque **ninguna accion de reversion escribe
    propiedades**. `DELETE_NODE`, `DELETE_RELATIONSHIP` y
    `FORGET_APPLIED_OPERATION` borran; `RESTORE_PROPERTIES` se declara no
    reconstruible y el desenlace deja de ser limpio (fail-closed). Un nodo o
    desaparece entero, o no lo toca nadie.

    Se comprueba con lo que sobrevive: se crean DOS entidades, se revierte solo
    la que creo el segundo plan, y la que queda tiene que conservar un
    `state_hash` que sigue describiendola.
    """
    base = make_plan(
        [create_entity("op:base", "entity:base", "Base")],
        plan_id="plan:tanda4:base",
    )
    assert writer.write(base, apply_request(base)).outcome == OUTCOME_APPLIED

    extra = make_plan(
        [create_entity("op:extra", "entity:extra", "Extra")],
        plan_id="plan:tanda4:extra",
    )
    salida_extra = writer.write(extra, apply_request(extra))
    assert salida_extra.outcome == OUTCOME_APPLIED, salida_extra.codes

    assert _state_hash_describe_el_nodo(probe) == 2

    doc = _documento_rollback(salida_extra, tmp_path)
    rc, acta = _mando_rollback(probe.driver, doc, capsys)
    assert rc == exit_codes.EXIT_OK, acta

    # La superviviente sigue ahi, y su hash SIGUE describiendola.
    quedan = probe.run(
        "MATCH (n:V3Entity) RETURN n.entity_id AS id ORDER BY id"
    )
    assert [f["id"] for f in quedan] == ["entity:base"], quedan
    assert _state_hash_describe_el_nodo(probe) == 1


def test_el_segundo_apply_en_PROCESO_NUEVO_deja_el_mismo_S1(writer, probe, tmp_path):
    """4A, pero sin poder achacarle el no-op a ninguna memoria del proceso.

    Si el `no-op` lo decide una estructura viva del writer y no el grafo, un
    proceso nuevo no lo reproduce. Aqui el segundo apply corre en un intérprete
    aparte, contra la MISMA base, y tiene que salir `noop` y dejar `S1` intacto.
    """
    uri = os.environ.get("S9K_4A_NEO4J_URI", "").strip()
    fichero = os.environ.get("S9K_4A_NEO4J_PASSWORD_FILE", "").strip()
    if not (uri and fichero):
        pytest.skip(
            "el proceso nuevo necesita una base alcanzable por URI: "
            "declara S9K_4A_NEO4J_URI y S9K_4A_NEO4J_PASSWORD_FILE"
        )

    plan = _plan_ciclo()
    primera = writer.write(plan, apply_request(plan))
    assert primera.outcome == OUTCOME_APPLIED, primera.codes
    s1 = _huella(probe)

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

    entorno = dict(os.environ)
    entorno.update({
        "S9K_T4_URI": uri,
        "S9K_T4_PASSWORD_FILE": fichero,
        "PYTHONPATH": str(APP_DIR),
    })
    proc = subprocess.run(
        [sys.executable, "-m", "tests.tanda4_apply_runner", str(plan_path)],
        cwd=str(APP_DIR), env=entorno, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    salida = json.loads(proc.stdout.strip().splitlines()[-1])

    assert salida["pid"] != os.getpid(), "no fue un proceso nuevo"
    assert salida["outcome"] == OUTCOME_APPLIED, salida
    assert salida["applied_operations"] == 0, salida
    assert salida["noop_operations"] == 3, salida
    assert _huella(probe) == s1, "el apply del proceso nuevo movio el grafo"


# --------------------------------------------------------------------------
# LA TABLA UNIFICADA (4C aplicada al mando de 4B)
# --------------------------------------------------------------------------
def test_el_mando_de_rollback_usa_la_tabla_de_4C_y_no_una_propia():
    """No basta con que los numeros coincidan: tienen que SER los de la tabla."""
    assert cli_rollback.RC_OK is exit_codes.EXIT_OK
    assert cli_rollback.RC_ERROR is exit_codes.EXIT_OUTCOME_NOT_OK
    assert cli_rollback.RC_INCOMPLETE is exit_codes.EXIT_OUTCOME_NOT_OK
    assert cli_rollback.RC_BLOCKED is exit_codes.EXIT_OUTCOME_NOT_OK
    # Los numeros que el mando traia de fabrica y que chocaban con la tabla.
    assert cli_rollback.RC_INCOMPLETE != 3, "3 es 'altas sin aprobar' en la tabla"
    assert cli_rollback.RC_BLOCKED != 4, "4 no significa nada en la tabla"


@pytest.mark.parametrize(
    "outcome",
    ["ROLLED_BACK", "DRY_RUN", "INCOMPLETE", "BLOCKED", "ERROR"],
)
def test_solo_un_desenlace_limpio_del_rollback_sale_con_cero(outcome):
    """La garantia de 4B, sobre la tabla de 4C. Tiene que seguir mordiendo."""
    limpio = outcome in ("ROLLED_BACK", "DRY_RUN")
    assert (exit_codes.exit_code_for_rollback(outcome) == 0) is limpio


def test_un_rollback_con_residuos_no_puede_salir_con_cero(writer, probe, tmp_path, capsys):
    """4C sobre 4B: si queda algo, ni el rc ni la frase pueden decir que no.

    Se fuerza un residuo de verdad -- se revierte un documento cuya instruccion
    no es reconstruible -- y se comprueba que el `rc` NO es 0 y que la frase
    humana lo dice. El desenlace y el texto salen del MISMO informe.
    """
    plan = _plan_ciclo()
    salida = writer.write(plan, apply_request(plan))
    assert salida.outcome == OUTCOME_APPLIED, salida.codes

    doc_dict = salida.rollback.to_dict()
    # Una instruccion que el traductor no sabe convertir: queda sin revertir.
    doc_dict["instructions"].append(
        {"operation_id": "op:imposible", "action": "RESTORE_PROPERTIES",
         "target_id": "entity:uno",
         "detail": {"workspace": WORKSPACE, "restore": {}, "changed": {},
                    "label": "V3Entity", "partida_id": None,
                    "idempotency_key": "clave:inexistente"}}
    )
    destino = tmp_path / "sucio.json"
    destino.write_text(json.dumps(doc_dict, ensure_ascii=False), encoding="utf-8")

    rc, acta = _mando_rollback(probe.driver, destino, capsys)
    assert rc != exit_codes.EXIT_OK, acta
    assert rc == exit_codes.EXIT_OUTCOME_NOT_OK, acta
    # NOMBRE SUPERSEDED, NO CAPACIDAD PERDIDA. `exit_codes.py:136-137` dice
    # literal que `UNEXPECTED_RESIDUE` SUSTITUYE a `INCOMPLETE` a secas, que se
    # conserva como alias historico. El desenlace que el mando publica hoy es
    # el nombre nuevo (`cli_rollback.py:724`); el `code` y el `rc` no se
    # mueven, y se siguen exigiendo aqui abajo igual que antes.
    assert acta["outcome"] == cli_rollback.OUTCOME_UNEXPECTED_RESIDUE
    assert acta["code"] == "CLI_ROLLBACK_INCOMPLETE"
    assert "NO es una reversion limpia" in acta["human"]
    assert acta["ok"] is False


def test_un_rollback_sin_autorizacion_sale_distinto_de_cero(
    writer, probe, tmp_path, capsys
):
    """BLOCKED -> rc != 0, la regla de 4C, en el mando de 4B."""
    plan = _plan_ciclo()
    salida = writer.write(plan, apply_request(plan))
    doc = _documento_rollback(salida, tmp_path)

    rc, acta = _mando_rollback(probe.driver, doc, capsys, env={})
    assert rc != exit_codes.EXIT_OK
    assert rc == exit_codes.EXIT_OUTCOME_NOT_OK
    assert acta["outcome"] == cli_rollback.OUTCOME_BLOCKED
    assert acta["code"] == "CLI_ROLLBACK_NOT_AUTHORIZED"
    # Y no toco nada: el grafo sigue en S1.
    assert _censo(probe)["marcas"] == 3
