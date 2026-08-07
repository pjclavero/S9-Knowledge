"""Motor de política de visibilidad: decisión deny-by-default por nodo.

Reglas (en orden; la primera denegación gana):

  1. admin_full            -> visible siempre (bypass total).
  2. workspace             -> el nodo debe declarar un workspace legible y estar
                              en allowed_workspaces. Sin workspace -> denegado.
  2b. ámbito (M5a/M5c)     -> el nodo debe DECLARAR `scope`: `partida` exige un
                              `partida_id` en allowed_partida_ids; `juego` es
                              lore compartido y no puede llevar `partida_id`.
                              Sin `scope` válido -> denegado. La ausencia nunca
                              se interpreta como el ámbito más amplio.
  2c. known_by (M5c)       -> si está presente debe ser lista de cadenas no
                              vacías; malformado -> denegado.
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
    ALL_SCOPES,
    ALL_STORED_LEVELS,
    DENY,
    NARRATOR,
    REFERENCE,
    SCOPE_PARTIDA,
    SECRET,
    VisibilityDecision,
    ViewerContext,
    known_by_of,
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
        #
        # M5c: fail-closed. Antes era `if ws is not None and ws not in ...`, es
        # decir, un nodo SIN workspace legible pasaba la barrera. Ese es el
        # mismo defecto permisivo que M5b-2 cerró para `visibility`, y no tenía
        # por qué sobrevivir aquí: si no se puede leer a qué workspace pertenece
        # un dato, no se puede afirmar que el lector tenga derecho a verlo.
        ws = node.get("workspace")
        if not isinstance(ws, str) or not ws.strip():
            return VisibilityDecision(False, "workspace_invalid")
        if ws not in ctx.allowed_workspaces:
            return VisibilityDecision(False, "workspace_not_allowed")

        # 2b. Aislamiento entre partidas (M5a, docs/v3/49 §2.6), con ámbito
        # DECLARADO (M5c). Antes se infería del propio hueco: "sin `partida_id`
        # = capa juego, visible desde cualquier partida". Esa inferencia hacía
        # indistinguible un lore deliberadamente compartido de un dato que
        # perdió su ámbito por el camino —y el segundo caso se resolvía hacia lo
        # más abierto—. Ahora el ámbito se declara y, si no se declara, se
        # deniega.
        #
        # Como el aislamiento de workspace, esta barrera NUNCA se salta por
        # conocimiento de personaje ni por pertenencia a party.
        scope = node.get("scope")
        if scope not in ALL_SCOPES:
            return VisibilityDecision(False, "scope_invalid")

        pid = node.get("partida_id")
        if scope == SCOPE_PARTIDA:
            # Ámbito de partida sin partida legible: contradicción interna del
            # dato. No se degrada a capa juego, que sería lo permisivo.
            if not isinstance(pid, str) or not pid.strip():
                return VisibilityDecision(False, "partida_id_blank")
            if pid not in ctx.allowed_partida_ids:
                return VisibilityDecision(False, "partida_not_allowed")
        else:
            # Capa juego: compartida entre partidas del workspace. Pero no puede
            # arrastrar un `partida_id`: sería un dato que dice ser de todos y
            # de una a la vez, y la vía "de todos" es la más abierta.
            if pid is not None:
                return VisibilityDecision(False, "scope_contradictorio")

        # 2c. M5c: `known_by` malformado deniega el nodo entero, no solo el
        # conocimiento. Es un campo de autorización: si no se puede interpretar,
        # no se puede decidir. Además evita el 500 que producía un tipo
        # inesperado al evaluar la pertenencia.
        _, known_by_valido = known_by_of(node)
        if not known_by_valido:
            return VisibilityDecision(False, "known_by_invalid")

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

    def partida_in_scope(self, partida_id: Any, ctx: ViewerContext) -> bool:
        """¿Cae esta partida dentro del ámbito del lector?

        Pregunta de ÁMBITO, no de contenido, y por eso vive aquí y no se
        responde fabricando un nodo sintético para pasarlo por ``can_view``:
        ese truco es lo que hizo que una sonda acabara evaluada como contenido.
        La usan los registros operativos (cola de revisión, trabajos), que
        tienen partida pero no visibilidad ni ámbito declarado.

        ``None`` significa "este registro no tiene dimensión de partida", no
        "es de todas": no es un dato del grafo al que se le haya perdido el
        ámbito, sino una fila que nunca lo tuvo.
        """
        if ctx.admin_full:
            return True
        if partida_id is None:
            return True
        if not isinstance(partida_id, str) or not partida_id.strip():
            return False
        return partida_id in ctx.allowed_partida_ids

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
