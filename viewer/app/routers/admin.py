"""Panel de administración: gestión de usuarios y auditoría."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import audit, db as auth_db
from app.auth.config import get_auth_settings
from app.auth.csrf import get_csrf_token_for_session, validate_csrf
from app.auth.dependencies import require_admin
from app.auth.models import ROLES, User
from app.auth.passwords import hash_password, validate_password

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/admin")


def _get_db_path() -> Path:
    cfg = get_auth_settings()
    p = Path(cfg.S9K_AUTH_DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _get_csrf(request: Request, session_id: int) -> str:
    cfg = get_auth_settings()
    raw = getattr(request.state, "csrf_raw", "")
    return get_csrf_token_for_session(session_id, raw, secret=cfg.S9K_CSRF_SECRET)


def _check_csrf(request: Request, token: str, session_id: int) -> bool:
    cfg = get_auth_settings()
    raw = getattr(request.state, "csrf_raw", "")
    return validate_csrf(token, session_id, raw, secret=cfg.S9K_CSRF_SECRET)


# ---------------------------------------------------------------------------
# GET /admin/users
# ---------------------------------------------------------------------------

@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    admin: User = Depends(require_admin),
):
    if isinstance(admin, RedirectResponse):
        return admin
    session = getattr(request.state, "session", None)
    db_path = _get_db_path()
    auth_db.ensure_migrated(db_path)
    with auth_db.get_conn(db_path) as conn:
        users = auth_db.list_users(conn)
    return templates.TemplateResponse(
        request,
        "auth/admin/users.html",
        {
            "users": users,
            "admin": admin,
            "csrf_token": _get_csrf(request, session.id if session else 0),
        },
    )


# ---------------------------------------------------------------------------
# GET /admin/users/new
# ---------------------------------------------------------------------------

@router.get("/users/new", response_class=HTMLResponse)
async def admin_users_new(
    request: Request,
    admin: User = Depends(require_admin),
):
    if isinstance(admin, RedirectResponse):
        return admin
    session = getattr(request.state, "session", None)
    return templates.TemplateResponse(
        request,
        "auth/admin/user_detail.html",
        {
            "edit_user": None,
            "roles": ROLES,
            "admin": admin,
            "csrf_token": _get_csrf(request, session.id if session else 0),
            "errors": [],
            "mode": "new",
        },
    )


# ---------------------------------------------------------------------------
# POST /admin/users/new
# ---------------------------------------------------------------------------

@router.post("/users/new")
async def admin_users_new_submit(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    role: str = Form(...),
    password: str = Form(...),
    must_change_password: bool = Form(default=False),
    csrf_token: str = Form(...),
    admin: User = Depends(require_admin),
):
    if isinstance(admin, RedirectResponse):
        return admin
    session = getattr(request.state, "session", None)

    if not _check_csrf(request, csrf_token, session.id if session else 0):
        raise HTTPException(status_code=403, detail="CSRF inválido")

    errors = validate_password(password, username)
    if role not in ROLES:
        errors.append(f"Rol inválido: {role}")

    if errors:
        return templates.TemplateResponse(
            request, "auth/admin/user_detail.html",
            {
                "edit_user": None, "roles": ROLES, "admin": admin,
                "csrf_token": _get_csrf(request, session.id if session else 0),
                "errors": errors, "mode": "new",
            },
            status_code=400,
        )

    db_path = _get_db_path()
    with auth_db.get_conn(db_path) as conn:
        existing = auth_db.get_user_by_username(conn, username)
        if existing:
            return templates.TemplateResponse(
                request, "auth/admin/user_detail.html",
                {
                    "edit_user": None, "roles": ROLES, "admin": admin,
                    "csrf_token": _get_csrf(request, session.id if session else 0),
                    "errors": ["El nombre de usuario ya existe."], "mode": "new",
                },
                status_code=400,
            )
        pw_hash = hash_password(password)
        new_user = auth_db.create_user(
            conn, username=username, display_name=display_name,
            password_hash=pw_hash, role=role,
            must_change_password=must_change_password,
            created_by=admin.username,
        )
        audit.log(conn, audit.USER_CREATED, "success",
                  user_id=admin.id, username_snapshot=admin.username,
                  metadata={"new_user": username, "role": role})
    return RedirectResponse(url=f"/admin/users/{new_user.id}", status_code=302)


# ---------------------------------------------------------------------------
# GET /admin/users/{id}
# ---------------------------------------------------------------------------

@router.get("/users/{user_id}", response_class=HTMLResponse)
async def admin_user_detail(
    request: Request,
    user_id: int,
    admin: User = Depends(require_admin),
):
    if isinstance(admin, RedirectResponse):
        return admin
    session = getattr(request.state, "session", None)
    db_path = _get_db_path()
    with auth_db.get_conn(db_path) as conn:
        edit_user = auth_db.get_user_by_id(conn, user_id)
    if edit_user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return templates.TemplateResponse(
        request,
        "auth/admin/user_detail.html",
        {
            "edit_user": edit_user,
            "roles": ROLES,
            "admin": admin,
            "csrf_token": _get_csrf(request, session.id if session else 0),
            "errors": [],
            "mode": "edit",
        },
    )


# ---------------------------------------------------------------------------
# POST /admin/users/{id}
# ---------------------------------------------------------------------------

@router.post("/users/{user_id}")
async def admin_user_update(
    request: Request,
    user_id: int,
    display_name: str = Form(...),
    role: str = Form(...),
    is_active: bool = Form(default=False),
    must_change_password: bool = Form(default=False),
    csrf_token: str = Form(...),
    admin: User = Depends(require_admin),
):
    if isinstance(admin, RedirectResponse):
        return admin
    session = getattr(request.state, "session", None)

    if not _check_csrf(request, csrf_token, session.id if session else 0):
        raise HTTPException(status_code=403, detail="CSRF inválido")

    db_path = _get_db_path()
    with auth_db.get_conn(db_path) as conn:
        target = auth_db.get_user_by_id(conn, user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        # No dejar el sistema sin admins activos
        if target.role == "admin" and target.is_active:
            if (role != "admin" or not is_active):
                if auth_db.count_active_admins(conn) <= 1:
                    raise HTTPException(
                        status_code=409,
                        detail="No se puede degradar/desactivar al único admin activo.",
                    )

        changes: dict = {}
        if target.display_name != display_name:
            changes["display_name"] = display_name
        if target.role != role:
            changes["role_before"] = target.role
            changes["role_after"] = role
        if target.is_active != is_active:
            changes["is_active"] = is_active

        auth_db.update_user(conn, user_id,
                            display_name=display_name,
                            role=role,
                            is_active=is_active,
                            must_change_password=must_change_password)

        event = audit.USER_UPDATED
        if "role_before" in changes:
            event = audit.ROLE_CHANGED
        if not is_active and target.is_active:
            event = audit.USER_DISABLED
            auth_db.revoke_sessions_for_user(conn, user_id)
        elif is_active and not target.is_active:
            event = audit.USER_ENABLED

        audit.log(conn, event, "success",
                  user_id=admin.id, username_snapshot=admin.username,
                  metadata={"target_user": target.username, **changes})

    return RedirectResponse(url=f"/admin/users/{user_id}", status_code=302)


# ---------------------------------------------------------------------------
# POST /admin/users/{id}/unlock
# ---------------------------------------------------------------------------

@router.post("/users/{user_id}/unlock")
async def admin_user_unlock(
    request: Request,
    user_id: int,
    csrf_token: str = Form(...),
    admin: User = Depends(require_admin),
):
    if isinstance(admin, RedirectResponse):
        return admin
    session = getattr(request.state, "session", None)

    if not _check_csrf(request, csrf_token, session.id if session else 0):
        raise HTTPException(status_code=403, detail="CSRF inválido")

    db_path = _get_db_path()
    with auth_db.get_conn(db_path) as conn:
        target = auth_db.get_user_by_id(conn, user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        auth_db.update_user(conn, user_id, failed_login_count=0, locked_until="")
        audit.log(conn, audit.USER_UPDATED, "success",
                  user_id=admin.id, username_snapshot=admin.username,
                  metadata={"action": "unlock", "target_user": target.username})

    return RedirectResponse(url=f"/admin/users/{user_id}", status_code=302)


# ---------------------------------------------------------------------------
# POST /admin/users/{id}/revoke-sessions
# ---------------------------------------------------------------------------

@router.post("/users/{user_id}/revoke-sessions")
async def admin_revoke_sessions(
    request: Request,
    user_id: int,
    csrf_token: str = Form(...),
    admin: User = Depends(require_admin),
):
    if isinstance(admin, RedirectResponse):
        return admin
    session = getattr(request.state, "session", None)

    if not _check_csrf(request, csrf_token, session.id if session else 0):
        raise HTTPException(status_code=403, detail="CSRF inválido")

    db_path = _get_db_path()
    with auth_db.get_conn(db_path) as conn:
        target = auth_db.get_user_by_id(conn, user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        count = auth_db.revoke_sessions_for_user(conn, user_id)
        audit.log(conn, audit.SESSIONS_REVOKED, "success",
                  user_id=admin.id, username_snapshot=admin.username,
                  metadata={"target_user": target.username, "sessions_revoked": count})

    return RedirectResponse(url=f"/admin/users/{user_id}", status_code=302)


# ---------------------------------------------------------------------------
# GET /admin/audit
# ---------------------------------------------------------------------------

@router.get("/audit", response_class=HTMLResponse)
async def admin_audit(
    request: Request,
    user_param: Optional[str] = None,
    event_type: Optional[str] = None,
    result: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    admin: User = Depends(require_admin),
):
    if isinstance(admin, RedirectResponse):
        return admin
    session = getattr(request.state, "session", None)

    page = max(1, page)
    page_size = min(max(10, page_size), 200)
    offset = (page - 1) * page_size

    db_path = _get_db_path()
    with auth_db.get_conn(db_path) as conn:
        events = auth_db.list_audit_events(
            conn,
            username=user_param,
            event_type=event_type,
            result=result,
            date_from=date_from,
            date_to=date_to,
            limit=page_size,
            offset=offset,
        )
        total = auth_db.count_audit_events(
            conn,
            username=user_param,
            event_type=event_type,
            result=result,
            date_from=date_from,
            date_to=date_to,
        )

    total_pages = max(1, (total + page_size - 1) // page_size)

    return templates.TemplateResponse(
        request,
        "auth/admin/audit.html",
        {
            "events": events,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "filters": {
                "user": user_param,
                "event_type": event_type,
                "result": result,
                "date_from": date_from,
                "date_to": date_to,
            },
            "event_types": audit.ALL_EVENT_TYPES,
            "admin": admin,
            "csrf_token": _get_csrf(request, session.id if session else 0),
        },
    )
