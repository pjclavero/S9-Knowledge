# -*- coding: utf-8 -*-
"""M5b-1 -- el escritor estampa la visibilidad y el payload no puede imponerla.

La pregunta que responden estas pruebas no es "¿sabe el motor decidir?" sino
"¿llega al grafo un valor en el que el motor pueda confiar?". Un motor
impecable sobre una propiedad que el payload eligio no protege nada.
"""
import pytest

from knowledge_v3.writer import cypher
from knowledge_v3.writer.visibility import (
    SOURCE_DEFAULT,
    SOURCE_EXPLICIT,
    KnowledgeVisibilityV1,
    VisibilityLevel,
    VisibilityStampError,
    stamp,
)

WS = "ws:test"


def props_de(q):
    return q.params["props"]


# --- estampado ------------------------------------------------------------
def test_sin_visibilidad_declarada_queda_en_secret_no_en_visible():
    """Un olvido no publica nada. Es toda la razon de ser del defecto."""
    p = props_de(cypher.create_entity("e:1", WS, None, {"name": "Doji"}))
    assert p["visibility"] == "secret"
    assert p["visibility_source"] == SOURCE_DEFAULT


def test_la_propiedad_se_escribe_siempre_aunque_known_by_este_vacio():
    """Ausente y vacio deben ser distinguibles: uno es un dato, el otro un fallo."""
    p = props_de(cypher.create_entity("e:1", WS, None, {}))
    assert "known_by" in p and p["known_by"] == []


def test_visibilidad_explicita_se_respeta_y_se_marca_como_tal():
    v = KnowledgeVisibilityV1(visibility=VisibilityLevel.PLAYER, known_by=("char:doji",))
    p = props_de(cypher.create_entity("e:1", WS, None, {}, visibility=v))
    assert p["visibility"] == "player"
    assert p["known_by"] == ["char:doji"]
    assert p["visibility_source"] == SOURCE_EXPLICIT


def doc(**extra):
    """Documento minimo conforme: el contrato exige identificarse a si mismo."""
    return {
        "contract_id": "knowledge-visibility/v1",
        "contract_version": "1.0.0",
        "visibility": "narrator",
        "known_by": [],
        **extra,
    }


def test_acepta_dict_conforme_al_contrato():
    p = props_de(cypher.create_assertion("a:1", WS, {}, visibility=doc()))
    assert p["visibility"] == "narrator"


def test_un_dict_sin_identificar_el_contrato_se_rechaza():
    """No se adivina a que contrato pertenece: o lo dice, o no vale."""
    with pytest.raises(VisibilityStampError):
        stamp({}, {"visibility": "narrator", "known_by": []}, partida_id=None)


def test_deny_se_puede_estampar_es_un_estado_legitimo_persistido():
    v = KnowledgeVisibilityV1(visibility=VisibilityLevel.DENY)
    p = props_de(cypher.create_entity("e:1", WS, None, {}, visibility=v))
    assert p["visibility"] == "deny"


# --- el payload no manda ---------------------------------------------------
@pytest.mark.parametrize(
    "prop", ["visibility", "known_by", "visibility_contract", "visibility_source"]
)
def test_el_payload_no_puede_colar_propiedades_de_visibilidad(prop):
    with pytest.raises(VisibilityStampError):
        cypher.create_entity("e:1", WS, None, {prop: "player"})


def test_el_payload_no_puede_colarlas_en_una_relacion():
    with pytest.raises(VisibilityStampError):
        cypher.create_relation("KNOWS", "e:1", "e:2", WS, {"visibility": "player"})


def test_las_propiedades_de_visibilidad_estan_reservadas():
    """Reservadas de verdad, no solo por convencion en el codigo."""
    assert {"visibility", "known_by", "visibility_contract", "visibility_source"} <= (
        cypher.RESERVED_PROPS
    )


# --- valores invalidos ------------------------------------------------------
@pytest.mark.parametrize(
    "malo",
    [
        {"visibility": "publico"},          # nivel inexistente
        {"visibility": ""},                 # vacio
        {"visibility": None},               # nulo explicito
        {"visibility": "PLAYER "},          # con espacio: no es el enum
        {"visibility": "player", "known_by": ["char:x", "char:x"]},  # duplicados
        {"visibility": "player", "known_by": [""]},                  # id vacio
    ],
)
def test_visibilidad_invalida_se_rechaza_no_se_degrada_en_silencio(malo):
    """Rechazar, no corregir. Corregir en silencio oculta el error de quien escribe."""
    with pytest.raises(VisibilityStampError):
        stamp({}, malo, partida_id=None)


def test_una_cadena_suelta_no_es_una_visibilidad_valida():
    """Aceptar `"player"` a secas es justo como se cuela un valor sin validar."""
    with pytest.raises(VisibilityStampError):
        stamp({}, "player", partida_id=None)


# --- no rompe lo anterior ---------------------------------------------------
def test_el_ambito_sigue_estampandose_junto_a_la_visibilidad():
    p = props_de(cypher.create_entity("e:1", WS, None, {}, partida_id="partida:Y", known_from_session=0))
    assert p["workspace"] == WS and p["partida_id"] == "partida:Y"
    assert p["visibility"] == "secret"


def test_las_consultas_generadas_siguen_pasando_la_guardia_destructiva():
    for q in (
        cypher.create_entity("e:1", WS, "Persona", {"name": "x"}),
        cypher.create_assertion("a:1", WS, {}),
        cypher.create_relation("KNOWS", "e:1", "e:2", WS, {}),
    ):
        cypher.assert_safe(q.cypher)


def test_stamp_no_muta_el_payload_original():
    original = {"name": "Doji"}
    stamp(original, partida_id=None)
    assert original == {"name": "Doji"}
