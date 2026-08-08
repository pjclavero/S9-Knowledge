"""Almacenamiento SQLite con migraciones versionadas para el sistema de auth."""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

from app.auth.models import AuditEvent, PartidaAccess, Session, User

SCHEMA_VERSION = 3

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

# v2 (M5a — multi-partida, docs/v3/49-multipartida-diseno.md §2.6): partida
# activa por sesión + asignaciones usuario->partida gestionadas por admin.
# Decisión de diseño (ver docs/v3/49, subsección "M5a implementado"): el
# visor tiene su PROPIA fuente de verdad de autorización (esta misma base,
# `auth.db`) — no conoce ni depende de `data-engine/app/access/access_store.py`
# (proceso, DB y ciclo de vida distintos; el visor jamás lo ha leído). Añadir
# aquí la asignación usuario->partida, con la misma forma que `users`/
# `sessions`, evita una segunda fuente de verdad y un acoplamiento nuevo entre
# procesos que hoy no existe.
_DDL_V2_ALTER = [
    "ALTER TABLE sessions ADD COLUMN active_partida TEXT",
]

_DDL_V2_CREATE = [
    """
    CREATE TABLE IF NOT EXISTS partida_access (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        workspace TEXT NOT NULL,
        partida_id TEXT NOT NULL,
        granted_by TEXT,
        granted_at TEXT NOT NULL,
        UNIQUE(user_id, workspace, partida_id)
    )
    """,
]

#: v3 (T2) -- la progresión de campaña vive en la CONCESIÓN de partida, no en la
#: petición. `?max_visible_session=99` decidido por el cliente sería una barrera
#: que el propio protegido puede levantar; por eso el dato sale del servidor.
#: NULL significa "sin tope" (narrador, admin, o partida sin progresión).
#: `character_id` es el personaje con el que ese usuario juega esa partida:
#: hasta ahora `active_character` no lo poblaba nadie y `knows()` devolvía
#: siempre False, con lo que todo el mecanismo `known_by` era inerte.
_DDL_V3_ALTER = [
    "ALTER TABLE partida_access ADD COLUMN max_visible_session INTEGER",
    "ALTER TABLE partida_access ADD COLUMN character_id TEXT",
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

            if current < 2:
                for stmt in _DDL_V2_ALTER:
                    try:
                        conn.execute(stmt)
                    except sqlite3.OperationalError as exc:
                        # Columna ya presente (DB creada ya en v2, o reintento
                        # tras fallo parcial): idempotente, no es un error real.
                        if "duplicate column" not in str(exc).lower():
                            raise
                for stmt in _DDL_V2_CREATE:
                    conn.execute(stmt)

            # v3 (T2). Va DESPUÉS de v2 porque altera la tabla que v2 crea.
            if current < 3:
                for stmt in _DDL_V3_ALTER:
                    try:
                        conn.execute(stmt)
                    except sqlite3.OperationalError as exc:
                        if "duplicate column" not in str(exc).lower():
                            raise

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
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:  # None o string vacío (p.ej. locked_until="" al desbloquear)
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
    keys = row.keys()
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
        # Columna añadida en v2: ausente si la conexión ve una DB aún no
        # migrada (no debería ocurrir tras ensure_migrated, pero es fail-safe).
        active_partida=row["active_partida"] if "active_partida" in keys else None,
    )


def _row_to_partida_access(row: sqlite3.Row) -> PartidaAccess:
    return PartidaAccess(
        id=row["id"],
        user_id=row["user_id"],
        workspace=row["workspace"],
        partida_id=row["partida_id"],
        granted_by=row["granted_by"],
        granted_at=_parse_dt(row["granted_at"]),
        max_visible_session=(
            row["max_visible_session"] if "max_visible_session" in row.keys() else None
        ),
        character_id=row["character_id"] if "character_id" in row.keys() else None,
    )


# ---------------------------------------------------------------------------
# Identidad de la base (device/inode) — sanitizada, sin secretos
# ---------------------------------------------------------------------------

