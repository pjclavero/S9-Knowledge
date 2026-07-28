# -*- coding: utf-8 -*-
"""Subsistema extractor V3: anclaje, precision, anti-alucinacion y mutaciones.

Estructura de la suite:

- fixtures GOLD propias (seis episodios pequenos con verdad de campo escrita a
  mano en `GOLD_CLAIMS`). Son deliberadamente cortas: sirven para fijar el
  COMPORTAMIENTO del extractor, no para estimar su calidad. La calidad la mide
  el benchmark con corpus held-out, y esta suite no puede sustituirlo;
- precision del determinista sobre las gold (se exige 1.0; la cobertura se
  reporta pero no se exige, que es exactamente la politica del subsistema);
- anti-alucinacion: citas, superficies y `fragment_id` inventados;
- mutaciones de las reglas clave: si al romper una regla la suite sigue verde,
  esa regla no estaba sosteniendo nada.
"""
from __future__ import annotations

import hashlib
import json

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.contracts import (  # noqa: E402
    CONTRACT_VERSION,
    ClaimProposal,
    EntityMention,
    EvidenceFragment,
    GameProfile,
    SourceEpisode,
    V3ContractError,
)
from knowledge_v3.extraction import (  # noqa: E402
    CoreferenceExtractor,
    DeterministicExtractor,
    EvidenceIndex,
    ExtractionContext,
    ExtractionError,
    ExtractionOutput,
    ExtractionPipeline,
    ExternalExtractionResponse,
    ExternalExtractor,
    Lexicon,
    LexiconEntry,
    TableExtractor,
    TemporalExtractor,
    VisualExtractor,
    build_claim,
    emit,
    normalize_payload,
    normalize_predicate,
)
from knowledge_v3.extraction import deterministic as det_mod  # noqa: E402
from knowledge_v3.extraction.deterministic import DETERMINISTIC_INFO  # noqa: E402
from knowledge_v3.extraction.text import tokenize  # noqa: E402

WORKSPACE = "gold"
ASSET_ID = "asset:gold-001"


def h(seed: str) -> dict:
    return {"algorithm": "sha256", "value": hashlib.sha256(seed.encode("utf-8")).hexdigest()}


SOURCE_HASH = h(ASSET_ID)


def trace(step: str = "normalize", produced=("text",)) -> list:
    return [
        {
            "step": step,
            "provider": "local",
            "name": "s9k.multimodal",
            "version": "3.0.0",
            "model": None,
            "produced": list(produced),
        }
    ]


def make_episode(episode_id: str, text=None, modality="TEXT", **over) -> SourceEpisode:
    data = dict(
        contract_version=CONTRACT_VERSION,
        workspace=WORKSPACE,
        source_asset_id=ASSET_ID,
        source_hash=SOURCE_HASH,
        provider_trace=trace(),
        produced_by_step="normalize",
        episode_id=episode_id,
        asset_id=ASSET_ID,
        sequence=0,
        modality=modality,
        text=text,
        page=None,
        bbox=None,
        time_start=None,
        time_end=None,
        previous_episode_id=None,
        next_episode_id=None,
        speaker=None,
        turn=None,
        table=None,
        quality={"score": 0.95, "flags": []},
        content_hash=h(episode_id + (text or "")),
    )
    data.update(over)
    episode = SourceEpisode(**data)
    episode.validate()
    return episode


def make_fragment(
    episode: SourceEpisode,
    fragment_id: str,
    literal: str,
    start: int,
    media_type: str = "EMBEDDED_TEXT",
    **over,
) -> EvidenceFragment:
    data = dict(
        contract_version=CONTRACT_VERSION,
        workspace=WORKSPACE,
        source_asset_id=ASSET_ID,
        source_hash=SOURCE_HASH,
        provider_trace=trace("fragment", ("literal_text",)),
        produced_by_step="fragment",
        fragment_id=fragment_id,
        episode_id=episode.episode_id,
        literal_text=literal,
        normalized_text=literal.lower(),
        start=start,
        end=start + len(literal),
        bbox=None,
        time_start=None,
        time_end=None,
        frame_id=None,
        page=None,
        media_type=media_type,
        confidence=0.99,
    )
    data.update(over)
    fragment = EvidenceFragment(**data)
    fragment.validate()
    return fragment


def text_episode(episode_id: str, text: str, **over):
    """Episodio de texto con UN fragmento que cubre todo el texto."""
    episode = make_episode(episode_id, text=text, **over)
    fragment = make_fragment(episode, f"frag:{episode_id}:0", text, 0)
    return episode, [fragment]


# --------------------------------------------------------------------------
# Lexico y perfil
# --------------------------------------------------------------------------
GOLD_LEXICON = Lexicon(
    [
        LexiconEntry("Elara", "Character", ("Elara de Val",), 0.9, "glossary"),
        LexiconEntry("Kael", "Character", (), 0.9, "glossary"),
        LexiconEntry("Valdor", "Location", (), 0.9, "glossary"),
        LexiconEntry("Orden del Alba", "Faction", ("la Orden",), 0.9, "glossary"),
        LexiconEntry("Espada de Ceniza", "Object", (), 0.85, "glossary"),
    ]
)


def make_profile(**over) -> GameProfile:
    data = dict(
        contract_version=CONTRACT_VERSION,
        workspace=WORKSPACE,
        source_asset_id="profile:generic",
        source_hash=h("profile:generic"),
        provider_trace=trace("profile", ("predicates",)),
        produced_by_step="profile",
        profile_id="generic",
        profile_version="1.0.0",
        core_ontology_version="1.0.0",
        entity_types=["Character", "Location", "Faction", "Object", "Event", "Concept"],
        predicates=[
            {"predicate": "MEMBER_OF", "domain": ["Character"], "range": ["Faction"]},
            {"predicate": "LIVES_IN", "domain": ["Character"], "range": ["Location"]},
            {"predicate": "LEADS", "domain": ["Character"], "range": ["Faction", "Character"]},
            {"predicate": "FOUNDED", "domain": ["Character"], "range": ["Location", "Faction"]},
            {"predicate": "LOCATED_IN", "domain": ["Location", "Object"], "range": ["Location"]},
            {"predicate": "OWNS", "domain": ["Character"], "range": ["Object"]},
        ],
        aliases=[{"canonical": "Orden del Alba", "variants": ["la Orden"]}],
        titles=["maestre"],
        factions=["Orden del Alba"],
        calendars=[{"calendar_id": "era-tercera", "epoch_label": "Tercera Era", "units": ["ciclo"]}],
        identity_rules=[],
        ambiguous_terms=[],
        source_priorities=[],
        evaluation_examples=[],
    )
    data.update(over)
    profile = GameProfile(**data)
    profile.validate()
    return profile


# --------------------------------------------------------------------------
# Corpus GOLD
# --------------------------------------------------------------------------
GOLD_TEXTS = {
    "ep:gold-1": "Elara pertenece a la Orden del Alba. Kael vive en Valdor.",
    "ep:gold-2": "Elara y Kael viven en Valdor.",
    "ep:gold-3": "Kael no vive en Valdor.",
    "ep:gold-4": "Se dice que Elara lidera la Orden del Alba.",
    "ep:gold-5": "En el año 300 de la Tercera Era, Kael fundó Valdor.",
    "ep:gold-6": "Elara caminó despacio junto al río mientras anochecía.",
}

#: Verdad de campo escrita a mano: (episodio, sujeto, predicado, objeto).
GOLD_CLAIMS = {
    ("ep:gold-1", "Elara", "MEMBER_OF", "Orden del Alba"),
    ("ep:gold-1", "Kael", "LIVES_IN", "Valdor"),
    ("ep:gold-3", "Kael", "LIVES_IN", "Valdor"),  # negado, pero es el mismo hecho propuesto
    ("ep:gold-4", "Elara", "LEADS", "Orden del Alba"),
    ("ep:gold-5", "Kael", "FOUNDED", "Valdor"),
}

#: Episodios donde la lectura NO es inequivoca: el extractor no debe afirmar.
GOLD_MUST_NOT_ASSERT = {"ep:gold-2", "ep:gold-6"}


def gold_context(profile=None, lexicon=GOLD_LEXICON) -> ExtractionContext:
    episodes, fragments = [], []
    for episode_id, text in GOLD_TEXTS.items():
        episode, frags = text_episode(episode_id, text)
        episodes.append(episode)
        fragments.extend(frags)
    return ExtractionContext(
        workspace=WORKSPACE,
        episodes=episodes,
        fragments=fragments,
        profile=profile,
        lexicon=lexicon,
    )


def single_context(episode_id: str, text: str, *, profile=None, lexicon=GOLD_LEXICON, **over):
    episode, frags = text_episode(episode_id, text, **over)
    ctx = ExtractionContext(
        workspace=WORKSPACE,
        episodes=[episode],
        fragments=frags,
        profile=profile,
        lexicon=lexicon,
    )
    return ctx, episode


def surfaces_of(out: ExtractionOutput, claim: ClaimProposal) -> tuple:
    def surface(mention_id):
        m = out.mention_by_id(mention_id)
        return m.metadata.get("canonical_surface", m.surface) if m else None

    return (
        surface(claim.subject_mentions[0]) if claim.subject_mentions else None,
        claim.best_predicate(),
        surface(claim.object_mentions[0]) if claim.object_mentions else None,
    )


def asserted(out: ExtractionOutput) -> list:
    return [c for c in out.claims if not c.abstained]


