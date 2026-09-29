"""Modelos de datos para autenticación: User, Session, AuditEvent."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
    # CORTE 6B-2 · C3. Overrides SOLO para pruebas/fixtures: hoy no hay
    # sistema de roles nuevo, así que `can_manage_access` y
    # `can_edit_context_label` derivan las dos de `is_admin()`. Pero son DOS
    # capacidades con DOS comprobaciones independientes, y el negativo
    # (gestiona accesos pero NO puede tocar el label) tiene que poder
    # construirse aunque hoy no exista ningún rol de producción que lo
    # produzca por sí solo — de ahí este campo, nunca persistido en `users`.
    capability_overrides: Optional[dict] = field(default=None)

    def is_locked(self, now: Optional[datetime] = None) -> bool:
        if self.locked_until is None:
            return False
        ts = now or _utcnow()
        return ts < self.locked_until

    def is_admin(self) -> bool:
        return self.role == "admin"

    def is_reviewer(self) -> bool:
        return self.role in ("admin", "reviewer")

    def can_see_reviews(self) -> bool:
        return self.role in ("admin", "reviewer")

    def can_access_admin(self) -> bool:
        return self.role == "admin"

    def _overridden(self, capacidad: str) -> Optional[bool]:
        if isinstance(self.capability_overrides, dict) and capacidad in self.capability_overrides:
            return bool(self.capability_overrides[capacidad])
        return None

    def can_manage_access(self) -> bool:
        """Conceder/revocar acceso a partidas (`/admin/partidas/grant|revoke`).

        Capacidad independiente de `can_edit_context_label` (C3): hoy las dos
        derivan de `is_admin()` porque no hay un sistema de roles nuevo, pero
        NO son el mismo booleano con dos nombres — se comprueban por
        separado, y el negativo (`capability_overrides`) lo demuestra.
        """
        overridden = self._overridden("can_manage_access")
        return self.is_admin() if overridden is None else overridden

    def can_edit_context_label(self) -> bool:
        """Editar `metadata.label` de un workspace/partida (Corte 6B-2)."""
        overridden = self._overridden("can_edit_context_label")
        return self.is_admin() if overridden is None else overridden


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
    # M5a: partida activa de esta sesión (docs/v3/49 §2.6). None = sin partida
    # seleccionada -> solo capa juego visible.
    active_partida: Optional[str] = None

    def is_valid(self, now: Optional[datetime] = None) -> bool:
        ts = now or _utcnow()
        return self.revoked_at is None and ts < self.expires_at


@dataclass
class PartidaAccess:
    """Asignación usuario -> partida permitida (M5a).

    Concedida por un admin desde el panel; sin auto-alta. Un usuario puede
    tener varias partidas asignadas (varias filas), pero solo una activa por
    sesión (`Session.active_partida`).
    """

    id: int
    user_id: int
    workspace: str
    partida_id: str
    granted_by: Optional[str]
    granted_at: datetime
    # Progresion de campana de ESTA concesion (T2). Se exponen para que el panel
    # pueda MOSTRARLAS: una concesion de personaje que no se ve en la interfaz es
    # un permiso que el operador no sabe que ha dado.
    max_visible_session: Optional[int] = None
    character_id: Optional[str] = None


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