def db_identity(db_path: Optional[Path] = None) -> dict:
    """Identidad sanitizada de la base: ruta canónica, device, inode, schema.

    Sirve para demostrar que login, cambio de contraseña y CLI operan sobre el
    MISMO fichero físico. No expone usuarios, hashes ni tokens.
    """
    path = (db_path or _db_path()).resolve()
    info: dict = {
        "path": str(path),
        "exists": path.exists(),
        "device": None,
        "inode": None,
        "size": None,
        "schema_version": None,
    }
    if path.exists():
        st = path.stat()
        info["device"] = st.st_dev
        info["inode"] = st.st_ino
        info["size"] = st.st_size
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            info["schema_version"] = row[0] if row else None
            conn.close()
        except Exception:
            info["schema_version"] = "error"
    return info


def verify_persisted_password(db_path: Path, user_id: int, password: str) -> bool:
    """Verifica un password contra el hash YA PERSISTIDO, con una conexión NUEVA.

    Se usa justo después de un cambio de contraseña (web o CLI): si el hash que
    quedó en disco no verifica el password todavía en memoria, el cambio NO debe
    declararse exitoso. Nunca registra el password.
    """
    from app.auth.passwords import verify_password

    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None:
            return False
        return verify_password(password, row["password_hash"])
    finally:
        conn.close()


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
        # "" significa "sin bloqueo": se persiste como NULL real, no como
        # cadena vacía, para que la columna tenga un único valor de desbloqueo.
        fields.append("locked_until = ?")
        values.append(locked_until or None)
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


# ---------------------------------------------------------------------------
# M5a: partida activa de sesión + asignaciones usuario->partida
# ---------------------------------------------------------------------------

def set_session_active_partida(
    conn: sqlite3.Connection, session_id: int, partida_id: Optional[str]
) -> None:
    """Fija (o limpia, con None) la partida activa de una sesión.

    Una cadena en blanco NO es una partida: se normaliza a None (capa juego),
    para que `""` nunca llegue a `allowed_partida_ids` como si fuese un id.
    """
    if isinstance(partida_id, str) and not partida_id.strip():
        partida_id = None
    conn.execute(
        "UPDATE sessions SET active_partida = ? WHERE id = ?",
        (partida_id, session_id),
    )
    conn.commit()


