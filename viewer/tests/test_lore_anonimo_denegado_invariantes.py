"""Las TRES garantias que se afirmaban y no estaban fijadas por ninguna prueba.

Salieron de una auditoria independiente, y las tres tienen la misma forma: una
afirmacion cierta en el codigo de hoy que **ninguna prueba podia poner roja**.
Nada de esto era explotable — se dice con precision en cada apartado — pero
"no explotable hoy" y "protegido" no son lo mismo, y la diferencia es
exactamente lo que este repositorio lleva siete rondas persiguiendo:

    la barrera existe -> se prueba otra cosa parecida -> queda verde
      -> alguien la mueve -> nada enrojece

Las tres se calibraron con su mutacion (VERDE -> ROJO -> VERDE, reversion por
hash). Ver `docs/81 §5 bis`.
"""
from __future__ import annotations

import pytest

from app.authz.context import build_viewer_context
from app.authz.scope import VisibilityScope
from app.policies.engine import POLICY
from app.policies.models import ViewerContext

WS = "ws:inv"
P = "partida:alfa"
PJ = "pc:ana"


# ===========================================================================
# 1. El DEFECTO del campo es no conceder
# ===========================================================================

def test_el_defecto_del_campo_es_no_conceder():
    """`can_view_lore` por defecto es False, y eso se comprueba SOBRE EL CAMPO.

    El registro M5b declara `missing=MINIMO` / `malformed=MINIMO` y el argumento
    escrito es: «una dimension booleana de CONCESION no puede fallar abierta si
    su valor por defecto es no conceder». Esa frase se repite en el registro, en
    `models.py` y en `docs/81`, y **nada la protegia**: invertir el defecto del
    dataclass a `True` dejaba las 1539 pruebas en verde.

    La `prueba_negativa` declarada mide MONOTONIA --que un contexto con
    `can_view_lore=False` no vea mas que uno con la concesion completa-- y esa
    es OTRA propiedad: se satisface igual de bien con cualquier defecto, porque
    pasa el valor explicitamente.

    No era explotable, y conviene decir por que: el productor unico
    (`build_viewer_context`) fija el valor en sus CUATRO ramas, asi que ningun
    contexto de produccion depende del defecto. Pero el defecto y esas lineas
    explicitas son **mutuamente redundantes**, y ninguno de los dos estaba
    probado por separado: quitar la linea explicita del anonimo tambien dejaba
    cero rojas. Aqui se fija el defecto; la linea explicita la fija la mutacion
    M4 de la calibracion.
    """
    assert ViewerContext().can_view_lore is False, (
        "el DEFECTO de `can_view_lore` concede. Una dimension booleana de "
        "concesion solo es fail-closed si su defecto es no conceder, y ese es "
        "el argumento con el que esta declarada `missing=MINIMO` en el registro"
    )


def test_el_defecto_de_TODA_dimension_booleana_de_concesion_es_no_conceder():
    """Generalizacion, para que la proxima no nazca desprotegida.

    No se enumera a mano: se leen del propio dataclass todas las dimensiones
    booleanas cuyo nombre las declara como CONCESION (`can_view_*`,
    `admin_full`, `session_public`) y se exige que ninguna conceda por defecto.
    Si alguien anade `can_view_lo_que_sea` con defecto `True`, esto se pone
    rojo el dia que se anade, no tres rondas despues.
    """
    vacio = ViewerContext()
    concesiones = [
        c for c in vars(vacio)
        if isinstance(getattr(vacio, c), bool)
        and (c.startswith("can_view_") or c in {"admin_full", "session_public"})
    ]
    # El arnes no puede pasar con cero casos.
    assert len(concesiones) >= 4, f"no se han encontrado dimensiones: {concesiones}"
    assert "can_view_lore" in concesiones

    conceden = [c for c in concesiones
                if getattr(vacio, c) is True and c != "session_public"]
    assert conceden == [], (
        f"{conceden} conceden por defecto. `session_public` esta excluida a "
        f"proposito y con su motivo: el motor NO la lee (cero apariciones en "
        f"`policies/engine.py`), asi que no es una llave de nada"
    )


