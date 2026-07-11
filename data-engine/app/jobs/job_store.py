"""
job_store.py — Cola de trabajos SQLite para el pipeline de fuentes externas.
Usa exclusivamente stdlib de Python (sqlite3, json, uuid, datetime, re, argparse).
"""

import sqlite3
import uuid
import re
import argparse
import os
import tempfile
from datetime import datetime, timezone

# ── Constantes ──────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "state", "jobs.db")

VALID_STATUSES = {
    "pending", "needs_metadata", "ready", "processing",
    "transcribing", "extracting", "completed", "failed",
    "ignored", "cancelled",
}

VALID_SOURCE_KINDS = {
    "book", "pdf", "audio", "video", "transcript", "text",
    "image", "youtube", "web", "manual_note", "test",
}

# source_kinds que requieren metadatos de sesión si no se proporcionan
METADATA_REQUIRED_KINDS = {"audio", "youtube"}

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id                        TEXT PRIMARY KEY,
    workspace                     TEXT NOT NULL,
    source_kind                   TEXT NOT NULL,
    source_url                    TEXT,
    source_path                   TEXT,
    source_title                  TEXT,
    source_author                 TEXT,
    source_date                   TEXT,
    status                        TEXT NOT NULL DEFAULT 'pending',
    created_at                    TEXT NOT NULL,
    updated_at                    TEXT NOT NULL,
    started_at                    TEXT,
    finished_at                   TEXT,
    error_message                 TEXT,
    requires_metadata             INTEGER NOT NULL DEFAULT 0,
    session_number                INTEGER,
    session_title                 TEXT,
    session_date                  TEXT,
    campaign_arc                  TEXT,
    visibility                    TEXT,
    knowledge_layer               TEXT,
    output_transcript_path        TEXT,
    output_markdown_path          TEXT,
    output_json_path              TEXT,
    neo4j_nodes_created           INTEGER NOT NULL DEFAULT 0,
    neo4j_relationships_created   INTEGER NOT NULL DEFAULT 0,
    manual_review_required_count  INTEGER NOT NULL DEFAULT 0
);
"""


# ── Utilidades internas ──────────────────────────────────────────────────────

def _now_iso() -> str:
    """Devuelve el instante actual en ISO-8601 UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def _row_to_dict(row) -> dict:
    if row is None:
        return None
    return dict(row)


def _validate_status(status: str):
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Estado inválido: '{status}'. Válidos: {sorted(VALID_STATUSES)}"
        )


def _validate_source_kind(source_kind: str):
    if source_kind not in VALID_SOURCE_KINDS:
        raise ValueError(
            f"source_kind inválido: '{source_kind}'. Válidos: {sorted(VALID_SOURCE_KINDS)}"
        )


# ── API pública ──────────────────────────────────────────────────────────────

def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Crea la tabla jobs si no existe. Operación idempotente."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with _connect(db_path) as conn:
        conn.execute(CREATE_TABLE_SQL)
        conn.commit()


def create_job(
    workspace: str,
    source_kind: str,
    source_url: str = None,
    source_path: str = None,
    db_path: str = DEFAULT_DB_PATH,
    **optional,
) -> str:
    """
    Inserta un nuevo trabajo en la cola.

    La lógica de estado inicial es:
    - Si source_kind in {audio, youtube} y no se proporcionan session_number
      ni session_title → status='needs_metadata', requires_metadata=1.
    - En cualquier otro caso → status='pending'.

    Devuelve el job_id (UUID4 como str).
    """
    if not workspace or not workspace.strip():
        raise ValueError("workspace no puede estar vacío.")
    _validate_source_kind(source_kind)

    job_id = str(uuid.uuid4())
    now = _now_iso()

    # Determinar si necesita metadatos
    needs_meta = (
        source_kind in METADATA_REQUIRED_KINDS
        and not optional.get("session_number")
        and not optional.get("session_title")
    )
    status = "needs_metadata" if needs_meta else optional.pop("status", "pending")
    _validate_status(status)

    requires_metadata = 1 if needs_meta else int(optional.pop("requires_metadata", 0))

    # Extraer campos conocidos de optional
    allowed_fields = {
        "source_title", "source_author", "source_date",
        "session_number", "session_title", "session_date",
        "campaign_arc", "visibility", "knowledge_layer",
        "output_transcript_path", "output_markdown_path", "output_json_path",
        "neo4j_nodes_created", "neo4j_relationships_created",
        "manual_review_required_count",
    }
    extra = {k: v for k, v in optional.items() if k in allowed_fields}

    columns = [
        "job_id", "workspace", "source_kind", "source_url", "source_path",
        "status", "created_at", "updated_at", "requires_metadata",
    ]
    values = [
        job_id, workspace, source_kind, source_url, source_path,
        status, now, now, requires_metadata,
    ]

    for k, v in extra.items():
        columns.append(k)
        values.append(v)

    placeholders = ", ".join(["?"] * len(values))
    col_str = ", ".join(columns)
    sql = f"INSERT INTO jobs ({col_str}) VALUES ({placeholders})"

    with _connect(db_path) as conn:
        conn.execute(sql, values)
        conn.commit()

    return job_id


