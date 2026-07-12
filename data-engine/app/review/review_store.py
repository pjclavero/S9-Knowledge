"""Persistencia de estados de revisión.

Guarda el estado de cada source_id en JSON (un fichero por source)
y opcionalmente en SQLite (state/reviews.db).
"""
from __future__ import annotations
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

log = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS review_states (
    source_id TEXT NOT NULL,
    workspace TEXT NOT NULL,
    step TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    details TEXT,
    PRIMARY KEY (source_id, workspace, step)
);
"""


class ReviewStore:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self._db_path = repo_root / "state" / "reviews.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        try:
            con = sqlite3.connect(str(self._db_path))
            con.execute(_SCHEMA_SQL)
            con.commit()
            con.close()
        except Exception as e:
            log.warning("No se pudo inicializar reviews.db: %s", e)

    def save_step(
        self,
        workspace: str,
        source_id: str,
        step: str,
        status: str,
        details: dict | None = None,
    ):
        """Guarda el estado de un paso del pipeline."""
        now = datetime.now(timezone.utc).isoformat()
        # JSON por source
        state_dir = self.repo_root / "output" / "reviews" / workspace / source_id
        state_dir.mkdir(parents=True, exist_ok=True)
        state_file = state_dir / "pipeline_state.json"
        state: dict = {}
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:
                state = {}
        state[step] = {"status": status, "updated_at": now, "details": details or {}}
        state_file.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # SQLite
        try:
            con = sqlite3.connect(str(self._db_path))
            con.execute(
                "INSERT OR REPLACE INTO review_states VALUES (?,?,?,?,?,?)",
                (source_id, workspace, step, status, now, json.dumps(details or {})),
            )
            con.commit()
            con.close()
        except Exception as e:
            log.warning("No se pudo guardar en reviews.db: %s", e)

    def get_state(self, workspace: str, source_id: str) -> dict:
        state_file = (
            self.repo_root / "output" / "reviews" / workspace / source_id / "pipeline_state.json"
        )
        if state_file.exists():
            try:
                return json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}
