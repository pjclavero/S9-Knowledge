# -*- coding: utf-8 -*-
"""Contrato de la superficie de RESULTADO y PROCEDENCIA. Sin Neo4j.

QUE MIDE ESTE FICHERO Y QUE NO
==============================
Aqui se afirma lo que se puede afirmar SIN base de datos: la forma de las
consultas, la lista blanca de campos, el tri-estado, el orden de las puertas y
--sobre todo-- que la autorizacion la decide el proveedor filtrado y no este
carril. La prueba INSIGNIA, la que parte de un apply REAL contra Neo4j, esta en
``test_resultado_procedencia_neo4j_real.py``: un contrato verde aqui NO
demuestra que el recorrido exista, y por eso las dos suites son necesarias.

El proveedor de estas pruebas es un ESPIA: registra cada llamada. Asi la
afirmacion "ni una fila sale sin pasar por `provider.entity`" se comprueba por
las llamadas OBSERVADAS, no leyendo el codigo.
"""
from __future__ import annotations

import os
import pathlib

import pytest

#: Raiz del repositorio, para exigir que NINGUNA ruta del servidor salga al
#: cliente. Este repositorio es PUBLICO y ya tuvo un incidente por topologia.
RAIZ_REPO = pathlib.Path(__file__).resolve().parents[2]

from app.providers import provenance_reader as lector
from app.services import result_provenance as servicio

WS = "leyenda"
OTRO_WS = "otro-mundo"
APPLY = "apply:" + "a" * 32
OTRO_APPLY = "apply:" + "b" * 32


# ===========================================================================
# Dobles: un lector que devuelve filas fijas y un proveedor que ESPIA
# ===========================================================================
class LectorFalso:
    """Devuelve material fijo. No autoriza nada: ese es justo el punto."""

    def __init__(self, *, operaciones=None, entidades=None, aristas=None,
                 aserciones=None, fragmentos=None, episodio=None, fuente=None,
                 revienta=(), persistio_procedencia=None):
        self._ops = operaciones if operaciones is not None else [
            {"idempotency_key": "k1", "operation_id": "op1",
             "applied_at": "2026-09-15T10:00:00Z", "ownership_id": "own:" + "c" * 32,
             "partida_id": None},
        ]
        self._ent = entidades if entidades is not None else ["entity:daiki"]
        self._ar = aristas if aristas is not None else []
        self._as = aserciones if aserciones is not None else []
        self._fr = fragmentos if fragmentos is not None else []
        self._ep = episodio
        self._fu = fuente
        self._revienta = set(revienta)
        # Por defecto, "el apply SI persistio procedencia": asi un fragmento
        # ausente se lee como hueco de ESE hecho, que es el caso comun.
        self._persistio = (
            bool(self._fr) if persistio_procedencia is None else persistio_procedencia)

    def _quizas(self, nombre):
        if nombre in self._revienta:
            raise RuntimeError("la fuente de datos no respondio")

    def operations_of_apply(self, ws, apply_id):
        self._quizas("operations_of_apply")
        return list(self._ops) if (ws == WS and apply_id == APPLY) else []

    def entity_ids_for_keys(self, ws, keys):
        self._quizas("entity_ids_for_keys")
        return list(self._ent)

    def relation_edges_for_keys(self, ws, keys):
        self._quizas("relation_edges_for_keys")
        return list(self._ar)

    def assertions_for_keys(self, ws, keys):
        self._quizas("assertions_for_keys")
        return list(self._as)

    def apply_persistio_procedencia(self, ws, keys):
        self._quizas("apply_persistio_procedencia")
        return self._persistio

    def fragments_supporting(self, ws, assertion_id):
        self._quizas("fragments_supporting")
        return list(self._fr)

    def episode(self, ws, eid):
        self._quizas("episode")
        return self._ep

    def source(self, ws, sid):
        self._quizas("source")
        return self._fu


class ProveedorEspia:
    """Lo que el `PolicyFilteredProvider` decidiria, y el registro de lo pedido."""

    def __init__(self, visibles=(), workspaces=(WS,), relaciones=None):
        self.visibles = {
            e: {"id": e, "entity_id": e, "label": e.split(":")[-1], "type": "PERSON"}
            for e in visibles
        }
        self._ws = list(workspaces)
        self._rel = relaciones or {}
        self.pedidas: list[str] = []

    def workspaces(self):
        return list(self._ws)

    def entity(self, entity_id, **_):
        self.pedidas.append(entity_id)
        return self.visibles.get(entity_id)

    def relations_for_entity(self, entity_id, **_):
        return (list(self._rel.get(entity_id, [])), [])


def _resultado(lector_falso, proveedor, apply_id=APPLY, ws=WS):
    return servicio.resultado_de_apply(
        provider=proveedor, reader=lector_falso, workspace=ws, apply_id=apply_id
    )


