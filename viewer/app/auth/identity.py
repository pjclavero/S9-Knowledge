"""Identidad del operador autenticado.

En esta fase solo provee la identidad para auditoría web.
No conecta con review_manual.py ni con el writer Neo4j.

USO FUTURO:
  - `reviewed_by`: se llenará con `identity.username` al aprobar un ítem.
  - `reviewed_at`: se llenará con la hora UTC del momento de la aprobación.
  - El router de revisión recibirá `OperatorIdentity` vía la dependencia
    `get_operator_identity` antes de invocar el writer Neo4j.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Request


@dataclass
class OperatorIdentity:
    user_id: int
    username: str
    display_name: str
    role: str
    session_id: int


def get_operator_identity(request: Request) -> Optional[OperatorIdentity]:
    """
    Devuelve la identidad del operador autenticado, o None si no hay sesión.

    Actualmente lee del atributo `request.state.user` que inyecta el middleware
    de autenticación cuando S9K_AUTH_ENABLED=true.
    """
    user = getattr(request.state, "user", None)
    session = getattr(request.state, "session", None)
    if user is None or session is None:
        return None
    return OperatorIdentity(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        session_id=session.id,
    )
