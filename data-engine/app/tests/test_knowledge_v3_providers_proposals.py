# -*- coding: utf-8 -*-
"""Mapeo puro de resultados de proveedor a documentos V3 propuestos."""
from __future__ import annotations

import pytest

from knowledge_v3.contracts import (
    ClaimProposal,
    EntityMention,
    EvidenceFragment,
    find_step,
    producing_step,
)
from knowledge_v3.providers import (
    ProposalError,
    Tier,
    claims_from_extraction,
    evidence_fragment_from_text,
    mentions_from_extraction,
    normalize_text,
)

from tests.test_knowledge_v3_providers_support import (
    EPISODE_TEXT,
    make_anchor,
    make_attribution,
)


# --------------------------------------------------------------------------
# Normalizacion determinista
# --------------------------------------------------------------------------
def test_normalize_text_es_determinista_e_idempotente():
    raw = "  El   CONSEJO\tde  Umbra\n"
    once = normalize_text(raw)
    assert once == "el consejo de umbra"
    assert normalize_text(once) == once


def test_normalize_text_normaliza_unicode_compatible():
    """NFKC: la ligadura y el ancho completo colapsan al mismo texto."""
    assert normalize_text("ﬁcha") == normalize_text("ficha")


# --------------------------------------------------------------------------
# EvidenceFragment
# --------------------------------------------------------------------------
def test_evidence_fragment_ancla_los_offsets_localmente():
    anchor = make_anchor()
    literal = "juro lealtad al Consejo de Umbra"
    frag = evidence_fragment_from_text(
        anchor,
        fragment_id="fragment:p12:0",
        literal_text=literal,
        media_type="EMBEDDED_TEXT",
        attribution=make_attribution(),
    )
    assert isinstance(frag, EvidenceFragment)
    assert EPISODE_TEXT[frag.start:frag.end] == literal
    assert frag.normalized_text == normalize_text(literal)
    frag.validate()


def test_evidence_fragment_rechaza_texto_que_no_esta_en_el_episodio():
    """Alucinacion: el proveedor entrega texto que la fuente no contiene."""
    with pytest.raises(ProposalError, match="no aparece literalmente"):
        evidence_fragment_from_text(
            make_anchor(),
            fragment_id="fragment:p12:0",
            literal_text="Daiki fue coronado emperador de Umbra",
            media_type="EMBEDDED_TEXT",
            attribution=make_attribution(),
        )


def test_evidence_asr_sin_anclaje_temporal_se_rechaza():
    with pytest.raises(ProposalError, match="ASR_TEXT"):
        evidence_fragment_from_text(
            make_anchor(),
            fragment_id="fragment:p12:0",
            literal_text="Daiki",
            media_type="ASR_TEXT",
            attribution=make_attribution(),
        )


def test_evidence_ocr_sin_bbox_se_rechaza():
    with pytest.raises(ProposalError, match="OCR_TEXT"):
        evidence_fragment_from_text(
            make_anchor(),
            fragment_id="fragment:p12:0",
            literal_text="Daiki",
            media_type="OCR_TEXT",
            attribution=make_attribution(),
        )


def test_evidence_asr_con_anclaje_temporal_valida():
    anchor = make_anchor(time_start=12.5, time_end=19.0)
    frag = evidence_fragment_from_text(
        anchor,
        fragment_id="fragment:asr:0",
        literal_text="Daiki",
        media_type="ASR_TEXT",
        attribution=make_attribution(),
    )
    assert frag.time_start == 12.5
    frag.validate()


# --------------------------------------------------------------------------
# provider_trace veraz
# --------------------------------------------------------------------------
def test_la_traza_declara_el_proveedor_real_y_su_modelo():
    frag = evidence_fragment_from_text(
        make_anchor(),
        fragment_id="fragment:p12:0",
        literal_text="Daiki",
        media_type="EMBEDDED_TEXT",
        attribution=make_attribution(),
    )
    step = producing_step(frag.to_dict())
    assert step["provider"] == "ollama"
    assert step["model"] == "qwen2.5:7b"
    assert frag.produced_by_step == "extraction.ollama"


