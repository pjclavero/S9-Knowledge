# -*- coding: utf-8 -*-
"""Si el usuario pidio escritura, el `rc` distingue QUE ocurrio de verdad.

DEFECTO QUE CIERRA ESTA SUITE
-----------------------------
`pipeline.ingest_cli` salia **0 sobre un `--apply` que no habia escrito nada**
cuando la cadena paraba antes del writer. El acta era honesta -- decia
`SIN_PLAN` y `SIN_RESULTADO_DE_ESCRITURA` -- pero el `rc` decia exito y el
grafo quedaba intacto. La causa estaba escrita en el codigo::

    "Sin bloque `write` no hubo writer ... eso es un exito (0)"

Correcto en dry-run, FALSO bajo `--apply`. Quedaba una clase entera de APPLY
fallidos indistinguible de un `APPLIED` para un runner desatendido.

LA TRAMPA QUE ESTA SUITE PROTEGE
--------------------------------
"0 escrituras" NO es siempre fallo: un `--apply` repetido sobre conocimiento
ya escrito da 0 operaciones y es un EXITO (no-op idempotente). Una regla
`operaciones == 0 -> error` cerraria el defecto Y romperia la idempotencia.
`test_el_noop_idempotente_sigue_saliendo_cero` es la prueba que se pondria
roja si alguien cae en esa tentacion.

COMO SE MIDE
------------
El `rc` se captura del valor que devuelve `ingest_cli.main` / el decisor real
`_rc_del_desenlace`; no se infiere de una tuberia, donde `$?` seria del ultimo
comando. Las aserciones son sobre CODIGOS estables (`code`, `hechos`), nunca
sobre el texto de una frase.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.pipeline import ingest_cli  # noqa: E402
from knowledge_v3.writer import exit_codes  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
EJEMPLOS = REPO / "examples" / "ingesta-v3"
PERFIL = EJEMPLOS / "perfil-operador.json"
CATALOGO = EJEMPLOS / "catalogo-workspace.json"
FUENTE = EJEMPLOS / "nota-cofradia-de-ambar.md"
AHORA = "2026-09-05T10:00:00Z"


# --------------------------------------------------------------------------
# Utillaje: informes con la FORMA real que publica el producto.
# --------------------------------------------------------------------------
def _informe(writer_mode: str, write: dict | None) -> dict:
    """Informe minimo con los dos unicos campos de los que sale el `rc`.

    `run.writer_mode` es el modo PEDIDO (lo pone `config.py` desde `apply`), y
    `write` es el bloque que publica `run_ingest` solo si el writer corrio.
    """
    doc: dict = {"run": {"writer_mode": writer_mode}}
    if write is not None:
        doc["write"] = write
    return doc


def _write(outcome, *, aplicadas=0, noop=0, codes=(), mode="APPLY") -> dict:
    return {
        "outcome": outcome,
        "mode": mode,
        "codes": list(codes),
        "applied_operations": aplicadas,
        "noop_operations": noop,
        "created_ids": [],
    }


class _SesionGrafoVacio:
    """Grafo con 0 nodos. No escribe: si alguien lo intenta, salta."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, *a, **k):
        return []

    def execute_read(self, *a, **k):
        return []

    def begin_transaction(self):  # pragma: no cover - debe no llamarse
        raise AssertionError("no habia plan que escribir y se abrio transaccion")


class _DriverGrafoVacio:
    def session(self, *a, **k):
        return _SesionGrafoVacio()

    def close(self):
        pass


@pytest.fixture()
def decisiones(tmp_path: Path) -> Path:
    """Documento de decisiones REVISADO y vacio: `--apply` lo exige."""
    destino = tmp_path / "decisiones.json"
    destino.write_text(
        json.dumps(
            {
                "contract": "entity-decisions/carril-b-v1",
                "workspace": "rpg-demo",
                "partida_id": None,
                "source_path": "x",
                "generated_at": AHORA,
                "graph_entity_ids": [],
                "decisions": [],
                "carencias": [],
                "totals": {},
            }
        ),
        encoding="utf-8",
    )
    return destino


