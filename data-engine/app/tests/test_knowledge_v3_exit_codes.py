# -*- coding: utf-8 -*-
"""Los `rc` son API: esto lo prueba, y prueba que la prueba puede ponerse roja.

TRES COSAS SE COMPRUEBAN AQUI
-----------------------------
1. La TABLA de `writer.exit_codes` (unidad).
2. Que `pipeline.ingest_cli` la usa: un desenlace no correcto sale != 0 y es
   DISTINGUIBLE del error de argumentos, sin leer el texto de ningun mensaje.
3. Que el TEXTO del acta deriva del desenlace: se le da un desenlace y se mira
   que la frase no afirma nada que ese desenlace no sostenga.

CONTROL NEGATIVO
----------------
`test_control_negativo_*` inyectan a proposito un mando que MIENTE (sale 0
sobre un BLOCKED) y una frase que MIENTE (dice "no se abrio ningun driver" con
driver abierto), y comprueban que la comprobacion correspondiente FALLA. Una
comprobacion que no puede ponerse roja no es una comprobacion; este proyecto ya
se ha llevado dos sustos con verdes por vacio.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from knowledge_v3.pipeline import ingest_cli
from knowledge_v3.writer import exit_codes


# --------------------------------------------------------------------------
# 1. La tabla, como unidad
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "outcome, codes, mode, esperado",
    [
        ("APPLIED", (), "APPLY", exit_codes.EXIT_OK),
        ("SIMULATED", (), "DRY_RUN", exit_codes.EXIT_OK),
        # BLOCKED es el defecto que dispara todo esto: el gate aguanto, 0
        # operaciones, grafo intacto -- y el mando salia 0.
        ("BLOCKED", ("GATE_ENV_NOT_ALLOWED",), "APPLY", exit_codes.EXIT_OUTCOME_NOT_OK),
        ("BLOCKED", ("GATE_WORKSPACE_NOT_DECLARED",), "APPLY",
         exit_codes.EXIT_OUTCOME_NOT_OK),
        ("BLOCKED", ("GATE_PLAN_HASH_NOT_CONFIRMED",), "APPLY",
         exit_codes.EXIT_OUTCOME_NOT_OK),
        ("REJECTED", ("PLAN_NOT_APPROVED",), "APPLY", exit_codes.EXIT_OUTCOME_NOT_OK),
        ("ABORTED", ("EXEC_DRIVER_FAILURE",), "APPLY", exit_codes.EXIT_OUTCOME_NOT_OK),
        ("INCONSISTENT", (), "APPLY", exit_codes.EXIT_OUTCOME_NOT_OK),
        ("ATTEMPTED", (), "APPLY", exit_codes.EXIT_OUTCOME_NOT_OK),
        # Sin resultado de escritura NO es exito.
        (None, (), None, exit_codes.EXIT_OUTCOME_NOT_OK),
        # Aplicado pero sin linea de rastro: no es un exito limpio.
        ("APPLIED", ("AUDIT_APPEND_FAILED",), "APPLY", exit_codes.EXIT_USAGE),
        # Pediste escribir y solo se simulo: eso no es 0.
        ("SIMULATED", (), "APPLY", exit_codes.EXIT_OUTCOME_NOT_OK),
    ],
)
def test_tabla_de_codigos(outcome, codes, mode, esperado):
    assert exit_codes.exit_code_for_outcome(outcome, codes, mode=mode) == esperado


def test_los_codigos_son_distinguibles_entre_si():
    """Estables Y distintos: un runner tiene que poder separarlos."""
    valores = {
        exit_codes.EXIT_OK,
        exit_codes.EXIT_OUTCOME_NOT_OK,
        exit_codes.EXIT_USAGE,
        exit_codes.EXIT_ALTAS_NOT_APPROVED,
    }
    assert len(valores) == 4
    assert exit_codes.EXIT_OK == 0
    # Todo lo que no es 0 tiene que ser != 0. Obvio, y por eso se aserta:
    # es la unica propiedad de la que depende un `if rc:` de un runner.
    assert all(v != 0 for v in valores - {exit_codes.EXIT_OK})


# --------------------------------------------------------------------------
# 2. El mando la usa
# --------------------------------------------------------------------------
def _informe(outcome, codes=(), mode="APPLY"):
    return {"write": {"outcome": outcome, "codes": list(codes), "mode": mode}}


def test_rc_del_mando_sobre_apply_bloqueado_no_es_cero():
    rc = ingest_cli._rc_del_desenlace(
        _informe("BLOCKED", ["GATE_ENV_NOT_ALLOWED"])
    )
    assert rc != 0
    assert rc == exit_codes.EXIT_OUTCOME_NOT_OK


def test_rc_de_bloqueado_es_distinguible_del_error_de_argumentos():
    """Se aserta sobre CODIGOS, no sobre el texto del error.

    El `2` de argparse (falta `--operador`, falta `--decisiones`) y el `1` de
    "el gate bloqueo" tienen que ser numeros distintos: si un runner no los
    separa, no puede reintentar solo el segundo.
    """
    bloqueado = ingest_cli._rc_del_desenlace(_informe("BLOCKED", ["GATE_ENV_NOT_ALLOWED"]))
    assert bloqueado != exit_codes.EXIT_USAGE
    assert bloqueado != exit_codes.EXIT_ALTAS_NOT_APPROVED
    assert bloqueado != exit_codes.EXIT_OK


def test_rc_de_dry_run_valido_y_de_apply_aplicado_son_cero():
    assert ingest_cli._rc_del_desenlace(_informe("SIMULATED", mode="DRY_RUN")) == 0
    assert ingest_cli._rc_del_desenlace(_informe("APPLIED", mode="APPLY")) == 0


def test_sin_bloque_write_la_ingesta_es_un_exito():
    """Una corrida que ni llega al writer produjo su informe: eso es 0."""
    assert ingest_cli._rc_del_desenlace({}) == 0


def test_argparse_sigue_saliendo_2_en_apply_sin_operador():
    """El comportamiento que YA era correcto no se toca."""
    with pytest.raises(SystemExit) as exc:
        ingest_cli.main([
            "fuente.md", "--perfil", "p.json", "--apply",
        ])
    assert exc.value.code == exit_codes.EXIT_USAGE == 2


# --------------------------------------------------------------------------
# 3. El TEXTO deriva del desenlace
# --------------------------------------------------------------------------
#: Afirmaciones que una frase NO puede hacer si el hecho no la sostiene.
MENTIRA_SIN_DRIVER = re.compile(r"no se abrio ningun driver")
MENTIRA_DRY_RUN = re.compile(r"\bdry-run\b")


def test_con_driver_abierto_la_frase_no_dice_que_no_se_abrio():
    falta = exit_codes.describe_outcome(
        "SIMULATED", mode="DRY_RUN", driver_opened=True
    )
    # El HECHO estructurado y la prosa salen del mismo dato. Se comprueba el
    # hecho (semantica) y, sobre la prosa, solo que no contenga la NEGACION:
    # buscar la afirmacion por subcadena seria contar texto.
    assert falta["hechos"]["driver_opened"] is True
    assert not MENTIRA_SIN_DRIVER.search(falta["detail"])


def test_sin_driver_la_frase_si_lo_dice():
    falta = exit_codes.describe_outcome(
        "SIMULATED", mode="DRY_RUN", driver_opened=False
    )
    assert MENTIRA_SIN_DRIVER.search(falta["detail"])


def test_un_apply_no_se_describe_como_dry_run():
    for outcome in ("APPLIED", "BLOCKED", "ABORTED", "INCONSISTENT"):
        falta = exit_codes.describe_outcome(
            outcome, mode="APPLY", driver_opened=True, applied_operations=3
        )
        assert not MENTIRA_DRY_RUN.search(falta["detail"]), outcome


def test_bloqueado_dice_bloqueado_y_lleva_sus_codigos():
    falta = exit_codes.describe_outcome(
        "BLOCKED", mode="APPLY", codes=["GATE_ENV_NOT_ALLOWED"], driver_opened=True
    )
    assert falta["code"] == "ESCRITURA_BLOQUEADA"
    assert falta["hechos"]["codes"] == ["GATE_ENV_NOT_ALLOWED"]
    assert falta["hechos"]["wrote_anything"] is False


def test_aplicado_no_se_describe_como_sin_escritura():
    falta = exit_codes.describe_outcome(
        "APPLIED", mode="APPLY", applied_operations=7, driver_opened=True
    )
    assert falta["code"] != "SIN_ESCRITURA"
    assert falta["hechos"]["applied_operations"] == 7
    assert falta["hechos"]["wrote_anything"] is True
    assert falta["hechos"]["was_dry_run"] is False


def test_texto_y_rc_no_pueden_divergir():
    """La propiedad de fondo: misma entrada, un solo desenlace, dos salidas.

    Si el `rc` dice "no es correcto", la frase no puede ser la de un exito, y
    al reves. Se recorre TODO el catalogo de desenlaces del writer para que
    añadir uno nuevo sin decidir su frase rompa esto.
    """
    from knowledge_v3.writer import writer as w

    desenlaces = [
        v for k, v in vars(w).items()
        if k.startswith("OUTCOME_") and isinstance(v, str)
    ]
    assert desenlaces, "no se encontro ningun OUTCOME_* que recorrer"
    for outcome in desenlaces:
        rc = exit_codes.exit_code_for_outcome(outcome)
        falta = exit_codes.describe_outcome(outcome)
        limpio = falta["code"] in ("SIN_ESCRITURA", "ESCRITURA_APLICADA")
        assert (rc == 0) == limpio, (outcome, rc, falta["code"])


# --------------------------------------------------------------------------
# CONTROL NEGATIVO: la comprobacion tiene que poder ponerse ROJA
# --------------------------------------------------------------------------
def test_control_negativo_un_rc_que_miente_pone_roja_la_prueba():
    """Se inyecta un mando que sale 0 sobre BLOCKED (el defecto original).

    Si esta prueba pasa, la de arriba SI puede fallar. Si esta fallara,
    significaria que la comprobacion del `rc` es verde por vacio.
    """
    def _rc_mentiroso(report: dict) -> int:
        return 0  # exactamente el defecto que se corrigio

    fallo = False
    try:
        rc = _rc_mentiroso(_informe("BLOCKED", ["GATE_ENV_NOT_ALLOWED"]))
        assert rc != 0
    except AssertionError:
        fallo = True
    assert fallo, (
        "la comprobacion del rc NO se puso roja ante un mando que miente: "
        "es verde por vacio"
    )


def test_control_negativo_una_frase_que_miente_pone_roja_la_prueba():
    """Se inyecta la frase VIEJA, la fija, con el driver abierto."""
    frase_vieja = {
        "code": "SIN_ESCRITURA",
        "detail": ("dry-run: no se abrio ningun driver y no se toco Neo4j. "
                   "Escribir es del carril C"),
    }
    fallo = False
    try:
        assert not MENTIRA_SIN_DRIVER.search(frase_vieja["detail"])
    except AssertionError:
        fallo = True
    assert fallo, (
        "la comprobacion del texto NO detecta la frase vieja con driver "
        "abierto: no comprueba nada"
    )


def test_control_negativo_la_divergencia_texto_rc_se_detecta():
    """Un desenlace inventado sin frase propia cae en la rama generica.

    Si alguien añadiera un `OUTCOME_X` "correcto" y se olvidara de la frase,
    `test_texto_y_rc_no_pueden_divergir` tiene que romperse. Aqui se simula esa
    divergencia a mano y se comprueba que la asercion la ve.
    """
    rc_fingido = 0            # como si fuera un exito
    frase = exit_codes.describe_outcome("DESENLACE_INVENTADO")
    limpio = frase["code"] in ("SIN_ESCRITURA", "ESCRITURA_APLICADA")
    fallo = False
    try:
        assert (rc_fingido == 0) == limpio
    except AssertionError:
        fallo = True
    assert fallo, "la asercion de coherencia texto/rc no detecta la divergencia"


# --------------------------------------------------------------------------
# 4. El README describe los mandos que EXISTEN. Parseado del parser.
# --------------------------------------------------------------------------
README = (
    Path(__file__).resolve().parents[3]
    / "examples" / "ingesta-v3" / "README.md"
)


@pytest.mark.skipif(not README.exists(), reason="README del ejemplo no presente")
def test_el_readme_no_niega_mandos_que_existen():
    """Se PARSEA el parser; no se cuentan apariciones de texto.

    El README afirmaba «el CLI no admite --apply» y el parser si lo admite.
    Aqui se pide lo contrario: cada bandera real aparece en el README, y
    ninguna bandera real aparece negada.
    """
    parser = ingest_cli.build_parser()
    banderas = {
        opt
        for accion in parser._actions
        for opt in accion.option_strings
        if opt.startswith("--") and opt != "--help"
    }
    texto = README.read_text(encoding="utf-8")
    faltan = sorted(b for b in banderas if b not in texto)
    assert not faltan, f"el README no menciona mandos que existen: {faltan}"
    for bandera in banderas:
        negacion = re.compile(
            r"no\s+admite\s+`?" + re.escape(bandera), re.IGNORECASE
        )
        assert not negacion.search(texto), f"el README niega {bandera}, que existe"


def test_los_hechos_estructurados_no_contradicen_al_desenlace():
    """`wrote_anything` es el campo que un auditor puede leer sin prosa.

    Solo un APPLIED con operaciones puede decir que escribio algo. Se recorre
    el catalogo entero de desenlaces para que uno nuevo no se cuele.
    """
    from knowledge_v3.writer import writer as w

    for k, outcome in vars(w).items():
        if not (k.startswith("OUTCOME_") and isinstance(outcome, str)):
            continue
        h = exit_codes.describe_outcome(outcome, applied_operations=5)["hechos"]
        assert h["wrote_anything"] == (outcome == "APPLIED"), outcome
        assert h["was_dry_run"] == (outcome == "SIMULATED"), outcome
        # Y la propiedad que cierra el circulo: si dice que escribio, el rc
        # tiene que ser 0; si el rc es 0, no puede haber mentido al reves.
        if h["wrote_anything"]:
            assert exit_codes.exit_code_for_outcome(outcome) == 0, outcome


def test_un_desenlace_sin_operaciones_no_afirma_haber_escrito():
    h = exit_codes.describe_outcome("APPLIED", applied_operations=0)["hechos"]
    assert h["wrote_anything"] is False
