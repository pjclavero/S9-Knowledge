"""Ablacion: si el LIMIT del rel_query de Neo4j puede desaparecer sin cambiar
ningun resultado del camino autorizado, no es una defensa: es adorno."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "viewer")); sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_neo4j import build, FakeDriver, FakeSession  # noqa: E402
from app.providers.neo4j_provider import Neo4jGraphProvider  # noqa: E402
from app.authz.filtered_provider import PolicyFilteredProvider  # noqa: E402
from app.policies.engine import VisibilityPolicy  # noqa: E402
from app.policies.models import ViewerContext  # noqa: E402


class SessionSinLimiteEnRelaciones(FakeSession):
    """LIMIT ablacionado SOLO para la consulta de relaciones."""
    def run(self, query, params=None):
        if "-[r]->" in query:
            p = dict(params or {}); p["limit"] = 10 ** 9
            return super().run(query, p)
        return super().run(query, params)


class DriverAblado(FakeDriver):
    def session(self, *a, **k): return SessionSinLimiteEnRelaciones(self.nodes, self.edges)


CTX = ViewerContext(role="reviewer", allowed_workspaces=frozenset({"leyenda"}),
                    can_view_reference=True, session_public=True)

print("### Ablacion del LIMIT sobre relaciones (camino autorizado: /api/graph)")
for n in (300, 500, 1000, 2000):
    nodes, edges = build(n, n * 3)
    out = {}
    for etiqueta, drv in (("con LIMIT", FakeDriver(nodes, edges)),
                          ("ABLADO", DriverAblado(nodes, edges))):
        base = Neo4jGraphProvider.__new__(Neo4jGraphProvider)
        base._driver = drv
        prov = PolicyFilteredProvider(base, CTX, VisibilityPolicy())
        gn, ge = prov.graph("leyenda", limit=300)
        out[etiqueta] = (len(gn), len(ge))
    igual = "IDENTICO -> el control no defiende nada" if out["con LIMIT"] == out["ABLADO"] else "DIFIERE"
    print(f"n={n:5d} con_LIMIT={out['con LIMIT']} ablado={out['ABLADO']}  {igual}")

print()
print("### Contraste: camino NO autorizado (base.graph directo con limit=300)")
for n in (300, 2000):
    nodes, edges = build(n, n * 3)
    b1 = Neo4jGraphProvider.__new__(Neo4jGraphProvider); b1._driver = FakeDriver(nodes, edges)
    b2 = Neo4jGraphProvider.__new__(Neo4jGraphProvider); b2._driver = DriverAblado(nodes, edges)
    print(f"n={n:5d} con_LIMIT={len(b1.graph('leyenda', limit=300)[1]):5d} aristas "
          f"| ablado={len(b2.graph('leyenda', limit=300)[1]):5d} aristas")
