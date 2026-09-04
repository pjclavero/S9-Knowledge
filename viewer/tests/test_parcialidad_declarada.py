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

from app.authz.dependencies import get_filtered_provider
from app.authz.filtered_provider import PolicyFilteredProvider
from app.graph_view import SIN_TOPE, vista_truncada
from app.main import app
from app.policies.models import ViewerContext
from app.providers.mock_provider import MockGraphProvider
from app.serializers import serialize_graph
from test_saturacion_grafo_caracterizacion import LIMIT, _fixture, _viewer

# Esta suite es CRITICA para `.github/scripts/check_suite_inventory.py`: si se
# silencia o desaparece, CI se pone ROJO.
#
# El marcador esta puesto A MANO, y merece la explicacion. La deteccion de
# suites criticas de ese gate se DERIVA de los arneses de calibracion que usan
# una suite como instrumento (`artifacts/identidad-durable/calibrar.py`,
# `scripts/calibrar_panel_*.py`, `scripts/calibracion/mutaciones_*.py`), y asi
# salen 18 modulos solos, sin lista. Esta suite no la usa todavia ningun arnes
# de esos —su calibracion es interna, los `test_calibracion_*` de aqui abajo—,
# asi que la derivacion no la alcanza. El ejercicio RC 1 la silencio y CI
# siguio verde con 1554 passed; no puede quedar fuera esperando a que algun dia
# aparezca un calibrador que la nombre.
#
# `critico` esta registrado en `pytest.ini` y no altera la ejecucion.
pytestmark = pytest.mark.critico

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


def _exige_declaracion_de_parcialidad(payload: dict, *, truncada: bool,
                                      limite: int) -> None:
    """El control calibrado. Rojo si falta `view`, si le faltan claves, si
    miente sobre el truncado o si los contadores no cuadran con los datos
    entregados.

    `limite` NO es opcional (carril 4 de V3.1). La versión anterior comprobaba
    que la clave `limit` ESTUVIERA, jamás su valor, y el cliente tampoco lo
    consume: medido sobre `main=aaf9695`, mutar `viewer/app/graph_view.py` para
    publicar `"limit": 999999` dejaba la suite entera en verde (1576 passed).
    Un metadato cuyo valor nadie comprueba no declara nada: es una clave.

    Se exige como argumento OBLIGATORIO a propósito. Un valor por defecto
    (`limite: int | None = None`, «si no me lo dices no lo compruebo») dejaría
    que una llamada futura recuperase el superviviente sin escribir nada
    sospechoso: la comprobación se apagaría por omisión, que es exactamente
    cómo se apagan los controles en este repo.
    """
    view = payload.get("view")
    assert isinstance(view, dict), (
        "la respuesta de /api/graph NO declara si la vista es completa o "
        "truncada: falta el bloque `view`. Sin él el cliente presenta un "
        "trozo del grafo como si fuera el grafo."
    )
    faltan = CLAVES_DE_VISTA - set(view)
    assert not faltan, f"al bloque `view` le faltan claves: {sorted(faltan)}"
    # EL VALOR, no la clave. `limit` dice bajo qué tope se ha construido esta
    # vista; si publica otro número, el aviso describe una vista que nadie
    # pidió y las cifras de al lado dejan de ser comprobables contra nada.
    assert view["limit"] == limite, (
        f"`view.limit` publica {view['limit']!r} y la vista se construyó con "
        f"tope {limite!r}. La clave está y MIENTE: es el superviviente medido "
        f"sobre main=aaf9695."
    )
    # Y el valor tiene que ser un entero de verdad: `\"300\"` == 300 es falso en
    # Python pero un `limit` que viaja como cadena rompe al cliente sin que la
    # igualdad de arriba lo distinga de un número equivocado.
    assert isinstance(view["limit"], int) and not isinstance(view["limit"], bool), (
        f"`view.limit` no es un entero: {view['limit']!r}"
    )
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


