"""Motor de política de visibilidad: decisión deny-by-default por nodo.

Reglas (en orden; la primera denegación gana):

  1. admin_full            -> visible siempre (bypass total).
  2. workspace             -> el workspace del nodo debe estar en allowed_workspaces.
  3. nivel de visibilidad  -> reference exige can_view_reference; secret y narrator
                              (capa GM) exigen can_view_secret.
  4. sesión futura         -> si session_index > max_visible_session y no can_view_future.
  5. pertenencia a party   -> contenido con `party` sólo lo ven sus miembros
                              (o contenido público con session_public).

`character_knowledge` (el personaje activo conoce el nodo) concede acceso a ESE
nodo aunque falle 3/4/5: el personaje ya lo vivió. NUNCA salta la barrera de
workspace (regla 2) ni el bypass de admin (regla 1).

Todos los métodos son puros: no escriben en ninguna fuente de datos.
"""
from __future__ import annotations

from typing import Any, Iterable

from app.policies.models import (
    NARRATOR,
    REFERENCE,
    SECRET,
    VisibilityDecision,
    ViewerContext,
)

_ALLOW = VisibilityDecision(True, "admin_full")


class VisibilityPolicy:
    """Evalúa un ``ViewerContext`` contra nodos/relaciones del grafo."""

    def can_view(self, node: dict[str, Any], ctx: ViewerContext) -> VisibilityDecision:
        # 1. Bypass total de administrador.
        if ctx.admin_full:
            return _ALLOW

        # 2. Aislamiento por workspace (nunca se salta, ni por conocimiento).
        ws = node.get("workspace")
        if ws is not None and ws not in ctx.allowed_workspaces:
            return VisibilityDecision(False, "workspace_not_allowed")

        knows = ctx.knows(node)

        # 3. Nivel de visibilidad del contenido.
        level = (node.get("visibility") or "player").lower()
        if not knows:
            if level == REFERENCE and not ctx.can_view_reference:
                return VisibilityDecision(False, "reference_not_allowed")
            if level == SECRET and not ctx.can_view_secret:
                return VisibilityDecision(False, "secret_not_allowed")
            if level == NARRATOR and not ctx.can_view_secret:
                # La capa del narrador/GM se trata como contenido elevado.
                return VisibilityDecision(False, "narrator_only")

        # 4. Sesiones futuras (spoilers de sesiones aún no jugadas/publicadas).
        if not knows and ctx.max_visible_session is not None:
            sess = node.get("session_index")
            if sess is not None and int(sess) > ctx.max_visible_session and not ctx.can_view_future:
                return VisibilityDecision(False, "future_session")

        # 5. Contenido acotado a un grupo (party).
        party = node.get("party")
        if party is not None and not knows and party not in ctx.party_membership:
            is_public = bool(node.get("is_public")) and ctx.session_public
            if not is_public:
                return VisibilityDecision(False, "party_scoped")

        return VisibilityDecision(True, "visible")

    # ------------------------------------------------------------------
    # Helpers de conjunto: la aplicación real (provider) los usa para que
    # LISTADOS, CONTEOS y BÚSQUEDAS filtren igual que el acceso por ID.
    # ------------------------------------------------------------------

    def filter_nodes(
        self, nodes: Iterable[dict[str, Any]], ctx: ViewerContext
    ) -> list[dict[str, Any]]:
        return [n for n in nodes if self.can_view(n, ctx).visible]

    def visible_ids(
        self, nodes: Iterable[dict[str, Any]], ctx: ViewerContext
    ) -> set[str]:
        return {n["id"] for n in nodes if "id" in n and self.can_view(n, ctx).visible}

    def filter_edges(
        self,
        edges: Iterable[dict[str, Any]],
        visible_node_ids: set[str],
        ctx: ViewerContext,
    ) -> list[dict[str, Any]]:
        """Una relación sólo es visible si AMBOS extremos lo son y ella misma
        supera la política (una relación puede ser secreta aunque sus nodos no).
        """
        out = []
        for e in edges:
            if e.get("from") not in visible_node_ids or e.get("to") not in visible_node_ids:
                continue
            if not self.can_view(e, ctx).visible:
                continue
            out.append(e)
        return out


# Instancia compartida sin estado.
POLICY = VisibilityPolicy()
