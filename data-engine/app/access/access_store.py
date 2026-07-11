"""
access_store.py — Módulo de acceso usuario-personaje, permisos por workspace y audit log.
Usa exclusivamente stdlib de Python (sqlite3, json, uuid, datetime, argparse, os, tempfile).
"""

import sqlite3
import uuid
import json
import argparse
import os
import tempfile
from datetime import datetime, timezone

# ── Constantes ──────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "state", "access.db")

VALID_WORKSPACES = {"leyenda", "mundo_tinieblas", "trudvang", "infrastructure"}

VALID_LINK_STATUSES = {"pending", "approved", "rejected", "revoked", "assigned"}

VALID_AUDIT_EVENTS = {
    "user_character_requested",
    "user_character_approved",
    "user_character_rejected",
    "user_character_assigned_by_admin",
    "user_character_revoked",
    "user_active_character_changed",
    "workspace_permission_changed",
}

# Valores por defecto razonables para permisos de workspace
DEFAULT_PERMISSION_FLAGS = {
    "enabled": 1,
    "role_in_workspace": "player",
    "max_visible_session": 0,
    "can_view_characters": 1,
    "can_view_locations": 1,
    "can_view_creatures": 1,
    "can_view_enemies": 0,
    "can_view_allies": 1,
    "can_view_objects": 1,
    "can_view_events": 1,
    "can_view_timeline": 1,
    "can_view_documents": 1,
    "can_view_images": 1,
    "can_view_relationships": 1,
    "can_view_uncertain_relations": 0,
    "can_view_reference": 0,
    "can_view_narrator": 0,
    "can_view_secret": 0,
    "can_view_future": 0,
}

# ── SQL de creación de tablas ────────────────────────────────────────────────

CREATE_USER_CHARACTER_LINK_SQL = """
CREATE TABLE IF NOT EXISTS user_character_link (
    id                        TEXT PRIMARY KEY,
    username                  TEXT NOT NULL,
    workspace                 TEXT NOT NULL,
    character_id              TEXT NOT NULL,
    character_name            TEXT,
    status                    TEXT NOT NULL DEFAULT 'pending',
    assigned_by_admin         INTEGER NOT NULL DEFAULT 0,
    requested_by_user         INTEGER NOT NULL DEFAULT 0,
    requested_at              TEXT,
    approved_at               TEXT,
    approved_by               TEXT,
    revoked_at                TEXT,
    revoked_by                TEXT,
    is_active_for_workspace   INTEGER NOT NULL DEFAULT 0,
    notes                     TEXT,
    created_at                TEXT NOT NULL,
    updated_at                TEXT NOT NULL
);
"""

CREATE_USER_WORKSPACE_PERMISSION_SQL = """
CREATE TABLE IF NOT EXISTS user_workspace_permission (
    id                          TEXT PRIMARY KEY,
    username                    TEXT NOT NULL,
    workspace                   TEXT NOT NULL,
    enabled                     INTEGER NOT NULL DEFAULT 1,
    role_in_workspace           TEXT,
    max_visible_session         INTEGER NOT NULL DEFAULT 0,
    can_view_characters         INTEGER NOT NULL DEFAULT 1,
    can_view_locations          INTEGER NOT NULL DEFAULT 1,
    can_view_creatures          INTEGER NOT NULL DEFAULT 1,
    can_view_enemies            INTEGER NOT NULL DEFAULT 0,
    can_view_allies             INTEGER NOT NULL DEFAULT 1,
    can_view_objects            INTEGER NOT NULL DEFAULT 1,
    can_view_events             INTEGER NOT NULL DEFAULT 1,
    can_view_timeline           INTEGER NOT NULL DEFAULT 1,
    can_view_documents          INTEGER NOT NULL DEFAULT 1,
    can_view_images             INTEGER NOT NULL DEFAULT 1,
    can_view_relationships      INTEGER NOT NULL DEFAULT 1,
    can_view_uncertain_relations INTEGER NOT NULL DEFAULT 0,
    can_view_reference          INTEGER NOT NULL DEFAULT 0,
    can_view_narrator           INTEGER NOT NULL DEFAULT 0,
    can_view_secret             INTEGER NOT NULL DEFAULT 0,
    can_view_future             INTEGER NOT NULL DEFAULT 0,
    created_at                  TEXT NOT NULL,
    updated_at                  TEXT NOT NULL,
    UNIQUE(username, workspace)
);
"""

