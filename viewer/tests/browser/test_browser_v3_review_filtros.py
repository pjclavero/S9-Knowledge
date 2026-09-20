# -*- coding: utf-8 -*-
"""E2E de navegador: el contexto de la consola `/v3/review` SOBREVIVE.

QUE CIERRA ESTE FICHERO, Y POR QUE AQUI Y NO EN LA SUITE DE `viewer/tests`.

La consola de revision pierde el filtro de corrida por dos caminos distintos,
y solo uno se puede medir sin navegador:

  · EL `<select>`. Los filtros se reenvian con `onchange="this.form.submit()"`,
    que es JavaScript. Una prueba con `TestClient` puede comprobar que el campo
    oculto ESTA en el formulario, pero no que el navegador lo reenvie: eso solo
    lo dice un navegador de verdad. La primera version de este corte declaro
    ese hueco como «region no observada», y era EVITABLE: este directorio ya
    existe y el job de CI lo ejecuta entero con chromium obligatorio y sin
    permitir un solo skip. Asi que se mide.

  · LA ACCION PRINCIPAL (aprobar, deshacer). Esa si se puede medir sin
    navegador, y se mide en `viewer/tests/test_v3_review_consola_corte.py`.

LO QUE ESTE FICHERO **NO** CUBRE (techo declarado):
  · No ejercita Neo4j: el proveedor de grafo es el `mock` del propio producto y
    el almacen de propuestas es un directorio temporal sembrado por la fixture.
  · Mide el filtro de CORRIDA. Los otros dos filtros viajan por el mismo campo
    oculto y el mismo formulario, pero aqui no se ejercen uno a uno.
"""
from __future__ import annotations

import json
from typing import Iterator

import pytest

from e2e_support import ViewerServer, login_as, start_viewer

WORKSPACE = "browser-alpha"
CORRIDA = "job-navegador-A"

#: El almacen que siembra la fixture de modulo. Lo necesita tambien la
#: fixture de ambito FUNCION que lo repone en cada caso (ver abajo).
_ALMACEN_SEMBRADO: dict[str, str] = {}


def _propuesta(pid: str, source_id: str) -> dict:
    episodio = "Ariadna protege la ciudad de Bruma durante el invierno."
    literal = "protege la ciudad de Bruma"
    inicio = episodio.index(literal)
    return {
        "proposal_id": pid,
        "workspace": WORKSPACE,
        "source_id": source_id,
        "episode_id": f"episode-{pid}",
        "episode_text": episodio,
        "evidence": {"start": inicio, "end": inicio + len(literal),
                     "literal_text": literal},
        "proposal": {"subject": "Ariadna", "predicate": "PROTECTS",
                     "object": "Bruma", "direction": "SUBJECT_TO_OBJECT",
                     "negation": {"negated": False, "type": "NONE"}},
        "engine_decision": {"decision": "REVIEW",
                            "reason_codes": ["AMBIGUOUS_PREDICATE"]},
        "ontology_version": "bruma-ontology-v1",
        "engine_version": "knowledge-v3-test",
    }


