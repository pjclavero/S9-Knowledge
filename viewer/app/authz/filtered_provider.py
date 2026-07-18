"""Provider que aplica la política de visibilidad EN LA QUERY.

Envuelve cualquier ``GraphProvider`` y garantiza que el filtro de visibilidad
se aplica ANTES de entregar datos: listados, CONTEOS, BÚSQUEDAS, tipos de
entidad, fuentes, calidad, acceso por ID y relaciones. Así se evita la
inferencia por conteos/autocomplete: lo no visible ni se cuenta ni aparece.

Contrato de "no visible por ID":
  ``entity(id)`` devuelve ``None`` para un nodo existente pero no visible — la
  API lo traduce a **404** (indistinguible de inexistente). Es una decisión
  deliberada para no revelar la existencia de secretos/futuro por diferencia
  entre 403 y 404. El 403 se reserva para faltas de ROL (capa de dependencias),
  no para faltas de visibilidad de contenido.

Solo lectura: delega lecturas al provider base; nunca escribe.
"""
from __future__ import annotations

from typing import Any

from app.policies.engine import VisibilityPolicy
from app.policies.models import ViewerContext
from app.providers.base import GraphProvider

# Ventana amplia para materializar el conjunto completo antes de filtrar y
# re-paginar. El filtro debe ocurrir sobre TODO el conjunto, no sobre una página
# ya recortada (si no, los conteos filtrarían mal).
_ALL = 10_000_000


