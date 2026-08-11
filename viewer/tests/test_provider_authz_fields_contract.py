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

Carril J (calidad de datos, v2) -- SE ELIMINA LA SEGUNDA FUENTE
---------------------------------------------------------------
Hasta ahora `CAMPOS_AUTORIZACION_NODO` era una tupla escrita A MANO en este
fichero: una SEGUNDA declaracion del modelo de autorizacion, paralela al
registro ejecutable `app/policies/registry.py`. Un modelo de autorizacion
declarado en dos sitios es un modelo de autorizacion que en algun momento estara
declarado de dos maneras, y el dia que se separen nadie se entera, porque cada
lista por separado es coherente consigo misma.

Ahora la tupla se DERIVA del registro. Anadir, quitar o renombrar una dimension
alli se propaga hasta aqui sin tocar este fichero. Concretamente:

  * `in_projection` decide si la dimension viaja en la proyeccion del provider
    (las dimensiones del CONTEXTO no son campos de nodo).
  * `applies_to` decide si aplica a nodo, a relacion o a ambos.
  * `stored_as` decide con que nombre la escribe el productor, que es el nombre
    que hay que buscar en la proyeccion.

Y --esto es lo importante-- derivar por si solo NO basta. Si la lista se deriva
y alguien BORRA una dimension del registro, la lista simplemente se acorta: hay
menos casos parametrizados y todo sigue verde. Una derivacion sin testigo
independiente convierte un borrado en un silencio. El testigo independiente es
el CODIGO DEL MOTOR: si el motor sigue consultando la dimension que el registro
ya no declara, las redes inversas del final de este fichero se ponen rojas.
"""
from __future__ import annotations

import dataclasses
import inspect
import re

import pytest

from app.policies import engine as engine_mod
from app.policies import models as models_mod
from app.policies.models import ViewerContext
from app.policies.registry import RETIRADAS, TODOS
from app.providers.neo4j_provider import _node_to_dict, _rel_to_dict


def _proyectados(destino: str) -> tuple[str, ...]:
    """Nombres que el provider debe transportar para `destino` (node/relationship).

    `stored_as` manda sobre `name`: la proyeccion lleva el nombre con el que el
    PRODUCTOR escribe el dato, no el nombre de la dimension. Un campo que se
    escribe con un nombre y se lee con otro fue exactamente T1.
    """
    return tuple(
        c.stored_as or c.name
        for c in TODOS
        if c.in_projection and destino in c.applies_to
    )


#: Campos que el motor de politica LEE de un nodo para decidir. DERIVADO del
#: registro ejecutable: no se edita a mano.
CAMPOS_AUTORIZACION_NODO = _proyectados("node")

#: Idem para relaciones. Una arista se evalua con `can_view` EXACTAMENTE igual
#: que un nodo. Al escribir este fichero por primera vez la lista de relaciones
#: se dejo mas corta --sin `party`, `is_public` ni `session_index`-- y eso
#: reproducia el defecto que venia a impedir: las reglas quedaban apagadas solo
#: para relaciones, en verde. Ya no se copia una tupla en la otra: se deriva
#: por separado y hay un test que exige que el REGISTRO las declare simetricas.
CAMPOS_AUTORIZACION_RELACION = _proyectados("relationship")

#: Dimensiones del CONTEXTO declaradas en el registro, con el nombre que usa el
#: motor (no el de almacenamiento).
DIMENSIONES_DEL_CONTEXTO = tuple(c.name for c in TODOS if not c.in_projection)

#: Dimensiones del contexto que el motor CONSUME y el registro NO declara.
#:
#: Esta cuarentena es un hallazgo de este carril, no un permiso. `viewer/app/
#: policies/**` es zona que este carril no puede modificar, asi que no se pueden
#: declarar aqui y ahora; se dejan nombradas para que (a) consten, y (b) la red
#: inversa siga siendo capaz de ponerse roja con CUALQUIER dimension nueva sin
#: declarar. La cuarentena solo puede ENCOGER: si crece, el test falla.
#:
#: Las tres son reales y consumidas dentro de una decision de autorizacion:
#:   admin_full          -- bypass TOTAL (`if ctx.admin_full: return visible`).
#:                          La dimension con mas poder del sistema no tiene
#:                          cadena declarada: ni autoridad, ni productor, ni
#:                          respuesta a "y si falta".
#:   can_view_reference  -- unica llave del nivel `reference`.
#:   character_knowledge -- concede conocimiento por ID precomputado, saltandose
#:                          `known_by`.
CONTEXTO_SIN_DECLARAR_EN_EL_REGISTRO = frozenset({
    "admin_full",
    "can_view_reference",
    "character_knowledge",
})

#: Campos que el motor lee de un nodo y NO son autorizacion sino identidad o
#: estructura del grafo.
_ESTRUCTURALES = frozenset({"type", "name", "label", "id", "from", "to"})


def _fuente_de_politica() -> str:
    """Codigo de los dos modulos de politica, SIN comentarios.

    Sin comentarios a proposito: una mencion en prosa no es un consumo. La red
    anterior barria el fichero entero y se conformaba con que el nombre
    apareciera en cualquier sitio.
    """
    lineas = []
    for mod in (engine_mod, models_mod):
        for ln in inspect.getsource(mod).splitlines():
            if not ln.lstrip().startswith("#"):
                lineas.append(ln)
    return "\n".join(lineas)


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


def test_el_registro_declara_al_menos_una_dimension_proyectada():
    """Guardia de la propia derivacion.

    Si un cambio en el registro (o en el criterio de derivacion) vaciase estas
    tuplas, todos los tests parametrizados de abajo desaparecerian y la suite
    seguiria verde con CERO comprobaciones. Cero casos no es un exito.
    """
    assert CAMPOS_AUTORIZACION_NODO, "la derivacion del registro no produce campos de nodo"
    assert CAMPOS_AUTORIZACION_RELACION, "la derivacion no produce campos de relacion"
    assert DIMENSIONES_DEL_CONTEXTO, "la derivacion no produce dimensiones de contexto"


def test_toda_dimension_del_registro_cae_en_exactamente_una_categoria():
    """Ninguna dimension puede evaporarse entre 'proyectada' y 'de contexto'.

    Una dimension con `in_projection=True` y `applies_to` vacio no la
    comprobaria nadie: ni la proyeccion (no aplica a nada) ni el contexto (dice
    que se proyecta). Se quedaria fuera de las dos redes en silencio.
    """
    proyectadas = set(CAMPOS_AUTORIZACION_NODO) | set(CAMPOS_AUTORIZACION_RELACION)
    huerfanas = [
        c.name for c in TODOS
        if c.in_projection and (c.stored_as or c.name) not in proyectadas
    ]
    assert not huerfanas, (
        f"{huerfanas} dicen proyectarse pero no aplican a nodo ni a relacion: "
        f"ninguna red las cubre"
    )
    assert len(TODOS) == len(proyectadas) + len(DIMENSIONES_DEL_CONTEXTO), (
        "el registro tiene dimensiones que no son ni proyectadas ni de contexto"
    )


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
        f"_rel_to_dict ha dejado de transportar '{campo}'. Sin el nivel de "
        f"visibilidad, TODA relacion cae en visibility_invalid y el visor real "
        f"se queda sin una sola arista."
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
    entera solo para aristas, y en verde. Ya paso una vez. Ahora la simetria se
    exige sobre el REGISTRO --que es donde se podria romper-- en vez de
    garantizarse por copia de una tupla en la otra, que la hacia cierta por
    construccion y por tanto incomprobable.
    """
    assert set(CAMPOS_AUTORIZACION_RELACION) == set(CAMPOS_AUTORIZACION_NODO), (
        "el registro declara dimensiones proyectadas que aplican solo a nodo o "
        "solo a relacion: eso apaga la regla para el otro tipo, en verde"
    )
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