# ===========================================================================
# 1. IDENTIDAD DURABLE -- nunca `elementId`, nunca posicion, nunca ruta
# ===========================================================================
def test_ninguna_consulta_del_lector_menciona_elementid():
    """Enumeracion sobre el TEXTO de las consultas, no sobre la memoria.

    Un `elementId` en una consulta acabaria en una URL publica y se romperia en
    el primer `dump`/`restore`, devolviendo el mismo 404 que un recurso que
    nunca existio: un fallo SILENCIOSO por diseno.
    """
    import inspect

    fuente = inspect.getsource(lector.ProvenanceReader)
    for prohibido in ("elementId(", "element_id", "id(a)", "id(r)", "id(n)"):
        assert prohibido not in fuente, (
            f"El lector de procedencia usa {prohibido!r}: eso es identidad "
            "FISICA, no durable, y cambia con un restore."
        )


@pytest.mark.parametrize("malo", [
    "", "apply:", "apply:zz", "a" * 32, "apply:" + "a" * 31, "apply:" + "A" * 32,
    "apply:" + "g" * 32, "../../etc/passwd", "apply:" + "a" * 33,
])
def test_un_apply_id_malformado_no_llega_a_la_base(malo):
    """La forma se comprueba ANTES de consultar. Se afirma por las llamadas."""
    espia = ProveedorEspia(visibles=["entity:daiki"])
    lec = LectorFalso()
    assert _resultado(lec, espia, apply_id=malo) is None
    assert espia.pedidas == [], (
        "Con un identificador malformado se ha consultado igualmente"
    )


def test_el_apply_id_bien_formado_se_acepta():
    """Control positivo: sin esto, el caso de arriba pasaria por accidente."""
    assert servicio.es_apply_id(APPLY)
    assert _resultado(LectorFalso(), ProveedorEspia(visibles=["entity:daiki"])) is not None


# ===========================================================================
# 2. LA AUTORIZACION LA DECIDE EL PROVEEDOR FILTRADO, Y SE OBSERVA
# ===========================================================================
def test_una_entidad_que_el_proveedor_no_devuelve_no_sale():
    """Control negativo del filtro de visibilidad, sobre llamadas medidas."""
    lec = LectorFalso(entidades=["entity:visible", "entity:oculta"])
    espia = ProveedorEspia(visibles=["entity:visible"])

    res = _resultado(lec, espia)

    ids = [f["entity_id"] for f in res.entidades.filas]
    assert "entity:oculta" not in ids, (
        "Una entidad que el proveedor filtrado NO devuelve ha llegado a la "
        "salida: el backend esta enviando material no autorizado."
    )
    assert ids == ["entity:visible"]
    assert "entity:oculta" in espia.pedidas, (
        "Ni siquiera se le pregunto al proveedor por esa entidad: este caso no "
        "esta midiendo el filtro, esta midiendo que el lector no la trajo."
    )


def test_un_workspace_fuera_de_alcance_no_consulta_nada():
    """FUGA DE AMBITO. El workspace se comprueba ANTES de mirar nada.

    El proveedor filtrado declara que este lector solo alcanza ``OTRO_WS``; se
    pide ``WS``. El orden de las aserciones es deliberado: la primera es la que
    EXPLICA el defecto --que haya salido material de un ambito ajeno-- y no el
    ``is None`` pelado, cuyo mensaje de fallo es un volcado ilegible que no
    dice en que capa se rompio.
    """
    espia = ProveedorEspia(visibles=["entity:daiki"], workspaces=[OTRO_WS])

    res = _resultado(LectorFalso(), espia)

    entregado = [] if res is None else [f["entity_id"] for f in res.entidades.filas]
    assert not entregado, (
        f"se ha entregado material del workspace {WS!r}, que NO esta en los "
        f"alcanzables por este lector ({[OTRO_WS]}): {entregado}. FUGA DE AMBITO."
    )
    assert espia.pedidas == [], (
        f"se ha consultado el grafo por {espia.pedidas} pese a que el "
        "workspace no esta autorizado: la comprobacion de ambito llega TARDE."
    )
    assert res is None, (
        "el ambito ajeno no da 404: la pantalla sirve para saber si un apply "
        "existe en un workspace que no es tuyo."
    )


def test_un_hecho_con_un_extremo_invisible_no_entrega_su_evidencia():
    """LA PUERTA DE LA EVIDENCIA, que es la politica de procedencia entera.

    El sujeto SI es visible. El objeto NO. Si el hecho saliera, quien mira
    podria deducir con que se relaciona algo que no puede ver -- y de ahi
    colgaria el fragmento literal de la fuente.
    """
    lec = LectorFalso(aserciones=[{
        "assertion_id": "assertion:1", "subject_entity_id": "entity:visible",
        "object_entity_id": "entity:oculta", "predicate": "JURO_LEALTAD",
        "idempotency_key": "k1",
    }])
    espia = ProveedorEspia(visibles=["entity:visible"])

    res = _resultado(lec, espia)
    assert res.hechos.filas == [], (
        "Un hecho con un extremo NO visible ha salido: por ese hecho se llega "
        "al fragmento literal, asi que esto es una fuga de evidencia."
    )

    detalle = servicio.detalle_de_asercion(
        provider=espia, reader=lec, workspace=WS,
        apply_id=APPLY, assertion_id="assertion:1",
    )
    assert detalle is None, (
        "La ficha de procedencia se sirve para un hecho cuyo objeto no es "
        "visible: el filtro de la lista no cubre la ficha directa."
    )