def test_un_resultado_externo_se_declara_external_no_local():
    """La trampa que el contrato quiere evitar: externo disfrazado de local."""
    frag = evidence_fragment_from_text(
        make_anchor(),
        fragment_id="fragment:p12:0",
        literal_text="Daiki",
        media_type="EMBEDDED_TEXT",
        attribution=make_attribution(
            tier=Tier.EXTERNAL, name="s9k.extractor.nvidia", model="meta/llama-3.3-70b-instruct",
            step="extraction.nvidia",
        ),
    )
    assert producing_step(frag.to_dict())["provider"] == "external"


def test_el_paso_de_anclaje_es_siempre_local():
    """Los offsets los pone el sistema: ese paso NO puede figurar como externo."""
    frag = evidence_fragment_from_text(
        make_anchor(),
        fragment_id="fragment:p12:0",
        literal_text="Daiki",
        media_type="EMBEDDED_TEXT",
        attribution=make_attribution(tier=Tier.EXTERNAL, step="extraction.nvidia"),
    )
    local = find_step(frag.provider_trace, "anchor.local")
    assert local["provider"] == "local"
    assert "start" in local["produced"] and "end" in local["produced"]


# --------------------------------------------------------------------------
# EntityMention
# --------------------------------------------------------------------------
def _mentions(payload, **kw):
    return mentions_from_extraction(
        make_anchor(),
        payload,
        attribution=make_attribution(),
        evidence_fragment_ids=["fragment:p12:0"],
        **kw,
    )


def test_menciones_validas_se_mapean_y_validan():
    mentions, codes = _mentions(
        {"mentions": [{"surface": "Daiki", "type": "Character", "confidence": 0.91}]}
    )
    assert len(mentions) == 1
    assert isinstance(mentions[0], EntityMention)
    assert mentions[0].best_type() == "Character"
    assert codes == ()
    mentions[0].validate()


def test_mencion_con_superficie_inexistente_se_descarta_con_codigo():
    mentions, codes = _mentions(
        {"mentions": [{"surface": "Emperador Zorak", "type": "Character", "confidence": 0.9}]}
    )
    assert mentions == ()
    assert "PROVIDER_MENTION_NOT_ANCHORABLE" in codes


def test_tipo_fuera_del_catalogo_se_descarta_no_se_traduce():
    """Caso REAL medido: qwen2.5:7b devolvio los tipos en chino."""
    mentions, codes = _mentions(
        {"mentions": [{"surface": "Umbra", "type": "地点", "confidence": 0.72}]}
    )
    assert len(mentions) == 1
    assert mentions[0].type_candidates == [], "un tipo desconocido no puede colarse"
    assert "PROVIDER_TYPE_OUT_OF_CATALOG" in codes


def test_type_candidates_quedan_ordenados_por_confianza():
    mentions, _ = _mentions(
        {
            "mentions": [
                {
                    "surface": "Daiki",
                    "type_candidates": [
                        {"type": "Concept", "confidence": 0.1},
                        {"type": "Character", "confidence": 0.9},
                    ],
                }
            ]
        }
    )
    assert [c["type"] for c in mentions[0].type_candidates] == ["Character", "Concept"]


def test_la_correferencia_nunca_la_propone_un_proveedor():
    mentions, _ = _mentions(
        {
            "mentions": [
                {"surface": "Daiki", "type": "Character", "coreference_candidates": ["mention:x"]}
            ]
        }
    )
    assert mentions[0].coreference_candidates == []


def test_mencion_sin_evidencia_es_un_error_de_programa():
    with pytest.raises(ProposalError):
        mentions_from_extraction(
            make_anchor(),
            {"mentions": []},
            attribution=make_attribution(),
            evidence_fragment_ids=[],
        )


