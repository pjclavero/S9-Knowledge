"""T1 (party deja de ser ACL) y T2 (sesion de revelacion cableada).

Las dos decisiones que el tercer dictamen dejo abiertas, porque no eran
arreglos sino semantica de producto:

T1  `party` + `party_membership` era una ACL dinamica: pertenecer al grupo daba
    acceso automatico a todo lo que el grupo hubiera conocido alguna vez. En una
    campana eso es falso -- quien se incorpora en la sesion 20 no conoce el
    secreto que el grupo descubrio en la 3. La party pasa a ser fuente de
    CONCESION (evento -> miembros presentes -> grants -> `known_by`), no una
    frontera evaluada en cada peticion.

T2  La proteccion frente a spoilers si es un requisito central del producto, y
    se cablea de extremo a extremo. Pero sobre `known_from_session` ("desde que
    sesion puede revelarse"), no sobre `session_index` ("a que episodio
    pertenece"): si en la sesion 12 se descubre un asesinato de hace cinco anos,
    la barrera es 12, no la cronologia del hecho.
"""
from __future__ import annotations

import pytest

from app.policies.engine import VisibilityPolicy
from app.policies.models import ViewerContext

POLICY = VisibilityPolicy()


def _nodo(**extra):
    base = {"id": "n1", "workspace": "ws", "scope": "juego",
            "partida_id": None, "visibility": "player"}
    base.update(extra)
    return base


def _jugador(**extra):
    base = {"role": "viewer", "allowed_workspaces": frozenset({"ws"}),
            "max_visible_session": 5,
            # LORE-ANONIMO-DENEGADO: un jugador AUTENTICADO si tiene la llave de
            # la capa juego. Sin ella, estos casos medirian la barrera nueva en
            # vez de la revelacion, y se pondrian rojos por el motivo equivocado.
            "can_view_lore": True}
    base.update(extra)
    return ViewerContext(**base)


# --- T1: pertenecer a una party NO concede nada -------------------------------

def test_pertenecer_a_la_party_no_concede_acceso_por_si_solo():
    """La propiedad central de T1.

    Antes: `party in ctx.party_membership` -> visible. Ahora la pertenencia no
    entra en la decision; el acceso vendra de un grant individual materializado
    en `known_by`.
    """
    nodo = _nodo(visibility="secret", party="los_cuervos")
    ctx = _jugador(party_membership=frozenset({"los_cuervos"}))
    d = POLICY.can_view(nodo, ctx)
    assert not d.visible
    assert d.reason == "secret_not_allowed"


def test_el_secreto_del_grupo_no_se_hereda_al_incorporarse():
    """El caso que motivo la decision: un PJ que entra en la sesion 20 no
    conoce el secreto que el grupo descubrio en la 3."""
    nodo = _nodo(visibility="secret", party="los_cuervos", known_from_session=3,
                 known_by=["pc:veterano"])
    recien_llegado = _jugador(
        active_character="pc:novato",
        party_membership=frozenset({"los_cuervos"}),
        max_visible_session=25,
    )
    assert not POLICY.can_view(nodo, recien_llegado).visible


def test_is_public_ya_no_abre_contenido():
    nodo = _nodo(visibility="secret", party="los_cuervos", is_public=True)
    ctx = _jugador(session_public=True, party_membership=frozenset())
    assert not POLICY.can_view(nodo, ctx).visible


def test_party_malformada_ya_no_importa_porque_no_decide():
    """Al no ser vocabulario autoritativo, su forma deja de ser una via de
    error: no deniega por invalida ni revienta."""
    nodo = _nodo(party=["ya", "no", "decide"])
    assert POLICY.can_view(nodo, _jugador()).visible


# --- T2: sesion de revelacion --------------------------------------------------

@pytest.mark.parametrize(
    "desde,tope,visible",
    [
        (3, 5, True),    # revelado antes del punto de la campana
        (8, 5, False),   # aun no revelado: spoiler
        (5, 5, True),    # el limite es inclusivo
        (0, 0, True),    # 0 es declaracion positiva: conocido desde el inicio
        (0, 5, True),
    ],
)
def test_known_from_session_frente_al_tope(desde, tope, visible):
    d = POLICY.can_view(_nodo(known_from_session=desde), _jugador(max_visible_session=tope))
    assert d.visible is visible
    if not visible:
        assert d.reason == "future_session"