# ---------------------------------------------------------------------------
# Los SEIS valores, uno a uno, contra cifras calculadas FUERA del metadato
# ---------------------------------------------------------------------------
#: Mensaje con el que se queja cada clave. Es el ANCLA de la calibración de más
#: abajo: cada falseo tiene que producir SU queja y no la del vecino, o el rojo
#: sería prestado y una clave podría quedarse sin vigilancia sin que se note.
_QUEJA = {
    "limit": "`view.limit`",
    "truncated": "`truncated`",
    "nodes_shown": "`nodes_shown`",
    "nodes_total": "`nodes_total`",
    "edges_shown": "`edges_shown`",
    "edges_total": "`edges_total`",
}


def _exige_contadores_por_valor(
    view: dict, *, limite: int, nodos_autorizados: int, relaciones_autorizadas: int,
    nodos_entregados: int, relaciones_entregadas: int,
) -> None:
    """Las SEIS cifras comprobadas por VALOR contra números de fuera del bloque.

    QUÉ APORTA ESTO, MEDIDO Y NO SUPUESTO
    -------------------------------------
    **Atribución, no cobertura.** La primera redacción de este carril daba a
    entender que los totales estaban sin comprobar, y eso era una garantía
    cobrada más ancha de lo que la medida sostiene. Mutando
    `viewer/app/graph_view.py` una a una contra el fichero de pruebas de
    `main=aaf9695` (reversión verificada por SHA-256):

        limit       -> 999999        aaf9695: 22 passed  <- ÚNICO SUPERVIVIENTE
        nodes_total -> recorte       aaf9695:  4 failed
        edges_total -> recorte       aaf9695:  5 failed
        edges_shown -> todas         aaf9695:  8 failed
        nodes_shown -> todos         aaf9695:  9 failed
        truncated   -> sólo nodos    aaf9695:  2 failed

    Los cinco contadores YA enrojecían — no dentro de
    `_exige_declaracion_de_parcialidad`, sino repartidos por los casos
    saturados. Lo que faltaba, y es lo que añade esta función, es que el rojo
    **diga de quién es**: cada aserción nombra su clave (`_QUEJA`) y la
    calibración exige que falsear `nodes_total` produzca la queja de
    `nodes_total`, no la de su vecina. Sin eso, una clave puede quedarse sin
    vigilancia propia viviendo del rojo prestado de otra y nadie lo nota.

    El único superviviente genuino era `limit`.

    Las cifras se traen calculadas por otro camino (el proveedor filtrado
    pedido SIN TOPE): derivarlas del `view` que se quiere comprobar sería una
    tautología.
    """
    assert view["limit"] == limite, (
        f"{_QUEJA['limit']} publica {view['limit']!r}, tope real {limite!r}")
    assert view["nodes_shown"] == nodos_entregados, (
        f"{_QUEJA['nodes_shown']} publica {view['nodes_shown']!r}, entregados "
        f"{nodos_entregados!r}")
    assert view["edges_shown"] == relaciones_entregadas, (
        f"{_QUEJA['edges_shown']} publica {view['edges_shown']!r}, entregadas "
        f"{relaciones_entregadas!r}")
    assert view["nodes_total"] == nodos_autorizados, (
        f"{_QUEJA['nodes_total']} publica {view['nodes_total']!r}, autorizados "
        f"{nodos_autorizados!r}")
    assert view["edges_total"] == relaciones_autorizadas, (
        f"{_QUEJA['edges_total']} publica {view['edges_total']!r}, autorizadas "
        f"{relaciones_autorizadas!r}")
    esperado = (nodos_entregados < nodos_autorizados
                or relaciones_entregadas < relaciones_autorizadas)
    assert view["truncated"] is esperado, (
        f"{_QUEJA['truncated']} publica {view['truncated']!r} y las cifras "
        f"reales dicen {esperado!r}")


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
    _exige_declaracion_de_parcialidad(payload, truncada=False, limite=LIMIT)


