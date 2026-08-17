"""IDENTIDAD DURABLE en la proyeccion del proveedor de Neo4j (P0 de RC).

QUE SE MIDE AQUI Y QUE NO
-------------------------
Aqui se mide la PROYECCION: que sale de `_node_to_dict` / `_rel_to_dict`. Es la
frontera exacta donde el defecto vivia -- la lista blanca no incluia
`entity_id`, asi que el `elementId` de Neo4j ocupaba el campo `id` y viajaba
entero hasta el `href` de cada ficha.

Esto NO demuestra durabilidad. Un test de conversion no puede: nunca ve un
`restore`. La demostracion esta en
`test_neo4j_integration_authz.py`, seccion «IDENTIFICADOR DURABLE», que crea la
entidad, guarda el enlace del panel, restaura en un store nuevo, COMPRUEBA que
el identificador fisico cambio y vuelve a abrir el enlace guardado. Este fichero
es el cinturon: corre en cada `pytest viewer/tests/` sin necesidad de Neo4j y
congela la forma que aquella prueba da por supuesta.

LA TRAMPA QUE ESTE FICHERO EVITA A PROPOSITO
--------------------------------------------
`viewer/examples/sample_graph.json` trae, en cada nodo, `id` y `entity_id` con
el MISMO valor (`"n_agasha_tamori"` en los dos). Un fixture asi no puede
distinguir «el dato llego» de «se aplico el respaldo»: si alguien reintrodujera
`entity_id = node.get("entity_id") or node.get("id")`, seguiria verde.

Por eso todos los dobles de aqui usan tres valores que NO pueden confundirse
entre si -- `entity_id` con el formato real del writer V3, `canonical_name`
legible, y `element_id` con la forma del driver -- y hay un test
(`test_los_valores_del_doble_no_pueden_confundirse`) que comprueba esa
no-colision ANTES de que ninguna otra medida signifique nada.
"""
from __future__ import annotations

import re

import pytest

from app.providers.neo4j_provider import _node_to_dict, _rel_to_dict
from app.serializers import serialize_node

# --- material del doble ------------------------------------------------------
#
# `entity_id` con el formato que produce de verdad el writer V3
# (`resolution/provisional.py`): prefijo `entity:new:` + 16 hex de
# `sha256(workspace \x1f superficie \x1f tipo)`.
ENTITY_ID = "entity:new:0dcb4f1a2e5b7c93"
#: Forma del identificador FISICO del driver: `<n>:<uuid>:<id interno>`.
ELEMENT_ID = "4:9f1c2b3a-0000-4000-8000-000000000001:17"
#: El mismo nodo despues de un `restore`: mismas propiedades, otro id fisico.
ELEMENT_ID_TRAS_RESTORE = "4:c7e50a44-1111-4000-8000-000000000002:508"
CANONICAL = "Agasha Tamori"

_FORMA_ELEMENT_ID = re.compile(r"^\d+:[0-9a-fA-F-]{36}:\d+$")


class NodoDoble:
    """Lo justo de un nodo del driver: mapa de propiedades + `element_id`."""

    def __init__(self, props: dict, element_id: str = ELEMENT_ID):
        self._props = dict(props)
        self.element_id = element_id

    def __iter__(self):
        return iter(self._props)

    def __getitem__(self, k):
        return self._props[k]

    def keys(self):
        return self._props.keys()


class RelacionDoble(NodoDoble):
    def __init__(self, props: dict, start: NodoDoble, end: NodoDoble):
        super().__init__(props, "5:9f1c2b3a-0000-4000-8000-000000000001:99")
        self.type = "VENERA"
        self.start_node = start
        self.end_node = end


def nodo(entity_id=ENTITY_ID, element_id=ELEMENT_ID, **extra) -> NodoDoble:
    props = {"canonical_name": CANONICAL, "entity_type": "Character"}
    if entity_id is not None:
        props["entity_id"] = entity_id
    props.update(extra)
    return NodoDoble(props, element_id)


# ===========================================================================
# 0. El doble discrimina. Sin esto, nada de lo de abajo mide nada.
# ===========================================================================

def test_los_valores_del_doble_no_pueden_confundirse():
    """No-colision COMPROBADA, no supuesta.

    Si `entity_id`, `canonical_name` y `element_id` compartieran valor -- que es
    justo lo que pasa en `sample_graph.json` -- ninguna de las pruebas
    siguientes podria distinguir «llego el `entity_id`» de «se aplico un
    respaldo hacia el `elementId`». La distincion es la medida.
    """
    valores = [ENTITY_ID, ELEMENT_ID, ELEMENT_ID_TRAS_RESTORE, CANONICAL]
    assert len(set(valores)) == len(valores), "dos valores del doble coinciden"
    assert _FORMA_ELEMENT_ID.match(ELEMENT_ID)
    assert _FORMA_ELEMENT_ID.match(ELEMENT_ID_TRAS_RESTORE)
    assert not _FORMA_ELEMENT_ID.match(ENTITY_ID), (
        "el `entity_id` de prueba tiene forma de elementId: un respaldo pasaria "
        "desapercibido"
    )
    assert ELEMENT_ID != ELEMENT_ID_TRAS_RESTORE, (
        "el 'antes' y el 'despues' del restore son iguales: la mutacion de "
        "identidad fisica no ejerceria nada"
    )


# ===========================================================================
# 1. `entity_id` VIAJA. Este es el defecto que abrio el carril.
# ===========================================================================

