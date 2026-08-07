"""CONTRATO entre el proveedor de Neo4j y el motor de politica (M5c).

Este fichero existe por un defecto concreto, y conviene contarlo porque el
defecto no se veia en ningun sitio:

    675 pruebas verdes del motor de politica
    + un serializador que descartaba `partida_id`
    = el aislamiento entre partidas NUNCA se evaluaba sobre datos reales

`_node_to_dict` construia el diccionario con una lista CERRADA de claves. Los
campos que el motor necesita para decidir --`partida_id`, `known_by`-- no
estaban en esa lista, y `_rel_to_dict` tampoco llevaba `visibility`. El writer
si los escribia en Neo4j: el dato existia y estaba bien etiquetado, y se perdia
al proyectarlo. Como todas las pruebas del motor usaban diccionarios fabricados
a mano, ninguna toco jamas esa frontera: `grep` de los serializadores reales en
toda la carpeta de tests daba cero.

La leccion no es "faltaban campos" sino que una proyeccion parcial silencia una
barrera entera sin poner nada en rojo. Por eso aqui no se prueba comportamiento:
se CONGELA la forma. Si alguien vuelve a quitar un campo de autorizacion de la
proyeccion, este fichero se pone rojo aunque el motor siga perfecto.
"""
from __future__ import annotations

import inspect
import re

import pytest

from app.policies import engine as engine_mod
from app.providers.neo4j_provider import _node_to_dict, _rel_to_dict

#: Campos que el motor de politica LEE de un nodo para decidir. Si anades una
#: regla que consulte un campo nuevo, va aqui y en el serializador.
CAMPOS_AUTORIZACION_NODO = (
    "workspace",
    "scope",
    "partida_id",
    "visibility",
    "known_by",
    "party",
    "is_public",
    "session_index",
)

#: Idem para relaciones. Una arista se evalua con `can_view` igual que un nodo.
CAMPOS_AUTORIZACION_RELACION = (
    "workspace",
    "scope",
    "partida_id",
    "visibility",
    "known_by",
)


class _NodoFalso:
    """Imita lo justo de un nodo del driver: mapa de propiedades + element_id."""

    def __init__(self, props, element_id="4:db:1"):
        self._props = props
        self.element_id = element_id

    def keys(self):
        return self._props.keys()

    def __getitem__(self, k):
        return self._props[k]

    def __iter__(self):
        return iter(self._props)


class _RelacionFalsa(_NodoFalso):
    def __init__(self, props, element_id="5:db:1"):
        super().__init__(props, element_id)
        self.type = "CONOCE"
        self.start_node = _NodoFalso({}, "4:db:1")
        self.end_node = _NodoFalso({}, "4:db:2")


@pytest.mark.parametrize("campo", CAMPOS_AUTORIZACION_NODO)
def test_el_serializador_de_nodo_transporta_el_campo_de_autorizacion(campo):
    valor = {"known_by": ["pc:ana"], "is_public": True, "session_index": 3}.get(campo, f"v:{campo}")
    d = _node_to_dict(_NodoFalso({campo: valor}))
    assert campo in d, (
        f"_node_to_dict ha dejado de transportar '{campo}'. El motor decide con "
        f"ese campo: sin el, su barrera deja de evaluarse sobre datos reales."
    )
    assert d[campo] == valor


@pytest.mark.parametrize("campo", CAMPOS_AUTORIZACION_RELACION)
def test_el_serializador_de_relacion_transporta_el_campo_de_autorizacion(campo):
    valor = {"known_by": ["pc:ana"]}.get(campo, f"v:{campo}")
    d = _rel_to_dict(_RelacionFalsa({campo: valor}))
    assert campo in d, (
        f"_rel_to_dict ha dejado de transportar '{campo}'. Sin 'visibility', "
        f"TODA relacion cae en visibility_invalid y el visor real se queda sin "
        f"una sola arista."
    )
    assert d[campo] == valor


def test_un_campo_ausente_en_neo4j_llega_como_None_y_no_desaparece():
    """La clave debe existir aunque la propiedad no este en la base.

    Importa la diferencia: una clave ausente hace que `node.get(campo)` valga
    None igual que un valor nulo, pero deja al motor sin poder distinguir "no
    hay dato" de "no me lo pasaron". Con la clave siempre presente, la decision
    fail-closed se toma sobre el dato real.
    """
    d = _node_to_dict(_NodoFalso({}))
    for campo in CAMPOS_AUTORIZACION_NODO:
        assert campo in d
        assert d[campo] is None or d[campo] == [] or d[campo] == ""


def test_ningun_campo_que_el_motor_consulta_queda_fuera_de_la_lista():
    """Red de seguridad contra el olvido inverso.

    Si alguien anade al motor una regla que lee `node.get("nuevo_campo")` y no
    lo anade a la proyeccion, el fallo vuelve a ser invisible. Este test lee el
    codigo del motor y exige que todo `node.get(...)` este cubierto arriba.
    """
    fuente = inspect.getsource(engine_mod.VisibilityPolicy.can_view)
    leidos = set(re.findall(r'node\.get\(\s*"([a-z_]+)"', fuente))
    # `id` no es autorizacion: es identidad, y siempre viaja.
    leidos.discard("id")
    faltan = leidos - set(CAMPOS_AUTORIZACION_NODO)
    assert not faltan, (
        f"el motor consulta {sorted(faltan)} pero la proyeccion no lo declara: "
        f"anadelo a CAMPOS_AUTORIZACION_NODO y al serializador"
    )