def get_job(job_id: str, db_path: str = DEFAULT_DB_PATH) -> dict:
    """Devuelve el trabajo como dict, o None si no existe."""
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return _row_to_dict(row)


def list_jobs(
    status: str = None,
    workspace: str = None,
    db_path: str = DEFAULT_DB_PATH,
) -> list:
    """Lista trabajos, con filtro opcional por status y/o workspace."""
    if status is not None:
        _validate_status(status)

    clauses = []
    params = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if workspace:
        clauses.append("workspace = ?")
        params.append(workspace)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM jobs {where} ORDER BY created_at DESC"

    with _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_job(job_id: str, db_path: str = DEFAULT_DB_PATH, **fields) -> bool:
    """
    Actualiza campos arbitrarios de un trabajo.
    Actualiza updated_at automáticamente.
    Valida status y source_kind si vienen en fields.
    Devuelve True si se actualizó al menos una fila.
    """
    if not fields:
        return False

    if "status" in fields:
        _validate_status(fields["status"])
    if "source_kind" in fields:
        _validate_source_kind(fields["source_kind"])

    fields["updated_at"] = _now_iso()

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    sql = f"UPDATE jobs SET {set_clause} WHERE job_id = ?"

    with _connect(db_path) as conn:
        cur = conn.execute(sql, values)
        conn.commit()
        return cur.rowcount > 0


def set_status(
    job_id: str,
    status: str,
    error_message: str = None,
    db_path: str = DEFAULT_DB_PATH,
) -> bool:
    """
    Helper para cambiar el estado de un trabajo.
    Ajusta started_at cuando entra en processing/transcribing/extracting
    y finished_at cuando llega a completed/failed/ignored/cancelled.
    """
    _validate_status(status)
    now = _now_iso()

    fields = {"status": status, "updated_at": now}

    if error_message is not None:
        fields["error_message"] = error_message

    if status in {"processing", "transcribing", "extracting"}:
        fields["started_at"] = now

    if status in {"completed", "failed", "ignored", "cancelled"}:
        fields["finished_at"] = now

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    sql = f"UPDATE jobs SET {set_clause} WHERE job_id = ?"

    with _connect(db_path) as conn:
        cur = conn.execute(sql, values)
        conn.commit()
        return cur.rowcount > 0


# ── Inferencia de metadatos desde nombre de archivo ──────────────────────────

# Patrones soportados (en orden de preferencia):
#   "2026-07-10 - Sesion 12 - El Arbol Blanco.m4a"
#   "Sesion 12 - El Arbol Blanco.m4a"
#   "sesion_12_el_arbol_blanco.mp3"
#   "s12 El Arbol Blanco.mp3"

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_SESSION_RE = re.compile(
    r"(?:sesi[oó]n|sesion|s)[_\s\-]*(\d+)",
    re.IGNORECASE,
)
# Separador estilo "Sesion 12 - Titulo"
_TITLE_AFTER_NUM_RE = re.compile(
    r"(?:sesi[oó]n|sesion|s)[_\s\-]*\d+[_\s\-]+(.+)",
    re.IGNORECASE,
)


def infer_session_metadata(filename: str) -> dict:
    """
    Dado un nombre de archivo de audio, intenta inferir:
        - session_number (int o None)
        - session_title (str o None)
        - session_date (str o None, formato YYYY-MM-DD)

    Ejemplos:
        "Sesion 12 - El Arbol Blanco.m4a"
            → {session_number: 12, session_title: 'El Arbol Blanco', session_date: None}
        "2026-07-10 - Sesion 12 - El Arbol Blanco.m4a"
            → {session_number: 12, session_title: 'El Arbol Blanco', session_date: '2026-07-10'}
    """
    # Eliminar extensión
    stem = re.sub(r"\.\w{2,5}$", "", filename).strip()

    # Intentar extraer fecha inicial
    session_date = None
    date_m = _DATE_RE.match(stem)
    if date_m:
        session_date = date_m.group(1)
        # Quitar la fecha del stem para simplificar el análisis posterior
        stem = stem[date_m.end():].lstrip(" -_").strip()

    # Intentar extraer número de sesión
    session_number = None
    num_m = _SESSION_RE.search(stem)
    if num_m:
        session_number = int(num_m.group(1))

    # Intentar extraer título
    session_title = None
    title_m = _TITLE_AFTER_NUM_RE.search(stem)
    if title_m:
        raw_title = title_m.group(1).strip(" -_")
        # Limpiar extensión residual y guiones iniciales/finales
        session_title = re.sub(r"\.\w{2,5}$", "", raw_title).strip(" -_") or None

    return {
        "session_number": session_number,
        "session_title": session_title,
        "session_date": session_date,
    }


# ── Clase de conveniencia ────────────────────────────────────────────────────