# ==========================================================================
# 1. Texto, tokenizacion y anclaje
# ==========================================================================
class TestTextAndAnchoring:
    def test_tokenize_preserva_offsets_del_texto_original(self):
        text = "Elara vive en Valdór."
        tokens = tokenize(text)
        for token in tokens:
            assert text[token.start:token.end] == token.text
        assert [t.norm for t in tokens] == ["elara", "vive", "en", "valdor"]

    def test_normalizacion_es_la_del_glosario_v1(self):
        from glossary.glossary_store import normalize_term
        from knowledge_v3.extraction.text import normalize

        for value in ("Orden del Alba", "VALDÓR", "espada-de-ceniza"):
            assert normalize(value) == normalize_term(value)

    def test_anclaje_rechaza_cita_inexistente(self):
        ctx, episode = single_context("ep:anchor", "Kael vive en Valdor.")
        index = ctx.index_of(episode)
        assert index.anchor_quote("Kael vive en Valdor") is not None
        assert index.anchor_quote("Kael gobierna Nara") is None

    def test_anclaje_reancla_cuando_el_fragment_id_no_existe(self):
        ctx, episode = single_context("ep:anchor2", "Kael vive en Valdor.")
        index = ctx.index_of(episode)
        anchor = index.anchor_quote("Valdor", "frag:inventado")
        assert anchor is not None
        assert anchor.fragment_id == "frag:ep:anchor2:0"
        assert "FRAGMENT_ID_NOT_FOUND" in anchor.reason_codes
        assert "REANCHORED_BY_CONTENT" in anchor.reason_codes

    def test_anclaje_marca_ambiguedad_con_varios_fragmentos(self):
        episode = make_episode("ep:amb", text="Valdor. Valdor.")
        f1 = make_fragment(episode, "frag:a", "Valdor.", 0)
        f2 = make_fragment(episode, "frag:b", "Valdor.", 8)
        index = EvidenceIndex(episode.episode_id, episode.text, (f1, f2))
        anchor = index.anchor_quote("Valdor")
        assert anchor is not None and anchor.ambiguous

    def test_offsets_de_un_episodio_sin_texto_son_del_fragmento(self):
        episode = make_episode("ep:notext", text=None, modality="IMAGE")
        frag = make_fragment(episode, "frag:img", "Un mapa de Valdor", 0, media_type="TABLE")
        index = EvidenceIndex(episode.episode_id, None, (frag,))
        anchor = index.anchor_quote("Valdor")
        assert anchor is not None
        assert anchor.basis == "fragment"
        assert frag.literal_text[anchor.start:anchor.end] == "Valdor"


# ==========================================================================
# 2. Lexico
# ==========================================================================
class TestLexicon:
    def test_no_casa_dentro_de_otra_palabra(self):
        tokens = tokenize("Elaramir no es Elara.")
        matches = GOLD_LEXICON.find_all(tokens)
        assert [m.surface for m in matches] == ["Elara"]
        assert matches[0].start == 15

    def test_prefiere_la_coincidencia_mas_larga(self):
        lex = Lexicon([LexiconEntry("Val", "Location"), LexiconEntry("Reino de Val", "Location")])
        matches = lex.find_all(tokenize("El Reino de Val prospera."))
        assert [m.surface for m in matches] == ["Reino de Val"]

    def test_alias_vale_menos_que_la_forma_canonica(self):
        matches = GOLD_LEXICON.find_all(tokenize("la Orden del Alba y la Orden"))
        by_surface = {m.surface: m for m in matches}
        assert by_surface["Orden del Alba"].confidence > by_surface["la Orden"].confidence
        assert by_surface["la Orden"].is_canonical is False

    def test_puente_con_el_glosario_v1_traduce_tipos_y_excluye_error_forms(self):
        from glossary.glossary_models import GlossaryTerm

        term = GlossaryTerm(
            workspace=WORKSPACE,
            canonical_term="Elara",
            normalized_term="elara",
            term_type="personaje",
            aliases=["Elara de Val"],
            spoken_forms=["elara"],
            error_forms=["e lara"],
            confidence=0.8,
        )
        lex = Lexicon.from_glossary_terms([term])
        entry = lex.entries[0]
        assert entry.entity_type == "Character"
        assert "Elara de Val" in entry.variants
        assert "e lara" not in entry.variants

    def test_tipo_desconocido_no_se_adivina(self):
        from knowledge_v3.extraction.lexicon import map_term_type

        assert map_term_type("cosa rara") is None
        assert map_term_type(None) is None


# ==========================================================================
# 3. Contratos: todo lo emitido valida
# ==========================================================================
class TestContractCompliance:
    def test_todo_lo_emitido_valida_contra_los_contratos_congelados(self):
        out = ExtractionPipeline.local_default().run(gold_context())
        assert out.mentions and out.claims
        for doc in [*out.mentions, *out.claims]:
            doc.validate()  # lanza si no cumple
            assert doc.contract_version == CONTRACT_VERSION
            assert doc.workspace == WORKSPACE

    def test_produced_by_step_apunta_al_paso_real(self):
        out = ExtractionPipeline.local_default().run(gold_context())
        for doc in [*out.mentions, *out.claims]:
            step = doc.to_dict()["produced_by_step"]
            entry = [e for e in doc.provider_trace if e["step"] == step]
            assert len(entry) == 1
            assert entry[0]["provider"] == "local"

    def test_emit_rechaza_un_documento_que_no_cumple_el_contrato(self):
        ctx, episode = single_context("ep:bad", "Kael vive en Valdor.")
        claim = build_claim(
            info=DETERMINISTIC_INFO,
            episode=episode,
            evidence_fragment_ids=["frag:ep:bad:0"],
            subject_mentions=["m:1"],
            object_mentions=["m:2"],
            predicate_candidates=[{"predicate": "LIVES_IN", "confidence": 0.8}],
            confidence=0.8,
        )
        claim.abstained = True  # contradiccion: abstenido con predicado y confianza
        out = ExtractionOutput()
        assert emit(claim, out, DETERMINISTIC_INFO, episode.episode_id) is False
        assert out.claims == []
        assert "CONTRACT_VIOLATION" in out.codes()

    def test_abstencion_no_lleva_predicado_ni_confianza(self):
        out = DeterministicExtractor().extract(gold_context())
        for claim in out.claims:
            if claim.abstained:
                assert claim.predicate_candidates == []
                assert claim.confidence == 0.0

    def test_aislamiento_de_workspace_es_duro(self):
        episode, frags = text_episode("ep:iso", "Kael vive en Valdor.")
        with pytest.raises(ExtractionError):
            ExtractionContext(workspace="otro", episodes=[episode], fragments=frags)

    def test_los_identificadores_son_deterministas(self):
        first = ExtractionPipeline.local_default().run(gold_context())
        second = ExtractionPipeline.local_default().run(gold_context())
        assert [m.to_json() for m in first.mentions] == [m.to_json() for m in second.mentions]
        assert [c.to_json() for c in first.claims] == [c.to_json() for c in second.claims]

    def test_roundtrip_de_las_propuestas(self):
        out = DeterministicExtractor().extract(gold_context())
        for doc in [*out.mentions, *out.claims]:
            cls = type(doc)
            assert cls.from_dict(json.loads(doc.to_json())) == doc


