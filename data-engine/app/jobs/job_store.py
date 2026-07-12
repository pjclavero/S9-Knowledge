"""
job_store.py — Cola de trabajos SQLite, compartida por dos usos:

1. Pipeline de fuentes externas (histórico): create_job/get_job/list_jobs/
   update_job/set_status con `source_kind` (book, pdf, audio, youtube, ...) y
   el vocabulario de estados rico de ingesta (needs_metadata, processing,
   transcribing, extracting, completed, ignored, ...).
2. Cola de trabajos genérica (Fase v0.2.4 "jobs worker and jobs panel"):
   claim_next_job/mark_running/mark_complete/mark_failed/mark_cancelled/
   mark_skipped/heartbeat/release_stale_jobs/get_counts_by_status, con
   `job_type` (echo, noop, y en el futuro media_probe/audio_extract/
   transcribe/write_markdown/ingest_text/audit_duplicates), `priority`,
   `payload_json`/`result_json` y reintentos (`attempts`/`max_attempts`).

Es la MISMA tabla `jobs` y el MISMO archivo: no se crea una segunda cola.
Los jobs genéricos usan `source_kind='generic'` internamente para satisfacer
la restricción NOT NULL heredada, pero se identifican por `job_type`.

Usa exclusivamente stdlib de Python (sqlite3, json, uuid, datetime, re, argparse).
"""

import json
import sqlite3
import uuid
import re
import argparse
import os
import tempfile
from datetime import datetime, timezone, timedelta

# ── Constantes ──────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "state", "jobs.db")

# Vocabulario de estados: unión de los dos usos (ver docstring del módulo).
# - Ingesta de fuentes (histórico): needs_metadata, ready, processing,
#   transcribing, extracting, completed, ignored.
# - Cola genérica (Fase jobs-worker-panel): running, complete, skipped.
# - Compartidos por ambos: pending, failed, cancelled.
VALID_STATUSES = {
    "pending", "needs_metadata", "ready", "processing",
    "transcribing", "extracting", "completed", "failed",
    "ignored", "cancelled",
    "running", "complete", "skipped",
}

VALID_SOURCE_KINDS = {
    "book", "pdf", "audio", "transcript", "text",
    "image", "youtube", "web", "manual_note", "test",
    # "generic": jobs de la cola genérica, identificados por job_type.
    "generic",
}

# source_kinds que requieren metadatos de sesión si no se proporcionan
METADATA_REQUIRED_KINDS = {"audio", "youtube"}

# Tipos de job previstos para la cola genérica (Fase jobs-worker-panel).
# Solo "noop" y "echo" tienen handler implementado en jobs/worker.py; el
# resto son placeholders para fases futuras (multimedia, ingesta, auditoría).
# job_type NO se valida contra esta lista al crear el job (permite añadir
# tipos nuevos sin tocar job_store.py); es solo documentación + referencia.
KNOWN_JOB_TYPES = {
    "noop", "echo",
    "media_probe", "audio_extract", "transcribe", "write_markdown",
    "ingest_text", "audit_duplicates",
}

# Campos "extra" de la cola genérica, insertables vía create_job(**optional).
_GENERIC_QUEUE_FIELDS = {
    "job_type", "priority", "payload_json", "result_json",
    "attempts", "max_attempts", "locked_by", "locked_at",
}

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
    manual_review_required_count  INTEGER NOT NULL DEFAULT 0,
    job_type                      TEXT,
    priority                      INTEGER NOT NULL DEFAULT 0,
    payload_json                  TEXT,
    result_json                   TEXT,
    attempts                      INTEGER NOT NULL DEFAULT 0,
    max_attempts                  INTEGER NOT NULL DEFAULT 3,
    locked_by                     TEXT,
    locked_at                     TEXT
);
"""

# Columnas añadidas por la Fase jobs-worker-panel, para migrar bases de datos
# creadas con el esquema anterior (ALTER TABLE ADD COLUMN, idempotente).
_MIGRATION_COLUMNS = [
    ("job_type", "TEXT"),
    ("priority", "INTEGER NOT NULL DEFAULT 0"),
    ("payload_json", "TEXT"),
    ("result_json", "TEXT"),
    ("attempts", "INTEGER NOT NULL DEFAULT 0"),
    ("max_attempts", "INTEGER NOT NULL DEFAULT 3"),
    ("locked_by", "TEXT"),
    ("locked_at", "TEXT"),
]


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

def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Añade columnas de la cola genérica si faltan (bases de datos antiguas).

    Idempotente: usa PRAGMA table_info para comprobar qué columnas existen
    antes de intentar el ALTER TABLE, en vez de confiar en capturar la
    excepción "duplicate column name" (más explícito y más portable).
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    for col_name, col_def in _MIGRATION_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_def}")


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Crea la tabla jobs si no existe, y migra el esquema si es antiguo.

    Operación idempotente: segura de llamar en cada arranque (CLI, worker,
    API del viewer).
    """
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with _connect(db_path) as conn:
        conn.execute(CREATE_TABLE_SQL)
        _migrate_schema(conn)
        conn.commit()


