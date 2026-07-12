"""SQLite store para el glosario de transcripción.

Tabla: glossary_terms (ver esquema en el docstring de GlossaryStore).
Ruta de la DB: env S9K_GLOSSARY_DB (default state/glossary.db relativo
al repositorio, calculado desde la ubicación de este fichero).

Funciones principales:
- upsert_term(term): insert o update por (workspace, canonical_term, source_id)
- get_term_by_canonical(workspace, canonical): búsqueda exacta
- search_terms(workspace, query, limit): búsqueda en normalized_term y aliases_json
- list_terms(workspace, enabled_only, limit): listado completo
- add_error_form(term_id, error_form): añade forma errónea al JSON
- stats(workspace): estadísticas agregadas
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from glossary.glossary_models import GlossaryTerm

log = logging.getLogger("glossary.store")

# Raíz del repo: data-engine/app/glossary/glossary_store.py → parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS glossary_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace TEXT NOT NULL,
    canonical_term TEXT NOT NULL,
    normalized_term TEXT NOT NULL,
    term_type TEXT,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    spoken_forms_json TEXT NOT NULL DEFAULT '[]',
    error_forms_json TEXT NOT NULL DEFAULT '[]',
    source_id TEXT NOT NULL DEFAULT '',
    source_kind TEXT,
    source_document TEXT,
    source_pages_json TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0.5,
    frequency INTEGER NOT NULL DEFAULT 1,
    priority REAL NOT NULL DEFAULT 0,
    edition TEXT,
    language TEXT DEFAULT 'es',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(workspace, canonical_term, source_id)
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_glossary_workspace ON glossary_terms(workspace);",
    "CREATE INDEX IF NOT EXISTS idx_glossary_normalized ON glossary_terms(normalized_term);",
    "CREATE INDEX IF NOT EXISTS idx_glossary_type ON glossary_terms(term_type);",
    "CREATE INDEX IF NOT EXISTS idx_glossary_priority ON glossary_terms(priority DESC);",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_term(value: str) -> str:
    """Normaliza un término para comparación interna.

    - Normalización Unicode NFKD
    - Minúsculas
    - Elimina diacríticos (tildes, diéresis) solo para comparación
    - Colapsa espacios múltiples
    - Elimina puntuación de comparación (guiones en palabras se conservan como espacio)

    El canonical_term original se conserva siempre en su campo propio.
    """
    import unicodedata
    import re

    # NFKD + minúsculas
    nfkd = unicodedata.normalize("NFKD", value.lower())
    # Eliminar marcas diacríticas (categoría Mn = Mark, Nonspacing)
    without_diacritics = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    # Reemplazar guiones y puntuación de límite de palabra por espacio
    cleaned = re.sub(r"[-_/\\]", " ", without_diacritics)
    # Eliminar puntuación sobrante (excepto alfanumérico y espacio)
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    # Colapsar espacios
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


class GlossaryStore:
    """Store SQLite para glossary_terms.

    Uso:
        store = GlossaryStore()          # usa S9K_GLOSSARY_DB o state/glossary.db
        store = GlossaryStore(path)      # ruta explícita (útil en tests)
    """

    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            env_path = os.environ.get("S9K_GLOSSARY_DB", "").strip()
            if env_path:
                db_path = Path(env_path)
            else:
                db_path = _REPO_ROOT / "state" / "glossary.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
        return self._conn

    def _init_db(self) -> None:
        conn = self._connect()
        conn.execute(_CREATE_TABLE)
        for idx_sql in _CREATE_INDEXES:
            conn.execute(idx_sql)
        conn.commit()
        log.debug("glossary_terms tabla e índices listos en %s", self.db_path)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Escritura ─────────────────────────────────────────────────────────────

    def upsert_term(self, term: GlossaryTerm) -> int:
        """Insert o update idempotente por (workspace, canonical_term, source_id).

        Si ya existe la tripleta única, actualiza todos los campos mutables
        (aliases, error_forms, spoken_forms, confidence, frequency, priority, etc.)
        y rellena updated_at. Devuelve el rowid.
        """
        conn = self._connect()
        now = _now_iso()
        # Normalizar si no viene normalizado
        if not term.normalized_term:
            term.normalized_term = normalize_term(term.canonical_term)

        sql_insert = """
        INSERT INTO glossary_terms (
            workspace, canonical_term, normalized_term, term_type,
            aliases_json, spoken_forms_json, error_forms_json,
            source_id, source_kind, source_document, source_pages_json,
            confidence, frequency, priority, edition, language, enabled,
            created_at, updated_at
        ) VALUES (
            :workspace, :canonical_term, :normalized_term, :term_type,
            :aliases_json, :spoken_forms_json, :error_forms_json,
            :source_id, :source_kind, :source_document, :source_pages_json,
            :confidence, :frequency, :priority, :edition, :language, :enabled,
            :created_at, :updated_at
        )
        ON CONFLICT(workspace, canonical_term, source_id) DO UPDATE SET
            normalized_term = excluded.normalized_term,
            term_type = excluded.term_type,
            aliases_json = excluded.aliases_json,
            spoken_forms_json = excluded.spoken_forms_json,
            error_forms_json = excluded.error_forms_json,
            source_kind = excluded.source_kind,
            source_document = excluded.source_document,
            source_pages_json = excluded.source_pages_json,
            confidence = excluded.confidence,
            frequency = excluded.frequency,
            priority = excluded.priority,
            edition = excluded.edition,
            language = excluded.language,
            enabled = excluded.enabled,
            updated_at = excluded.updated_at
        """
        params = {
            "workspace": term.workspace,
            "canonical_term": term.canonical_term,
            "normalized_term": term.normalized_term,
            "term_type": term.term_type,
            "aliases_json": json.dumps(term.aliases, ensure_ascii=False),
            "spoken_forms_json": json.dumps(term.spoken_forms, ensure_ascii=False),
            "error_forms_json": json.dumps(term.error_forms, ensure_ascii=False),
            "source_id": term.source_id if term.source_id is not None else "",
            "source_kind": term.source_kind,
            "source_document": term.source_document,
            "source_pages_json": json.dumps(term.source_pages, ensure_ascii=False),
            "confidence": term.confidence,
            "frequency": term.frequency,
            "priority": term.priority,
            "edition": term.edition,
            "language": term.language,
            "enabled": 1 if term.enabled else 0,
            "created_at": term.created_at or now,
            "updated_at": now,
        }
        cur = conn.execute(sql_insert, params)
        conn.commit()
        rowid = cur.lastrowid or self._get_id(term.workspace, term.canonical_term, term.source_id)
        return rowid

    def _get_id(self, workspace: str, canonical_term: str, source_id: str | None) -> int | None:
        conn = self._connect()
        cur = conn.execute(
            "SELECT id FROM glossary_terms WHERE workspace=? AND canonical_term=? AND source_id=?",
            (workspace, canonical_term, source_id if source_id is not None else ""),
        )
        row = cur.fetchone()
        return row["id"] if row else None

    def add_error_form(self, term_id: int, error_form: str) -> None:
        """Añade error_form al JSON existente si no está ya incluido."""
        conn = self._connect()
        row = conn.execute(
            "SELECT error_forms_json FROM glossary_terms WHERE id=?", (term_id,)
        ).fetchone()
        if not row:
            log.warning("add_error_form: term_id %d no encontrado", term_id)
            return
        forms: list[str] = json.loads(row["error_forms_json"] or "[]")
        if error_form not in forms:
            forms.append(error_form)
            conn.execute(
                "UPDATE glossary_terms SET error_forms_json=?, updated_at=? WHERE id=?",
                (json.dumps(forms, ensure_ascii=False), _now_iso(), term_id),
            )
            conn.commit()

    # ── Consulta ──────────────────────────────────────────────────────────────

    def get_term_by_canonical(self, workspace: str, canonical: str) -> GlossaryTerm | None:
        """Busca por canonical_term exacto (case-sensitive)."""
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM glossary_terms WHERE workspace=? AND canonical_term=? LIMIT 1",
            (workspace, canonical),
        ).fetchone()
        return GlossaryTerm.from_row(dict(row)) if row else None

    def search_terms(
        self, workspace: str, query: str, limit: int = 50
    ) -> list[GlossaryTerm]:
        """Búsqueda simple en normalized_term y aliases_json por substring."""
        conn = self._connect()
        nq = normalize_term(query)
        rows = conn.execute(
            """SELECT * FROM glossary_terms
               WHERE workspace=? AND enabled=1
                 AND (normalized_term LIKE ? OR aliases_json LIKE ? OR error_forms_json LIKE ?)
               ORDER BY priority DESC
               LIMIT ?""",
            (workspace, f"%{nq}%", f"%{nq}%", f"%{nq}%", limit),
        ).fetchall()
        return [GlossaryTerm.from_row(dict(r)) for r in rows]

    def list_terms(
        self, workspace: str, enabled_only: bool = True, limit: int | None = None
    ) -> list[GlossaryTerm]:
        conn = self._connect()
        sql = "SELECT * FROM glossary_terms WHERE workspace=?"
        params: list = [workspace]
        if enabled_only:
            sql += " AND enabled=1"
        sql += " ORDER BY priority DESC, canonical_term ASC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = conn.execute(sql, params).fetchall()
        return [GlossaryTerm.from_row(dict(r)) for r in rows]

    def stats(self, workspace: str) -> dict:
        """Devuelve estadísticas del glosario para un workspace."""
        conn = self._connect()
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM glossary_terms WHERE workspace=?", (workspace,)
        ).fetchone()["n"]
        enabled = conn.execute(
            "SELECT COUNT(*) AS n FROM glossary_terms WHERE workspace=? AND enabled=1", (workspace,)
        ).fetchone()["n"]
        by_type = conn.execute(
            """SELECT COALESCE(term_type,'(sin tipo)') as t, COUNT(*) as n
               FROM glossary_terms WHERE workspace=?
               GROUP BY t ORDER BY n DESC""",
            (workspace,),
        ).fetchall()
        by_source = conn.execute(
            """SELECT COALESCE(source_kind,'(desconocido)') as s, COUNT(*) as n
               FROM glossary_terms WHERE workspace=?
               GROUP BY s ORDER BY n DESC""",
            (workspace,),
        ).fetchall()
        top = conn.execute(
            """SELECT canonical_term, priority FROM glossary_terms
               WHERE workspace=? AND enabled=1
               ORDER BY priority DESC LIMIT 10""",
            (workspace,),
        ).fetchall()
        return {
            "workspace": workspace,
            "total": total,
            "enabled": enabled,
            "by_type": {r["t"]: r["n"] for r in by_type},
            "by_source": {r["s"]: r["n"] for r in by_source},
            "top_priority": [{"term": r["canonical_term"], "priority": round(r["priority"], 3)} for r in top],
        }