def test_un_hecho_con_los_dos_extremos_visibles_SI_entrega_su_evidencia():
    """Control positivo. Sin el, el caso anterior seria verde por vacio."""
    lec = LectorFalso(
        aserciones=[{
            "assertion_id": "assertion:1", "subject_entity_id": "entity:a",
            "object_entity_id": "entity:b", "predicate": "JURO_LEALTAD",
            "idempotency_key": "k1",
        }],
        fragmentos=[{c: None for c in lector.CAMPOS_FRAGMENTO} | {
            "fragment_id": "fragment:p1:0", "literal_text": "jamas juro lealtad",
            "episode_id": "episode:1", "source_asset_id": "asset:1", "page": 12,
        }],
        episodio={"episode_id": "episode:1", "page": 12, "sequence": 12,
                  "modality": "TEXT", "source_asset_id": "asset:1"},
        fuente={c: None for c in lector.CAMPOS_FUENTE} | {
            "source_asset_id": "asset:1", "original_name": "nota.md"},
    )
    espia = ProveedorEspia(visibles=["entity:a", "entity:b"])

    res = _resultado(lec, espia)
    assert [h["assertion_id"] for h in res.hechos.filas] == ["assertion:1"]

    detalle = servicio.detalle_de_asercion(
        provider=espia, reader=lec, workspace=WS,
        apply_id=APPLY, assertion_id="assertion:1",
    )
    assert detalle is not None
    assert detalle.evidencias.estado == servicio.DISPONIBLE
    assert detalle.evidencias.filas[0]["fragmento"]["literal_text"] == "jamas juro lealtad"


# ===========================================================================
# 3. ATRIBUCION CRUZADA -- la evidencia de un apply no sale por la URL de otro
# ===========================================================================
def test_un_hecho_de_otro_apply_no_se_sirve_bajo_este_apply_id():
    """El `apply_id` de la URL no es decorativo: acota el conjunto.

    El lector NO conoce ese apply (devuelve cero operaciones), asi que no hay
    claves, asi que no hay aserciones. Si la ficha se sirviera igual, la
    pantalla de una ejecucion ensenaria el resultado de otra.
    """
    lec = LectorFalso(aserciones=[{
        "assertion_id": "assertion:1", "subject_entity_id": "entity:a",
        "object_entity_id": None, "predicate": "P", "idempotency_key": "k1",
    }])
    espia = ProveedorEspia(visibles=["entity:a"])

    detalle = servicio.detalle_de_asercion(
        provider=espia, reader=lec, workspace=WS,
        apply_id=OTRO_APPLY, assertion_id="assertion:1",
    )
    assert detalle is None, (
        "Se ha servido la procedencia de un hecho bajo el identificador de un "
        "apply que no lo produjo: ATRIBUCION CRUZADA."
    )
    # ...y bajo el suyo SI, o el caso de arriba seria verde por vacio.
    assert servicio.detalle_de_asercion(
        provider=espia, reader=lec, workspace=WS,
        apply_id=APPLY, assertion_id="assertion:1") is not None


# ===========================================================================
# 4. LISTA BLANCA -- lo que no puede salir, por ENUMERACION
# ===========================================================================
@pytest.mark.parametrize("blanca", [
    lector.CAMPOS_FUENTE, lector.CAMPOS_EPISODIO, lector.CAMPOS_FRAGMENTO])
def test_ninguna_lista_blanca_contiene_un_campo_prohibido(blanca):
    """`original_location` es una ruta del servidor y `text` es la fuente
    entera. Ni uno ni otro pueden viajar a un navegador."""
    colados = set(blanca) & lector.CAMPOS_PROHIBIDOS
    assert not colados, f"Campos prohibidos en una lista blanca: {sorted(colados)}"


def test_el_texto_completo_del_episodio_no_esta_en_la_lista_blanca():
    """La politica, dicha como una ausencia COMPROBADA y no como una promesa.

    El episodio entero no es "el fragmento que sostiene el hecho". Que su
    `text` no se pida es lo que impide que ver un hecho entregue el pasaje
    completo del que salio.
    """
    assert "text" not in lector.CAMPOS_EPISODIO
    assert "text" in lector.CAMPOS_PROHIBIDOS


