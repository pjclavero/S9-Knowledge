"""Banco de medida del camino Neo4j con un driver de pega que ejecuta el
Cypher de verdad contra un grafo en memoria (misma semantica de LIMIT)."""
import sys, random
from pathlib import Path
VIEWER = Path(__file__).resolve().parents[3] / "viewer"
sys.path.insert(0, str(VIEWER))


class FakeNode(dict):
    @property
    def element_id(self): return self["id"]
    def items(self): return dict.items(self)


class FakeRel(dict):
    @property
    def element_id(self): return self["id"]
    @property
    def type(self): return self["type"]
    @property
    def start_node(self): return self["_sn"]
    @property
    def end_node(self): return self["_en"]
    def items(self): return dict.items(self)


class FakeSession:
    """Sesion de pega.

    La cota se aplica SOLO si la consulta trae la clausula ``LIMIT``. Asi,
    ablacionar = **quitar la clausula del Cypher**, no subir el parametro.
    Registra en ``cotas_vistas`` la cota efectiva de cada consulta de
    relaciones, para poder demostrar si podia morder o no.
    """

    def __init__(self, nodes, edges, cotas_vistas=None):
        self.nodes, self.edges = nodes, edges
        self.cotas_vistas = cotas_vistas if cotas_vistas is not None else []

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def run(self, query, params=None):
        p = params or {}
        tiene_clausula = "LIMIT" in query.upper()
        lim = p.get("limit", 10 ** 9) if tiene_clausula else 10 ** 9
        if "-[r]->" in query:                      # rel_query
            self.cotas_vistas.append(lim if tiene_clausula else None)
            out = []
            for e in self.edges:                   # LIMIT aplicado a RELACIONES
                if len(out) >= lim: break
                out.append({"n": self.nodes[e["_a"]], "r": e, "m": self.nodes[e["_b"]]})
            return out
        return [{"n": n} for n in self.nodes[:lim]]  # node_query


class FakeDriver:
    def __init__(self, nodes, edges):
        self.nodes, self.edges = nodes, edges
        self.cotas_vistas = []

    def session(self, *a, **k):
        return FakeSession(self.nodes, self.edges, self.cotas_vistas)


def build(n_nodes, n_edges, seed=7):
    rnd = random.Random(seed)
    nodes = [FakeNode({"id": f"n{i}", "canonical_name": f"E{i}", "entity_type": "Character",
                       "visibility": "reference", "workspace": "leyenda",
                       "scope": "juego"}) for i in range(n_nodes)]
    edges = []
    for k in range(n_edges):
        a, b = rnd.randrange(n_nodes), rnd.randrange(n_nodes)
        if a == b: b = (b + 1) % n_nodes
        r = FakeRel({"id": f"e{k}", "type": "RELATED_TO", "visibility": "reference", "scope": "juego", "workspace": "leyenda"})
        r["_a"], r["_b"] = a, b
        r["_sn"], r["_en"] = nodes[a], nodes[b]
        edges.append(r)
    return nodes, edges


if __name__ == "__main__":
    from app.providers.neo4j_provider import Neo4jGraphProvider
    prov = Neo4jGraphProvider.__new__(Neo4jGraphProvider)
    print("### camino Neo4j (Cypher real, driver de pega) limit=300")
    for n in (300, 500, 1000, 2000):
        nodes, edges = build(n, n * 3)
        prov._driver = FakeDriver(nodes, edges)
        gn, ge = prov.graph("leyenda", limit=300)
        print(f"n={n:5d} E={n*3:5d} | rel_query devuelve<= 300 (LIMIT sobre RELACIONES) "
              f"-> nodos={len(gn):4d} aristas={len(ge):4d} dens={len(ge)/max(1,len(gn)):.2f}")