# ===========================================================================
# 2. La barrera de la capa juego es de AMBITO: `known_by` no la salta
# ===========================================================================

def _ctx_con_personaje(**over) -> ViewerContext:
    base = dict(
        role="viewer",
        allowed_workspaces=frozenset({WS}),
        active_character=PJ,
        max_visible_session=10,
        can_view_lore=False,   # el sujeto: NO tiene la llave de la capa juego
    )
    base.update(over)
    return ViewerContext(**base)


#: Las DOS vias de conocimiento de personaje. Se prueban las dos porque son dos
#: campos distintos con dos escritores distintos (`known_by` del writer V3 y
#: `known_by_characters` de `ingest_rpg`), y G3 fue exactamente que una viajaba
#: y la otra no.
VIAS_DE_CONOCIMIENTO = [
    pytest.param({"known_by": [PJ]}, id="known_by"),
    pytest.param({"known_by_characters": [PJ]}, id="known_by_characters"),
    pytest.param({}, id="character_knowledge (por id precomputado)"),
]


@pytest.mark.parametrize("concesion", VIAS_DE_CONOCIMIENTO)
def test_el_conocimiento_de_personaje_NO_salta_la_barrera_de_capa_juego(concesion):
    """`can_view_lore` es de AMBITO, no de NIVEL, y esa distincion es la regla.

    El conocimiento de personaje salta la regla 3 (nivel de visibilidad): el PJ
    ya lo vivio. Lo que NUNCA salta es el AMBITO --workspace, partida-- y la
    capa juego es ambito, no nivel. Por eso 2b-bis esta colocada ANTES de
    `ctx.knows` y FUERA del `if not knows`.

    Estaba bien en el codigo y **nada lo fijaba**: mover la comprobacion dentro
    del bloque `if not knows` dejaba las 1539 pruebas en verde.

    No era explotable por un anonimo --`ctx.knows` exige un `active_character`
    LEGIBLE y el anonimo no tiene ninguno-- asi que lo que se perdia era
    defensa en profundidad, no una puerta abierta. Pero es justo la clase de
    afirmacion que este registro obliga a demostrar: `known_by` es un campo de
    concesion, y si un dia concediera ambito ademas de nivel, la decision del
    operador quedaria rota por un camino que nadie mira.
    """
    ctx = _ctx_con_personaje()
    nodo = {"id": "lore", "workspace": WS, "scope": "juego", "visibility": "player"}
    nodo.update(concesion)
    if not concesion:  # la via de `character_knowledge`
        ctx = _ctx_con_personaje(character_knowledge=frozenset({"lore"}))

    # Contraveneno: el conocimiento tiene que estar CONCEDIDO de verdad, o esta
    # prueba pasaria por no haber concedido nada.
    assert ctx.knows(nodo) is True, (
        "el conocimiento de personaje no se ha concedido: sin eso, 'no salta la "
        "barrera' se cumpliria por vacio"
    )

    d = POLICY.can_view(nodo, ctx)
    assert not d.visible, (
        "el conocimiento de personaje ha saltado la barrera de la capa juego. "
        "Es una barrera de AMBITO: `known_by` salta el NIVEL, nunca el ambito"
    )
    assert d.reason == "lore_not_allowed", (
        f"deniega, pero por otro motivo ({d.reason}): un rojo por el motivo "
        f"equivocado no demuestra esta barrera"
    )


def test_pero_el_conocimiento_SI_salta_el_NIVEL_cuando_hay_llave():
    """Contrapeso obligatorio del test de arriba.

    Si `known_by` no concediera nada nunca, «no salta el ambito» seria cierto
    por inutilidad. Con la llave de la capa juego puesta, el MISMO conocimiento
    SI abre un nodo `secret` que de otro modo estaria cerrado.
    """
    ctx = _ctx_con_personaje(can_view_lore=True)
    nodo = {"id": "s", "workspace": WS, "scope": "juego", "visibility": "secret",
            "known_by": [PJ]}
    assert POLICY.can_view(nodo, ctx).visible, (
        "el conocimiento de personaje no abre el nivel `secret`: entonces la "
        "prueba de arriba no estaba midiendo una barrera, medía un `known_by` "
        "inerte"
    )
    sin_conocer = {**nodo, "known_by": ["pc:otro"]}
    assert not POLICY.can_view(sin_conocer, ctx).visible


