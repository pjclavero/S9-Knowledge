# -*- coding: utf-8 -*-
"""Carril 10A: la asimetria de CONTRACCION en las reglas de relacion.

El defecto medido en la integracion de la tanda 9: la regla `MEMBER_OF` listaba
"es miembro de" pero NO "es miembro del". El emparejado de frases es por TOKENS
(`phrase_tokens`), asi que ('es','miembro','de') no casa jamas con
('es','miembro','del'), y el escenario multipartida moria con
`PIPELINE_STOPPED / step=engine` ("el extractor no propuso ningun claim"),
`mentions=2 ... claims=0`.

La laguna era ASIMETRICA, y eso es lo que la convierte en defecto y no en
decision de diseno: la MISMA regla ya declaraba "forma parte del",
"pertenece al", "pertenecia al" y "pertenecio al". El vocabulario ya pretendia
cubrir la contraccion; la tokenizacion la hacia inalcanzable en esa variante.

Estos tests fijan las TRES condiciones del encargo:

1. la frase del defecto produce el claim;
2. lo que ya funcionaba sigue produciendo el MISMO claim (control diferencial);
3. lo que NO debia producir claim SIGUE sin producirlo -- que es la condicion
   de aceptacion real: si cerrar la asimetria hiciera hablar al extractor donde
   antes callaba, seria una ampliacion agresiva y habria fallado aunque el
   escenario se pusiera verde.

Y un cuarto grupo fija el ALCANCE del cierre: es aditivo, no toca ninguna regla
que no declarase ya la contraccion, y no deja asimetrias residuales.
"""
from __future__ import annotations

import hashlib

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.contracts import (  # noqa: E402
    CONTRACT_VERSION,
    EvidenceFragment,
    GameProfile,
    SourceEpisode,
)
from knowledge_v3.extraction import (  # noqa: E402
    DeterministicExtractor,
    ExtractionContext,
    Lexicon,
    LexiconEntry,
)
from knowledge_v3.extraction.deterministic import (  # noqa: E402
    _CONTRACTIONS,
    _RELATION_RULES_BASE,
    RELATION_RULES,
    _close_contraction_gap,
    _contract,
)

WS = "carril10a"
ASSET = "asset:carril10a"


def _h(seed: str) -> dict:
    return {"algorithm": "sha256", "value": hashlib.sha256(seed.encode("utf-8")).hexdigest()}


def _trace(step: str = "normalize", produced=("text",)) -> list:
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


def _episode(eid: str, text: str):
    episode = SourceEpisode(
        contract_version=CONTRACT_VERSION, workspace=WS, source_asset_id=ASSET,
        source_hash=_h(ASSET), provider_trace=_trace(), produced_by_step="normalize",
        episode_id=eid, asset_id=ASSET, sequence=0, modality="TEXT", text=text,
        page=None, bbox=None, time_start=None, time_end=None,
        previous_episode_id=None, next_episode_id=None, speaker=None, turn=None,
        table=None, quality={"score": 0.95, "flags": []},
        content_hash=_h(eid + text),
    )
    episode.validate()
    fragment = EvidenceFragment(
        contract_version=CONTRACT_VERSION, workspace=WS, source_asset_id=ASSET,
        source_hash=_h(ASSET), provider_trace=_trace("fragment", ("literal_text",)),
        produced_by_step="fragment", fragment_id=f"frag:{eid}:0", episode_id=eid,
        literal_text=text, normalized_text=text.lower(), start=0, end=len(text),
        bbox=None, time_start=None, time_end=None, frame_id=None, page=None,
        media_type="EMBEDDED_TEXT", confidence=0.99,
    )
    fragment.validate()
    return episode, [fragment]


LEXICON = Lexicon(
    [
        LexiconEntry("Sela Marrec", "Character", (), 0.9, "glossary"),
        LexiconEntry("Kael", "Character", (), 0.9, "glossary"),
        LexiconEntry("Consejo de Umbra", "Faction", ("Consejo Umbra",), 0.9, "glossary"),
        LexiconEntry("Cofradia de Ambar", "Faction", (), 0.9, "glossary"),
    ]
)