@pytest.mark.parametrize("n_nodes", [500, 1000, 2000])
def test_casos_saturados_declaran_truncado(tmp_path, n_nodes):
    path, n_edges = _fixture(tmp_path, n_nodes)
    payload = _respuesta(path, limit=LIMIT)

    _exige_declaracion_de_parcialidad(payload, truncada=True, limite=LIMIT)
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

    _exige_declaracion_de_parcialidad(payload, truncada=True, limite=LIMIT)
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

    _exige_declaracion_de_parcialidad(payload, truncada=True, limite=LIMIT)
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


def _exige_truncado_por_relaciones(nodes, edges, limit) -> None:
    """Control calibrado de la SEGUNDA cláusula de `truncated`.

    La cabecera de este carril afirma: «truncada si falta CUALQUIER cosa —
    pueden caber todos los nodos y faltar relaciones igualmente». Esa mitad de
    la afirmación estaba **cobrada sin control**: el revisor demostró que
    reducir `truncated` a `len(mostrados) < len(nodes)` dejaba TODA la suite en
    verde. Una garantía sin una mutación capaz de ponerla roja no vale, aunque
    hoy sea inofensiva.
    """
    _, relaciones, view = vista_truncada(nodes, edges, limit)
    assert view["nodes_shown"] == view["nodes_total"], "el caso exige que los nodos QUEPAN"
    assert len(relaciones) < len(edges), "el caso exige que falte alguna relación"
    assert view["truncated"] is True, (
        "caben todos los nodos pero faltan relaciones y la vista se declara "
        "COMPLETA. Es exactamente el desplome cuadrático presentado como grafo "
        "entero: la segunda cláusula de `truncated` no está haciendo su trabajo."
    )


# Nodos que caben de sobra y una relación COLGANTE (un extremo fuera del
# conjunto). No es alcanzable desde el router de hoy (ver el test siguiente),
# pero `vista_truncada` es una función pública (`__all__`) y responde de lo que
# promete para cualquier entrada válida.
_NODOS_QUE_CABEN = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
_RELACIONES_CON_UNA_COLGANTE = [
    {"id": "e1", "from": "a", "to": "b"},
    {"id": "e2", "from": "b", "to": "FUERA"},
]


def test_truncado_por_relaciones_aunque_quepan_todos_los_nodos():
    _exige_truncado_por_relaciones(_NODOS_QUE_CABEN, _RELACIONES_CON_UNA_COLGANTE, 300)


def test_calibracion_quitar_la_segunda_clausula_de_truncated_pone_el_gate_ROJO():
    """MUTACIÓN 8 (la que faltaba): `truncated` reducido a mirar sólo los nodos.

    QUÉ CALIBRA ESTE TEST, exactamente: parchea el nombre `vista_truncada` en el
    global de ESTE módulo de test, no `app.graph_view.vista_truncada`. Es decir,
    demuestra que **el helper de aserción sabe ponerse rojo**, no que la línea
    fuente esté guardada.

    **Quien guarda la línea fuente es el caso directo** de arriba
    (`test_truncado_por_relaciones_aunque_quepan_todos_los_nodos`): con la
    segunda cláusula suprimida en `viewer/app/graph_view.py`, ese caso se pone
    ROJO contra el árbol mutado (comprobado; verde → rojo → revertir → verde).
    División de trabajo deliberada: uno prueba el instrumento, el otro el
    sistema.
    """
    import app.graph_view as gv

    original = gv.vista_truncada
    _exige_truncado_por_relaciones(_NODOS_QUE_CABEN, _RELACIONES_CON_UNA_COLGANTE, 300)  # verde

    def mutante(nodes, edges, limit):
        mostrados, relaciones, view = original(nodes, edges, limit)
        view["truncated"] = len(mostrados) < len(nodes)  # <- sólo la 1ª cláusula
        return mostrados, relaciones, view

    globals()["vista_truncada"] = mutante
    try:
        with pytest.raises(AssertionError, match="COMPLETA"):
            _exige_truncado_por_relaciones(
                _NODOS_QUE_CABEN, _RELACIONES_CON_UNA_COLGANTE, 300
            )
    finally:
        globals()["vista_truncada"] = original

    # revertido: verde otra vez, en el mismo proceso
    _exige_truncado_por_relaciones(_NODOS_QUE_CABEN, _RELACIONES_CON_UNA_COLGANTE, 300)


