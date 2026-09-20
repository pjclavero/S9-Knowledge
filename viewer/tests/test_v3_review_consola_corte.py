"""CORTE · La consola `/v3/review` dice la verdad sobre lo que muestra y oculta.

LA PROPIEDAD QUE ESTOS TESTIGOS DEFIENDEN
-----------------------------------------
`/v3/review` es la consola que DECIDE (`/panel/review` es de sólo lectura por
contrato declarado). Un corte anterior puso el enlace que lleva hasta aquí con
la corrida puesta; esto cierra lo que pasa una vez DENTRO:

  E-1. LA CABECERA NO PUEDE CONTRADECIR A LA LISTA. Medido sobre el HTML
       servido, antes de este corte:

           sin filtro                  items=4  cabecera='4 pendientes de 4'
           job_id que NO casa          items=0  cabecera='4 pendientes de 4'
           source_id que NO casa       items=0  cabecera='4 pendientes de 4'
           engine_decision que NO casa items=0  cabecera='4 pendientes de 4'

       La cabecera IGNORABA los tres filtros. Falsa confirmación: la pantalla
       se desmentía a sí misma sobre una lista vacía.

  D-2. EL FILTRO DE CORRIDA, DECLARADO Y PEGAJOSO. Medido: con `job_id` puesto,
       la cadena no aparecía en NINGUNA parte del HTML (la pantalla no decía
       que había un filtro) y el formulario de filtros no lo llevaba, así que
       tocar «Fuente» borraba el `job_id` EN SILENCIO y la cola se ensanchaba
       sola. Un cambio de estado no declarado, provocado por un clic del propio
       operador.

  H-1. Y LO MISMO POR LA PUERTA PRINCIPAL. Medido por efecto:

           GET  ?workspace=alpha&job_id=job-A -> 2 fichas, filtro declarado
           POST /v3/review/decide (APPROVE)   -> 303 a ?workspace=alpha
           GET  de ese destino                -> 3 fichas, filtro AUSENTE

       La cola se ensanchaba de 2 a 3 porque el operador había APROBADO algo,
       no porque hubiera tocado un filtro. Ningún formulario POST llevaba los
       filtros y el redirect codificaba a mano sólo el `workspace`, así que
       tiraba también `source_id` y `engine_decision`.

POR QUÉ ESTOS TESTIGOS PIDEN LA PANTALLA
----------------------------------------
Las garantías son VISIBLES: viven en la plantilla y en el redirect, no en el
servicio. Un testigo que se conformara con el `QueueView` que devuelve
`ReviewService` seguiría verde con la cabecera borrada — ya pasó en este
programa. Por eso aquí se hace GET del HTML, se lee el marcado, y donde hay una
acción se RECORRE EL POST y se SIGUE EL REDIRECT.

LO QUE ESTOS TESTIGOS **NO** CUBREN (techo declarado)
-----------------------------------------------------
  · **JavaScript.** El `onchange="this.form.submit()"` de los selects no se
    dispara aquí. Lo que esta suite mide es que el filtro ESTÁ en el
    formulario, que es lo que el navegador reenviaría. El gesto REAL —tocar
    «Fuente» y que el navegador reenvíe— se mide en
    `viewer/tests/browser/test_browser_v3_review_filtros.py`, con chromium de
    verdad; ese fichero declara a su vez su propio techo. Esta suite, por sí
    sola, NO cubre el reenvío.
  · **Infraestructura real.** El almacén de propuestas es un directorio
    temporal y no hay Neo4j. Capa alcanzada: usable desde el producto (HTTP +
    plantilla reales), no «ejercida contra infra real».
  · **Autorización.** El negativo de ámbito muere por la barrera de PARTIDA y
    no dice nada de las demás puertas. Y es una GUARDA DE REGRESIÓN de una
    propiedad que ya existía en la base, no la prueba de un arreglo de este
    corte.
  · **El resto de la consola.** Estos testigos miran el recuento, los filtros y
    su supervivencia. No dicen nada del cuerpo de la ficha, de la corrección,
    del glosario ni del apply.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import v3_review as router_module
from app.services.v3_review import ReviewService
from test_v3_review import proposal


def _escribir(directorio: Path, corrida: str, propuestas: list[dict]) -> None:
    """Un paquete con su bloque `run`.

    `package_runs` NO se escribe a mano en la propuesta: lo deriva
    `load_proposals` del sobre del paquete. Poner la clave directamente en el
    documento produce un testigo que mide una atribución que el producto nunca
    habría construido (se comprobó: con la clave a mano, el filtro que SÍ casa
    devolvía 0).
    """
    directorio.joinpath(f"{corrida}.json").write_text(
        json.dumps({"run": {"job_id": corrida}, "items": propuestas}, ensure_ascii=False),
        encoding="utf-8",
    )


@pytest.fixture
def consola(monkeypatch, tmp_path, lector_por_dependencia):
    """Cuatro propuestas pendientes en `alpha`: dos por corrida, dos por fuente."""
    directorio = tmp_path / "proposals"
    directorio.mkdir()
    _escribir(directorio, "job-A", [
        proposal("pa0", workspace="alpha", source_id="source-0"),
        proposal("pa1", workspace="alpha", source_id="source-1"),
    ])
    _escribir(directorio, "job-B", [
        proposal("pb0", workspace="alpha", source_id="source-0"),
        proposal("pb1", workspace="alpha", source_id="source-1"),
    ])
    servicio = ReviewService(directorio, tmp_path / "decisions.jsonl")
    monkeypatch.setattr(router_module, "_service", lambda: servicio)
    # `chassis_nav` lo instala el chasis en el entorno Jinja compartido al
    # construir la app real; sin importarlo, esta plantilla se queda sin global.
    import app.main  # noqa: F401

    app = FastAPI()
    app.include_router(router_module.router)
    lector_por_dependencia(app)
    return TestClient(app), directorio


def _fichas(html: str) -> int:
    return html.count("data-review-item")


def _campos(html: str, patron: str) -> dict[str, str]:
    """Los campos que un formulario de la pantalla lleva DE VERDAD.

    Se envía lo que el formulario trae, no un diccionario a mano. Un POST
    construido con campos inventados mide una petición que el navegador nunca
    habría hecho — y este defecto vive justo en lo que el formulario OLVIDA
    llevar, así que fabricarlo lo taparía.
    """
    formulario = re.search(patron, html, re.S)
    assert formulario is not None, f"no está el formulario {patron!r} en la pantalla"
    return dict(re.findall(r'name="([^"]+)" value="([^"]*)"', formulario.group(0)))


def _aprobar(cliente, html: str) -> str:
    """Aprueba la primera propuesta y devuelve el `Location` del 303."""
    datos = _campos(html, r'<form class="v3r-decision".*?</form>')
    datos["human_decision"] = "APPROVE"
    respuesta = cliente.post("/v3/review/decide", data=datos, follow_redirects=False)
    assert respuesta.status_code == 303, (
        f"decidir no redirige (PRG roto): status {respuesta.status_code}"
    )
    return respuesta.headers["location"]


def _cabecera(html: str) -> str:
    bloque = re.search(r"<p data-recuento=.*?</p>", html, re.S)
    assert bloque is not None, (
        "la cabecera de recuento ha desaparecido de la pantalla: sin ella no "
        "hay nada que pueda contradecir a la lista, ni decir la verdad"
    )
    return " ".join(bloque.group(0).split())


# ===========================================================================
# E-1 · La cabecera cuenta lo que se muestra Y lo que hay, sin confundirlos.
# ===========================================================================

@pytest.mark.parametrize("filtro", [
    "job_id=job-ZZZ-que-no-existe",
    "source_id=source-que-no-existe",
    "engine_decision=ABSTAIN",
])
def test_con_la_lista_vacia_la_cabecera_no_afirma_que_hay_cuatro(consola, filtro):
    """EL DEFECTO EXACTO: «4 pendientes de 4» sobre CERO fichas.

    Se demuestra primero que el caso es el que se dice —la lista SÍ está
    vacía—; sin eso el testigo se pondría verde con cualquier respuesta.
    """
    cliente, _ = consola
    html = cliente.get(f"/v3/review?workspace=alpha&{filtro}").text
    assert _fichas(html) == 0, (
        f"el caso no es el que se mide: con {filtro!r} la pantalla sigue "
        f"pintando {_fichas(html)} fichas"
    )
    cabecera = _cabecera(html)
    assert "data-mostradas>0<" in cabecera, (
        "con la lista vacía la pantalla no declara que está mostrando CERO; "
        f"cabecera: {cabecera!r}"
    )
    assert "filtrado" in cabecera, (
        "la pantalla no declara que hay un filtro puesto, así que el operador "
        f"lee las cifras como si fueran toda la cola; cabecera: {cabecera!r}"
    )


def test_la_cabecera_no_esconde_el_trabajo_pendiente_detras_del_filtro(consola):
    """EL ERROR SIMÉTRICO, que es tan falso como el original.

    Pasarse de listo y colapsar las tres cifras en la del filtro produciría
    «0 pendientes de 0» con cuatro propuestas esperando: escondería que hay
    cola, y el operador se iría creyendo que no queda nada.
    """
    cliente, _ = consola
    cabecera = _cabecera(cliente.get(
        "/v3/review?workspace=alpha&job_id=job-ZZZ-que-no-existe").text)
    assert "data-remaining>4<" in cabecera, (
        "el filtro se ha comido el recuento de pendientes del workspace: la "
        f"pantalla esconde que queda trabajo por decidir; cabecera: {cabecera!r}"
    )
    assert "pendientes de 4" in cabecera, (
        f"el total del workspace ya no se dice; cabecera: {cabecera!r}"
    )


def test_sin_filtros_la_cabecera_no_inventa_una_cifra_de_mostradas(consola):
    """AUSENCIA DE FILTRO != FILTRO VACÍO.

    Sin filtros no hay nada que distinguir, y añadir un «mostrando N» sería
    ruido que sugiere un recorte inexistente.
    """
    cliente, _ = consola
    html = cliente.get("/v3/review?workspace=alpha").text
    assert _fichas(html) == 4, f"el caso no es el que se mide: {_fichas(html)} fichas"
    cabecera = _cabecera(html)
    assert "sin-filtro" in cabecera, (
        f"la pantalla cree que hay un filtro puesto y no lo hay: {cabecera!r}"
    )
    assert "data-mostradas" not in cabecera, (
        f"sin filtros se pinta un recorte que no existe: {cabecera!r}"
    )


def test_con_filtro_que_casa_las_tres_cifras_son_distinguibles(consola):
    cliente, _ = consola
    html = cliente.get("/v3/review?workspace=alpha&job_id=job-A").text
    assert _fichas(html) == 2, f"el caso no es el que se mide: {_fichas(html)} fichas"
    cabecera = _cabecera(html)
    assert "data-mostradas>2<" in cabecera and "data-remaining>4<" in cabecera, (
        "la cabecera no distingue lo que MUESTRA (2) de lo que QUEDA (4): "
        f"{cabecera!r}"
    )


# ===========================================================================
# E-1 · SEGURIDAD: un contador es una superficie de fuga de EXISTENCIA.
# ===========================================================================

def test_el_recuento_cuenta_despues_del_recorte_por_ambito(consola):
    """UNA CIFRA QUE CUENTE ANTES DEL RECORTE DELATA LO QUE NO SE PUEDE VER.

    ESTO ES UNA GUARDA DE REGRESIÓN, NO LA DEMOSTRACIÓN DE UN ARREGLO. El
    recorte por ámbito en el recuento YA ESTABA en la base `e3fe2ebb`; este
    corte no lo introduce. Lo que hace es ponerle un testigo, porque el corte
    toca precisamente las cifras de la cabecera y una de las formas conocidas
    de romper esta propiedad es «arreglar un contador». Presentarlo como un
    arreglo sería atribuirse una garantía ajena.

    Arreglar un contador es fácil que filtre existencia: si `remaining` o
    `total` contaran sobre el almacén y no sobre lo permitido, la cabecera
    diría cuántas propuestas hay en una partida ajena.

    EL NEGATIVO MUERE POR ÁMBITO, NO POR OTRA PUERTA, y se demuestra con el
    DIFERENCIAL: la propuesta intrusa es idéntica a las que SÍ se cuentan
    salvo en que declara una `partida_id` que no es la activa. Si muriese por
    una validación de forma, la gemela sin `partida_id` también moriría.
    """
    cliente, directorio = consola
    gemela = proposal("intrusa", workspace="alpha", source_id="source-0")

    # Control positivo del diferencial: SIN partida ajena, la gemela SÍ cuenta.
    _escribir(directorio, "job-C", [gemela])
    cabecera = _cabecera(cliente.get("/v3/review?workspace=alpha").text)
    assert "pendientes de 5" in cabecera, (
        "el diferencial no vale: la gemela sin partida ajena tampoco se "
        f"cuenta, así que lo de abajo no probaría nada; cabecera: {cabecera!r}"
    )

    # Y ahora la MISMA propuesta, con una partida que no es la activa.
    ajena = dict(gemela, partida_id="partida-de-otra-mesa")
    _escribir(directorio, "job-C", [ajena])
    html = cliente.get("/v3/review?workspace=alpha").text
    cabecera = _cabecera(html)
    assert "pendientes de 4" in cabecera, (
        "la cabecera cuenta una propuesta de otra partida: la cifra delata "
        f"existencia fuera del ámbito del lector; cabecera: {cabecera!r}"
    )
    assert "partida-de-otra-mesa" not in html and "intrusa" not in html, (
        "el identificador de la propuesta ajena viaja en el HTML"
    )


# ===========================================================================
# D-2 · El filtro de corrida se declara y no se pierde con un clic.
# ===========================================================================

def test_la_pantalla_declara_que_esta_filtrando_por_una_corrida(consola):
    cliente, _ = consola
    html = cliente.get("/v3/review?workspace=alpha&job_id=job-A").text
    assert 'data-filtro-corrida="job-A"' in html, (
        "la pantalla no declara en ninguna parte que hay un filtro de corrida "
        "puesto: el operador ve una cola recortada creyendo que es entera"
    )
    assert "data-quitar-filtro-corrida" in html, (
        "no hay forma de quitar el filtro de corrida desde la pantalla"
    )


def test_el_job_id_viaja_en_el_formulario_de_filtros(consola):
    """PEGAJOSO. Sin el campo oculto, tocar «Fuente» borra la corrida.

    No se puede ejercer el `onchange` sin navegador; lo que se mide es que el
    campo que el navegador reenviaría ESTÁ, y que está DENTRO del formulario
    de filtros (fuera de él sería inerte).
    """
    cliente, _ = consola
    html = cliente.get("/v3/review?workspace=alpha&job_id=job-A").text
    formulario = re.search(r'<form class="v3r-filters".*?</form>', html, re.S)
    assert formulario is not None, "el formulario de filtros ha desaparecido"
    assert 'name="job_id" value="job-A"' in formulario.group(0), (
        "el `job_id` no viaja en el formulario de filtros: al tocar «Fuente» "
        "o «Decisión del motor» el filtro de corrida se pierde en silencio y "
        "la cola se ensancha sola"
    )


def test_sin_corrida_no_se_inventa_un_filtro_de_corrida(consola):
    """El error simétrico de D-2: declarar un filtro que nadie puso.

    CONTROL POSITIVO OBLIGATORIO. Este testigo se quedó VERDE cuando el revisor
    borró la plantilla entera —la consola no mostraba NADA— porque sus dos
    aserciones eran sólo de AUSENCIA: pasaban igual sobre una pantalla en
    blanco, sobre un 500 o sobre un redirect. Sus hermanos sí se autocontrolan.
    Un testigo de ausencia sin control positivo no guarda nada, porque «no está»
    es cierto también cuando no hay pantalla.
    """
    cliente, _ = consola
    html = cliente.get("/v3/review?workspace=alpha").text
    assert _fichas(html) == 4 and "v3r-filters" in html, (
        "no hay pantalla que medir (fichas: "
        f"{_fichas(html)}, formulario de filtros: {'v3r-filters' in html}): lo "
        "que este testigo afirme a partir de aquí sería una ausencia trivial"
    )
    assert "data-filtro-corrida" not in html, (
        "la pantalla anuncia un filtro de corrida sin que haya ninguno"
    )
    assert 'name="job_id"' not in html, (
        "el formulario lleva un `job_id` vacío que el navegador reenviaría"
    )


# ===========================================================================
# H-1 · El filtro sobrevive a la ACCIÓN PRINCIPAL de la consola.
# ===========================================================================

def test_aprobar_una_propuesta_no_ensancha_la_cola_en_silencio(consola):
    """EL DEFECTO, MEDIDO POR EFECTO Y DE PUNTA A PUNTA.

    Antes de este corte, con el filtro de corrida puesto:

        GET  /v3/review?workspace=alpha&job_id=job-A -> 2 fichas, filtro declarado
        POST /v3/review/decide (APPROVE)             -> 303 a /v3/review?workspace=alpha
        GET  de ese destino                          -> 3 fichas, filtro AUSENTE

    La cola se ensanchaba sola de 2 a 3 por un clic del propio operador y sin
    declararlo. Es la misma enfermedad que el filtro no pegajoso del `<select>`,
    pero por la PUERTA PRINCIPAL en vez de por la lateral, y peor: allí el
    operador al menos había tocado un filtro; aquí sólo aprobó una propuesta.

    El testigo RECORRE EL POST y SIGUE EL REDIRECT hasta el HTML, porque es ahí
    —y no en el diccionario de un servicio— donde el contexto se perdía.
    """
    cliente, _ = consola
    antes = cliente.get("/v3/review?workspace=alpha&job_id=job-A").text
    assert _fichas(antes) == 2, f"el caso no es el que se mide: {_fichas(antes)} fichas"

    destino = _aprobar(cliente, antes)
    assert "job_id=job-A" in destino, (
        "tras decidir, el redirect tira el filtro de corrida y devuelve al "
        f"operador a la cola entera; Location: {destino!r}"
    )

    despues = cliente.get(destino).text
    assert "data-filtro-corrida" in despues, (
        "la pantalla a la que se vuelve ya no declara el filtro de corrida"
    )
    assert _fichas(despues) == 1, (
        "la cola no quedó en la propuesta que faltaba de ESTA corrida: se ha "
        f"ensanchado a {_fichas(despues)} fichas sin que nadie lo pidiera"
    )


def test_deshacer_tampoco_pierde_el_contexto(consola):
    """`undo` es la otra acción de esta consola, y tenía el mismo redirect."""
    cliente, _ = consola
    antes = cliente.get("/v3/review?workspace=alpha&job_id=job-A").text
    pantalla = cliente.get(_aprobar(cliente, antes)).text

    datos = _campos(pantalla, r'<form method="post" action="/v3/review/undo">.*?</form>')
    respuesta = cliente.post("/v3/review/undo", data=datos, follow_redirects=False)
    assert respuesta.status_code == 303, f"deshacer no redirige: {respuesta.status_code}"
    assert "job_id=job-A" in respuesta.headers["location"], (
        "deshacer devuelve al operador a la cola entera; Location: "
        f"{respuesta.headers['location']!r}"
    )


def test_los_tres_filtros_sobreviven_a_la_decision_no_solo_la_corrida(consola):
    """LOS TRES. El redirect codificaba `workspace` a mano, así que tiraba
    también `source_id` y `engine_decision`: arreglar sólo el `job_id` habría
    dejado dos tercios del defecto en pie."""
    cliente, _ = consola
    url = "/v3/review?workspace=alpha&job_id=job-A&source_id=source-0&engine_decision=REVIEW"
    antes = cliente.get(url).text
    assert _fichas(antes) == 1, f"el caso no es el que se mide: {_fichas(antes)} fichas"

    destino = _aprobar(cliente, antes)
    for esperado in ("job_id=job-A", "source_id=source-0", "engine_decision=REVIEW"):
        assert esperado in destino, (
            f"el filtro {esperado!r} no sobrevive a la decisión; "
            f"Location: {destino!r}"
        )


def test_no_se_pega_un_filtro_que_el_operador_no_puso(consola):
    """EL ERROR SIMÉTRICO de H-1: que el arreglo se pase de pegajoso.

    Un contexto que sobrevive a todo y no se puede soltar es una cárcel. Sin
    filtros, el destino tras decidir no debe llevar ninguno inventado.
    """
    cliente, _ = consola
    antes = cliente.get("/v3/review?workspace=alpha").text
    assert _fichas(antes) == 4, f"el caso no es el que se mide: {_fichas(antes)} fichas"

    destino = _aprobar(cliente, antes)
    for nombre in ("job_id", "source_id", "engine_decision"):
        assert nombre not in destino, (
            f"el destino se inventa un filtro {nombre!r} que nadie puso: "
            f"{destino!r}"
        )


def test_el_filtro_que_viaja_en_el_post_no_puede_fabricar_parametros(consola):
    """EL FILTRO VIAJA POR LA URL, ASÍ QUE SE CODIFICA.

    El redirect se construía con una f-string. Un valor con `&`, con `=` o con
    un salto de línea podría fabricar parámetros ajenos o partir la cabecera
    `Location`. `urlencode` lo cierra, y esto lo comprueba.

    NO ES una comprobación de autorización: estos tres valores no conceden
    nada. El ámbito se resuelve en el servidor y el recuento cuenta después del
    recorte; lo que se guarda aquí es la FORMA de la URL.
    """
    cliente, _ = consola
    antes = cliente.get("/v3/review?workspace=alpha").text
    datos = _campos(antes, r'<form class="v3r-decision".*?</form>')
    datos["human_decision"] = "APPROVE"
    datos["job_id"] = "job-A&workspace=otro-workspace"

    destino = cliente.post(
        "/v3/review/decide", data=datos, follow_redirects=False
    ).headers["location"]
    assert destino.count("workspace=") == 1, (
        f"el valor del filtro ha fabricado un parámetro ajeno: {destino!r}"
    )
    assert "\n" not in destino and "\r" not in destino, (
        f"el valor del filtro parte la cabecera Location: {destino!r}"
    )
    # Y el workspace que vale sigue siendo el del formulario, no el inyectado.
    assert "workspace=alpha" in destino, destino


def test_con_el_almacen_caido_la_pantalla_no_afirma_estar_mostrando_la_corrida(
    monkeypatch, tmp_path, lector_por_dependencia,
):
    """AUSENCIA != LISTA FILTRADA.

    Con el almacén caído y un `job_id` puesto, la pantalla decía a la vez
    «estás viendo sólo las propuestas de la corrida X» y «no se puede decir
    cuántas propuestas hay pendientes»: afirmaba mostrar algo que no mostraba.
    El filtro se sigue diciendo —el operador tiene derecho a saber con qué
    parámetro entró—, pero sin prometer una lista.
    """
    from app.services.v3_review import ReviewService

    ausente = tmp_path / "no-existe"
    servicio = ReviewService(ausente, tmp_path / "decisions.jsonl")
    monkeypatch.setattr(router_module, "_service", lambda: servicio)
    import app.main  # noqa: F401

    app = FastAPI()
    app.include_router(router_module.router)
    lector_por_dependencia(app)
    html = TestClient(app).get("/v3/review?workspace=alpha&job_id=job-A").text

    assert 'data-state="unavailable"' in html, (
        "el caso no es el que se mide: el almacén no se declara caído"
    )
    assert "Estás viendo sólo las propuestas" not in html, (
        "con la cola no consultable la pantalla sigue afirmando que está "
        "mostrando las propuestas de una corrida"
    )
    assert 'data-filtro-corrida="job-A"' in html, (
        "el error simétrico: la pantalla se calla con qué filtro entró el "
        "operador, que es un dato que él mismo puso"
    )
    assert str(ausente) not in html, "la ruta del almacén se ha filtrado al HTML"


# ===========================================================================
# R-3 · Cada rojo dice su causa, no sólo el color.
# ===========================================================================

def _clasifica_asserts(ruta: Path) -> dict:
    """Red AST sobre los `assert` de un fichero.

    TECHO DECLARADO — lo que esta red NO ve:
      · NO evalúa nada: clasifica por la FORMA del nodo. Un mensaje que sea una
        cadena vacía o que mienta cuenta aquí como «mensaje»; esto guarda
        contra el valor pelado, no contra la prosa mala.
      · Sólo mira `ast.Assert`. Un rojo levantado con `pytest.fail(...)`, con
        `raises_code` o dentro de un ayudante no aparece en estas cifras, y
        esta red no dice NADA sobre ellos.
      · Sólo mira el fichero que se le pasa. No cubre el resto de la suite, y
        atribuirle esa cobertura sería falso.
      · El volcado se detecta como `Subscript` con `Slice` literal. Uno
        construido de otra forma (`textwrap`, `str.format`) NO se ve.
    """
    import ast

    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    opacos, pelados, volcados = [], [], []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Assert):
            continue
        if nodo.msg is None:
            # SIN MENSAJE NO ES LO MISMO QUE OPACO. pytest reescribe las
            # comparaciones y enseña los dos operandos, así que `assert a == b`
            # SÍ dice su causa solo. Lo opaco es `assert f(x)`: una llamada que
            # devuelve bool produce un `assert False` mudo.
            if not isinstance(nodo.test, ast.Compare):
                opacos.append(nodo.lineno)
            continue
        if not isinstance(nodo.msg, (ast.Constant, ast.JoinedStr, ast.BinOp)):
            pelados.append(nodo.lineno)
        for sub in ast.walk(nodo):
            if isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Slice):
                volcados.append(sub.lineno)
    return {"opacos": opacos, "pelados": pelados, "volcados": sorted(set(volcados))}


def test_los_rojos_del_corte_2_dicen_su_causa():
    """Higiene MEDIDA, con el antes y el después.

    Antes de este corte, sobre 82 asserts de `test_panel_veracidad_corte2.py`:
    27 con mensaje de VALOR PELADO (hay medido un `AssertionError: []`) y 2
    volcados de corte (`html[:400]`, `envio.text[:300]`), que producen un rojo
    que empieza por líneas en blanco y se lee igual que un rojo sin causa. La
    docstring de ese fichero explicaba por qué el volcado no vale mientras el
    volcado seguía vivo dentro.

    Después: 0 y 0. Los que quedan sin mensaje son TODOS comparaciones, que
    pytest explica solo; no son opacos y no se tocan.
    """
    ruta = Path(__file__).resolve().parent / "test_panel_veracidad_corte2.py"
    medida = _clasifica_asserts(ruta)
    assert medida["pelados"] == [], (
        "vuelven los mensajes de valor pelado, que producen rojos del tipo "
        f"`AssertionError: []`; líneas: {medida['pelados']}"
    )
    assert medida["volcados"] == [], (
        "vuelve el volcado de marcado como mensaje de rojo; el ayudante "
        "`_frase_del_resultado` existe justo para no hacer esto; líneas: "
        f"{medida['volcados']}"
    )
    assert medida["opacos"] == [], (
        f"hay asserts que pytest no puede explicar solo: {medida['opacos']}"
    )


def test_la_red_ast_de_r3_se_pone_roja_por_la_causa_correcta(tmp_path):
    """CALIBRACIÓN. Una red que no sabe ponerse roja no guarda nada.

    Se le da un fichero fabricado con un ejemplar de cada categoría y se
    comprueba que los clasifica por separado — incluida la distinción que hace
    que la red no sea un contador ciego: la comparación sin mensaje NO cuenta
    como opaca.
    """
    cobaya = tmp_path / "cobaya.py"
    cobaya.write_text(
        "def t():\n"
        "    assert a == b\n"              # 2 · explicable: no cuenta
        "    assert f(x)\n"                # 3 · opaco
        "    assert g(y), valores\n"       # 4 · pelado
        "    assert h(z), texto[:400]\n"   # 5 · pelado + volcado
        "    assert k(w), 'la causa'\n",   # 6 · correcto
        encoding="utf-8",
    )
    medida = _clasifica_asserts(cobaya)
    assert medida == {"opacos": [3], "pelados": [4, 5], "volcados": [5]}, medida
