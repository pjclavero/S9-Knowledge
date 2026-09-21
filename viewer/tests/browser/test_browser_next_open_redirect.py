# -*- coding: utf-8 -*-
r"""E2E de navegador: el destino interno legitimo SOBREVIVE al navegador.

POR QUE ESTE FICHERO EXISTE, Y POR QUE NO BASTA LA SUITE SIN NAVEGADOR
----------------------------------------------------------------------
`viewer/tests/test_next_url_open_redirect.py` mide la cabecera `Location` de la
respuesta HTTP. Eso ya es mucho mas que preguntarle a `_safe_next()` que string
devuelve, pero sigue sin ser la pregunta final, porque quien tiene la ultima
palabra sobre a donde va el usuario no es nuestro parser: es el navegador. Aqui
se mide el destino al que un Chromium de verdad acaba llegando.

LA CAUSA, BIEN ATRIBUIDA (costo tres vueltas, y la tercera fue la medida)
--------------------------------------------------------------------------
Aqui se dijo primero que `/\evil.example/x` escapa porque Chrome normaliza `\`
a `/`. Por la cabecera `Location` eso NO ocurre: Starlette percent-encodea la
backslash, el navegador recibe `/%5Cevil.example/x` y no hay backslash que
normalizar. La normalizacion es real —bajo WHATWG, `/\evil…` CRUDO si saca del
sitio—, pero por esta ruta el navegador nunca la recibe cruda. Lo neutraliza el
transporte, no el validador.

Despues se dijo que tampoco `///evil.example/x` sacaba a Chromium del sitio, y
que por tanto no existia negativo de navegador posible. **Tambien era falso, y
la causa era un ARNES CIEGO** (ver el techo). Con el arnes arreglado, Chromium
SALE con `//`, `///` y `////`, igual que `curl`, `fetch` y el parser WHATWG. No
habia outlier de motor: habia un instrumento que no veia.

De modo que los negativos de navegador EXISTEN y estan aqui: `///` y `////`.
Su calibracion —que se ponen rojos al retirar la defensa, y que el arnes es
capaz de ver una fuga— vive en `test_browser_next_calibracion.py`.

COMO SE OBSERVA LA FUGA
-----------------------
El dominio hostil RESUELVE a un servidor trampa propio
(`--host-resolver-rules`), y la fuga se observa por la cabecera `Host` que
recibe la trampa y por `page.url`. Ver `e2e_support.servidor_trampa`.

TECHO DECLARADO — QUE **NO** CUBRE ESTE FICHERO
-----------------------------------------------
- **TODO ARNES QUE MIDA AUSENCIA LLEVA UN CONTROL POSITIVO DE RESULTADO
  CONOCIDO DENTRO DE LA PROPIA TABLA. Si el control conocido no se detecta, el
  arnes esta ciego y sus ceros no valen.** Esta escrito como techo porque aqui
  costo caro: el arnes anterior observaba peticiones abortadas contra un
  dominio que NO RESUELVE, la navegacion moria en DNS, la lista quedaba vacia y
  eso se leia como «se quedo dentro». Declaraba interno hasta
  `//evil.example/x`, que escapa en todos los instrumentos. Lo que lo destapo
  no fue razonar mejor, sino meter en la tabla un caso cuyo resultado se sabia
  de antemano. El control vive ahora en `test_browser_next_calibracion.py`.
- Un unico motor: chromium. Nada dice de Firefox ni de Safari.
- Cubre `POST /login`. `POST /partida/select` y `GET /login` se miden por
  cabecera y por HTML en la suite sin navegador, NO aqui.
- Los negativos son `///` y `////`. La backslash y sus codificaciones NO
  discriminan por esta superficie (Starlette las codifica), y eso esta medido
  en el fichero de calibracion; su rechazo se mide sobre la cabecera.
- No prueba nada sobre autorizacion: que el destino sea interno no dice que el
  usuario pueda verlo.
- **Estas pruebas ERRORAN, no se saltan, si no hay chromium**, y es una
  DECISIÓN, no un descuido. Lanzan su propio navegador (necesitan
  `--host-resolver-rules`) en vez de pasar por la fixture `page` compartida,
  que es la que trae el guardia de «chromium no disponible -> skip». En CI da
  igual, porque chromium siempre está y la puerta prohíbe los skips; fuera de
  CI, preferimos el error ruidoso. La lección entera de este microcarril es que
  un verde incapaz de fallar no vale nada, y un módulo de seguridad que se
  salta en silencio es exactamente eso. Si algún día molestara, el arreglo es
  añadir el guardia aquí a propósito, no descubrirlo por accidente.
"""
from __future__ import annotations