def test_la_rama_de_relaciones_es_INALCANZABLE_desde_el_router_de_hoy(tmp_path):
    """Por qué el caso anterior es una garantía de la función y no un defecto de
    producto: con `SIN_TOPE` las relaciones se computan sobre TODOS los nodos
    visibles, así que si los nodos caben, caben todas. No hay relación colgante
    posible por esta vía.

    Y este test **vigila esa condición de verdad**. La primera versión no lo
    hacía: usaba sólo fixturas de 50 y 200 nodos con `limit=300`, donde el tope
    del router nunca muerde, así que seguía VERDE con el router mutado a
    `limit=limit` — un test que decía vigilar algo y no reaccionaba cuando eso
    cambiaba. El bloque con `limit < n_nodes` es el que muerde: si el router
    dejara de pedir sin tope, `nodes_total` pasaría de 2000 a 300 (contaría el
    recorte en vez del conjunto visible) y esto se pone ROJO.
    """
    # (a) el invariante: si caben los nodos, caben todas las relaciones.
    for n_nodes in (50, 200):
        path, n_edges = _fixture(tmp_path, n_nodes)
        payload = _respuesta(path, limit=300)  # limit > n_nodes: caben todos
        assert payload["view"]["nodes_shown"] == payload["view"]["nodes_total"]
        assert payload["view"]["edges_shown"] == n_edges, (
            "caben todos los nodos y aun así falta alguna relación: la rama "
            "'colgante' ha dejado de ser inalcanzable desde el router"
        )
        assert payload["view"]["truncated"] is False

    # (b) la condición que lo sostiene, donde el tope SÍ muerde. Va por el
    # ROUTER DE VERDAD (`TestClient` + `dependency_overrides`), no por
    # `_respuesta`, que es una reimplementación local y por tanto no puede ver
    # un cambio en el router: ése fue justo el fallo de la primera versión.
    # `get_filtered_provider` SÍ se inyecta por `Depends` (a diferencia de
    # `get_visibility_context`), así que sobrescribirlo no es inerte — y que
    # `nodes_total` valga 2000 lo demuestra: el grafo de ejemplo no los tiene.
    n_nodes = 2000
    path, n_edges = _fixture(tmp_path, n_nodes)
    app.dependency_overrides[get_filtered_provider] = lambda: PolicyFilteredProvider(
        MockGraphProvider(path), _viewer()
    )
    try:
        r = client.get("/api/graph", params={"workspace": "leyenda", "limit": 300})
        assert r.status_code == 200
        view = r.json()["view"]
    finally:
        app.dependency_overrides.pop(get_filtered_provider, None)

    assert view["nodes_total"] == n_nodes, (
        f"nodes_total = {view['nodes_total']} en vez de {n_nodes}: el router ha "
        f"dejado de pedir SIN TOPE y está contando su propio recorte. Con eso, "
        f"la garantía 'si caben los nodos caben todas las relaciones' deja de "
        f"sostenerse y la segunda cláusula de `truncated` pasa de inalcanzable "
        f"a imprescindible."
    )
    assert view["edges_total"] == n_edges
    assert view["nodes_shown"] == 300 and view["truncated"] is True