@pytest.fixture(scope="module")
def profile() -> GameProfile:
    p = GameProfile(
        contract_version=CONTRACT_VERSION, workspace=WS,
        source_asset_id="profile:carril10a", source_hash=_h("profile:carril10a"),
        provider_trace=_trace("profile", ("predicates",)), produced_by_step="profile",
        profile_id="carril10a", profile_version="1.0.0", core_ontology_version="1.0.0",
        entity_types=["Character", "Location", "Faction", "Object", "Event", "Concept"],
        predicates=[
            {"predicate": "MEMBER_OF", "domain": ["Character"], "range": ["Faction"]},
            {"predicate": "LEADS", "domain": ["Character"], "range": ["Faction", "Character"]},
        ],
        aliases=[], titles=[],
        factions=["Consejo de Umbra", "Cofradia de Ambar"],
        calendars=[], identity_rules=[], ambiguous_terms=[],
        source_priorities=[], evaluation_examples=[],
    )
    p.validate()
    return p


def _asserted(text: str, profile: GameProfile) -> list[str]:
    """Predicados AFIRMADOS (no abstenciones) que el determinista propone."""
    eid = "ep:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    episode, fragments = _episode(eid, text)
    ctx = ExtractionContext(
        workspace=WS, episodes=[episode], fragments=fragments,
        profile=profile, lexicon=LEXICON,
    )
    out = DeterministicExtractor().extract(ctx)
    return [
        c.predicate_candidates[0]["predicate"]
        for c in out.claims
        if not c.abstained and c.predicate_candidates
    ]


# ==========================================================================
# 1. El defecto: la frase EXACTA del escenario A/B produce el claim
# ==========================================================================
def test_es_miembro_del_produce_member_of(profile):
    """La frase literal de `escenario_carril7.py` (fuente B-s7.md)."""
    assert _asserted("Sela Marrec es miembro del Consejo de Umbra.", profile) == ["MEMBER_OF"]


# ==========================================================================
# 2. Control diferencial: lo que ya funcionaba produce el MISMO claim
# ==========================================================================
@pytest.mark.parametrize(
    "texto",
    [
        "Sela Marrec pertenece al Consejo de Umbra.",       # control del integrador
        "Sela Marrec es miembro de la Cofradia de Ambar.",  # forma plena, ya cubierta
        "Sela Marrec forma parte del Consejo de Umbra.",    # contraccion ya declarada
        "Sela Marrec pertenecio al Consejo de Umbra.",
    ],
)
def test_lo_que_ya_funcionaba_sigue_igual(texto, profile):
    assert _asserted(texto, profile) == ["MEMBER_OF"]


# ==========================================================================
# 3. Caso negativo: cerrar la asimetria NO hace hablar al extractor
# ==========================================================================
#: Contextos en los que el extractor CALLA por sus guardas (condicional,
#: interrogativo, coordinacion ambigua, modificador). Todos llevan ahora la
#: forma contraida: antes del arreglo no se emitian porque la frase ni siquiera
#: casaba; despues del arreglo la frase SI casa, y siguen sin emitirse porque
#: las guardas hacen su trabajo. Ese es exactamente el punto del test: si el
#: cierre de la asimetria hubiese sido una ampliacion agresiva, estos casos se
#: habrian puesto a hablar.
NO_DEBEN_EMITIR = [
    "Si Sela Marrec es miembro del Consejo de Umbra, todo cambia.",
    "Es Sela Marrec miembro del Consejo de Umbra?",
    "Sela Marrec y Kael son miembros del Consejo de Umbra.",
    "El hermano de Sela Marrec es miembro del Consejo de Umbra.",
]


@pytest.mark.parametrize("texto", NO_DEBEN_EMITIR)
def test_los_casos_ambiguos_siguen_sin_producir_claim(texto, profile):
    assert _asserted(texto, profile) == []


#: La condicion negativa FUERTE, y la que de verdad acota el arreglo: la forma
#: contraida no puede comportarse mejor NI PEOR que la forma que la regla ya
#: cubria. Se comparan predicado, estatus epistemico y confianza, no solo "hay
#: claim": un cierre de asimetria que ademas subiese la confianza, o que
#: convirtiese un RUMORED en ASSERTED, seria una ampliacion encubierta.
#:
#: Es tambien lo que impide que este test mienta sobre contextos que el
#: extractor NO suprime por diseno (rumor -> RUMORED@0.6; la negacion la
#: resuelve el motor, no el extractor: `negation_policy_at_engine`). Ahi la
#: exigencia correcta no es "no emite", es "emite lo MISMO que su hermana".
PARIDAD = [
    # (contraida, ya cubierta por la regla antes del arreglo)
    ("Sela Marrec es miembro del Consejo de Umbra.",
     "Sela Marrec pertenece al Consejo de Umbra."),
    ("Se rumorea que Sela Marrec es miembro del Consejo de Umbra.",
     "Se rumorea que Sela Marrec pertenece al Consejo de Umbra."),
    ("Sela Marrec no es miembro del Consejo de Umbra.",
     "Sela Marrec no pertenece al Consejo de Umbra."),
    ("Si Sela Marrec es miembro del Consejo de Umbra, todo cambia.",
     "Si Sela Marrec pertenece al Consejo de Umbra, todo cambia."),
    ("Es Sela Marrec miembro del Consejo de Umbra?",
     "Pertenece Sela Marrec al Consejo de Umbra?"),
]