@pytest.fixture(scope="module")
def viewer_con_cola(tmp_path_factory) -> Iterator[ViewerServer]:
    """Visor real con un almacen de propuestas SEMBRADO.

    Dos corridas, y dos fuentes distintas dentro de la corrida que se filtra:
    sin dos fuentes el `<select>` de «Fuente» no tendria dos opciones que
    elegir, y el gesto que se quiere ejercer no existiria.
    """
    almacen = tmp_path_factory.mktemp("propuestas-v3")
    (almacen / "a.json").write_text(json.dumps({
        "run": {"job_id": CORRIDA},
        "items": [_propuesta("nav-a0", "source-0"), _propuesta("nav-a1", "source-1")],
    }), encoding="utf-8")
    (almacen / "b.json").write_text(json.dumps({
        "run": {"job_id": "job-navegador-B"},
        "items": [_propuesta("nav-b0", "source-0")],
    }), encoding="utf-8")

    _ALMACEN_SEMBRADO["dir"] = str(almacen)

    servidor = start_viewer(
        tmp_path_factory,
        env={"S9K_V3_REVIEW_PROPOSALS_DIR": str(almacen),
             # LAS DECISIONES TAMBIEN SE AISLAN. Sin esto, `decide` escribe en
             # `viewer/output/reviews-v3/decisions.jsonl` —el arbol del repo— y
             # deja una decision pegada que envenena la siguiente ejecucion: la
             # propuesta aprobada ya no vuelve a salir en la cola y el caso deja
             # de ser el que se mide.
             "S9K_V3_REVIEW_DECISIONS_PATH": str(almacen.parent / "decisions.jsonl"),
             "S9K_DEFAULT_WORKSPACE": WORKSPACE},
    )
    viewer = next(servidor)

    # CONTROL POSITIVO DEL LABORATORIO, ANTES DE ENCENDER EL NAVEGADOR.
    #
    # El primer intento de este fichero se cayó en CI con `fichas=0,
    # almacen_caido=True`, y el sintoma en la UI no decia CUAL de los eslabones
    # habia fallado. Aqui se comprueban los dos que pueden romperse sin que la
    # pantalla lo explique, y cada uno dice su causa:
    #
    #   1. que la ruta EFECTIVA del almacen sea la sembrada (si no, el visor
    #      esta mirando `viewer/output/reviews-v3/proposals`, que esta en
    #      `.gitignore` y en un checkout limpio NO EXISTE);
    #   2. que el servicio SEPA leerla.
    #
    # Sin esto, un fallo de laboratorio se disfraza de fallo de producto.
    from app.services.v3_review import ReviewService, default_proposals_dir

    efectiva = default_proposals_dir()
    assert efectiva == almacen, (
        "el visor no esta mirando el almacen sembrado por esta fixture, sino "
        f"{efectiva!r}. Si es `viewer/output/...`, la variable "
        "`S9K_V3_REVIEW_PROPOSALS_DIR` no ha llegado al servidor"
    )
    cola = ReviewService().queue(WORKSPACE, job_id=CORRIDA)
    assert len(cola.items) == 2, (
        "el laboratorio no tiene cola que enseniar antes de abrir el "
        f"navegador: items={len(cola.items)} total={cola.total}. El defecto "
        "esta en la siembra, no en la pantalla"
    )

    try:
        yield viewer
    finally:
        for _ in servidor:
            pass


@pytest.fixture(autouse=True)
def _el_almacen_sembrado_manda(viewer_con_cola, monkeypatch):
    """LA VENTANA ENTRE LA FIXTURE Y LA PETICION, CERRADA. Causa MEDIDA.

    El `conftest.py` de la raiz tiene una fixture AUTOUSE y de ambito FUNCION
    que redirige `S9K_V3_REVIEW_PROPOSALS_DIR` a un almacen propio de CADA caso
    —y hace bien: sin ella, un caso que corre una ingesta escribiria en el
    almacen real del repositorio, y un almacen compartido contamina entre
    casos—.

    Pero `viewer_con_cola` es de ambito MODULO, asi que se monta ANTES: siembra
    su almacen, sus dos controles positivos pasan... y despues, para cada caso,
    la autouse de la raiz apunta la variable a un directorio vacio. De ahi el
    sintoma que costo dos intentos entender: el almacen estaba bien EN TIEMPO
    DE FIXTURE y roto EN TIEMPO DE PETICION.

    Esto no es un apaño: es exactamente lo que esa fixture documenta que hay
    que hacer —«un test que quiera fijar el suyo vuelve a declarar la variable
    en su propio fixture, que corre despues de este y manda sobre el»—. Al ser
    de ambito funcion y estar en el modulo, corre DESPUES de la de la raiz.
    """
    monkeypatch.setenv("S9K_V3_REVIEW_PROPOSALS_DIR", _ALMACEN_SEMBRADO["dir"])


@pytest.fixture()
def revisor(page, viewer_con_cola):
    """La consola que DECIDE pide rol reviewer o admin."""
    login_as(page, viewer_con_cola, "s9reviewer")
    return page


def _abrir_con_corrida(page, viewer: ViewerServer):
    page.goto(viewer.url(f"/v3/review?workspace={WORKSPACE}&job_id={CORRIDA}"))
    page.wait_for_selector("form.v3r-filters")