def test_el_criterio_de_id_es_el_mismo_que_el_del_proveedor():
    """Deriva silenciosa que el test byte-a-byte no cubría: el proveedor usa
    `"id" in n` y `vista_truncada` usaba `n.get("id") is not None`. Difieren
    ante un nodo con `id=None`, que ninguna fixture generaba."""
    nodes = [{"id": None}, {"id": "b"}]
    edges = [{"id": "e1", "from": None, "to": "b"}]
    _, relaciones, _ = vista_truncada(nodes, edges, 300)

    # Criterio del proveedor (copiado de `PolicyFilteredProvider.graph`).
    ids_proveedor = {n["id"] for n in nodes if "id" in n}
    esperadas = [e for e in edges
                 if e.get("from") in ids_proveedor and e.get("to") in ids_proveedor]
    assert [e["id"] for e in relaciones] == [e["id"] for e in esperadas], (
        "el criterio de identidad de `vista_truncada` ya no es el del proveedor"
    )


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
        can_view_lore=True,  # LORE-ANONIMO-DENEGADO: lector autenticado
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
    _exige_declaracion_de_parcialidad(payload, truncada=False, limite=LIMIT)


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


def test_api_graph_http_declara_la_vista(lector_por_dependencia):
    """Extremo a extremo por HTTP con el grafo de ejemplo: el bloque `view`
    llega de verdad al cliente, no sólo a la función."""
    # LORE-ANONIMO-DENEGADO (V3 RC, 2026-08-14): sin principal ya no se
    # entrega la capa juego, asi que esta prueba de FORMA necesita un lector
    # con derecho. Lo instala por las dependencias que si muerden.
    lector_por_dependencia(app)
    r = client.get("/api/graph", params={"workspace": "leyenda", "limit": 2000})
    assert r.status_code == 200
    _exige_declaracion_de_parcialidad(r.json(), truncada=False, limite=2000)

    r2 = client.get("/api/graph", params={"workspace": "leyenda", "limit": 1})
    assert r2.status_code == 200
    payload = r2.json()
    assert len(payload["nodes"]) == 1
    _exige_declaracion_de_parcialidad(payload, truncada=True, limite=1)


# ---------------------------------------------------------------------------
# Regla 6 + calibración: ROJO si se rompe o se quita el indicador
# ---------------------------------------------------------------------------
def test_calibracion_sin_bloque_view_el_gate_se_pone_rojo(tmp_path):
    """MUTACIÓN 1: el servidor deja de mandar `view` (la regresión exacta que
    existía antes de este carril)."""
    path, _ = _fixture(tmp_path, 2000)
    payload = _respuesta(path)
    _exige_declaracion_de_parcialidad(payload, truncada=True, limite=LIMIT)  # verde antes

    payload.pop("view")
    with pytest.raises(AssertionError, match="NO declara si la vista"):
        _exige_declaracion_de_parcialidad(payload, truncada=True, limite=LIMIT)


def test_calibracion_un_view_mutilado_el_gate_se_pone_rojo(tmp_path):
    """MUTACIÓN 2: `view` está, pero le falta una clave (rompe el metadato sin
    borrarlo: el sabotaje sutil)."""
    path, _ = _fixture(tmp_path, 2000)
    for clave in sorted(CLAVES_DE_VISTA):
        payload = _respuesta(path)
        payload["view"].pop(clave)
        with pytest.raises(AssertionError):
            _exige_declaracion_de_parcialidad(payload, truncada=True, limite=LIMIT)


def test_calibracion_un_view_que_miente_el_gate_se_pone_rojo(tmp_path):
    """MUTACIÓN 3: la peor de todas — el metadato existe y dice "completa"
    sobre una vista recortada."""
    path, _ = _fixture(tmp_path, 2000)
    payload = _respuesta(path)
    payload["view"]["truncated"] = False
    with pytest.raises(AssertionError, match="truncated"):
        _exige_declaracion_de_parcialidad(payload, truncada=True, limite=LIMIT)

    payload = _respuesta(path)
    payload["view"]["nodes_total"] = payload["view"]["nodes_shown"]
    payload["view"]["edges_total"] = payload["view"]["edges_shown"]
    with pytest.raises(AssertionError, match="no falta nada"):
        _exige_declaracion_de_parcialidad(payload, truncada=True, limite=LIMIT)


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