def test_la_consulta_del_episodio_no_selecciona_el_texto():
    """No basta con la constante: se comprueba la CONSULTA que se emitiria.

    Una lista blanca correcta y una consulta que pide `ep.text` aparte darian
    verde arriba y fuga aqui.
    """
    emitidas = []

    class DriverEspia:
        def session(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def run(self, q, params=None):
            emitidas.append(q)
            return []

    lec = lector.ProvenanceReader(DriverEspia())
    lec.episode(WS, "episode:1")
    lec.source(WS, "asset:1")
    lec.fragments_supporting(WS, "assertion:1")

    assert emitidas, "El espia no capturo ni una consulta: no mide nada"
    for q in emitidas:
        assert "ep.text" not in q and "src.original_location" not in q, (
            f"La consulta pide un campo prohibido: {q}"
        )


def test_el_recorrido_de_evidencia_no_baja_a_los_hermanos_del_episodio():
    """`SUPPORTED_BY` y para. Subir al episodio para bajar a sus fragmentos
    entregaria la fuente entera a quien solo puede ver un hecho."""
    import inspect

    fuente = inspect.getsource(lector.ProvenanceReader.fragments_supporting)
    assert "SUPPORTED_BY" in fuente
    assert "HAS_FRAGMENT" not in fuente, (
        "La consulta de evidencia recorre HAS_FRAGMENT: eso alcanza a los "
        "fragmentos HERMANOS, que este hecho no sostiene."
    )


# ===========================================================================
# 5. AUSENCIA != CERO
# ===========================================================================
def test_sin_lector_se_levanta_indisponibilidad_y_no_un_vacio():
    """"Este despliegue no lee procedencia" NO es "no hay procedencia".

    Y tampoco es "no existe": devolver `None` --que la ruta traduce a 404--
    mandaria a quien mira a buscar un identificador que SI era bueno. Es
    indisponibilidad de una dependencia, y sale por su propia puerta.
    """
    with pytest.raises(servicio.ProcedenciaNoDisponible) as exc:
        servicio.resultado_de_apply(
            provider=ProveedorEspia(visibles=[]), reader=None,
            workspace=WS, apply_id=APPLY,
        )
    assert exc.value.code == servicio.PROVENANCE_READER_UNAVAILABLE


def test_el_orden_es_forma_ambito_y_LUEGO_dependencia():
    """Un ambito ajeno da 404 AUNQUE la dependencia tampoco este.

    Si la dependencia se comprobara antes, un lector sin derechos distinguiria
    "ese workspace existe" de "no existe" comparando 503 contra 404.
    """
    espia = ProveedorEspia(visibles=[], workspaces=[OTRO_WS])
    assert servicio.resultado_de_apply(
        provider=espia, reader=None, workspace=WS, apply_id=APPLY) is None
    assert servicio.resultado_de_apply(
        provider=espia, reader=None, workspace=WS, apply_id="mal-formado") is None


def test_un_bloque_que_no_se_pudo_leer_no_publica_cifra():
    """El tri-estado DENTRO de la pagina: fallo parcial, no de la dependencia.

    Aqui la pagina SI existe --las operaciones se leyeron-- y lo que falla es
    una seccion. Ese es el caso en que `ERROR` vive en la pantalla en vez de
    en el codigo de estado.
    """
    for bloque in (servicio.Bloque.con_error(),):
        assert bloque.total is None, (
            "Un bloque que no se pudo leer publica un recuento: ese 0 no lo ha "
            "medido nadie."
        )
        assert bloque.hay_cifra is False
        assert bloque.filas == []


@pytest.mark.parametrize("revienta", [
    "entity_ids_for_keys", "relation_edges_for_keys", "assertions_for_keys"])
def test_un_fallo_de_lectura_da_ERROR_y_no_un_cero(revienta):
    """ERROR y VACIO son estados distintos. Confundirlos es el defecto exacto
    que el Carril A acaba de cerrar en otra pantalla."""
    lec = LectorFalso(revienta=[revienta])
    res = _resultado(lec, ProveedorEspia(visibles=["entity:daiki"]))
    bloques = {"entity_ids_for_keys": res.entidades,
               "relation_edges_for_keys": res.relaciones,
               "assertions_for_keys": res.hechos}
    afectado = bloques[revienta]
    assert afectado.estado == servicio.ERROR
    assert afectado.total is None


def test_un_apply_sin_material_visible_dice_VACIO_con_cifra_medida():
    """El cero que SI se ha medido lleva su cifra: es una medida, no un hueco."""
    res = _resultado(LectorFalso(entidades=[]), ProveedorEspia(visibles=[]))
    assert res.entidades.estado == servicio.VACIO
    assert res.entidades.total == 0


def test_un_apply_inexistente_es_404_y_no_un_resultado_vacio():
    """Un resultado vacio AFIRMARIA que el apply existe y no cambio nada."""
    assert _resultado(LectorFalso(), ProveedorEspia(visibles=[]),
                      apply_id=OTRO_APPLY) is None


def test_no_hay_ningun_estado_sin_productor():
    """Cada estado del vocabulario lo PRODUCE alguien. Se comprueba, no se cree.

    Un estado declarado que nadie emite es vocabulario muerto, y el vocabulario
    muerto acaba usandose para otra cosa. Aqui se exige que los tres salgan de
    una llamada real, no de la lista.
    """
    producidos = {
        servicio.Bloque.leido([{"x": 1}]).estado,
        servicio.Bloque.leido([]).estado,
        servicio.Bloque.sin_procedencia().estado,
        servicio.Bloque.con_error().estado,
    }
    assert producidos == set(servicio.ESTADOS), (
        f"estados declarados {set(servicio.ESTADOS)} != producidos {producidos}"
    )
    assert len(set(servicio.ESTADOS)) == len(servicio.ESTADOS)


# ===========================================================================
# 6. LA SUPERFICIE: solo GET, apagada por defecto, 404 indistinguible
# ===========================================================================
@pytest.fixture
def app_real():
    from app.main import app
    return app


def _rutas_del_prefijo(app):
    from app.chassis import iter_mounted_routes, route_in_prefix
    return [r for r in iter_mounted_routes(app)
            if route_in_prefix(r, "/panel/resultado")]


def test_ninguna_ruta_del_prefijo_acepta_escritura(app_real):
    """Por ENUMERACION del espacio de URL, no por revision ocular."""
    from app.chassis import write_methods

    rutas = _rutas_del_prefijo(app_real)
    assert rutas, "El censo no ve ni una ruta del prefijo: no mide nada"
    culpables = [(r.path, write_methods(r)) for r in rutas if write_methods(r)]
    assert not culpables, f"Rutas capaces de escribir: {culpables}"


def test_el_interruptor_falla_cerrado(app_real, monkeypatch):
    """Ausente, vacio o ininteligible -> apagado. Nunca permiso maximo."""
    from app.routers import resultado as router_mod

    for crudo in (None, "", "   ", "false", "quizas", "0", "TRUE-ish"):
        if crudo is None:
            monkeypatch.delenv(router_mod.FLAG_ENV, raising=False)
        else:
            monkeypatch.setenv(router_mod.FLAG_ENV, crudo)
        assert router_mod._encendido() is False, f"{crudo!r} ha encendido la pantalla"

    for crudo in ("true", "TRUE", " 1 ", "1"):
        monkeypatch.setenv(router_mod.FLAG_ENV, crudo)
        assert router_mod._encendido() is True, f"{crudo!r} no la ha encendido"


def test_la_pantalla_no_es_un_oraculo_de_existencia(app_real, monkeypatch):
    """Ninguna respuesta puede depender de si ESE apply existe.

    Tres situaciones, y ninguna puede distinguirse de otra por un dato que el
    lector no deba tener:

    * APAGADA -> 404, con el cuerpo UNICO;
    * ENCENDIDA y workspace fuera de alcance -> el MISMO 404, mismo cuerpo
      (es la via por la que un curioso intentaria enumerar applies ajenos);
    * ENCENDIDA sobre un despliegue que no lee procedencia -> la MISMA pagina
      sea cual sea el identificador, porque no se ha mirado ninguna base.

    Esta suite corre con el proveedor por defecto, que NO es Neo4j: por eso el
    tercer caso es observable aqui. El 404 de "ese apply no existe en una base
    REAL" se afirma en la suite de Neo4j real, que es donde hay base.
    """
    from fastapi.testclient import TestClient

    from app.auth.config import get_auth_settings
    from app.routers import resultado as router_mod

    otro = "apply:" + "9" * 32
    monkeypatch.setenv("S9K_AUTH_ENABLED", "false")
    get_auth_settings.cache_clear()
    try:
        c = TestClient(app_real, raise_server_exceptions=False, follow_redirects=False)

        monkeypatch.delenv(router_mod.FLAG_ENV, raising=False)
        apagada = c.get(f"/panel/resultado/{APPLY}")
        assert apagada.status_code == 404
        assert router_mod.NO_ENCONTRADO in apagada.text

        monkeypatch.setenv(router_mod.FLAG_ENV, "true")
        ajeno = c.get(f"/panel/resultado/{APPLY}",
                      params={"workspace": "workspace-que-no-es-tuyo"})
        assert ajeno.status_code == 404, (
            "Un workspace fuera de alcance no da 404: la pantalla sirve para "
            "enumerar ejecuciones ajenas."
        )
        assert ajeno.json() == apagada.json(), (
            "El cuerpo del 404 distingue 'pantalla apagada' de 'no es tuyo'."
        )

        uno = c.get(f"/panel/resultado/{APPLY}")
        dos = c.get(f"/panel/resultado/{otro}")
        assert uno.status_code == dos.status_code == 503, (
            "Sin lector de procedencia el desenlace no es 503: o se degrada a "
            "un vacio que nadie ha medido, o dice 'no existe' de algo que no "
            "se ha mirado."
        )
        # Sin lector no se ha consultado ninguna base, asi que las dos
        # respuestas no pueden diferir en NADA: si difieren, algo se consulto.
        assert uno.text == dos.text, (
            "Sin lector, dos identificadores distintos producen respuestas "
            "distintas: algo se ha consultado y eso es un oraculo."
        )
        assert servicio.PROVENANCE_READER_UNAVAILABLE in uno.text, (
            "El 503 no lleva codigo estable: `CODIGO: frase` es la forma "
            "exigida, y sin el codigo no se puede correlacionar con el log."
        )
        assert "Traceback" not in uno.text and str(RAIZ_REPO) not in uno.text, (
            "El cuerpo del error lleva detalle tecnico o una ruta del servidor"
        )
    finally:
        get_auth_settings.cache_clear()


def test_el_lector_no_es_un_GraphProvider(app_real):
    """No se puede inyectar donde va el proveedor filtrado.

    Si `ProvenanceReader` heredara de `GraphProvider`, alguien lo pondria en un
    `Depends(get_filtered_provider)` y la pantalla quedaria sin politica.
    """
    from app.providers.base import GraphProvider

    assert not issubclass(lector.ProvenanceReader, GraphProvider)


def test_reader_for_devuelve_None_cuando_la_fuente_no_es_neo4j():
    """Y `None` lo lee el servicio como NO DISPONIBLE, nunca como cero."""
    class SinDriver:
        pass

    assert lector.reader_for(SinDriver()) is None


def test_los_literales_del_writer_coinciden_con_los_del_motor():
    """Dos arboles de `sys.path` que no pueden importarse entre si: las
    etiquetas estan DUPLICADAS a la fuerza. Que no DIVERJAN se comprueba.

    Sin esto, el dia que el writer renombre una etiqueta esta pantalla se
    quedaria en blanco y el verde de las demas pruebas no se enteraria.
    """
    from knowledge_v3.writer import cypher as writer_cypher
    from knowledge_v3.writer import provenance as writer_prov
    from knowledge_v3.writer.apply_identity import APPLY_ID_FIELD
    from knowledge_v3.writer.ownership_identity import OWNERSHIP_ID_FIELD

    assert lector.LABEL_APPLIED_OPERATION == writer_cypher.LABEL_APPLIED_OPERATION
    assert lector.LABEL_ASSERTION == writer_cypher.LABEL_ASSERTION
    assert lector.LABEL_SOURCE == writer_prov.LABEL_SOURCE
    assert lector.LABEL_EPISODE == writer_prov.LABEL_EPISODE
    assert lector.LABEL_EVIDENCE == writer_prov.LABEL_EVIDENCE
    assert lector.APPLY_ID_FIELD == APPLY_ID_FIELD
    assert lector.OWNERSHIP_ID_FIELD == OWNERSHIP_ID_FIELD
    assert "SUPPORTED_BY" == writer_prov.REL_SUPPORTED_BY


def test_el_apply_id_de_este_modulo_acepta_lo_que_produce_el_writer():
    """La forma no se copia de memoria: se genera con el productor real."""
    from knowledge_v3.writer.apply_identity import compute_apply_id

    real = compute_apply_id(
        workspace=WS, snapshot_id="snapshot:neo4j:x", plan_hash="deadbeef",
    )
    assert servicio.es_apply_id(real), (
        f"El validador de forma rechaza un apply_id REAL del writer: {real!r}"
    )


# ===========================================================================
# 7. TRES CEROS QUE SE PARECEN. Solo uno es una carencia del producto.
# ===========================================================================
# El Carril B midio que un apply lanzado desde la interfaz va SIN
# `ProvenanceBundle`: `apply_v3` escribe el conocimiento, anota
# `APPLY_PROVENANCE_NOT_PERSISTED` y enumera los fragmentos colgantes. En el
# grafo eso deja aserciones SIN un solo `SUPPORTED_BY`.
#
# Sin distinguirlo, esa ejecucion y un hecho que simplemente no tiene cita se
# pintan con la MISMA frase, y el operador no puede saber cual de las dos le
# ha tocado.

def _detalle(lec, espia, apply_id=APPLY, assertion_id="assertion:1"):
    return servicio.detalle_de_asercion(
        provider=espia, reader=lec, workspace=WS,
        apply_id=apply_id, assertion_id=assertion_id)


_ASERCION = [{
    "assertion_id": "assertion:1", "subject_entity_id": "entity:a",
    "object_entity_id": None, "predicate": "MEMBER_OF", "idempotency_key": "k1",
}]


def test_una_ejecucion_que_no_persistio_procedencia_lo_DICE():
    """El apply escribio el hecho y NINGUNA de sus aserciones tiene soporte."""
    lec = LectorFalso(aserciones=_ASERCION, fragmentos=[], persistio_procedencia=False)
    detalle = _detalle(lec, ProveedorEspia(visibles=["entity:a"]))

    assert detalle is not None, (
        "Se ha devuelto 404: eso dice 'ese hecho no existe', y existe -- lo que "
        "no existe es su procedencia."
    )
    assert detalle.evidencias.estado == servicio.SIN_PROCEDENCIA, (
        f"estado {detalle.evidencias.estado!r}: una ejecucion que no guardo "
        "procedencia se esta pintando como un hecho sin evidencia."
    )
    assert detalle.evidencias.filas == []


def test_un_hecho_sin_cita_en_una_ejecucion_QUE_SI_persistio_dice_VACIO():
    """El contraste que hace significar al caso anterior.

    Misma pantalla vacia, otra causa: aqui la ejecucion SI dejo procedencia
    (otras aserciones la tienen), asi que el hueco es de ESTE hecho.
    """
    lec = LectorFalso(aserciones=_ASERCION, fragmentos=[], persistio_procedencia=True)
    detalle = _detalle(lec, ProveedorEspia(visibles=["entity:a"]))

    assert detalle.evidencias.estado == servicio.VACIO, (
        f"estado {detalle.evidencias.estado!r}: un hueco de ESTE hecho se esta "
        "presentando como una carencia de la ejecucion entera."
    )


def test_los_tres_ceros_son_TRES_desenlaces_distintos():
    """Enumerados juntos, que es la unica forma de ver que no se confunden."""
    sin_proc = _detalle(
        LectorFalso(aserciones=_ASERCION, fragmentos=[], persistio_procedencia=False),
        ProveedorEspia(visibles=["entity:a"]))
    hueco = _detalle(
        LectorFalso(aserciones=_ASERCION, fragmentos=[], persistio_procedencia=True),
        ProveedorEspia(visibles=["entity:a"]))
    # Sin permiso sobre el sujeto: indistinguible de inexistente, y es 404.
    sin_permiso = _detalle(
        LectorFalso(aserciones=_ASERCION, fragmentos=[], persistio_procedencia=True),
        ProveedorEspia(visibles=[]))

    desenlaces = (
        sin_proc.evidencias.estado,
        hueco.evidencias.estado,
        "404" if sin_permiso is None else "SERVIDO",
    )
    assert desenlaces == (servicio.SIN_PROCEDENCIA, servicio.VACIO, "404"), (
        f"Los tres ceros no dan tres desenlaces distintos: {desenlaces}"
    )


def test_no_se_pregunta_por_el_discriminador_cuando_SI_hay_fragmentos():
    """No se paga una consulta por una pregunta ya contestada."""
    lec = LectorFalso(
        aserciones=_ASERCION,
        fragmentos=[{c: None for c in lector.CAMPOS_FRAGMENTO} | {
            "fragment_id": "f1", "literal_text": "algo"}],
        revienta=["apply_persistio_procedencia"],  # si se llamara, reventaria
    )
    detalle = _detalle(lec, ProveedorEspia(visibles=["entity:a"]))
    assert detalle.evidencias.estado == servicio.DISPONIBLE


def test_un_fallo_al_discriminar_da_ERROR_y_no_inventa_un_veredicto():
    lec = LectorFalso(aserciones=_ASERCION, fragmentos=[],
                      revienta=["apply_persistio_procedencia"])
    detalle = _detalle(lec, ProveedorEspia(visibles=["entity:a"]))
    assert detalle.evidencias.estado == servicio.ERROR
    assert detalle.evidencias.total is None


# ===========================================================================
# 8. EL TESTIGO DE LA DEPENDENCIA CON EL APPLY DE LA INTERFAZ
# ===========================================================================
# Vive AQUI, en la suite que corre SIEMPRE, y no en la de Neo4j real: es una
# propiedad del CODIGO, no del grafo, y en aquel modulo el `skipif` de las
# variables de base lo dejaria en `skipped` -- que es exactamente el falso
# verde que este carril ya tuvo que cerrar una vez.

def test_el_plan_sellado_de_la_interfaz_solo_emite_CREATE_ASSERTION():
    """EL TESTIGO QUE MIRA DONDE DICE MIRAR. Sin Neo4j: es una propiedad del codigo.

    El apply de la interfaz consume el plan que sella `seal_review_plan`, y ese
    plan determina si hay ARISTA que abrir. Hoy emite solo `CREATE_ASSERTION`:
    por eso la prueba insignia parte de un apply por la ruta de INGESTA, que si
    proyecta. Esa dependencia queda atada AQUI.

    Se comprueba por AST --un literal unico, ningun `operation_type` calculado--
    y no contando apariciones en el texto: contar da falsos negativos en cuanto
    alguien compone el valor. Cuando el Carril B2 haga que el apply proyecte,
    este caso se pondra ROJO y dira que la insignia puede pasar a partir de un
    apply de la interfaz. Eso es lo que se quiere que pase.
    """
    import ast

    fuente = (RAIZ_REPO / "data-engine" / "app" / "knowledge_v3" / "review_plan.py")
    arbol = ast.parse(fuente.read_text())

    calculados, literales = [], set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Dict):
            for clave, valor in zip(nodo.keys, nodo.values):
                if isinstance(clave, ast.Constant) and clave.value == "operation_type":
                    if isinstance(valor, ast.Constant):
                        literales.add(valor.value)
                    else:
                        calculados.append(ast.dump(valor)[:80])
        if isinstance(nodo, ast.keyword) and nodo.arg == "operation_type":
            if isinstance(nodo.value, ast.Constant):
                literales.add(nodo.value.value)
            else:
                calculados.append(ast.dump(nodo.value)[:80])

    assert literales, (
        "no se encontro ningun `operation_type` en review_plan.py: el testigo "
        "no esta mirando lo que cree mirar (¿se movio el sellado de plan?)"
    )
    assert not calculados, (
        f"hay `operation_type` CALCULADOS ({calculados}): este testigo solo "
        "sabe leer literales, asi que ya no puede afirmar que el plan de la "
        "interfaz no proyecta. Hay que medirlo de otra forma."
    )
    assert literales == {"CREATE_ASSERTION"}, (
        f"el plan sellado de la interfaz ya emite {sorted(literales)}. Si "
        "incluye una proyeccion de relacion, la prueba insignia YA PUEDE "
        "partir de un apply de la interfaz en vez de uno de ingesta: "
        "revisarla y retirar la dependencia declarada."
    )