def test_entity_id_viaja_en_la_proyeccion():
    d = _node_to_dict(nodo())
    assert d["entity_id"] == ENTITY_ID, (
        "`_node_to_dict` no transporta `entity_id`. Es una lista blanca "
        "explicita: lo que no este nombrado no llega, y sin `entity_id` la "
        "identidad que viaja a la URL solo puede ser el `elementId`."
    )


def test_el_id_publicado_es_el_durable_y_no_el_fisico():
    d = _node_to_dict(nodo())
    assert d["id"] == ENTITY_ID
    assert d["id"] != ELEMENT_ID, (
        "el campo `id` --el que acaba en el `href` de la ficha-- sigue siendo "
        "el elementId de Neo4j"
    )
    assert not _FORMA_ELEMENT_ID.match(str(d["id"]))


def test_el_element_id_no_se_proyecta_por_ninguna_clave():
    """No basta con no ponerlo en `id`: no puede salir POR NADA.

    `serialize_node` hace `node.get("id") or node.get("element_id")`. Si la
    proyeccion publicara `element_id` en cualquier clave, el serializador lo
    recogeria por ese respaldo en cuanto `id` fuera vacio, y el identificador
    fisico volveria a la URL por la puerta de atras.
    """
    d = _node_to_dict(nodo())
    culpables = [k for k, v in d.items() if ELEMENT_ID in str(v)]
    assert culpables == [], f"el elementId se proyecta en {culpables}"


# ===========================================================================
# 2. CONTROLES NEGATIVOS de la proyeccion
# ===========================================================================

def test_cambiar_el_element_id_no_cambia_la_identidad_publicada():
    """El control que define «durable»: otro id fisico, la misma identidad.

    Es exactamente lo que hace un `dump`/`restore`. Antes de este carril este
    test era imposible de pasar: `id` ERA el `element_id`.
    """
    antes = _node_to_dict(nodo(element_id=ELEMENT_ID))
    despues = _node_to_dict(nodo(element_id=ELEMENT_ID_TRAS_RESTORE))
    assert antes["id"] == despues["id"] == ENTITY_ID
    assert antes == despues, (
        "la proyeccion cambia al cambiar el identificador fisico: algo del "
        "`elementId` se sigue colando"
    )


def test_cambiar_el_entity_id_SI_cambia_la_identidad_publicada():
    """CONTROL NEGATIVO DECISIVO, en su version de proyeccion.

    Si tocar el identificador de dominio NO moviera el `id` publicado, es que
    el `id` no viene de `entity_id` y todo lo demas seria decorado. Su gemelo
    de extremo a extremo --cambiar el `entity_id` en Neo4j y ver el enlace
    guardado ponerse ROJO-- vive en la suite de integracion.
    """
    otro = "entity:new:ffffffffffffffff"
    assert otro != ENTITY_ID
    assert _node_to_dict(nodo(entity_id=otro))["id"] == otro
    assert _node_to_dict(nodo(entity_id=otro))["id"] != ENTITY_ID


def test_un_nodo_sin_entity_id_no_es_direccionable():
    """Sin identidad durable no hay identidad. NO se degrada al `elementId`.

    Degradar seria lo comodo y es justo el defecto: el enlace parecerian
    funcionar y moriria en la siguiente restauracion, con un 404 indistinguible
    de «no existe».
    """
    d = _node_to_dict(nodo(entity_id=None))
    assert d["entity_id"] is None
    assert d["id"] is None
    assert ELEMENT_ID not in str(d)
    # Y el serializador tampoco lo rescata.
    assert serialize_node(d)["entity_id"] == ""
    assert serialize_node(d)["id"] is None


# ===========================================================================
# 3. Aristas: los extremos tambien son identidad de dominio
# ===========================================================================

OTRO_ENTITY_ID = "entity:new:aa11bb22cc33dd44"


def _arista(desde=None, hacia=None):
    a = nodo(entity_id=ENTITY_ID, element_id=ELEMENT_ID)
    b = nodo(entity_id=OTRO_ENTITY_ID, element_id=ELEMENT_ID_TRAS_RESTORE)
    return _rel_to_dict(RelacionDoble({"visibility": "player"}, a, b), desde, hacia)


def test_los_extremos_de_una_arista_son_entity_id():
    """`PolicyFilteredProvider` --zona congelada-- resuelve el otro extremo con
    `self._base.entity(edge["from"|"to"])` y cruza nodos con `{n["id"]}`. Si los
    extremos no vivieran en el mismo espacio de nombres que `entity()`, el visor
    se quedaria sin una sola relacion.
    """
    e = _arista(ENTITY_ID, OTRO_ENTITY_ID)
    assert e["from"] == ENTITY_ID
    assert e["to"] == OTRO_ENTITY_ID


def test_los_extremos_nunca_caen_hacia_el_element_id():
    """Sin extremos explicitos desde Cypher, la respuesta honesta es `None`.

    El respaldo tentador (`nodo.element_id`) es el que reintroduce el defecto.
    """
    e = _arista()  # el driver entrega los extremos sin hidratar
    assert e["from"] == ENTITY_ID and e["to"] == OTRO_ENTITY_ID
    sin_props = _rel_to_dict(
        RelacionDoble({}, NodoDoble({}, ELEMENT_ID), NodoDoble({}, ELEMENT_ID_TRAS_RESTORE))
    )
    assert sin_props["from"] is None and sin_props["to"] is None, (
        "un extremo sin `entity_id` ha caido hacia el identificador fisico"
    )


@pytest.mark.parametrize("campo", ["from", "to"])
def test_los_extremos_no_tienen_forma_de_element_id(campo):
    assert not _FORMA_ELEMENT_ID.match(str(_arista(ENTITY_ID, OTRO_ENTITY_ID)[campo]))