# --------------------------------------------------------------------------
# 1. `--apply` que NO llega al writer. EL DEFECTO. Extremo a extremo.
# --------------------------------------------------------------------------
def test_un_apply_que_no_llega_al_writer_no_puede_salir_cero(
    tmp_path, monkeypatch, decisiones
):
    """Reproduccion exacta del defecto medido por el supervisor.

    `--apply --operador ... --desde-grafo` sobre un grafo vacio y una fuente
    de la que el motor no saca ni un claim: la cadena para en `engine`, el
    writer NUNCA corre, no hay bloque `write`. Antes: `rc = 0`.

    Se prueba por EFECTO OBSERVADO -- el `rc` que devuelve `main` y el
    informe que quedo en disco --, no leyendo el codigo fuente.
    """
    fuente = tmp_path / "sin-claims.txt"
    fuente.write_text("111 222 333 444.\n", encoding="utf-8")
    salida = tmp_path / "out"
    monkeypatch.setattr(
        ingest_cli, "_driver_factory", lambda args: (lambda: _DriverGrafoVacio())
    )

    rc = ingest_cli.main([
        str(fuente), "--perfil", str(PERFIL), "--apply",
        "--operador", "op-5c", "--decisiones", str(decisiones),
        "--desde-grafo", "--out-dir", str(salida), "--ahora", AHORA,
    ])

    informe = json.loads((salida / "informe.json").read_text(encoding="utf-8"))
    # La premisa del escenario, OBSERVADA y no supuesta: el writer no corrio.
    assert "write" not in informe, "este escenario exige que el writer no corra"
    assert informe["run"]["writer_mode"] == "APPLY"

    assert rc != exit_codes.EXIT_OK, (
        "un --apply que ni intento escribir salio 0: un runner desatendido lo "
        "lee como una escritura correcta"
    )
    assert rc == exit_codes.EXIT_OUTCOME_NOT_OK

    # Y el acta lo NOMBRA. Codigo estable, no subcadena de la frase.
    codigos = [c["code"] for c in informe["carencias"]]
    assert "APPLY_SIN_CAMINO_AL_WRITER" in codigos
    falta = next(c for c in informe["carencias"]
                 if c["code"] == "APPLY_SIN_CAMINO_AL_WRITER")
    assert falta["hechos"]["outcome"] == exit_codes.RUN_NO_WRITE_PATH
    assert falta["hechos"]["reached_writer"] is False
    assert falta["hechos"]["wrote_anything"] is False


# --------------------------------------------------------------------------
# 2-5. Los cinco desenlaces contra el DECISOR REAL del `rc`.
# --------------------------------------------------------------------------
# `main` devuelve literalmente `_rc_del_desenlace(report)`: es el punto donde
# se decide el numero, y se le dan informes con la forma que el producto
# publica de verdad.
def test_un_apply_que_escribe_sale_cero():
    rc = ingest_cli._rc_del_desenlace(
        _informe("APPLY", _write("APPLIED", aplicadas=7))
    )
    assert rc == exit_codes.EXIT_OK


def test_el_noop_idempotente_sigue_saliendo_cero():
    """LA TRAMPA. Repetir un apply sobre lo ya escrito es un EXITO.

    Esta prueba se pone ROJA si alguien cierra el defecto con la regla facil
    `operaciones == 0 -> error`. La idempotencia que otro equipo demostro
    byte a byte depende de que siga verde.
    """
    informe = _informe("APPLY", _write("APPLIED", aplicadas=0, noop=9))
    assert ingest_cli._rc_del_desenlace(informe) == exit_codes.EXIT_OK

    desenlace = exit_codes.resolve_run_outcome("APPLY", informe["write"])
    assert desenlace == exit_codes.RUN_NOOP_IDEMPOTENT
    # La frase tambien lo distingue de un APPLY que escribio.
    falta = exit_codes.describe_outcome(desenlace, mode="APPLY", driver_opened=True)
    assert falta["code"] == "SIN_CAMBIOS_IDEMPOTENTE"
    assert falta["hechos"]["wrote_anything"] is False
    assert falta["hechos"]["reached_writer"] is True


def test_el_dry_run_pedido_y_cumplido_sale_cero():
    # Con writer: SIMULATED. Sin writer: la cadena no llego, y en dry-run eso
    # es lo esperado -- NO se convierte en fallo.
    assert ingest_cli._rc_del_desenlace(
        _informe("DRY_RUN", _write("SIMULATED", mode="DRY_RUN"))
    ) == exit_codes.EXIT_OK
    assert ingest_cli._rc_del_desenlace(
        _informe("DRY_RUN", None)
    ) == exit_codes.EXIT_OK


def test_una_escritura_bloqueada_no_sale_cero_y_no_se_confunde_con_error_de_uso():
    informe = _informe("APPLY", _write("BLOCKED", codes=["GATE_NOT_AUTHORIZED"]))
    rc = ingest_cli._rc_del_desenlace(informe)
    assert rc != exit_codes.EXIT_OK
    assert rc == exit_codes.EXIT_OUTCOME_NOT_OK
    # DISTINGUIBLE del 2 de argparse: son numeros distintos, y el 2 se
    # comprueba de verdad ejecutando el mando mal invocado, mas abajo.
    assert rc != exit_codes.EXIT_USAGE


def test_el_error_de_uso_conserva_su_propio_codigo(capsys):
    """`--apply` sin `--operador`: argparse sale 2, distinto del 1 de BLOCKED."""
    with pytest.raises(SystemExit) as salida:
        ingest_cli.main([str(FUENTE), "--perfil", str(PERFIL), "--apply"])
    assert salida.value.code == exit_codes.EXIT_USAGE
    assert exit_codes.EXIT_USAGE != exit_codes.EXIT_OUTCOME_NOT_OK


