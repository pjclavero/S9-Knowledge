"""Motor de política de visibilidad: decisión deny-by-default por nodo.

Reglas (en orden; la primera denegación gana):

  1. admin_full            -> visible siempre (bypass total).
  2. workspace             -> el workspace del nodo debe estar en allowed_workspaces.
  2b. partida (M5a)        -> si el nodo tiene `partida_id`, debe estar en
                              allowed_partida_ids (la partida activa de la
                              sesión). Sin `partida_id` = capa juego, visible
                              siempre dentro del workspace. `partida_id` en
                              blanco = dato inválido -> nunca visible.
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
    ALL_STORED_LEVELS,
    DENY,
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
        # 0. M5b-2: la visibilidad debe ser un valor del vocabulario cerrado.
        #
        # Va ANTES del bypass de administrador, y no es un detalle: si fuera
        # despues, `admin_full` haria visible tanto un `deny` --que es terminal
        # por definicion-- como un nodo con la propiedad corrupta. Un bypass
        # solo puede saltarse reglas de permiso; no puede convertir un dato
        # invalido en un dato valido.
        raw = node.get("visibility")
        level = raw.strip().lower() if isinstance(raw, str) else None
        if level not in ALL_STORED_LEVELS:
            # Ausente, vacia, de otro tipo, o un nivel que este motor no
            # conoce (p.ej. escrito por una version futura). Ninguno de esos
            # casos puede resolverse "hacia lo permisivo" sin adivinar.
            return VisibilityDecision(False, "visibility_invalid")
        if level == DENY:
            return VisibilityDecision(False, "deny_absolute")

        # 1. Bypass total de administrador.
        if ctx.admin_full:
            return _ALLOW

        # 2. Aislamiento por workspace (nunca se salta, ni por conocimiento).
        ws = node.get("workspace")
        if ws is not None and ws not in ctx.allowed_workspaces:
            return VisibilityDecision(False, "workspace_not_allowed")

        # 2b. Aislamiento entre partidas (M5a, docs/v3/49 §2.6). `partida_id`
        # ausente/None = capa juego (lore compartido): visible para cualquier
        # partida de ese juego. `partida_id` presente = material privado de esa
        # partida concreta: solo visible si es la partida activa de la sesión.
        # Como el aislamiento de workspace, esta barrera NUNCA se salta por
        # conocimiento de personaje ni por pertenencia a party.
        pid = node.get("partida_id")
        if pid is not None:
            # `partida_id` en blanco ("" o solo espacios) NO es capa juego: el
            # contrato knowledge-v3 lo rechaza en el esquema (M2), así que aquí
            # solo puede llegar por dato corrupto. Semántica explícita y
            # fail-closed: nunca visible para nadie salvo admin_full, y nunca
            # utilizable como comodín aunque alguien colase "" en
            # allowed_partida_ids.
            if isinstance(pid, str) and not pid.strip():
                return VisibilityDecision(False, "partida_id_blank")
            if pid not in ctx.allowed_partida_ids:
                return VisibilityDecision(False, "partida_not_allowed")

        knows = ctx.knows(node)

        # 3. Nivel de visibilidad del contenido. `level` ya viene validado
        # desde la regla 0: aqui no se vuelve a leer del nodo.
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