def _diagnostico(page) -> str:
    """Por que la pantalla no trae lo que se esperaba, en una linea.

    Un rojo que solo dice «no trae 2 fichas» no distingue «el almacen no se
    leyo» de «el ambito recorto» de «el filtro no caso». Las tres se arreglan
    en sitios distintos, asi que el mensaje las separa.
    """
    import os

    from app.services.v3_review import ReviewService, default_proposals_dir

    # EL ESTADO DEL ALMACEN **EN TIEMPO DE PETICION**, no en tiempo de fixture.
    # El servidor corre en un hilo de ESTE proceso, asi que esto lee justo lo
    # que el visor acaba de leer. La ventana entre fixture y peticion es donde
    # se perdio el almacen la vez anterior, y sin medirla el rojo no dice nada.
    try:
        efectiva = default_proposals_dir()
        existe = efectiva.exists()
        contenido = sorted(p.name for p in efectiva.iterdir()) if existe else []
    except Exception as exc:  # noqa: BLE001 - es un diagnostico, no una garantia
        efectiva, existe, contenido = f"<{type(exc).__name__}>", False, []
    try:
        cola = len(ReviewService().queue(WORKSPACE, job_id=CORRIDA).items)
    except Exception as exc:  # noqa: BLE001
        cola = f"<{type(exc).__name__}: {getattr(exc, 'code', '')}>"

    codigo = page.locator("[data-almacen-code]")
    return (
        f"url={page.url!r} "
        f"fichas={page.locator('[data-review-item]').count()} "
        f"almacen_caido={page.locator('[data-state=\"unavailable\"]').count() > 0} "
        f"codigo_almacen={codigo.first.get_attribute('data-almacen-code') if codigo.count() else None!r} "
        f"recuento={page.locator('[data-recuento]').inner_text() if page.locator('[data-recuento]').count() else None!r} "
        f"opciones_workspace={page.locator('form.v3r-filters select[name=\"workspace\"] option').count()} "
        f"| EN PETICION: env={os.environ.get('S9K_V3_REVIEW_PROPOSALS_DIR')!r} "
        f"dir_efectivo={str(efectiva)!r} existe={existe} contenido={contenido} "
        f"queue_directa={cola}"
    )


def test_el_filtro_de_corrida_sobrevive_a_tocar_el_select_de_fuente(
    revisor, viewer_con_cola,
):
    """EL GESTO REAL: el operador toca «Fuente» y el navegador reenvia el form.

    Antes de este corte el `job_id` no estaba en el formulario, asi que este
    reenvio lo borraba EN SILENCIO y la cola se ensanchaba sola. Aqui lo
    reenvia un navegador de verdad, disparando el `onchange`, no un cliente
    que fabrica la peticion a mano.
    """
    _abrir_con_corrida(revisor, viewer_con_cola)

    # SE DEMUESTRA PRIMERO EL CASO: la pantalla esta filtrada de verdad.
    assert revisor.locator("[data-filtro-corrida]").count() == 1, (
        "la pantalla de partida no declara el filtro de corrida, asi que lo "
        f"que se mida despues no dira nada de si sobrevive. {_diagnostico(revisor)}"
    )
    assert revisor.locator("[data-review-item]").count() == 2, (
        f"el caso no es el que se mide: la corrida filtrada no trae 2 fichas. "
        f"{_diagnostico(revisor)}"
    )

    # EL GESTO. `select_option` dispara el evento `change` del navegador, que
    # es lo que ejecuta `this.form.submit()`.
    revisor.locator('form.v3r-filters select[name="source_id"]').select_option(
        "source-0"
    )
    revisor.wait_for_url("**source_id=source-0**")

    assert f"job_id={CORRIDA}" in revisor.url, (
        "el navegador reenvio el formulario de filtros SIN el `job_id`: el "
        f"filtro de corrida se perdio al tocar «Fuente». URL: {revisor.url}"
    )
    assert revisor.locator("[data-filtro-corrida]").count() == 1, (
        "tras el reenvio la pantalla ya no declara el filtro de corrida"
    )
    assert revisor.locator("[data-review-item]").count() == 1, (
        "la cola no se ha estrechado a la fuente elegida dentro de la corrida: "
        "o el filtro de corrida se perdio, o el de fuente no se aplico"
    )


