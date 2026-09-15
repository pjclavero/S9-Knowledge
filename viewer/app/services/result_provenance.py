# -*- coding: utf-8 -*-
"""RESULTADO de una ejecucion y su PROCEDENCIA, de solo lectura.

LA PREGUNTA QUE CONTESTA
------------------------
Hoy el operador no puede responder desde la interfaz "¿que cambio esta
ejecucion y de donde salio?". Lo medido en ``main`` antes de este modulo:

* ``/panel/sources`` pinta una columna "Procedencia" que es ``source_kind``
  --EXTRACCION, otro vocabulario-- y que sale "no disponible" cuando falta;
* la procedencia del APPLY (``V3Source``/``V3Episode``/``V3Evidence``, que el
  writer SI persiste desde ``apply_v3``) no tiene ninguna superficie: el unico
  consumidor de ``apply_id`` en ``viewer/`` era un fichero de tests.

Este modulo compone el recorrido entero con identidades DURABLES:

    apply_id -> V3AppliedOperation -> idempotency_key
             -> entidades y relaciones escritas
             -> V3Assertion -[SUPPORTED_BY]-> V3Evidence (fragmento LITERAL)
             -> V3Episode (localizador) -> V3Source (fuente)

DONDE SE DECIDE LA AUTORIZACION, Y DONDE NO
-------------------------------------------
**Aqui no se escribe ni una regla de visibilidad.** La unica autoridad es
``PolicyFilteredProvider`` --el mismo que sirve ``/entities`` y
``/panel/entities``--, y se le consulta por IDENTIDAD DURABLE:

* una entidad entra en el resultado si y solo si ``provider.entity(id)`` la
  devuelve (``None`` = no existe O no es visible, indistinguibles a proposito);
* una relacion entra si y solo si aparece en
  ``provider.relations_for_entity(sujeto)``, que ya exige que la arista y el
  otro extremo sean visibles;
* **la evidencia de una asercion entra si y solo si TODOS sus extremos de
  entidad son visibles para este lector.**

Esa ultima linea ES la politica de procedencia, hecha ejecutable: ver una
assertion no da acceso a toda su fuente, sino AL FRAGMENTO QUE LA SOSTIENE.
Por eso ``ProvenanceReader.fragments_supporting`` recorre ``SUPPORTED_BY`` y
para, y por eso la lista blanca del episodio no incluye su ``text``.

NO SE CREA NINGUNA ACL NUEVA. Los nodos de procedencia siguen escribiendose
SIN ``visibility`` y SIN ``known_by`` --son fail-closed a proposito y siguen
sin llevar la etiqueta publica ``:Entity``, invariante que afirman
``test_contrato_writer_a_visor_neo4j`` y ``test_integracion_tanda11``--. No se
alcanzan por politica propia: se alcanzan por la de la entidad que ya podias
ver, o no se alcanzan.

FILTRAR EN LA PLANTILLA NO ES FILTRAR
-------------------------------------
Todo lo que este modulo no autoriza NO SE DEVUELVE. Las plantillas pintan lo
que reciben; no ocultan nada. Un filtro que solo viva en el frontend es una
fuga con una hoja de estilo delante.

AUSENCIA != CERO
----------------
Cada bloque del resultado lleva su propio ESTADO explicito
(``DISPONIBLE``/``VACIO``/``SIN_PROCEDENCIA``/``ERROR``). Una seccion que no se pudo leer no
publica un ``0``: publica ``ERROR`` y ni una cifra. Y cuando lo que falta es
la DEPENDENCIA entera --no una seccion-- no hay pagina: hay un **503** con
codigo estable, porque una pantalla llena de huecos no es una respuesta
honesta y un **404** mandaria a quien mira a buscar un identificador que si
era bueno.

Es la misma doctrina que el Corte 4 fijo para el almacen de propuestas
(``services/v3_review.py``: codigo estable, ``CODIGO: frase`` en el
``detail``, 503 para la dependencia ausente), aplicada aqui desde el
principio. El catalogo de codigos es PROPIO --ver mas abajo por que-- y
unificar los dos es deuda declarada, no tarea de este carril.

CERO ESCRITURAS. Ni un ``CREATE``, ni un ``MERGE``, ni un ``SET``. Ninguna
funcion de aqui abre una transaccion de escritura y ninguna ruta que la use
acepta un metodo que no sea ``GET``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.providers.provenance_reader import ProvenanceReader

__all__ = [
    "DISPONIBLE", "VACIO", "SIN_PROCEDENCIA", "ERROR", "ESTADOS",
    "Bloque", "Resultado", "DetalleEvidencia", "ProcedenciaNoDisponible",
    "CODIGOS", "detalle_seguro",
    "RESULT_NOT_FOUND", "PROVENANCE_READER_UNAVAILABLE",
    "resultado_de_apply", "detalle_de_asercion", "es_apply_id",
]

# --------------------------------------------------------------------------
# Codigos estables + frase accionable, la forma que fijo el Corte 1
# --------------------------------------------------------------------------
# Misma doctrina que `app/panel_errors.py` y que el Corte 4: el CODIGO es API
# --estable, buscable, correlacionable con el log-- y la FRASE es para una
# persona. Nunca sale `str(exc)`, nunca sale el nombre de la clase de la
# excepcion y nunca sale una ruta del servidor: este repositorio es PUBLICO y
# ya tuvo un incidente por topologia interna.
#
# El catalogo es PROPIO y no se anade al de `panel_errors`: aquel declara su
# alcance --"el CAMINO NUEVO del Corte 1"-- y ampliarlo desde aqui seria
# apropiarse de una superficie ajena. Unificar los dos catalogos es deuda
# declarada, no una tarea de este carril.

#: No hay ningun resultado con ese identificador para este lector. Cubre a la
#: vez "no existe", "no es tuyo" y "el identificador esta mal formado": los
#: tres dan el MISMO codigo y la MISMA frase, que es lo que impide usar la
#: pantalla como oraculo de existencia.
RESULT_NOT_FOUND = "RESULT_NOT_FOUND"

#: Este despliegue no puede leer la procedencia. NO es "no hay procedencia", y
#: no se degrada a una pantalla vacia: es indisponibilidad de una DEPENDENCIA,
#: y el desenlace correcto es 503 --la dependencia caida no es culpa de quien
#: mira--. Misma resolucion que tomo el Corte 4 para el almacen de propuestas.
PROVENANCE_READER_UNAVAILABLE = "PROVENANCE_READER_UNAVAILABLE"

CODIGOS: dict[str, str] = {
    RESULT_NOT_FOUND:
        "No hay ningun resultado con ese identificador.",
    PROVENANCE_READER_UNAVAILABLE:
        "Este despliegue no puede consultar la procedencia, asi que no se "
        "sabe que cambio esta ejecucion. Avisa a quien administra el servicio.",
}


def detalle_seguro(code: str) -> str:
    """`CODIGO: frase`, y nada mas. FALLA RUIDOSAMENTE si el codigo no existe.

    Un codigo inventado no se degrada a un mensaje generico: eso convertiria
    una errata en un mensaje mudo en produccion.
    """
    return f"{code}: {CODIGOS[code]}"


class ProcedenciaNoDisponible(RuntimeError):
    """La dependencia de procedencia no esta. La ruta lo traduce a 503.

    No lleva --ni puede llevar-- ningun campo con detalle tecnico: si no existe
    el sitio donde meter la ruta del servidor, nadie la mete "solo esta vez".
    """

    code = PROVENANCE_READER_UNAVAILABLE

#: Hay MATERIAL y se pinta.
DISPONIBLE = "DISPONIBLE"
#: La lectura FUE BIEN y no habia nada. Un cero MEDIDO.
VACIO = "VACIO"
#: Esta EJECUCION no persistio procedencia (el apply fue SIN
#: `ProvenanceBundle`). NO es "este hecho no tiene evidencia": es una carencia
#: de la ejecucion entera, y el operador tiene que poder distinguirlas.
#: Se DERIVA del grafo --ninguna asercion del apply tiene `SUPPORTED_BY`--,
#: no de un informe que esta pantalla no lee.
SIN_PROCEDENCIA = "SIN_PROCEDENCIA"
#: La lectura de ESA seccion FALLO. Tampoco es un cero, y no publica cifras.
#:
#: No hay un estado "no disponible": cuando lo que falta es la
#: dependencia entera, la respuesta es un 503 con codigo estable y no una
#: pagina. Un estado sin productor es vocabulario muerto, y el vocabulario
#: muerto acaba usandose para otra cosa.
ERROR = "ERROR"

ESTADOS: tuple[str, ...] = (DISPONIBLE, VACIO, SIN_PROCEDENCIA, ERROR)

#: Forma admisible de un `apply_id` (``writer/apply_identity.py``). Se
#: comprueba ANTES de tocar la base: una cadena arbitraria en la URL no llega a
#: convertirse en un parametro de consulta.
_APPLY_PREFIX = "apply:"
_APPLY_DIGEST = 32


def es_apply_id(valor: Any) -> bool:
    """¿Tiene forma de ``apply_id``? Se comprueba, no se presume."""
    if not isinstance(valor, str) or not valor.startswith(_APPLY_PREFIX):
        return False
    resto = valor[len(_APPLY_PREFIX):]
    return len(resto) == _APPLY_DIGEST and all(
        c in "0123456789abcdef" for c in resto
    )


@dataclass
class Bloque:
    """Una seccion del resultado, CON SU ESTADO. Nunca una lista pelada.

    ``filas`` solo tiene sentido en ``DISPONIBLE`` y ``VACIO``. En
    ``ERROR`` se queda vacia y ``total`` vale ``None``: una
    seccion que no se pudo leer no publica un recuento, porque un ``0`` ahi es
    una afirmacion que nadie ha medido.
    """

    estado: str
    filas: list = field(default_factory=list)
    total: Optional[int] = None

    @classmethod
    def leido(cls, filas: list) -> "Bloque":
        filas = list(filas)
        return cls(estado=DISPONIBLE if filas else VACIO, filas=filas, total=len(filas))

    @classmethod
    def sin_procedencia(cls) -> "Bloque":
        """La EJECUCION no dejo procedencia. Cero MEDIDO, y de otra cosa.

        Lleva cifra ``0`` --se ha medido: no hay ni un soporte en todo el
        apply-- pero con su propio estado, porque la frase que merece el
        operador no es "este hecho no tiene evidencia".
        """
        return cls(estado=SIN_PROCEDENCIA, filas=[], total=0)

    @classmethod
    def con_error(cls) -> "Bloque":
        return cls(estado=ERROR, filas=[], total=None)

    @property
    def hay_cifra(self) -> bool:
        return self.total is not None


@dataclass
class Resultado:
    """Lo que ESA ejecucion cambio, ya autorizado."""

    apply_id: str
    workspace: str
    ownership_id: Optional[str]
    partida_id: Optional[str]
    aplicado_en: Optional[str]
    operaciones: int
    entidades: Bloque
    relaciones: Bloque
    hechos: Bloque


@dataclass
class DetalleEvidencia:
    """Un hecho de ese apply y la evidencia LITERAL que lo sostiene."""

    apply_id: str
    workspace: str
    assertion_id: str
    predicate: Optional[str]
    sujeto: dict
    objeto: Optional[dict]
    evidencias: Bloque


# --------------------------------------------------------------------------
# Autorizacion: una sola puerta, y es la que ya existia
# --------------------------------------------------------------------------
def _entidad_visible(provider: Any, entity_id: Optional[str]) -> Optional[dict]:
    """La entidad si este lector puede verla; ``None`` en cualquier otro caso.

    ``None`` cubre a la vez "no existe", "no es visible" y "el proveedor no
    supo resolverla": los tres son el MISMO resultado hacia fuera, que es lo
    que impide usar esta funcion para sondear existencia.
    """
    if not entity_id:
        return None
    try:
        return provider.entity(entity_id)
    except Exception:  # noqa: BLE001 - un extremo ilegible es un extremo ausente
        return None


def _ficha(nodo: dict) -> dict:
    """Lo minimo para nombrar una entidad en pantalla, por identidad durable."""
    # Las claves son las de `_node_to_dict`: `id`/`entity_id` son el MISMO
    # identificador de dominio (nunca el `elementId`, que ese proyector no
    # publica) y el tipo viaja en `type`. Un nodo sin identidad durable sale
    # con `entity_id=None` y la ficha NO es direccionable: se prefiere eso a
    # regalarle un identificador fisico que se rompe en el primer restore.
    return {
        "entity_id": nodo.get("id") or nodo.get("entity_id"),
        "nombre": nodo.get("label") or "",
        "tipo": nodo.get("type") or "",
    }


def _workspace_autorizado(provider: Any, workspace: str) -> bool:
    """¿Puede este lector mirar ese workspace? Lo dice el proveedor FILTRADO.

    No hay aqui ninguna lista de workspaces propia: ``workspaces()`` del
    proveedor filtrado ya devuelve la interseccion con los permitidos (y todos
    para ``admin_full``). Una segunda lista seria una segunda politica.
    """
    try:
        return workspace in set(provider.workspaces() or ())
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------
# 1. El resultado de una ejecucion
# --------------------------------------------------------------------------
def resultado_de_apply(
    *,
    provider: Any,
    reader: Optional[ProvenanceReader],
    workspace: str,
    apply_id: str,
) -> Optional[Resultado]:
    """El resultado AUTORIZADO de ``apply_id``, o ``None`` si no procede.

    ``None`` significa "no hay nada que ensenarte de ese apply": forma invalida
    del identificador, workspace fuera de tu alcance, o ningun apply con ese
    identificador en el. Los tres dan el MISMO ``None`` y la ruta el MISMO 404,
    para que la pantalla no sirva de oraculo de existencia.

    ``reader`` a ``None`` NO devuelve ``None``: levanta
    ``ProcedenciaNoDisponible``, que la ruta traduce a **503**. "Este despliegue
    no lee procedencia" y "ese apply no existe" son cosas distintas, y un 404
    ahi haria perder el tiempo a quien mira buscando un identificador que si
    era bueno. La dependencia caida no es culpa del lector.

    El ORDEN importa y no es cosmetico: la forma del identificador y el ambito
    se comprueban ANTES que la dependencia. Al reves, un lector sin derechos
    sobre un workspace podria distinguir "ese workspace existe" de "no existe"
    comparando 503 contra 404.
    """
    if not es_apply_id(apply_id):
        return None
    if not _workspace_autorizado(provider, workspace):
        return None

    if reader is None:
        raise ProcedenciaNoDisponible(PROVENANCE_READER_UNAVAILABLE)

    try:
        operaciones = reader.operations_of_apply(workspace, apply_id)
    except Exception:  # noqa: BLE001
        return Resultado(
            apply_id=apply_id, workspace=workspace, ownership_id=None,
            partida_id=None, aplicado_en=None, operaciones=0,
            entidades=Bloque.con_error(),
            relaciones=Bloque.con_error(),
            hechos=Bloque.con_error(),
        )

    if not operaciones:
        # Ese apply no dejo marca en ESTE workspace. No existe para este
        # lector, y eso es un 404, no un resultado vacio: un resultado vacio
        # afirmaria que el apply existe y no cambio nada.
        return None

    claves = [o["idempotency_key"] for o in operaciones if o.get("idempotency_key")]
    primera = operaciones[0]

    return Resultado(
        apply_id=apply_id,
        workspace=workspace,
        ownership_id=primera.get("ownership_id"),
        partida_id=primera.get("partida_id"),
        aplicado_en=min(
            (o["applied_at"] for o in operaciones if o.get("applied_at")),
            default=None,
        ),
        operaciones=len(operaciones),
        entidades=_bloque_entidades(provider, reader, workspace, claves),
        relaciones=_bloque_relaciones(provider, reader, workspace, claves),
        hechos=_bloque_hechos(provider, reader, workspace, claves),
    )


def _bloque_entidades(provider, reader, workspace, claves) -> Bloque:
    """Entidades de ese apply que este lector PUEDE ver.

    Los ``entity_id`` crudos se piden al lector, pero ni uno solo llega a la
    salida sin pasar por ``provider.entity``: el lector aporta la ATRIBUCION
    (que entidades son de este apply) y el proveedor filtrado aporta el
    PERMISO. Las dos cosas tienen que concurrir.
    """
    try:
        crudos = reader.entity_ids_for_keys(workspace, claves)
    except Exception:  # noqa: BLE001
        return Bloque.con_error()
    filas = []
    for entity_id in crudos:
        nodo = _entidad_visible(provider, entity_id)
        if nodo is not None:
            filas.append(_ficha(nodo))
    return Bloque.leido(filas)


def _bloque_relaciones(provider, reader, workspace, claves) -> Bloque:
    """Relaciones de ese apply que este lector PUEDE ver.

    No se filtra la arista aqui. Se le pregunta a
    ``provider.relations_for_entity(sujeto)`` --que ya exige arista visible Y
    otro extremo visible-- y se CRUZA con las aristas que el lector atribuye a
    este apply. El cruce es por la terna durable ``(from, to, type)``: la
    arista V3 no tiene identidad durable propia y su ``elementId`` es fisico,
    de un solo viaje, y no se usa para nada aqui.
    """
    try:
        atribuidas = reader.relation_edges_for_keys(workspace, claves)
    except Exception:  # noqa: BLE001
        return Bloque.con_error()

    esperadas = {(e["from_id"], e["to_id"], e["type"]) for e in atribuidas}
    filas = []
    vistos = set()
    for sujeto in sorted({e["from_id"] for e in atribuidas}):
        nodo = _entidad_visible(provider, sujeto)
        if nodo is None:
            continue  # el sujeto no es visible -> su arista tampoco sale
        try:
            salientes, _entrantes = provider.relations_for_entity(sujeto)
        except Exception:  # noqa: BLE001
            return Bloque.con_error()
        for arista in salientes:
            terna = (arista.get("from"), arista.get("to"), arista.get("type"))
            if terna not in esperadas or terna in vistos:
                continue
            otro = _entidad_visible(provider, arista.get("to"))
            if otro is None:
                continue
            vistos.add(terna)
            filas.append({
                "tipo": arista.get("type"),
                "etiqueta": arista.get("label") or arista.get("type"),
                "desde": _ficha(nodo),
                "hasta": _ficha(otro),
            })
    return Bloque.leido(filas)


def _bloque_hechos(provider, reader, workspace, claves) -> Bloque:
    """Hechos (``V3Assertion``) de ese apply cuyos EXTREMOS puede ver el lector.

    Esta es la puerta de la evidencia. Un hecho solo aparece --y solo por el
    aparece luego su fragmento literal-- si TODAS las entidades que nombra son
    visibles para quien mira. Si el objeto existe pero no es visible, el hecho
    NO sale: entregarlo permitiria deducir con quien se relaciona algo que no
    se puede ver.
    """
    try:
        aserciones = reader.assertions_for_keys(workspace, claves)
    except Exception:  # noqa: BLE001
        return Bloque.con_error()
    filas = []
    for a in aserciones:
        sujeto = _entidad_visible(provider, a.get("subject_entity_id"))
        if sujeto is None:
            continue
        objeto = None
        if a.get("object_entity_id"):
            objeto = _entidad_visible(provider, a["object_entity_id"])
            if objeto is None:
                continue
        filas.append({
            "assertion_id": a.get("assertion_id"),
            "predicate": a.get("predicate"),
            "sujeto": _ficha(sujeto),
            "objeto": _ficha(objeto) if objeto else None,
        })
    return Bloque.leido(filas)


# --------------------------------------------------------------------------
# 2. La procedencia de UN hecho de ESE apply
# --------------------------------------------------------------------------
def detalle_de_asercion(
    *,
    provider: Any,
    reader: Optional[ProvenanceReader],
    workspace: str,
    apply_id: str,
    assertion_id: str,
) -> Optional[DetalleEvidencia]:
    """El hecho y la evidencia LITERAL que lo sostiene, o ``None``.

    Tres condiciones, y las tres se comprueban, ninguna se presume:

    1. ``assertion_id`` pertenece a ``apply_id`` --se busca entre las claves de
       ESE apply, no en todo el grafo--. Sin esto, la pantalla de un apply
       ensenaria la evidencia de otro: ATRIBUCION CRUZADA.
    2. el workspace esta autorizado para este lector;
    3. los extremos de entidad del hecho son visibles para este lector.

    ``reader`` a ``None`` levanta ``ProcedenciaNoDisponible`` -> **503**, igual
    que en ``resultado_de_apply`` y por la misma razon: un 404 diria "ese hecho
    no existe", que es una afirmacion que nadie ha comprobado.
    """
    if not es_apply_id(apply_id) or not assertion_id:
        return None
    if not _workspace_autorizado(provider, workspace):
        return None
    if reader is None:
        raise ProcedenciaNoDisponible(PROVENANCE_READER_UNAVAILABLE)

    try:
        operaciones = reader.operations_of_apply(workspace, apply_id)
        claves = [o["idempotency_key"] for o in operaciones if o.get("idempotency_key")]
        aserciones = reader.assertions_for_keys(workspace, claves) if claves else []
    except Exception:  # noqa: BLE001
        return None

    # CONDICION 1: del apply que se esta mirando, y de ningun otro.
    elegida = next((a for a in aserciones if a.get("assertion_id") == assertion_id), None)
    if elegida is None:
        return None

    sujeto = _entidad_visible(provider, elegida.get("subject_entity_id"))
    if sujeto is None:
        return None
    objeto = None
    if elegida.get("object_entity_id"):
        objeto = _entidad_visible(provider, elegida["object_entity_id"])
        if objeto is None:
            return None

    def _ficha_con(bloque: Bloque) -> DetalleEvidencia:
        return DetalleEvidencia(
            apply_id=apply_id, workspace=workspace, assertion_id=assertion_id,
            predicate=elegida.get("predicate"), sujeto=_ficha(sujeto),
            objeto=_ficha(objeto) if objeto else None,
            evidencias=bloque,
        )

    try:
        fragmentos = reader.fragments_supporting(workspace, assertion_id)
    except Exception:  # noqa: BLE001
        return _ficha_con(Bloque.con_error())

    # TRES CEROS QUE SE PARECEN Y NO SON LO MISMO
    # ------------------------------------------
    # Este hecho no tiene fragmentos. Antes de decir "no consta evidencia" hay
    # que saber si es que ESTA EJECUCION no persistio ninguna: `apply_v3`
    # escribe el conocimiento igual cuando le falta el `ProvenanceBundle`, y
    # entonces NINGUNA asercion del apply tiene soporte. Eso es una carencia de
    # la ejecucion, no un dato de este hecho, y se DERIVA del grafo.
    #
    #   1. la ejecucion no dejo procedencia   -> SIN_PROCEDENCIA (aqui)
    #   2. este hecho no tiene evidencia      -> VACIO
    #   3. no puedes ver este hecho           -> None -> 404 (mas arriba)
    #
    # Las tres pintarian una pantalla sin fragmentos. Solo la primera es una
    # carencia del producto que el operador tiene que poder ver como tal.
    if not fragmentos:
        try:
            if not reader.apply_persistio_procedencia(workspace, claves):
                return _ficha_con(Bloque.sin_procedencia())
        except Exception:  # noqa: BLE001
            return _ficha_con(Bloque.con_error())

    filas = []
    for fr in fragmentos:
        # Localizador y fuente se resuelven POR IDENTIDAD DURABLE del propio
        # fragmento, acotados al mismo workspace. Si falta alguno se dice que
        # falta: no se inventa procedencia (requisito 8).
        episodio = None
        if fr.get("episode_id"):
            try:
                episodio = reader.episode(workspace, fr["episode_id"])
            except Exception:  # noqa: BLE001
                episodio = None
        fuente = None
        if fr.get("source_asset_id"):
            try:
                fuente = reader.source(workspace, fr["source_asset_id"])
            except Exception:  # noqa: BLE001
                fuente = None
        filas.append({"fragmento": fr, "episodio": episodio, "fuente": fuente})

    return DetalleEvidencia(
        apply_id=apply_id, workspace=workspace, assertion_id=assertion_id,
        predicate=elegida.get("predicate"), sujeto=_ficha(sujeto),
        objeto=_ficha(objeto) if objeto else None,
        evidencias=Bloque.leido(filas),
    )