# ===========================================================================
# CARRIL 4 de V3.1: PARCIALIDAD POR VALOR
#
# EL SUPERVIVIENTE, y sólo él: mutando `viewer/app/graph_view.py`
# (`"limit": limit` -> `"limit": 999999`) la suite entera seguía VERDE
# (1576 passed sobre `main=aaf9695`). Causa: `CLAVES_DE_VISTA` comprobaba la
# PRESENCIA de la clave y jamás su valor, y el cliente tampoco la consume. Una
# clave presente con el valor equivocado no es una declaración: es un adorno
# con nombre de declaración.
#
# Los otros cinco contadores NO eran supervivientes: falsear cualquiera de
# ellos ya ponía roja la suite de `aaf9695` (la tabla está medida en el
# docstring de `_exige_contadores_por_valor`). Lo que esta sección les añade no
# es cobertura sino ATRIBUCIÓN: que cada rojo nombre su clave, para que ninguna
# viva del rojo prestado de otra.
# ===========================================================================

def _cifras_reales(path: Path, *, limit: int, ctx: ViewerContext | None = None):
    """Las cinco cifras calculadas SIN mirar el bloque `view`.

    Se obtienen del proveedor filtrado pedido SIN TOPE (el conjunto autorizado
    completo) y del recorte hecho aparte. Si se derivaran del propio `view` que
    se quiere comprobar, la comparación sería una tautología.
    """
    prov = PolicyFilteredProvider(MockGraphProvider(path), ctx or _viewer())
    todos_n, todas_e = prov.graph("leyenda", limit=SIN_TOPE)
    mostrados, relaciones, _ = vista_truncada(todos_n, todas_e, limit)
    return dict(
        limite=limit,
        nodos_autorizados=len(todos_n), relaciones_autorizadas=len(todas_e),
        nodos_entregados=len(mostrados), relaciones_entregadas=len(relaciones),
    )


@pytest.mark.parametrize("n_nodes,limit", [(50, 300), (500, 300), (2000, 300),
                                           (2000, 1), (2000, 2000)])
def test_las_seis_cifras_del_bloque_view_son_las_de_verdad(tmp_path, n_nodes, limit):
    """Regla 3 llevada al servidor: no basta con que el cliente no invente
    cifras; las que manda el servidor tienen que ser las que son.

    Los cinco casos incluyen `limit=1` (el recorte máximo) y `limit=2000` (sin
    recorte): así el valor de `limit` publicado no puede acertar por coincidir
    con el número de nodos ni con una constante del módulo.
    """
    path, _ = _fixture(tmp_path, n_nodes)
    payload = _respuesta(path, limit=limit)
    _exige_contadores_por_valor(payload["view"], **_cifras_reales(path, limit=limit))


def test_el_limite_publicado_es_el_PEDIDO_por_HTTP(tmp_path, lector_por_dependencia):
    """`view.limit` recorre la ruta real: parámetro de consulta -> router ->
    respuesta. Un valor fijo (el superviviente) acertaría a lo sumo en uno de
    los tres, así que se piden tres distintos y NINGUNO es el de por defecto.
    """
    lector_por_dependencia(app)
    path, _ = _fixture(tmp_path, 2000)
    app.dependency_overrides[get_filtered_provider] = lambda: PolicyFilteredProvider(
        MockGraphProvider(path), _viewer()
    )
    try:
        for pedido in (7, 123, 999):
            r = client.get("/api/graph",
                           params={"workspace": "leyenda", "limit": pedido})
            assert r.status_code == 200
            view = r.json()["view"]
            assert view["limit"] == pedido, (
                f"se pidió limit={pedido} y la vista declara {view['limit']!r}: "
                f"el metadato no describe ESTA vista")
            assert view["nodes_shown"] == pedido, (
                "y las cifras de al lado tampoco: el recorte no es el pedido")
    finally:
        app.dependency_overrides.pop(get_filtered_provider, None)