CREATE_ACCESS_AUDIT_LOG_SQL = """
CREATE TABLE IF NOT EXISTS access_audit_log (
    id           TEXT PRIMARY KEY,
    ts           TEXT NOT NULL,
    event        TEXT NOT NULL,
    username     TEXT NOT NULL,
    workspace    TEXT NOT NULL,
    character_id TEXT,
    actor        TEXT,
    detail       TEXT
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
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _row_to_dict(row) -> dict:
    if row is None:
        return None
    return dict(row)


def _new_id() -> str:
    return str(uuid.uuid4())


# ── API pública ──────────────────────────────────────────────────────────────

def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Crea las 3 tablas si no existen. Operación idempotente."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with _connect(db_path) as conn:
        conn.execute(CREATE_USER_CHARACTER_LINK_SQL)
        conn.execute(CREATE_USER_WORKSPACE_PERMISSION_SQL)
        conn.execute(CREATE_ACCESS_AUDIT_LOG_SQL)
        conn.commit()


def _audit(conn: sqlite3.Connection, event: str, username: str, workspace: str,
           character_id: str = None, actor: str = None, detail: dict = None) -> None:
    """Inserta una entrada en access_audit_log dentro de la misma conexión."""
    conn.execute(
        """
        INSERT INTO access_audit_log (id, ts, event, username, workspace, character_id, actor, detail)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _new_id(),
            _now_iso(),
            event,
            username,
            workspace,
            character_id,
            actor,
            json.dumps(detail, ensure_ascii=False) if detail is not None else None,
        ),
    )


def request_character(
    username: str,
    workspace: str,
    character_id: str,
    character_name: str = None,
    notes: str = None,
    db_path: str = DEFAULT_DB_PATH,
) -> str:
    """
    Crea un vínculo con status='pending', requested_by_user=1.
    Audita user_character_requested.
    Devuelve el id del link.
    """
    now = _now_iso()
    link_id = _new_id()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO user_character_link
                (id, username, workspace, character_id, character_name, status,
                 assigned_by_admin, requested_by_user, requested_at,
                 is_active_for_workspace, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'pending', 0, 1, ?, 0, ?, ?, ?)
            """,
            (link_id, username, workspace, character_id, character_name, now, notes, now, now),
        )
        _audit(conn, "user_character_requested", username, workspace,
               character_id=character_id, actor=username,
               detail={"link_id": link_id, "character_name": character_name, "notes": notes})
        conn.commit()
    return link_id


def assign_character(
    username: str,
    workspace: str,
    character_id: str,
    character_name: str = None,
    approved_by: str = "admin",
    active: bool = True,
    db_path: str = DEFAULT_DB_PATH,
) -> str:
    """
    Crea un vínculo con status='assigned', assigned_by_admin=1.
    Si active=True pone is_active_for_workspace=1 (y desactiva otros del mismo user+workspace).
    Audita user_character_assigned_by_admin.
    Devuelve el id del link.
    """
    now = _now_iso()
    link_id = _new_id()
    with _connect(db_path) as conn:
        if active:
            conn.execute(
                """
                UPDATE user_character_link
                SET is_active_for_workspace = 0, updated_at = ?
                WHERE username = ? AND workspace = ?
                """,
                (now, username, workspace),
            )
        conn.execute(
            """
            INSERT INTO user_character_link
                (id, username, workspace, character_id, character_name, status,
                 assigned_by_admin, requested_by_user, approved_at, approved_by,
                 is_active_for_workspace, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'assigned', 1, 0, ?, ?, ?, ?, ?)
            """,
            (link_id, username, workspace, character_id, character_name,
             now, approved_by, 1 if active else 0, now, now),
        )
        _audit(conn, "user_character_assigned_by_admin", username, workspace,
               character_id=character_id, actor=approved_by,
               detail={"link_id": link_id, "character_name": character_name, "active": active})
        conn.commit()
    return link_id


def approve_link(
    link_id: str,
    approved_by: str = "admin",
    db_path: str = DEFAULT_DB_PATH,
) -> bool:
    """
    Cambia status a 'approved', registra approved_at y approved_by.
    Audita user_character_approved.
    Devuelve True si se actualizó alguna fila.
    """
    now = _now_iso()
    with _connect(db_path) as conn:
        row = _row_to_dict(
            conn.execute("SELECT * FROM user_character_link WHERE id = ?", (link_id,)).fetchone()
        )
        if row is None:
            return False
        cur = conn.execute(
            """
            UPDATE user_character_link
            SET status = 'approved', approved_at = ?, approved_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, approved_by, now, link_id),
        )
        if cur.rowcount > 0:
            _audit(conn, "user_character_approved", row["username"], row["workspace"],
                   character_id=row["character_id"], actor=approved_by,
                   detail={"link_id": link_id})
        conn.commit()
        return cur.rowcount > 0


