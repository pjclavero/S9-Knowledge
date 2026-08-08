"""Regresiones del segundo dictamen NO CONFORME (G1, G2, G3).

Los tres son la MISMA familia que H1/H2/H3, que ya se creían cerrados:

  G1  un campo que el motor consume sin tipar -> excepcion, no denegacion
  G2  un camino que no pasa por el ambito del servidor -> fuga entre workspaces
  G3  un campo que el motor lee y la proyeccion no transporta -> barrera muda

Conviene subrayar por que hizo falta un segundo revisor: la red anti-reincidencia
del primer arreglo (`test_provider_authz_fields_contract.py`) mira el codigo de
`can_view` con una expresion regular, y `known_by_characters` se lee dentro de
`models.known_by_of`. La red no podia verlo. Un test que solo vigila un fichero
no cubre una regla que se movio a otro.
"""
from __future__ import annotations

import pytest

from app.policies.engine import VisibilityPolicy
from app.policies.models import ViewerContext

POLICY = VisibilityPolicy()


def _nodo(**extra):
    base = {
        "id": "n1",
        "workspace": "ws",
        "scope": "juego",
        "partida_id": None,
        "visibility": "player",
    }
    base.update(extra)
    return base


def _ctx(**extra):
    base = {
        "role": "viewer",
        "allowed_workspaces": frozenset({"ws"}),
        "max_visible_session": 5,
    }
    base.update(extra)
    return ViewerContext(**base)


# --- G1: dato malformado deniega, NUNCA revienta -----------------------------

# NOTA (T1/T2): las pruebas de `session_index` y `party` que estaban aqui se
# retiraron al cambiar la semantica, no por comodidad. `party` dejo de ser
# vocabulario autoritativo (T1) y `session_index` fue sustituido por
# `known_from_session` (T2); su cobertura vive ahora en
# `test_t1_party_t2_revelacion.py`. Se conserva la propiedad que de verdad
# importaba de G1: un dato malformado no puede tumbar el conjunto entero.

def test_un_nodo_corrupto_no_tumba_el_listado_entero():
    nodos = [
        _nodo(id="sano"),
        _nodo(id="malo", known_from_session="tres"),
        _nodo(id="sano2"),
    ]
    visibles = POLICY.filter_nodes(nodos, _ctx())
    assert [n["id"] for n in visibles] == ["sano", "sano2"]


# --- G3: todo campo que el motor lee debe viajar en la proyeccion ------------

def test_known_by_characters_viaja_en_la_proyeccion_del_proveedor():
    """`ingest_rpg` escribe `known_by_characters` en nodos `:Entity` reales.

    El motor lo lee como respaldo de `known_by`. Si el serializador no lo
    transporta, la concesion de conocimiento se pierde y --peor-- un valor
    corrupto deja de denegar: la barrera queda apagada en silencio, que es
    exactamente H1.
    """
    from app.providers.neo4j_provider import _node_to_dict, _rel_to_dict
    from tests.test_provider_authz_fields_contract import (
        CAMPOS_AUTORIZACION_NODO,
        _NodoFalso,
        _RelacionFalsa,
    )

    assert "known_by_characters" in CAMPOS_AUTORIZACION_NODO
    assert "known_by_characters" in _node_to_dict(_NodoFalso({}))
    assert "known_by_characters" in _rel_to_dict(_RelacionFalsa({}))


def test_known_by_characters_corrupto_deniega_igual_que_known_by():
    d = POLICY.can_view(_nodo(known_by_characters="PJ01"), _ctx())
    assert not d.visible and d.reason == "known_by_invalid"


def test_known_by_characters_concede_conocimiento():
    ctx = _ctx(active_character="pc:ana", can_view_secret=False)
    nodo = _nodo(visibility="secret", known_by_characters=["pc:ana"])
    assert POLICY.can_view(nodo, ctx).visible


# --- G2: /reviews decide con el ambito del SERVIDOR --------------------------

@pytest.mark.parametrize(
    "malicioso",
    ["../../secretos", "..", ".", "/etc", "ws/../..", "a" * 65, "ws\x00", ""],
)
def test_reviews_dir_no_sale_del_arbol_de_revisiones(malicioso):
    """`workspace` llegaba crudo a la ruta: `../../secretos` enumeraba
    directorios arbitrarios del servidor."""
    from fastapi import HTTPException

    from app.main import _reviews_dir

    with pytest.raises(HTTPException) as exc:
        _reviews_dir(malicioso)
    assert exc.value.status_code == 404


def test_reviews_dir_confina_incluso_lo_que_pasa_el_patron():
    """Doble defensa: la ruta resuelta debe caer bajo la raiz de revisiones."""
    from app.main import _reviews_dir, _reviews_root

    destino = _reviews_dir("leyenda")
    assert _reviews_root() in destino.parents


def test_reviews_no_acepta_un_workspace_fuera_del_ambito(monkeypatch):
    """La fuga: un `reviewer` de A veia la cola de B cambiando la URL.

    El material de revision es anterior a la visibilidad y al ambito --son
    entidades y descripciones en crudo, todavia sin etiquetar--, asi que la
    unica barrera posible es esta. Responde 404 y no 403: un 403 confirmaria
    que el workspace ajeno existe.
    """
    from fastapi import HTTPException

    import app.main as main_module
    from app.authz.scope import VisibilityScope

    ajeno = VisibilityScope(ViewerContext(
        role="reviewer", allowed_workspaces=frozenset({"propio"})
    ))
    monkeypatch.setattr(main_module, "get_visibility_scope", lambda _r: ajeno)

    assert main_module._reviews_workspace(None, "propio") == "propio"
    with pytest.raises(HTTPException) as exc:
        main_module._reviews_workspace(None, "ajeno")
    assert exc.value.status_code == 404


def test_reviews_admin_conserva_acceso(monkeypatch):
    import app.main as main_module
    from app.authz.scope import VisibilityScope

    scope = VisibilityScope(ViewerContext(role="admin", admin_full=True))
    monkeypatch.setattr(main_module, "get_visibility_scope", lambda _r: scope)
    assert main_module._reviews_workspace(None, "cualquiera") == "cualquiera"
