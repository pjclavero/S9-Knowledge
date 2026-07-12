"""Tests del normalizador determinista de transcripciones L5A."""
import importlib.util, json, sqlite3, sys, tempfile
from pathlib import Path

# Cargar el módulo desde su ruta (data-engine tiene guion → import por ruta)
_HERE = Path(__file__).resolve()
_MOD = _HERE.parents[1] / "glossary" / "transcript_normalizer.py"
_spec = importlib.util.spec_from_file_location("transcript_normalizer", _MOD)
tn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tn)


def _make_db(tmp_path):
    db = str(tmp_path / "g.db")
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE glossary_terms (
        id INTEGER PRIMARY KEY AUTOINCREMENT, workspace TEXT, canonical_term TEXT,
        normalized_term TEXT, term_type TEXT, aliases_json TEXT DEFAULT '[]',
        spoken_forms_json TEXT DEFAULT '[]', error_forms_json TEXT DEFAULT '[]',
        source_id TEXT, source_kind TEXT, source_document TEXT, source_pages_json TEXT DEFAULT '[]',
        confidence REAL DEFAULT 0.5, frequency INTEGER DEFAULT 1, priority REAL DEFAULT 0,
        edition TEXT, language TEXT, enabled INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT)""")
    con.execute("INSERT INTO glossary_terms (workspace, canonical_term, normalized_term, error_forms_json, confidence, enabled) "
                "VALUES ('leyenda','Clan Grulla','clan grulla','[\"Clan Gruya\"]', 0.99, 1)")
    con.execute("INSERT INTO glossary_terms (workspace, canonical_term, normalized_term, error_forms_json, confidence, enabled) "
                "VALUES ('leyenda','oni','oni','[\"honi\"]', 0.99, 1)")
    con.commit(); con.close()
    return db


def test_basic_substitution(tmp_path):
    db = _make_db(tmp_path)
    efs = tn.load_error_forms(db, "leyenda")
    new, repl = tn.normalize_text("El Clan Gruya avanza hacia el sur", efs, 1)
    assert "Clan Grulla" in new
    assert "Clan Gruya" not in new
    assert len(repl) == 1
    assert repl[0]["to"] == "Clan Grulla"


def test_timestamps_preserved(tmp_path):
    db = _make_db(tmp_path)
    raw = "**[00:00:01]** El Clan Gruya\n**[00:00:05]** avanza\n[00:00:09] hacia oni"
    src = tmp_path / "raw.md"; src.write_text(raw, encoding="utf-8")
    outdir = tmp_path / "out"
    sys.argv = ["x", "--input", str(src), "--output-dir", str(outdir), "--workspace", "leyenda", "--db", db]
    tn.main()
    normalized = (outdir / "raw.normalized.md").read_text(encoding="utf-8")
    assert len(tn.TS_RE.findall(raw)) == len(tn.TS_RE.findall(normalized)) == 3


def test_review_json_structure(tmp_path):
    db = _make_db(tmp_path)
    raw = "**[00:00:01]** El Clan Gruya avanza"
    src = tmp_path / "raw.md"; src.write_text(raw, encoding="utf-8")
    outdir = tmp_path / "out"
    sys.argv = ["x", "--input", str(src), "--output-dir", str(outdir), "--workspace", "leyenda", "--db", db]
    tn.main()
    review = json.loads((outdir / "raw.review.json").read_text(encoding="utf-8"))
    assert review["workspace"] == "leyenda"
    assert review["ready_for_ingestion"] is False
    assert review["timestamps_preserved"] is True
    assert review["replacements_count"] == 1
    assert review["replacements"][0]["to"] == "Clan Grulla"


def test_word_boundary_respected(tmp_path):
    db = _make_db(tmp_path)
    efs = tn.load_error_forms(db, "leyenda")
    # "honi" es error_form de oni; no debe sustituir dentro de "chihoning" ni tocar "colonia"
    new, repl = tn.normalize_text("la colonia y el chihoning", efs, 1)
    assert new == "la colonia y el chihoning"
    assert len(repl) == 0
    # pero sí como palabra suelta
    new2, repl2 = tn.normalize_text("aparece honi de repente", efs, 1)
    assert "oni" in new2.split()
    assert len(repl2) == 1


def test_timestamp_not_modified(tmp_path):
    db = _make_db(tmp_path)
    prefix, text = tn.split_timestamp("**[00:01:23]** El Clan Gruya")
    assert "00:01:23" in prefix
    assert "Clan Gruya" in text