import json
from typing import Iterator

import pytest

from e2e_support import (
    DOMINIO_HOSTIL,
    ViewerServer,
    navegador_que_resuelve_lo_hostil,
    salio_del_producto,
    servidor_trampa,
    start_viewer,
)

WORKSPACE = "browser-redir"
CORRIDA = "job-redir-A"

#: Dominio de ejemplo (RFC 2606). Solo resuelve dentro de este laboratorio,
#: y a la trampa: ver `e2e_support.servidor_trampa`.
HOSTIL = DOMINIO_HOSTIL

_ALMACEN_SEMBRADO: dict[str, str] = {}


def _propuesta(pid: str) -> dict:
    episodio = "Ariadna protege la ciudad de Bruma durante el invierno."
    literal = "protege la ciudad de Bruma"
    inicio = episodio.index(literal)
    return {
        "proposal_id": pid,
        "workspace": WORKSPACE,
        "source_id": "source-0",
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
def viewer_redir(tmp_path_factory) -> Iterator[ViewerServer]:
    """Visor real con una cola sembrada, para que el positivo aterrice en algo."""
    almacen = tmp_path_factory.mktemp("propuestas-redir")
    (almacen / "a.json").write_text(json.dumps({
        "run": {"job_id": CORRIDA},
        "items": [_propuesta("redir-a0"), _propuesta("redir-a1")],
    }), encoding="utf-8")
    _ALMACEN_SEMBRADO["dir"] = str(almacen)

    servidor = start_viewer(
        tmp_path_factory,
        env={
            "S9K_V3_REVIEW_PROPOSALS_DIR": str(almacen),
            # Sin esto, `decide` escribiria en el arbol del repositorio.
            "S9K_V3_REVIEW_DECISIONS_PATH": str(almacen.parent / "decisions.jsonl"),
            "S9K_DEFAULT_WORKSPACE": WORKSPACE,
        },
    )
    viewer = next(servidor)

    # Control positivo del laboratorio ANTES de encender el navegador: si la
    # cola no existe, el rojo del positivo seria de siembra y no de producto.
    from app.services.v3_review import ReviewService, default_proposals_dir
    efectiva = default_proposals_dir()
    assert efectiva == almacen, (
        "el visor no mira el almacen sembrado sino "
        f"{efectiva!r}: `S9K_V3_REVIEW_PROPOSALS_DIR` no llego al servidor"
    )
    cola = ReviewService().queue(WORKSPACE, job_id=CORRIDA)
    assert len(cola.items) == 2, (
        f"laboratorio sin cola antes de abrir el navegador: items={len(cola.items)}"
    )

    try:
        yield viewer
    finally:
        for _ in servidor:
            pass


@pytest.fixture(autouse=True)
def _el_almacen_sembrado_manda(viewer_redir, monkeypatch):
    """La autouse de AMBITO FUNCION del `conftest.py` de la raiz redirige
    `S9K_V3_REVIEW_PROPOSALS_DIR` DESPUES de que esta fixture de MODULO haya
    sembrado. Se vuelve a declarar aqui, en ambito funcion, que es justo lo que
    aquella fixture documenta que hay que hacer."""
    monkeypatch.setenv("S9K_V3_REVIEW_PROPOSALS_DIR", _ALMACEN_SEMBRADO["dir"])


def _login_con_next(page, viewer: ViewerServer, next_valor: str):
    """Login por el formulario real, con `next` CODIFICADO en la query.

    Se codifica a proposito: interpolar el valor crudo partiria en parametros
    sueltos un destino con `?` y `&` —justo el positivo que hay que defender— y
    la prueba mediria otra cosa.
    """
    from urllib.parse import urlencode

    from playwright.sync_api import Error as PlaywrightError

    page.goto(viewer.url("/login?" + urlencode({"next": next_valor})))
    page.fill("#username", "s9reviewer")
    page.fill("#password", viewer.users["s9reviewer"]["password"])
    page.click("#login-submit")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightError:
        # Que la navegacion no llegue a estabilizarse NO es el resultado: el
        # resultado lo dicen la trampa y `page.url`, que ya estan observados.
        pass
    return page


@pytest.fixture()
def trampa():
    with servidor_trampa() as (servidor, puerto):
        yield servidor, puerto


@pytest.fixture()
def pagina_con_trampa(trampa):
    """Chromium propio con `evil.example` resolviendo a la trampa.

    No sirve la fixture `browser` compartida: hace falta
    `--host-resolver-rules`, que es lo que impide que el arnes quede ciego.
    """
    from playwright.sync_api import sync_playwright

    _servidor, puerto = trampa
    with sync_playwright() as p:
        navegador = navegador_que_resuelve_lo_hostil(p, puerto)
        try:
            contexto = navegador.new_context()
            yield contexto.new_page()
        finally:
            navegador.close()


# ---------------------------------------------------------------------------
# POSITIVO
# ---------------------------------------------------------------------------

def test_navegador_vuelve_a_la_consola_filtrada(pagina_con_trampa, viewer_redir,
                                                trampa):
    """Login con `next` = consola filtrada -> el navegador aterriza AHI."""
    destino = f"/v3/review?workspace={WORKSPACE}&job_id={CORRIDA}"
    servidor, _ = trampa
    page = _login_con_next(pagina_con_trampa, viewer_redir, destino)

    salio, evidencia = salio_del_producto(page, servidor)
    assert not salio, f"la sesion de laboratorio salio del visor: {evidencia!r}"
    assert page.url == viewer_redir.url(destino), (
        f"EL DESTINO INTERNO NO SOBREVIVIO AL NAVEGADOR: tras el login la URL "
        f"efectiva es {page.url!r} y se esperaba {viewer_redir.url(destino)!r}. "
        f"Los filtros de la consola (`workspace` y `job_id`) viajan en la query "
        f"de `next`; si el validador los descarta, el operador pierde su "
        f"contexto en cada caducidad de sesion."
    )
    page.wait_for_selector("form.v3r-filters")
    fichas = page.locator("[data-review-item]").count()
    assert fichas == 2, (
        f"la consola filtrada cargo pero muestra {fichas} fichas y el "
        f"laboratorio sembro 2: el `next` llego pero el filtro no se aplico "
        f"como lo aplicaria el operador."
    )


# ---------------------------------------------------------------------------
# NEGATIVOS. Existen, discriminan, y estan calibrados en
# `test_browser_next_calibracion.py` —que ademas comprueba que el arnes no
# esta ciego antes de que ningun «no salio» de aqui signifique algo—.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("etiqueta,hostil", [
    ("tres barras", f"///{HOSTIL}/x"),
    ("cuatro barras", f"////{HOSTIL}/x"),
], ids=["tres barras", "cuatro barras"])
def test_navegador_no_sale_del_producto(pagina_con_trampa, viewer_redir, trampa,
                                        etiqueta, hostil):
    servidor, _ = trampa
    page = _login_con_next(pagina_con_trampa, viewer_redir, hostil)

    salio, evidencia = salio_del_producto(page, servidor)
    assert not salio, (
        f"REDIRECCION ABIERTA CONFIRMADA POR EL NAVEGADOR: con next={hostil!r} "
        f"[{etiqueta}] Chromium acabo FUERA del producto. Evidencia: "
        f"{evidencia!r}. Da igual que `_safe_next()` considerase esa cadena una "
        f"ruta interna: quien interpreta `Location` es el navegador, y salta "
        f"todas las barras iniciales al entrar en la autoridad."
    )
    assert page.url.startswith(viewer_redir.base_url), (
        f"[{etiqueta}] la URL efectiva tras el login es {page.url!r}, que no "
        f"pertenece al origen del producto ({viewer_redir.base_url!r})."
    )
