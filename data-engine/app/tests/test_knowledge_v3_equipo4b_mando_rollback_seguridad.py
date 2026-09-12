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

    # `--operator` y `--audit-log` van AQUI porque desde el bloque 5B son
    # condiciones para llegar siquiera a resolver la conexion: sin ellas el
    # mando bloquea antes, y esta prueba dejaria de medir lo suyo --el fichero
    # de secreto-- sin decirlo. Pasarlas es lo que mantiene la prueba honesta.
    rc, salida = _correr(
        [str(doc), "--workspace", WS, "--execute",
         "--operator", "pjc", "--audit-log", str(tmp_path / "audit.jsonl"),
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
    # Mismo motivo que arriba: operador y auditoria son ahora previos a la
    # conexion, asi que se declaran para que lo que falle sea la conexion.
    rc, salida = _correr(
        [str(doc), "--workspace", WS, "--execute",
         "--operator", "pjc", "--audit-log", str(tmp_path / "audit.jsonl")],
        CONEXION, capsys,
    )
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
    texto_limpio = cli_rollback.describe(cli_rollback.OUTCOME_ROLLED_BACK, limpio)
    # EQUIPO 6B: la frase ya no dice «no queda NADA de esa operacion». Eso
    # seria falso cuando algo suyo se conserva por estar COMPARTIDO, que es
    # legitimo (`retained`). Lo unico que `clean` sostiene --y lo unico que se
    # afirma-- es que no queda RESIDUO.
    assert texto_limpio.endswith(
        "No queda ningun residuo de esta operacion en el grafo."
    )
    assert "NO es una reversion limpia" not in texto_limpio
    assert limpio.clean


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


# --- EQUIPO 5B: el borrado anonimo y sin traza ------------------------------
# DEFECTO MEDIDO por un supervisor independiente: con el entorno y el workspace
# correctos pero SIN `--operator`, la reversion se ejecuto de verdad --1
# relacion, 1 marca y 12 nodos de procedencia borrados-- y el propio informe
# decia `"operator": null`. El mando ni siquiera aceptaba `--audit-log`.
#
# Lo que se fija aqui NO es un gate nuevo: son las condiciones que el gate del
# writer YA exige para escribir (`GATE_OPERATOR_MISSING`,
# `GATE_OPERATOR_INVALID`, `GATE_AUDIT_UNAVAILABLE`), aplicadas a la operacion
# que BORRA. Y se comprueba el EFECTO --que no se llega a abrir sesion-- no
# solo el codigo impreso: un driver que reviente si alguien lo toca.


class _DriverProhibido:
    """Si el mando llega a usar el driver, la prueba REVIENTA.

    Comprobar solo el `code` impreso dejaria pasar un mando que bloquea
    DESPUES de haber borrado. La garantia es «no borra», y para observarla hay
    que observar que no se toca el grafo, no que se imprime la palabra correcta.
    """

    def session(self, *a, **k):  # pragma: no cover - debe no llamarse nunca
        raise AssertionError(
            "el mando abrio sesion contra el grafo pese a no estar autorizado: "
            "eso es exactamente el borrado anonimo que este bloque cierra"
        )

    def close(self):  # pragma: no cover
        pass


def test_sin_operator_no_borra(tmp_path, capsys):
    doc = _documento(tmp_path)
    rc, salida = _correr(
        [str(doc), "--workspace", WS, "--execute",
         "--audit-log", str(tmp_path / "a.jsonl"),
         "--neo4j-uri", "bolt://x", "--neo4j-user", "u",
         "--neo4j-password-file", "-"],
        CONEXION, capsys,
    )
    assert rc == cli_rollback.RC_BLOCKED
    assert salida["outcome"] == cli_rollback.OUTCOME_NO_OPERATOR
    assert salida["code"] == "GATE_OPERATOR_MISSING"
    assert salida["ok"] is False
    # La frase sale de los HECHOS, y los hechos dicen que no se borro nada.
    assert salida["hechos"]["deleted_anything"] is False
    assert salida["hechos"]["clean"] is False
    assert "no se borro nada" in salida["human"]


def test_sin_operator_no_llega_a_tocar_el_grafo(tmp_path, capsys):
    """El EFECTO, no la frase: ni se abre la sesion."""
    doc = _documento(tmp_path)
    rc = cli_rollback.main(
        [str(doc), "--workspace", WS, "--execute",
         "--audit-log", str(tmp_path / "a.jsonl")],
        driver_factory=lambda: _DriverProhibido(),
        env=dict(CONEXION),
    )
    capsys.readouterr()
    assert rc == cli_rollback.RC_BLOCKED


def test_operator_con_forma_no_admisible_no_borra(tmp_path, capsys):
    doc = _documento(tmp_path)
    rc = cli_rollback.main(
        [str(doc), "--workspace", WS, "--execute", "--operator", "pj c/../etc",
         "--audit-log", str(tmp_path / "a.jsonl")],
        driver_factory=lambda: _DriverProhibido(),
        env=dict(CONEXION),
    )
    salida = json.loads(capsys.readouterr().out)
    assert rc == cli_rollback.RC_BLOCKED
    assert salida["code"] == "GATE_OPERATOR_INVALID"


def test_sin_audit_log_no_borra(tmp_path, capsys):
    doc = _documento(tmp_path)
    rc = cli_rollback.main(
        [str(doc), "--workspace", WS, "--execute", "--operator", "pjc"],
        driver_factory=lambda: _DriverProhibido(),
        env=dict(CONEXION),
    )
    salida = json.loads(capsys.readouterr().out)
    assert rc == cli_rollback.RC_BLOCKED
    assert salida["code"] == "GATE_AUDIT_UNAVAILABLE"


def test_audit_log_inservible_no_borra(tmp_path, capsys):
    """No basta con que se declare: tiene que ser ESCRIBIBLE. Se mide."""
    jaula = tmp_path / "solo-lectura"
    jaula.mkdir()
    jaula.chmod(0o500)
    try:
        rc = cli_rollback.main(
            [str(_documento(tmp_path)), "--workspace", WS, "--execute",
             "--operator", "pjc", "--audit-log", str(jaula / "a.jsonl")],
            driver_factory=lambda: _DriverProhibido(),
            env=dict(CONEXION),
        )
        salida = json.loads(capsys.readouterr().out)
    finally:
        jaula.chmod(0o700)
    assert rc == cli_rollback.RC_BLOCKED
    assert salida["code"] == "GATE_AUDIT_UNAVAILABLE"


def test_la_auditoria_se_escribe_de_verdad(tmp_path, capsys):
    """Y se ENSENA: el intento va ANTES de tocar nada, el desenlace despues."""
    registro = tmp_path / "audit.jsonl"

    class _Sesion:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def run(self, cypher, params=None):
            return []

    class _Driver:
        def session(self):
            return _Sesion()

        def close(self):
            pass

    rc = cli_rollback.main(
        [str(_documento(tmp_path)), "--workspace", WS, "--execute",
         "--operator", "pjc", "--audit-log", str(registro)],
        driver_factory=lambda: _Driver(),
        env=dict(CONEXION),
    )
    salida = json.loads(capsys.readouterr().out)
    assert rc == cli_rollback.RC_OK
    assert salida["operator"] == "pjc"
    assert salida["audit_log"] == str(registro)

    lineas = [json.loads(l) for l in registro.read_text(encoding="utf-8").splitlines() if l]
    assert lineas, "el registro esta vacio: la auditoria no se escribio"
    assert [l["outcome"] for l in lineas] == ["ATTEMPTED", "ROLLED_BACK"]
    assert all(l["mode"] == "ROLLBACK" for l in lineas)
    assert all(l["operator_id"] == "pjc" for l in lineas)


def test_el_bloqueo_tambien_deja_rastro(tmp_path, capsys):
    """Un log que solo guarda los exitos no es auditoria."""
    registro = tmp_path / "audit.jsonl"
    cli_rollback.main(
        [str(_documento(tmp_path)), "--workspace", WS, "--execute",
         "--operator", "pj c/mal", "--audit-log", str(registro)],
        driver_factory=lambda: _DriverProhibido(),
        env=dict(CONEXION),
    )
    capsys.readouterr()
    lineas = [json.loads(l) for l in registro.read_text(encoding="utf-8").splitlines() if l]
    assert lineas, "un bloqueo sin rastro es un borrado intentado sin traza"
    assert lineas[0]["outcome"] == cli_rollback.OUTCOME_NO_OPERATOR
    assert lineas[0]["detail"]["code"] == "GATE_OPERATOR_INVALID"


def test_la_simulacion_sigue_sin_exigir_operador(tmp_path, capsys):
    """DRY_RUN no borra, luego no se le piden las garantias del borrado.

    Exigirselas seria endurecer por endurecer: la simulacion no toca el grafo,
    no abre conexion y no lee el secreto. La garantia se pide donde esta el
    riesgo.
    """
    rc, salida = _correr([str(_documento(tmp_path)), "--workspace", WS], {}, capsys)
    assert rc == cli_rollback.RC_OK
    assert salida["outcome"] == cli_rollback.OUTCOME_DRY_RUN


def test_los_desenlaces_nuevos_salen_no_cero_por_la_tabla_unica():
    """Los tres nombres acordados con el 5C, y su `rc` por LISTA BLANCA.

    No se toca `exit_codes`: su `ROLLBACK_OUTCOMES_OK` es lista blanca y falla
    CERRADO, asi que un desenlace nuevo sale `!= 0` por omision. Se OBSERVA en
    vez de presuponerlo -- que es justo lo que fallo en la tanda anterior.
    """
    from knowledge_v3.writer import exit_codes

    for desenlace in (cli_rollback.OUTCOME_NO_OPERATOR,
                      cli_rollback.OUTCOME_NO_AUDIT,
                      cli_rollback.OUTCOME_UNEXPECTED_RESIDUE):
        assert desenlace not in exit_codes.ROLLBACK_OUTCOMES_OK
        assert exit_codes.exit_code_for_rollback(desenlace) != 0


def test_la_frase_nunca_dice_limpia_sobre_hechos_que_no_lo_son():
    """DEFECTO 4, cerrado por construccion: prosa derivada de los hechos.

    Se recorren desenlaces y se comprueba la implicacion en los DOS sentidos:
    «limpia» solo aparece si `clean`, y `clean` obliga a que no aparezca «NO
    es una reversion limpia». Un aserto en un solo sentido dejaria pasar la
    mitad de la contradiccion medida.
    """
    from knowledge_v3.writer.rollback_provenance import RollbackReport

    sucio = RollbackReport(
        executed=[{"operation_id": "op-1"}],
        residues=[{"operation_id": "op-1", "what": "algo", "detail": {}}],
        unrecoverable=["ROLLBACK_RESIDUE op-1: algo"],
    )
    limpio = RollbackReport(executed=[{"operation_id": "op-1"}])

    for outcome, informe in (
        (cli_rollback.OUTCOME_UNEXPECTED_RESIDUE, sucio),
        (cli_rollback.OUTCOME_ROLLED_BACK, limpio),
    ):
        hechos = cli_rollback.rollback_facts(outcome, informe)
        frase = cli_rollback.describe(outcome, informe)
        assert hechos["clean"] is informe.clean
        if hechos["clean"]:
            assert "NO es una reversion limpia" not in frase
        else:
            assert "No queda nada de esa operacion" not in frase