# ===========================================================================
# 9. LA GUARDA DE QUE ESTA COBERTURA SE EJERCE DE VERDAD
# ===========================================================================
# MEDIDO, y por eso existe este caso: quitando
# `test_resultado_procedencia_neo4j_real.py` de la lista del paso de Neo4j de
# `ci.yml`, la puerta de inventario sigue diciendo OK. Ese modulo se declara
# CONDICIONAL con condicion `(not URI or not PASSWORD)` y en `test-viewer`
# --que no define esas variables-- sale `skipped` con rc=0 y el job VERDE. O
# sea: el trinquete de inventario NO caza la desaparicion de esta cobertura.
#
# Asi que la guarda vive AQUI, en la suite que corre SIEMPRE. Si alguien quita
# el modulo de la invocacion, o anade otro de la misma familia sin invocarlo,
# esto se pone rojo y dice que hay que anadirlo. La regla no es una lista que
# haya que acordarse de rellenar: el conjunto se DERIVA y la lista se compara.

def _modulos_del_visor_que_exigen_neo4j_de_prueba() -> set:
    """Modulos de `viewer/tests` que LEEN `NEO4J_TEST_URI` del entorno.

    Por AST y por EFECTO, no por nombre ni por `grep`: la convencion de
    nombres tiene excepciones medidas en este repo (`descubre_neo4j_real.py`
    documenta un falso positivo y un falso negativo), y contar apariciones de
    texto casa dentro de comentarios y docstrings -- este mismo fichero nombra
    la variable varias veces sin ser uno de ellos.
    """
    import ast

    def lee_la_variable(nodo) -> bool:
        if isinstance(nodo, ast.Call):
            f = nodo.func
            if isinstance(f, ast.Attribute) and f.attr in ("get", "getenv"):
                return any(isinstance(a, ast.Constant) and a.value == "NEO4J_TEST_URI"
                           for a in nodo.args)
        if isinstance(nodo, ast.Subscript):
            s = nodo.slice
            return isinstance(s, ast.Constant) and s.value == "NEO4J_TEST_URI"
        return False

    hallados = set()
    base = RAIZ_REPO / "viewer" / "tests"
    for py in sorted(base.glob("test_*.py")):
        try:
            arbol = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        if any(lee_la_variable(n) for n in ast.walk(arbol)):
            hallados.add(py.relative_to(RAIZ_REPO).as_posix())
    return hallados