# ==========================================================================
# 4. Extractor determinista: precision sobre el corpus GOLD
# ==========================================================================
class TestDeterministicPrecision:
    def test_precision_sobre_las_gold_es_total(self):
        out = DeterministicExtractor().extract(gold_context())
        emitted = {
            (c.episode_id, *surfaces_of(out, c)) for c in asserted(out)
        }
        falsos = emitted - GOLD_CLAIMS
        assert falsos == set(), f"falsos positivos: {falsos}"

    def test_cobertura_se_reporta(self):
        """REPORTA la cobertura; no la exige. Solo comprueba que no es cero.

        Un umbral sobre seis frases escritas por nosotros no seria una medida de
        calidad: seria dev == test, el error exacto del PR #106. La cifra se
        imprime para que quede en el log del gate y la mida el benchmark.
        """
        out = DeterministicExtractor().extract(gold_context())
        emitted = {(c.episode_id, *surfaces_of(out, c)) for c in asserted(out)}
        aciertos = emitted & GOLD_CLAIMS
        recall = len(aciertos) / len(GOLD_CLAIMS)
        print(
            f"\n[gold] recall={recall:.2f} ({len(aciertos)}/{len(GOLD_CLAIMS)}) "
            f"precision=1.00 por construccion (ver test anterior) "
            f"— cifra de COMPORTAMIENTO, no de calidad"
        )
        assert aciertos, "el extractor no acierta ni una: eso si es un fallo"

    def test_frase_coordinada_no_produce_afirmacion(self):
        ctx, _ = single_context("ep:gold-2", GOLD_TEXTS["ep:gold-2"])
        out = DeterministicExtractor().extract(ctx)
        assert asserted(out) == []
        codes = [r for c in out.claims for r in c.metadata["abstention_reasons"]]
        assert "COORDINATED_SUBJECT" in codes

    def test_texto_sin_relacion_no_produce_claims(self):
        ctx, _ = single_context("ep:gold-6", GOLD_TEXTS["ep:gold-6"])
        out = DeterministicExtractor().extract(ctx)
        assert out.claims == []
        assert [m.surface for m in out.mentions] == ["Elara"]

    def test_negacion_se_detecta_y_obliga_a_revision(self):
        ctx, _ = single_context("ep:gold-3", GOLD_TEXTS["ep:gold-3"])
        claim = asserted(DeterministicExtractor().extract(ctx))[0]
        assert claim.negated is True
        assert claim.review_required is True
        assert claim.best_predicate() == "LIVES_IN"

    def test_rumor_degrada_el_estatus_epistemico(self):
        ctx, _ = single_context("ep:gold-4", GOLD_TEXTS["ep:gold-4"])
        claim = asserted(DeterministicExtractor().extract(ctx))[0]
        assert claim.epistemic_status_hint == "RUMORED"
        assert claim.review_required is True
        assert "se dice que" in claim.epistemic_cues

    def test_mencion_por_patron_de_titulo_del_perfil(self):
        ctx, _ = single_context(
            "ep:title", "El maestre Aldric guarda el archivo.", profile=make_profile()
        )
        out = DeterministicExtractor().extract(ctx)
        aldric = [m for m in out.mentions if m.surface == "Aldric"]
        assert aldric and aldric[0].best_type() == "Character"
        assert aldric[0].metadata["match_origin"] == "title_pattern"

    def test_alias_enlaza_con_la_mencion_canonica_del_episodio(self):
        ctx, _ = single_context(
            "ep:alias", "La Orden del Alba crecio. La Orden reclutaba en Valdor."
        )
        out = DeterministicExtractor().extract(ctx)
        canonical = [m for m in out.mentions if m.surface == "Orden del Alba"][0]
        alias = [m for m in out.mentions if m.surface == "la Orden"][0]
        assert alias.coreference_candidates == [canonical.mention_id]
        assert alias.metadata["alias_match"] is True

    def test_predicado_fuera_del_perfil_se_abstiene(self):
        profile = make_profile(
            predicates=[{"predicate": "LIVES_IN", "domain": ["Character"], "range": ["Location"]}]
        )
        ctx, _ = single_context("ep:gold-1", GOLD_TEXTS["ep:gold-1"], profile=profile)
        out = DeterministicExtractor().extract(ctx)
        reasons = [r for c in out.claims if c.abstained for r in c.metadata["abstention_reasons"]]
        assert "PREDICATE_NOT_IN_PROFILE" in reasons
        assert {c.best_predicate() for c in asserted(out)} == {"LIVES_IN"}

    def test_tipos_incompatibles_con_el_perfil_se_abstienen(self):
        profile = make_profile(
            predicates=[{"predicate": "LIVES_IN", "domain": ["Character"], "range": ["Faction"]}]
        )
        ctx, _ = single_context("ep:types", "Kael vive en Valdor.", profile=profile)
        out = DeterministicExtractor().extract(ctx)
        assert asserted(out) == []
        reasons = [r for c in out.claims for r in c.metadata["abstention_reasons"]]
        assert "TYPE_INCOMPATIBLE_WITH_PROFILE" in reasons

    def test_episodio_de_baja_calidad_obliga_a_revision(self):
        ctx, _ = single_context(
            "ep:lowq", "Kael vive en Valdor.", quality={"score": 0.2, "flags": ["LOW_OCR"]}
        )
        claim = asserted(DeterministicExtractor().extract(ctx))[0]
        assert claim.review_required is True

    def test_mencion_sin_fragmento_que_la_cubra_no_se_emite(self):
        episode = make_episode("ep:partial", text="Kael vive en Valdor.")
        frag = make_fragment(episode, "frag:partial", "Kael vive", 0)
        ctx = ExtractionContext(WORKSPACE, [episode], [frag], lexicon=GOLD_LEXICON)
        out = DeterministicExtractor().extract(ctx)
        assert [m.surface for m in out.mentions] == ["Kael"]
        assert "MENTION_WITHOUT_EVIDENCE" in out.codes()


# ==========================================================================
# 5. Anti-alucinacion (payload de modelo)
# ==========================================================================
class TestAntiHallucination:
    def _ctx(self):
        return single_context("ep:llm", "Kael vive en Valdor desde hace anos.")

    def test_mencion_que_no_existe_en_el_texto_se_descarta(self):
        ctx, episode = self._ctx()
        payload = {
            "mentions": [
                {"surface": "Kael", "type": "Character", "confidence": 0.9},
                {"surface": "Zarquon el Terrible", "type": "Character", "confidence": 0.95},
            ],
            "claims": [],
        }
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert [m.surface for m in out.mentions] == ["Kael"]
        assert "HALLUCINATED_MENTION" in out.codes()

    def test_cita_inventada_tumba_la_propuesta(self):
        ctx, episode = self._ctx()
        payload = {
            "mentions": [
                {"surface": "Kael", "type": "Character", "quote": "Kael gobierna el mundo"}
            ],
            "claims": [],
        }
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert out.mentions == []
        assert "HALLUCINATED_QUOTE" in out.codes()

    def test_fragment_id_inventado_se_reancla_por_contenido(self):
        ctx, episode = self._ctx()
        payload = {
            "mentions": [
                {"surface": "Valdor", "type": "Location", "fragment_id": "frag:que-no-existe"}
            ],
            "claims": [],
        }
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert len(out.mentions) == 1
        mention = out.mentions[0]
        assert mention.evidence_fragment_ids == ["frag:ep:llm:0"]
        assert "FRAGMENT_ID_NOT_FOUND" in mention.metadata["anchor_reason_codes"]
        assert episode.text[mention.start:mention.end] == "Valdor"

    def test_claim_con_sujeto_no_anclado_no_se_emite(self):
        ctx, episode = self._ctx()
        payload = {
            "mentions": [{"surface": "Valdor", "type": "Location"}],
            "claims": [
                {
                    "subject": "Zarquon",
                    "object": "Valdor",
                    "predicate": "RULES",
                    "relation": "gobierna",
                    "quote": "Kael vive en Valdor",
                }
            ],
        }
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert out.claims == []
        assert "SUBJECT_NOT_GROUNDED" in out.codes()

    def test_los_offsets_del_modelo_se_ignoran(self):
        ctx, episode = self._ctx()
        payload = {
            "mentions": [
                {"surface": "Valdor", "type": "Location", "start": 999, "end": 1500}
            ],
            "claims": [],
        }
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        mention = out.mentions[0]
        assert (mention.start, mention.end) == (
            episode.text.index("Valdor"),
            episode.text.index("Valdor") + len("Valdor"),
        )

    def test_tipo_fuera_del_catalogo_no_se_acepta(self):
        ctx, episode = self._ctx()
        payload = {"mentions": [{"surface": "Kael", "type": "Deity"}], "claims": []}
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert out.mentions[0].type_candidates == []
        assert "UNKNOWN_ENTITY_TYPE" in out.codes()

    def test_predicado_no_normalizable_se_convierte_en_abstencion(self):
        ctx, episode = self._ctx()
        payload = {
            "mentions": [
                {"surface": "Kael", "type": "Character"},
                {"surface": "Valdor", "type": "Location"},
            ],
            "claims": [
                {"subject": "Kael", "object": "Valdor", "predicate": "?!", "relation": "vive en"}
            ],
        }
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert out.claims[0].abstained is True
        assert "PREDICATE_NOT_NORMALIZABLE" in out.claims[0].metadata["abstention_reasons"]

    def test_la_confianza_del_modelo_esta_limitada(self):
        ctx, episode = self._ctx()
        payload = {
            "mentions": [
                {"surface": "Kael", "type": "Character", "confidence": 1.0},
                {"surface": "Valdor", "type": "Location", "confidence": 1.0},
            ],
            "claims": [
                {
                    "subject": "Kael", "object": "Valdor", "predicate": "LIVES_IN",
                    "relation": "vive en", "confidence": 1.0,
                }
            ],
        }
        out = normalize_payload(
            payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO, confidence_cap=0.7
        )
        assert all(m.confidence <= 0.7 for m in out.mentions)
        assert out.claims[0].confidence <= 0.7
        assert out.claims[0].review_required is True

    def test_payload_que_no_es_un_objeto(self):
        ctx, episode = self._ctx()
        out = normalize_payload(["nope"], ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert "MODEL_PAYLOAD_MALFORMED" in out.codes()

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("vive en", "VIVE_EN"),
            ("  member-of ", "MEMBER_OF"),
            ("MEMBER_OF", "MEMBER_OF"),
            ("123", None),
            ("", None),
            (None, None),
        ],
    )
    def test_normalizacion_de_predicado(self, raw, expected):
        assert normalize_predicate(raw) == expected


