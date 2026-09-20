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

POR QUÉ ESTOS TESTIGOS PIDEN LA PANTALLA
----------------------------------------
Las dos garantías son VISIBLES: viven en la plantilla, no en el servicio. Un
testigo que se conformara con el `QueueView` que devuelve `ReviewService`
seguiría verde con la cabecera borrada — ya pasó en este programa. Por eso
aquí se hace GET del HTML y se lee el marcado.

LO QUE ESTOS TESTIGOS **NO** CUBREN (techo declarado)
-----------------------------------------------------
  · No ejercen JavaScript: el `onchange="this.form.submit()"` de los selects no
    se dispara aquí. Lo que se mide es que el `job_id` ESTÁ en el formulario,
    que es lo que el navegador reenviaría; el reenvío real del navegador queda
    como región no observada por esta suite.
  · No ejercen infraestructura real: el almacén de propuestas es un directorio
    temporal. Capa alcanzada: **usable desde el producto** (HTTP + plantilla
    reales), no «ejercida contra infra real».
  · El negativo por ámbito muere por la barrera de partida. No dice nada de las
    demás puertas de autorización.
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
    """El error simétrico de D-2: declarar un filtro que nadie puso."""
    cliente, _ = consola
    html = cliente.get("/v3/review?workspace=alpha").text
    assert "data-filtro-corrida" not in html, (
        "la pantalla anuncia un filtro de corrida sin que haya ninguno"
    )
    assert 'name="job_id"' not in html, (
        "el formulario lleva un `job_id` vacío que el navegador reenviaría"
    )


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