def _rutas_invocadas_en_el_paso_de_neo4j() -> set:
    """Rutas que el paso de CI nombra. Se parsea el YAML, no se hace `grep`.

    Un `grep` sobre el fichero casa igual con una ruta escrita en un
    comentario; el YAML da el `run` de ESE paso, que es lo que se ejecuta.
    """
    import re

    # `import` PELADO, nunca `importorskip`: si `yaml` faltara, esta guarda se
    # auto-omitiria y volveria a ser un skip VERDE -- exactamente el defecto
    # que existe para cerrar. Sin `yaml` este caso ERRORA, que es rojo y se ve.
    # Lo dijo la puerta de inventario con un PREFLIGHT, y tenia razon.
    import yaml
    doc = yaml.safe_load((RAIZ_REPO / ".github" / "workflows" / "ci.yml").read_text())
    for job in (doc.get("jobs") or {}).values():
        for paso in job.get("steps") or []:
            if paso.get("name") == "Run authz integration tests":
                cuerpo = paso.get("run") or ""
                # Solo lineas de invocacion, nunca comentarios.
                util = "\n".join(l for l in cuerpo.splitlines()
                                 if not l.lstrip().startswith("#"))
                return set(re.findall(r"viewer/tests/\S+?\.py", util))
    raise AssertionError(
        "no se encontro el paso 'Run authz integration tests' en ci.yml: esta "
        "guarda no esta mirando lo que cree mirar"
    )


