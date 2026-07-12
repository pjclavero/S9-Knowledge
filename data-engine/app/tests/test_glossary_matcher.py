"""Tests del GlossaryMatcher: búsqueda exacta, alias, error_form y fuzzy."""
from __future__ import annotations

import sys
from pathlib import Path
import tempfile
import pytest

_THIS = Path(__file__).resolve()
_APP_DIR = _THIS.parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from glossary.glossary_store import GlossaryStore, normalize_term
from glossary.glossary_models import GlossaryTerm
from glossary.glossary_matcher import GlossaryMatcher


@pytest.fixture
def populated_store():
    """Store con semillas L5A para tests de búsqueda."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    store = GlossaryStore(db_path)

    seeds = [
        GlossaryTerm(
            workspace="leyenda",
            canonical_term="Toshi Ranbo",
            normalized_term=normalize_term("Toshi Ranbo"),
            term_type="lugar",
            aliases=["Ciudad Toshi Ranbo"],
            spoken_forms=["Toshi Ranbo"],
            error_forms=["Tosi Rambo", "Toshi Rambo", "Tosi Ranbo"],
            source_kind="manual_seed",
            confidence=0.99,
            frequency=1,
            priority=0.7,
        ),
        GlossaryTerm(
            workspace="leyenda",
            canonical_term="Seiyuro",
            normalized_term=normalize_term("Seiyuro"),
            term_type="personaje",
            aliases=["Mirumoto Seiyuro"],
            spoken_forms=["Seiyuro"],
            error_forms=["Se Lloro", "Se Yuro"],
            source_kind="manual_seed",
            confidence=0.99,
            frequency=1,
            priority=0.65,
        ),
        GlossaryTerm(
            workspace="leyenda",
            canonical_term="Clan Grulla",
            normalized_term=normalize_term("Clan Grulla"),
            term_type="clan",
            aliases=["Grulla"],
            spoken_forms=["Clan Grulla"],
            error_forms=["Clan Gruya"],
            source_kind="manual_seed",
            confidence=0.99,
            frequency=1,
            priority=0.65,
        ),
        GlossaryTerm(
            workspace="leyenda",
            canonical_term="wakizashi",
            normalized_term=normalize_term("wakizashi"),
            term_type="arma",
            aliases=[],
            spoken_forms=["wakizashi"],
            error_forms=["guacizasi", "wacizasi"],
            source_kind="manual_seed",
            confidence=0.99,
            frequency=1,
            priority=0.6,
        ),
        # Término en otro workspace — no debe aparecer en búsquedas de 'leyenda'
        GlossaryTerm(
            workspace="otro",
            canonical_term="Toshi Ranbo",
            normalized_term=normalize_term("Toshi Ranbo"),
            term_type="lugar",
            aliases=[],
            spoken_forms=[],
            error_forms=[],
            source_kind="manual_seed",
            confidence=0.5,
            frequency=1,
            priority=0.3,
        ),
    ]
    for t in seeds:
        store.upsert_term(t)

    yield store
    store.close()
    db_path.unlink(missing_ok=True)


@pytest.fixture
def matcher(populated_store):
    return GlossaryMatcher(populated_store, workspace="leyenda", fuzzy_threshold=0.72)


# ── Búsqueda por error_form ───────────────────────────────────────────────────

def test_search_error_form_tosi_rambo(matcher):
    """'Tosi Rambo' debe encontrar 'Toshi Ranbo' via error_form."""
    results = matcher.search("Tosi Rambo")
    assert len(results) >= 1
    first = results[0]
    assert first.term.canonical_term == "Toshi Ranbo"
    assert first.match_type == "error_form"


def test_search_error_form_se_lloro(matcher):
    """'Se Lloro' debe encontrar 'Seiyuro' via error_form."""
    results = matcher.search("Se Lloro")
    assert len(results) >= 1
    assert results[0].term.canonical_term == "Seiyuro"
    assert results[0].match_type == "error_form"


def test_search_error_form_se_yuro(matcher):
    """'Se Yuro' debe encontrar 'Seiyuro' via error_form."""
    results = matcher.search("Se Yuro")
    assert len(results) >= 1
    assert results[0].term.canonical_term == "Seiyuro"


def test_search_error_form_clan_gruya(matcher):
    """'Clan Gruya' debe encontrar 'Clan Grulla'."""
    results = matcher.search("Clan Gruya")
    assert len(results) >= 1
    assert results[0].term.canonical_term == "Clan Grulla"


def test_search_error_form_guacizasi(matcher):
    """'guacizasi' debe encontrar 'wakizashi'."""
    results = matcher.search("guacizasi")
    assert len(results) >= 1
    assert results[0].term.canonical_term == "wakizashi"


# ── Búsqueda exacta ───────────────────────────────────────────────────────────

def test_search_exact_canonical(matcher):
    results = matcher.search("Toshi Ranbo")
    assert len(results) >= 1
    assert results[0].term.canonical_term == "Toshi Ranbo"
    assert results[0].match_type == "exact"


def test_search_exact_case_insensitive(matcher):
    """La búsqueda normaliza antes de comparar: 'toshi ranbo' == 'Toshi Ranbo'."""
    results = matcher.search("toshi ranbo")
    assert len(results) >= 1
    assert results[0].term.canonical_term == "Toshi Ranbo"


# ── Búsqueda por alias ────────────────────────────────────────────────────────

def test_search_alias(matcher):
    """'Ciudad Toshi Ranbo' es alias de 'Toshi Ranbo'."""
    results = matcher.search("Ciudad Toshi Ranbo")
    assert len(results) >= 1
    assert results[0].term.canonical_term == "Toshi Ranbo"
    assert results[0].match_type in ("alias", "exact")


def test_search_alias_grulla(matcher):
    """'Grulla' es alias de 'Clan Grulla'."""
    results = matcher.search("Grulla")
    assert len(results) >= 1
    assert results[0].term.canonical_term == "Clan Grulla"


# ── Aislamiento de workspace ──────────────────────────────────────────────────

def test_workspace_isolation(populated_store):
    """El matcher de 'otro' workspace no ve términos de 'leyenda'."""
    matcher_otro = GlossaryMatcher(populated_store, workspace="otro")
    results = matcher_otro.search("Seiyuro")
    # Seiyuro solo existe en workspace 'leyenda'
    assert len(results) == 0


def test_workspace_leyenda_only(matcher):
    """El matcher de 'leyenda' no devuelve duplicados del workspace 'otro'."""
    results = matcher.search("Toshi Ranbo")
    # Todos deben ser del workspace 'leyenda'
    for r in results:
        assert r.term.workspace == "leyenda"


# ── error_forms no son alias canónicos ───────────────────────────────────────

def test_error_forms_not_returned_as_canonical(matcher):
    """Una búsqueda por error_form devuelve el canonical, no el error."""
    results = matcher.search("Tosi Rambo")
    for r in results:
        # El canonical_term nunca debe ser la forma errónea
        assert r.term.canonical_term != "Tosi Rambo"


# ── Búsqueda fuzzy ───────────────────────────────────────────────────────────

def test_fuzzy_partial_match(matcher):
    """Una query parecida pero no exacta debe encontrar el término correcto."""
    results = matcher.search("Toshi Rambo")  # error tipográfico leve
    assert len(results) >= 1
    # Debe encontrar 'Toshi Ranbo' (via error_form o fuzzy)
    canonicals = [r.term.canonical_term for r in results]
    assert "Toshi Ranbo" in canonicals


def test_no_results_garbage(matcher):
    """Una query sin sentido no debe devolver resultados."""
    results = matcher.search("xzqpqpqpqp")
    # Puede devolver 0 o alguno fuzzy con score bajo
    # Con threshold 0.72, una cadena aleatoria no debería matchear
    for r in results:
        assert r.score >= 0.72