# ==========================================================================
# 6. Temporal
# ==========================================================================
class TestTemporal:
    def test_expresion_con_calendario_del_perfil(self):
        ctx, _ = single_context("ep:gold-5", GOLD_TEXTS["ep:gold-5"], profile=make_profile())
        claim = asserted(DeterministicExtractor().extract(ctx))[0]
        assert claim.best_predicate() == "FOUNDED"
        expr = claim.temporal_expressions[0]
        assert expr["calendar_id"] == "era-tercera"
        assert expr["kind"] == "POINT"
        assert "valid_from" not in expr  # un ano de mundo de juego NO es una fecha UTC

    def test_sin_perfil_no_hay_calendario(self):
        ctx, _ = single_context("ep:gold-5", GOLD_TEXTS["ep:gold-5"])
        claim = asserted(DeterministicExtractor().extract(ctx))[0]
        assert claim.temporal_expressions[0].get("calendar_id") is None

    def test_fecha_iso_real_si_se_traduce_a_utc(self):
        ctx, episode = single_context("ep:iso", "El pacto se firmo el 2026-07-27 en Valdor.")
        out = TemporalExtractor().extract(ctx)
        expr = out.claims[0].temporal_expressions[0]
        assert expr["valid_from"] == "2026-07-27T00:00:00Z"

    def test_intervalos_y_duraciones(self):
        ctx, episode = single_context(
            "ep:temp", "Reino desde el año 200 hasta el año 300. Duro durante 100 años."
        )
        out = TemporalExtractor().extract(ctx)
        kinds = {e["kind"] for e in out.claims[0].temporal_expressions}
        assert {"INTERVAL", "DURATION"} <= kinds

    def test_las_expresiones_sueltas_salen_como_abstencion(self):
        ctx, _ = single_context("ep:temp2", "Todo ocurrio ayer.")
        out = TemporalExtractor().extract(ctx)
        assert out.claims[0].abstained is True
        assert out.claims[0].confidence == 0.0
        assert out.claims[0].temporal_expressions[0]["fragment_id"] == "frag:ep:temp2:0"


# ==========================================================================
# 7. Correferencia
# ==========================================================================
class TestCoreference:
    def test_pronombre_enlaza_con_el_antecedente_tipado_mas_cercano(self):
        ctx, _ = single_context("ep:coref", "Kael entro en Valdor. Él vive en Valdor.")
        prior = DeterministicExtractor().extract(ctx)
        out = CoreferenceExtractor().extract(ctx, prior=prior)
        pronoun = [m for m in out.mentions if m.surface.lower() == "él"][0]
        kael = [m for m in prior.mentions if m.surface == "Kael"][0]
        assert pronoun.coreference_candidates == [kael.mention_id]
        assert pronoun.type_candidates == []  # un pronombre no aporta tipo

    def test_el_articulo_el_no_se_confunde_con_el_pronombre(self):
        ctx, _ = single_context("ep:art", "Kael cruzo el rio y el bosque de Valdor.")
        prior = DeterministicExtractor().extract(ctx)
        out = CoreferenceExtractor().extract(ctx, prior=prior)
        assert out.mentions == []

    def test_primera_persona_usa_el_speaker(self):
        ctx, _ = single_context(
            "ep:speaker",
            "Kael hablo. Yo vivo en Valdor.",
            modality="SPEAKER_TURN",
            speaker={"speaker_id": "spk:1", "label": "Kael", "confidence": 0.9},
            turn=1,
        )
        prior = DeterministicExtractor().extract(ctx)
        out = CoreferenceExtractor().extract(ctx, prior=prior)
        yo = [m for m in out.mentions if m.surface == "Yo"][0]
        kael = [m for m in prior.mentions if m.surface == "Kael"][0]
        assert yo.coreference_candidates == [kael.mention_id]
        assert yo.metadata["coreference_kind"] == "SPEAKER"

    def test_primera_persona_sin_speaker_no_se_resuelve(self):
        ctx, _ = single_context("ep:nospk", "Kael hablo. Yo vivo en Valdor.")
        prior = DeterministicExtractor().extract(ctx)
        out = CoreferenceExtractor().extract(ctx, prior=prior)
        assert out.mentions == []
        assert "FIRST_PERSON_WITHOUT_SPEAKER" in out.codes()

    def test_sin_menciones_previas_no_resuelve_nada(self):
        ctx, _ = single_context("ep:solo", "Él vive alli.")
        out = CoreferenceExtractor().extract(ctx, prior=ExtractionOutput())
        assert out.mentions == []
        assert "COREFERENCE_WITHOUT_MENTIONS" in out.codes()

    def test_pronombre_sin_antecedente_no_inventa_uno(self):
        ctx, _ = single_context("ep:noante", "Él vive en Valdor.")
        prior = DeterministicExtractor().extract(ctx)
        out = CoreferenceExtractor().extract(ctx, prior=prior)
        assert out.mentions == []
        assert "PRONOUN_WITHOUT_ANTECEDENT" in out.codes()


# ==========================================================================
# 8. Tablas
# ==========================================================================
def table_context(header, rows, *, profile=None, quality=None):
    literal_rows = [" | ".join(str(c or "") for c in row) for row in rows]
    episode = make_episode(
        "ep:table",
        text=None,
        modality="TABLE",
        table={"header": list(header), "rows": [list(r) for r in rows]},
        quality=quality or {"score": 0.95, "flags": []},
    )
    fragments = [
        make_fragment(episode, f"frag:row:{i}", literal, i * 100, media_type="TABLE")
        for i, literal in enumerate(literal_rows)
    ]
    ctx = ExtractionContext(WORKSPACE, [episode], fragments, profile=profile)
    return ctx, episode


class TestTable:
    def test_claims_desde_la_estructura_fila_columna(self):
        ctx, _ = table_context(
            ["Nombre", "Faccion", "Ubicacion"],
            [["Elara", "Orden del Alba", "Valdor"], ["Kael", "Orden del Alba", "Nara"]],
        )
        out = TableExtractor().extract(ctx)
        triples = {(*surfaces_of(out, c),) for c in asserted(out)}
        assert ("Elara", "MEMBER_OF", "Orden del Alba") in triples
        assert ("Kael", "LOCATED_IN", "Nara") in triples
        assert all(c.metadata["structured_source"] for c in asserted(out))

    def test_direccion_explicita_de_la_columna_lider(self):
        ctx, _ = table_context(["Nombre", "Lider"], [["Orden del Alba", "Elara"]])
        claim = asserted(TableExtractor().extract(ctx))[0]
        assert claim.best_predicate() == "LEADS"
        assert claim.best_direction() == "OBJECT_TO_SUBJECT"

    def test_celda_multivalor_se_abstiene(self):
        ctx, _ = table_context(["Nombre", "Aliado"], [["Elara", "Kael, Aldric"]])
        out = TableExtractor().extract(ctx)
        assert asserted(out) == []
        assert "TABLE_MULTIVALUE_CELL" in out.claims[0].metadata["abstention_reasons"]

    def test_columna_no_mapeada_no_inventa_predicado(self):
        ctx, _ = table_context(["Nombre", "Color favorito"], [["Elara", "azul"]])
        out = TableExtractor().extract(ctx)
        assert asserted(out) == []
        assert "TABLE_COLUMN_NOT_MAPPED" in out.codes()

    def test_celda_sin_evidencia_no_produce_mencion(self):
        episode = make_episode(
            "ep:table",
            text=None,
            modality="TABLE",
            table={"header": ["Nombre", "Faccion"], "rows": [["Elara", "Orden del Alba"]]},
        )
        frag = make_fragment(episode, "frag:row:0", "Elara | (ilegible)", 0, media_type="TABLE")
        ctx = ExtractionContext(WORKSPACE, [episode], [frag])
        out = TableExtractor().extract(ctx)
        assert asserted(out) == []
        assert "TABLE_CELL_WITHOUT_EVIDENCE" in out.codes()

    def test_offsets_declaran_su_base(self):
        ctx, _ = table_context(["Nombre", "Faccion"], [["Elara", "Orden del Alba"]])
        out = TableExtractor().extract(ctx)
        assert all(m.metadata["offset_basis"] == "fragment" for m in out.mentions)
        assert all("offset_fragment_id" in m.metadata for m in out.mentions)

    def test_tabla_sin_encabezado_no_afirma_nada(self):
        episode = make_episode(
            "ep:table", text=None, modality="TABLE", table={"rows": [["Elara", "Valdor"]]}
        )
        frag = make_fragment(episode, "frag:row:0", "Elara | Valdor", 0, media_type="TABLE")
        ctx = ExtractionContext(WORKSPACE, [episode], [frag])
        out = TableExtractor().extract(ctx)
        assert out.claims == []
        assert "TABLE_WITHOUT_HEADER" in out.codes()


# ==========================================================================
# 9. Externo y visual
# ==========================================================================
class _FakePort:
    """Doble del subsistema de proveedores. NO es transporte: no sale de proceso."""

    def __init__(self, payload, name="proveedor.externo", model="modelo-x"):
        self.payload = payload
        self.name = name
        self.model = model
        self.requests = []

    def propose(self, request):
        self.requests.append(request)
        return ExternalExtractionResponse(
            payload=self.payload,
            provider_name=self.name,
            provider_version="1.0.0",
            model=self.model,
        )

    describe = propose


