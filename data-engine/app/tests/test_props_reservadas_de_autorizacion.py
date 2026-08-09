"""Las propiedades de autorizacion son RESERVADAS del writer (H6-3, H6-4).

Sexto dictamen: `known_by_characters` y `known_from_session` son campos que el
motor de politicas CONSUME para decidir, y estaban fuera del guardado reservado
del writer. Un payload podia fijarlos y conceder conocimiento --o adelantar la
sesion de revelacion-- por la puerta de atras. Se corrigieron, pero sin prueba:
quitarlos de la lista dejaba el arbol verde, que es la definicion misma del
defecto que esta ronda cierra.

Ademas se comprueba que las DOS listas que deben coincidir --`VISIBILITY_PROPS`
(lo que estampa el modulo de visibilidad) y `RESERVED_PROPS` (lo que el payload
no puede fijar)-- no divergen: dos listas que deben ser iguales y nada que lo
verifique acaban divergiendo.
"""
from __future__ import annotations

import pytest

from knowledge_v3.writer import codes
from knowledge_v3.writer.cypher import RESERVED_PROPS, safe_props
from knowledge_v3.writer.errors import WriterAbort
from knowledge_v3.writer.visibility import VISIBILITY_PROPS


#: Toda dimension que el motor del visor consume para decidir. El payload no
#: puede fijar NINGUNA: la autoridad es el writer.
DIMENSIONES_DE_AUTORIZACION = [
    "workspace",
    "partida_id",
    "scope",
    "visibility",
    "known_by",
    "known_by_characters",
    "known_from_session",
]


@pytest.mark.parametrize("prop", DIMENSIONES_DE_AUTORIZACION)
def test_el_payload_no_puede_fijar_una_dimension_de_autorizacion(prop):
    with pytest.raises(WriterAbort) as exc:
        safe_props({prop: "lo que sea"})
    assert exc.value.code == codes.EXEC_UNSUPPORTED_PAYLOAD


@pytest.mark.parametrize("prop", DIMENSIONES_DE_AUTORIZACION)
def test_cada_dimension_esta_declarada_como_reservada(prop):
    assert prop in RESERVED_PROPS


def test_las_dos_listas_de_props_de_visibilidad_no_divergen():
    """`VISIBILITY_PROPS` describe lo que estampa el modulo de visibilidad; si
    algo de ahi no es reservado, el payload puede pisarlo."""
    fuera = VISIBILITY_PROPS - RESERVED_PROPS
    assert not fuera, (
        f"{sorted(fuera)} se estampan como visibilidad pero el payload puede "
        f"fijarlas: la autoridad del writer seria decorativa"
    )


def test_una_propiedad_normal_si_pasa():
    """La red no puede ser "prohibirlo todo": eso tambien pasaria los tests."""
    assert safe_props({"display_name": "Ana"}) == {"display_name": "Ana"}