def grant_partida_access(
    conn: sqlite3.Connection,
    user_id: int,
    workspace: str,
    partida_id: str,
    granted_by: Optional[str] = None,
    max_visible_session: Optional[int] = None,
    character_id: Optional[str] = None,
) -> PartidaAccess:
    """Concede a un usuario acceso a una partida. Idempotente (INSERT OR IGNORE).

    `max_visible_session` y `character_id` son parte de la concesion, no
    decorado: sin ellos la regla de sesion de revelacion no se evalua y
    `knows()` devuelve siempre False. Se anadieron al esquema (v3) y al lector
    antes que aqui, y durante un tiempo NADIE los escribia: la barrera existia,
    estaba probada, y no se aplicaba a ninguna peticion real. Es el mismo
    defecto que se venia persiguiendo, un nivel mas abajo -- por eso hay ahora
    una prueba que exige un productor real para cada campo que el motor consume.
    """
    now = _utcnow()
    if max_visible_session is not None:
        if isinstance(max_visible_session, bool) or not isinstance(max_visible_session, int) \
                or max_visible_session < 0:
            raise ValueError(
                f"max_visible_session invalido: {max_visible_session!r}; "
                "debe ser un entero no negativo o None (sin tope)"
            )
    if character_id is not None and (not isinstance(character_id, str) or not character_id.strip()):
        raise ValueError(f"character_id invalido: {character_id!r}")
    conn.execute(
        """
        INSERT OR IGNORE INTO partida_access
            (user_id, workspace, partida_id, granted_by, granted_at,
             max_visible_session, character_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, workspace, partida_id, granted_by, now,
         max_visible_session, character_id),
    )
    # INSERT OR IGNORE no actualiza una concesion ya existente, y la progresion
    # de campana CAMBIA con cada sesion jugada: sin esto, subir el tope no
    # tendria efecto y el operador creeria haberlo subido.
    # `COALESCE` conservaba el valor anterior cuando se pasaba None, asi que la
    # concesion de personaje NO SE PODIA REVOCAR desde el panel: un operador que
    # reconcedia dejando el campo en blanco creia haberlo quitado y no lo habia
    # quitado. Y `active_character` salta la regla de nivel, o sea que lo que
    # sobrevivia era un bypass invisible en la interfaz. Ahora el UPDATE fija
    # exactamente lo que se declara: reconceder es declarar el estado completo.
    conn.execute(
        "UPDATE partida_access SET max_visible_session = ?, character_id = ? "
        "WHERE user_id = ? AND workspace = ? AND partida_id = ?",
        (max_visible_session, character_id, user_id, workspace, partida_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM partida_access WHERE user_id = ? AND workspace = ? AND partida_id = ?",
        (user_id, workspace, partida_id),
    ).fetchone()
    return _row_to_partida_access(row)


def revoke_partida_access(conn: sqlite3.Connection, access_id: int) -> bool:
    cur = conn.execute("DELETE FROM partida_access WHERE id = ?", (access_id,))
    conn.commit()
    return cur.rowcount > 0


def list_partida_access(
    conn: sqlite3.Connection,
    *,
    user_id: Optional[int] = None,
    workspace: Optional[str] = None,
) -> list[PartidaAccess]:
    where: list[str] = []
    params: list = []
    if user_id is not None:
        where.append("user_id = ?")
        params.append(user_id)
    if workspace is not None:
        where.append("workspace = ?")
        params.append(workspace)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = conn.execute(
        f"SELECT * FROM partida_access {clause} ORDER BY workspace, partida_id", params
    ).fetchall()
    return [_row_to_partida_access(r) for r in rows]


def user_allowed_partidas(
    conn: sqlite3.Connection, user_id: int, workspace: Optional[str] = None
) -> list[str]:
    """Partidas que un usuario puede seleccionar (asignadas por un admin)."""
    return [a.partida_id for a in list_partida_access(conn, user_id=user_id, workspace=workspace)]


def partida_progress(
    conn: sqlite3.Connection, user_id: int, workspace: str, partida_id: str
) -> tuple[Optional[int], Optional[str]]:
    """Progresión de campaña de esa concesión: ``(max_visible_session, character_id)``.

    Es la fuente SERVIDOR del tope de sesión (T2). Nunca llega del cliente: un
    ``?max_visible_session=99`` dejaría que el propio protegido levantara la
    barrera.

    **La ausencia de tope declarado NO significa "sin tope": significa 0.**
    Esto se corrigio tras el quinto dictamen. El arreglo anterior anadio el
    escritor pero lo dejo OPT-IN: `NULL` seguia valiendo "sin limite", y un
    `ALTER TABLE ADD COLUMN` deja a NULL todas las concesiones anteriores --
    justo las que motivaron el hallazgo. La barrera solo actuaba si el operador
    se acordaba de rellenar un campo opcional del formulario.

    Es la misma regla que ya rige el ambito: una propiedad ausente nunca se
    interpreta como el permiso mas amplio. Quien deba ver material no revelado
    lo obtiene por una capacidad EXPLICITA (`can_view_future`, que ya tienen
    reviewer y admin), no por un hueco en una tabla.
    """
    row = conn.execute(
        "SELECT max_visible_session, character_id FROM partida_access "
        "WHERE user_id = ? AND workspace = ? AND partida_id = ?",
        (user_id, workspace, partida_id),
    ).fetchone()
    if row is None:
        # Sin fila de concesion no hay progresion que declarar: 0, no "sin tope".
        return 0, None
    tope = row["max_visible_session"]
    if tope is None or isinstance(tope, bool) or not isinstance(tope, int) or tope < 0:
        # Ausente, NULL heredado de la migracion, o corrupto: el tope mas
        # restrictivo. Un dato que no se puede leer no puede abrir nada.
        tope = 0
    pj = row["character_id"]
    if not isinstance(pj, str) or not pj.strip():
        pj = None
    return tope, pj


def partida_exists(conn: sqlite3.Connection, partida_id: str) -> bool:
    """¿Existe esa partida como asignación de algún usuario?

    Es la única definición de "partida conocida" que tiene el visor hoy (no hay
    catálogo de partidas). Sirve para que un admin no pueda activar una partida
    inventada por error tipográfico.
    """
    if not isinstance(partida_id, str) or not partida_id.strip():
        return False
    row = conn.execute(
        "SELECT 1 FROM partida_access WHERE partida_id = ? LIMIT 1", (partida_id,)
    ).fetchone()
    return row is not None


def get_partida_access_by_id(conn: sqlite3.Connection, access_id: int) -> Optional[PartidaAccess]:
    row = conn.execute("SELECT * FROM partida_access WHERE id = ?", (access_id,)).fetchone()
    return _row_to_partida_access(row) if row else None


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
