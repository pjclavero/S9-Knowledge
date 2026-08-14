"""Banco de medida (no versionado): balance por capa de /api/graph.

LORE-ANONIMO-DENEGADO (V3 RC, 2026-08-14) — POR QUE ESTE BANCO PIDE UNA LLAVE
----------------------------------------------------------------------------
Las fixturas de este banco son `scope="juego"` (capa juego), y desde la decision
del operador la capa juego exige `can_view_lore`. El contexto de este harness se
construye A MANO, asi que no pasa por `build_viewer_context` y no recibe nada
que el productor no le pongan aqui.

Sin `can_view_lore=True` este banco NO revienta: todos sus nodos caen en
`lore_not_allowed`, mide CERO y **no lo dice**. Es decir, se convierte en el
mismo fallo silencioso que este banco existe para detectar, un nivel mas arriba.
Ningun test ni CI lo ejecuta, asi que nada se pondria rojo.

Un revisor AUTENTICADO tiene la llave, luego anadirla es lo que REPRODUCE la
medida registrada, no lo que la relaja: no se toca workspace, ni partida, ni
`known_by`, ni el tope de sesion, ni `admin_full` (que sigue en False, porque
con bypass la columna `drop_politica` seria un instrumento muerto).

Los otros tres bancos de este directorio (`harness_ablacion`, `harness_opciones`,
`harness_http`) tenian exactamente la misma forma y llevan la misma linea.
"""
import json, os, sys, random, tempfile
from pathlib import Path
VIEWER = Path(__file__).resolve().parents[3] / "viewer"
sys.path.insert(0, str(VIEWER))
os.environ["S9K_GRAPH_PROVIDER"] = "mock"
os.environ["S9K_DEFAULT_WORKSPACE"] = "leyenda"
os.environ.setdefault("S9K_CSRF_SECRET", "x" * 64)
os.environ.setdefault("S9K_SESSION_SECURE", "false")


COMUNIDAD = 100  # entidades por "documento": tamano de comunidad densa