class PolicyFilteredProvider(GraphProvider):
    def __init__(self, base: GraphProvider, ctx: ViewerContext, policy: VisibilityPolicy | None = None):
        self._base = base
        self._ctx = ctx
        self._policy = policy or VisibilityPolicy()

    @property
    def name(self) -> str:
        # Proxy transparente: reporta la identidad del provider base para que
        # /api/status (nombre + conectividad reales) no se rompa al envolverlo.
        # El filtrado ocurre en los métodos de datos, no en la identidad.
        return self._base.name

    # -- passthrough de conectividad -----------------------------------------
    def is_connected(self) -> bool:
        return self._base.is_connected()

    def workspaces(self) -> list[str]:
        allowed = self._ctx.allowed_workspaces
        if self._ctx.admin_full:
            return self._base.workspaces()
        return [w for w in self._base.workspaces() if w in allowed]

    # -- helpers de materialización ------------------------------------------
    def _visible_nodes(self, workspace: str) -> list[dict[str, Any]]:
        nodes, _ = self._base.list_entities(workspace, limit=_ALL, offset=0)
        return self._policy.filter_nodes(nodes, self._ctx)

    def _visible_graph(self, workspace: str) -> tuple[list[dict], list[dict]]:
        nodes, edges = self._base.graph(workspace, limit=_ALL)
        vnodes = self._policy.filter_nodes(nodes, self._ctx)
        vids = {n["id"] for n in vnodes if "id" in n}
        vedges = self._policy.filter_edges(edges, vids, self._ctx)
        return vnodes, vedges

    # -- conteos (filtrados) --------------------------------------------------
    def counts(self, workspace: str | None = None) -> tuple[int, int]:
        wss = [workspace] if workspace else self.workspaces()
        n_total = e_total = 0
        for ws in wss:
            vnodes, vedges = self._visible_graph(ws)
            n_total += len(vnodes)
            e_total += len(vedges)
        return n_total, e_total

    def entity_types(self, workspace: str) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for n in self._visible_nodes(workspace):
            t = n.get("type")
            if t:
                counts[t] = counts.get(t, 0) + 1
        return [
            {"entity_type": t, "count": c}
            for t, c in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        ]

    # -- búsqueda (filtrada; el recorte por limit se hace tras filtrar) -------
    def search(self, workspace: str, q: str, limit: int = 50) -> list[dict[str, Any]]:
        raw = self._base.search(workspace, q, limit=_ALL)
        visible = self._policy.filter_nodes(raw, self._ctx)
        return visible[:limit]

    # -- grafo (nodos + relaciones filtrados) ---------------------------------
    def graph(
        self,
        workspace: str,
        limit: int = 300,
        entity_type: str | None = None,
        q: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        nodes, edges = self._base.graph(workspace, limit=_ALL, entity_type=entity_type, q=q)
        vnodes = self._policy.filter_nodes(nodes, self._ctx)[:limit]
        vids = {n["id"] for n in vnodes if "id" in n}
        vedges = self._policy.filter_edges(edges, vids, self._ctx)
        return vnodes, vedges

    # -- acceso por ID: no visible -> None (=> 404) ---------------------------
    def entity(self, entity_id: str) -> dict[str, Any] | None:
        node = self._base.entity(entity_id)
        if node is None:
            return None
        if not self._policy.can_view(node, self._ctx).visible:
            return None
        return node

    def relations_for_entity(
        self, entity_id: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        # El propio nodo debe ser visible; si no, no exponemos sus relaciones.
        if self.entity(entity_id) is None:
            return [], []
        outgoing, incoming = self._base.relations_for_entity(entity_id)

        def _edge_ok(edge: dict[str, Any], other_key: str) -> bool:
            if not self._policy.can_view(edge, self._ctx).visible:
                return False
            other = self._base.entity(edge.get(other_key))
            if other is None:
                return False
            return self._policy.can_view(other, self._ctx).visible

        return (
            [e for e in outgoing if _edge_ok(e, "to")],
            [e for e in incoming if _edge_ok(e, "from")],
        )

    # -- listado paginado (filtrado ANTES de paginar) -------------------------
    def list_entities(
        self,
        workspace: str,
        *,
        q: str = "",
        entity_type: str | None = None,
        source_kind: str | None = None,
        review_status: str | None = None,
        visibility: str | None = None,
        quality_status: str | None = None,
        min_confidence: float | None = None,
        sort: str = "canonical_name",
        order: str = "asc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        items, _ = self._base.list_entities(
            workspace,
            q=q,
            entity_type=entity_type,
            source_kind=source_kind,
            review_status=review_status,
            visibility=visibility,
            quality_status=quality_status,
            min_confidence=min_confidence,
            sort=sort,
            order=order,
            limit=_ALL,
            offset=0,
        )
        visible = self._policy.filter_nodes(items, self._ctx)
        total = len(visible)
        page = visible[offset:offset + limit]
        return page, total

    # -- fuentes: recomputadas a partir de nodos visibles ---------------------
    def list_sources(self, workspace: str) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for n in self._visible_nodes(workspace):
            sid = n.get("source_document") or n.get("source_id")
            if sid:
                counts[sid] = counts.get(sid, 0) + 1
        return [{"source_id": sid, "entity_count": c} for sid, c in sorted(counts.items())]

    def source_detail(self, workspace: str, source_id: str) -> dict[str, Any] | None:
        entities = [
            n for n in self._visible_nodes(workspace)
            if (n.get("source_document") or n.get("source_id")) == source_id
        ]
        if not entities:
            return None
        return {
            "source_id": source_id,
            "workspace": workspace,
            "entity_count": len(entities),
            "entity_types": sorted({n.get("type") for n in entities if n.get("type")}),
        }

    # -- calidad: métricas recomputadas sobre lo visible ----------------------
    def quality_metrics(self, workspace: str | None = None) -> dict[str, Any]:
        wss = [workspace] if workspace else self.workspaces()
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        for ws in wss:
            vn, ve = self._visible_graph(ws)
            nodes += vn
            edges += ve

        by_type: dict[str, int] = {}
        by_ws: dict[str, int] = {}
        by_review: dict[str, int] = {}
        by_visibility: dict[str, int] = {}
        c_high = c_mid = c_low = c_none = 0
        no_source = no_desc = no_type = 0
        for n in nodes:
            by_type[n.get("type") or ""] = by_type.get(n.get("type") or "", 0) + 1
            by_ws[n.get("workspace") or ""] = by_ws.get(n.get("workspace") or "", 0) + 1
            by_review[n.get("review_status") or ""] = by_review.get(n.get("review_status") or "", 0) + 1
            by_visibility[n.get("visibility") or ""] = by_visibility.get(n.get("visibility") or "", 0) + 1
            c = n.get("confidence")
            if c is None:
                c_none += 1
            elif float(c) >= 0.8:
                c_high += 1
            elif float(c) >= 0.5:
                c_mid += 1
            else:
                c_low += 1
            if not (n.get("source_document") or n.get("source_id")):
                no_source += 1
            if not n.get("description"):
                no_desc += 1
            if not n.get("type"):
                no_type += 1

        return {
            "workspace": workspace,
            "total_entities": len(nodes),
            "total_relations": len(edges),
            "by_entity_type": by_type,
            "by_workspace": by_ws,
            "by_review_status": by_review,
            "by_visibility": by_visibility,
            "confidence_distribution": {
                "high_gte_0_8": c_high,
                "mid_gte_0_5": c_mid,
                "low_lt_0_5": c_low,
                "no_value": c_none,
            },
            "data_gaps": {
                "no_source_document": no_source,
                "no_description": no_desc,
                "no_entity_type": no_type,
            },
        }