# ===========================================================================
# 3. La SEGUNDA PUERTA, en su direccion LEGITIMA
# ===========================================================================
#
# `partida_in_scope(None, ctx)` acota el corpus que no vive en el grafo:
# propuestas V3, contratos de revision y cola de trabajos, todos via
# `VisibilityScope.partida_only()`. La calibracion de M3 solo tenia rojas de la
# direccion ANONIMA --que un anonimo no reciba-- y nada cubria la contraria:
# que un lector CON derecho siga recibiendo el material sin `partida_id`.
#
# Sin esta mitad, la segunda puerta se podria "arreglar" devolviendo siempre
# False, y ninguna prueba lo notaria.

def _scope(role, auth=True) -> VisibilityScope:
    """Ambito por el PRODUCTOR unico, no fabricado a mano."""
    return VisibilityScope(build_viewer_context(
        role=role, auth_enabled=auth, default_workspace=WS,
    )).partida_only()


#: Un registro por familia real del corpus fuera del grafo, con la forma en que
#: cada una declara (o no declara) su partida. Las rutas de `partida_id` son las
#: que lee `authz/scope.py`.
SIN_PARTIDA = [
    pytest.param({"proposal_id": "p1"}, id="propuesta V3 sin partida"),
    pytest.param({"source_id": "src_1", "metadata": {}}, id="contrato v1 sin partida"),
    pytest.param({"id": "job-1", "type": "echo"}, id="trabajo de la cola"),
    pytest.param({"id": "x", "scope": {}}, id="scope sin partida_id"),
]


@pytest.mark.parametrize("registro", SIN_PARTIDA)
def test_un_lector_legitimo_SI_recibe_el_material_sin_partida(registro):
    """DIRECCION LEGITIMA de la segunda puerta: el que tiene derecho, recibe.

    Es la mitad que faltaba. `partida_in_scope` devuelve `ctx.can_view_lore`
    cuando el registro no declara partida; si alguien lo cambiara por `False`
    --ocultar de mas, el fallo que mas facilmente se confunde con seguridad--
    la consola de revision, el glosario V3 y la cola de trabajos se quedarian
    vacios para TODO EL MUNDO, y hasta ahora nada lo habria dicho.
    """
    for rol in ("viewer", "reviewer", "admin"):
        assert _scope(rol).allows(registro), (
            f"un {rol} autenticado NO recibe un registro sin partida: la "
            f"denegacion al anonimo se ha llevado por delante al legitimo"
        )


@pytest.mark.parametrize("registro", SIN_PARTIDA)
def test_y_el_anonimo_NO_lo_recibe(registro):
    """La otra direccion, sobre los MISMOS registros. Las dos, o ninguna dice nada."""
    assert not _scope(None, auth=False).allows(registro), (
        "el anonimo recibe material sin partida: la ausencia de partida ha "
        "vuelto a conceder visibilidad"
    )


def test_la_segunda_puerta_no_abre_la_partida_ajena_a_nadie():
    """Y no se ha abierto nada de paso: con partida ajena sigue cerrado.

    Contraveneno de los dos de arriba: si `allows` devolviera True para todo,
    el primero pasaria y el segundo no — pero conviene fijar tambien que la
    barrera de partida, que es la que este `scope` existe para aplicar, sigue
    puesta para un lector legitimo SIN esa partida.
    """
    ajeno = {"proposal_id": "p2", "partida_id": "partida:otra"}
    for rol in ("viewer", "reviewer"):
        assert not _scope(rol).allows(ajeno), (
            f"un {rol} sin esa partida activa recibe material de partida ajena"
        )
    # El admin sí: es el bypass total, y esa es su definicion declarada.
    assert _scope("admin").allows(ajeno)
