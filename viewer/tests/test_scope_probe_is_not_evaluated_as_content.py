"""REGRESION M5b-2: una SONDA DE AMBITO no es CONTENIDO. No unificar ambas cosas.

Historia, para quien lea esto dentro de seis meses y crea que sobra:

`VisibilityScope` no pregunta "¿puede verse este dato?" sino "¿cae este registro
dentro de mi ambito?". Para eso CONSTRUIA un nodo sintetico que solo llevaba
`workspace` y `partida_id` y lo pasaba por el mismo motor que evalua contenido.
Cuando M5b-2 cerro el defecto permisivo --todo nodo debe declarar una
`visibility` valida-- esa sonda dejo de tener nivel y el motor la denego. No fue
una regresion de datos: fueron 78 de 79 fallos, y dejaba INALCANZABLE la cola de
revision entera.

La correccion de M5b-2 fue que la sonda declarase su naturaleza
(`_PROBE_VISIBILITY = player`), NO relajar el motor. M5c va un paso mas alla y
elimina el objeto: la pregunta de ambito tiene ahora su propia via
(`POLICY.partida_in_scope`) y ya no se fabrica ningun nodo sintetico.

Este fichero fija la frontera probando LAS DOS MITADES A LA VEZ, que es justo lo
que un arreglo apresurado rompe: casi siempre se "arregla" una reabriendo la
otra.

    mitad A: la sonda decide ambito           -> no puede denegarse a si misma
    mitad B: el contenido sin visibility      -> sigue fallando cerrado

Si manana alguien vuelve a pasar un objeto sintetico al evaluador de contenido,
o afloja el motor para que pase, uno de los dos bloques se pone rojo.
"""
import inspect

import pytest

from app.authz.scope import VisibilityScope
from app.policies.engine import POLICY
from app.policies.models import ViewerContext

WS = "ws:test"
OTRO_WS = "ws:ajeno"
PARTIDA = "partida:viajando-por-el-imperio"
OTRA_PARTIDA = "partida:snowsaga"


def scope(**kw):
    base = dict(
        role="player",
        allowed_workspaces=frozenset({WS}),
        active_partida=PARTIDA,
        allowed_partida_ids=frozenset({PARTIDA}),
    )
    base.update(kw)
    # LORE-ANONIMO-DENEGADO: un registro SIN partida es capa juego, y la capa
    # juego pide llave. El sujeto de esta sonda es un lector legitimo, asi que
    # la tiene; lo que aqui se mide es que la sonda no se evalue como CONTENIDO,
    # no la barrera nueva.
    base.setdefault("can_view_lore", True)
    return VisibilityScope(ViewerContext(**base))


# --- mitad A: la sonda de ambito sigue pudiendo decidir ---------------------
def test_scope_probe_is_not_evaluated_as_content__la_sonda_decide_su_ambito():
    """Sin esto, el cierre de M5b-2 vacia la cola de revision entera."""
    s = scope()
    assert s.allows_partida(PARTIDA), "la partida activa debe caer en ambito"
    assert s.allows({"partida_id": PARTIDA, "workspace": WS})


def test_scope_probe_is_not_evaluated_as_content__capa_juego_sin_partida():
    """Un registro sin partida es capa juego compartida: visible, no denegado."""
    assert scope().allows({"workspace": WS})


def test_scope_probe_is_not_evaluated_as_content__el_ambito_sigue_aislando():
    """La sonda no puede pasar SIEMPRE: seguiria siendo un agujero, no un arreglo."""
    s = scope()
    assert not s.allows_partida(OTRA_PARTIDA)
    assert not s.allows({"partida_id": OTRA_PARTIDA, "workspace": WS})
    assert not s.allows({"workspace": OTRO_WS})


def test_scope_probe_is_not_evaluated_as_content__ya_no_existe_nodo_sintetico():
    """M5c va mas lejos que el arreglo original y elimina la sonda como objeto.

    Antes, la pregunta de ambito se respondia fabricando un nodo sintetico con
    una visibilidad de conveniencia (`_PROBE_VISIBILITY = player`) y pasandolo
    por el evaluador de CONTENIDO. Funcionaba y no era explotable --el valor se
    escribia el ultimo, asi que nadie podia autodeclararse sonda-- pero mantenia
    viva la confusion que causo los 78 fallos: un no-contenido recorriendo el
    camino del contenido.

    Ahora la pregunta de ambito tiene su propia via (`POLICY.partida_in_scope`).
    La propiedad que se fija aqui es mas fuerte que la anterior: no es que la
    sonda declare bien su naturaleza, es que **ya no hay sonda que declarar**.
    """
    assert not hasattr(VisibilityScope, "_PROBE_VISIBILITY")
    fuente = inspect.getsource(VisibilityScope.allows)
    assert "visibility" not in fuente, (
        "allows() ha vuelto a construir un nodo con visibilidad: la pregunta de "
        "ambito y la de contenido se estan mezclando otra vez"
    )


# --- mitad B: el contenido real NO se relaja por lo anterior ----------------
@pytest.mark.parametrize(
    "nodo",
    [
        pytest.param({}, id="sin_visibility"),
        pytest.param({"visibility": None}, id="nula"),
        pytest.param({"visibility": ""}, id="vacia"),
        pytest.param({"visibility": "publico"}, id="desconocida"),
    ],
)
def test_scope_probe_is_not_evaluated_as_content__el_contenido_sigue_cerrado(nodo):
    """El arreglo de la sonda NO debe haber reabierto el defecto permisivo."""
    ctx = ViewerContext(
        role="player",
        allowed_workspaces=frozenset({WS}),
        active_partida=PARTIDA,
        allowed_partida_ids=frozenset({PARTIDA}),
    )
    d = POLICY.can_view({"workspace": WS, "partida_id": PARTIDA, **nodo}, ctx)
    assert not d.visible
    assert d.reason == "visibility_invalid"


def test_scope_probe_is_not_evaluated_as_content__ambas_mitades_a_la_vez():
    """El invariante completo en una sola asercion, por si se separan los tests."""
    s = scope()
    ctx = s.ctx
    en_ambito = s.allows({"partida_id": PARTIDA, "workspace": WS})
    contenido_mudo = POLICY.can_view({"workspace": WS, "partida_id": PARTIDA}, ctx).visible
    assert en_ambito and not contenido_mudo
