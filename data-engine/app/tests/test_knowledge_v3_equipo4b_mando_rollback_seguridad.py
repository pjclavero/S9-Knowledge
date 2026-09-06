# -*- coding: utf-8 -*-
"""EQUIPO 4B -- las reglas de seguridad del mando de reversion, sin Neo4j.

El mando que EJECUTA un rollback borra. No puede pedir menos garantias que el
que escribe, asi que se le exigen las MISMAS y aqui se observan una a una:

* el secreto no viaja por `argv` (no existe la opcion, y la ruta declarada
  tiene que ser 0600);
* sin conexion declarada falla CERRADO, no se degrada a simulacion;
* autorizacion de operador declarada (las dos del APPLY);
* el `workspace` del documento tiene que ser el autorizado.

Ninguna necesita servidor: se miden sobre el propio mando.
"""
from __future__ import annotations

import json

import pytest

from knowledge_v3.writer import cli_rollback
from knowledge_v3.writer.rollback import RollbackDocument, RollbackInstruction

WS = "ws-4b"
CONEXION = {"S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": WS}


def _documento(tmp_path, *, workspace=WS, instrucciones=None):
    doc = RollbackDocument(workspace=workspace, snapshot_id="snap", plan_hash="h")
    doc.instructions = list(instrucciones or [
        RollbackInstruction(
            operation_id="op-1", action="DELETE_NODE", target_id="entity:x",
            detail={"workspace": workspace, "label": "V3Entity",
                    "partida_id": None, "idempotency_key": "k1",
                    "created_id": "entity:x"},
        )
    ])
    destino = tmp_path / "rb.json"
    destino.write_text(json.dumps(doc.to_dict(), ensure_ascii=False), encoding="utf-8")
    return destino


def _correr(argv, env, capsys):
    rc = cli_rollback.main(argv, env=dict(env))
    return rc, json.loads(capsys.readouterr().out)


def test_ninguna_opcion_acepta_la_contrasena_por_argv():
    """No es que no se use: es que NO EXISTE la opcion."""
    opciones = {
        s
        for accion in cli_rollback.build_parser()._actions
        for s in accion.option_strings
    }
    prohibidas = [
        o for o in opciones
        if "password" in o and not o.endswith("-file")
    ]
    assert prohibidas == [], prohibidas
    assert "--neo4j-password-file" in opciones


def test_fichero_de_secreto_legible_por_otros_se_rechaza(tmp_path, capsys):
    secreto = tmp_path / "pass"
    secreto.write_text("loquesea\n", encoding="utf-8")
    secreto.chmod(0o644)
    doc = _documento(tmp_path)

    rc, salida = _correr(
        [str(doc), "--workspace", WS, "--execute",
         "--neo4j-uri", "bolt://127.0.0.1:1", "--neo4j-user", "neo4j",
         "--neo4j-password-file", str(secreto)],
        CONEXION, capsys,
    )
    assert rc != 0
    assert salida["outcome"] == "ERROR"
    # Se reconoce por CODIGO, no por la redaccion del mensaje.
    assert salida["code"] == "CLI_SECRET_FILE_UNUSABLE"
    assert "loquesea" not in json.dumps(salida)


def test_sin_conexion_declarada_falla_cerrado_y_no_simula(tmp_path, capsys):
    doc = _documento(tmp_path)
    rc, salida = _correr([str(doc), "--workspace", WS, "--execute"], CONEXION, capsys)
    assert rc != 0
    assert salida["code"] == "CLI_DRIVER_CONFIG_MISSING"
    assert salida["outcome"] == "ERROR"
    # NO se degrada a DRY_RUN: quien pidio borrar no recibe un "ok".
    assert salida["outcome"] != cli_rollback.OUTCOME_DRY_RUN


