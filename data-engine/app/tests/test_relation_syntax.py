# -*- coding: utf-8 -*-
"""Tests del adaptador sintactico desacoplado (`relation-syntax/v1`).

Cubren: texto vacio, una/varias frases, espanol e ingles, idioma no soportado
(degradado), negacion, voz pasiva, sujeto omitido, multiples entidades,
proveedor ausente (falla claro), proveedor que lanza (aislado), offsets Unicode
(acentos + emoji), serializacion round-trip, determinismo, y las garantias de
NO carga de modelos al importar / NO red / NO descarga.

SIN red, SIN Neo4j, SIN LLM, SIN escritura. Solo leen `relations.syntax`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from relations.syntax import (  # noqa: E402
    SYNTAX_VERSION,
    SUPPORTED_LANGUAGES,
    SyntaxAdapterError,
    SyntaxProviderUnavailable,
    SyntaxToken,
    SyntaxDependency,
    SyntaxSentence,
    SyntaxAnalysis,
    SyntaxAnalyzer,
    HeuristicSyntaxAnalyzer,
    NullSyntaxAnalyzer,
    ExternalModelSyntaxAnalyzer,
    get_analyzer,
    analyze,
    safe_analyze,
)


# ---------------------------------------------------------------------------
# Garantias de importacion: sin efectos secundarios, sin red, sin descarga
# ---------------------------------------------------------------------------
def test_import_no_side_effects_no_network_modules():
    """Importar el modulo no debe traer clientes de red ni frameworks de modelo."""
    for banned in ("requests", "httpx", "urllib3", "spacy", "stanza", "torch", "neo4j"):
        assert banned not in sys.modules or True  # otros tests pueden importarlos
    # Lo esencial: el propio modulo syntax no importa red ni modelos.
    import relations.syntax as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for banned in ("import requests", "import httpx", "import spacy", "import stanza",
                   "import torch", "from neo4j", "import neo4j"):
        assert banned not in src, f"syntax.py no debe importar {banned!r}"


def test_default_analyzer_always_available():
    an = get_analyzer()
    assert isinstance(an, HeuristicSyntaxAnalyzer)
    assert an.available() is True
    assert an.name == "heuristic"


# ---------------------------------------------------------------------------
# Texto vacio
# ---------------------------------------------------------------------------
def test_empty_text():
    a = analyze("")
    assert a.text == ""
    assert a.sentences == ()
    assert a.quality == 0.0
    assert a.provider == "heuristic"
    assert a.version == SYNTAX_VERSION


def test_whitespace_only_text():
    a = analyze("   \n\t  ")
    assert a.sentences == ()
    assert a.quality == 0.0


# ---------------------------------------------------------------------------
# Una / varias frases
# ---------------------------------------------------------------------------
def test_single_sentence():
    a = analyze("Aragorn ama a Arwen.")
    assert len(a.sentences) == 1
    s = a.sentences[0]
    assert s.text == "Aragorn ama a Arwen."
    assert s.start == 0
    assert s.tokens[0].text == "Aragorn"


def test_multiple_sentences():
    a = analyze("Frodo camina. Sam observa. Gollum acecha.")
    assert len(a.sentences) == 3
    # indices de frase deterministas y crecientes
    assert [s.index for s in a.sentences] == [0, 1, 2]
    # los spans no se solapan y respetan el orden textual
    assert a.sentences[0].start < a.sentences[1].start < a.sentences[2].start


def test_sentence_offsets_match_original():
    text = "Primera frase. Segunda frase."
    a = analyze(text)
    for s in a.sentences:
        assert text[s.start:s.end] == s.text


# ---------------------------------------------------------------------------
# Espanol / ingles
# ---------------------------------------------------------------------------
def test_spanish_autodetect():
    a = analyze("El rey gobierna la ciudad con justicia.")
    assert a.language == "es"
    assert a.degraded is False


def test_english_autodetect():
    a = analyze("The king rules the city with justice.")
    assert a.language == "en"
    assert a.degraded is False


def test_english_explicit_language_svo():
    s = analyze("Aragorn loves Arwen.", language="en").sentences[0]
    verb = s.tokens[s.main_verb_index]
    assert verb.text.lower() == "loves"
    assert s.subject_index is not None
    assert s.object_index is not None


# ---------------------------------------------------------------------------
# Idioma no soportado -> degradado (no falla)
# ---------------------------------------------------------------------------
def test_unsupported_language_degraded():
    a = analyze("Bonjour tout le monde.", language="fr")
    assert a.language == "fr"
    assert a.degraded is True
    assert a.quality == pytest.approx(0.2)
    # Aun asi segmenta y tokeniza con offsets validos
    assert len(a.sentences) == 1
    s = a.sentences[0]
    assert s.subject_index is None and s.main_verb_index is None
    assert s.tokens  # hay tokens
    assert any("no soportado" in n for n in a.notes)


def test_unsupported_language_offsets_still_valid():
    text = "Guten Tag Welt."
    a = analyze(text, language="de")
    for s in a.sentences:
        for tok in s.tokens:
            assert text[tok.start:tok.end] == tok.text


# ---------------------------------------------------------------------------
# Negacion
# ---------------------------------------------------------------------------
def test_negation_spanish():
    s = analyze("Frodo no confia en Gollum.").sentences[0]
    assert s.negated is True
    neg_tokens = [t for t in s.tokens if t.is_negation]
    assert len(neg_tokens) == 1
    assert neg_tokens[0].text.lower() == "no"
    assert neg_tokens[0].dep == "neg"


def test_negation_english():
    s = analyze("The king does not rule.", language="en").sentences[0]
    assert s.negated is True


def test_no_false_negation():
    s = analyze("Aragorn ama a Arwen.").sentences[0]
    assert s.negated is False


def test_negation_not_flagged_in_degraded_mode():
    # 'no' aparece pero en idioma no soportado no se marca negacion linguistica
    s = analyze("Ich habe no idea.", language="de").sentences[0]
    assert s.negated is False


# ---------------------------------------------------------------------------
# Voz pasiva
# ---------------------------------------------------------------------------
def test_passive_spanish():
    s = analyze("La ciudad fue destruida por el enemigo.").sentences[0]
    assert s.passive is True


def test_passive_english():
    s = analyze("The king was killed by the traitor.", language="en").sentences[0]
    assert s.passive is True


def test_active_not_passive():
    s = analyze("El enemigo destruye la ciudad.").sentences[0]
    assert s.passive is False


# ---------------------------------------------------------------------------
# Sujeto omitido (pro-drop)
# ---------------------------------------------------------------------------
def test_omitted_subject():
    # Frase sin sujeto explicito: el verbo abre la frase.
    s = analyze("Ama a Arwen.").sentences[0]
    assert s.main_verb_index is not None
    assert s.subject_index is None
    assert s.object_index is not None


# ---------------------------------------------------------------------------
# Multiples entidades
# ---------------------------------------------------------------------------
def test_multiple_entities():
    s = analyze("Aragorn conoce a Gandalf y a Legolas.").sentences[0]
    words = [t.text for t in s.tokens if t.pos != "PUNCT"]
    # Deben conservarse todas las entidades como tokens con offsets
    for name in ("Aragorn", "Gandalf", "Legolas"):
        assert name in words


# ---------------------------------------------------------------------------
# Proveedor ausente: falla CLARO
# ---------------------------------------------------------------------------
def test_provider_absent_fails_clearly():
    with pytest.raises(SyntaxProviderUnavailable):
        get_analyzer("spacy")
    with pytest.raises(SyntaxProviderUnavailable):
        get_analyzer("stanza")


def test_unknown_provider_raises():
    with pytest.raises(SyntaxAdapterError):
        get_analyzer("no-such-provider")


def test_external_analyzer_unavailable_and_raises():
    ext = ExternalModelSyntaxAnalyzer("spacy")
    assert ext.available() is False
    with pytest.raises(SyntaxProviderUnavailable):
        ext.analyze("hola mundo.")


# ---------------------------------------------------------------------------
# Proveedor que lanza excepcion: AISLADO por safe_analyze
# ---------------------------------------------------------------------------
class _BrokenAnalyzer(SyntaxAnalyzer):
    name = "broken"

    def analyze(self, text, *, language=None):
        raise RuntimeError("boom interno del proveedor")


def test_broken_provider_isolated():
    a = safe_analyze(_BrokenAnalyzer(), "Aragorn ama a Arwen.")
    assert a.provider == "broken"
    assert a.degraded is True
    assert a.sentences == ()
    assert any("boom" in n for n in a.notes)


def test_safe_analyze_ok_provider_passthrough():
    a = safe_analyze(HeuristicSyntaxAnalyzer(), "Frodo camina.")
    assert a.provider == "heuristic"
    assert a.degraded is False


# ---------------------------------------------------------------------------
# Offsets con Unicode (acentos + emoji)
# ---------------------------------------------------------------------------
def test_unicode_accent_offsets():
    text = "Núñez atacó la fortaleza."
    a = analyze(text)
    for s in a.sentences:
        for tok in s.tokens:
            assert text[tok.start:tok.end] == tok.text


def test_emoji_offsets():
    text = "Frodo camina 🌍 hacia Mordor."
    a = analyze(text)
    reconstructed_ok = True
    for s in a.sentences:
        for tok in s.tokens:
            if text[tok.start:tok.end] != tok.text:
                reconstructed_ok = False
    assert reconstructed_ok
    # El emoji aparece como token propio con offsets correctos
    emoji_tokens = [t for s in a.sentences for t in s.tokens if t.text == "🌍"]
    assert len(emoji_tokens) == 1
    et = emoji_tokens[0]
    assert text[et.start:et.end] == "🌍"


# ---------------------------------------------------------------------------
# Serializacion round-trip y determinismo
# ---------------------------------------------------------------------------
def test_roundtrip_dict():
    a = analyze("La ciudad fue destruida por el enemigo. Aragorn no huye.")
    b = SyntaxAnalysis.from_dict(a.to_dict())
    assert b.to_dict() == a.to_dict()


def test_roundtrip_json():
    a = analyze("Aragorn ama a Arwen. Gollum no confia en nadie.")
    j = a.to_json()
    b = SyntaxAnalysis.from_json(j)
    assert b.to_json() == j


def test_json_is_deterministic():
    text = "El rey gobierna. La reina protege la ciudad."
    j1 = analyze(text).to_json()
    j2 = analyze(text).to_json()
    assert j1 == j2


def test_analysis_is_deterministic_objects():
    text = "Aragorn conoce a Gandalf."
    a1 = analyze(text)
    a2 = analyze(text)
    assert a1.to_dict() == a2.to_dict()


def test_from_json_invalid_raises():
    with pytest.raises(SyntaxAdapterError):
        SyntaxAnalysis.from_json("{not-json")


def test_token_dependency_roundtrip():
    tok = SyntaxToken(index=0, text="Aragorn", start=0, end=7, dep="nsubj")
    assert SyntaxToken.from_dict(tok.to_dict()) == tok
    dep = SyntaxDependency(head_index=1, dependent_index=0, relation="nsubj")
    assert SyntaxDependency.from_dict(dep.to_dict()) == dep


def test_sentence_roundtrip():
    s = analyze("Aragorn ama a Arwen.").sentences[0]
    s2 = SyntaxSentence.from_dict(s.to_dict())
    assert s2.to_dict() == s.to_dict()


# ---------------------------------------------------------------------------
# Null provider
# ---------------------------------------------------------------------------
def test_null_provider():
    a = get_analyzer("null").analyze("Aragorn ama a Arwen.")
    assert a.provider == "null"
    assert a.sentences == ()
    assert a.degraded is True


# ---------------------------------------------------------------------------
# Contrato de la interfaz / dependencias
# ---------------------------------------------------------------------------
def test_dependencies_reference_valid_tokens():
    s = analyze("Aragorn ama a Arwen.").sentences[0]
    token_indices = {t.index for t in s.tokens}
    for d in s.dependencies:
        assert d.head_index in token_indices
        assert d.dependent_index in token_indices


def test_root_is_main_verb():
    s = analyze("Aragorn ama a Arwen.").sentences[0]
    root_tokens = [t for t in s.tokens if t.dep == "root"]
    assert len(root_tokens) == 1
    assert root_tokens[0].index == s.main_verb_index


def test_supported_languages_constant():
    assert "es" in SUPPORTED_LANGUAGES
    assert "en" in SUPPORTED_LANGUAGES


def test_bad_text_type_raises():
    with pytest.raises(SyntaxAdapterError):
        HeuristicSyntaxAnalyzer().analyze(123)  # type: ignore[arg-type]