def test_un_simulated_cuando_se_pidio_apply_es_una_mentira_y_no_sale_cero():
    """"Me pediste escribir y solo simule" no es un exito."""
    assert ingest_cli._rc_del_desenlace(
        _informe("APPLY", _write("SIMULATED", mode="DRY_RUN"))
    ) != exit_codes.EXIT_OK


# --------------------------------------------------------------------------
# 6. Ningun mensaje afirma algo que no ocurrio.
# --------------------------------------------------------------------------
CENSO = [
    # (modo pedido, bloque write, ¿escribio?, ¿llego al writer?, rc esperado)
    ("APPLY", _write("APPLIED", aplicadas=3), True, True, 0),
    ("APPLY", _write("APPLIED", aplicadas=0, noop=4), False, True, 0),
    ("APPLY", _write("BLOCKED", codes=["X"]), False, True, 1),
    ("APPLY", _write("REJECTED", codes=["X"]), False, True, 1),
    ("APPLY", None, False, False, 1),
    ("DRY_RUN", _write("SIMULATED", mode="DRY_RUN"), False, True, 0),
    ("DRY_RUN", None, False, False, 0),
]


@pytest.mark.parametrize("modo,bloque,escribio,llego,rc_esperado", CENSO)
def test_la_frase_del_acta_no_afirma_nada_que_no_ocurriera(
    modo, bloque, escribio, llego, rc_esperado
):
    """Texto y `rc` salen del MISMO desenlace, y los hechos son observados.

    Se comparan CAMPOS estructurados, no subcadenas: contar texto da falsos
    negativos en cuanto alguien reescribe una palabra.
    """
    informe = _informe(modo, bloque)
    desenlace = exit_codes.resolve_run_outcome(modo, bloque)
    falta = exit_codes.describe_outcome(
        desenlace,
        mode=modo,
        applied_operations=(bloque or {}).get("applied_operations", 0),
        codes=(bloque or {}).get("codes", ()),
        driver_opened=True,
    )
    hechos = falta["hechos"]

    assert hechos["wrote_anything"] is escribio, (
        f"{desenlace}: el acta afirma wrote_anything={hechos['wrote_anything']} "
        f"y lo cierto es {escribio}"
    )
    assert hechos["reached_writer"] is llego
    assert hechos["was_dry_run"] is (desenlace == "SIMULATED")
    # El `rc` que un runner leera sale del MISMO desenlace que esa frase.
    assert ingest_cli._rc_del_desenlace(informe) == rc_esperado


def test_ningun_desenlace_desconocido_se_cuela_como_exito():
    """HUECO PREVISTO para 5A y 5B: la tabla falla CERRADA.

    Un desenlace que otro equipo añada -- `CONSTRAINTS_MISSING` (5A),
    `NO_OPERATOR` / `NO_AUDIT` / `UNEXPECTED_RESIDUE` (5B) -- sale distinto de
    0 SIN que nadie tenga que tocar este modulo. Se comprueba con nombres que
    hoy no existen a proposito.
    """
    for inventado in ("CONSTRAINTS_MISSING", "NO_OPERATOR", "NO_AUDIT",
                      "UNEXPECTED_RESIDUE", "ALGO_QUE_NADIE_HA_ESCRITO_AUN"):
        assert inventado not in exit_codes.RUN_OUTCOMES_OK
        assert exit_codes.exit_code_for_run(inventado) != exit_codes.EXIT_OK
        assert ingest_cli._rc_del_desenlace(
            _informe("APPLY", _write(inventado))
        ) != exit_codes.EXIT_OK


# --------------------------------------------------------------------------
# 7. CONTROL NEGATIVO. Una comprobacion que no puede fallar no es comprobacion.
# --------------------------------------------------------------------------
def test_control_negativo_si_un_desenlace_miente_la_comprobacion_se_pone_roja(
    monkeypatch,
):
    """Se hace mentir a `resolve_run_outcome` y se exige que el censo FALLE.

    La mentira inyectada es exactamente el defecto original: llamar `APPLIED`
    a un `--apply` que no llego al writer. Si tras esta inyeccion el censo
    siguiera pasando, el censo no estaria comprobando nada.
    """
    autentico = exit_codes.resolve_run_outcome

    def _mentiroso(requested_mode, write_block):
        if not write_block and requested_mode == "APPLY":
            return "APPLIED"  # LA MENTIRA: no corrio el writer y dice que si
        return autentico(requested_mode, write_block)

    monkeypatch.setattr(exit_codes, "resolve_run_outcome", _mentiroso)

    # El caso del censo que cubre "APPLY sin bloque write".
    modo, bloque, escribio, llego, rc_esperado = ("APPLY", None, False, False, 1)

    with pytest.raises(AssertionError):
        test_la_frase_del_acta_no_afirma_nada_que_no_ocurriera(
            modo, bloque, escribio, llego, rc_esperado
        )