def create_job(
    workspace: str,
    source_kind: str = None,
    source_url: str = None,
    source_path: str = None,
    db_path: str = DEFAULT_DB_PATH,
    job_type: str = None,
    payload: dict = None,
    priority: int = 0,
    max_attempts: int = 3,
    **optional,
) -> str:
    """
    Inserta un nuevo trabajo en la cola.

    Dos modos de uso:
    - Ingesta de fuentes (histórico): pasar `source_kind` (book/pdf/audio/...).
      La lógica de estado inicial es: si source_kind in {audio, youtube} y no
      se proporcionan session_number ni session_title → status='needs_metadata',
      requires_metadata=1. En cualquier otro caso → status='pending'.
    - Cola genérica (Fase jobs-worker-panel): pasar `job_type` (echo/noop/...)
      y opcionalmente `payload` (dict, se serializa a payload_json).
      Si no se indica `source_kind`, se usa 'generic' automáticamente.
      Siempre status='pending' (sin lógica de needs_metadata).

    Devuelve el job_id (UUID4 como str).
    """
    if not workspace or not workspace.strip():
        raise ValueError("workspace no puede estar vacío.")

    is_generic = source_kind is None
    if is_generic:
        if not job_type or not job_type.strip():
            raise ValueError("Debe indicarse source_kind o job_type.")
        source_kind = "generic"
    _validate_source_kind(source_kind)

    job_id = str(uuid.uuid4())
    now = _now_iso()

    if is_generic:
        needs_meta = False
        status = optional.pop("status", "pending")
    else:
        # Determinar si necesita metadatos (solo aplica al modo ingesta de fuentes)
        needs_meta = (
            source_kind in METADATA_REQUIRED_KINDS
            and not optional.get("session_number")
            and not optional.get("session_title")
        )
        status = "needs_metadata" if needs_meta else optional.pop("status", "pending")
    _validate_status(status)

    requires_metadata = 1 if needs_meta else int(optional.pop("requires_metadata", 0))

    if job_type is not None:
        optional["job_type"] = job_type
    if payload is not None:
        optional["payload_json"] = json.dumps(payload, ensure_ascii=False)
    if priority:
        optional["priority"] = priority
    if max_attempts != 3:
        optional["max_attempts"] = max_attempts

    # Extraer campos conocidos de optional
    allowed_fields = {
        "source_title", "source_author", "source_date",
        "session_number", "session_title", "session_date",
        "campaign_arc", "visibility", "knowledge_layer",
        "output_transcript_path", "output_markdown_path", "output_json_path",
        "neo4j_nodes_created", "neo4j_relationships_created",
        "manual_review_required_count",
    } | _GENERIC_QUEUE_FIELDS
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
    job_type: str = None,
    limit: int = None,
    db_path: str = DEFAULT_DB_PATH,
) -> list:
    """Lista trabajos, con filtro opcional por status/workspace/job_type/limit."""
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
    if job_type:
        clauses.append("job_type = ?")
        params.append(job_type)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM jobs {where} ORDER BY created_at DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))

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

    if status in {"processing", "transcribing", "extracting", "running"}:
        fields["started_at"] = now

    if status in {"completed", "failed", "ignored", "cancelled", "complete", "skipped"}:
        fields["finished_at"] = now

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    sql = f"UPDATE jobs SET {set_clause} WHERE job_id = ?"

    with _connect(db_path) as conn:
        cur = conn.execute(sql, values)
        conn.commit()
        return cur.rowcount > 0


# ── Cola genérica de trabajos (Fase jobs-worker-panel) ────────────────────────
# Estas funciones son las que usa jobs/worker.py y app/cli/jobs.py. Operan
# sobre la misma tabla `jobs` que el resto del módulo.