def test_quitar_el_filtro_de_corrida_lo_quita_de_verdad(revisor, viewer_con_cola):
    """EL ERROR SIMETRICO: que el arreglo pegue un filtro que el operador quito.

    Un campo oculto pegajoso sin forma de soltarlo es una carcel. El enlace de
    la pantalla tiene que devolver la cola de TODAS las corridas.
    """
    _abrir_con_corrida(revisor, viewer_con_cola)
    revisor.locator("[data-quitar-filtro-corrida]").click()
    revisor.wait_for_selector("form.v3r-filters")

    assert "job_id" not in revisor.url, (
        f"el filtro de corrida sobrevive a quitarlo: {revisor.url}"
    )
    assert revisor.locator("[data-filtro-corrida]").count() == 0, (
        "la pantalla sigue declarando un filtro de corrida que ya no hay"
    )
    assert revisor.locator("[data-review-item]").count() == 3, (
        f"tras quitar el filtro no se ven las propuestas de todas las corridas. "
        f"{_diagnostico(revisor)}"
    )


def test_decidir_en_el_navegador_no_ensancha_la_cola_ni_pierde_la_corrida(
    revisor, viewer_con_cola,
):
    """EL RECORRIDO ENTERO, CON EL GESTO QUE DECIDE.

    Cola visible -> se aprueba una propuesta con el boton de verdad -> el
    navegador sigue el 303 -> el filtro de corrida sigue puesto y la cola se ha
    ESTRECHADO (no ensanchado). Es H-1 medido en navegador, no con un cliente
    que fabrica el POST.
    """
    _abrir_con_corrida(revisor, viewer_con_cola)
    # SIN ACOPLE AL ORDEN. Este caso APRUEBA, y aprobar cambia el estado que
    # comparte el modulo. En vez de exigir un 2 que depende de que ninguna
    # prueba anterior haya decidido, se toma el ANTES y se exige ANTES-1: la
    # propiedad que se mide —la cola se estrecha, no se ensancha— es la misma y
    # ya no se rompe si alguien reordena el fichero.
    antes = revisor.locator("[data-review-item]").count()
    assert antes >= 2, (
        "el caso no es el que se mide: hacen falta al menos 2 propuestas en la "
        f"corrida para poder aprobar una y seguir viendo cola. {_diagnostico(revisor)}"
    )

    # El boton real de la primera ficha visible.
    revisor.locator('form.v3r-decision button[value="APPROVE"]').first.click()
    revisor.wait_for_selector("form.v3r-filters")

    assert f"job_id={CORRIDA}" in revisor.url, (
        "tras DECIDIR en el navegador se ha perdido la corrida: el operador "
        f"vuelve a la cola entera. {_diagnostico(revisor)}"
    )
    assert revisor.locator("[data-filtro-corrida]").count() == 1, (
        f"la pantalla ya no declara el filtro de corrida. {_diagnostico(revisor)}"
    )
    assert revisor.locator("[data-review-item]").count() == antes - 1, (
        f"la cola no se ha estrechado de {antes} a {antes - 1} tras aprobar: "
        "se ha ensanchado sola por un clic del propio operador. "
        f"{_diagnostico(revisor)}"
    )


def test_la_consola_nunca_ofrece_un_enlace_con_workspace_None(
    revisor, viewer_con_cola,
):
    """`?workspace=None` es una cadena literal que no es ningun workspace.

    Lo encontro un instrumento de navegador en el intento anterior de este
    mismo fichero, recorriendo el gesto de quitar el filtro.
    """
    _abrir_con_corrida(revisor, viewer_con_cola)
    assert "workspace=None" not in revisor.content(), (
        f"la pantalla ofrece un enlace roto. {_diagnostico(revisor)}"
    )
    revisor.locator("[data-quitar-filtro-corrida]").click()
    revisor.wait_for_selector("form.v3r-filters")
    assert "workspace=None" not in revisor.url, (
        f"quitar el filtro lleva a un workspace literal «None»: {revisor.url}"
    )