def test_payload_sin_mentions_devuelve_codigo_no_excepcion():
    mentions, codes = _mentions({})
    assert mentions == ()
    assert codes == ("PROVIDER_NO_MENTIONS",)


def test_mentions_no_lista_es_error():
    with pytest.raises(ProposalError):
        _mentions({"mentions": "Daiki"})


def test_elementos_no_objeto_se_descartan_con_codigo():
    mentions, codes = _mentions({"mentions": ["Daiki", 42, None]})
    assert mentions == ()
    assert "PROVIDER_ITEM_NOT_OBJECT" in codes


def test_confianza_fuera_de_rango_se_recorta_a_cero_uno():
    mentions, _ = _mentions(
        {"mentions": [{"surface": "Daiki", "type": "Character", "confidence": 7.5}]}
    )
    assert mentions[0].confidence == 1.0
    mentions[0].validate()


def test_confianza_no_numerica_no_rompe_el_mapeo():
    mentions, _ = _mentions(
        {"mentions": [{"surface": "Daiki", "type": "Character", "confidence": "mucha"}]}
    )
    assert mentions[0].confidence == 0.0


# --------------------------------------------------------------------------
# ClaimProposal
# --------------------------------------------------------------------------
def _claims(payload, mention_ids=("mention:m0", "mention:m1")):
    return claims_from_extraction(
        make_anchor(),
        payload,
        attribution=make_attribution(),
        evidence_fragment_ids=["fragment:p12:0"],
        mention_ids=list(mention_ids),
    )


def test_claim_valido_se_mapea_y_valida():
    claims, codes = _claims(
        {
            "claims": [
                {
                    "subject_mentions": ["mention:m0"],
                    "object_mentions": ["mention:m1"],
                    "relation_phrase": "juro lealtad a",
                    "predicate_candidates": [
                        {"predicate": "MEMBER_OF", "confidence": 0.7},
                        {"predicate": "ALLY_OF", "confidence": 0.2},
                    ],
                    "direction_candidates": [{"direction": "SUBJECT_TO_OBJECT", "confidence": 0.8}],
                    "epistemic_status_hint": "ASSERTED",
                    "confidence": 0.62,
                }
            ]
        }
    )
    assert len(claims) == 1
    claim = claims[0]
    assert isinstance(claim, ClaimProposal)
    assert claim.best_predicate() == "MEMBER_OF"
    assert claim.review_required is True
    claim.validate()


def test_un_claim_de_proveedor_siempre_exige_revision():
    """Ningun proveedor puede declararse a si mismo no revisable."""
    claims, _ = _claims(
        {
            "claims": [
                {
                    "subject_mentions": ["mention:m0"],
                    "object_mentions": ["mention:m1"],
                    "predicate_candidates": [{"predicate": "MEMBER_OF", "confidence": 0.9}],
                    "review_required": False,
                }
            ]
        }
    )
    assert claims[0].review_required is True


def test_mention_id_inventado_se_marca_y_el_claim_cae():
    claims, codes = _claims(
        {
            "claims": [
                {
                    "subject_mentions": ["mention:inventada"],
                    "object_mentions": ["mention:m1"],
                    "predicate_candidates": [{"predicate": "MEMBER_OF", "confidence": 0.9}],
                }
            ]
        }
    )
    assert claims == ()
    assert "PROVIDER_MENTION_ID_INVENTED" in codes


def test_predicado_no_normalizado_se_descarta():
    claims, codes = _claims(
        {
            "claims": [
                {
                    "subject_mentions": ["mention:m0"],
                    "object_mentions": ["mention:m1"],
                    "predicate_candidates": [{"predicate": "es amigo de", "confidence": 0.9}],
                }
            ]
        }
    )
    assert "PROVIDER_PREDICATE_NOT_NORMALIZED" in codes
    assert claims[0].abstained is True
    assert claims[0].confidence == 0.0
    claims[0].validate()


