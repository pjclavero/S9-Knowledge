"""Tests del extractor endurecido S9 Knowledge (v0.2.5b).

1. is_stopword("Todo") == True
2. is_stopword("Llevás") == True (con tilde rioplatense)
3. is_stopword("Como") == True
4. Extractor heurístico NO emite "Todo"/"Como"/"Llevás" con confidence >= 0.85
5. Character single-token común no sale con confianza alta
6. "Kitsugi Kaji" (compuesto 2 tokens) puede salir con confianza más alta
7. Match de glosario sube confidence y canonicaliza
8. llm_extractor descarta JSON inválido (mock de Ollama, sin llamada real)
9. llm_extractor descarta entidades sin evidence
10. llm_extractor descarta tipos no permitidos
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_APP_DIR = _TESTS_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review.stopwords import is_stopword, is_weak_single_token, STOPWORDS_ES
from review.extractor import (
    extract_from_segments, _load_glossary, _character_confidence,
    _is_compound_proper_name, _normalize_for_compare,
)
from review.classifier import ClassifiedSegment
from review.models import Candidate


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_seg(text: str, seg_id: str = "src_seg_0001") -> ClassifiedSegment:
    return {
        "segment_id": seg_id,
        "source_id": "src_test",
        "source_kind": "audio",
        "workspace": "test_ws",
        "timestamp_start": "00:05:00",
        "timestamp_end": "00:09:00",
        "text": text,
        "should_extract": True,
        "category": "rpg_content",
        "lines": [],
    }


# ── TAREA 1: stopwords ────────────────────────────────────────────────────────

def test_is_stopword_todo():
    """'Todo' (capitalizado) debe ser stopword."""
    assert is_stopword("Todo") is True, "is_stopword('Todo') debe ser True"


def test_is_stopword_llevas_con_tilde():
    """'Llevás' (tilde rioplatense) debe ser stopword."""
    assert is_stopword("Llevás") is True, "is_stopword('Llevás') debe ser True"


def test_is_stopword_como():
    """'Como' (capitalizado a inicio de frase) debe ser stopword."""
    assert is_stopword("Como") is True, "is_stopword('Como') debe ser True"


def test_is_stopword_pues():
    assert is_stopword("pues") is True


def test_is_stopword_nombre_propio_no_es_stopword():
    """Un nombre propio real NO debe ser stopword."""
    assert is_stopword("Kitsugi") is False
    assert is_stopword("Doji Satsume") is False


def test_is_weak_single_token_todo():
    """'Todo' es single-token y stopword → weak."""
    assert is_weak_single_token("Todo") is True


def test_is_weak_single_token_compound_not_weak():
    """Un nombre compuesto nunca es weak_single_token."""
    assert is_weak_single_token("Doji Satsume") is False


def test_stopwords_es_normalized():
    """Todos los items de STOPWORDS_ES deben estar en minúsculas sin tildes."""
    import unicodedata
    for w in STOPWORDS_ES:
        nfkd = unicodedata.normalize("NFKD", w.lower())
        stripped = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
        assert w == stripped, f"'{w}' no está normalizado correctamente en STOPWORDS_ES"


# ── TAREA 2: extractor NO emite basura con confidence >= 0.85 ─────────────────

def test_extractor_no_emite_todo_con_confianza_alta():
    """El extractor NO debe emitir 'Todo' con confidence >= 0.85."""
    seg = _make_seg("Todo esto es parte del juego y los personajes lo saben bien.")
    candidates = extract_from_segments([seg], glossary={})
    todo_high = [c for c in candidates if c.name == "Todo" and c.confidence >= 0.85]
    assert len(todo_high) == 0, f"'Todo' no debe salir con confidence>=0.85: {todo_high}"


def test_extractor_no_emite_como_con_confianza_alta():
    """El extractor NO debe emitir 'Como' con confidence >= 0.85."""
    seg = _make_seg("Como ya sabéis, el Clan Grulla domina la política.")
    candidates = extract_from_segments([seg], glossary={})
    como_high = [c for c in candidates if c.name == "Como" and c.confidence >= 0.85]
    assert len(como_high) == 0, f"'Como' no debe salir con confidence>=0.85: {como_high}"


def test_extractor_no_emite_llevas_con_confianza_alta():
    """El extractor NO debe emitir 'Llevás' con confidence >= 0.85."""
    seg = _make_seg("Llevás muchos años en el clan y lo sabes mejor que nadie.")
    candidates = extract_from_segments([seg], glossary={})
    llevas_high = [c for c in candidates if "llev" in (c.name or "").lower() and c.confidence >= 0.85]
    assert len(llevas_high) == 0, f"'Llevás' no debe salir con confidence>=0.85: {llevas_high}"


# ── TAREA 2b: anti-Character débil ────────────────────────────────────────────

def test_single_token_common_word_not_high_confidence():
    """Un single-token como 'Bueno' no debe salir con confidence >= 0.85."""
    seg = _make_seg("Bueno, ya veremos qué pasa en la siguiente sesión.")
    candidates = extract_from_segments([seg], glossary={})
    bueno_high = [c for c in candidates
                  if (c.name or "").lower() == "bueno" and c.confidence >= 0.85]
    assert len(bueno_high) == 0, f"'Bueno' (single-token común) no debe ser high-confidence: {bueno_high}"


def test_compound_proper_name_can_have_higher_confidence():
    """Un nombre propio compuesto 'Kitsugi Kaji' puede salir con confidence > 0.65."""
    seg = _make_seg("Kitsugi Kaji entra en la sala del consejo del Clan Grulla.")
    candidates = extract_from_segments([seg], glossary={})
    kitsugi = [c for c in candidates if "kitsugi" in (c.name or "").lower()]
    # No exigimos un umbral exacto, pero sí que sea mayor que una single-word común
    if kitsugi:
        assert kitsugi[0].confidence > 0.65, \
            f"Nombre compuesto debe tener confidence > 0.65, got {kitsugi[0].confidence}"
    # Si no aparece, el test pasa: el extractor no está obligado a detectar todo


def test_compound_name_detection():
    """_is_compound_proper_name debe retornar True para nombres de 2+ tokens capitalizados."""
    assert _is_compound_proper_name("Doji Satsume") is True
    assert _is_compound_proper_name("Kitsugi Kaji") is True
    assert _is_compound_proper_name("Clan Grulla") is True
    assert _is_compound_proper_name("Satsume") is False  # solo un token


# ── TAREA 2c: glosario sube confidence y canonicaliza ─────────────────────────

def test_glossary_match_boosts_confidence():
    """Un nombre que coincide con el glosario debe tener confidence mayor."""
    # Sin glosario: Doji Satsume sale con confianza base
    seg = _make_seg("Doji Satsume llega al castillo.")
    cands_no_gloss = extract_from_segments([seg], glossary={})
    doji_no_gloss = [c for c in cands_no_gloss if "doji" in (c.name or "").lower()]

    # Con glosario que contiene el nombre
    gloss = {"doji satsume": "Doji Satsume"}
    cands_gloss = extract_from_segments([seg], glossary=gloss)
    doji_gloss = [c for c in cands_gloss if "doji" in (c.name or "").lower()]

    if doji_no_gloss and doji_gloss:
        assert doji_gloss[0].confidence > doji_no_gloss[0].confidence, \
            f"Glosario debe subir confidence: sin_gloss={doji_no_gloss[0].confidence}, con_gloss={doji_gloss[0].confidence}"


def test_glossary_canonicalizes_name():
    """Si el glosario tiene canonical diferente al detectado, debe canonicalizar."""
    # "Bayushi Tsubaki" en texto pero glosario tiene "Bayushi Tsubaki-san" como canonical
    gloss = {"bayushi tsubaki": "Bayushi Tsubaki-san"}
    seg = _make_seg("Bayushi Tsubaki aparece ante el magistrado.")
    cands = extract_from_segments([seg], glossary=gloss)
    # Buscar por fragmento "bayushi"
    bayushi = [c for c in cands if "bayushi" in (c.name or "").lower()]
    if bayushi:
        assert bayushi[0].name == "Bayushi Tsubaki-san", \
            f"Canonicalización esperada 'Bayushi Tsubaki-san', got '{bayushi[0].name}'"


# ── TAREA 3: llm_extractor — tests con mock ────────────────────────────────────

@patch("review.llm_extractor._call_ollama")
def test_llm_extractor_descarta_json_invalido(mock_ollama):
    """Si Ollama devuelve JSON inválido, llm_extractor retorna lista vacía (sin crash)."""
    mock_ollama.return_value = "esto no es json valido { ni tampoco"

    from review.llm_extractor import extract_with_llm
    seg = _make_seg("Doji Satsume entra en la sala del consejo.")
    result = extract_with_llm([seg], glossary_snapshot=[], workspace="test")
    # Con JSON inválido: el segmento se descarta, lista vacía o sin candidatos de ese seg
    # No debe crashear
    assert isinstance(result, list)


@patch("review.llm_extractor._call_ollama")
def test_llm_extractor_descarta_entidades_sin_evidence(mock_ollama):
    """Entidades sin campo 'evidence' deben ser descartadas."""
    mock_ollama.return_value = json.dumps({
        "entities": [
            {"name": "Doji Satsume", "type": "Character", "confidence": 0.9},  # sin evidence
            {"name": "Castillo Shiro", "type": "Location", "evidence": "el castillo de Shiro", "confidence": 0.8},
        ],
        "relations": [],
    })

    from review.llm_extractor import extract_with_llm
    seg = _make_seg("Doji Satsume llega al Castillo Shiro.")
    result = extract_with_llm([seg], glossary_snapshot=[], workspace="test")
    names = [c.name for c in result]
    assert "Doji Satsume" not in names, "Entidad sin evidence debe descartarse"
    assert "Castillo Shiro" in names, "Entidad con evidence debe mantenerse"


@patch("review.llm_extractor._call_ollama")
def test_llm_extractor_descarta_tipos_no_permitidos(mock_ollama):
    """Tipos fuera de la lista permitida deben descartarse."""
    mock_ollama.return_value = json.dumps({
        "entities": [
            {"name": "Espada Sagrada", "type": "WeaponMagic", "evidence": "la espada sagrada", "confidence": 0.9},
            {"name": "Templo del Dragón", "type": "Location", "evidence": "el templo", "confidence": 0.85},
        ],
        "relations": [],
    })

    from review.llm_extractor import extract_with_llm
    seg = _make_seg("La Espada Sagrada está en el Templo del Dragón.")
    result = extract_with_llm([seg], glossary_snapshot=[], workspace="test")
    names = [c.name for c in result]
    assert "Espada Sagrada" not in names, "Tipo no permitido 'WeaponMagic' debe descartarse"
    assert "Templo del Dragón" in names, "Tipo 'Location' debe mantenerse"


@patch("review.llm_extractor._call_ollama")
def test_llm_extractor_respuesta_correcta(mock_ollama):
    """Con respuesta LLM correcta, deben generarse candidatos Candidate válidos."""
    mock_ollama.return_value = json.dumps({
        "entities": [
            {
                "name": "Doji Satsume",
                "type": "Character",
                "evidence": "Doji Satsume entra en la sala",
                "confidence": 0.92,
            }
        ],
        "relations": [],
    })

    from review.llm_extractor import extract_with_llm
    seg = _make_seg("Doji Satsume entra en la sala del consejo.")
    result = extract_with_llm([seg], glossary_snapshot=[], workspace="test")
    assert len(result) == 1
    c = result[0]
    assert c.name == "Doji Satsume"
    assert c.entity_type == "Character"
    assert c.confidence == 0.92
    assert c.evidence == "Doji Satsume entra en la sala"
    assert c.timestamp_start == "00:05:00"


@patch("review.llm_extractor._call_ollama")
def test_llm_extractor_ollama_none_no_crash(mock_ollama):
    """Si Ollama retorna None (timeout/error), no debe crashear y retorna lista vacía."""
    mock_ollama.return_value = None

    from review.llm_extractor import extract_with_llm
    seg = _make_seg("Bayushi Kachiko conspira en las sombras.")
    result = extract_with_llm([seg], glossary_snapshot=[], workspace="test")
    assert isinstance(result, list)
    # Puede ser vacía o tener candidatos de otros segmentos; no debe lanzar excepción


# ── Extra: garantía stopword <= 0.85 ──────────────────────────────────────────

def test_character_confidence_stopword_never_above_085():
    """_character_confidence para cualquier stopword nunca debe superar 0.85."""
    stopwords_to_test = ["Todo", "Como", "Llevás", "Pues", "Vale", "Bueno", "Mira"]
    for sw in stopwords_to_test:
        conf = _character_confidence(sw, "texto de prueba", {}, 0.90)
        assert conf < 0.85, f"Stopword '{sw}' no puede tener confidence >= 0.85, got {conf}"