# ---------------------------------------------------------------------------
# REDES INVERSAS. El motor es el testigo independiente de la derivacion.
# ---------------------------------------------------------------------------

def test_ningun_campo_de_nodo_que_el_motor_consulta_queda_fuera_del_registro():
    """Red de seguridad contra el olvido inverso, y contra el borrado silencioso.

    Dos fallos distintos caen aqui:

      * se anade al motor una regla que lee `node.get("nuevo_campo")` y nadie lo
        declara -> el campo no se proyecta y la barrera se apaga;
      * se BORRA una dimension del registro mientras el motor la sigue leyendo
        -> la lista derivada se acorta sola y, sin este test, no pasaria nada.

    Este test miraba SOLO `can_view`, y por eso no vio que `known_by_of` --en
    `policies/models.py`-- leia `known_by_characters`. La red anti-reincidencia
    contenia viva una reincidencia. Ahora barre los dos modulos enteros y
    tambien las lecturas sobre aristas (`edge.get`), que antes no miraba.
    """
    fuente = _fuente_de_politica()
    leidos = set(re.findall(r'(?:node|edge|rel)\.get\(\s*["\']([a-z_]+)["\']', fuente))
    leidos -= _ESTRUCTURALES
    faltan = leidos - set(CAMPOS_AUTORIZACION_NODO)
    assert not faltan, (
        f"el motor consulta {sorted(faltan)} y el registro ejecutable NO lo "
        f"declara como dimension proyectada. O se declara en "
        f"app/policies/registry.py (con productor, semantica de ausencia y "
        f"prueba negativa) o el motor deja de consultarlo: una barrera que se "
        f"evalua sobre un campo que nadie declara ni proyecta es decorativa."
    )


