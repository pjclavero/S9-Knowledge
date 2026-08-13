"""GATE: el visor sabe si la vista es completa y, si no lo es, LO DICE.

Qué se afirma aquí
------------------
`docs/72` dejó demostrado que `/api/graph` devuelve el subgrafo inducido sobre
los primeros `limit` nodos y que por eso pierde relaciones cuadráticamente.
Este módulo NO arregla eso (el carril no lo tiene encomendado y el test de
caracterización `test_saturacion_grafo_caracterizacion.py` sigue fijando el
desplome). Lo que cierra es la parte que convertía una limitación técnica en
una afirmación falsa de producto: la respuesta no decía que estaba recortada y
el cliente presentaba el trozo como si fuera el grafo.

Las seis reglas del encargo, y dónde se comprueban cada una:

  1. saber si es completa o truncada  -> `test_caso_pequeno_completo`,
                                         `test_casos_saturados_declaran_truncado`
  2. declararlo visiblemente          -> `test_la_pagina_trae_el_hueco_del_aviso`,
                                         `test_el_cliente_pinta_el_aviso`, y en JS
                                         la sonda mutada de `test_graph_ux_v2.py`
                                         (vive alli porque es el fichero que el
                                         job con Node ejecuta POR NOMBRE; aqui se
                                         omitiria en silencio donde no hay Node)
  3. no inventar cifras               -> `test_el_cliente_no_calcula_cifras_propias`
  4. contadores POST-autorización     -> `test_los_totales_se_cuentan_despues_de_filtrar`,
                                         `test_ablacion_sin_permisos_los_totales_colapsan`
  5. pequeño completo + saturados     -> arriba, incluido el peor caso conocido
  6. ROJO si se quita el indicador    -> los `test_calibracion_*`

CALIBRACIÓN (la norma del proyecto, aplicada)
---------------------------------------------
Ningún control se cobra como defensa sin una mutación deliberada que lo ponga
rojo. Por eso las comprobaciones no son `assert` sueltos sino FUNCIONES
(`_exige_declaracion_de_parcialidad`, `_exige_hueco_del_aviso`, ...) a las que
se les pasa una respuesta o un contenido MUTADO para verificar que fallan. Un
test que sólo enseñara el aviso funcionando sería el décimo instrumento que
siempre dice que todo va bien.

Nota sobre el punto de inyección: `get_visibility_context` se llama como
función normal, no vía `Depends`, así que sobrescribirlo es INERTE. Aquí no se
simula ningún rol por esa vía: los contextos se pasan directamente al
`PolicyFilteredProvider`, y la prueba de que el control muerde es que al
quitarle permisos el resultado CAMBIA (`test_ablacion_sin_permisos_...`).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.authz.filtered_provider import PolicyFilteredProvider
from app.graph_view import SIN_TOPE, vista_truncada
from app.main import app
from app.policies.models import ViewerContext
from app.providers.mock_provider import MockGraphProvider
from app.serializers import serialize_graph
from test_saturacion_grafo_caracterizacion import LIMIT, _fixture, _viewer

VIEWER_ROOT = Path(__file__).resolve().parents[1]
GRAPH_HTML = VIEWER_ROOT / "app" / "templates" / "graph.html"
GRAPH_JS = VIEWER_ROOT / "app" / "static" / "js" / "graph.js"
GRAPH_CORE_JS = VIEWER_ROOT / "app" / "static" / "js" / "graph-core.js"

client = TestClient(app)


# ---------------------------------------------------------------------------
# El contrato del servidor, como función comprobable (no como assert suelto)
# ---------------------------------------------------------------------------
CLAVES_DE_VISTA = {
    "limit", "truncated", "nodes_shown", "nodes_total", "edges_shown", "edges_total",
}


def _exige_declaracion_de_parcialidad(payload: dict, *, truncada: bool) -> None:
    """El control calibrado. Rojo si falta `view`, si le faltan claves, si
    miente sobre el truncado o si los contadores no cuadran con los datos
    entregados."""
    view = payload.get("view")
    assert isinstance(view, dict), (
        "la respuesta de /api/graph NO declara si la vista es completa o "
        "truncada: falta el bloque `view`. Sin él el cliente presenta un "
        "trozo del grafo como si fuera el grafo."
    )
    faltan = CLAVES_DE_VISTA - set(view)
    assert not faltan, f"al bloque `view` le faltan claves: {sorted(faltan)}"
    assert view["truncated"] is truncada, (
        f"`truncated` dice {view['truncated']!r} y la vista {'SÍ' if truncada else 'NO'} "
        f"está recortada ({view['nodes_shown']}/{view['nodes_total']} nodos, "
        f"{view['edges_shown']}/{view['edges_total']} relaciones)."
    )
    assert view["nodes_shown"] == len(payload["nodes"]), "nodes_shown no cuenta lo entregado"
    assert view["edges_shown"] == len(payload["edges"]), "edges_shown no cuenta lo entregado"
    assert view["nodes_shown"] <= view["nodes_total"]
    assert view["edges_shown"] <= view["edges_total"]
    if truncada:
        assert (view["nodes_shown"] < view["nodes_total"]
                or view["edges_shown"] < view["edges_total"]), (
            "se declara truncada pero no falta nada: el metadato no describe la vista"
        )
    else:
        assert view["nodes_shown"] == view["nodes_total"]
        assert view["edges_shown"] == view["edges_total"]


def _respuesta(path: Path, *, limit: int = LIMIT, ctx: ViewerContext | None = None) -> dict:
    """Lo mismo que hace `/api/graph`, con el proveedor filtrado de verdad."""
    prov = PolicyFilteredProvider(MockGraphProvider(path), ctx or _viewer())
    todos_n, todas_e = prov.graph("leyenda", limit=SIN_TOPE)
    nodes, edges, view = vista_truncada(todos_n, todas_e, limit)
    return serialize_graph("leyenda", nodes, edges, view=view)


# ---------------------------------------------------------------------------
# Regla 5: un caso pequeño COMPLETO y varios saturados
# ---------------------------------------------------------------------------
def test_caso_pequeno_completo(tmp_path):
    """Con todo dentro del límite, la respuesta se declara COMPLETA: el aviso
    no puede convertirse en ruido permanente que se aprende a ignorar."""
    path, n_edges = _fixture(tmp_path, 50)
    payload = _respuesta(path, limit=LIMIT)

    assert len(payload["nodes"]) == 50
    assert len(payload["edges"]) == n_edges
    _exige_declaracion_de_parcialidad(payload, truncada=False)


@pytest.mark.parametrize("n_nodes", [500, 1000, 2000])
def test_casos_saturados_declaran_truncado(tmp_path, n_nodes):
    path, n_edges = _fixture(tmp_path, n_nodes)
    payload = _respuesta(path, limit=LIMIT)

    _exige_declaracion_de_parcialidad(payload, truncada=True)
    view = payload["view"]
    # Los totales son los del conjunto VISIBLE completo, no los del recorte.
    assert view["nodes_total"] == n_nodes
    assert view["edges_total"] == n_edges
    assert view["nodes_shown"] == LIMIT


def test_peor_caso_conocido_uniforme_2000(tmp_path):
    """El peor caso medido en `docs/72`: 2000 nodos uniformes, 2,85 % de las
    relaciones. Lo que se exige aquí no es la cifra —eso ya lo fija el test de
    caracterización— sino que la vista lo DIGA."""
    path, n_edges = _fixture(tmp_path, 2000)
    payload = _respuesta(path, limit=LIMIT)
    view = payload["view"]

    _exige_declaracion_de_parcialidad(payload, truncada=True)
    assert view["edges_shown"] / view["edges_total"] < 0.06, (
        "esto ya no es el peor caso caracterizado; revisar docs/72"
    )


def test_el_caso_alineado_tambien_se_declara(tmp_path):
    """La severidad depende de la alineación (2,85 % vs 15,33 %), pero la
    parcialidad NO: alineado sigue siendo una vista incompleta y se declara
    igual. Si el aviso sólo saliera en el caso sintético, en producción —que es
    el caso alineado— el visor volvería a mentir."""
    path, n_edges = _fixture(tmp_path, 2000, alineado=True)
    payload = _respuesta(path, limit=LIMIT)

    _exige_declaracion_de_parcialidad(payload, truncada=True)
    assert payload["view"]["edges_shown"] / n_edges > 0.05, "¿ya no es el caso alineado?"


def test_la_vista_del_router_es_byte_a_byte_la_del_proveedor(tmp_path):
    """SUPERVIVIENTE. `vista_truncada` reproduce el recorte del proveedor
    filtrado. Si algún día divergen, el visor enseñaría un grafo y contaría
    otro, en silencio. Aquí se exige la identidad."""
    for n_nodes in (50, 500, 2000):
        path, _ = _fixture(tmp_path, n_nodes)
        prov = PolicyFilteredProvider(MockGraphProvider(path), _viewer())
        esperados_n, esperadas_e = prov.graph("leyenda", limit=LIMIT)
        todos_n, todas_e = prov.graph("leyenda", limit=SIN_TOPE)
        nodes, edges, _view = vista_truncada(todos_n, todas_e, LIMIT)

        assert [n["id"] for n in nodes] == [n["id"] for n in esperados_n]
        assert [e["id"] for e in edges] == [e["id"] for e in esperadas_e]


# ---------------------------------------------------------------------------
# Regla 4: los contadores se calculan DESPUÉS de autorizar
# ---------------------------------------------------------------------------
def _mixto(tmp_path):
    """Grafo con material `reference` (restringido) y `player` (abierto)."""
    nodes, edges = [], []
    for i in range(40):
        nodes.append({
            "id": f"n{i}", "entity_id": f"n{i}", "label": f"E{i}", "type": "Character",
            "visibility": "reference" if i >= 10 else "player",
            "workspace": "leyenda", "scope": "juego", "knowledge_layer": "book",
            "review_status": "auto_extracted", "confidence": 0.9,
        })
    for k in range(39):
        a, b = k, k + 1
        edges.append({
            "id": f"e{k}", "from": f"n{a}", "to": f"n{b}", "type": "RELATED_TO",
            "label": "rel",
            "visibility": "reference" if max(a, b) >= 10 else "player",
            "workspace": "leyenda", "scope": "juego",
            "review_status": "auto_extracted", "confidence": 0.8,
        })
    p = tmp_path / "mixto.json"
    p.write_text(json.dumps({"workspace": "leyenda", "nodes": nodes, "edges": edges}),
                 encoding="utf-8")
    return p


def _sin_referencia() -> ViewerContext:
    return ViewerContext(
        role="viewer",
        allowed_workspaces=frozenset({"leyenda"}),
        can_view_reference=False,
        admin_full=False,
    )


def _exige_totales_autorizados(view: dict, *, nodos: int, relaciones: int) -> None:
    """Control calibrado de la regla 4: los totales publicados cuentan SOLO lo
    que esta persona puede ver."""
    assert view["nodes_total"] == nodos, (
        f"nodes_total = {view['nodes_total']}, autorizado = {nodos}: se está "
        f"contando material que esta persona NO puede ver. Fuga por conteo."
    )
    assert view["edges_total"] == relaciones, (
        f"edges_total = {view['edges_total']}, autorizado = {relaciones}: fuga por conteo."
    )


def test_los_totales_se_cuentan_despues_de_filtrar(tmp_path):
    """FUGA que este test impide: publicar "de 40" a quien sólo puede ver 10.

    Un total "real" calculado antes de filtrar revelaría por diferencia cuánto
    material oculto existe.
    """
    path = _mixto(tmp_path)
    payload = _respuesta(path, limit=LIMIT, ctx=_sin_referencia())

    _exige_totales_autorizados(payload["view"], nodos=10, relaciones=9)
    _exige_declaracion_de_parcialidad(payload, truncada=False)


def test_calibracion_contar_ANTES_de_filtrar_pone_el_gate_ROJO(tmp_path):
    """MUTACIÓN 4, la más delicada del carril: alguien "mejora" los totales
    contándolos sobre el proveedor BASE (sin política). La vista se vuelve una
    fuga y el control tiene que verlo.

    No es un número inventado a mano: se calcula de verdad con el proveedor sin
    filtrar, que es exactamente el error que se quiere impedir.
    """
    path = _mixto(tmp_path)
    ctx = _sin_referencia()

    # como está hoy: post-autorización
    _exige_totales_autorizados(_respuesta(path, ctx=ctx)["view"], nodos=10, relaciones=9)

    # la mutación: totales tomados del proveedor base, antes de la política
    base = MockGraphProvider(path)
    crudos_n, crudas_e = base.graph("leyenda", limit=SIN_TOPE)
    prov = PolicyFilteredProvider(base, ctx)
    vis_n, vis_e = prov.graph("leyenda", limit=SIN_TOPE)
    _, _, view_fugado = vista_truncada(crudos_n, crudas_e, LIMIT)

    assert len(crudos_n) > len(vis_n), "la mutación no muerde: la política no filtra nada aquí"
    with pytest.raises(AssertionError, match="Fuga por conteo"):
        _exige_totales_autorizados(view_fugado, nodos=10, relaciones=9)


def test_api_graph_http_declara_la_vista():
    """Extremo a extremo por HTTP con el grafo de ejemplo: el bloque `view`
    llega de verdad al cliente, no sólo a la función."""
    r = client.get("/api/graph", params={"workspace": "leyenda", "limit": 2000})
    assert r.status_code == 200
    _exige_declaracion_de_parcialidad(r.json(), truncada=False)

    r2 = client.get("/api/graph", params={"workspace": "leyenda", "limit": 1})
    assert r2.status_code == 200
    payload = r2.json()
    assert len(payload["nodes"]) == 1
    _exige_declaracion_de_parcialidad(payload, truncada=True)


# ---------------------------------------------------------------------------
# Regla 6 + calibración: ROJO si se rompe o se quita el indicador
# ---------------------------------------------------------------------------
def test_calibracion_sin_bloque_view_el_gate_se_pone_rojo(tmp_path):
    """MUTACIÓN 1: el servidor deja de mandar `view` (la regresión exacta que
    existía antes de este carril)."""
    path, _ = _fixture(tmp_path, 2000)
    payload = _respuesta(path)
    _exige_declaracion_de_parcialidad(payload, truncada=True)  # verde antes

    payload.pop("view")
    with pytest.raises(AssertionError, match="NO declara si la vista"):
        _exige_declaracion_de_parcialidad(payload, truncada=True)


def test_calibracion_un_view_mutilado_el_gate_se_pone_rojo(tmp_path):
    """MUTACIÓN 2: `view` está, pero le falta una clave (rompe el metadato sin
    borrarlo: el sabotaje sutil)."""
    path, _ = _fixture(tmp_path, 2000)
    for clave in sorted(CLAVES_DE_VISTA):
        payload = _respuesta(path)
        payload["view"].pop(clave)
        with pytest.raises(AssertionError):
            _exige_declaracion_de_parcialidad(payload, truncada=True)


def test_calibracion_un_view_que_miente_el_gate_se_pone_rojo(tmp_path):
    """MUTACIÓN 3: la peor de todas — el metadato existe y dice "completa"
    sobre una vista recortada."""
    path, _ = _fixture(tmp_path, 2000)
    payload = _respuesta(path)
    payload["view"]["truncated"] = False
    with pytest.raises(AssertionError, match="truncated"):
        _exige_declaracion_de_parcialidad(payload, truncada=True)

    payload = _respuesta(path)
    payload["view"]["nodes_total"] = payload["view"]["nodes_shown"]
    payload["view"]["edges_total"] = payload["view"]["edges_shown"]
    with pytest.raises(AssertionError, match="no falta nada"):
        _exige_declaracion_de_parcialidad(payload, truncada=True)


# ---------------------------------------------------------------------------
# Regla 2 y 3: el cliente lo declara VISIBLEMENTE y no inventa cifras
# ---------------------------------------------------------------------------
def _exige_hueco_del_aviso(html: str) -> None:
    assert 'id="graph-partiality"' in html, (
        "la página del visor no tiene dónde pintar el aviso de vista parcial"
    )
    bloque = re.search(r'<p id="graph-partiality"[^>]*>', html)
    assert bloque, "el aviso no es un elemento propio"
    assert 'role="alert"' in bloque.group(0), (
        "el aviso debe anunciarse como ALERTA: no es un estado más de carga"
    )


def _exige_que_el_cliente_pinte_el_aviso(js: str) -> None:
    assert "graph-partiality" in js, "el cliente no busca el hueco del aviso"
    assert "partialityNotice" in js, "el cliente no calcula el aviso"
    assert re.search(r"lastView\s*=\s*data\.view\s*\|\|\s*\{\}", js), (
        "el cliente debe quedarse con `view` y tratar su AUSENCIA como vista "
        "posiblemente incompleta (`|| {}`); si guarda `null` se calla."
    )


def test_la_pagina_trae_el_hueco_del_aviso():
    _exige_hueco_del_aviso(GRAPH_HTML.read_text(encoding="utf-8"))


def test_el_cliente_pinta_el_aviso():
    _exige_que_el_cliente_pinte_el_aviso(GRAPH_JS.read_text(encoding="utf-8"))


def test_calibracion_si_se_borra_el_aviso_de_la_pagina_el_gate_se_pone_rojo():
    """MUTACIÓN 5: quitar el elemento del aviso de la plantilla."""
    html = GRAPH_HTML.read_text(encoding="utf-8")
    mutado = re.sub(r'<p id="graph-partiality".*?</p>', "", html, flags=re.S)
    assert mutado != html, "la mutación no ha mordido: revisar el patrón"
    with pytest.raises(AssertionError, match="dónde pintar"):
        _exige_hueco_del_aviso(mutado)

    sin_alerta = html.replace('id="graph-partiality" class="graph-partiality" role="alert"',
                              'id="graph-partiality" class="graph-partiality" role="status"')
    assert sin_alerta != html
    with pytest.raises(AssertionError, match="ALERTA"):
        _exige_hueco_del_aviso(sin_alerta)


def test_calibracion_si_el_cliente_deja_de_pintarlo_el_gate_se_pone_rojo():
    """MUTACIÓN 6: el cliente vuelve al comportamiento anterior (ignorar
    `view`, o guardarlo sin el fail-closed)."""
    js = GRAPH_JS.read_text(encoding="utf-8")
    mutado = js.replace("core.partialityNotice(lastView)", "null")
    assert mutado != js
    with pytest.raises(AssertionError, match="no calcula el aviso"):
        _exige_que_el_cliente_pinte_el_aviso(mutado)

    fail_open = js.replace("lastView = data.view || {};", "lastView = data.view || null;")
    assert fail_open != js
    with pytest.raises(AssertionError, match="posiblemente incompleta"):
        _exige_que_el_cliente_pinte_el_aviso(fail_open)


def test_el_cliente_no_calcula_cifras_propias():
    """Regla 3. Los números del aviso salen del servidor tal cual: en la
    función que lo redacta no hay resta, ni porcentaje, ni estimación."""
    core = GRAPH_CORE_JS.read_text(encoding="utf-8")
    cuerpo = core.split("function partialityNotice(view)")[1].split("\n  function ")[0]
    # Sólo el código: los comentarios pueden decir lo que haga falta.
    codigo = "\n".join(
        l for l in cuerpo.splitlines()
        if not l.strip().startswith(("//", "*", "/*"))
    )
    for operador, queja in (
        (" - ", "resta cifras por su cuenta"),
        ("%", "calcula un porcentaje que nadie le ha dado"),
        ("/", "divide cifras por su cuenta"),
        ("toFixed", "da una cifra derivada, no la que dijo el servidor"),
    ):
        assert operador not in codigo, "el aviso " + queja
