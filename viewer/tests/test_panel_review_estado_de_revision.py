# -*- coding: utf-8 -*-
"""Slice 2 · Corte 4 — «esta ingesta produjo estas propuestas y éste es su
estado de revisión», afirmado de forma veraz y trazable.

LOS TRES DEFECTOS QUE ESTE MÓDULO FIJA
--------------------------------------
Medidos ejecutando sobre `6fb686a`, con el recorrido REAL del panel::

    /panel/review  (la entrada del nav, SIN workspace)

    almacen POBLADO               200  «Sin propuestas visibles» = False
    almacen AUSENTE               200  «Sin propuestas visibles» = True
    almacen ILEGIBLE (chmod 000)  200  «Sin propuestas visibles» = True
    almacen VACIO (legitimo)      200  «Sin propuestas visibles» = True

    «La ingesta ha terminado correctamente» · en revision: 0
    por_veredicto REVIEW=2 · 4 propuestas REALMENTE escritas
    cero mencion y cero enlace a /panel/review

    /panel/review no expone ningun job_id: dos ingestas de la misma fuente
    son indistinguibles.

Tres sitios, un solo problema: **el producto presenta como CONOCIDO lo que no
sabe**. Ausencia de almacén como «no hay nada que revisar»; revisión de
identidad como si fuera el veredicto `REVIEW`; y una cola sin corrida como si
cualquier propuesta fuese de la última ingesta.

El texto del caso AUSENTE era además falso y tranquilizador: «No hay ningún
workspace de revisión visible **para tu ámbito actual**» atribuía al ÁMBITO lo
que causaba un almacén que no estaba.

POR QUÉ ESTAS PRUEBAS NO SE PONEN VERDES POR CASUALIDAD
-------------------------------------------------------
1. **`tmp_path` SIEMPRE existe.** Ése es justo el motivo de que la suite del
   Corte 3 esté verde sin cubrir ninguno de estos bloqueantes: una prueba que
   pide `tmp_path` nunca ve un directorio ausente. Aquí el almacén roto se
   rompe EXPLÍCITAMENTE (`rmtree`, `chmod 000`) y siempre PARTIENDO DE UNO
   POBLADO, para que lo que se exige sea un CAMBIO de pantalla. Una prueba que
   naciera con el almacén ya roto no distinguiría nada.
2. **Identidad, no recuento.** Se comparan conjuntos de `proposal_id`. Un
   recuento se pondría verde con restos de otra corrida.
3. **El recorrido es el del operador**: formulario real, CSRF real, cola real,
   worker real y la entrada del nav SIN `workspace` — que es por donde el
   operador llega de verdad. Con `?workspace=` explícito el defecto no se veía.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from app import jobs_client


# ---------------------------------------------------------------------------
# GRAFO DE MENTIRA: este modulo no viene a medir la observacion del grafo
# ---------------------------------------------------------------------------
# Desde el Slice 2 · Corte 5 la ingesta del panel abre una conexion de solo
# lectura a Neo4j y falla cerrado sin ella. Los casos de este modulo miden otra
# cosa y corren sin Docker, asi que se les da un doble que responde a la
# consulta del catalogo. Lo que NINGUNO de ellos puede afirmar por eso es que
# el producto observe el grafo de verdad: eso se mide con Neo4j real.
@pytest.fixture(autouse=True)
def _grafo_de_mentira(monkeypatch):
    import grafo_doble

    return grafo_doble.instalar(monkeypatch)

# El arnés del Corte 3 ya monta app real, auth real, cola real y almacén
# aislado. Se REUTILIZA en vez de reconstruirlo: dos arneses para el mismo
# recorrido acaban divergiendo, y el que no se mira es el que miente.
from test_panel_review_cola_desde_ingesta import (  # noqa: F401
    EJEMPLOS, PASSWORD, SLOT_B, SLOT_C,
    _correr_worker, _csrf, _opciones, _propuestas_escritas,
    almacen_de_propuestas, auth_on, cola, operador, paneles_on, real_app,
    _entorno_limpio, _salud_aislada,
)

#: Frase del estado vacío. Es lo que el operador lee y lo que estos tests
#: exigen que NO aparezca cuando el almacén no se pudo consultar.
VACIO = "Sin propuestas visibles"


# ---------------------------------------------------------------------------
# Utillaje del recorrido
# ---------------------------------------------------------------------------

@pytest.fixture
def fuentes(tmp_path) -> Path:
    """Catálogo con DOS fuentes distintas, copia escribible del de ejemplo.

    La segunda es el mismo texto con otro nombre de fichero. El `source_id` es
    el nombre del fichero y entra en la identidad de la propuesta, así que las
    dos corridas producen propuestas REVIEW con `proposal_id` DISJUNTOS: es lo
    que permite exigir que ninguna se atribuya a la corrida ajena.

    No se toca `perfil-operador.json` ni la regla «un directorio, un
    workspace»: las dos fuentes viven en el MISMO directorio y comparten
    workspace a propósito.
    """
    destino = tmp_path / "fuentes"
    shutil.copytree(EJEMPLOS, destino)
    original = destino / "nota-cofradia-de-ambar.md"
    (destino / "nota-cofradia-segunda-sesion.md").write_text(
        original.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return destino


def _ingerir(operador, cola, fuentes, monkeypatch, indice: int = 0) -> tuple[str, dict]:
    """Una ingesta COMPLETA desde el panel. Devuelve (job_id, resultado)."""
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(fuentes))
    pantalla = operador.get(SLOT_B.prefix)
    assert pantalla.status_code == 200, pantalla.status_code
    opciones = _opciones(pantalla.text)
    assert len(opciones) > indice, opciones

    envio = operador.post(
        "/panel/operations/ingestas",
        data={"fuente": opciones[indice], "csrf_token": _csrf(pantalla.text)},
    )
    assert envio.status_code == 303, envio.text[:300]

    store = jobs_client._load_job_store()
    pendientes = store.list_jobs(status="pending", db_path=str(cola))
    assert len(pendientes) == 1, pendientes
    job_id = pendientes[0]["job_id"]
    assert _correr_worker(cola) == 1
    final = store.get_job(job_id, db_path=str(cola))
    assert final["status"] == "complete", final.get("error_message")
    return job_id, json.loads(final["result_json"])


def _pantalla(operador, **params):
    """`/panel/review` POR LA ENTRADA DEL NAV: sin `workspace` salvo que se pida.

    Es la diferencia que hacía invisible el defecto: con `?workspace=` explícito
    el almacén ausente SÍ daba 404, pero el nav no pone ese parámetro y el
    operador nunca llegaba por ahí.
    """
    consulta = "&".join(f"{k}={v}" for k, v in params.items() if v)
    return operador.get(f"{SLOT_C.prefix}{'?' + consulta if consulta else ''}")


def _ids_en_pantalla(html: str, candidatos) -> set[str]:
    return {pid for pid in candidatos if pid in html}


# ===========================================================================
# 1. LOS TRES DESENLACES DEL ALMACÉN
# ===========================================================================

def test_almacen_ausente_no_se_presenta_como_vacio(
    real_app, paneles_on, cola, operador, almacen_de_propuestas, fuentes, monkeypatch
):
    """AUSENCIA != CERO, y se exige el CAMBIO desde una pantalla poblada.

    Arranca con propuestas de verdad, comprueba que la pantalla las enseña, y
    sólo entonces borra el almacén. Si la prueba naciera con el almacén ya
    roto, no distinguiría «ausente» de «vacío» y se pondría verde por serlo
    todo a la vez.
    """
    _ingerir(operador, cola, fuentes, monkeypatch)
    escritas, _ = _propuestas_escritas(almacen_de_propuestas)
    assert escritas, "sin propuestas la prueba no puede exigir ningún cambio"

    poblada = _pantalla(operador)
    assert poblada.status_code == 200
    assert VACIO not in poblada.text, "la pantalla ya decía «vacío» estando poblada"

    shutil.rmtree(almacen_de_propuestas)

    rota = _pantalla(operador)
    assert VACIO not in rota.text, (
        "con el almacén BORRADO la pantalla sigue diciendo «Sin propuestas "
        "visibles»: presenta una ausencia de dato como un cero conocido"
    )
    assert "ámbito actual" not in rota.text, (
        "el vacío se sigue atribuyendo al ÁMBITO cuando la causa es que el "
        "almacén no está"
    )
    assert rota.status_code == 503, rota.status_code
    assert 'data-state="error"' in rota.text
    assert "NO ESTA" in rota.text, rota.text[:400]
    # Repo público: ni ruta, ni traza.
    assert str(almacen_de_propuestas) not in rota.text
    assert "Traceback" not in rota.text


def test_almacen_ilegible_no_se_presenta_como_vacio(
    real_app, paneles_on, cola, operador, almacen_de_propuestas, fuentes, monkeypatch
):
    """El caso peor: `exists()` es True y `Path.glob` se traga el PermissionError.

    Por eso no basta con mirar `exists()`: el listado tiene que hacerse con algo
    que SÍ pueda fallar (`os.listdir`). Un listado que no puede fallar no puede
    distinguir un directorio ilegible de uno vacío.
    """
    _ingerir(operador, cola, fuentes, monkeypatch)
    assert _propuestas_escritas(almacen_de_propuestas)[0]
    assert VACIO not in _pantalla(operador).text

    # La premisa, COMPROBADA: el directorio existe y aun así no se puede leer.
    os.chmod(almacen_de_propuestas, 0o000)
    try:
        assert almacen_de_propuestas.exists(), (
            "premisa rota: este caso sólo prueba algo si exists() sigue siendo True"
        )
        with pytest.raises(PermissionError):
            os.listdir(almacen_de_propuestas)

        rota = _pantalla(operador)
        assert VACIO not in rota.text, (
            "con el almacén ILEGIBLE la pantalla dice «Sin propuestas visibles»: "
            "un permiso roto se presenta como «no hay nada que revisar»"
        )
        assert rota.status_code == 503, rota.status_code
        assert "NO SE PUEDE LEER" in rota.text, rota.text[:400]
        assert str(almacen_de_propuestas) not in rota.text
    finally:
        os.chmod(almacen_de_propuestas, stat.S_IRWXU)


def test_almacen_vacio_legitimo_si_se_presenta_como_vacio(
    real_app, paneles_on, cola, operador, almacen_de_propuestas
):
    """Y AL REVÉS: arreglar los dos anteriores a lo bruto rompería éste.

    Un almacén presente, legible y sin propuestas es un hecho CONOCIDO y se
    dice tal cual. Tratarlo como error sería el defecto simétrico: alarmar al
    operador por una ingesta que legítimamente no dejó nada.
    """
    almacen_de_propuestas.mkdir(parents=True, exist_ok=True)
    assert almacen_de_propuestas.is_dir()
    assert os.listdir(almacen_de_propuestas) == []

    vacia = _pantalla(operador)
    # EL ORDEN DE LAS AFIRMACIONES IMPORTA. La primera que se rompe es la que
    # da el mensaje del rojo, y el rojo tiene que decir POR QUÉ. Comprobar el
    # código de estado antes que el estado de la pantalla producía un
    # «assert 503 == 200» que no nombra la causa: el arnés de calibración lo
    # detectó como rojo mal atribuido.
    assert 'data-state="error"' not in vacia.text, (
        "un almacén vacío legítimo se está presentando como un FALLO: arreglar "
        "«ausente» e «ilegible» a lo bruto, alarmando siempre, no vale"
    )
    assert vacia.status_code == 200, (
        f"un vacío legítimo responde {vacia.status_code}: se está tratando como "
        "almacén no disponible"
    )
    assert VACIO in vacia.text, "un vacío legítimo tiene que decirse vacío"
    assert "se ha leído correctamente" in vacia.text


def test_los_tres_desenlaces_no_comparten_respuesta(
    real_app, paneles_on, cola, operador, almacen_de_propuestas, fuentes, monkeypatch
):
    """Los tres estados, uno al lado del otro: tres respuestas DISTINTAS.

    Comprobarlos por separado deja pasar el arreglo que los unifica todos en un
    error. Aquí se exige que las tres respuestas difieran entre sí.
    """
    _ingerir(operador, cola, fuentes, monkeypatch)
    respaldo = Path(str(almacen_de_propuestas) + ".respaldo")
    shutil.copytree(almacen_de_propuestas, respaldo)

    desenlaces = {}
    desenlaces["poblado"] = _pantalla(operador)

    shutil.rmtree(almacen_de_propuestas)
    desenlaces["ausente"] = _pantalla(operador)

    shutil.copytree(respaldo, almacen_de_propuestas)
    os.chmod(almacen_de_propuestas, 0o000)
    try:
        desenlaces["ilegible"] = _pantalla(operador)
    finally:
        os.chmod(almacen_de_propuestas, stat.S_IRWXU)

    shutil.rmtree(almacen_de_propuestas)
    almacen_de_propuestas.mkdir(parents=True)
    desenlaces["vacio"] = _pantalla(operador)

    assert desenlaces["poblado"].status_code == 200
    assert desenlaces["vacio"].status_code == 200
    assert desenlaces["ausente"].status_code == 503
    assert desenlaces["ilegible"].status_code == 503

    # Vacío y ausente NO pueden leerse igual: era exactamente el defecto.
    assert VACIO in desenlaces["vacio"].text
    assert VACIO not in desenlaces["ausente"].text
    assert VACIO not in desenlaces["ilegible"].text
    # Y ausente e ilegible tampoco son el mismo hecho ni la misma acción.
    assert desenlaces["ausente"].text != desenlaces["ilegible"].text, (
        "«no está» y «no se puede leer» llevan al operador a sitios distintos "
        "(alinear la ruta compartida vs. arreglar un permiso) y se están "
        "diciendo con el mismo texto"
    )


# ===========================================================================
# 2. EL RESUMEN DE LA INGESTA DICE EL `REVIEW` REAL Y CONDUCE
# ===========================================================================

def test_el_resumen_refleja_el_review_real(
    real_app, paneles_on, cola, operador, almacen_de_propuestas, fuentes, monkeypatch
):
    """`en_revision` era `review_identity`: otro hecho, otro número.

    El operador leía «terminado correctamente · en revisión 0» con `REVIEW=2`
    y cuatro propuestas escritas, y no abría la consola de revisión.
    """
    _job, resultado = _ingerir(operador, cola, fuentes, monkeypatch)
    resumen = resultado["resumen"]
    review_real = (resumen["por_veredicto"] or {}).get("REVIEW", 0)
    assert review_real > 0, (
        f"la fuente del arnés ya no produce REVIEW: {resumen['por_veredicto']}"
    )

    assert resumen["en_revision"] == review_real, (
        f"el resumen dice «en revisión: {resumen['en_revision']}» mientras el "
        f"motor declara REVIEW={review_real}"
    )
    # El dato de identidad NO se pierde: se nombra por lo que es.
    assert "revision_de_identidad" in resumen

    # Y el mensaje del desenlace no puede seguir siendo tranquilizador a secas.
    assert "REVIEW" in resultado["message"], resultado["message"]

    escritas, _ = _propuestas_escritas(almacen_de_propuestas)
    assert resumen["propuestas_de_revision"] == len(escritas), (
        "el resumen no dice cuántas propuestas revisables dejó esta corrida"
    )


def test_el_resumen_enlaza_a_la_revision_de_SU_corrida(
    real_app, paneles_on, cola, operador, almacen_de_propuestas, fuentes, monkeypatch
):
    """Cero mención y cero enlace a `/panel/review`: el recorrido no cerraba.

    Y el enlace no vale si lleva a la cola entera: tiene que llevar a las
    propuestas de ESTA corrida.
    """
    job_id, _resultado = _ingerir(operador, cola, fuentes, monkeypatch)

    # `solicitado` es el parámetro del patrón PRG: es exactamente a donde
    # redirige el POST del formulario, o sea la pantalla que el operador ve
    # después de lanzar la ingesta.
    acuse = operador.get(f"{SLOT_B.prefix}?solicitado={job_id}")
    assert acuse.status_code == 200, acuse.status_code
    assert 'data-role="enlace-revision"' in acuse.text, (
        "el acuse de la ingesta no ofrece ningún camino a la revisión"
    )
    assert SLOT_C.prefix in acuse.text, "no se menciona /panel/review"
    assert f"job_id={job_id}" in acuse.text, (
        "el enlace lleva a la cola entera, no a las propuestas de esta corrida"
    )


# ===========================================================================
# 3. LA PRUEBA INSIGNIA
# ===========================================================================

def test_insignia_dos_ingestas_se_distinguen_y_el_almacen_roto_cambia_la_pantalla(
    real_app, paneles_on, cola, operador, almacen_de_propuestas, fuentes, monkeypatch
):
    """El guion entero del corte, de una pieza.

        ingesta A -> REVIEW>0 -> aparecen EXACTAMENTE las propuestas de A
        ingesta B -> propuestas nuevas -> el operador PUEDE DISTINGUIR A de B
        romper el almacen (POBLADO) -> la pantalla CAMBIA a «no disponible»

    Se comprueba IDENTIDAD, no recuento.
    """
    # --- premisa: el almacén arranca vacío. Se comprueba, no se supone. ---
    previas, _ = _propuestas_escritas(almacen_de_propuestas)
    assert previas == [], f"restos de otra corrida invalidarían todo: {previas}"

    # --- INGESTA A -------------------------------------------------------
    job_a, resultado_a = _ingerir(operador, cola, fuentes, monkeypatch, indice=0)
    assert (resultado_a["resumen"]["por_veredicto"] or {}).get("REVIEW", 0) > 0
    ids_a, workspaces = _propuestas_escritas(almacen_de_propuestas)
    ids_a = set(ids_a)
    assert ids_a, "la ingesta A no escribió ninguna propuesta"
    workspace = workspaces.pop()

    solo_a = _pantalla(operador, workspace=workspace, job_id=job_a)
    assert solo_a.status_code == 200
    assert _ids_en_pantalla(solo_a.text, ids_a) == ids_a, (
        "la corrida A no enseña exactamente sus propias propuestas: sin "
        "atribución a la corrida, A y B no se distinguen y el operador no "
        "puede saber qué produjo la ingesta que acaba de lanzar"
    )

    # --- INGESTA B, otra fuente del MISMO catálogo y workspace ------------
    job_b, _resultado_b = _ingerir(operador, cola, fuentes, monkeypatch, indice=1)
    assert job_b != job_a
    todas, _ = _propuestas_escritas(almacen_de_propuestas)
    ids_b = set(todas) - ids_a
    assert ids_b, "la ingesta B no aportó ninguna propuesta nueva"

    # EL OPERADOR DISTINGUE A DE B. En los dos sentidos: cada corrida enseña
    # las suyas Y NO enseña las de la otra. Sólo la primera mitad se pondría
    # verde con una pantalla que lo enseña todo.
    vista_a = _pantalla(operador, workspace=workspace, job_id=job_a)
    assert _ids_en_pantalla(vista_a.text, ids_a) == ids_a
    assert _ids_en_pantalla(vista_a.text, ids_b) == set(), (
        "propuestas de la corrida B aparecen atribuidas a la corrida A: las "
        "propuestas antiguas se confunden con las de la corrida actual"
    )

    vista_b = _pantalla(operador, workspace=workspace, job_id=job_b)
    assert _ids_en_pantalla(vista_b.text, ids_b) == ids_b
    assert _ids_en_pantalla(vista_b.text, ids_a) == set()

    # Y sin filtrar, la pantalla DICE de qué corrida viene cada propuesta: dos
    # ingestas ya no dejan una pantalla indistinguible.
    completa = _pantalla(operador, workspace=workspace)
    assert job_a in completa.text and job_b in completa.text, (
        "la cola no expone ningún job_id: dos ingestas siguen siendo "
        "indistinguibles en pantalla"
    )

    # --- ROMPER EL ALMACÉN, PARTIENDO DE POBLADO -------------------------
    assert VACIO not in completa.text
    shutil.rmtree(almacen_de_propuestas)
    rota = _pantalla(operador, workspace=workspace)
    assert rota.status_code == 503
    assert VACIO not in rota.text, (
        "la pantalla no cambió de «vacío» a «no disponible» al romper el almacén"
    )


def test_una_reejecucion_de_la_misma_fuente_no_deja_la_pantalla_identica(
    real_app, paneles_on, cola, operador, almacen_de_propuestas, fuentes, monkeypatch
):
    """El caso que el encargo señala: dedup por digest dejaba todo IGUAL.

    Reejecutar la misma fuente no produce reclamaciones nuevas —son las mismas,
    y fingir que son otras sería mentir al revés—. Lo que sí cambia, y tiene
    que verse, es que AHORA las produjeron DOS corridas.
    """
    job_a, _ = _ingerir(operador, cola, fuentes, monkeypatch, indice=0)
    ids, workspaces = _propuestas_escritas(almacen_de_propuestas)
    ids = set(ids)
    workspace = workspaces.pop()

    antes = _pantalla(operador, workspace=workspace)
    assert job_a in antes.text

    # Antes de la segunda corrida, filtrar por ella no enseña NADA — y lo dice
    # como vacío legítimo, no como almacén roto.
    inexistente = _pantalla(operador, workspace=workspace, job_id="corrida-que-no-existe")
    assert inexistente.status_code == 200
    assert VACIO in inexistente.text

    job_b, _ = _ingerir(operador, cola, fuentes, monkeypatch, indice=0)
    assert job_b != job_a

    despues = _pantalla(operador, workspace=workspace)
    assert despues.text != antes.text, (
        "dos ingestas de la misma fuente dejan la pantalla IDÉNTICA: el "
        "operador no puede saber si la corrida que acaba de lanzar hizo algo"
    )
    assert job_b in despues.text, "la segunda corrida no aparece por ninguna parte"

    # Las MISMAS reclamaciones, ahora atribuidas a las DOS corridas.
    por_b = _pantalla(operador, workspace=workspace, job_id=job_b)
    assert _ids_en_pantalla(por_b.text, ids) == ids
    por_a = _pantalla(operador, workspace=workspace, job_id=job_a)
    assert _ids_en_pantalla(por_a.text, ids) == ids


# ===========================================================================
# 4. QUE NO SE VUELVA A CONFUNDIR AUSENCIA CON CERO
# ===========================================================================

def test_load_proposals_distingue_los_tres_estados_en_el_origen(tmp_path):
    """La distinción vive en el servicio, no sólo en la plantilla.

    `tmp_path` SIEMPRE existe: el directorio ausente se construye a mano
    justamente porque la fixture nunca lo daría.
    """
    from app.services.v3_review import (
        PROPOSALS_STORE_MISSING, PROPOSALS_STORE_UNREADABLE,
        ProposalStoreUnavailable, load_proposals,
    )

    ausente = tmp_path / "no-existe"
    assert not ausente.exists()
    with pytest.raises(ProposalStoreUnavailable) as ausencia:
        load_proposals(ausente)
    assert ausencia.value.code == PROPOSALS_STORE_MISSING

    vacio = tmp_path / "vacio"
    vacio.mkdir()
    assert load_proposals(vacio) == [], "un vacío legítimo es una lista vacía"

    ilegible = tmp_path / "ilegible"
    ilegible.mkdir()
    (ilegible / "paquete.json").write_text("{}", encoding="utf-8")
    os.chmod(ilegible, 0o000)
    try:
        assert ilegible.exists(), "premisa: exists() sigue siendo True"
        with pytest.raises(ProposalStoreUnavailable) as permiso:
            load_proposals(ilegible)
        assert permiso.value.code == PROPOSALS_STORE_UNREADABLE
    finally:
        os.chmod(ilegible, stat.S_IRWXU)


def test_el_glob_silencioso_no_vuelve_a_ser_la_via_de_lectura():
    """`Path.glob` se traga el `PermissionError`; por eso no se usa aquí.

    Se comprueba por AST sobre la función real, no contando texto: una
    comprobación que busca la cadena `glob` se pondría verde con un comentario.
    """
    import ast
    import inspect

    from app.services import v3_review

    arbol = ast.parse(inspect.getsource(v3_review.load_proposals))
    globs = [
        nodo for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Attribute) and nodo.attr == "glob"
    ]
    assert not globs, (
        "load_proposals vuelve a listar con `glob`, que devuelve un iterador "
        "vacío —sin error— cuando el directorio no se puede leer: el caso "
        "ILEGIBLE volvería a presentarse como «no hay propuestas»"
    )
