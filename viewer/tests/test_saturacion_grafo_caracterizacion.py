"""Caracterización del desplome cuadrático de relaciones en `/api/graph`.

Esto NO es un test de "funciona bien". Es un test de CARACTERIZACIÓN: fija el
defecto documentado en `docs/72-saturacion-del-grafo-diagnostico.md` para que
deje de estar sólo narrado en un documento y pase a estar **aseverado en CI**.

Motivo: los bancos de medida viven en `docs/measurements/72-saturacion-grafo/`
y **ningún job de CI los ejecuta**. Una refactorización futura podía mover,
mejorar o empeorar este comportamiento sin que se encendiera ninguna luz.

El defecto: `PolicyFilteredProvider.graph` recorta los nodos ANTES de recoger
las aristas (`filter_nodes(...)[:limit]`), así que devuelve el **subgrafo
inducido sobre los primeros `limit` nodos** y la retención de relaciones cae
con el CUADRADO de la fracción de nodos: ``p ~ (limit/N)^2``.

CALIBRACIÓN (aquí, no en prosa): además de fijar el comportamiento de hoy,
este módulo demuestra que la comprobación **sabe ponerse ROJA** en los dos
sentidos — si alguien arregla el truncado y si el desplome empeora—. Un
control que no puede fallar no defiende nada.

Este fichero vive en `viewer/tests/`, que está FUERA del hash de
`viewer/app/**` usado por `benchmarks/perf/calibracion.py`: no invalida la
calibración de rendimiento.
"""
from __future__ import annotations

import json
import random

import pytest

from app.authz.filtered_provider import _ALL, PolicyFilteredProvider
from app.policies.models import ViewerContext
from app.providers.mock_provider import MockGraphProvider

LIMIT = 300
GRADO_MEDIO = 3
SEMILLA = 7


def _viewer() -> ViewerContext:
    """Espectador REAL: `admin_full=False`.

    Con `admin_full=True` la política ni se evalúa (bypass total) y el test
    mediría otra cosa distinta de la que anuncia. Es la avería que este
    proyecto ya se ha hecho a sí mismo cuatro veces.

    No se pasa `session_public`: **el motor no lo lee** (`grep session_public
    app/policies/engine.py` → cero). Ponerlo sugeriría que contribuye a lo que
    aquí se mide, y no contribuye: la única dimensión de política que estas
    fixturas ejercen es `can_view_reference` (más el workspace).
    """
    return ViewerContext(
        role="reviewer",
        allowed_workspaces=frozenset({"leyenda"}),
        can_view_reference=True,
        can_view_lore=True,  # LORE-ANONIMO-DENEGADO: lector autenticado
        admin_full=False,
    )


