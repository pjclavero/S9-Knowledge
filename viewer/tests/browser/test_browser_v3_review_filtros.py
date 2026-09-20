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

    servidor = start_viewer(
        tmp_path_factory,
        env={"S9K_V3_REVIEW_PROPOSALS_DIR": str(almacen),
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
    return (
        f"url={page.url!r} "
        f"fichas={page.locator('[data-review-item]').count()} "
        f"almacen_caido={page.locator('[data-state=\"unavailable\"]').count() > 0} "
        f"recuento={page.locator('[data-recuento]').inner_text() if page.locator('[data-recuento]').count() else None!r} "
        f"opciones_workspace={page.locator('form.v3r-filters select[name=\"workspace\"] option').count()}"
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