def reject_link(
    link_id: str,
    approved_by: str = "admin",
    db_path: str = DEFAULT_DB_PATH,
) -> bool:
    """
    Cambia status a 'rejected'.
    Audita user_character_rejected.
    Devuelve True si se actualizó alguna fila.
    """
    now = _now_iso()
    with _connect(db_path) as conn:
        row = _row_to_dict(
            conn.execute("SELECT * FROM user_character_link WHERE id = ?", (link_id,)).fetchone()
        )
        if row is None:
            return False
        cur = conn.execute(
            """
            UPDATE user_character_link
            SET status = 'rejected', updated_at = ?
            WHERE id = ?
            """,
            (now, link_id),
        )
        if cur.rowcount > 0:
            _audit(conn, "user_character_rejected", row["username"], row["workspace"],
                   character_id=row["character_id"], actor=approved_by,
                   detail={"link_id": link_id})
        conn.commit()
        return cur.rowcount > 0


def revoke_link(
    link_id: str,
    revoked_by: str = "admin",
    db_path: str = DEFAULT_DB_PATH,
) -> bool:
    """
    Cambia status a 'revoked', revoked_at, is_active_for_workspace=0.
    Audita user_character_revoked.
    Devuelve True si se actualizó alguna fila.
    """
    now = _now_iso()
    with _connect(db_path) as conn:
        row = _row_to_dict(
            conn.execute("SELECT * FROM user_character_link WHERE id = ?", (link_id,)).fetchone()
        )
        if row is None:
            return False
        cur = conn.execute(
            """
            UPDATE user_character_link
            SET status = 'revoked', revoked_at = ?, revoked_by = ?,
                is_active_for_workspace = 0, updated_at = ?
            WHERE id = ?
            """,
            (now, revoked_by, now, link_id),
        )
        if cur.rowcount > 0:
            _audit(conn, "user_character_revoked", row["username"], row["workspace"],
                   character_id=row["character_id"], actor=revoked_by,
                   detail={"link_id": link_id})
        conn.commit()
        return cur.rowcount > 0


def set_active_character(
    username: str,
    workspace: str,
    link_id: str,
    db_path: str = DEFAULT_DB_PATH,
) -> bool:
    """
    Pone is_active_for_workspace=1 en el link indicado (debe estar approved o assigned)
    y 0 en los demás de ese user+workspace.
    Audita user_active_character_changed.
    Devuelve True si la operación tuvo efecto.
    """
    now = _now_iso()
    with _connect(db_path) as conn:
        row = _row_to_dict(
            conn.execute("SELECT * FROM user_character_link WHERE id = ?", (link_id,)).fetchone()
        )
        if row is None:
            return False
        if row["status"] not in ("approved", "assigned"):
            raise ValueError(
                f"El link {link_id} tiene status='{row['status']}'; "
                "solo se puede activar un link con status 'approved' o 'assigned'."
            )
        # Desactivar todos los links del mismo user+workspace
        conn.execute(
            """
            UPDATE user_character_link
            SET is_active_for_workspace = 0, updated_at = ?
            WHERE username = ? AND workspace = ?
            """,
            (now, username, workspace),
        )
        # Activar el link solicitado
        conn.execute(
            """
            UPDATE user_character_link
            SET is_active_for_workspace = 1, updated_at = ?
            WHERE id = ?
            """,
            (now, link_id),
        )
        _audit(conn, "user_active_character_changed", username, workspace,
               character_id=row["character_id"], actor=username,
               detail={"link_id": link_id, "character_name": row["character_name"]})
        conn.commit()
        return True


