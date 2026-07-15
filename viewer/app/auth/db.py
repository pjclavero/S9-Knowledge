"""Almacenamiento SQLite con migraciones versionadas para el sistema de auth."""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional

from app.auth.models import AuditEvent, Session, User

SCHEMA_VERSION = 1

_DB_PATH_DEFAULT = "viewer/state/auth.db"
_local = threading.local()

# ---------------------------------------------------------------------------
# Ruta configurable
# ---------------------------------------------------------------------------

def _db_path() -> Path:
    raw = os.environ.get("S9K_AUTH_DB_PATH", _DB_PATH_DEFAULT)
    p = Path(raw)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------------

def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_conn(db_path: Optional[Path] = None) -> Generator[sqlite3.Connection, None, None]:
    """
    Proporciona una conexión SQLite.
    Crea una conexión nueva por llamada; la cierra al salir del bloque.
    Usar como: `with get_conn(path) as conn: ...`
    """
    path = db_path or _db_path()
    conn = _connect(path)
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# DDL de tablas
# ---------------------------------------------------------------------------

_DDL = [
    # v1
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'viewer',
        is_active INTEGER NOT NULL DEFAULT 1,
        must_change_password INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_login_at TEXT,
        failed_login_count INTEGER NOT NULL DEFAULT 0,
        locked_until TEXT,
        created_by TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        session_hash TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        revoked_at TEXT,
        ip_hash TEXT,
        user_agent_hash TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        user_id INTEGER,
        username_snapshot TEXT,
        event_type TEXT NOT NULL,
        result TEXT NOT NULL,
        route TEXT,
        method TEXT,
        ip_hash TEXT,
        user_agent_hash TEXT,
        metadata_json TEXT
    )
    """,
]


# ---------------------------------------------------------------------------
# Migraciones
# ---------------------------------------------------------------------------

def _current_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return row[0] or 0
    except Exception:
        return 0


def migrate(db_path: Optional[Path] = None) -> None:
    """Aplica migraciones pendientes con bloqueo de archivo para evitar concurrencia."""
    path = db_path or _db_path()
    lock_path = path.with_suffix(".lock")

    with open(lock_path, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            conn = _connect(path)
            current = _current_version(conn)
            if current >= SCHEMA_VERSION:
                conn.close()
                return

            # Backup antes de migrar
            if path.exists() and path.stat().st_size > 0:
                backup = path.with_suffix(f".bak.v{current}")
                shutil.copy2(str(path), str(backup))

            for stmt in _DDL:
                conn.execute(stmt)

            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, _utcnow()),
            )
            conn.commit()
            conn.close()
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def ensure_migrated(db_path: Optional[Path] = None) -> None:
    """Ejecuta migrate() si la DB necesita actualización."""
    path = db_path or _db_path()
    conn = _connect(path)
    v = _current_version(conn)
    conn.close()
    if v < SCHEMA_VERSION:
        migrate(path)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.utcnow().isoformat()


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if s is None:
        return None
    return datetime.fromisoformat(s)


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        password_hash=row["password_hash"],
        role=row["role"],
        is_active=bool(row["is_active"]),
        must_change_password=bool(row["must_change_password"]),
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
        last_login_at=_parse_dt(row["last_login_at"]),
        failed_login_count=row["failed_login_count"],
        locked_until=_parse_dt(row["locked_until"]),
        created_by=row["created_by"],
    )


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        user_id=row["user_id"],
        session_hash=row["session_hash"],
        created_at=_parse_dt(row["created_at"]),
        expires_at=_parse_dt(row["expires_at"]),
        last_seen_at=_parse_dt(row["last_seen_at"]),
        revoked_at=_parse_dt(row["revoked_at"]),
        ip_hash=row["ip_hash"],
        user_agent_hash=row["user_agent_hash"],
    )


# ---------------------------------------------------------------------------
# CRUD de usuarios
# ---------------------------------------------------------------------------

def create_user(
    conn: sqlite3.Connection,
    username: str,
    display_name: str,
    password_hash: str,
    role: str = "viewer",
    must_change_password: bool = False,
    created_by: Optional[str] = None,
) -> User:
    now = _utcnow()
    cur = conn.execute(
        """
        INSERT INTO users
            (username, display_name, password_hash, role, is_active, must_change_password,
             created_at, updated_at, failed_login_count, created_by)
        VALUES (?, ?, ?, ?, 1, ?, ?, ?, 0, ?)
        """,
        (username, display_name, password_hash, role, int(must_change_password), now, now, created_by),
    )
    conn.commit()
    return get_user_by_id(conn, cur.lastrowid)


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> Optional[User]:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_username(conn: sqlite3.Connection, username: str) -> Optional[User]:
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return _row_to_user(row) if row else None


def list_users(conn: sqlite3.Connection) -> list[User]:
    rows = conn.execute("SELECT * FROM users ORDER BY username").fetchall()
    return [_row_to_user(r) for r in rows]


def update_user(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    display_name: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    must_change_password: Optional[bool] = None,
    password_hash: Optional[str] = None,
    last_login_at: Optional[str] = None,
    failed_login_count: Optional[int] = None,
    locked_until: Optional[str] = None,
) -> Optional[User]:
    fields: list[str] = ["updated_at = ?"]
    values: list = [_utcnow()]
    if display_name is not None:
        fields.append("display_name = ?")
        values.append(display_name)
    if role is not None:
        fields.append("role = ?")
        values.append(role)
    if is_active is not None:
        fields.append("is_active = ?")
        values.append(int(is_active))
    if must_change_password is not None:
        fields.append("must_change_password = ?")
        values.append(int(must_change_password))
    if password_hash is not None:
        fields.append("password_hash = ?")
        values.append(password_hash)
    if last_login_at is not None:
        fields.append("last_login_at = ?")
        values.append(last_login_at)
    if failed_login_count is not None:
        fields.append("failed_login_count = ?")
        values.append(failed_login_count)
    if locked_until is not None:
        fields.append("locked_until = ?")
        values.append(locked_until)
    values.append(user_id)
    conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    return get_user_by_id(conn, user_id)


def count_active_admins(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
    ).fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# CRUD de sesiones
# ---------------------------------------------------------------------------

def create_session(
    conn: sqlite3.Connection,
    user_id: int,
    session_hash: str,
    expires_at: str,
    ip_hash: Optional[str] = None,
    user_agent_hash: Optional[str] = None,
) -> Session:
    now = _utcnow()
    cur = conn.execute(
        """
        INSERT INTO sessions
            (user_id, session_hash, created_at, expires_at, last_seen_at, ip_hash, user_agent_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, session_hash, now, expires_at, now, ip_hash, user_agent_hash),
    )
    conn.commit()
    return get_session_by_id(conn, cur.lastrowid)


