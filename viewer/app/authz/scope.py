"""Ámbito visible (workspace + partida) para datos que NO vienen del grafo.

``PolicyFilteredProvider`` cubre todo lo que se lee a través de un
``GraphProvider``. Pero el visor sirve además material que vive fuera de Neo4j:

  - los documentos de contrato del panel de revisión v1 (``/review-console``),
  - las propuestas/candidatos de glosario del panel V3 (``/v3/review``),
  - la cola de trabajos del data-engine (``/jobs``, ``/api/jobs``).

Todo eso es material de una partida concreta (o de la capa juego compartida) y
debe respetar EL MISMO aislamiento. Este módulo es el punto único donde ese
material se contrasta con la política: no reimplementa reglas, delega en
``VisibilityPolicy.can_view`` normalizando cada registro a las dos barreras que
nunca se saltan (regla 2 workspace, regla 2b partida). Así el criterio vive en
un solo sitio y no en un ``if`` por ruta.

Deny-by-default: si un registro no declara workspace se considera capa juego
del workspace permitido (visible), pero si declara uno ajeno o una partida que
no es la activa, no se entrega — ni en listados, ni en conteos, ni por ID.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, TypeVar

from app.policies.engine import POLICY, VisibilityPolicy
from app.policies.models import ViewerContext

T = TypeVar("T", bound=Mapping[str, Any])

# Lugares donde un documento puede declarar su partida, en orden de prioridad.
# El primero que exista manda; ninguno = capa juego (lore compartido).
_PARTIDA_PATHS: tuple[tuple[str, ...], ...] = (
    ("partida_id",),
    # Los contratos review-ingest v1 son cerrados (additionalProperties: false)
    # salvo `metadata`: ahí es donde un documento v1 declara su partida.
    ("metadata", "partida_id"),
    ("scope", "partida_id"),
    ("provenance", "partida_id"),
    ("payload", "partida_id"),
)
_WORKSPACE_PATHS: tuple[tuple[str, ...], ...] = (
    ("workspace",),
    ("scope", "workspace"),
    ("payload", "workspace"),
)


def _dig(record: Mapping[str, Any], path: Sequence[str]) -> Any:
    cur: Any = record
    for key in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(key)
    return cur


def _first(record: Mapping[str, Any], paths: Iterable[Sequence[str]]) -> Optional[str]:
    for path in paths:
        value = _dig(record, path)
        if value is not None:
            return value if isinstance(value, str) else str(value)
    return None


@dataclass(frozen=True)
class VisibilityScope:
    """Ámbito visible de la petición aplicado a registros arbitrarios.

    Se construye desde el mismo ``ViewerContext`` que usa el provider filtrado,
    de modo que un admin (``admin_full``) ve lo mismo en ambos caminos y un
    usuario con partida activa ve, en ambos, su partida más la capa juego.
    """

    ctx: ViewerContext
    policy: VisibilityPolicy = POLICY
    #: Si el `workspace` del registro es comparable con los workspaces del
    #: visor. Es cierto para los datos operativos de este despliegue (cola de
    #: jobs). NO lo es para los corpus de revisión (contratos v1 y propuestas
    #: V3), cuyo campo `workspace` es una etiqueta del corpus de laboratorio y
    #: no un workspace del visor: allí la barrera aplicable es la de partida.
    enforce_workspace: bool = True

    def partida_only(self) -> "VisibilityScope":
        """Mismo ámbito, sin comparar workspaces ajenos al modelo del visor."""
        return VisibilityScope(self.ctx, self.policy, enforce_workspace=False)

    # -- decisiones elementales ------------------------------------------------
    def allows_workspace(self, workspace: Optional[str]) -> bool:
        if self.ctx.admin_full or not self.enforce_workspace:
            return True
        if workspace is None:
            return True
        return workspace in self.ctx.allowed_workspaces

    def allows_partida(self, partida_id: Optional[str]) -> bool:
        return self.policy.can_view({"partida_id": partida_id}, self.ctx).visible

    def allows(self, record: Mapping[str, Any]) -> bool:
        """True si el registro pertenece al ámbito visible (workspace+partida)."""
        workspace = _first(record, _WORKSPACE_PATHS)
        if not self.allows_workspace(workspace):
            return False
        node = {
            "workspace": workspace if self.enforce_workspace else None,
            "partida_id": _first(record, _PARTIDA_PATHS),
        }
        return self.policy.can_view(node, self.ctx).visible

    # -- helpers de conjunto ---------------------------------------------------
    def filter(self, records: Iterable[T]) -> list[T]:
        return [r for r in records if self.allows(r)]

    def filter_workspaces(self, workspaces: Iterable[str]) -> list[str]:
        return [w for w in workspaces if self.allows_workspace(w)]

    # -- recorte de detalle ----------------------------------------------------
    @property
    def sees_operational_detail(self) -> bool:
        """Solo admin ve el detalle operativo (rutas de fichero, payloads).

        Un revisor necesita saber QUÉ hay en cola de su ámbito, no dónde vive el
        fichero en el disco del servidor.
        """
        return bool(self.ctx.admin_full) or self.ctx.role == "admin"


#: Ámbito sin restricciones, para llamadores internos/programáticos (CLI, tests
#: de servicio) que no representan a un usuario del visor.
UNRESTRICTED = VisibilityScope(ViewerContext(role="admin", admin_full=True))
