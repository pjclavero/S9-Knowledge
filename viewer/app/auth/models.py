"""Modelos de datos para autenticación: User, Session, AuditEvent."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


ROLES = ("admin", "reviewer", "viewer")


@dataclass
class User:
    id: int
    username: str
    display_name: str
    password_hash: str
    role: str  # admin | reviewer | viewer
    is_active: bool
    must_change_password: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: Optional[datetime]
    failed_login_count: int
    locked_until: Optional[datetime]
    created_by: Optional[str]

    def is_locked(self, now: Optional[datetime] = None) -> bool:
        if self.locked_until is None:
            return False
        ts = now or datetime.utcnow()
        return ts < self.locked_until

    def is_admin(self) -> bool:
        return self.role == "admin"

    def is_reviewer(self) -> bool:
        return self.role in ("admin", "reviewer")

    def can_see_reviews(self) -> bool:
        return self.role in ("admin", "reviewer")

    def can_access_admin(self) -> bool:
        return self.role == "admin"


@dataclass
class Session:
    id: int
    user_id: int
    session_hash: str  # sha256 del token; el token en claro NO se guarda
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime
    revoked_at: Optional[datetime]
    ip_hash: Optional[str]
    user_agent_hash: Optional[str]

    def is_valid(self, now: Optional[datetime] = None) -> bool:
        ts = now or datetime.utcnow()
        return self.revoked_at is None and ts < self.expires_at


@dataclass
class AuditEvent:
    id: int
    created_at: datetime
    user_id: Optional[int]
    username_snapshot: Optional[str]
    event_type: str
    result: str  # success | failure | info
    route: Optional[str]
    method: Optional[str]
    ip_hash: Optional[str]
    user_agent_hash: Optional[str]
    metadata_json: Optional[str]