def test_known_by_NO_salta_la_barrera_historica():
    """El corazon de T2, y una correccion sobre el motor anterior.

    `known_by` es la proyeccion del estado ACTUAL de conocimiento: dice que el
    PJ lo sabe, no desde cuando. Si bastara para saltarse el tope, pedir "ver
    como PJ hasta la sesion 5" revelaria lo que ese mismo PJ descubrio en la 12
    -- un spoiler producido por la funcion que existe para evitarlo.
    """
    nodo = _nodo(known_from_session=12, known_by=["pc:ana"])
    ctx = _jugador(active_character="pc:ana", max_visible_session=5)
    d = POLICY.can_view(nodo, ctx)
    assert not d.visible
    assert d.reason == "future_session"


def test_can_view_future_si_puede_saltarla():
    """Explicito y solo para quien lo tiene concedido (narrador/admin)."""
    nodo = _nodo(known_from_session=12)
    ctx = _jugador(max_visible_session=5, can_view_future=True)
    assert POLICY.can_view(nodo, ctx).visible


def test_sin_tope_LEGIBLE_no_se_aplica_ninguna_barrera__ya_no():
    """7a ronda: la INVERSA de lo que este test afirmaba antes.

    Decia: "`max_visible_session=None` = sin progresion, luego visible". Es la
    tercera encarnacion del mismo defecto: `None` significaba a la vez "no
    aplica", "la concesion no declara tope" y "no se pudo leer la concesion", y
    el motor las trataba a las tres como permiso maximo. Un tope ilegible no
    puede abrir nada.
    """
    d = POLICY.can_view(_nodo(known_from_session=99), _jugador(max_visible_session=None))
    assert not d.visible
    assert d.reason == "session_cap_missing"


def test_el_tope_NO_APLICABLE_tampoco_abre():
    """El estado declarado (sin partida activa) deniega el dato que SI declara
    sesion de revelacion: menos contexto nunca puede dar mas acceso (H6-9)."""
    from app.policies.models import NO_APLICA

    d = POLICY.can_view(_nodo(known_from_session=99), _jugador(max_visible_session=NO_APLICA))
    assert not d.visible
    assert d.reason == "session_cap_not_applicable"


@pytest.mark.parametrize("tope", ["cinco", -1, 3.5, True, [], {}])
def test_un_tope_corrupto_deniega_en_vez_de_abrir(tope):
    d = POLICY.can_view(_nodo(known_from_session=1), _jugador(max_visible_session=tope))
    assert not d.visible
    assert d.reason == "session_cap_missing"


def test_contenido_de_partida_SIN_sesion_de_revelacion_deniega():
    """H6-1, el peor de los tres criticos del sexto dictamen.

    `if desde is not None:` hacia que un nodo `scope=partida` sin
    `known_from_session` se saltara la regla ENTERA y fuera visible con
    cualquier tope, mientras el registro y docs/58 declaraban `missing=DENY`.
    El unico guardian era un `raise` del writer -- que solo cubre lo que
    escribe el writer -- y no tenia ninguna prueba.
    """
    nodo = _nodo(scope="partida", partida_id="partida:uno")
    nodo.pop("known_from_session", None)
    ctx = _jugador(allowed_partida_ids=frozenset({"partida:uno"}), max_visible_session=99)
    d = POLICY.can_view(nodo, ctx)
    assert not d.visible
    assert d.reason == "known_from_session_missing"


@pytest.mark.parametrize("valor", ["tres", -1, [], {}, 3.5, True])
def test_known_from_session_malformada_deniega_sin_reventar(valor):
    d = POLICY.can_view(_nodo(known_from_session=valor), _jugador())
    assert not d.visible
    assert d.reason == "known_from_session_invalid"


def test_session_index_ya_no_decide_nada():
    """No se mantiene como alias silencioso: el motor lo ignora."""
    assert POLICY.can_view(_nodo(session_index=99), _jugador(max_visible_session=5)).visible


def test_la_barrera_se_aplica_tambien_en_conjuntos():
    """Listados, conteos y grafo comparten `filter_nodes`, asi que probar el
    conjunto cubre lista, detalle, busqueda, conteos y grafo a la vez."""
    nodos = [_nodo(id="a", known_from_session=1), _nodo(id="b", known_from_session=9)]
    visibles = POLICY.filter_nodes(nodos, _jugador(max_visible_session=5))
    assert [n["id"] for n in visibles] == ["a"]


def test_las_relaciones_pasan_por_la_misma_regla():
    arista = _nodo(id="r1", known_from_session=9)
    assert not POLICY.can_view(arista, _jugador(max_visible_session=5)).visible
