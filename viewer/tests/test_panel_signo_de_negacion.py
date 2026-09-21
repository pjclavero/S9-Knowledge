# -*- coding: utf-8 -*-
"""EL SIGNO DE UN HECHO, EN LAS TRES PANTALLAS QUE LO ENSEÑAN.

EL DEFECTO, tal y como lo midió un operador recorriendo el producto con Neo4j
real. El nodo del grafo traía `negated = true`, el sobre de la ingesta lo traía
y Review lo había explicado (`NEGATED_CLAIM`, «la frase niega la relación en vez
de afirmarla»). Y aun así:

    /panel/resultado/<apply>/hecho/<assertion>  ->  «Sela Marrec MEMBER_OF
                                                     Consejo de Umbra»
    /panel/entities/item/<entity>               ->  «pertenece a · ASSERTED»
    y justo debajo, la evidencia literal:        «Sela Marrec NO pertenece al
                                                  Consejo de Umbra.»

La pantalla se contradecía a sí misma en el mismo recuadro. El dato ya existía:
lo que faltaba era que el visor lo publicara.

QUÉ AFIRMA ESTE FICHERO Y QUÉ NO
================================
Aquí se pide LA PANTALLA (`GET` del HTML) en las tres superficies —resultado,
procedencia de un hecho y ficha de entidad— y se afirma sobre el marcado que el
servidor emite. No se llama a un servicio ni se inspecciona un diccionario: el
defecto era, literalmente, «el dato llega y la plantilla no lo pinta», y una
prueba sobre el diccionario habría seguido verde con el defecto puesto.

Lo que este fichero NO puede afirmar es que el recorrido COMPLETO conserve el
signo desde una fuente negativa: el proveedor y el lector son dobles. Eso lo
mide `test_signo_de_negacion_writer_a_visor_neo4j.py`, contra Neo4j real y con
el material escrito por el writer de verdad. Un verde aquí no sustituye a aquél.

EL RECUENTO, MEDIDO: 24 casos recolectados aquí y 5 en
`test_panel_causa_del_plan_superseded.py`. Se dice porque en un informe previo
escribí «26+5» contándolos de memoria; el número sale de `--collect-only`.

Y EL TECHO, DICHO ENTERO: no existe un solo test que recorra texto crudo ->
HTML. La propiedad se sostiene por COMPOSICIÓN de tres ficheros —extracción
(`test_knowledge_v3_e2e_global.py`), apply-a-lectura
(`test_signo_de_negacion_writer_a_visor_neo4j.py`) y lectura-a-pantalla
(éste)—. Leído del tirón parece que hay un E2E, y no lo hay.

LOS TRES CASOS, Y LOS TRES SE COMPRUEBAN
========================================
    negated is True     -> NEGADO          la frase lleva «NO»
    negated is False    -> AFIRMATIVO      la frase NO lleva «NO»
    ausente / no booleano -> NO_DISPONIBLE  la pantalla lo DICE

El segundo no es relleno: pintar como negado un hecho afirmativo es tan grave
como lo contrario, y sin un caso que lo vigile la forma más fácil de aprobar el
primero sería marcarlo todo. El tercero es una DECISIÓN DECLARADA: ausencia no
es cero, y un hecho antiguo sin `negated` no se convierte en «afirmativo».
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.chassis import FEATURE_SLOTS, slot_flag_env
from app.providers.base import GraphProvider

SLOT_G = next(s for s in FEATURE_SLOTS if s.key == "G")
FLAG_G = slot_flag_env(SLOT_G)
FLAG_RESULTADO = "S9K_PANEL_RESULTADO_ENABLED"

WS = "juego:signo"
PASSWORD = "SignoDeNegacion_1234567890!"
APPLY = "apply:" + "a" * 32

SUJETO = "entity:sela-marrec"
OBJETO = "entity:consejo-umbra"
PREDICADO = "MEMBER_OF"

#: Un `assertion_id` por signo. Tenerlos separados permite pedir la MISMA
#: pantalla tres veces y comparar el marcado, en vez de fiarse de un contador.
ID_NEGADO = "assertion:negado"
ID_AFIRMATIVO = "assertion:afirmativo"
ID_SIN_SIGNO = "assertion:sin-signo"

#: LA MARCA. Se afirma sobre el atributo Y sobre el texto visible: el atributo
#: solo sería invisible para el operador, y el texto solo no distingue las tres
#: ramas.
NEGADO = 'data-signo="HECHO_NEGADO"'
AFIRMATIVO = 'data-signo="HECHO_AFIRMATIVO"'
SIN_SIGNO = 'data-signo="HECHO_SIGNO_NO_DISPONIBLE"'
MARCA_NO = 'data-role="marca-negacion"'


# ===========================================================================
# Dobles
# ===========================================================================
def _asercion(assertion_id: str, negated) -> dict:
    """Un hecho CRUDO como lo entrega el proveedor. `negated` se pasa tal cual.

    El tercer caso se construye OMITIENDO la clave, no poniéndola a `None`:
    así es como llega un hecho escrito antes de que el writer estampara el
    campo, y es el caso que una normalización a `False` convertiría en una
    afirmación que nadie hizo.
    """
    fila = {
        "assertion_id": assertion_id, "id": assertion_id,
        "predicate": PREDICADO,
        "subject_entity_id": SUJETO, "object_entity_id": OBJETO,
        "status": "ASSERTED", "workspace": WS, "scope": "juego",
        "partida_id": None, "local_override_of": None,
        "visibility": "player", "review_status": "reviewed", "confidence": 0.9,
    }
    if negated is not _AUSENTE:
        fila["negated"] = negated
    return fila


class _Ausente:
    def __repr__(self):  # pragma: no cover - solo para mensajes de fallo
        return "<campo ausente>"


_AUSENTE = _Ausente()


def _entidad(entity_id: str) -> dict:
    return {
        "id": entity_id, "entity_id": entity_id, "label": entity_id,
        "canonical_name": entity_id, "type": "PERSON",
        "description": "Entidad de prueba.", "workspace": WS, "scope": "juego",
        "visibility": "player", "review_status": "reviewed", "confidence": 0.9,
        "source_document": "nota.md",
    }


class ProveedorFalso(GraphProvider):
    """Proveedor BASE crudo: no filtra nada, la política real corre encima."""

    name = "falso"

    def __init__(self, hechos):
        self._hechos = list(hechos)

    def is_connected(self): return True
    def workspaces(self): return [WS]
    def counts(self, workspace=None): return (2, 0)
    def entity_types(self, workspace): return []
    def search(self, workspace, q, limit=50): return []
    def graph(self, workspace, limit=300, entity_type=None, q=None): return ([], [])
    def list_sources(self, workspace): return []
    def source_detail(self, workspace, source_id): return None
    def quality_metrics(self, workspace=None): return {}
    def relations_for_entity(self, entity_id, *, workspaces=None): return ([], [])

    def entity(self, entity_id, *, workspaces=None):
        return _entidad(entity_id) if entity_id in (SUJETO, OBJETO) else None

    def list_entities(self, workspace, **kw):
        nodos = [_entidad(SUJETO)] if workspace == WS else []
        return nodos, len(nodos)

    def list_assertions(self, workspace, *, subject_entity_id=None):
        return [
            dict(h) for h in self._hechos
            if h.get("workspace") == workspace
            and (subject_entity_id is None
                 or h.get("subject_entity_id") == subject_entity_id)
        ]


class LectorFalso:
    """Lector de procedencia. Entrega las aserciones TAL CUAL se le dan.

    Importa que no las normalice: si este doble rellenara `negated`, la prueba
    mediría al doble y no al `RETURN` del lector real ni a la plantilla.
    """

    def __init__(self, aserciones):
        self._as = list(aserciones)

    def operations_of_apply(self, ws, apply_id):
        if ws != WS or apply_id != APPLY:
            return []
        return [{"idempotency_key": "k1", "operation_id": "op1",
                 "applied_at": "2026-09-15T10:00:00Z",
                 "ownership_id": "own:" + "c" * 32, "partida_id": None}]

    def entity_ids_for_keys(self, ws, keys): return [SUJETO]
    def relation_edges_for_keys(self, ws, keys): return []
    def assertions_for_keys(self, ws, keys): return [dict(a) for a in self._as]
    def apply_persistio_procedencia(self, ws, keys): return True

    def fragments_supporting(self, ws, assertion_id):
        # LA CITA LITERAL que el defecto contradecía. Va en el material a
        # propósito: es lo que convierte «un campo que falta» en «la pantalla
        # afirma y niega lo mismo en el mismo recuadro».
        # El campo se llama `literal_text` porque así lo declara
        # `provenance_reader.CAMPOS_FRAGMENTO`; `text` está en
        # `CAMPOS_PROHIBIDOS` y no puede viajar. No es un detalle: un doble que
        # emita el campo equivocado pinta el fragmento vacío y la
        # contradicción deja de ser observable — pasó en el primer intento.
        return [{"fragment_id": "fragment:1", "episode_id": None,
                 "source_asset_id": None, "page": None, "start": None,
                 "end": None, "media_type": None, "time_start": None,
                 "time_end": None,
                 "literal_text": "Sela Marrec NO pertenece al Consejo de Umbra."}]

    def episode(self, ws, eid): return None
    def source(self, ws, sid): return None


# ===========================================================================
# Fixtures: app REAL, plantillas REALES, cadena de autorización REAL
# ===========================================================================
@pytest.fixture
def real_app():
    from app.main import app
    return app


@pytest.fixture(autouse=True)
def _grafo_de_mentira(monkeypatch):
    """La ingesta del panel abre una conexión de sólo lectura y falla cerrado
    sin ella. Aquí no se mide eso: se le da el doble que ya usa la suite."""
    import grafo_doble

    return grafo_doble.instalar(monkeypatch)


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    from app.auth.config import get_auth_settings
    from app.config import get_settings

    monkeypatch.setenv("S9K_DEFAULT_WORKSPACE", WS)
    monkeypatch.setenv("S9K_AUTH_ENABLED", "true")
    monkeypatch.setenv("S9K_AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv(FLAG_RESULTADO, "true")
    monkeypatch.setenv(FLAG_G, "true")
    get_settings.cache_clear()
    get_auth_settings.cache_clear()

    from app.auth import db as auth_db
    auth_db.ensure_migrated(tmp_path / "auth.db")
    yield tmp_path / "auth.db"
    get_settings.cache_clear()
    get_auth_settings.cache_clear()


def _cookie(db_path: Path, username: str, role: str = "admin") -> str:
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db.get_conn(db_path) as conn:
        u = auth_db.create_user(
            conn, username=username, display_name=username.title(),
            password_hash=hash_password(PASSWORD), role=role)
        auth_db.update_user(conn, u.id, must_change_password=False)
        u = auth_db.get_user_by_id(conn, u.id)
        token, _ = create_session(conn, u)
    return token


def _cliente(app, cookie: str) -> TestClient:
    from app.auth.config import get_auth_settings

    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, cookie)
    return c


def _ficha_de_entidad(real_app, entorno, hechos, usuario):
    """SUPERFICIE 3 — `GET /panel/entities/item/<entity_id>`."""
    import app.deps as deps

    real_app.dependency_overrides[deps.get_provider] = lambda: ProveedorFalso(hechos)
    try:
        return _cliente(real_app, _cookie(entorno, usuario)).get(
            f"{SLOT_G.prefix}/item/{SUJETO}")
    finally:
        real_app.dependency_overrides.pop(deps.get_provider, None)


class _ProveedorDeResultado:
    """Lo que el proveedor FILTRADO decidiría, para la superficie de resultado."""

    def workspaces(self): return [WS]
    def entity(self, entity_id, **_):
        return _entidad(entity_id) if entity_id in (SUJETO, OBJETO) else None
    def relations_for_entity(self, entity_id, **_): return ([], [])


def _pantalla_resultado(real_app, entorno, monkeypatch, hechos, usuario, sufijo=""):
    """SUPERFICIES 1 y 2 — resultado de la ejecución y procedencia de un hecho."""
    from app.authz.dependencies import get_filtered_provider
    from app.routers import resultado as ruta_resultado

    monkeypatch.setattr(ruta_resultado, "reader_for",
                        lambda _p: LectorFalso(hechos))
    real_app.dependency_overrides[get_filtered_provider] = _ProveedorDeResultado
    try:
        return _cliente(real_app, _cookie(entorno, usuario)).get(
            f"/panel/resultado/{APPLY}{sufijo}", params={"workspace": WS})
    finally:
        real_app.dependency_overrides.pop(get_filtered_provider, None)


def _bloque_del_hecho(html: str, assertion_id: str) -> str:
    """El trozo de HTML de ESE hecho, no la página entera.

    Buscar la marca en toda la página era un falso verde esperando: con tres
    hechos en la misma lista, `'HECHO_NEGADO' in html` se cumple por el hecho
    negado aunque el afirmativo también estuviera marcado.
    """
    trozos = re.split(r"(?=<li )", html)
    for t in trozos:
        if f'data-assertion-id="{assertion_id}"' in t:
            return t
    raise AssertionError(
        f"el hecho {assertion_id} no aparece en la pantalla; sin él esta "
        f"prueba no mide nada")


# ===========================================================================
# SUPERFICIE 1 — la pantalla de RESULTADO de la ejecución
# ===========================================================================
def test_resultado_pinta_el_NO_de_un_hecho_negado(real_app, entorno, monkeypatch):
    """EL DEFECTO, en la primera pantalla."""
    r = _pantalla_resultado(
        real_app, entorno, monkeypatch,
        [_asercion(ID_NEGADO, True)], "signo-r1")
    assert r.status_code == 200, r.status_code
    bloque = _bloque_del_hecho(r.text, ID_NEGADO)
    assert NEGADO in bloque, (
        "la pantalla de resultado no publica el signo del hecho: un hecho que "
        "NIEGA la relación se está pintando igual que uno que la afirma")
    assert MARCA_NO in bloque, (
        "el signo viaja en un atributo pero la FRASE no lleva el «NO»: el "
        "operador sigue leyendo «Sela Marrec pertenece al Consejo de Umbra»")


def test_resultado_NO_marca_como_negado_un_hecho_afirmativo(
        real_app, entorno, monkeypatch):
    """EL ERROR SIMÉTRICO. Sin este caso, marcarlo todo aprobaría el anterior."""
    r = _pantalla_resultado(
        real_app, entorno, monkeypatch,
        [_asercion(ID_AFIRMATIVO, False)], "signo-r2")
    assert r.status_code == 200, r.status_code
    bloque = _bloque_del_hecho(r.text, ID_AFIRMATIVO)
    # EL ORDEN IMPORTA, y se midió. Con la marca invertida el primer `assert`
    # que saltaba era el del atributo, cuyo mensaje es el bloque pelado: la
    # calibración lo marcó como «roja, pero SIN su causa». La propiedad que
    # este caso defiende va PRIMERA, con su frase.
    assert MARCA_NO not in bloque, (
        "un hecho AFIRMATIVO se está pintando con la marca de negación: "
        "invertir el signo es tan grave como perderlo")
    assert NEGADO not in bloque, (
        "un hecho AFIRMATIVO lleva el código de negado: "
        "invertir el signo es tan grave como perderlo")
    assert AFIRMATIVO in bloque, (
        "un hecho afirmativo no publica su signo: "
        "invertir el signo es tan grave como perderlo")


def test_resultado_dice_que_no_sabe_el_signo_cuando_el_campo_no_viene(
        real_app, entorno, monkeypatch):
    """AUSENCIA NO ES CERO, y la pantalla lo DICE en vez de callar."""
    r = _pantalla_resultado(
        real_app, entorno, monkeypatch,
        [_asercion(ID_SIN_SIGNO, _AUSENTE)], "signo-r3")
    assert r.status_code == 200, r.status_code
    bloque = _bloque_del_hecho(r.text, ID_SIN_SIGNO)
    assert SIN_SIGNO in bloque, (
        "un hecho SIN el campo `negated` se está publicando como si su signo "
        "se conociera; ausencia no es «afirmativo»")
    assert AFIRMATIVO not in bloque, bloque
    assert "no consta si este hecho afirma o niega" in bloque, (
        "la pantalla conoce el tercer estado pero no se lo dice a nadie: un "
        "hueco en blanco se lee como «afirmativo»")


def test_resultado_distingue_los_tres_signos_en_la_MISMA_pagina(
        real_app, entorno, monkeypatch):
    """Los tres a la vez. Un marcado CABLEADO en la plantilla moriría aquí."""
    r = _pantalla_resultado(
        real_app, entorno, monkeypatch,
        [_asercion(ID_NEGADO, True), _asercion(ID_AFIRMATIVO, False),
         _asercion(ID_SIN_SIGNO, _AUSENTE)], "signo-r4")
    assert r.status_code == 200, r.status_code
    assert NEGADO in _bloque_del_hecho(r.text, ID_NEGADO), (
        "con los tres hechos delante, el negado no sale marcado como negado")
    assert AFIRMATIVO in _bloque_del_hecho(r.text, ID_AFIRMATIVO), (
        "con los tres hechos delante, el afirmativo no sale marcado como "
        "afirmativo: o el marcado esta cableado o el signo se ha perdido")
    assert SIN_SIGNO in _bloque_del_hecho(r.text, ID_SIN_SIGNO), (
        "con los tres hechos delante, el que no trae signo no sale declarado "
        "como tal; ausencia no es «afirmativo»")


# ===========================================================================
# SUPERFICIE 2 — la procedencia de UN hecho (donde está la cita literal)
# ===========================================================================
def _procedencia(real_app, entorno, monkeypatch, negated, assertion_id, usuario):
    return _pantalla_resultado(
        real_app, entorno, monkeypatch, [_asercion(assertion_id, negated)],
        usuario, sufijo=f"/hecho/{assertion_id}")


def test_procedencia_no_contradice_a_su_propia_evidencia(
        real_app, entorno, monkeypatch):
    """EL RECUADRO QUE SE CONTRADECÍA A SÍ MISMO.

    La cita literal —«Sela Marrec NO pertenece al Consejo de Umbra»— la sirve
    el mismo doble, y se comprueba que está: sin ella esta prueba mediría media
    pantalla y la contradicción no sería observable.
    """
    r = _procedencia(real_app, entorno, monkeypatch, True, ID_NEGADO, "signo-p1")
    assert r.status_code == 200, r.status_code
    assert "NO pertenece al Consejo de Umbra" in r.text, (
        "la cita literal no se ha pintado: sin ella no hay contradicción que "
        "medir y esta prueba no vale")
    assert NEGADO in r.text, (
        "el hecho se pinta sin signo JUNTO a la evidencia que lo niega")
    assert MARCA_NO in r.text, (
        "la frase del hecho NO lleva el «NO»: el recuadro sigue afirmando lo que su propia cita literal niega")


def test_procedencia_NO_marca_como_negado_un_hecho_afirmativo(
        real_app, entorno, monkeypatch):
    """El simétrico, en la segunda superficie."""
    r = _procedencia(real_app, entorno, monkeypatch, False, ID_AFIRMATIVO,
                     "signo-p2")
    assert r.status_code == 200, r.status_code
    assert AFIRMATIVO in r.text, (
        "un hecho afirmativo no publica su signo en la procedencia")
    assert MARCA_NO not in r.text, (
        "se ha pintado la marca de negación sobre un hecho afirmativo")


def test_procedencia_declara_el_signo_ausente(real_app, entorno, monkeypatch):
    r = _procedencia(real_app, entorno, monkeypatch, _AUSENTE, ID_SIN_SIGNO,
                     "signo-p3")
    assert r.status_code == 200, r.status_code
    assert SIN_SIGNO in r.text, (
        "un hecho sin el campo `negated` se publica como si su signo se conociera; ausencia no es «afirmativo»")
    assert "no consta si este hecho afirma o niega" in r.text


# ===========================================================================
# SUPERFICIE 3 — la ficha de entidad
# ===========================================================================
def test_ficha_de_entidad_pinta_el_NO_de_un_hecho_negado(real_app, entorno):
    """«pertenece a · ASSERTED» para un hecho que decía lo contrario."""
    r = _ficha_de_entidad(real_app, entorno, [_asercion(ID_NEGADO, True)],
                          "signo-e1")
    assert r.status_code == 200, r.status_code
    bloque = _bloque_del_hecho(r.text, ID_NEGADO)
    assert NEGADO in bloque, (
        "la ficha de entidad sigue publicando el predicado sin su signo")
    assert MARCA_NO in bloque, (
        "la ficha pinta el predicado sin el «NO»: el operador lee lo contrario de lo que dice el dato")


def test_ficha_de_entidad_NO_marca_como_negado_un_hecho_afirmativo(
        real_app, entorno):
    r = _ficha_de_entidad(real_app, entorno, [_asercion(ID_AFIRMATIVO, False)],
                          "signo-e2")
    assert r.status_code == 200, r.status_code
    bloque = _bloque_del_hecho(r.text, ID_AFIRMATIVO)
    assert AFIRMATIVO in bloque, (
        "un hecho afirmativo no publica su signo en la ficha de entidad")
    assert MARCA_NO not in bloque, (
        "la ficha marca como negado un hecho afirmativo")


def test_ficha_de_entidad_declara_el_signo_ausente(real_app, entorno):
    r = _ficha_de_entidad(real_app, entorno, [_asercion(ID_SIN_SIGNO, _AUSENTE)],
                          "signo-e3")
    assert r.status_code == 200, r.status_code
    bloque = _bloque_del_hecho(r.text, ID_SIN_SIGNO)
    assert SIN_SIGNO in bloque, (
        "un hecho sin el campo `negated` se publica como si su signo se conociera; ausencia no es «afirmativo»")
    assert "no consta si este hecho afirma o niega" in bloque


def test_ficha_de_entidad_distingue_los_tres_en_la_MISMA_pagina(
        real_app, entorno):
    r = _ficha_de_entidad(
        real_app, entorno,
        [_asercion(ID_NEGADO, True), _asercion(ID_AFIRMATIVO, False),
         _asercion(ID_SIN_SIGNO, _AUSENTE)], "signo-e4")
    assert r.status_code == 200, r.status_code
    assert NEGADO in _bloque_del_hecho(r.text, ID_NEGADO), (
        "con los tres hechos delante, el negado no sale marcado como negado")
    assert AFIRMATIVO in _bloque_del_hecho(r.text, ID_AFIRMATIVO), (
        "con los tres hechos delante, el afirmativo no sale marcado como "
        "afirmativo: o el marcado esta cableado o el signo se ha perdido")
    assert SIN_SIGNO in _bloque_del_hecho(r.text, ID_SIN_SIGNO), (
        "con los tres hechos delante, el que no trae signo no sale declarado "
        "como tal; ausencia no es «afirmativo»")


# ===========================================================================
# LA AUTORIDAD ÚNICA — conversión ESTRICTA, enumerada
# ===========================================================================
# Estos casos no piden la pantalla a propósito: cubren por ENUMERACIÓN las
# ramas que el corpus de las pantallas no alcanza (un `negated` que no es
# booleano). El techo queda dicho: esto mide la función, no el recorrido.

@pytest.mark.parametrize("valor,esperado", [
    (True, "HECHO_NEGADO"),
    (False, "HECHO_AFIRMATIVO"),
    (None, "HECHO_SIGNO_NO_DISPONIBLE"),
    # NI UNO DE ESTOS ES AFIRMATIVO. Son los valores que una verdad de Python
    # (`bool(v)`) convertiría en un signo que nadie ha leído.
    (0, "HECHO_SIGNO_NO_DISPONIBLE"),
    (1, "HECHO_SIGNO_NO_DISPONIBLE"),
    ("", "HECHO_SIGNO_NO_DISPONIBLE"),
    ("false", "HECHO_SIGNO_NO_DISPONIBLE"),
    ("true", "HECHO_SIGNO_NO_DISPONIBLE"),
    ([], "HECHO_SIGNO_NO_DISPONIBLE"),
])
def test_la_conversion_del_signo_es_estricta(valor, esperado):
    from app.labels import negation_code

    assert negation_code(valor) == esperado, (
        f"`negated={valor!r}` se ha interpretado como {negation_code(valor)}; "
        f"sólo los booleanos de verdad dicen el signo")


def test_un_codigo_de_signo_desconocido_se_NOMBRA_y_no_se_descarta():
    """Un hueco en blanco se lee como «afirmativo». Por eso no se descarta."""
    from app.labels import negation_label

    texto = negation_label("HECHO_SIGNO_INVENTADO")
    assert texto, "un código no traducible ha salido como cadena vacía"
    assert "HECHO_SIGNO_INVENTADO" in texto, texto


def test_el_serializador_publica_el_signo_y_no_el_booleano_crudo():
    """CONTRATO de la capa que alimenta la ficha de entidad.

    `serialize_assertion` es una lista BLANCA: lo que no esté, no sale. Este
    caso es el que enrojece si alguien la recorta y el signo vuelve a caerse
    antes de llegar a la plantilla.
    """
    from app.serializers import serialize_assertion

    assert serialize_assertion({"negated": True})["signo"] == "HECHO_NEGADO"
    assert serialize_assertion({"negated": False})["signo"] == "HECHO_AFIRMATIVO"
    assert serialize_assertion({})["signo"] == "HECHO_SIGNO_NO_DISPONIBLE"


def test_el_proyector_del_proveedor_de_neo4j_publica_el_signo():
    """La lista BLANCA del proveedor real, sin necesitar la base.

    `_assertion_to_dict` recibe un nodo del driver y lo proyecta; un `dict`
    normal sirve de nodo. Este caso existe porque la CALIBRACIÓN lo pidió:
    quitar el campo de esa lista dejaba verdes todas las pruebas de pantalla
    —usan un proveedor doble que no pasa por ahí— y la única red era la suite
    de Neo4j real, que no corre sin Docker.

    Lo que este caso NO dice es que el campo exista en el grafo: eso lo mide
    `data-engine/app/tests/test_signo_de_negacion_writer_a_visor_neo4j.py`.
    """
    from app.providers.neo4j_provider import _assertion_to_dict

    assert _assertion_to_dict({"assertion_id": "a", "negated": True})["negated"] is True, (
        "el proyector del proveedor de Neo4j ha dejado de publicar el signo: "
        "el hecho llega entero a la pantalla MENOS su significado")
    assert _assertion_to_dict({"assertion_id": "a", "negated": False})["negated"] is False, (
        "el proyector del proveedor de Neo4j ha dejado de publicar el signo")
    # AUSENCIA: `None`, y NO `False`. Un `or False` en esa línea reintroduce el
    # defecto en su forma simétrica y no lo vería ninguna otra prueba.
    assert _assertion_to_dict({"assertion_id": "a"})["negated"] is None, (
        "el proyector normaliza la ausencia del signo a «afirmativo»: "
        "ausencia no es cero")


def test_el_lector_de_procedencia_PIDE_el_signo_en_su_consulta():
    """RECORDATORIO, NO GARANTÍA. Léase el párrafo entero antes de confiar.

    Esto CUENTA TEXTO: lee el código fuente del método y busca un substring.
    Eso significa dos cosas, y las dos importan:

      * pasaría con `a.negated AS negated` escrito en un COMENTARIO;
      * fallaría ante un refactor legítimo que construyera el mismo `RETURN`
        de otra forma —por concatenación, por una lista de campos, etc.—.

    O sea que no establece la garantía: la establece
    `test_signo_de_negacion_writer_a_visor_neo4j.py::test_el_lector_de_procedencia_trae_el_signo_desde_el_grafo`,
    que EJECUTA la consulta contra un Neo4j real y mira el valor que vuelve.
    Aquél es la evidencia; éste se queda porque aquél necesita Docker y no
    corre en todas partes, y porque el día que alguien recorte el `RETURN` sin
    pensarlo este rojo llega antes y dice dónde mirar.
    """
    import inspect

    from app.providers.provenance_reader import ProvenanceReader

    fuente = inspect.getsource(ProvenanceReader.assertions_for_keys)
    assert "a.negated AS negated" in fuente, (
        "`assertions_for_keys` ha dejado de seleccionar `negated`: el signo se "
        "pierde en el primer salto desde el grafo. Si ha sido un refactor "
        "legítimo, la garantía la da la suite de Neo4j real y este recordatorio "
        "hay que reescribirlo, no silenciarlo")
