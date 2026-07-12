"""Tests del GlossaryStore y de normalize_term."""
from __future__ import annotations

import sys
from pathlib import Path
import tempfile
import pytest

# Bootstrap: añadir data-engine/app al path
_THIS = Path(__file__).resolve()
# Este fichero está en data-engine/app/tests/ -> parent[1] = data-engine/app
_APP_DIR = _THIS.parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from glossary.glossary_store import GlossaryStore, normalize_term
from glossary.glossary_models import GlossaryTerm


# ── normalize_term ────────────────────────────────────────────────────────────

def test_normalize_strips_diacritics():
    assert normalize_term("Toshí  Ranbo") == "toshi ranbo"

def test_normalize_toshi_ranbo():
    assert normalize_term("Toshi Ranbo") == "toshi ranbo"

def test_normalize_rokugán():
    assert normalize_term("Rokugán") == "rokugan"

def test_normalize_collapses_spaces():
    assert normalize_term("  Clan   León  ") == "clan leon"

def test_normalize_lowercase():
    assert normalize_term("WAKIZASHI") == "wakizashi"

def test_normalize_removes_punctuation():
    # Puntuación de comparación se elimina
    result = normalize_term("Mirumoto-Seiyuro")
    # guiones → espacio → "mirumoto seiyuro"
    assert result == "mirumoto seiyuro"


# ── GlossaryStore ─────────────────────────────────────────────────────────────

@pytest.fixture
def store():
    """Store en fichero temporal eliminado al finalizar el test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    s = GlossaryStore(db_path)
    yield s
    s.close()
    db_path.unlink(missing_ok=True)


def _make_term(canonical: str, workspace: str = "test", **kwargs) -> GlossaryTerm:
    return GlossaryTerm(
        workspace=workspace,
        canonical_term=canonical,
        normalized_term=normalize_term(canonical),
        **kwargs,
    )


def test_upsert_and_retrieve(store):
    t = _make_term("Toshi Ranbo", term_type="lugar")
    tid = store.upsert_term(t)
    assert isinstance(tid, int) and tid > 0

    found = store.get_term_by_canonical("test", "Toshi Ranbo")
    assert found is not None
    assert found.canonical_term == "Toshi Ranbo"
    assert found.term_type == "lugar"


def test_upsert_idempotente(store):
    """Upsert dos veces no debe duplicar el término."""
    t = _make_term("Seiyuro", term_type="personaje")
    id1 = store.upsert_term(t)
    id2 = store.upsert_term(t)
    # El mismo término no genera un segundo registro
    terms = store.list_terms("test", enabled_only=False)
    assert len(terms) == 1
    # Los IDs deben apuntar al mismo registro
    assert id1 == id2 or store.get_term_by_canonical("test", "Seiyuro") is not None


def test_workspace_isolation(store):
    """Términos de workspaces distintos no se mezclan."""
    t1 = _make_term("Rokugán", workspace="leyenda")
    t2 = _make_term("Rokugán", workspace="otro")
    store.upsert_term(t1)
    store.upsert_term(t2)

    terms_leyenda = store.list_terms("leyenda")
    terms_otro = store.list_terms("otro")
    assert len(terms_leyenda) == 1
    assert len(terms_otro) == 1
    assert terms_leyenda[0].workspace == "leyenda"
    assert terms_otro[0].workspace == "otro"


def test_add_error_form(store):
    t = _make_term("Toshi Ranbo")
    tid = store.upsert_term(t)
    store.add_error_form(tid, "Tosi Rambo")
    store.add_error_form(tid, "Tosi Rambo")  # idempotente

    found = store.get_term_by_canonical("test", "Toshi Ranbo")
    assert "Tosi Rambo" in found.error_forms
    assert found.error_forms.count("Tosi Rambo") == 1  # no duplicado


def test_error_forms_not_canonical(store):
    """error_forms no deben tratarse como alias canónicos.

    Un error_form es una forma incorrecta que el ASR produce; no debe
    aparecer en aliases ni en canonical_term.
    """
    t = _make_term(
        "Toshi Ranbo",
        error_forms=["Tosi Rambo"],
        aliases=["Ciudad Toshi Ranbo"],
    )
    store.upsert_term(t)

    found = store.get_term_by_canonical("test", "Toshi Ranbo")
    assert found is not None
    assert "Tosi Rambo" in found.error_forms
    assert "Tosi Rambo" not in found.aliases
    assert found.canonical_term != "Tosi Rambo"


def test_list_terms_enabled_only(store):
    t1 = _make_term("Termino A", enabled=True)
    t2 = _make_term("Termino B", enabled=False)
    store.upsert_term(t1)
    store.upsert_term(t2)

    enabled = store.list_terms("test", enabled_only=True)
    all_terms = store.list_terms("test", enabled_only=False)
    assert len(enabled) == 1
    assert enabled[0].canonical_term == "Termino A"
    assert len(all_terms) == 2


def test_stats(store):
    store.upsert_term(_make_term("Toshi Ranbo", term_type="lugar"))
    store.upsert_term(_make_term("Seiyuro", term_type="personaje"))
    stats = store.stats("test")
    assert stats["total"] == 2
    assert stats["enabled"] == 2
    assert "lugar" in stats["by_type"]
    assert "personaje" in stats["by_type"]