def get_active_character(
    username: str,
    workspace: str,
    db_path: str = DEFAULT_DB_PATH,
) -> dict:
    """Devuelve el dict del link activo (is_active_for_workspace=1) o None."""
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM user_character_link
            WHERE username = ? AND workspace = ? AND is_active_for_workspace = 1
            LIMIT 1
            """,
            (username, workspace),
        ).fetchone()
    return _row_to_dict(row)


def list_links(
    username: str = None,
    workspace: str = None,
    status: str = None,
    db_path: str = DEFAULT_DB_PATH,
) -> list:
    """Lista vínculos usuario-personaje con filtros opcionales."""
    clauses = []
    params = []
    if username:
        clauses.append("username = ?")
        params.append(username)
    if workspace:
        clauses.append("workspace = ?")
        params.append(workspace)
    if status:
        if status not in VALID_LINK_STATUSES:
            raise ValueError(f"Status inválido: '{status}'. Válidos: {sorted(VALID_LINK_STATUSES)}")
        clauses.append("status = ?")
        params.append(status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM user_character_link {where} ORDER BY created_at DESC"
    with _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def set_workspace_permission(
    username: str,
    workspace: str,
    db_path: str = DEFAULT_DB_PATH,
    **flags,
) -> str:
    """
    Upsert de permisos de workspace para un usuario.
    Audita workspace_permission_changed.
    Devuelve el id del registro.
    """
    now = _now_iso()
    with _connect(db_path) as conn:
        existing = _row_to_dict(
            conn.execute(
                "SELECT * FROM user_workspace_permission WHERE username = ? AND workspace = ?",
                (username, workspace),
            ).fetchone()
        )

        if existing is None:
            # INSERT con valores por defecto + flags suministrados
            perm = dict(DEFAULT_PERMISSION_FLAGS)
            perm.update(flags)
            perm_id = _new_id()
            columns = ["id", "username", "workspace", "created_at", "updated_at"] + list(perm.keys())
            values = [perm_id, username, workspace, now, now] + list(perm.values())
            placeholders = ", ".join(["?"] * len(values))
            col_str = ", ".join(columns)
            conn.execute(
                f"INSERT INTO user_workspace_permission ({col_str}) VALUES ({placeholders})",
                values,
            )
            perm_id = perm_id
        else:
            perm_id = existing["id"]
            if flags:
                set_clause = ", ".join(f"{k} = ?" for k in flags) + ", updated_at = ?"
                vals = list(flags.values()) + [now, perm_id]
                conn.execute(
                    f"UPDATE user_workspace_permission SET {set_clause} WHERE id = ?",
                    vals,
                )

        _audit(conn, "workspace_permission_changed", username, workspace,
               actor="admin",
               detail={"flags_changed": flags})
        conn.commit()
    return perm_id


def get_workspace_permission(
    username: str,
    workspace: str,
    db_path: str = DEFAULT_DB_PATH,
) -> dict:
    """Devuelve el dict de permisos o None si no existe."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM user_workspace_permission WHERE username = ? AND workspace = ?",
            (username, workspace),
        ).fetchone()
    return _row_to_dict(row)


def list_audit(
    username: str = None,
    limit: int = 100,
    db_path: str = DEFAULT_DB_PATH,
) -> list:
    """Lista entradas del audit log con filtro opcional por username."""
    params = []
    where = ""
    if username:
        where = "WHERE username = ?"
        params.append(username)
    params.append(limit)
    sql = f"SELECT * FROM access_audit_log {where} ORDER BY ts DESC LIMIT ?"
    with _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


# ── Clase de conveniencia ────────────────────────────────────────────────────