def claim_next_job(
    worker_id: str,
    job_types: list = None,
    workspace: str = None,
    db_path: str = DEFAULT_DB_PATH,
) -> dict:
    """
    Reclama atómicamente el siguiente job 'pending' (mayor prioridad primero,
    luego el más antiguo) y lo marca 'running' con locked_by/locked_at/started_at.

    Usa una transacción explícita (BEGIN IMMEDIATE) para evitar que dos
    workers reclamen el mismo job en el uso concurrente sencillo previsto en
    esta fase (un archivo SQLite en modo WAL, pocos workers).

    Devuelve el job (dict) reclamado, o None si no hay ninguno pendiente que
    cumpla los filtros.
    """
    clauses = ["status = 'pending'"]
    params = []
    if job_types:
        placeholders = ", ".join(["?"] * len(job_types))
        clauses.append(f"job_type IN ({placeholders})")
        params.extend(job_types)
    if workspace:
        clauses.append("workspace = ?")
        params.append(workspace)
    where = " AND ".join(clauses)

    now = _now_iso()
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            f"SELECT * FROM jobs WHERE {where} "
            f"ORDER BY priority DESC, created_at ASC LIMIT 1",
            params,
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None

        job_id = row["job_id"]
        conn.execute(
            """
            UPDATE jobs
            SET status = 'running', locked_by = ?, locked_at = ?,
                started_at = ?, updated_at = ?
            WHERE job_id = ? AND status = 'pending'
            """,
            (worker_id, now, now, now, job_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    return get_job(job_id, db_path=db_path)


def mark_running(job_id: str, worker_id: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Marca un job como 'running' y registra quién lo tiene (sin pasar por claim)."""
    now = _now_iso()
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE jobs
            SET status = 'running', locked_by = ?, locked_at = ?,
                started_at = COALESCE(started_at, ?), updated_at = ?
            WHERE job_id = ?
            """,
            (worker_id, now, now, now, job_id),
        )
        conn.commit()
        return cur.rowcount > 0


def mark_complete(job_id: str, result: dict = None, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Marca un job como 'complete', guarda result_json y libera el lock."""
    now = _now_iso()
    result_json = json.dumps(result, ensure_ascii=False) if result is not None else None
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE jobs
            SET status = 'complete', result_json = ?, finished_at = ?,
                updated_at = ?, locked_by = NULL, locked_at = NULL
            WHERE job_id = ?
            """,
            (result_json, now, now, job_id),
        )
        conn.commit()
        return cur.rowcount > 0


def mark_failed(
    job_id: str,
    error_message: str,
    retry: bool = True,
    db_path: str = DEFAULT_DB_PATH,
) -> bool:
    """
    Marca un fallo, incrementa `attempts` y libera el lock.

    Si `retry=True` y attempts (tras incrementar) < max_attempts, el job
    vuelve a 'pending' para que un worker lo reintente más tarde. Si no,
    (o si se agotaron los intentos) queda en 'failed' definitivamente.
    """
    now = _now_iso()
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT attempts, max_attempts FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return False
        attempts = (row["attempts"] or 0) + 1
        # OJO: max_attempts=0 es un valor válido ("sin reintentos"), no debe
        # tratarse como falsy y caer al default 3.
        max_attempts = row["max_attempts"] if row["max_attempts"] is not None else 3

        will_retry = retry and attempts < max_attempts
        new_status = "pending" if will_retry else "failed"

        fields = {
            "attempts": attempts,
            "status": new_status,
            "error_message": error_message,
            "updated_at": now,
            "locked_by": None,
            "locked_at": None,
        }
        if not will_retry:
            fields["finished_at"] = now

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [job_id]
        cur = conn.execute(f"UPDATE jobs SET {set_clause} WHERE job_id = ?", values)
        conn.commit()
        return cur.rowcount > 0


def mark_cancelled(job_id: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Marca un job como 'cancelled' y libera el lock."""
    now = _now_iso()
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE jobs
            SET status = 'cancelled', finished_at = ?, updated_at = ?,
                locked_by = NULL, locked_at = NULL
            WHERE job_id = ?
            """,
            (now, now, job_id),
        )
        conn.commit()
        return cur.rowcount > 0


def mark_skipped(job_id: str, message: str = "", db_path: str = DEFAULT_DB_PATH) -> bool:
    """
    Marca un job como 'skipped' (no es un fallo: p.ej. job_type sin handler
    implementado todavía). Libera el lock.
    """
    now = _now_iso()
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE jobs
            SET status = 'skipped', error_message = ?, finished_at = ?,
                updated_at = ?, locked_by = NULL, locked_at = NULL
            WHERE job_id = ?
            """,
            (message or None, now, now, job_id),
        )
        conn.commit()
        return cur.rowcount > 0


def heartbeat(job_id: str, worker_id: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    """
    Actualiza locked_at para probar que el worker sigue vivo procesando el
    job. Solo tiene efecto si el job sigue 'running' y bloqueado por ese
    worker_id (evita que un worker viejo reviva un job ya liberado/reasignado).
    """
    now = _now_iso()
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE jobs
            SET locked_at = ?, updated_at = ?
            WHERE job_id = ? AND status = 'running' AND locked_by = ?
            """,
            (now, now, job_id, worker_id),
        )
        conn.commit()
        return cur.rowcount > 0


def release_stale_jobs(timeout_seconds: int, db_path: str = DEFAULT_DB_PATH) -> list:
    """
    Busca jobs 'running' cuyo locked_at sea más antiguo que `timeout_seconds`
    (worker probablemente muerto/colgado sin heartbeat) y los recupera:
    - si les quedan reintentos (attempts < max_attempts): vuelven a 'pending'.
    - si no: pasan a 'failed' con un mensaje claro.

    Devuelve la lista de job_id afectados. No se pierde ningún job: siempre
    queda en un estado terminal o vuelve a la cola.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    now = _now_iso()
    affected: list = []
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT job_id, attempts, max_attempts FROM jobs "
            "WHERE status = 'running' AND locked_at IS NOT NULL AND locked_at < ?",
            (cutoff,),
        ).fetchall()
        for row in rows:
            job_id = row["job_id"]
            attempts = row["attempts"] or 0
            # max_attempts=0 es válido ("sin reintentos"); no caer al default 3.
            max_attempts = row["max_attempts"] if row["max_attempts"] is not None else 3
            if attempts < max_attempts:
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'pending', locked_by = NULL, locked_at = NULL,
                        updated_at = ?,
                        error_message = 'liberado: worker sin actividad (stale)'
                    WHERE job_id = ?
                    """,
                    (now, job_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'failed', locked_by = NULL, locked_at = NULL,
                        updated_at = ?, finished_at = ?,
                        error_message = 'fallido: worker sin actividad (stale) y sin reintentos'
                    WHERE job_id = ?
                    """,
                    (now, now, job_id),
                )
            affected.append(job_id)
        conn.commit()
    return affected


def get_counts_by_status(workspace: str = None, db_path: str = DEFAULT_DB_PATH) -> dict:
    """Devuelve {status: count} para el workspace (o global si no se indica)."""
    where = ""
    params = []
    if workspace:
        where = "WHERE workspace = ?"
        params.append(workspace)
    sql = f"SELECT status, COUNT(*) AS n FROM jobs {where} GROUP BY status"
    with _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return {row["status"]: row["n"] for row in rows}


def resolve_db_path(db_path: str = None) -> str:
    """Resuelve la ruta de jobs.db: argumento explícito > S9K_JOBS_DB > default."""
    if db_path:
        return db_path
    return os.environ.get("S9K_JOBS_DB") or DEFAULT_DB_PATH


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

    def create_job(self, workspace: str, source_kind: str = None, **kw) -> str:
        return create_job(workspace, source_kind, db_path=self.db_path, **kw)

    def get_job(self, job_id: str) -> dict:
        return get_job(job_id, db_path=self.db_path)

    def list_jobs(self, status: str = None, workspace: str = None,
                  job_type: str = None, limit: int = None) -> list:
        return list_jobs(status=status, workspace=workspace, job_type=job_type,
                         limit=limit, db_path=self.db_path)

    def update_job(self, job_id: str, **fields) -> bool:
        return update_job(job_id, db_path=self.db_path, **fields)

    def set_status(self, job_id: str, status: str, error_message: str = None) -> bool:
        return set_status(job_id, status, error_message=error_message, db_path=self.db_path)

    # ── Cola genérica ──────────────────────────────────────────────────────
    def claim_next_job(self, worker_id: str, job_types: list = None,
                       workspace: str = None) -> dict:
        return claim_next_job(worker_id, job_types=job_types, workspace=workspace,
                              db_path=self.db_path)

    def mark_running(self, job_id: str, worker_id: str) -> bool:
        return mark_running(job_id, worker_id, db_path=self.db_path)

    def mark_complete(self, job_id: str, result: dict = None) -> bool:
        return mark_complete(job_id, result=result, db_path=self.db_path)

    def mark_failed(self, job_id: str, error_message: str, retry: bool = True) -> bool:
        return mark_failed(job_id, error_message, retry=retry, db_path=self.db_path)

    def mark_cancelled(self, job_id: str) -> bool:
        return mark_cancelled(job_id, db_path=self.db_path)

    def mark_skipped(self, job_id: str, message: str = "") -> bool:
        return mark_skipped(job_id, message=message, db_path=self.db_path)

    def heartbeat(self, job_id: str, worker_id: str) -> bool:
        return heartbeat(job_id, worker_id, db_path=self.db_path)

    def release_stale_jobs(self, timeout_seconds: int) -> list:
        return release_stale_jobs(timeout_seconds, db_path=self.db_path)

    def get_counts_by_status(self, workspace: str = None) -> dict:
        return get_counts_by_status(workspace=workspace, db_path=self.db_path)

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