def build(n_nodes, n_edges, mode="random", seed=7, edge_vis="reference", node_vis="reference"):
    """Modos:

    - ``random``      : aristas uniformes. **Peor caso**: el orden de
                        almacenamiento no guarda ninguna relacion con la
                        topologia.
    - ``head``        : control positivo (todas las aristas entre los 300
                        primeros nodos).
    - ``comunidades`` : entidades del mismo "documento" consecutivas Y
                        densamente interconectadas -> orden ALINEADO con la
                        topologia. Es el caso plausible de produccion.
    - ``comunidades_barajadas``: misma topologia, ids repartidos al azar ->
                        aisla si lo que manda es la topologia o la ALINEACION.
    """
    rnd = random.Random(seed)
    orden = list(range(n_nodes))
    if mode == "comunidades_barajadas":
        rnd.shuffle(orden)          # comunidad c -> posiciones dispersas
    pos = {c: i for i, c in enumerate(orden)}   # id_comunidad -> indice de almacen

    nodes = [{"id": f"n{i}", "entity_id": f"n{i}", "label": f"E{i}", "type": "Character",
              "visibility": node_vis, "workspace": "leyenda", "scope": "juego",
              "knowledge_layer": "book", "review_status": "auto_extracted", "confidence": 0.9}
             for i in range(n_nodes)]
    edges = []
    for k in range(n_edges):
        if mode == "random":
            a, b = rnd.randrange(n_nodes), rnd.randrange(n_nodes)
        elif mode == "head":     # control: todas las aristas entre los 300 primeros nodos
            a, b = rnd.randrange(min(300, n_nodes)), rnd.randrange(min(300, n_nodes))
        elif mode == "chain":
            a = k % max(1, n_nodes - 1); b = a + 1
        elif mode in ("comunidades", "comunidades_barajadas"):
            # Ambos extremos dentro de la misma comunidad de COMUNIDAD miembros.
            base = rnd.randrange(max(1, n_nodes // COMUNIDAD)) * COMUNIDAD
            ancho = min(COMUNIDAD, n_nodes - base)
            a = pos[base + rnd.randrange(ancho)]
            b = pos[base + rnd.randrange(ancho)]
        if a == b:
            b = (b + 1) % n_nodes
        edges.append({"id": f"e{k}", "from": f"n{a}", "to": f"n{b}", "type": "RELATED_TO",
                      "label": "rel", "visibility": edge_vis, "workspace": "leyenda",
                      "scope": "juego", "review_status": "auto_extracted", "confidence": 0.8})
    p = Path(tempfile.mkdtemp()) / "g.json"
    p.write_text(json.dumps({"workspace": "leyenda", "nodes": nodes, "edges": edges}), encoding="utf-8")
    return p


def measure(path, limit):
    from app.providers.mock_provider import MockGraphProvider
    from app.authz.filtered_provider import PolicyFilteredProvider, _ALL
    from app.policies.engine import VisibilityPolicy
    from app.policies.models import ViewerContext
    from app.serializers import serialize_graph
    import inspect
    base = MockGraphProvider(path)
    pol = VisibilityPolicy()
    # Espectador REAL, sin bypass: si usaramos admin_full=True la politica no
    # se evaluaria y la columna "drop_politica" seria un instrumento muerto.
    ctx = ViewerContext(
        role="reviewer",
        allowed_workspaces=frozenset({"leyenda"}),
        can_view_reference=True,
        can_view_secret=False,
        can_view_future=False,
        # LORE-ANONIMO-DENEGADO (V3 RC, 2026-08-14): ver nota de cabecera.
        can_view_lore=True,
        admin_full=False,
    )
    prov = PolicyFilteredProvider(base, ctx, pol)
    R = {}
    R["L0_store_edges"] = len(base._edges)
    bn, be = base.graph("leyenda", limit=_ALL)
    R["L1_base_ALL_nodes"], R["L1_base_ALL_edges"] = len(bn), len(be)
    bn2, be2 = base.graph("leyenda", limit=limit)
    R["L1b_base_limit_edges"] = len(be2)
    vnodes_full = pol.filter_nodes(bn, ctx)
    R["L2_nodes_visibles"] = len(vnodes_full)
    vnodes = vnodes_full[:limit]
    R["L2_nodes_tras_truncar"] = len(vnodes)
    vids = {n["id"] for n in vnodes}
    drop_trunc = drop_pol = 0
    for e in be:
        if e["from"] not in vids or e["to"] not in vids:
            drop_trunc += 1
        elif not pol.can_view(e, ctx).visible:
            drop_pol += 1
    R["L3_edges_in"] = len(be)
    R["L3_drop_truncado"] = drop_trunc
    R["L3_drop_politica"] = drop_pol
    vedges = pol.filter_edges(be, vids, ctx)
    R["L3_edges_out"] = len(vedges)
    ser = serialize_graph("leyenda", vnodes, vedges)
    R["L4_serial_nodes"], R["L4_serial_edges"] = len(ser["nodes"]), len(ser["edges"])
    conectados = {e["from"] for e in vedges} | {e["to"] for e in vedges}
    R["nodos_sueltos"] = len(vnodes) - len(conectados & vids)
    R["L5_json_bytes"] = len(json.dumps(ser))
    pn, pe = prov.graph("leyenda", limit=limit)
    R["Lprov_nodes"], R["Lprov_edges"] = len(pn), len(pe)
    return R


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="random")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--edge-vis", default="reference")
    a = ap.parse_args()
    print(f"### modo={a.mode} limit={a.limit} edge_vis={a.edge_vis}")
    for n in (300, 500, 1000, 2000):
        p = build(n, n * 3, mode=a.mode, edge_vis=a.edge_vis)
        R = measure(p, a.limit)
        pred = n * 3 * (min(a.limit, n) / n) ** 2
        print(f"n={n:5d} E={n*3:5d} | L0={R['L0_store_edges']:5d} L1_ALL={R['L1_base_ALL_edges']:5d} "
              f"L1_limit={R['L1b_base_limit_edges']:5d} L3in={R['L3_edges_in']:5d} "
              f"L3out={R['L3_edges_out']:5d} L4={R['L4_serial_edges']:5d} prov={R['Lprov_edges']:5d} "
              f"nodos={R['L4_serial_nodes']:4d} | trunc={R['L3_drop_truncado']:5d} "
              f"pol={R['L3_drop_politica']:5d} | pred(L/N)^2={pred:7.1f} "
              f"| dens={R['L3_edges_out']/max(1,R['L4_serial_nodes']):.2f} "
              f"sueltos={R['nodos_sueltos']:4d} cob={100*R['L3_edges_out']/max(1,n*3):5.2f}% "
              f"bytes={R['L5_json_bytes']}")
