"""M5b-2 -- visibilidad ausente, vacia, desconocida o invalida -> DENY.

Requisito del operador, literal: debe probarse por las DOS vias, atravesando el
adaptador e invocando el motor directamente. No es redundancia: el adaptador
podria estar tapando un motor permisivo, y un motor correcto no sirve si el
adaptador lo esquiva. Solo probando ambas se sabe cual de las dos protege.
"""
import pytest

from app.authz.visibility_contract import V3VisibilityPolicyAdapter
from app.policies.engine import POLICY
from app.policies.models import DENY, NARRATOR, PLAYER, REFERENCE, SECRET, ViewerContext

WS = "ws:test"

#: Todo lo que NO es un nivel valido. Cada uno por un motivo distinto.
INVALIDOS = [
    pytest.param({}, id="ausente"),
    pytest.param({"visibility": None}, id="nula"),
    pytest.param({"visibility": ""}, id="vacia"),
    pytest.param({"visibility": "   "}, id="solo_espacios"),
    pytest.param({"visibility": "publico"}, id="nivel_inexistente"),
    pytest.param({"visibility": "PLAYER;--"}, id="con_basura"),
    pytest.param({"visibility": "omniscient"}, id="nivel_futuro_desconocido"),
    pytest.param({"visibility": 1}, id="entero"),
    pytest.param({"visibility": True}, id="booleano"),
    pytest.param({"visibility": ["player"]}, id="lista"),
    pytest.param({"visibility": {"level": "player"}}, id="diccionario"),
]


def ctx(**kw):
    base = dict(
        role="player",
        allowed_workspaces=(WS,),
        can_view_secret=True,
        can_view_reference=True,
        can_view_future=True,
    )
    base.update(kw)
    return ViewerContext(**base)


# --- via 1: el motor, invocado directamente --------------------------------
@pytest.mark.parametrize("nodo", INVALIDOS)
def test_motor_directo_deniega_toda_visibilidad_invalida(nodo):
    d = POLICY.can_view({"workspace": WS, "scope": "juego", **nodo}, ctx())
    assert not d.visible
    assert d.reason == "visibility_invalid"


@pytest.mark.parametrize("nodo", INVALIDOS)
def test_motor_directo_deniega_aunque_sea_administrador(nodo):
    """Un bypass salta reglas de permiso; no convierte un dato invalido en valido."""
    d = POLICY.can_view({"workspace": WS, "scope": "juego", **nodo}, ctx(role="admin", admin_full=True))
    assert not d.visible


@pytest.mark.parametrize("nodo", INVALIDOS)
def test_motor_directo_deniega_aunque_el_personaje_lo_conozca(nodo):
    """Conocer un hecho no arregla que su nivel sea ilegible."""
    d = POLICY.can_view(
        {"workspace": WS, "scope": "juego", "id": "n1", "known_by": ["char:a"], **nodo},
        ctx(active_character="char:a", character_knowledge=("n1",)),
    )
    assert not d.visible


def test_deny_es_terminal_tambien_para_administrador():
    d = POLICY.can_view({"workspace": WS, "scope": "juego", "visibility": DENY}, ctx(role="admin", admin_full=True))
    assert not d.visible
    assert d.reason == "deny_absolute"


# --- via 2: a traves del adaptador -----------------------------------------
@pytest.mark.parametrize("nodo", INVALIDOS)
def test_adaptador_deniega_toda_visibilidad_invalida(nodo):
    adaptador = V3VisibilityPolicyAdapter()
    d = adaptador.policy.can_view({"workspace": WS, "scope": "juego", **nodo}, ctx())
    assert not d.visible


# --- control positivo: esto no pasa por vacuidad ---------------------------
@pytest.mark.parametrize("nivel", [PLAYER, NARRATOR, SECRET, REFERENCE])
def test_los_niveles_validos_siguen_siendo_visibles(nivel):
    """Sin esto, un motor que denegara SIEMPRE pasaria todas las pruebas de arriba."""
    d = POLICY.can_view({"workspace": WS, "scope": "juego", "visibility": nivel}, ctx())
    assert d.visible, d.reason


def test_el_espacio_sobrante_no_invalida_un_nivel_legitimo():
    """Se normaliza, no se rechaza: un dato con espacios es legible sin adivinar."""
    assert POLICY.can_view({"workspace": WS, "scope": "juego", "visibility": " Player "}, ctx()).visible