def test_ninguna_dimension_del_contexto_que_el_motor_consulta_queda_sin_declarar():
    """El agujero que la red anterior NO miraba: el CONTEXTO.

    La red inversa original buscaba `node.get("...")` y nada mas. El motor toma
    la mitad de sus decisiones leyendo ATRIBUTOS del contexto (`ctx.admin_full`,
    `ctx.can_view_secret`, ...), asi que era estructuralmente incapaz de ver
    ninguna dimension de contexto sin declarar. Y ese era exactamente el fallo
    que el docstring del registro pone como H-A: una dimension con columna,
    lector y pruebas, y ningun escritor, que la primera red no habria detectado
    "porque solo miraba campos de nodo".

    Las dimensiones se derivan de los campos del propio `ViewerContext`, no de
    una lista: un campo nuevo entra en el barrido el dia que se anade.
    """
    fuente = _fuente_de_politica()
    campos_ctx = {f.name for f in dataclasses.fields(ViewerContext)}
    consumidas = {c for c in campos_ctx if re.search(rf"(?:ctx|self)\.{c}\b", fuente)}
    assert consumidas, "el barrido de dimensiones de contexto no encuentra ninguna"

    sin_declarar = consumidas - set(DIMENSIONES_DEL_CONTEXTO)
    nuevas = sin_declarar - CONTEXTO_SIN_DECLARAR_EN_EL_REGISTRO
    assert not nuevas, (
        f"el motor decide con {sorted(nuevas)} y el registro ejecutable no las "
        f"declara: sin cadena declarada no hay autoridad, ni productor, ni "
        f"respuesta a 'y si falta'"
    )

    # La cuarentena solo puede encoger. Si una dimension se declara por fin en
    # el registro, hay que sacarla de aqui en el mismo cambio; si no, la
    # cuarentena se vuelve un vertedero que nadie vacia.
    resueltas = CONTEXTO_SIN_DECLARAR_EN_EL_REGISTRO - sin_declarar
    assert not resueltas, (
        f"{sorted(resueltas)} ya estan declaradas en el registro (o el motor "
        f"dejo de consumirlas): quitalas de "
        f"CONTEXTO_SIN_DECLARAR_EN_EL_REGISTRO"
    )


def test_las_dimensiones_retiradas_no_vuelven_por_la_puerta_de_atras():
    """`party`, `is_public` y `session_index` estan RETIRADAS en el registro.

    Retirarlas fue T1/T2: eran reglas que se evaluaban sobre campos que ningun
    escritor producia. El registro las nombra para que no vuelvan; aqui se
    comprueba que efectivamente no han vuelto, ni al motor ni a la proyeccion
    declarada.
    """
    fuente = _fuente_de_politica()
    proyectadas = set(CAMPOS_AUTORIZACION_NODO) | set(CAMPOS_AUTORIZACION_RELACION)
    for nombre, motivo in RETIRADAS.items():
        assert nombre not in proyectadas, (
            f"'{nombre}' esta declarada como RETIRADA y ha vuelto a la "
            f"proyeccion de autorizacion. Motivo de la retirada: {motivo}"
        )
        vuelto = re.search(
            rf'(?:node|edge|rel)\.get\(\s*["\']{nombre}["\']', fuente
        ) or re.search(rf"(?:ctx|self)\.{nombre}\b", fuente)
        assert not vuelto, (
            f"el motor ha vuelto a consultar '{nombre}', retirada por: {motivo}"
        )
