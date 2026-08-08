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
    # Segundo nombre del mismo dato, escrito por `ingest_rpg` en los nodos
    # `:Entity` que el visor lee de verdad. El motor lo consulta desde
    # `models.known_by_of`, no desde `can_view`, y por eso la red inversa de
    # abajo tuvo que dejar de mirar un solo fichero.
    "known_by_characters",
    # Sesión de REVELACIÓN (T2). Sustituye a `session_index`, que el motor leía
    # y ningún escritor producía: una regla entera evaluándose sobre un campo
    # inexistente, en verde. `party` e `is_public` salieron de esta lista al
    # retirarse la ACL de party (T1); siguen viajando como dato, pero ya no son
    # vocabulario de autorización, y por eso no se congelan aquí.
    "known_from_session",
)

#: Idem para relaciones. Una arista se evalua con `can_view` EXACTAMENTE igual
#: que un nodo, asi que la lista es la MISMA. Al escribir este fichero por
#: primera vez se dejo mas corta --sin `party`, `is_public` ni `session_index`--
#: y eso reproducia el defecto que venia a impedir: las reglas de party y de
#: sesion futura quedaban apagadas solo para relaciones, en verde. De ahi que
#: ahora sea la misma tupla y que exista el test de simetria de abajo.
CAMPOS_AUTORIZACION_RELACION = CAMPOS_AUTORIZACION_NODO


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


def test_nodos_y_relaciones_declaran_los_mismos_campos():
    """Simetria obligatoria: el motor no distingue nodo de arista al decidir.

    Una lista mas corta para relaciones no "protege menos": apaga la regla
    entera solo para aristas, y en verde. Ya paso una vez.
    """
    assert set(CAMPOS_AUTORIZACION_RELACION) == set(CAMPOS_AUTORIZACION_NODO)
    falsa = _RelacionFalsa({c: "x" for c in CAMPOS_AUTORIZACION_NODO})
    proyectada = _rel_to_dict(falsa)
    faltan = [c for c in CAMPOS_AUTORIZACION_NODO if c not in proyectada]
    assert not faltan, f"_rel_to_dict no transporta {faltan}"


def test_el_wrapper_de_politica_cubre_todos_los_metodos_del_proveedor():
    """Ningun metodo del proveedor puede llegar al router sin pasar el filtro.

    `PolicyFilteredProvider` protege sobrescribiendo metodo a metodo. Es
    efectivo pero fragil: un metodo nuevo en el ABC que nadie sobrescriba se
    hereda sin filtrar y la fuga es inmediata y silenciosa. Este test convierte
    esa disciplina en algo comprobable.
    """
    from app.authz.filtered_provider import PolicyFilteredProvider
    from app.providers.base import GraphProvider

    metodos = {
        nombre for nombre, valor in vars(GraphProvider).items()
        if callable(valor) and not nombre.startswith("_")
    }
    sin_cubrir = {m for m in metodos if m not in vars(PolicyFilteredProvider)}
    assert not sin_cubrir, (
        f"PolicyFilteredProvider no sobrescribe {sorted(sin_cubrir)}: esos "
        f"metodos llegarian al router SIN filtrar por politica"
    )


def test_ningun_campo_que_el_motor_consulta_queda_fuera_de_la_lista():
    """Red de seguridad contra el olvido inverso.

    Si alguien anade al motor una regla que lee `node.get("nuevo_campo")` y no
    lo anade a la proyeccion, el fallo vuelve a ser invisible. Este test lee el
    codigo del motor y exige que todo `node.get(...)` este cubierto arriba.

    Este test miraba SOLO `can_view`, y por eso no vio que `known_by_of` --en
    `policies/models.py`-- leía `known_by_characters`, un campo que la
    proyección no transportaba. La red anti-reincidencia contenía viva una
    reincidencia. Ahora barre los dos módulos de política enteros: una regla
    puede mudarse de función, y la red no debe depender de dónde viva.
    """
    import app.policies.models as models_mod

    fuente = "\n".join(
        inspect.getsource(m) for m in (engine_mod, models_mod)
    )
    leidos = set(re.findall(r'node\.get\(\s*["\']([a-z_]+)["\']', fuente))
    # Campos que no son de autorización sino de identidad/estructura.
    leidos -= {"type", "name", "label"}
    # `id` no es autorizacion: es identidad, y siempre viaja.
    leidos.discard("id")
    faltan = leidos - set(CAMPOS_AUTORIZACION_NODO)
    assert not faltan, (
        f"el motor consulta {sorted(faltan)} pero la proyeccion no lo declara: "
        f"anadelo a CAMPOS_AUTORIZACION_NODO y al serializador"
    )
