"""El registro deja de ser una DECLARACION y pasa a ser una ESPECIFICACION.

El sexto dictamen encontro el defecto de fondo de las seis rondas anteriores,
esta vez dentro de la propia red anti-reincidencia:

    `viewer/app/policies/registry.py` declaraba la semantica que queremos, y
    NADA probaba que el motor la cumpliera.

`known_from_session` declaraba `missing=DENY` y el motor --`if desde is not
None:`-- dejaba pasar la ausencia: un nodo `scope=partida` sin sesion de
revelacion era visible con cualquier tope. La red anterior daba por buena esa
dimension porque su comprobacion era que el NOMBRE del campo apareciera en
algun fichero de prueba. Mencionar no es probar.

Aqui, para cada dimension declarada:

  1. se construye un caso VISIBLE de referencia,
  2. se le quita el campo y se comprueba que el motor hace lo que el registro
     dice que hace ante la ausencia,
  3. se corrompe el campo y se comprueba lo mismo ante el dato invalido,
  4. y se exige que la dimension declare --y que existan de verdad-- su prueba
     negativa y su prueba de extremo a extremo por HTTP.

Los puntos 2 y 3 son el motor de VERDAD, no una lectura del registro: si
alguien vuelve a poner `if x is not None:` en una decision de seguridad, el
registro seguira diciendo DENY y este fichero se pondra rojo.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.policies.engine import POLICY
from app.policies.models import NO_APLICA, ViewerContext
from app.policies.registry import (
    CAMPOS_DEL_CONTEXTO,
    CAMPOS_DEL_DATO,
    DENY,
    MINIMO,
    NEUTRO,
    TODOS,
)

WS = "juego:spec"
OTRO_WS = "juego:ajeno"
P = "partida:alfa"
OTRA_P = "partida:beta"
PJ = "pc:ana"

#: Valor invalido universal: no es cadena, ni entero, ni lista de cadenas. Sirve
#: como "dato corrupto" para cualquier dimension sin tener que inventar uno por
#: campo (y sin que la prueba se ablande campo a campo).
CORRUPTO = {"malo": 1}


def _ctx(**over) -> ViewerContext:
    base = dict(
        role="viewer",
        allowed_workspaces=frozenset({WS}),
        active_partida=P,
        allowed_partida_ids=frozenset({P}),
        active_character=PJ,
        max_visible_session=5,
        can_view_secret=False,
        can_view_future=False,
        can_view_reference=True,
        session_public=True,
        # P0-AUTH: la referencia tiene que EJERCER las dimensiones nuevas, o su
        # prueba de ausencia pasaria por vacuidad. `character_knowledge` concede
        # `secreto_por_id` y `can_view_reference` concede `manual`; sin ellas en
        # la referencia, quitarlas no cambiaria nada y el subconjunto se
        # cumpliria siempre.
        character_knowledge=frozenset({"secreto_por_id"}),
        # LORE-ANONIMO-DENEGADO: la referencia es un lector AUTENTICADO, y la
        # capa juego (`lore`, `manual`) es suya. Sin esta llave el corpus de
        # referencia perderia esos dos nodos y el contraveneno de mas abajo
        # --que exige `lore` visible-- se pondria rojo por la razon equivocada.
        can_view_lore=True,
    )
    base.update(over)
    return ViewerContext(**base)


def _nodo_base(campo: str) -> dict:
    """Caso VISIBLE de referencia, ajustado a la dimension bajo prueba.

    `known_by` y `known_by_characters` son dos nombres del mismo dato y el
    lector prefiere el primero: si estuvieran los dos, corromper el segundo no
    tendria efecto y la prueba pasaria por la razon equivocada.
    """
    nodo = {
        "id": "n1",
        "workspace": WS,
        "scope": "partida",
        "partida_id": P,
        "visibility": "player",
        "known_from_session": 2,
    }
    if campo == "known_by_characters":
        nodo["known_by_characters"] = [PJ]
    else:
        nodo["known_by"] = [PJ]
    return nodo


def test_el_caso_de_referencia_es_visible():
    """Si la referencia no fuera visible, TODAS las comprobaciones de abajo
    pasarian sin demostrar nada: es el modo de fallo silencioso clasico de una
    prueba negativa."""
    for campo in ("known_by", "known_by_characters"):
        d = POLICY.can_view(_nodo_base(campo), _ctx())
        assert d.visible, f"referencia no visible ({campo}): {d.reason}"


# --- 1. el comportamiento REAL del motor frente a lo declarado --------------

@pytest.mark.parametrize("campo", CAMPOS_DEL_DATO, ids=lambda c: c.name)
def test_la_ausencia_y_el_dato_invalido_se_comportan_como_declara_el_registro(campo):
    nombre = campo.stored_as or campo.name
    ctx = _ctx()
    base = _nodo_base(campo.name)
    assert POLICY.can_view(base, ctx).visible

    # --- ausencia
    sin = {k: v for k, v in base.items() if k != nombre}
    d = POLICY.can_view(sin, ctx)
    if campo.missing == DENY:
        assert not d.visible, (
            f"'{campo.name}' declara missing=DENY y el motor lo deja pasar "
            f"({d.reason}). Es H6-1 exactamente: la declaracion dice una cosa y "
            f"la cadena hace otra."
        )
    elif campo.missing == NEUTRO:
        assert d.visible, (
            f"'{campo.name}' declara su ausencia como NEUTRA y el motor deniega "
            f"({d.reason}): la declaracion y el motor no dicen lo mismo"
        )
    else:  # MINIMO
        assert not d.visible, (
            f"'{campo.name}' declara minimo privilegio ante la ausencia y el "
            f"motor concede"
        )

    # --- dato invalido
    corrupto = dict(base)
    corrupto[nombre] = CORRUPTO
    d = POLICY.can_view(corrupto, ctx)
    assert not d.visible, (
        f"'{campo.name}' declara malformed={campo.malformed} y el motor deja "
        f"pasar un valor corrupto ({d.reason})"
    )


# --- 2. las dimensiones del CONTEXTO no amplian al faltar -------------------

#: Corpus de nodos que cubre las dos capas, los dos workspaces, las dos
#: partidas, el nivel elevado y la revelacion futura. Se compara CONJUNTOS de
#: visibles: la propiedad que interesa no es "deniega este nodo" sino "quitarle
#: contexto al lector nunca le ensena mas".
CORPUS = [
    {"id": "lore", "workspace": WS, "scope": "juego", "visibility": "player"},
    {"id": "propia", "workspace": WS, "scope": "partida", "partida_id": P,
     "visibility": "player", "known_from_session": 2},
    {"id": "propia_futura", "workspace": WS, "scope": "partida", "partida_id": P,
     "visibility": "player", "known_from_session": 40},
    {"id": "propia_secreta", "workspace": WS, "scope": "partida", "partida_id": P,
     "visibility": "secret", "known_from_session": 2, "known_by": [PJ]},
    {"id": "secreto_ajeno", "workspace": WS, "scope": "partida", "partida_id": P,
     "visibility": "secret", "known_from_session": 2, "known_by": ["pc:bryn"]},
    {"id": "otra_partida", "workspace": WS, "scope": "partida", "partida_id": OTRA_P,
     "visibility": "player", "known_from_session": 0},
    {"id": "otro_ws", "workspace": OTRO_WS, "scope": "juego", "visibility": "player"},
    # P0-AUTH -- material que SOLO abre una de las dimensiones nuevas.
    {"id": "manual", "workspace": WS, "scope": "juego", "visibility": "reference"},
    {"id": "secreto_por_id", "workspace": WS, "scope": "partida", "partida_id": P,
     "visibility": "secret", "known_from_session": 2},
    {"id": "denegado", "workspace": WS, "scope": "juego", "visibility": "deny"},
]

#: Representacion de "esta dimension no llega" para cada dimension del contexto,
#: en sus variantes realistas. Se declara aqui y se exige cobertura completa
#: mas abajo: anadir una dimension al registro sin decir como se ve su ausencia
#: pone rojo el fichero, en vez de quedar sin cubrir en silencio.
AUSENCIAS: dict[str, list] = {
    "max_visible_session": [None, NO_APLICA, CORRUPTO, -1, True, "5"],
    "active_character": [None, "", "   "],
    "allowed_partida_ids": [frozenset()],
    "can_view_future": [False],
    "can_view_secret": [False],
    "allowed_workspaces": [frozenset()],
    "can_view_reference": [False],
    "character_knowledge": [frozenset()],
    # `admin_full` es una CONCESION booleana: su ausencia es `False`, y `False`
    # es el minimo por construccion. Este caso comprueba la monotonia igual que
    # los demas, pero se dice con todas las letras que es DEBIL: la referencia
    # ya se evalua sin la potestad, asi que quitarla no puede ensenar mas. Lo
    # que de verdad sostiene esta dimension no es esta linea, sino la cadena
    # HTTP completa --concesion, uso y REVOCACION-- de
    # `test_p0_autoridad_admin_full_http.py`, mas la mutacion que la reintroduce
    # por cada una de sus tres vias. Declararlo aqui, en vez de cobrarse este
    # caso como cobertura, es la diferencia entre medir y aparentar.
    "admin_full": [False],
    # LORE-ANONIMO-DENEGADO. Su ausencia es `False` y retira la capa juego
    # entera (`lore`, `manual`, `denegado`): a diferencia de `admin_full`, este
    # caso NO es debil -- la referencia SI ejerce la dimension, porque tres
    # nodos del corpus son de `scope=juego` y solo esta llave los abre.
    "can_view_lore": [False],
}


def _visibles(ctx) -> set[str]:
    return {n["id"] for n in CORPUS if POLICY.can_view(n, ctx).visible}


def test_toda_dimension_del_contexto_declara_como_se_ve_su_ausencia():
    faltan = {c.name for c in CAMPOS_DEL_CONTEXTO} - set(AUSENCIAS)
    assert not faltan, (
        f"{sorted(faltan)} son dimensiones de contexto sin representacion de "
        f"ausencia declarada: su fail-closed no se estaria ejerciendo"
    )


@pytest.mark.parametrize("campo", CAMPOS_DEL_CONTEXTO, ids=lambda c: c.name)
def test_una_dimension_de_contexto_ausente_nunca_amplia_lo_visible(campo):
    """H6-9 generalizado: menos contexto no puede dar mas acceso.

    Antes, un autenticado sin partida activa recibia `max_visible_session=None`
    y quedaba MENOS restringido que un anonimo, que recibe 0.
    """
    referencia = _visibles(_ctx())
    for ausencia in AUSENCIAS[campo.name]:
        ctx = _ctx(**{campo.name: ausencia})
        visto = _visibles(ctx)
        assert visto <= referencia, (
            f"con '{campo.name}' = {ausencia!r} se ve MAS que con la concesion "
            f"completa: {sorted(visto - referencia)}"
        )


def test_el_corpus_de_referencia_no_es_todo_invisible():
    """Contraveneno: si la referencia estuviera vacia, el subconjunto de arriba
    se cumpliria siempre y el test seria decorativo."""
    assert {"lore", "propia", "propia_secreta"} <= _visibles(_ctx())
    assert "propia_futura" not in _visibles(_ctx())
    assert "otra_partida" not in _visibles(_ctx())


# --- 3. cada dimension declara pruebas, y esas pruebas EXISTEN --------------

RAIZ_VIEWER = Path(__file__).resolve().parents[1]


def _existe(test_id: str) -> bool:
    """¿Apunta ese `fichero::test[param]` a una funcion de prueba real?"""
    if "::" not in test_id:
        return False
    fichero, nombre = test_id.split("::", 1)
    nombre = re.sub(r"\[.*\]$", "", nombre)
    p = RAIZ_VIEWER / fichero
    if not p.exists():
        return False
    return re.search(rf"^def {re.escape(nombre)}\(", p.read_text(encoding="utf-8"),
                     re.M) is not None


@pytest.mark.parametrize("campo", TODOS, ids=lambda c: c.name)
def test_cada_dimension_declara_una_prueba_negativa_que_existe(campo):
    assert campo.prueba_negativa, (
        f"'{campo.name}' declara su fail-closed y no dice que prueba lo "
        f"demuestra: eso es lo que permitio que el registro dijera DENY "
        f"mientras el motor dejaba pasar la ausencia"
    )
    assert _existe(campo.prueba_negativa), (
        f"la prueba negativa declarada por '{campo.name}' no existe: "
        f"{campo.prueba_negativa}"
    )


@pytest.mark.parametrize("campo", TODOS, ids=lambda c: c.name)
def test_cada_dimension_declara_una_prueba_HTTP_que_existe(campo):
    """H6-5: sin una prueba que atraviese HTTP, una dimension puede estar
    inerte en produccion con el CI en verde."""
    assert campo.prueba_http, f"'{campo.name}' no declara prueba de extremo a extremo"
    assert _existe(campo.prueba_http), (
        f"la prueba HTTP declarada por '{campo.name}' no existe: {campo.prueba_http}"
    )


def test_las_pruebas_HTTP_declaradas_atraviesan_de_verdad_HTTP():
    """Que el fichero declarado sea una prueba de cadena y no otra unitaria
    disfrazada: tiene que pedir por HTTP con una sesion real."""
    for campo in TODOS:
        fichero = RAIZ_VIEWER / campo.prueba_http.split("::")[0]
        texto = fichero.read_text(encoding="utf-8")
        assert "TestClient" in texto or "_cliente(" in texto, (
            f"'{campo.name}' declara como prueba HTTP un fichero que no hace "
            f"ninguna peticion: {fichero.name}"
        )
        assert "ViewerContext(" not in texto, (
            f"'{campo.name}' declara como prueba HTTP un fichero que fabrica el "
            f"ViewerContext a mano: ese atajo se salta justo los tramos donde "
            f"vivian H-A y H6-5"
        )
