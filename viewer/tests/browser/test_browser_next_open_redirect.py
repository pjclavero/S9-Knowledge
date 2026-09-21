# -*- coding: utf-8 -*-
r"""E2E de navegador: `next` NUNCA saca al usuario del producto.

POR QUE ESTE FICHERO EXISTE, Y POR QUE NO BASTA LA SUITE SIN NAVEGADOR
----------------------------------------------------------------------
`viewer/tests/test_next_url_open_redirect.py` mide la cabecera `Location` de la
respuesta HTTP. Eso ya es mucho mas que preguntarle a `_safe_next()` que string
devuelve, pero sigue sin ser la pregunta final, porque quien tiene la ultima
palabra sobre a donde va el usuario no es nuestro parser: es el navegador. Aqui
se mide el destino al que un Chromium de verdad acaba llegando.

LA CAUSA, BIEN ATRIBUIDA (la primera version de este docstring la tenia mal)
----------------------------------------------------------------------------
Se decia aqui que `/\evil.example/x` escapa porque Chrome normaliza `\` a `/`.
Por la cabecera `Location` ESO NO OCURRE, y esta medido: Starlette
percent-encodea la backslash, el navegador recibe `/%5Cevil.example/x` y no hay
ninguna backslash que normalizar. Esa normalizacion es real en otros contextos
—un `href` crudo, por ejemplo—, pero no en este.

Lo que SI escapa por esta superficie, medido con la defensa retirada en
`test_browser_next_calibracion.py`, es la barra repetida: `///evil.example/x`.
Un navegador salta todas las barras iniciales al entrar en la autoridad y lee
`evil.example` como host. Por eso los negativos DE NAVEGADOR de este fichero
son `///` y `////` y no la backslash: son los unicos que se pondrian rojos si
la defensa cayera, y un negativo que no puede ponerse rojo no guarda nada.

La backslash y sus codificaciones siguen siendo rechazos OBLIGATORIOS del
validador —se miden sobre la cabecera, en la suite sin navegador, donde si
discriminan—, pero no caben aqui como negativos.

COMO SE OBSERVA LA FUGA SIN TOCAR LA RED
----------------------------------------
Se intercepta TODA peticion y se aborta la que no vaya a 127.0.0.1, anotandola.
Dos consecuencias buenas: la prueba no depende de DNS ni sale a internet (el
dominio es de ejemplo y no existe), y la fuga queda registrada aunque el
navegador no llegue a cargar nada. Si `evil.example` aparece en esa lista, el
usuario se habria ido: eso es la redireccion abierta.

TECHO DECLARADO — QUE **NO** CUBRE ESTE FICHERO
-----------------------------------------------
- Un unico motor: chromium. Nada dice de Firefox ni de Safari; la normalizacion
  `\\` -> `/` la hacen tambien, pero aqui no se mide.
- Cubre `POST /login`. `POST /partida/select` y `GET /login` se miden por
  cabecera y por HTML en la suite sin navegador, NO aqui: este fichero no debe
  leerse como si les diera cobertura de navegador.
- Mide la tabla por muestreo, y solo los casos que DISCRIMINAN en esta
  superficie (`///` y `////`). La tabla COMPLETA vive en la suite sin
  navegador; cual de los casos discrimina y cual no, medido, en
  `test_browser_next_calibracion.py`.
- No prueba nada sobre autorizacion: que el destino sea interno no dice que el
  usuario pueda verlo.
"""
from __future__ import annotations

import json
from typing import Iterator

import pytest

from e2e_support import ViewerServer, start_viewer

WORKSPACE = "browser-redir"
CORRIDA = "job-redir-A"