def get_session_by_id(conn: sqlite3.Connection, session_id: int) -> Optional[Session]:
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return _row_to_session(row) if row else None


def get_session_by_hash(conn: sqlite3.Connection, session_hash: str) -> Optional[Session]:
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_hash = ?", (session_hash,)
    ).fetchone()
    return _row_to_session(row) if row else None


def update_session_last_seen(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute(
        "UPDATE sessions SET last_seen_at = ? WHERE id = ?",
        (_utcnow(), session_id),
    )
    conn.commit()


def revoke_session(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute(
        "UPDATE sessions SET revoked_at = ? WHERE id = ?",
        (_utcnow(), session_id),
    )
    conn.commit()


def revoke_sessions_for_user(conn: sqlite3.Connection, user_id: int) -> int:
    now = _utcnow()
    cur = conn.execute(
        "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
        (now, user_id),
    )
    conn.commit()
    return cur.rowcount


def cleanup_expired_sessions(conn: sqlite3.Connection) -> int:
    now = _utcnow()
    cur = conn.execute(
        "DELETE FROM sessions WHERE expires_at < ? AND revoked_at IS NOT NULL",
        (now,),
    )
    conn.commit()
    return cur.rowcount


# ---------------------------------------------------------------------------
# CRUD de auditoría
# ---------------------------------------------------------------------------

def log_audit_event(
    conn: sqlite3.Connection,
    event_type: str,
    result: str,
    *,
    user_id: Optional[int] = None,
    username_snapshot: Optional[str] = None,
    route: Optional[str] = None,
    method: Optional[str] = None,
    ip_hash: Optional[str] = None,
    user_agent_hash: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_events
            (created_at, user_id, username_snapshot, event_type, result,
             route, method, ip_hash, user_agent_hash, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _utcnow(),
            user_id,
            username_snapshot,
            event_type,
            result,
            route,
            method,
            ip_hash,
            user_agent_hash,
            json.dumps(metadata, ensure_ascii=False) if metadata else None,
        ),
    )
    conn.commit()


def list_audit_events(
    conn: sqlite3.Connection,
    *,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    event_type: Optional[str] = None,
    result: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditEvent]:
    where: list[str] = []
    params: list = []
    if user_id is not None:
        where.append("user_id = ?")
        params.append(user_id)
    if username is not None:
        where.append("username_snapshot = ?")
        params.append(username)
    if event_type is not None:
        where.append("event_type = ?")
        params.append(event_type)
    if result is not None:
        where.append("result = ?")
        params.append(result)
    if date_from is not None:
        where.append("created_at >= ?")
        params.append(date_from)
    if date_to is not None:
        where.append("created_at <= ?")
        params.append(date_to)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    params += [limit, offset]
    rows = conn.execute(
        f"SELECT * FROM audit_events {clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params,
    ).fetchall()
    return [_row_to_audit(r) for r in rows]


def count_audit_events(
    conn: sqlite3.Connection,
    *,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    event_type: Optional[str] = None,
    result: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> int:
    where: list[str] = []
    params: list = []
    if user_id is not None:
        where.append("user_id = ?")
        params.append(user_id)
    if username is not None:
        where.append("username_snapshot = ?")
        params.append(username)
    if event_type is not None:
        where.append("event_type = ?")
        params.append(event_type)
    if result is not None:
        where.append("result = ?")
        params.append(result)
    if date_from is not None:
        where.append("created_at >= ?")
        params.append(date_from)
    if date_to is not None:
        where.append("created_at <= ?")
        params.append(date_to)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    row = conn.execute(f"SELECT COUNT(*) FROM audit_events {clause}", params).fetchone()
    return row[0] if row else 0


def _row_to_audit(row: sqlite3.Row) -> AuditEvent:
    return AuditEvent(
        id=row["id"],
        created_at=_parse_dt(row["created_at"]),
        user_id=row["user_id"],
        username_snapshot=row["username_snapshot"],
        event_type=row["event_type"],
        result=row["result"],
        route=row["route"],
        method=row["method"],
        ip_hash=row["ip_hash"],
        user_agent_hash=row["user_agent_hash"],
        metadata_json=row["metadata_json"],
    )