class AccessStore:
    """
    Wrapper orientado a objetos de las funciones del módulo.
    Todos los métodos delegan en las funciones de módulo superiores.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        init_db(self.db_path)

    def request_character(self, username, workspace, character_id,
                          character_name=None, notes=None) -> str:
        return request_character(username, workspace, character_id,
                                 character_name=character_name, notes=notes,
                                 db_path=self.db_path)

    def assign_character(self, username, workspace, character_id,
                         character_name=None, approved_by="admin", active=True) -> str:
        return assign_character(username, workspace, character_id,
                                character_name=character_name, approved_by=approved_by,
                                active=active, db_path=self.db_path)

    def approve_link(self, link_id, approved_by="admin") -> bool:
        return approve_link(link_id, approved_by=approved_by, db_path=self.db_path)

    def reject_link(self, link_id, approved_by="admin") -> bool:
        return reject_link(link_id, approved_by=approved_by, db_path=self.db_path)

    def revoke_link(self, link_id, revoked_by="admin") -> bool:
        return revoke_link(link_id, revoked_by=revoked_by, db_path=self.db_path)

    def set_active_character(self, username, workspace, link_id) -> bool:
        return set_active_character(username, workspace, link_id, db_path=self.db_path)

    def get_active_character(self, username, workspace) -> dict:
        return get_active_character(username, workspace, db_path=self.db_path)

    def list_links(self, username=None, workspace=None, status=None) -> list:
        return list_links(username=username, workspace=workspace,
                          status=status, db_path=self.db_path)

    def set_workspace_permission(self, username, workspace, **flags) -> str:
        return set_workspace_permission(username, workspace, db_path=self.db_path, **flags)

    def get_workspace_permission(self, username, workspace) -> dict:
        return get_workspace_permission(username, workspace, db_path=self.db_path)

    def list_audit(self, username=None, limit=100) -> list:
        return list_audit(username=username, limit=limit, db_path=self.db_path)


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cmd_init(args):
    db_path = args.db or DEFAULT_DB_PATH
    init_db(db_path)
    print(f"Base de datos inicializada: {db_path}")


def _cmd_selftest(_args):
    import sys

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_access.db")
        print(f"[selftest] DB temporal: {db_path}")

        # 1. init_db
        init_db(db_path)
        print("[selftest] init_db OK")

        # 2. assign_character — admin asigna Kakita Asuka a 'pedro' en leyenda
        link_pedro = assign_character(
            username="pedro",
            workspace="leyenda",
            character_id="char-kakita-asuka",
            character_name="Kakita Asuka",
            approved_by="admin",
            active=True,
            db_path=db_path,
        )
        print(f"[selftest] assign_character OK → link_id={link_pedro}")

        # 3. Verificar personaje activo de pedro
        active = get_active_character("pedro", "leyenda", db_path=db_path)
        assert active is not None, "pedro debería tener personaje activo"
        assert active["character_id"] == "char-kakita-asuka"
        assert active["is_active_for_workspace"] == 1
        assert active["status"] == "assigned"
        print(f"[selftest] get_active_character OK → {active['character_name']}")

        # 4. request_character — ana solicita Kimi en leyenda
        link_ana_pending = request_character(
            username="ana",
            workspace="leyenda",
            character_id="char-kimi",
            character_name="Kimi",
            notes="Quiero jugar con este personaje",
            db_path=db_path,
        )
        print(f"[selftest] request_character OK → link_id={link_ana_pending}")

        # Verificar que está pending
        links_ana = list_links(username="ana", db_path=db_path)
        assert len(links_ana) == 1
        assert links_ana[0]["status"] == "pending"
        print("[selftest] list_links (ana, pending) OK")

        # 5. approve_link — admin aprueba la solicitud de ana
        ok = approve_link(link_ana_pending, approved_by="admin", db_path=db_path)
        assert ok, "approve_link debería devolver True"
        links_ana = list_links(username="ana", db_path=db_path)
        assert links_ana[0]["status"] == "approved"
        assert links_ana[0]["approved_by"] == "admin"
        print("[selftest] approve_link OK → status=approved")

        # 6. set_active_character — activar el link aprobado de ana
        ok = set_active_character("ana", "leyenda", link_ana_pending, db_path=db_path)
        assert ok, "set_active_character debería devolver True"
        active_ana = get_active_character("ana", "leyenda", db_path=db_path)
        assert active_ana is not None
        assert active_ana["character_name"] == "Kimi"
        assert active_ana["is_active_for_workspace"] == 1
        print(f"[selftest] set_active_character OK → {active_ana['character_name']} activa")

        # 7. Asignar un segundo personaje a pedro (no activo), luego cambiar activo
        link_pedro2 = assign_character(
            username="pedro",
            workspace="leyenda",
            character_id="char-toshiro",
            character_name="Toshiro",
            approved_by="admin",
            active=False,
            db_path=db_path,
        )
        # pedro debería seguir con Kakita Asuka como activo
        active_pedro = get_active_character("pedro", "leyenda", db_path=db_path)
        assert active_pedro is not None
        assert active_pedro["character_id"] == "char-kakita-asuka", \
            f"Esperado char-kakita-asuka, got {active_pedro['character_id']}"
        print("[selftest] segundo assign sin active=True OK → Kakita Asuka sigue activa")

        # Cambiar a Toshiro como activo
        ok = set_active_character("pedro", "leyenda", link_pedro2, db_path=db_path)
        assert ok
        active_pedro = get_active_character("pedro", "leyenda", db_path=db_path)
        assert active_pedro["character_id"] == "char-toshiro"
        print("[selftest] set_active_character cambio OK → Toshiro ahora activo")

        # 8. set_workspace_permission
        perm_id = set_workspace_permission(
            "pedro", "leyenda",
            can_view_enemies=1,
            can_view_secret=0,
            can_view_narrator=0,
            max_visible_session=5,
            db_path=db_path,
        )
        print(f"[selftest] set_workspace_permission OK → perm_id={perm_id}")

        perm = get_workspace_permission("pedro", "leyenda", db_path=db_path)
        assert perm is not None
        assert perm["can_view_enemies"] == 1
        assert perm["max_visible_session"] == 5
        assert perm["can_view_characters"] == 1  # default
        print(f"[selftest] get_workspace_permission OK → can_view_enemies={perm['can_view_enemies']}, max_visible_session={perm['max_visible_session']}")

        # Actualizar permiso existente (upsert)
        set_workspace_permission("pedro", "leyenda", can_view_secret=1, db_path=db_path)
        perm = get_workspace_permission("pedro", "leyenda", db_path=db_path)
        assert perm["can_view_secret"] == 1
        print("[selftest] upsert de permiso existente OK → can_view_secret=1")

        # 9. revoke_link — revocar link de Toshiro de pedro
        ok = revoke_link(link_pedro2, revoked_by="admin", db_path=db_path)
        assert ok
        links_pedro = list_links(username="pedro", db_path=db_path)
        link_toshiro = next((l for l in links_pedro if l["id"] == link_pedro2), None)
        assert link_toshiro is not None
        assert link_toshiro["status"] == "revoked"
        assert link_toshiro["is_active_for_workspace"] == 0
        print("[selftest] revoke_link OK → Toshiro revocado")

        # pedro ya no tiene activo (Toshiro revocado, Kakita Asuka desactivada antes)
        active_pedro = get_active_character("pedro", "leyenda", db_path=db_path)
        assert active_pedro is None, \
            f"pedro no debería tener activo tras revocar Toshiro, got {active_pedro}"
        print("[selftest] get_active_character tras revocación OK → None")

        # 10. reject_link — asignar a ana un segundo link y rechazarlo
        link_ana2 = request_character(
            username="ana", workspace="leyenda",
            character_id="char-otro", character_name="Otro",
            db_path=db_path,
        )
        ok = reject_link(link_ana2, approved_by="admin", db_path=db_path)
        assert ok
        links_ana = list_links(username="ana", status="rejected", db_path=db_path)
        assert len(links_ana) == 1
        print("[selftest] reject_link OK")

        # 11. list_links con filtros
        all_links = list_links(workspace="leyenda", db_path=db_path)
        print(f"[selftest] list_links(workspace=leyenda) → {len(all_links)} link(s)")
        assert len(all_links) >= 4

        # 12. list_audit
        audit_entries = list_audit(db_path=db_path)
        print(f"[selftest] list_audit → {len(audit_entries)} entrada(s)")
        assert len(audit_entries) >= 7

        # Auditoría de pedro
        audit_pedro = list_audit(username="pedro", db_path=db_path)
        print(f"[selftest] list_audit(username=pedro) → {len(audit_pedro)} entrada(s)")
        assert len(audit_pedro) >= 3

        events = [e["event"] for e in audit_entries]
        assert "user_character_assigned_by_admin" in events
        assert "user_character_requested" in events
        assert "user_character_approved" in events
        assert "user_active_character_changed" in events
        assert "workspace_permission_changed" in events
        assert "user_character_revoked" in events
        assert "user_character_rejected" in events
        print("[selftest] todos los eventos de auditoría presentes OK")

    print("\nOK — selftest completado sin errores.")


def main():
    import sys

    parser = argparse.ArgumentParser(
        description="Módulo de acceso usuario-personaje con permisos y audit log."
    )
    parser.add_argument("--init", action="store_true", help="Crear/verificar la base de datos.")
    parser.add_argument("--selftest", action="store_true", help="Ejecutar selftest con BD temporal.")
    parser.add_argument("--db", default=None, help="Ruta alternativa a access.db")

    args = parser.parse_args()

    if args.selftest:
        _cmd_selftest(args)
    elif args.init:
        _cmd_init(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