def _firma(text: str, profile: GameProfile) -> list[tuple]:
    """Predicado + estatus epistemico + confianza de cada claim afirmado."""
    eid = "ep:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    episode, fragments = _episode(eid, text)
    ctx = ExtractionContext(
        workspace=WS, episodes=[episode], fragments=fragments,
        profile=profile, lexicon=LEXICON,
    )
    out = DeterministicExtractor().extract(ctx)
    return [
        (
            c.predicate_candidates[0]["predicate"] if c.predicate_candidates else None,
            c.epistemic_status_hint,
            round(c.confidence, 6),
        )
        for c in out.claims
        if not c.abstained
    ]


@pytest.mark.parametrize("contraida,ya_cubierta", PARIDAD)
def test_la_contraida_se_comporta_igual_que_su_hermana(contraida, ya_cubierta, profile):
    assert _firma(contraida, profile) == _firma(ya_cubierta, profile)


# ==========================================================================
# 4. Alcance del cierre: aditivo, acotado y sin residuo
# ==========================================================================
def test_el_cierre_es_estrictamente_aditivo():
    """Ni un predicado, ni una confianza, ni una direccion se mueven."""
    assert len(RELATION_RULES) == len(_RELATION_RULES_BASE)
    for efectiva, base in zip(RELATION_RULES, _RELATION_RULES_BASE):
        assert efectiva.predicate == base.predicate
        assert efectiva.direction == base.direction
        assert efectiva.confidence == base.confidence
        assert efectiva.symmetric == base.symmetric
        assert efectiva.subject_types == base.subject_types
        assert efectiva.object_types == base.object_types
        assert efectiva.blocked_prev == base.blocked_prev
        # las frases originales siguen ahi, en su orden, y lo nuevo va detras
        assert efectiva.phrases[: len(base.phrases)] == base.phrases


def test_una_regla_sin_contraccion_declarada_no_crece():
    """El criterio, comprobado sobre el producto: sin contraccion previa, no se toca.

    Es la guarda anti-ampliacion. `PARENT_OF` ("es padre de"/"es madre de") no
    declara ninguna contraccion, asi que "es padre del" NO debe aparecer por
    arte del cierre: seria vocabulario nuevo, que es justo lo que este carril
    no hace.
    """
    for efectiva, base in zip(RELATION_RULES, _RELATION_RULES_BASE):
        declara = any(
            p.split()[-1] in _CONTRACTIONS.values() for p in base.phrases if p.split()
        )
        if not declara:
            assert efectiva.phrases == base.phrases, (
                f"la regla {base.predicate!r} no declaraba ninguna contraccion "
                f"y ha crecido: {set(efectiva.phrases) - set(base.phrases)}"
            )


def test_no_queda_ninguna_asimetria_de_esta_clase():
    """Sobre las reglas EFECTIVAS, el residuo de la clase es cero."""
    residuo: dict = {}
    for regla in RELATION_RULES:
        frases = set(regla.phrases)
        declara = any(p.split()[-1] in _CONTRACTIONS.values() for p in frases if p.split())
        if not declara:
            continue
        faltan = sorted(
            c for p in frases if (c := _contract(p)) is not None and c not in frases
        )
        if faltan:
            residuo[regla.predicate] = faltan
    assert residuo == {}, f"asimetrias de contraccion sin cerrar: {residuo}"


def test_el_cierre_es_idempotente():
    """Aplicarlo dos veces no anade nada: el paradigma esta cerrado."""
    for regla in RELATION_RULES:
        assert _close_contraction_gap(regla).phrases == regla.phrases


def test_contract_solo_toca_el_ultimo_token():
    assert _contract("es miembro de") == "es miembro del"
    assert _contract("sirve a") == "sirve al"
    assert _contract("es miembro del") is None
    assert _contract("vive en") is None
    assert _contract("") is None
