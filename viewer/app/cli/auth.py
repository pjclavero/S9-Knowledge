"""CLI administrativa de autenticación.

Uso:
  python -m viewer.app.cli.auth <comando> [opciones]

Comandos disponibles:
  create-admin        Crea usuario administrador
  create-user         Crea usuario con rol especificado
  list-users          Lista todos los usuarios
  set-password        Cambia contraseña de un usuario
  set-role            Cambia el rol de un usuario
  enable-user         Activa un usuario
  disable-user        Desactiva un usuario
  unlock-user         Desbloquea una cuenta bloqueada
  revoke-sessions     Revoca sesiones de un usuario
  cleanup-sessions    Elimina sesiones expiradas
  status              Muestra estado del sistema de auth
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

# Ajustar PYTHONPATH para que funcione como módulo standalone
_HERE = Path(__file__).resolve()
_VIEWER_ROOT = _HERE.parents[3]  # viewer/
if str(_VIEWER_ROOT) not in sys.path:
    sys.path.insert(0, str(_VIEWER_ROOT))

from app.auth import audit, db as auth_db
from app.auth.config import get_auth_settings
from app.auth.models import ROLES
from app.auth.passwords import hash_password, validate_password


def _get_db_path() -> Path:
    cfg = get_auth_settings()
    p = Path(cfg.S9K_AUTH_DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _ensure_db() -> Path:
    path = _get_db_path()
    auth_db.ensure_migrated(path)
    return path


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------

def cmd_create_admin(args: argparse.Namespace) -> int:
    print("=== Crear administrador ===")
    username = input("Username: ").strip()
    if not username:
        print("Error: username vacío.", file=sys.stderr)
        return 1
    display_name = input("Display name: ").strip() or username
    password = getpass.getpass("Password: ")
    password2 = getpass.getpass("Confirmar password: ")
    if password != password2:
        print("Error: las contraseñas no coinciden.", file=sys.stderr)
        return 1
    errors = validate_password(password, username)
    if errors:
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        return 1

    db_path = _ensure_db()
    with auth_db.get_conn(db_path) as conn:
        existing = auth_db.get_user_by_username(conn, username)
        if existing:
            print(f"Error: el usuario '{username}' ya existe.", file=sys.stderr)
            return 1
        pw_hash = hash_password(password)
        user = auth_db.create_user(
            conn, username=username, display_name=display_name,
            password_hash=pw_hash, role="admin",
            must_change_password=False, created_by="cli",
        )
        audit.log(conn, audit.USER_CREATED, "success",
                  user_id=user.id, username_snapshot=user.username,
                  metadata={"created_by": "cli", "role": "admin"})
    print(f"Admin '{username}' creado (id={user.id}).")
    return 0


def cmd_create_user(args: argparse.Namespace) -> int:
    print("=== Crear usuario ===")
    username = input("Username: ").strip()
    if not username:
        print("Error: username vacío.", file=sys.stderr)
        return 1
    display_name = input("Display name: ").strip() or username
    role = input(f"Rol ({'/'.join(ROLES)}): ").strip()
    if role not in ROLES:
        print(f"Error: rol inválido '{role}'.", file=sys.stderr)
        return 1
    password = getpass.getpass("Password: ")
    password2 = getpass.getpass("Confirmar password: ")
    if password != password2:
        print("Error: las contraseñas no coinciden.", file=sys.stderr)
        return 1
    errors = validate_password(password, username)
    if errors:
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        return 1

    db_path = _ensure_db()
    with auth_db.get_conn(db_path) as conn:
        existing = auth_db.get_user_by_username(conn, username)
        if existing:
            print(f"Error: el usuario '{username}' ya existe.", file=sys.stderr)
            return 1
        pw_hash = hash_password(password)
        user = auth_db.create_user(
            conn, username=username, display_name=display_name,
            password_hash=pw_hash, role=role,
            must_change_password=True, created_by="cli",
        )
        audit.log(conn, audit.USER_CREATED, "success",
                  user_id=user.id, username_snapshot=user.username,
                  metadata={"created_by": "cli", "role": role})
    print(f"Usuario '{username}' creado (id={user.id}, role={role}).")
    return 0


def cmd_list_users(args: argparse.Namespace) -> int:
    db_path = _ensure_db()
    with auth_db.get_conn(db_path) as conn:
        users = auth_db.list_users(conn)
    if not users:
        print("No hay usuarios.")
        return 0
    print(f"{'ID':>4} {'USERNAME':<20} {'DISPLAY':<25} {'ROLE':<10} {'ACTIVE':<7} {'LOCKED'}")
    for u in users:
        locked = "SI" if u.is_locked() else "-"
        active = "SI" if u.is_active else "NO"
        print(f"{u.id:>4} {u.username:<20} {u.display_name:<25} {u.role:<10} {active:<7} {locked}")
    return 0


def cmd_set_password(args: argparse.Namespace) -> int:
    username = getattr(args, "username", None) or input("Username: ").strip()
    password = getpass.getpass("Nueva contraseña: ")
    password2 = getpass.getpass("Confirmar: ")
    if password != password2:
        print("Error: las contraseñas no coinciden.", file=sys.stderr)
        return 1
    errors = validate_password(password, username)
    if errors:
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        return 1

    db_path = _ensure_db()
    with auth_db.get_conn(db_path) as conn:
        user = auth_db.get_user_by_username(conn, username)
        if user is None:
            print(f"Error: usuario '{username}' no encontrado.", file=sys.stderr)
            return 1
        pw_hash = hash_password(password)
        auth_db.update_user(conn, user.id, password_hash=pw_hash, must_change_password=False)
        auth_db.revoke_sessions_for_user(conn, user.id)
        audit.log(conn, audit.PASSWORD_CHANGED, "success",
                  user_id=user.id, username_snapshot=user.username,
                  metadata={"changed_by": "cli"})
    print(f"Contraseña de '{username}' actualizada. Sesiones revocadas.")
    return 0


def cmd_set_role(args: argparse.Namespace) -> int:
    username = getattr(args, "username", None) or input("Username: ").strip()
    role = getattr(args, "role", None) or input(f"Rol ({'/'.join(ROLES)}): ").strip()
    if role not in ROLES:
        print(f"Error: rol inválido '{role}'.", file=sys.stderr)
        return 1

    db_path = _ensure_db()
    with auth_db.get_conn(db_path) as conn:
        user = auth_db.get_user_by_username(conn, username)
        if user is None:
            print(f"Error: usuario '{username}' no encontrado.", file=sys.stderr)
            return 1
        if user.role == "admin" and role != "admin":
            if auth_db.count_active_admins(conn) <= 1 and user.is_active:
                print("Error: no se puede degradar al único admin activo.", file=sys.stderr)
                return 1
        auth_db.update_user(conn, user.id, role=role)
        audit.log(conn, audit.ROLE_CHANGED, "success",
                  user_id=user.id, username_snapshot=user.username,
                  metadata={"role_before": user.role, "role_after": role, "changed_by": "cli"})
    print(f"Rol de '{username}' cambiado a '{role}'.")
    return 0


def cmd_enable_user(args: argparse.Namespace) -> int:
    username = getattr(args, "username", None) or input("Username: ").strip()
    db_path = _ensure_db()
    with auth_db.get_conn(db_path) as conn:
        user = auth_db.get_user_by_username(conn, username)
        if user is None:
            print(f"Error: usuario '{username}' no encontrado.", file=sys.stderr)
            return 1
        auth_db.update_user(conn, user.id, is_active=True)
        audit.log(conn, audit.USER_ENABLED, "success",
                  user_id=user.id, username_snapshot=user.username,
                  metadata={"changed_by": "cli"})
    print(f"Usuario '{username}' activado.")
    return 0


def cmd_disable_user(args: argparse.Namespace) -> int:
    username = getattr(args, "username", None) or input("Username: ").strip()
    db_path = _ensure_db()
    with auth_db.get_conn(db_path) as conn:
        user = auth_db.get_user_by_username(conn, username)
        if user is None:
            print(f"Error: usuario '{username}' no encontrado.", file=sys.stderr)
            return 1
        if user.role == "admin" and user.is_active:
            if auth_db.count_active_admins(conn) <= 1:
                print("Error: no se puede desactivar al único admin activo.", file=sys.stderr)
                return 1
        auth_db.update_user(conn, user.id, is_active=False)
        auth_db.revoke_sessions_for_user(conn, user.id)
        audit.log(conn, audit.USER_DISABLED, "success",
                  user_id=user.id, username_snapshot=user.username,
                  metadata={"changed_by": "cli"})
    print(f"Usuario '{username}' desactivado. Sesiones revocadas.")
    return 0


def cmd_unlock_user(args: argparse.Namespace) -> int:
    username = getattr(args, "username", None) or input("Username: ").strip()
    db_path = _ensure_db()
    with auth_db.get_conn(db_path) as conn:
        user = auth_db.get_user_by_username(conn, username)
        if user is None:
            print(f"Error: usuario '{username}' no encontrado.", file=sys.stderr)
            return 1
        auth_db.update_user(conn, user.id, failed_login_count=0, locked_until="")
        audit.log(conn, audit.USER_UPDATED, "success",
                  user_id=user.id, username_snapshot=user.username,
                  metadata={"action": "unlock", "changed_by": "cli"})
    print(f"Cuenta de '{username}' desbloqueada.")
    return 0


def cmd_revoke_sessions(args: argparse.Namespace) -> int:
    username = getattr(args, "username", None) or input("Username: ").strip()
    db_path = _ensure_db()
    with auth_db.get_conn(db_path) as conn:
        user = auth_db.get_user_by_username(conn, username)
        if user is None:
            print(f"Error: usuario '{username}' no encontrado.", file=sys.stderr)
            return 1
        count = auth_db.revoke_sessions_for_user(conn, user.id)
        audit.log(conn, audit.SESSIONS_REVOKED, "success",
                  user_id=user.id, username_snapshot=user.username,
                  metadata={"sessions_revoked": count, "changed_by": "cli"})
    print(f"Sesiones de '{username}' revocadas ({count}).")
    return 0


def cmd_cleanup_sessions(args: argparse.Namespace) -> int:
    db_path = _ensure_db()
    with auth_db.get_conn(db_path) as conn:
        count = auth_db.cleanup_expired_sessions(conn)
    print(f"Sesiones expiradas eliminadas: {count}.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    db_path = _get_db_path()
    cfg = get_auth_settings()
    print(f"S9K_AUTH_ENABLED: {cfg.S9K_AUTH_ENABLED}")
    print(f"DB path: {db_path}")
    print(f"DB exists: {db_path.exists()}")
    if not db_path.exists():
        print("DB no inicializada. Ejecuta create-admin para comenzar.")
        return 0
    auth_db.ensure_migrated(db_path)
    with auth_db.get_conn(db_path) as conn:
        users = auth_db.list_users(conn)
        admins = [u for u in users if u.role == "admin" and u.is_active]
        total_events = auth_db.count_audit_events(conn)
    print(f"Usuarios totales: {len(users)}")
    print(f"Admins activos: {len(admins)}")
    print(f"Eventos de auditoría: {total_events}")
    if not admins:
        print("ADVERTENCIA: No hay administradores activos. Crea uno con create-admin.")
    return 0


# ---------------------------------------------------------------------------
# CLI principal
# ---------------------------------------------------------------------------

COMMANDS = {
    "create-admin": cmd_create_admin,
    "create-user": cmd_create_user,
    "list-users": cmd_list_users,
    "set-password": cmd_set_password,
    "set-role": cmd_set_role,
    "enable-user": cmd_enable_user,
    "disable-user": cmd_disable_user,
    "unlock-user": cmd_unlock_user,
    "revoke-sessions": cmd_revoke_sessions,
    "cleanup-sessions": cmd_cleanup_sessions,
    "status": cmd_status,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CLI administrativa de autenticación S9 Knowledge"
    )
    parser.add_argument("command", choices=list(COMMANDS.keys()), help="Comando a ejecutar")
    parser.add_argument("--username", help="Nombre de usuario (para comandos que lo requieren)")
    parser.add_argument("--role", help="Rol (para set-role)")

    args = parser.parse_args()
    fn = COMMANDS[args.command]
    try:
        return fn(args)
    except KeyboardInterrupt:
        print("\nCancelado.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