class TestExternalAndVisual:
    def test_sin_puerto_no_hay_propuestas_pero_si_diagnostico(self):
        ctx, _ = single_context("ep:ext", "Kael vive en Valdor.")
        extractor = ExternalExtractor()
        out = extractor.extract(ctx)
        assert extractor.bound is False
        assert (out.mentions, out.claims) == ([], [])
        assert "EXTERNAL_PROVIDER_NOT_BOUND" in out.codes()

    def test_las_propuestas_externas_se_trazan_como_externas(self):
        ctx, _ = single_context("ep:ext", "Kael vive en Valdor.")
        port = _FakePort(
            {
                "mentions": [
                    {"surface": "Kael", "type": "Character"},
                    {"surface": "Valdor", "type": "Location"},
                ],
                "claims": [
                    {
                        "subject": "Kael", "object": "Valdor", "predicate": "LIVES_IN",
                        "relation": "vive en", "confidence": 0.99,
                    }
                ],
            }
        )
        out = ExternalExtractor(port).extract(ctx)
        claim = out.claims[0]
        assert claim.producing_provider()["provider"] == "external"
        assert claim.producing_provider()["name"] == "proveedor.externo"
        assert claim.confidence <= 0.6  # tope externo, mas bajo que el de Ollama
        assert claim.review_required is True

    def test_el_externo_pasa_por_el_mismo_filtro_anti_alucinacion(self):
        ctx, _ = single_context("ep:ext", "Kael vive en Valdor.")
        port = _FakePort({"mentions": [{"surface": "Nadie", "type": "Character"}], "claims": []})
        out = ExternalExtractor(port).extract(ctx)
        assert out.mentions == []
        assert "HALLUCINATED_MENTION" in out.codes()

    def test_la_peticion_externa_no_lleva_secretos_ni_rutas(self):
        ctx, _ = single_context("ep:ext", "Kael vive en Valdor.")
        port = _FakePort({"mentions": [], "claims": []})
        ExternalExtractor(port).extract(ctx)
        request = port.requests[0]
        assert request.workspace == WORKSPACE
        assert request.fragments[0][0] == "frag:ep:ext:0"
        assert not hasattr(request, "credentials")

    def test_puerto_que_falla_no_tumba_la_extraccion(self):
        class _Boom:
            def propose(self, request):
                raise RuntimeError("token=secreto")

        ctx, _ = single_context("ep:ext", "Kael vive en Valdor.")
        out = ExternalExtractor(_Boom()).extract(ctx)
        assert "EXTERNAL_PROVIDER_FAILED" in out.codes()
        assert all("secreto" not in d.detail for d in out.diagnostics)

    def test_visual_sin_proveedor_es_un_stub_honesto(self):
        episode = make_episode("ep:img", text=None, modality="IMAGE")
        frag = make_fragment(episode, "frag:img", "mapa de Valdor", 0, media_type="MAP",
                             bbox={"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5})
        ctx = ExtractionContext(WORKSPACE, [episode], [frag])
        out = VisualExtractor().extract(ctx)
        assert (out.mentions, out.claims) == ([], [])
        assert "VISION_PROVIDER_NOT_AVAILABLE" in out.codes()

    def test_lo_visual_nace_pidiendo_revision(self):
        episode = make_episode("ep:img", text=None, modality="DIAGRAM")
        frag = make_fragment(episode, "frag:img", "Kael y Valdor unidos por una linea", 0,
                             media_type="DIAGRAM",
                             bbox={"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0})
        ctx = ExtractionContext(WORKSPACE, [episode], [frag])
        port = _FakePort(
            {
                "mentions": [
                    {"surface": "Kael", "type": "Character"},
                    {"surface": "Valdor", "type": "Location"},
                ],
                "claims": [
                    {
                        "subject": "Kael", "object": "Valdor", "predicate": "LIVES_IN",
                        "relation": "linea", "epistemic": "ASSERTED", "confidence": 0.9,
                        "quote": "Kael y Valdor unidos por una linea",
                    }
                ],
            }
        )
        claim = [c for c in VisualExtractor(port).extract(ctx).claims if not c.abstained][0]
        assert claim.epistemic_status_hint == "VISUAL_INFERRED"
        assert claim.review_required is True
        assert claim.confidence <= 0.5


# ==========================================================================
# 10. Pipeline
# ==========================================================================
class TestPipeline:
    def test_el_pipeline_local_no_toca_la_red(self, monkeypatch):
        import urllib.request

        def _boom(*args, **kwargs):
            raise AssertionError("el pipeline local no puede abrir sockets")

        monkeypatch.setattr(urllib.request, "urlopen", _boom)
        out = ExtractionPipeline.local_default().run(gold_context())
        assert out.claims

    def test_la_correferencia_ve_las_menciones_de_los_pasos_previos(self):
        episodes, fragments = [], []
        episode, frags = text_episode("ep:pipe", "Kael entro en Valdor. Él vive en Valdor.")
        episodes.append(episode)
        fragments.extend(frags)
        ctx = ExtractionContext(WORKSPACE, episodes, fragments, lexicon=GOLD_LEXICON)
        out = ExtractionPipeline.local_default().run(ctx)
        pronombres = [m for m in out.mentions if m.metadata.get("pronoun")]
        assert len(pronombres) == 1
        assert pronombres[0].coreference_candidates

    def test_episodio_sin_fragmentos_se_salta_con_diagnostico(self):
        episode = make_episode("ep:huerfano", text="Kael vive en Valdor.")
        ctx = ExtractionContext(WORKSPACE, [episode], [], lexicon=GOLD_LEXICON)
        out = ExtractionPipeline.local_default().run(ctx)
        assert (out.mentions, out.claims) == ([], [])
        assert "EPISODE_WITHOUT_EVIDENCE" in out.codes()

    def test_la_salida_nunca_es_un_grafo(self):
        out = ExtractionPipeline.local_default().run(gold_context())
        for doc in [*out.mentions, *out.claims]:
            assert doc.CONTRACT_ID in (
                "entity-mention/v3-internal-v1",
                "claim-proposal/v3-internal-v1",
            )


# ==========================================================================
# 11. Mutaciones: si al romper la regla la suite sigue verde, no servia
# ==========================================================================
class TestMutations:
    def test_la_coordinacion_del_sujeto_esta_protegida_por_dos_guardas(self, monkeypatch):
        """Romper solo la coordinacion NO basta: queda la de sujetos multiples.

        Es defensa en profundidad deliberada. El mutante que relajaba una sola
        de las dos sobrevivia a la suite anterior.
        """
        ctx, _ = single_context("ep:gold-2", GOLD_TEXTS["ep:gold-2"])
        monkeypatch.setattr(det_mod, "COORDINATION_TOKENS", frozenset())
        monkeypatch.setattr(det_mod, "COORDINATION_PHRASES", ())
        out = DeterministicExtractor().extract(ctx)
        assert asserted(out) == []
        reasons = [r for c in out.claims for r in c.metadata["abstention_reasons"]]
        assert "MULTIPLE_SUBJECT_CANDIDATES" in reasons

    def test_mutar_la_guarda_de_coordinacion_deja_pasar_un_falso_positivo(self, monkeypatch):
        # Objeto coordinado con UN solo sujeto: aqui la unica guarda es la de
        # coordinacion, y al quitarla el falso positivo entra.
        lexicon = Lexicon(
            [*GOLD_LEXICON.entries, LexiconEntry("Nara", "Location", (), 0.9, "glossary")]
        )
        ctx, _ = single_context("ep:coord-obj", "Kael vive en Valdor y Nara.", lexicon=lexicon)
        assert asserted(DeterministicExtractor().extract(ctx)) == []
        monkeypatch.setattr(det_mod, "COORDINATION_TOKENS", frozenset())
        monkeypatch.setattr(det_mod, "COORDINATION_PHRASES", ())
        out = DeterministicExtractor().extract(ctx)
        assert asserted(out), "sin la guarda de coordinacion el extractor afirma de mas"

    def test_mutar_las_marcas_de_negacion_pierde_la_negacion(self, monkeypatch):
        ctx, _ = single_context("ep:gold-3", GOLD_TEXTS["ep:gold-3"])
        monkeypatch.setattr(det_mod, "NEGATION_CUES", ())
        claim = asserted(DeterministicExtractor().extract(ctx))[0]
        assert claim.negated is False

    def test_mutar_las_marcas_epistemicas_convierte_un_rumor_en_afirmacion(self, monkeypatch):
        ctx, _ = single_context("ep:gold-4", GOLD_TEXTS["ep:gold-4"])
        monkeypatch.setattr(det_mod, "EPISTEMIC_CUES", ())
        claim = asserted(DeterministicExtractor().extract(ctx))[0]
        assert claim.epistemic_status_hint == "ASSERTED"

    def test_mutar_la_verificacion_de_citas_deja_entrar_alucinaciones(self, monkeypatch):
        ctx, episode = single_context("ep:llm", "Kael vive en Valdor.")
        monkeypatch.setattr(EvidenceIndex, "contains_quote", lambda self, fid, quote: True)
        monkeypatch.setattr(
            EvidenceIndex, "_locate", lambda self, quote, fid: (0, 4, "episode")
        )
        payload = {"mentions": [{"surface": "Zarquon", "type": "Character"}], "claims": []}
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert out.mentions, "sin verificacion de citas, una entidad inventada entra en el sistema"

    def test_mutar_la_distancia_maxima_del_pronombre(self, monkeypatch):
        ctx, _ = single_context(
            "ep:far",
            "Kael entro en la sala. " + "Todo estaba en silencio y en calma absoluta. " * 3
            + "Él vive en Valdor.",
        )
        prior = DeterministicExtractor().extract(ctx)
        assert CoreferenceExtractor(max_distance=3).extract(ctx, prior=prior).mentions == []
        assert CoreferenceExtractor(max_distance=200).extract(ctx, prior=prior).mentions


# ==========================================================================
# 12. Hallazgos de la revision independiente (B1-B6, A1-A4)
#
# Cada test de esta seccion reproduce un caso que ANTES pasaba el filtro. Son
# la deuda de una revision que demostro que una propuesta puede estar anclada a
# evidencia que no dice lo que la propuesta afirma.
# ==========================================================================
class TestQuoteIsMandatory:
    """B1 — un claim de modelo sin cita no puede afirmarse."""

    def test_claim_sin_cita_se_abstiene(self):
        ctx, episode = single_context("ep:llm", "Kael vive en Valdor y la Orden del Alba crecio.")
        payload = {
            "mentions": [
                {"surface": "Kael", "type": "Character", "quote": "Kael vive en Valdor"},
                {"surface": "Orden del Alba", "type": "Faction",
                 "quote": "la Orden del Alba crecio"},
            ],
            # SERVES no aparece por ningun lado del texto: el modelo lo invento
            # sobre dos menciones que si existen.
            "claims": [
                {"subject": "Kael", "object": "Orden del Alba", "predicate": "SERVES",
                 "relation": "sirve a", "confidence": 0.9}
            ],
        }
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert asserted(out) == []
        claim = out.claims[0]
        assert claim.abstained is True
        assert claim.confidence == 0.0
        assert "CLAIM_WITHOUT_QUOTE" in claim.metadata["abstention_reasons"]

    def test_dos_menciones_ancladas_no_sostienen_la_relacion_entre_ellas(self):
        ctx, episode = single_context("ep:llm", "Kael vive en Valdor.")
        payload = {
            "mentions": [
                {"surface": "Kael", "type": "Character"},
                {"surface": "Valdor", "type": "Location"},
            ],
            "claims": [
                {"subject": "Kael", "object": "Valdor", "predicate": "RULES",
                 "relation": "gobierna", "confidence": 0.99}
            ],
        }
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert asserted(out) == []


class TestQuoteInContext:
    """B2 — la cita se verifica EN CONTEXTO, no solo su existencia."""

    def test_cita_parcial_que_invierte_el_sentido_se_abstiene(self):
        ctx, episode = single_context("ep:neg", "Kael no sirve a la Orden del Alba.")
        payload = {
            "mentions": [
                {"surface": "Kael", "type": "Character"},
                {"surface": "Orden del Alba", "type": "Faction"},
            ],
            "claims": [
                {"subject": "Kael", "object": "Orden del Alba", "predicate": "SERVES",
                 "relation": "sirve a", "negated": False, "confidence": 0.9,
                 "quote": "sirve a la Orden del Alba"}
            ],
        }
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert asserted(out) == []
        assert "NEGATION_CONTEXT_MISMATCH" in out.claims[0].metadata["abstention_reasons"]

    def test_si_el_modelo_declara_la_negacion_el_claim_sigue_vivo(self):
        ctx, episode = single_context("ep:neg", "Kael no sirve a la Orden del Alba.")
        payload = {
            "mentions": [
                {"surface": "Kael", "type": "Character"},
                {"surface": "Orden del Alba", "type": "Faction"},
            ],
            "claims": [
                {"subject": "Kael", "object": "Orden del Alba", "predicate": "SERVES",
                 "relation": "sirve a", "negated": True, "confidence": 0.9,
                 "quote": "sirve a la Orden del Alba"}
            ],
        }
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        claim = asserted(out)[0]
        assert claim.negated is True and claim.review_required is True

    def test_contexto_no_factivo_tumba_el_claim_del_modelo(self):
        ctx, episode = single_context("ep:nf", "Es falso que Kael sirva a la Orden del Alba.")
        payload = {
            "mentions": [
                {"surface": "Kael", "type": "Character"},
                {"surface": "Orden del Alba", "type": "Faction"},
            ],
            "claims": [
                {"subject": "Kael", "object": "Orden del Alba", "predicate": "SERVES",
                 "relation": "sirve", "confidence": 0.9,
                 "quote": "Kael sirva a la Orden del Alba"}
            ],
        }
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert asserted(out) == []
        assert "NON_FACTIVE_CONTEXT" in out.claims[0].metadata["abstention_reasons"]

    def test_el_contexto_manda_sobre_la_pista_del_modelo(self):
        ctx, episode = single_context("ep:rum", "Se dice que Kael vive en Valdor.")
        payload = {
            "mentions": [
                {"surface": "Kael", "type": "Character"},
                {"surface": "Valdor", "type": "Location"},
            ],
            "claims": [
                {"subject": "Kael", "object": "Valdor", "predicate": "LIVES_IN",
                 "relation": "vive en", "epistemic": "ASSERTED", "confidence": 0.9,
                 "quote": "Kael vive en Valdor"}
            ],
        }
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert asserted(out)[0].epistemic_status_hint == "RUMORED"


class TestAmbiguousAnchorBlocks:
    """B3 — `AMBIGUOUS_ANCHOR` no es decorativo: bloquea la afirmacion."""

    def _ctx_dos_fragmentos(self):
        text = "Kael sirve a la Orden. Kael no sirve a la Orden."
        episode = make_episode("ep:amb2", text=text)
        f1 = make_fragment(episode, "frag:si", "Kael sirve a la Orden.", 0)
        f2 = make_fragment(episode, "frag:no", "Kael no sirve a la Orden.", 22)
        ctx = ExtractionContext(WORKSPACE, [episode], [f1, f2], lexicon=GOLD_LEXICON)
        return ctx, episode

    def test_cita_presente_en_dos_fragmentos_se_abstiene(self):
        ctx, episode = self._ctx_dos_fragmentos()
        payload = {
            "mentions": [
                {"surface": "Kael", "type": "Character"},
                {"surface": "la Orden", "type": "Faction"},
            ],
            "claims": [
                {"subject": "Kael", "object": "la Orden", "predicate": "SERVES",
                 "relation": "sirve a", "confidence": 0.9, "quote": "sirve a la Orden"}
            ],
        }
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert asserted(out) == []
        reasons = out.claims[0].metadata["abstention_reasons"]
        assert "AMBIGUOUS_ANCHOR" in reasons

    def test_el_reanclaje_no_puede_elegir_el_fragmento_negado_en_silencio(self):
        ctx, episode = self._ctx_dos_fragmentos()
        index = ctx.index_of(episode)
        anchor = index.anchor_quote("sirve a la Orden", "frag:inventado")
        assert anchor is not None and anchor.ambiguous


class TestNonFactiveDeterministic:
    """B4 — los seis contextos no factivos del revisor, en el determinista."""

    @pytest.mark.parametrize(
        "texto",
        [
            "Si Kael vive en Valdor, la Orden lo sabra.",
            "¿Kael vive en Valdor?",
            "Es falso que Kael vive en Valdor.",
            "Nadie cree que Kael vive en Valdor.",
            "El cronista afirmo falsamente que Kael vive en Valdor.",
            "Nada cambia salvo que Kael vive en Valdor.",
        ],
    )
    def test_ningun_contexto_no_factivo_produce_una_afirmacion_plana(self, texto):
        ctx, _ = single_context("ep:nf", texto)
        out = DeterministicExtractor().extract(ctx)
        for claim in asserted(out):
            assert claim.epistemic_status_hint != "ASSERTED", texto
            assert claim.review_required is True, texto

    def test_la_falsedad_y_la_pregunta_se_abstienen(self):
        for texto in ("Es falso que Kael vive en Valdor.", "¿Kael vive en Valdor?"):
            ctx, _ = single_context("ep:nf", texto)
            out = DeterministicExtractor().extract(ctx)
            assert asserted(out) == [], texto
            reasons = [r for c in out.claims for r in c.metadata["abstention_reasons"]]
            assert "NON_FACTIVE_CONTEXT" in reasons, texto

    def test_el_condicional_sale_como_hipotesis(self):
        ctx, _ = single_context("ep:cond", "Si Kael vive en Valdor, la Orden lo sabra.")
        claims = asserted(DeterministicExtractor().extract(ctx))
        assert claims
        assert claims[0].epistemic_status_hint == "HYPOTHETICAL"
        assert claims[0].review_required is True


class TestCoordinationAndModifiers:
    """B5 — coordinacion no adyacente, disyunciones y sujeto-modificador."""

    def _lex(self):
        return Lexicon(
            [
                *GOLD_LEXICON.entries,
                LexiconEntry("Mira", "Character", (), 0.9, "glossary"),
                LexiconEntry("Nara", "Location", (), 0.9, "glossary"),
                LexiconEntry("Aldric", "Character", (), 0.9, "glossary"),
            ]
        )

    @pytest.mark.parametrize(
        "texto",
        [
            "Kael y tambien Mira viven en Valdor.",
            "Kael, asi como Mira, vive en Valdor.",
            "Ni siquiera Kael vive en Valdor.",
            "Mira junto a Kael vive en Valdor.",
            "Kael o Mira vive en Valdor.",
            "El hermano de Kael vive en Valdor.",
            "La espada de Kael se encuentra en Valdor.",
            "Segun Kael, Mira vive en Nara.",
        ],
    )
    def test_la_lectura_ambigua_no_produce_afirmacion(self, texto):
        ctx, _ = single_context("ep:coord", texto, lexicon=self._lex())
        out = DeterministicExtractor().extract(ctx)
        emitidos = {surfaces_of(out, c) for c in asserted(out)}
        # Lo que NO puede pasar es afirmar de un sujeto elegido por proximidad.
        for subject, _predicate, _obj in emitidos:
            assert subject != "Kael" or "hermano" not in texto, texto
        assert not emitidos or all(c.review_required for c in asserted(out)), texto

    def test_el_sujeto_modificador_se_detecta_y_se_abstiene(self):
        ctx, _ = single_context(
            "ep:mod", "El hermano de Kael vive en Valdor.", lexicon=self._lex()
        )
        out = DeterministicExtractor().extract(ctx)
        assert asserted(out) == []
        reasons = [r for c in out.claims for r in c.metadata["abstention_reasons"]]
        assert "SUBJECT_IS_MODIFIER" in reasons

    def test_coordinacion_con_token_intercalado(self):
        ctx, _ = single_context(
            "ep:coord2", "Kael y tambien Mira viven en Valdor.", lexicon=self._lex()
        )
        out = DeterministicExtractor().extract(ctx)
        assert asserted(out) == []
        reasons = [r for c in out.claims for r in c.metadata["abstention_reasons"]]
        assert {"COORDINATED_SUBJECT", "MULTIPLE_SUBJECT_CANDIDATES"} & set(reasons)

    def test_varias_menciones_antes_de_la_frase_son_duda(self):
        ctx, _ = single_context(
            "ep:multi", "Mira hablo con Kael que vive en Valdor.", lexicon=self._lex()
        )
        out = DeterministicExtractor().extract(ctx)
        assert asserted(out) == []
        reasons = [r for c in out.claims for r in c.metadata["abstention_reasons"]]
        assert "MULTIPLE_SUBJECT_CANDIDATES" in reasons


class TestSurvivingMutants:
    """B6 — los dos mutantes que sobrevivian a la suite anterior."""

    def test_m1_la_guarda_de_misma_frase_es_imprescindible(self):
        """Sujeto en una frase y relacion en la siguiente: no hay claim."""
        ctx, _ = single_context("ep:m1", "Kael descanso. Vive en Valdor.")
        out = DeterministicExtractor().extract(ctx)
        assert asserted(out) == []
        assert "RELATION_PHRASE_WITHOUT_ARGUMENTS" in out.codes()

    def test_m1_al_relajar_la_frase_entra_el_falso_positivo(self, monkeypatch):
        """Y si se relaja (todo el episodio = una frase), el claim aparece.

        Es la prueba de que la guarda sostiene algo: sin ella, `Kael descanso.
        Vive en Valdor.` produce LIVES_IN(Kael, Valdor).
        """
        from knowledge_v3.extraction.text import Sentence

        ctx, episode = single_context("ep:m1", "Kael descanso. Vive en Valdor.")
        index = ctx.index_of(episode)
        monkeypatch.setattr(
            det_mod,
            "_sentence_of",
            lambda sentences, token_index: Sentence(
                0, len(episode.text), 0, len(index.tokens) - 1
            ),
        )
        out = DeterministicExtractor().extract(ctx)
        assert asserted(out), "la guarda de misma-frase no estaba sosteniendo nada"

    def test_m2c_la_contencion_de_citas_es_exacta_no_parecida(self):
        """Una cita que se PARECE mucho no es la cita."""
        ctx, episode = single_context("ep:m2", "Kael vive en Valdor.")
        index = ctx.index_of(episode)
        fid = "frag:ep:m2:0"
        assert index.contains_quote(fid, "Kael vive en Valdor") is True
        # Las tres siguientes se PARECEN muchisimo (ratio > 0.9) y ninguna
        # aparece en el texto. Un umbral de similitud las aceptaria.
        assert index.contains_quote(fid, "Kael vive en Valdorr") is False
        assert index.contains_quote(fid, "Kael vive en Valdar") is False
        assert index.contains_quote(fid, "Kael no vive en Valdor") is False

    def test_m2c_una_cita_casi_igual_no_ancla(self):
        ctx, episode = single_context("ep:m2", "Kael vive en Valdor.")
        payload = {
            "mentions": [{"surface": "Valdorr", "type": "Location"}],
            "claims": [],
        }
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert out.mentions == []
        assert "HALLUCINATED_MENTION" in out.codes()


class TestOffsetScoping:
    """A1 — los offsets caen en el fragmento declarado, no en otro."""

    def test_los_offsets_pertenecen_al_fragmento_anclado(self):
        text = "Valdor prospera. Kael llego a Valdor."
        episode = make_episode("ep:scope", text=text)
        f1 = make_fragment(episode, "frag:uno", "Valdor prospera.", 0)
        f2 = make_fragment(episode, "frag:dos", "Kael llego a Valdor.", 17)
        ctx = ExtractionContext(WORKSPACE, [episode], [f1, f2])
        index = ctx.index_of(episode)
        anchor = index.anchor_quote("Valdor", "frag:dos")
        assert anchor.fragment_id == "frag:dos"
        assert f2.start <= anchor.start and anchor.end <= f2.end
        assert text[anchor.start:anchor.end] == "Valdor"

    def test_cita_ausente_del_fragmento_declarado_se_reancla_marcada(self):
        text = "Valdor prospera. Kael llego."
        episode = make_episode("ep:scope2", text=text)
        f1 = make_fragment(episode, "frag:uno", "Valdor prospera.", 0)
        f2 = make_fragment(episode, "frag:dos", "Kael llego.", 17)
        ctx = ExtractionContext(WORKSPACE, [episode], [f1, f2])
        anchor = ctx.index_of(episode).anchor_quote("Valdor", "frag:dos")
        assert anchor.fragment_id == "frag:uno"
        assert "QUOTE_NOT_IN_CLAIMED_FRAGMENT" in anchor.reason_codes


class TestTypeSafety:
    """A2 — basura en los tipos no tumba el lote."""

    @pytest.mark.parametrize("valor", ["alta", None, [], {}, "NaN", float("inf")])
    def test_confianza_no_numerica_no_rompe_nada(self, valor):
        ctx, episode = single_context("ep:types", "Kael vive en Valdor.")
        payload = {
            "mentions": [{"surface": "Kael", "type": "Character", "confidence": valor}],
            "claims": [],
        }
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert len(out.mentions) == 1
        assert 0.0 <= out.mentions[0].confidence <= 1.0
        assert "INVALID_CONFIDENCE" in out.codes()

    def test_un_episodio_envenenado_no_tumba_los_demas(self):
        from knowledge_v3.extraction import OllamaExtractor
        from knowledge_v3.extraction.ollama_client import OllamaClient, OllamaConfig

        bueno, frags_b = text_episode("ep:ok", "Kael vive en Valdor.")
        malo, frags_m = text_episode("ep:malo", "Elara vive en Valdor.")
        ctx = ExtractionContext(
            WORKSPACE, [bueno, malo], [*frags_b, *frags_m], lexicon=GOLD_LEXICON
        )
        respuestas = [
            json.dumps({"mentions": [{"surface": "Kael", "type": "Character"}], "claims": []}),
            json.dumps({"mentions": [{"surface": "Elara", "confidence": {"a": 1}}], "claims": []}),
        ]
        calls = {"n": 0}

        def transport(url, payload, timeout):
            item = respuestas[min(calls["n"], len(respuestas) - 1)]
            calls["n"] += 1
            return {"response": item, "model": payload["model"]}

        client = OllamaClient(
            config=OllamaConfig(url="http://x:1", model="m"), transport=transport
        )
        out = OllamaExtractor(client).extract(ctx)
        assert any(m.surface == "Kael" for m in out.mentions)


class TestCapsAndProviderHygiene:
    """A3/A4 y menores: topes, tipos de tabla e identidad del proveedor."""

    def test_el_tope_de_ollama_no_se_puede_subir(self):
        from knowledge_v3.extraction import OllamaExtractor
        from knowledge_v3.extraction.ollama_client import OllamaClient, OllamaConfig

        client = OllamaClient(
            config=OllamaConfig(url="http://x:1", model="m"),
            transport=lambda u, p, t: {"response": "{}", "model": "m"},
        )
        assert OllamaExtractor(client, confidence_cap=1.0).confidence_cap == 0.7

    def test_la_tabla_no_inventa_el_tipo_de_la_celda(self):
        ctx, _ = table_context(["Nombre", "Ubicacion"], [["Kael", "Elara"]])
        out = TableExtractor().extract(ctx)
        for mention in out.mentions:
            assert mention.type_candidates == []

    def test_la_tabla_consulta_el_perfil_y_se_abstiene_si_no_encaja(self):
        lexicon = Lexicon(list(GOLD_LEXICON.entries))
        ctx, episode = table_context(
            ["Nombre", "Ubicacion"], [["Kael", "Elara"]], profile=make_profile()
        )
        ctx.lexicon = lexicon
        out = TableExtractor().extract(ctx)
        assert asserted(out) == []
        reasons = [r for c in out.claims for r in c.metadata["abstention_reasons"]]
        assert {"TYPE_INCOMPATIBLE_WITH_PROFILE", "OBJECT_TYPE_MISMATCH"} & set(reasons)

    def test_la_tabla_con_tipos_confirmados_si_afirma(self):
        # MEMBER_OF(Character, Faction) SI encaja con el dominio/rango del
        # perfil, y los dos tipos los confirma el lexico.
        ctx, _ = table_context(
            ["Nombre", "Faccion"], [["Kael", "Orden del Alba"]], profile=make_profile()
        )
        ctx.lexicon = GOLD_LEXICON
        claim = asserted(TableExtractor().extract(ctx))[0]
        assert claim.best_predicate() == "MEMBER_OF"
        assert claim.review_required is False

    def test_un_proveedor_externo_no_puede_hacerse_pasar_por_local(self):
        from knowledge_v3.extraction.external import sanitize_provider_name

        assert sanitize_provider_name("s9k.extraction.ollama") == "external.ollama"
        assert sanitize_provider_name("prov\n\r; rm -rf") == "prov rm -rf"
        assert sanitize_provider_name("x" * 500).__len__() == 128
        assert sanitize_provider_name(None) is None

    def test_la_traza_externa_se_sanea(self):
        ctx, _ = single_context("ep:ext", "Kael vive en Valdor.")
        port = _FakePort(
            {"mentions": [{"surface": "Kael", "type": "Character"}], "claims": []},
            name="s9k.extraction.deterministic",
        )
        out = ExternalExtractor(port).extract(ctx)
        entry = out.mentions[0].to_dict()["provider_trace"][0]
        assert entry["provider"] == "external"
        assert entry["name"] == "external.deterministic"

    def test_tipos_contradictorios_para_la_misma_superficie_se_diagnostican(self):
        ctx, episode = single_context("ep:dup", "Kael vive en Valdor.")
        payload = {
            "mentions": [
                {"surface": "Kael", "type": "Character"},
                {"surface": "Kael", "type": "Location"},
            ],
            "claims": [],
        }
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert "CONFLICTING_MENTION_TYPES" in out.codes()


#: Mini-corpus TRAMPA: frases construidas para que un extractor lexico ingenuo
#: afirme algo falso. Cada entrada es `(texto, afirmaciones ACEPTABLES)`. Una
#: lista vacia significa "aqui no se puede afirmar nada".
TRAP_CORPUS: tuple[tuple[str, tuple], ...] = (
    ("Kael y tambien Mira viven en Valdor.", ()),
    ("Kael, asi como Mira, vive en Valdor.", ()),
    ("Ni siquiera Kael vive en Valdor.", (("Kael", "LIVES_IN", "Valdor"),)),  # negado
    ("Mira junto a Kael vive en Valdor.", ()),
    ("Kael o Mira vive en Valdor.", ()),
    ("El hermano de Kael vive en Valdor.", ()),
    ("La espada de Kael se encuentra en Valdor.", ()),
    ("Segun Kael, Mira vive en Nara.", (("Mira", "LIVES_IN", "Nara"),)),
    ("Si Kael vive en Valdor, la Orden lo sabra.", (("Kael", "LIVES_IN", "Valdor"),)),
    ("¿Kael vive en Valdor?", ()),
    ("Es falso que Kael vive en Valdor.", ()),
    ("Nadie cree que Kael vive en Valdor.", ()),
    ("El cronista afirmo falsamente que Kael vive en Valdor.", ()),
    ("Nada cambia salvo que Kael vive en Valdor.", (("Kael", "LIVES_IN", "Valdor"),)),
    ("Kael no vive en Valdor.", (("Kael", "LIVES_IN", "Valdor"),)),
    ("Kael vive en Valdor.", (("Kael", "LIVES_IN", "Valdor"),)),
    ("Elara pertenece a la Orden del Alba.", (("Elara", "MEMBER_OF", "Orden del Alba"),)),
)


class TestTrapCorpus:
    """El mini-corpus trampa de la revision: CERO afirmaciones equivocadas.

    Se mide precision, no cobertura: las frases donde el extractor calla o se
    abstiene son un resultado correcto. Las negadas y las hipoteticas SI pueden
    proponerse, siempre que salgan marcadas (`negated` / `epistemic_status_hint`)
    y pidiendo revision: proponer "Kael vive en Valdor, negado" es leer bien el
    texto; proponerlo como afirmacion plana es leerlo al reves.
    """

    LEXICON = Lexicon(
        [
            *GOLD_LEXICON.entries,
            LexiconEntry("Mira", "Character", (), 0.9, "glossary"),
            LexiconEntry("Nara", "Location", (), 0.9, "glossary"),
        ]
    )

    def test_ninguna_afirmacion_equivocada(self):
        errores = []
        emitidas = 0
        for i, (texto, aceptables) in enumerate(TRAP_CORPUS):
            ctx, _ = single_context(f"ep:trap-{i}", texto, lexicon=self.LEXICON)
            out = DeterministicExtractor().extract(ctx)
            for claim in asserted(out):
                emitidas += 1
                triple = surfaces_of(out, claim)
                if triple not in aceptables:
                    errores.append((texto, triple))
                elif claim.negated or claim.epistemic_status_hint != "ASSERTED":
                    if not claim.review_required:
                        errores.append((texto, "marcada pero sin review_required"))
        assert errores == [], f"afirmaciones equivocadas: {errores}"
        print(f"\n[trampa] {emitidas} afirmaciones emitidas, 0 equivocadas de {len(TRAP_CORPUS)} frases")

    def test_lo_negado_sale_marcado_no_afirmado_en_plano(self):
        ctx, _ = single_context("ep:trap-neg", "Ni siquiera Kael vive en Valdor.")
        claim = asserted(DeterministicExtractor().extract(ctx))[0]
        assert claim.negated is True
        assert claim.review_required is True


# ==========================================================================
# 13. Observaciones no bloqueantes de la revision (O1-O3)
# ==========================================================================
class TestPersonToPersonRelations:
    """O1 — el "de" que cierra el predicado no convierte al objeto en modificador.

    Sin esta excepcion, PARENT_OF / CHILD_OF / SIBLING_OF / ALLY_OF / ENEMY_OF
    quedaban INERTES: "es padre de Mira" abstenia siempre porque el objeto iba
    precedido de "de"... que era el final de la propia frase de relacion.
    """

    LEXICON = Lexicon(
        [*GOLD_LEXICON.entries, LexiconEntry("Mira", "Character", (), 0.9, "glossary")]
    )

    @pytest.mark.parametrize(
        "texto,predicado",
        [
            ("Kael es padre de Mira.", "PARENT_OF"),
            ("Elara es madre de Mira.", "PARENT_OF"),
            ("Kael es hijo de Mira.", "CHILD_OF"),
            ("Elara es hermana de Mira.", "SIBLING_OF"),
            ("Kael es aliado de Mira.", "ALLY_OF"),
            ("Kael es enemigo de Mira.", "ENEMY_OF"),
        ],
    )
    def test_las_relaciones_persona_persona_si_afirman(self, texto, predicado):
        ctx, _ = single_context("ep:pp", texto, lexicon=self.LEXICON)
        claims = asserted(DeterministicExtractor().extract(ctx))
        assert claims, f"{texto} no produjo ningun claim"
        assert claims[0].best_predicate() == predicado
        assert claims[0].negated is False

    def test_el_modificador_de_verdad_sigue_absteniendo(self):
        ctx, _ = single_context(
            "ep:mod2", "El hermano de Kael vive en Valdor.", lexicon=self.LEXICON
        )
        out = DeterministicExtractor().extract(ctx)
        assert asserted(out) == []
        reasons = [r for c in out.claims for r in c.metadata["abstention_reasons"]]
        assert "SUBJECT_IS_MODIFIER" in reasons

    def test_el_objeto_modificador_ajeno_a_la_frase_sigue_absteniendo(self):
        ctx, _ = single_context(
            "ep:mod3", "Kael vive en la casa de Mira.", lexicon=self.LEXICON
        )
        out = DeterministicExtractor().extract(ctx)
        assert asserted(out) == []
        reasons = [r for c in out.claims for r in c.metadata["abstention_reasons"]]
        assert "OBJECT_IS_MODIFIER" in reasons


class TestPayloadHygieneObservations:
    """O2/O3 — confianza mal tipada en claims y campos de texto que no son texto."""

    def _payload_base(self):
        return {
            "mentions": [
                {"surface": "Kael", "type": "Character"},
                {"surface": "Valdor", "type": "Location"},
            ],
            "claims": [
                {
                    "subject": "Kael", "object": "Valdor", "predicate": "LIVES_IN",
                    "relation": "vive en", "quote": "Kael vive en Valdor",
                }
            ],
        }

    @pytest.mark.parametrize("valor", ["alta", None, [], {"a": 1}])
    def test_o2_confianza_mal_tipada_en_un_claim_se_diagnostica(self, valor):
        ctx, episode = single_context("ep:o2", "Kael vive en Valdor.")
        payload = self._payload_base()
        payload["claims"][0]["confidence"] = valor
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert "INVALID_CONFIDENCE" in out.codes()
        claim = asserted(out)[0]
        assert claim.confidence == 0.0

    def test_o3_una_superficie_que_no_es_texto_se_rechaza(self):
        ctx, episode = single_context("ep:o3", "Kael vive en Valdor.")
        payload = {"mentions": [{"surface": ["Kael"], "type": "Character"}], "claims": []}
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert out.mentions == []
        assert "NON_TEXT_FIELD" in out.codes()
        # Lo que NO puede pasar: que la superficie acabe siendo "['Kael']".
        assert all("[" not in m.surface for m in out.mentions)

    def test_o3_un_claim_con_campos_no_textuales_se_rechaza(self):
        ctx, episode = single_context("ep:o3", "Kael vive en Valdor.")
        payload = self._payload_base()
        payload["claims"][0]["subject"] = {"nombre": "Kael"}
        out = normalize_payload(payload, ctx=ctx, episode=episode, info=DETERMINISTIC_INFO)
        assert out.claims == []
        assert "NON_TEXT_FIELD" in out.codes()

    def test_o3_los_campos_de_texto_correctos_siguen_pasando(self):
        ctx, episode = single_context("ep:o3", "Kael vive en Valdor.")
        out = normalize_payload(
            self._payload_base(), ctx=ctx, episode=episode, info=DETERMINISTIC_INFO
        )
        assert asserted(out)[0].best_predicate() == "LIVES_IN"