#: Falseo de CADA cifra CONSERVANDO SU CLAVE. No se borra nada: el bloque sigue
#: teniendo las seis claves, con los tipos correctos, y miente. Es la forma del
#: defecto que sobrevivía.
def _falsear(view: dict, clave: str) -> dict:
    falso = dict(view)
    if clave == "truncated":
        falso[clave] = not view[clave]
    else:
        # +1 no vale para todo: en `nodes_shown` produciría un número que ya no
        # cuadra con lo entregado y lo cazaría cualquier control. Se usa un
        # valor GRANDE y plausible, que es lo que escribiría alguien que
        # "arregla" el metadato: el 999999 del superviviente medido.
        falso[clave] = 999999
    assert set(falso) == set(view), "el falseo tiene que CONSERVAR las claves"
    assert falso[clave] != view[clave], f"el falseo de `{clave}` no muerde"
    return falso


@pytest.mark.parametrize("clave", sorted(CLAVES_DE_VISTA))
def test_calibracion_falsear_una_cifra_CONSERVANDO_la_clave_pone_ROJO(tmp_path, clave):
    """MUTACIÓN 9 (la que faltaba, una por clave): el bloque `view` conserva
    las seis claves y una de ellas MIENTE.

    Se exige además que el rojo sea SUYO: el mensaje tiene que nombrar la clave
    falseada. Sin esa comprobación, `nodes_total` podría estar cubierto sólo
    por el rojo prestado de `truncated` y nadie lo sabría.
    """
    path, _ = _fixture(tmp_path, 2000)
    cifras = _cifras_reales(path, limit=LIMIT)
    view = _respuesta(path, limit=LIMIT)["view"]
    _exige_contadores_por_valor(view, **cifras)  # verde antes

    with pytest.raises(AssertionError) as e:
        _exige_contadores_por_valor(_falsear(view, clave), **cifras)
    assert _QUEJA[clave] in str(e.value), (
        f"falsear `{clave}` puso rojo, pero la queja es de otra clave "
        f"({str(e.value)[:120]}): el rojo es PRESTADO y `{clave}` sigue sin control")


def test_calibracion_el_limite_mentiroso_pone_ROJO_en_el_control_general(tmp_path):
    """El superviviente exacto, en el control que lo dejaba pasar.

    `_exige_declaracion_de_parcialidad` es la función por la que pasan TODOS
    los casos de este fichero. Con `view["limit"] = 999999` —la mutación
    literal que se midió sobre `main=aaf9695`— tiene que ponerse roja.
    """
    path, _ = _fixture(tmp_path, 2000)
    payload = _respuesta(path, limit=LIMIT)
    _exige_declaracion_de_parcialidad(payload, truncada=True, limite=LIMIT)  # verde

    payload["view"]["limit"] = 999999
    with pytest.raises(AssertionError, match="view.limit"):
        _exige_declaracion_de_parcialidad(payload, truncada=True, limite=LIMIT)

    # Y un `limit` con el valor correcto pero del tipo equivocado tampoco pasa:
    # `"300" == 300` es falso en Python, pero sin la comprobación de tipo un
    # `limit` en cadena viajaría al cliente y la igualdad de arriba no diría
    # POR QUÉ.
    payload = _respuesta(path, limit=LIMIT)
    payload["view"]["limit"] = str(LIMIT)
    with pytest.raises(AssertionError, match="view.limit"):
        _exige_declaracion_de_parcialidad(payload, truncada=True, limite=LIMIT)


def test_el_control_del_limite_NO_es_opcional():
    """Ablación del propio control: que no se pueda apagar por omisión.

    Si `limite` tuviera valor por defecto, bastaría con dejar de pasarlo para
    volver al estado de `aaf9695` sin que nada se pusiera rojo. Se afirma sobre
    la FIRMA REAL (`inspect`), no sobre el texto del fichero.
    """
    import inspect

    firma = inspect.signature(_exige_declaracion_de_parcialidad)
    p = firma.parameters["limite"]
    assert p.default is inspect.Parameter.empty, (
        "`limite` tiene valor por defecto: la comprobación del VALOR de `limit` "
        "se apagaría con sólo omitir el argumento")
    assert p.kind is inspect.Parameter.KEYWORD_ONLY