def test_predicate_candidates_quedan_en_orden_canonico():
    claims, _ = _claims(
        {
            "claims": [
                {
                    "subject_mentions": ["mention:m0"],
                    "object_mentions": ["mention:m1"],
                    "predicate_candidates": [
                        {"predicate": "ZETA", "confidence": 0.5},
                        {"predicate": "ALFA", "confidence": 0.5},
                        {"predicate": "BETA", "confidence": 0.9},
                    ],
                }
            ]
        }
    )
    assert [c["predicate"] for c in claims[0].predicate_candidates] == ["BETA", "ALFA", "ZETA"]
    claims[0].validate()


def test_direccion_invalida_se_descarta_con_codigo():
    claims, codes = _claims(
        {
            "claims": [
                {
                    "subject_mentions": ["mention:m0"],
                    "object_mentions": ["mention:m1"],
                    "predicate_candidates": [{"predicate": "MEMBER_OF", "confidence": 0.9}],
                    "direction_candidates": [{"direction": "HACIA_ARRIBA", "confidence": 0.9}],
                }
            ]
        }
    )
    assert "PROVIDER_DIRECTION_INVALID" in codes
    assert claims[0].direction_candidates == []


def test_claim_reflexivo_se_descarta():
    claims, codes = _claims(
        {
            "claims": [
                {
                    "subject_mentions": ["mention:m0"],
                    "object_mentions": ["mention:m0"],
                    "predicate_candidates": [{"predicate": "MEMBER_OF", "confidence": 0.9}],
                }
            ]
        }
    )
    assert claims == ()
    assert "PROVIDER_CLAIM_SELF_RELATION" in codes


def test_hint_epistemico_desconocido_degrada_a_unknown():
    claims, codes = _claims(
        {
            "claims": [
                {
                    "subject_mentions": ["mention:m0"],
                    "object_mentions": ["mention:m1"],
                    "predicate_candidates": [{"predicate": "MEMBER_OF", "confidence": 0.9}],
                    "epistemic_status_hint": "SEGURISIMO",
                }
            ]
        }
    )
    assert claims[0].epistemic_status_hint == "UNKNOWN"
    assert "PROVIDER_EPISTEMIC_HINT_INVALID" in codes


def test_abstencion_lleva_confianza_cero_por_contrato():
    claims, codes = _claims(
        {
            "claims": [
                {
                    "subject_mentions": ["mention:m0"],
                    "object_mentions": ["mention:m1"],
                    "predicate_candidates": [{"predicate": "MEMBER_OF", "confidence": 0.9}],
                    "abstained": True,
                    "confidence": 0.9,
                }
            ]
        }
    )
    assert claims[0].abstained and claims[0].confidence == 0.0
    assert claims[0].predicate_candidates == [], "abstenerse es no proponer predicado"
    assert "PROVIDER_ABSTAINED_WITH_PREDICATE" in codes
    claims[0].validate()


def test_payload_sin_claims_devuelve_codigo():
    claims, codes = _claims({})
    assert claims == ()
    assert codes == ("PROVIDER_NO_CLAIMS",)


# --------------------------------------------------------------------------
# Pureza
# --------------------------------------------------------------------------
def test_el_mapeo_es_puro_dos_llamadas_dan_el_mismo_json():
    payload = {"mentions": [{"surface": "Daiki", "type": "Character", "confidence": 0.9}]}
    a, _ = _mentions(payload)
    b, _ = _mentions(payload)
    assert a[0].to_json() == b[0].to_json()


def test_el_mapeo_no_muta_el_payload_de_entrada():
    import copy

    payload = {"mentions": [{"surface": "Daiki", "type": "Character", "confidence": 0.9}]}
    original = copy.deepcopy(payload)
    _mentions(payload)
    assert payload == original


def test_round_trip_exacto_de_los_documentos_propuestos():
    mentions, _ = _mentions(
        {"mentions": [{"surface": "Daiki", "type": "Character", "confidence": 0.9}]}
    )
    doc = mentions[0]
    assert EntityMention.from_dict(doc.to_dict()) == doc
