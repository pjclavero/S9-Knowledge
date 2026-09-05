# -*- coding: utf-8 -*-
"""Ingesta V3 de una fuente REAL: el vertical slice, extremo a extremo.

Esta suite no puntua nada contra el gold: corre la cadena sobre **bytes de un
fichero de verdad** y comprueba que lo que sale es lo que el informe dice que
sale. Tres clases de prueba:

  * **positivo**: la nota de `examples/ingesta-v3/` produce episodios,
    evidencia, menciones enlazadas, un alta de entidad, relaciones, una
    afirmacion y un plan aprobado;
  * **negativo critico**: el CLI no puede escribir (no admite `--apply`) y no
    disimula lo que no encuentra (declara carencias en vez de ceros mudos);
  * **integracion**: los conteos del informe se recuentan sobre el propio
    informe, y dos corridas con el mismo instante inyectado dan el mismo
    `plan_hash`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.pipeline import ingest_cli  # noqa: E402
from knowledge_v3.pipeline.errors import PipelineError  # noqa: E402
from knowledge_v3.pipeline.ingest_report import REPORT_CONTRACT  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
EJEMPLOS = REPO / "examples" / "ingesta-v3"
FUENTE = EJEMPLOS / "nota-cofradia-de-ambar.md"
PERFIL = EJEMPLOS / "perfil-operador.json"
CATALOGO = EJEMPLOS / "catalogo-workspace.json"

#: Instante INYECTADO: la cadena no llama al reloj, y fijarlo aqui es lo que
#: hace que dos corridas sean comparables byte a byte.
AHORA = "2026-09-05T10:00:00Z"


@pytest.fixture(scope="module")
def informe() -> dict:
    return ingest_cli.run_ingest(
        FUENTE, profile_path=PERFIL, catalog_path=CATALOGO, now=AHORA
    )


# --------------------------------------------------------------------------
# 1. Positivo: la fuente real entra y produce conocimiento
# --------------------------------------------------------------------------
def test_la_fuente_real_se_normaliza_desde_bytes(informe):
    assert informe["report_contract"] == REPORT_CONTRACT
    assert informe["run"]["source_kind"] == "MARKDOWN"
    assert informe["run"]["byte_size"] == FUENTE.stat().st_size
    assert informe["run"]["input_hash"]["algorithm"] == "sha256"
    assert informe["episodes"], "el normalizador no produjo episodios"
    assert informe["evidence"], "sin evidencia no hay nada que anclar"


def test_cada_evidencia_apunta_a_un_episodio_de_esta_corrida(informe):
    episodios = {e["episode_id"] for e in informe["episodes"]}
    for fragmento in informe["evidence"]:
        assert fragmento["episode_id"] in episodios


def test_hay_entidades_enlazadas_contra_el_catalogo(informe):
    enlaces = informe["candidates"]["link_existing"]
    assert enlaces, "ninguna mencion se enlazo con el grafo existente"
    catalogo = {
        e["entity_id"] for e in json.loads(CATALOGO.read_text(encoding="utf-8"))["entities"]
    }
    for enlace in enlaces:
        destino = enlace["assigned_entity_id"] or enlace["selected_entity_id"]
        assert destino in catalogo, f"se enlazo a {destino!r}, que no esta en el catalogo"


def test_la_entidad_provisional_se_propone_como_alta_no_como_enlace(informe):
    """`Bren Halloway` esta en el glosario pero NO en el grafo: alta, no enlace."""
    altas = informe["candidates"]["create_entity"]
    assert len(altas) == 1, [a["action"] for a in altas]
    assert altas[0]["action"] in ("CREATE_NEW", "CREATE_PROVISIONAL")
    assert altas[0]["entity_type"] == "Character"
    enlazadas = {
        c["assigned_entity_id"] or c["selected_entity_id"]
        for c in informe["candidates"]["link_existing"]
    }
    assert "entity:bren-halloway" not in enlazadas


def test_hay_relaciones_con_evidencia_y_una_afirmacion_aceptada(informe):
    assert informe["claims"], "el extractor no propuso ninguna relacion"
    aceptadas = [d for d in informe["decisions"] if d["decision"] == "ACCEPT"]
    assert aceptadas, "ninguna decision ACCEPT: no hay conocimiento que escribir"
    assert len(informe["assertions"]) == len(aceptadas)
    for decision in aceptadas:
        assert decision["evidence_fragment_ids"], "una ACCEPT sin evidencia"


def test_la_negacion_no_se_asserta_como_hecho(informe):
    """`Sela Marrec no pertenece al Consejo de Umbra` no puede acabar en ACCEPT."""
    negadas = [d for d in informe["decisions"] if d["negated"]]
    assert negadas, "la frase negada de la fuente no llego al motor"
    for decision in negadas:
        assert decision["decision"] != "ACCEPT"
    afirmados = {
        (a["subject_entity_id"], a["predicate"], a["object_entity_id"])
        for a in informe["assertions"]
    }
    assert ("entity:sela-marrec", "MEMBER_OF", "entity:consejo-umbra") not in afirmados


def test_el_plan_esta_sellado_y_es_lo_que_consume_el_carril_c(informe):
    plan = informe["plan"]
    assert plan is not None
    assert plan["contract_id"] == "graph-mutation-plan/v3-internal-v1"
    assert plan["local_approval"]["approved"] is True
    assert plan["plan_hash"]["algorithm"] == "sha256"
    assert plan["mutation_operations"], "un plan aprobado sin operaciones no escribe nada"


# --------------------------------------------------------------------------
# 2. Negativo critico
# --------------------------------------------------------------------------
def test_el_cli_no_admite_apply(capsys):
    """Escribir es del carril C. No hay bandera, y por eso no hay descuido.

    Se comprueba la ESTRUCTURA del parser (que `--apply` no es una opcion
    declarada) y el EFECTO (salida distinta de cero), no la redaccion del aviso.
    """
    opciones = {
        cadena
        for accion in ingest_cli.build_parser()._actions
        for cadena in accion.option_strings
    }
    assert "--apply" not in opciones
    with pytest.raises(SystemExit) as exc:
        ingest_cli.main([str(FUENTE), "--perfil", str(PERFIL), "--apply"])
    assert exc.value.code != 0
    capsys.readouterr()


def test_la_corrida_declara_dry_run_y_no_lleva_driver(informe):
    assert informe["run"]["apply"] is False
    assert informe["run"]["writer_mode"] == "DRY_RUN"


def test_sin_glosario_no_se_publica_un_cero_mudo(tmp_path):
    """Una fuente cuyos nombres no conoce nadie: el informe lo DICE."""
    perfil = json.loads(PERFIL.read_text(encoding="utf-8"))
    # El glosario del perfil son alias + facciones + titulos (`Lexicon.from_profile`).
    # Se vacian los tres: un perfil que no nombra nada del mundo.
    perfil["aliases"] = []
    perfil["factions"] = []
    perfil["titles"] = []
    sin_alias = tmp_path / "perfil-sin-alias.json"
    sin_alias.write_text(json.dumps(perfil), encoding="utf-8")

    informe = ingest_cli.run_ingest(FUENTE, profile_path=sin_alias, now=AHORA)
    codigos = {c["code"] for c in informe["carencias"]}
    assert "SIN_GLOSARIO" in codigos
    assert "SIN_MENCIONES" in codigos
    assert informe["totals"]["mentions"] == 0
    assert informe["run"]["lexicon_entries"] == 0


def test_un_perfil_de_otro_workspace_no_se_reescribe_en_silencio():
    """Se comprueba la ETAPA del error, no su redaccion (politica del carril 5)."""
    with pytest.raises(PipelineError) as exc:
        ingest_cli.run_ingest(
            FUENTE, profile_path=PERFIL, workspace="otro-workspace", now=AHORA
        )
    assert exc.value.stage == "config"


def test_un_fichero_vacio_no_es_una_fuente(tmp_path):
    vacio = tmp_path / "vacio.md"
    vacio.write_bytes(b"")
    with pytest.raises(PipelineError) as exc:
        ingest_cli.run_ingest(vacio, profile_path=PERFIL, now=AHORA)
    assert exc.value.stage == "input"


# --------------------------------------------------------------------------
# 3. Integracion: el informe se puede auditar contra si mismo
# --------------------------------------------------------------------------
def test_todos_los_totales_se_recuentan_sobre_el_propio_informe(informe):
    """Ningun total es un numero de otro sitio: se recalcula aqui, con `len`."""
    totals = informe["totals"]
    assert totals["episodes"] == len(informe["episodes"])
    assert totals["evidence"] == len(informe["evidence"])
    assert totals["mentions"] == len(informe["mentions"])
    assert totals["resolutions"] == len(informe["resolutions"])
    assert totals["claims"] == len(informe["claims"])
    assert totals["decisions"] == len(informe["decisions"])
    assert totals["assertions"] == len(informe["assertions"])
    assert totals["abstentions"] == len(informe["abstentions"])
    assert totals["contradictions"] == len(informe["contradictions"])
    assert totals["plan_operations"] == len(informe["plan"]["mutation_operations"])
    esperado = (
        totals["link_existing"] + totals["create_entity"] + totals["review_identity"]
    )
    assert esperado == totals["resolutions"]
    assert sum(totals["decisions_by_outcome"].values()) == totals["decisions"]


def test_dos_corridas_con_el_mismo_instante_dan_el_mismo_plan(informe):
    otra = ingest_cli.run_ingest(
        FUENTE, profile_path=PERFIL, catalog_path=CATALOGO, now=AHORA
    )
    assert otra["plan"]["plan_hash"] == informe["plan"]["plan_hash"]
    assert otra["run"]["input_hash"] == informe["run"]["input_hash"]


def test_una_fuente_txt_tambien_entra(tmp_path):
    """TXT y Markdown son el minimo que este CLI declara soportar."""
    nota = tmp_path / "nota.txt"
    nota.write_text(
        "La Cofradia de Ambar es aliada de la Casa del Ciervo.\n", encoding="utf-8"
    )
    informe = ingest_cli.run_ingest(
        nota, profile_path=PERFIL, catalog_path=CATALOGO, now=AHORA
    )
    assert informe["run"]["source_kind"] == "TEXT"
    assert informe["totals"]["mentions"] >= 2


def test_el_acta_markdown_menciona_las_secciones_del_encargo(informe):
    from knowledge_v3.pipeline.ingest_report import to_markdown

    acta = to_markdown(informe)
    for seccion in (
        "SOURCE", "INPUT HASH", "EPISODES", "EVIDENCE", "ENTITIES",
        "LINK_EXISTING", "CREATE_ENTITY", "RELATIONS", "REVIEW", "ABSTAIN",
        "ASSERTIONS", "PLAN", "CARENCIAS",
    ):
        assert seccion in acta, f"el acta no publica {seccion}"