def test_sin_declaracion_de_operador_queda_bloqueado(tmp_path, capsys):
    doc = _documento(tmp_path)
    rc, salida = _correr(
        [str(doc), "--workspace", WS, "--execute"],
        {"S9K_WRITER_WORKSPACE": WS}, capsys,
    )
    assert rc == cli_rollback.RC_BLOCKED
    assert salida["code"] == "CLI_ROLLBACK_NOT_AUTHORIZED"


def test_workspace_declarado_que_no_es_el_del_documento(tmp_path, capsys):
    doc = _documento(tmp_path, workspace="otro")
    rc, salida = _correr([str(doc), "--workspace", WS, "--execute"], CONEXION, capsys)
    assert rc == cli_rollback.RC_BLOCKED
    assert salida["code"] == "CLI_ROLLBACK_WORKSPACE_MISMATCH"


def test_la_simulacion_no_resuelve_conexion_ni_lee_secreto(tmp_path, capsys):
    doc = _documento(tmp_path)
    rc, salida = _correr([str(doc), "--workspace", WS], {}, capsys)
    assert rc == 0
    assert salida["outcome"] == "DRY_RUN"
    assert len(salida["would_execute"]) == 1


def test_el_desenlace_humano_no_puede_contradecir_al_informe():
    """La linea humana se DERIVA del informe; no es una frase independiente."""
    from knowledge_v3.writer.rollback_provenance import RollbackReport

    sucio = RollbackReport(residues=[{"operation_id": "op", "what": "x", "detail": {}}])
    texto = cli_rollback.describe(cli_rollback.OUTCOME_INCOMPLETE, sucio)
    assert "NO es una reversion limpia" in texto
    assert not sucio.clean

    limpio = RollbackReport()
    assert cli_rollback.describe(cli_rollback.OUTCOME_ROLLED_BACK, limpio).endswith(
        "No queda nada de esa operacion en el grafo."
    )


def test_documento_ilegible_o_incompleto_no_ejecuta_nada(tmp_path, capsys):
    roto = tmp_path / "roto.json"
    roto.write_text('{"workspace": "ws-4b"}', encoding="utf-8")
    rc, salida = _correr([str(roto), "--workspace", WS, "--execute"], CONEXION, capsys)
    assert rc == cli_rollback.RC_ERROR
    assert salida["outcome"] == "ERROR"


def test_acepta_el_informe_de_ingesta_con_el_documento_anidado(tmp_path, capsys):
    """Es la forma que el operador tiene en la mano (`informe.json`)."""
    doc = RollbackDocument(workspace=WS, snapshot_id="s", plan_hash="h")
    doc.instructions = [
        RollbackInstruction("op-1", "FORGET_APPLIED_OPERATION", "k1",
                            {"workspace": WS, "idempotency_key": "k1"})
    ]
    informe = tmp_path / "informe.json"
    informe.write_text(
        json.dumps({"write": {}, "rollback": doc.to_dict()}), encoding="utf-8"
    )
    rc, salida = _correr([str(informe), "--workspace", WS], {}, capsys)
    assert rc == 0
    assert salida["outcome"] == "DRY_RUN"
    assert salida["would_execute"][0]["action"] == "FORGET_APPLIED_OPERATION"


@pytest.mark.parametrize(
    "outcome,rc",
    [
        (cli_rollback.OUTCOME_DRY_RUN, cli_rollback.RC_OK),
        (cli_rollback.OUTCOME_ROLLED_BACK, cli_rollback.RC_OK),
        (cli_rollback.OUTCOME_INCOMPLETE, cli_rollback.RC_INCOMPLETE),
        (cli_rollback.OUTCOME_BLOCKED, cli_rollback.RC_BLOCKED),
        (cli_rollback.OUTCOME_ERROR, cli_rollback.RC_ERROR),
    ],
)
def test_la_tabla_de_codigos_de_salida_es_la_acordada(outcome, rc):
    """Semantica de 4C: solo APPLIED/DRY_RUN valido salen con 0."""
    limpio = outcome in (cli_rollback.OUTCOME_DRY_RUN, cli_rollback.OUTCOME_ROLLED_BACK)
    assert (rc == 0) is limpio