def test_la_cobertura_neo4j_del_visor_se_invoca_entera_en_ci():
    """Ningun modulo de esta familia puede quedarse fuera del paso que lo ejerce."""
    derivados = _modulos_del_visor_que_exigen_neo4j_de_prueba()
    invocados = _rutas_invocadas_en_el_paso_de_neo4j()

    assert derivados, (
        "el derivador no encontro NINGUN modulo que lea NEO4J_TEST_URI: esta "
        "guarda no mide nada (cambio la familia de variables?)"
    )
    sin_invocar = derivados - invocados
    assert not sin_invocar, (
        f"estos modulos exigen NEO4J_TEST_URI y NINGUN job los invoca con esa "
        f"variable: {sorted(sin_invocar)}. En `test-viewer` saldran SKIPPED "
        "con rc=0 y el job VERDE, o sea que su cobertura no existe. Anadelos a "
        "la invocacion del paso 'Run authz integration tests' de ci.yml."
    )


def test_mi_suite_de_neo4j_real_es_de_esa_familia_y_esta_invocada():
    """Control positivo de la guarda de arriba, sobre el modulo de este carril.

    Sin esto, la guarda pasaria igual el dia que este modulo dejara de leer la
    variable (y por tanto saliera del conjunto derivado) aunque su cobertura
    hubiera desaparecido.
    """
    mio = "viewer/tests/test_resultado_procedencia_neo4j_real.py"
    assert mio in _modulos_del_visor_que_exigen_neo4j_de_prueba()
    assert mio in _rutas_invocadas_en_el_paso_de_neo4j()