#: Dominio de ejemplo (RFC 2606). No existe y no se resuelve nunca.
HOSTIL = "evil.example"

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

    Se codifica a proposito: `do_login` de `e2e_support` interpola el valor
    crudo, asi que un destino con `?` y `&` —justo el positivo que hay que
    defender— se partiria en parametros sueltos y la prueba mediria otra cosa.
    Codificado, el servidor recibe EXACTAMENTE la cadena que se quiere probar.
    """
    from urllib.parse import urlencode

    from playwright.sync_api import TimeoutError as PWTimeout

    page.goto(viewer.url("/login?" + urlencode({"next": next_valor})))
    page.fill("#username", "s9reviewer")
    page.fill("#password", viewer.users["s9reviewer"]["password"])
    page.click("#login-submit")
    try:
        page.wait_for_load_state("networkidle")
    except PWTimeout:
        # Si el navegador se fue a un destino que `_vigilar_salidas` aborta, la
        # navegacion nunca queda «idle». Eso NO es el fallo que hay que
        # reportar: el fallo es la fuga, y lo dice el `assert` del caso con su
        # causa. Tragarse el timeout aqui evita que un rojo legitimo llegue
        # disfrazado de «timeout esperando la red», que se lee igual que un
        # rojo sin causa.
        pass
    return page


def _vigilar_salidas(page, viewer: ViewerServer) -> list:
    """Aborta y anota toda peticion que no vaya al propio visor."""
    fugas: list = []

    def _manejar(route, request):
        if request.url.startswith(viewer.base_url):
            route.continue_()
        else:
            fugas.append(request.url)
            route.abort()

    page.route("**/*", _manejar)
    return fugas


# ---------------------------------------------------------------------------
# POSITIVO
# ---------------------------------------------------------------------------

def test_navegador_vuelve_a_la_consola_filtrada(page, viewer_redir):
    """Login con `next` = consola filtrada -> el navegador aterriza AHI."""
    destino = f"/v3/review?workspace={WORKSPACE}&job_id={CORRIDA}"
    fugas = _vigilar_salidas(page, viewer_redir)
    _login_con_next(page, viewer_redir, destino)

    assert not fugas, f"la sesion de laboratorio salio del visor: {fugas}"
    assert page.url == viewer_redir.url(destino), (
        f"EL DESTINO INTERNO NO SOBREVIVIO AL NAVEGADOR: tras el login la URL "
        f"efectiva es {page.url!r} y se esperaba {viewer_redir.url(destino)!r}. "
        f"Los filtros de la consola (`workspace` y `job_id`) viajan en la query "
        f"de `next`; si el validador los descarta, el operador pierde su "
        f"contexto en cada caducidad de sesion."
    )
    page.wait_for_selector("form.v3r-filters")
    # `[data-review-item]`, que es como la consola `/v3/review` marca cada
    # ficha. Un selector inventado cuenta 0 y da un rojo cuyo mensaje culpa al
    # filtro: rojo por la razon equivocada. MEDIDO en CI: con
    # `[data-proposal-id]` —que existe, pero en las plantillas del CHASIS, no
    # en esta— este caso fallaba con «0 fichas» estando el producto bien.
    fichas = page.locator("[data-review-item]").count()
    assert fichas == 2, (
        f"la consola filtrada cargo pero muestra {fichas} fichas y el "
        f"laboratorio sembro 2: el `next` llego pero el filtro no se aplico "
        f"como lo aplicaria el operador."
    )


# ---------------------------------------------------------------------------
# NEGATIVOS — el navegador es quien decide, y decide quedarse dentro
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("etiqueta,hostil", [
    ("tres barras", f"///{HOSTIL}/x"),
    ("cuatro barras", f"////{HOSTIL}/x"),
], ids=lambda v: v if isinstance(v, str) else str(v))
def test_navegador_no_sale_del_producto(page, viewer_redir, etiqueta, hostil):
    fugas = _vigilar_salidas(page, viewer_redir)
    _login_con_next(page, viewer_redir, hostil)

    assert not any(HOSTIL in u for u in fugas), (
        f"REDIRECCION ABIERTA CONFIRMADA POR EL NAVEGADOR: con next={hostil!r} "
        f"[{etiqueta}] Chromium intento navegar a {fugas!r}, es decir, FUERA del "
        f"producto. Da igual que `_safe_next()` considerase esa cadena una ruta "
        f"interna: quien interpreta `Location` es el navegador, y salta todas "
        f"las barras iniciales al entrar en la autoridad."
    )
    assert page.url.startswith(viewer_redir.base_url), (
        f"REDIRECCION ABIERTA CONFIRMADA POR EL NAVEGADOR: con next={hostil!r} "
        f"[{etiqueta}] la URL efectiva tras el login es {page.url!r}, que no "
        f"pertenece al origen del producto ({viewer_redir.base_url!r})."
    )
    assert HOSTIL not in page.url, (
        f"[{etiqueta}] el dominio externo aparece en la URL final: {page.url!r}"
    )
