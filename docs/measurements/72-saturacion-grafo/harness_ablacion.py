"""Ablacion del LIMIT del `rel_query` de Neo4j.

SEXTA AVERIA DEL INSTRUMENTO (la encontro el revisor; la version anterior de
este banco era una TAUTOLOGIA CON FORMATO DE MEDIDA):

  - No ablacionaba nada: hacia ``p["limit"] = 10 ** 9``, es decir **subia el
    parametro** en vez de **quitar la clausula**.
  - Y la rama "con LIMIT" tampoco tenia cota efectiva, porque
    ``filtered_provider.py:101`` reenvia ``_ALL`` (10.000.000) al provider base.

  Resultado: 10^7 frente a 10^9 sobre fixtures de 6.000 aristas como mucho.
  Ninguna de las dos ramas podia morder, asi que la columna **no podia leer
  `DIFIERE` jamas**: el `IDENTICO` estaba forzado por aritmetica, no medido.

Corregido de dos maneras a la vez:
  1. La ablacion ahora **elimina la clausula LIMIT del Cypher** (la sesion de
     pega solo acota si la consulta la trae).
  2. Se anade un **CONTROL POSITIVO** con una cota que SI puede morder (400),
     para demostrar que esta maquinaria sabe leer `DIFIERE`.

La conclusion de fondo no cambia, pero su fundamento si: el LIMIT no defiende
nada en el camino autorizado **por construccion** —``_ALL`` no puede morder por
debajo de 10 millones de relaciones—, no "porque la ablacion no movio nada".
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "viewer")); sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_neo4j import build, FakeDriver, FakeSession  # noqa: E402
from app.providers.neo4j_provider import Neo4jGraphProvider  # noqa: E402
from app.authz.filtered_provider import PolicyFilteredProvider, _ALL  # noqa: E402
from app.policies.engine import VisibilityPolicy  # noqa: E402
from app.policies.models import ViewerContext  # noqa: E402

RE_LIMIT = "LIMIT $limit"


class SessionSinClausulaLimit(FakeSession):
    """Ablacion DE VERDAD: se borra la clausula del texto de la consulta de
    relaciones. No se toca el parametro."""

    def run(self, query, params=None):
        if "-[r]->" in query:
            query = query.replace(RE_LIMIT, "")
            assert "LIMIT" not in query.upper(), "la clausula no se quito"
        return super().run(query, params)


class DriverAblado(FakeDriver):
    def session(self, *a, **k):
        return SessionSinClausulaLimit(self.nodes, self.edges, self.cotas_vistas)


class SessionCotaQueMuerde(FakeSession):
    """CONTROL POSITIVO: cota de 400 relaciones, que sobre 6.000 SI muerde."""

    def run(self, query, params=None):
        if "-[r]->" in query:
            params = dict(params or {}); params["limit"] = 400
        return super().run(query, params)


class DriverCotaQueMuerde(FakeDriver):
    def session(self, *a, **k):
        return SessionCotaQueMuerde(self.nodes, self.edges, self.cotas_vistas)


CTX = ViewerContext(role="reviewer", allowed_workspaces=frozenset({"leyenda"}),
                    can_view_reference=True)


def _mide(nodes, edges, driver_cls):
    drv = driver_cls(nodes, edges)
    base = Neo4jGraphProvider.__new__(Neo4jGraphProvider)
    base._driver = drv
    prov = PolicyFilteredProvider(base, CTX, VisibilityPolicy())
    gn, ge = prov.graph("leyenda", limit=300)
    return (len(gn), len(ge)), drv.cotas_vistas


print(f"### Contexto: filtered_provider reenvia _ALL = {_ALL:,} al provider base.")
print("### Una fixture de 6.000 aristas NO puede alcanzar esa cota: ver columna 'cota'.")
print()
print("### A) Ablacion REAL (se borra la clausula LIMIT del Cypher)")
for n in (300, 500, 1000, 2000):
    nodes, edges = build(n, n * 3)
    con, cotas_con = _mide(nodes, edges, FakeDriver)
    abl, _ = _mide(nodes, edges, DriverAblado)
    igual = "IDENTICO" if con == abl else "DIFIERE"
    print(f"n={n:5d} E={n*3:5d} cota_recibida={cotas_con[0]:>10,} "
          f"con_clausula={con} ablado={abl}  {igual}")

print()
print("### B) CONTROL POSITIVO: cota de 400, que SI muerde sobre estas fixturas.")
print("###    Si aqui no sale DIFIERE, el banco entero es ciego.")
for n in (300, 500, 1000, 2000):
    nodes, edges = build(n, n * 3)
    con, cotas_con = _mide(nodes, edges, DriverCotaQueMuerde)
    abl, _ = _mide(nodes, edges, DriverAblado)
    igual = "IDENTICO -> BANCO CIEGO" if con == abl else "DIFIERE  <- sabe verlo"
    print(f"n={n:5d} E={n*3:5d} cota_recibida={cotas_con[0]:>10,} "
          f"con_clausula={con} ablado={abl}  {igual}")

print()
print("### C) Contraste: camino NO autorizado (base.graph directo, limit=300).")
print("###    Aqui la cota si llega al provider y el LIMIT muerde de verdad.")
for n in (300, 2000):
    nodes, edges = build(n, n * 3)
    b1 = Neo4jGraphProvider.__new__(Neo4jGraphProvider); b1._driver = FakeDriver(nodes, edges)
    b2 = Neo4jGraphProvider.__new__(Neo4jGraphProvider); b2._driver = DriverAblado(nodes, edges)
    e1 = len(b1.graph("leyenda", limit=300)[1])
    e2 = len(b2.graph("leyenda", limit=300)[1])
    print(f"n={n:5d} con_clausula={e1:5d} aristas | ablado={e2:5d} aristas "
          f"| {'DIFIERE' if e1 != e2 else 'IDENTICO'}")