class JobStore:
    """
    Wrapper orientado a objetos de las funciones del módulo.
    Todos los métodos delegan en las funciones de módulo superiores.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        init_db(self.db_path)

    def create_job(self, workspace: str, source_kind: str, **kw) -> str:
        return create_job(workspace, source_kind, db_path=self.db_path, **kw)

    def get_job(self, job_id: str) -> dict:
        return get_job(job_id, db_path=self.db_path)

    def list_jobs(self, status: str = None, workspace: str = None) -> list:
        return list_jobs(status=status, workspace=workspace, db_path=self.db_path)

    def update_job(self, job_id: str, **fields) -> bool:
        return update_job(job_id, db_path=self.db_path, **fields)

    def set_status(self, job_id: str, status: str, error_message: str = None) -> bool:
        return set_status(job_id, status, error_message=error_message, db_path=self.db_path)

    @staticmethod
    def infer_session_metadata(filename: str) -> dict:
        return infer_session_metadata(filename)


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cmd_init(args):
    db_path = args.db or DEFAULT_DB_PATH
    init_db(db_path)
    print(f"Base de datos inicializada: {db_path}")


def _cmd_selftest(args):
    import sys

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_jobs.db")
        print(f"[selftest] DB temporal: {db_path}")

        # 1. Inicializar
        init_db(db_path)
        print("[selftest] init_db OK")

        # 2. Crear job de prueba
        job_id = create_job(
            workspace="leyenda",
            source_kind="test",
            source_url="http://ejemplo.local/test",
            source_title="Prueba de selftest",
            db_path=db_path,
        )
        print(f"[selftest] create_job OK → job_id={job_id}")

        # 3. Leer el job
        job = get_job(job_id, db_path=db_path)
        assert job is not None, "get_job devolvió None"
        assert job["workspace"] == "leyenda"
        assert job["source_kind"] == "test"
        assert job["status"] == "pending"
        print(f"[selftest] get_job OK → status={job['status']}")

        # 4. Actualizar a 'completed'
        ok = set_status(job_id, "completed", db_path=db_path)
        assert ok, "set_status no actualizó ninguna fila"
        job = get_job(job_id, db_path=db_path)
        assert job["status"] == "completed"
        assert job["finished_at"] is not None
        print(f"[selftest] set_status OK → status={job['status']}, finished_at={job['finished_at']}")

        # 5. update_job campo libre
        update_job(job_id, neo4j_nodes_created=42, db_path=db_path)
        job = get_job(job_id, db_path=db_path)
        assert job["neo4j_nodes_created"] == 42
        print(f"[selftest] update_job OK → neo4j_nodes_created={job['neo4j_nodes_created']}")

        # 6. list_jobs
        jobs = list_jobs(workspace="leyenda", db_path=db_path)
        assert len(jobs) == 1
        print(f"[selftest] list_jobs OK → {len(jobs)} trabajo(s)")

        # 7. Validación de estado inválido
        try:
            _validate_status("volando")
            print("[selftest] ERROR: debería haber lanzado ValueError para estado inválido")
            sys.exit(1)
        except ValueError:
            print("[selftest] validación de estado inválido OK")

        # 8. Validación de source_kind inválido
        try:
            create_job("leyenda", "ovni", db_path=db_path)
            print("[selftest] ERROR: debería haber lanzado ValueError para source_kind inválido")
            sys.exit(1)
        except ValueError:
            print("[selftest] validación de source_kind inválido OK")

        # 9. needs_metadata para audio sin sesión
        audio_id = create_job(
            workspace="leyenda",
            source_kind="audio",
            source_path="/mnt/audio/sesion_sin_titulo.m4a",
            db_path=db_path,
        )
        audio_job = get_job(audio_id, db_path=db_path)
        assert audio_job["status"] == "needs_metadata", f"Esperado needs_metadata, got {audio_job['status']}"
        assert audio_job["requires_metadata"] == 1
        print(f"[selftest] needs_metadata logic OK → status={audio_job['status']}")

        # 10. infer_session_metadata
        ejemplos = [
            "Sesion 12 - El Arbol Blanco.m4a",
            "2026-07-10 - Sesion 12 - El Arbol Blanco.m4a",
        ]
        for fname in ejemplos:
            meta = infer_session_metadata(fname)
            print(f"[selftest] infer_session_metadata('{fname}') → {meta}")
            assert meta["session_number"] == 12, f"Esperado 12, got {meta['session_number']}"
            assert meta["session_title"] is not None

    print("\nOK — selftest completado sin errores.")


def main():
    parser = argparse.ArgumentParser(
        description="Cola de trabajos SQLite para el pipeline de fuentes externas."
    )
    sub = parser.add_subparsers(dest="cmd")

    p_init = sub.add_parser("--init", help="Crear/verificar la base de datos.")
    p_init.add_argument("--db", default=None, help="Ruta alternativa a jobs.db")

    sub.add_parser("--selftest", help="Ejecutar selftest con BD temporal.")

    # Soporte para llamada directa: python job_store.py --init / --selftest
    args, _ = parser.parse_known_args()

    import sys
    raw = sys.argv[1:]
    if "--selftest" in raw:
        _cmd_selftest(args)
    elif "--init" in raw:
        # Reconstruir con argparse estándar para --db
        p2 = argparse.ArgumentParser()
        p2.add_argument("--init", action="store_true")
        p2.add_argument("--db", default=None)
        a2 = p2.parse_args()
        _cmd_init(a2)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