def _fixture(tmp_path, n_nodes: int, *, alineado: bool = False):
    """Grafo sintético de grado medio 3, determinista.

    ``alineado=False``: aristas uniformes — peor caso, el orden de almacén no
    guarda relación con la topología.
    ``alineado=True``: comunidades de 100 entidades consecutivas y densamente
    interconectadas — el caso plausible de producción (entidades del mismo
    documento creadas seguidas).
    """
    rnd = random.Random(SEMILLA)
    n_edges = n_nodes * GRADO_MEDIO
    nodes = [
        {
            "id": f"n{i}", "entity_id": f"n{i}", "label": f"E{i}", "type": "Character",
            "visibility": "reference", "workspace": "leyenda", "scope": "juego",
            "knowledge_layer": "book", "review_status": "auto_extracted", "confidence": 0.9,
        }
        for i in range(n_nodes)
    ]
    edges = []
    for k in range(n_edges):
        if alineado:
            base = rnd.randrange(max(1, n_nodes // 100)) * 100
            ancho = min(100, n_nodes - base)
            a, b = base + rnd.randrange(ancho), base + rnd.randrange(ancho)
        else:
            a, b = rnd.randrange(n_nodes), rnd.randrange(n_nodes)
        if a == b:
            b = (b + 1) % n_nodes
        edges.append({
            "id": f"e{k}", "from": f"n{a}", "to": f"n{b}", "type": "RELATED_TO",
            "label": "rel", "visibility": "reference", "workspace": "leyenda",
            "scope": "juego", "review_status": "auto_extracted", "confidence": 0.8,
        })
    p = tmp_path / f"g{n_nodes}{'_alineado' if alineado else ''}.json"
    p.write_text(json.dumps({"workspace": "leyenda", "nodes": nodes, "edges": edges}),
                 encoding="utf-8")
    return p, n_edges


def _retencion(path, n_edges: int, *, limit: int = LIMIT, provider_cls=PolicyFilteredProvider):
    prov = provider_cls(MockGraphProvider(path), _viewer())
    nodes, edges = prov.graph("leyenda", limit=limit)
    return len(nodes), len(edges), len(edges) / n_edges


class _ProviderSinTruncado(PolicyFilteredProvider):
    """Ablación del defecto: el MISMO provider sin el `[:limit]` de nodos.

    Es "el mundo en el que alguien arregla el truncado". Vive aquí y no en
    `viewer/app/authz/**`, que este carril no modifica.
    """

    def graph(self, workspace, limit=300, entity_type=None, q=None):
        # `_ALL` importado de produccion, no un 10**7 a mano: si produccion
        # cambiara esa constante, una copia local haria divergir la ablacion
        # EN SILENCIO y dejaria de ablacionar lo que dice ablacionar.
        nodes, edges = self._base.graph(workspace, limit=_ALL,
                                        entity_type=entity_type, q=q)
        vnodes = self._policy.filter_nodes(nodes, self._ctx)  # <- sin [:limit]
        vids = {n["id"] for n in vnodes if "id" in n}
        return vnodes, self._policy.filter_edges(edges, vids, self._ctx)


# --- Banda de caracterización -------------------------------------------------
# Retención MEDIDA hoy (árbol e0305cc), aristas uniformes, limit=300:
#   n=500 -> 571/1500 = 38,1 %   n=1000 -> 318/3000 = 10,6 %
#   n=2000 -> 171/6000 = 2,85 %
# La banda es holgada a propósito: fija el ORDEN DE MAGNITUD del desplome, no
# una cifra exacta que se rompería con cualquier cambio de semilla.
BANDAS = {500: (0.25, 0.55), 1000: (0.06, 0.20), 2000: (0.015, 0.060)}


def _exige_desplome(n_nodes: int, retenido: float) -> None:
    """La comprobación calibrada. Roja por ARRIBA (alguien lo arregló: hay que
    borrar este test y celebrarlo) y roja por ABAJO (empeoró)."""
    bajo, alto = BANDAS[n_nodes]
    assert retenido >= bajo, (
        f"n={n_nodes}: la retención de relaciones EMPEORÓ ({retenido:.3%} < {bajo:.1%}). "
        f"El visor enseña aún menos grafo que cuando se caracterizó el defecto."
    )
    assert retenido <= alto, (
        f"n={n_nodes}: la retención SUBIÓ a {retenido:.3%} (> {alto:.1%}). "
        f"Si el truncado de nodos se ha corregido, este test de caracterización "
        f"ya no describe el sistema: bórralo y actualiza "
        f"docs/72-saturacion-del-grafo-diagnostico.md."
    )


@pytest.mark.parametrize("n_nodes", [500, 1000, 2000])
def test_la_retencion_de_relaciones_se_desploma_con_el_cuadrado(tmp_path, n_nodes):
    """Hoy `/api/graph` devuelve el subgrafo inducido sobre los primeros 300
    nodos, y por eso pierde relaciones cuadráticamente."""
    path, n_edges = _fixture(tmp_path, n_nodes)
    n_out, e_out, retenido = _retencion(path, n_edges)

    assert n_out == LIMIT, "los nodos sí topan limpiamente en el límite"
    _exige_desplome(n_nodes, retenido)

    # La ley: la retención medida acompaña a (limit/N)^2 dentro de un factor 2.
    predicho = (LIMIT / n_nodes) ** 2
    assert predicho / 2 <= retenido <= predicho * 2, (
        f"n={n_nodes}: retenido {retenido:.3%} se aparta de la ley cuadrática "
        f"{predicho:.3%}; la causa raíz documentada puede haber cambiado."
    )


def test_calibracion_el_control_se_pone_rojo_si_alguien_arregla_el_truncado(tmp_path):
    """Necesidad y suficiencia del `[:limit]`: quitándolo, la retención vuelve
    al 100 % y la comprobación de arriba TIENE que fallar."""
    for n_nodes in (500, 1000, 2000):
        path, n_edges = _fixture(tmp_path, n_nodes)
        _, _, retenido = _retencion(path, n_edges, provider_cls=_ProviderSinTruncado)

        assert retenido == 1.0, (
            f"sin el truncado de nodos no debe perderse NI UNA relación; "
            f"medido {retenido:.3%}"
        )
        with pytest.raises(AssertionError, match="la retención SUBIÓ"):
            _exige_desplome(n_nodes, retenido)


def test_calibracion_el_control_se_pone_rojo_si_el_desplome_empeora():
    """El otro sentido: una retención por debajo de la banda también es roja."""
    with pytest.raises(AssertionError, match="EMPEORÓ"):
        _exige_desplome(2000, 0.001)


def test_la_severidad_depende_de_la_alineacion_entre_orden_y_topologia(tmp_path):
    """El 2,85 % es el PEOR CASO, no una predicción de producción.

    Con la misma densidad real y el mismo límite, si las entidades del mismo
    documento se almacenan consecutivas y están densamente interconectadas
    —el caso plausible de producción— la densidad mostrada se conserva casi
    intacta y casi no quedan nodos sueltos. Lo que manda no es el orden ni la
    topología por separado, sino su ALINEACIÓN.
    """
    n_nodes = 2000
    uniforme, n_edges = _fixture(tmp_path, n_nodes)
    alineado, _ = _fixture(tmp_path, n_nodes, alineado=True)

    _, e_uni, ret_uni = _retencion(uniforme, n_edges)
    n_ali, e_ali, ret_ali = _retencion(alineado, n_edges)

    assert ret_ali > ret_uni * 3, (
        f"la alineación debe mejorar la retención de forma grande: "
        f"alineado {ret_ali:.2%} vs uniforme {ret_uni:.2%}"
    )
    # Bajo alineación la DENSIDAD mostrada se conserva (la real es 3,0)...
    assert e_ali / n_ali > 2.5, f"densidad alineada {e_ali / n_ali:.2f}, esperada ~3"
    # ...aunque la COBERTURA sigue siendo parcial: sigue siendo una vista
    # incompleta que hoy el visor no declara como tal.
    assert ret_ali < 0.35, (
        f"aun alineado, la vista sigue siendo parcial ({ret_ali:.2%}); si dejara "
        f"de serlo, la recomendación de declarar la parcialidad cambiaría"
    )
