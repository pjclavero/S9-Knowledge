"""CORTE 2 · La pantalla no puede inventar lo que el sistema no sabe.

LA PROPIEDAD QUE ESTOS TESTIGOS DEFIENDEN
-----------------------------------------
La pantalla que conduce una decisión muestra el estado que el sistema REALMENTE
conoce, y no fabrica una explicación para rellenar el hueco.

Tres defectos de la MISMA propiedad, medidos en la remedición del recorrido:

  1. EL CERO MUDO. Una fuente de la que el motor no extrae nada producía
     pantalla verde (`INGEST_OK`, «no ha dejado nada en revisión») con
     menciones 0, afirmaciones 0 y propuestas 0. El motor SÍ diagnosticaba
     —`ingest_report._carencias` emite `SIN_GLOSARIO`, `SIN_MENCIONES`,
     `SIN_CLAIMS`, `CADENA_DETENIDA`…— y su propio CLI las imprime bajo
     «## CARENCIAS declaradas · No se rellena con ceros que parezcan datos».
     Lo que faltaba no era el diagnóstico: era que el PRODUCTO lo consumiera.
     Su segunda cara es `APPLY_REJECTED`, que decía «el motivo queda registrado
     en el servidor» mientras el motivo real se perdía en un `log.error`.

  2. `PLAN_SUPERSEDED` afirmaba «Una decisión cambió después de preparar lo
     aprobado» — una causa que el código no comprueba: al estado `superseded`
     se llega por TRES caminos y sólo uno es ése. En el tercero (un apply que
     falló) el mensaje OCULTABA que lo que falló fue la escritura.

  3. El enlace del acuse mandaba a `/panel/review`, que es de SÓLO LECTURA por
     contrato declarado. El operador seguía el camino que el producto le
     marcaba y llegaba a una pantalla sin botones.

POR QUÉ ESTOS TESTIGOS PIDEN LA PANTALLA
----------------------------------------
Estas garantías son VISIBLES. Un testigo que se conforme con el diccionario
que devuelve un servicio se queda verde aunque la plantilla no pinte nada — y
en este mismo programa ya ocurrió: una cabecera se pudo borrar entera sin que
la suite se moviera.

QUÉ MIRA CADA UNO, SIN AFIRMAR DE MÁS. Decir «todos piden la pantalla» sería,
en un corte cuya propiedad es no afirmar lo que no se comprueba, exactamente
el defecto que el corte persigue. Y la primera versión de este párrafo —escrita
para dejar de afirmar de más— volvió a hacerlo por partida doble: dijo que M5
ponía rojos a estos testigos (M5 pone rojo el testigo EXTERNO; aquí no mueve
ninguno) y se presentó como exhaustiva dejándose uno fuera. El reparto real,
con la mutación que pone rojo a cada uno:

  PIDEN EL HTML por GET (de ahí sale la afirmación de visibilidad):
    · test_una_ingesta_que_no_cosecha_nada_lo_DICE_en_la_pantalla      · M1, M4
    · test_una_cosecha_esteril_no_se_anuncia_como_tranquilizadora      · M6, M7
    · test_con_ABSTAIN_y_sin_REVIEW_el_acuse_no_se_contradice_a_si_mismo · M8
    · test_si_borro_el_bloque_de_carencias_este_testigo_se_pone_rojo   · M1, M4

  NO PIDEN LA PANTALLA — miran el catálogo, el AST del almacén o la firma de
  la ruta, porque lo que afirman es del DATO, no del pintado:
    · test_las_carencias_desconocidas_se_nombran_en_vez_de_desaparecer
        se pondría rojo si `panel_errors.carencia` se tragara el código, o si
        el filtro por forma dejara de descartar lo que no es un código.
    · test_la_pantalla_no_afirma_que_una_decision_cambio               · M2
    · test_el_camino_del_apply_fallido_se_distingue_y_se_dice
        se pondría rojo si el sellado escribiera `apply_notes_json` y la
        columna dejara de distinguir el camino.
    · test_el_rechazo_del_writer_llega_al_operador_con_su_motivo
        se pondría rojo si el mapa de rechazos publicara un código no
        declarado, o si filtrara el código interno del writer al operador.
    · test_la_consola_que_decide_acepta_la_corrida_puesta              · M3
    · test_las_cinco_ramas_del_desenlace_estan_cerradas                · M6, M7, M8

  DÓNDE VIVE LA COBERTURA DE PANTALLA DE LOS QUE NO LA PIDEN:
    · `PLAN_SUPERSEDED` y el apply fallido se recorren POR LA UI, con GET del
      acuse y la frase exigida en el HTML, en
      `test_panel_apply_desde_la_ui.py::test_tras_un_apply_fallido_la_pantalla_no_culpa_a_una_decision`
      — y ÉSE es el que M5 pone rojo.
    · El destino del enlace se lee del `href` del propio acuse en
      `test_panel_review_estado_de_revision.py::test_el_resumen_enlaza_a_la_revision_de_SU_corrida`.

  · test_la_enumeracion_de_esta_cabecera_es_exhaustiva
        el guardián de la lista: se pondría rojo si alguien añade un caso
        y no lo añade aquí. Esta enumeración ya se quedó corta una vez.

  Esta lista cubre TODOS los casos del fichero, Y ESO SE COMPRUEBA: el
  último de la lista lo verifica, para que no vuelva a quedarse corta sin
  que nadie se entere.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app import jobs_client

# El arnés del recorrido, reutilizado tal cual: app real, auth real, cola real
# y almacén de propuestas real. No se simula ninguna capa intermedia.
from test_panel_review_cola_desde_ingesta import (  # noqa: F401
    EJEMPLOS, SLOT_B, SLOT_C,
    _correr_worker, _csrf, _opciones,
    almacen_de_propuestas, auth_on, cola, operador, paneles_on, real_app,
    _entorno_limpio, _salud_aislada, _grafo_de_mentira,
)


#: La frase EXACTA que producía el cero mudo. No se busca «parecida»: se busca
#: ésta, porque es la que el operador leía como «estaba todo claro».
FRASE_TRANQUILIZADORA = "no ha dejado nada en revision"

#: La causalidad fabricada que `PLAN_SUPERSEDED` afirmaba sin comprobarla.
CAUSALIDAD_FABRICADA = "Una decision cambio"


# ---------------------------------------------------------------------------
# Utillaje
# ---------------------------------------------------------------------------

@pytest.fixture
def fuente_muda(tmp_path):
    """Un catálogo con UNA fuente de la que el motor no puede extraer nada.

    Se copia el perfil y el catálogo de ejemplo —para que el alta sea la de
    producción, no una maqueta— y se sustituye el texto por prosa que no
    contiene ni un nombre del glosario. Es exactamente el caso que producía la
    pantalla verde: fuente válida, corrida correcta, cosecha CERO.
    """
    import shutil

    destino = tmp_path / "fuentes"
    shutil.copytree(EJEMPLOS, destino)
    (destino / "nota-cofradia-de-ambar.md").unlink()
    (destino / "nota-sin-cosecha.md").write_text(
        "# Nota de sesion\n\n"
        "## Lo que se hablo\n\n"
        "Se reviso el calendario y se acordo continuar la semana que viene.\n\n"
        "No hubo acuerdos que registrar ni nada pendiente de anotar.\n",
        encoding="utf-8",
    )
    return destino


@pytest.fixture
def fuente_esteril(tmp_path):
    """Una fuente con MENCIONES pero sin ni una relación. El residuo D-1.

    MEDIDO sobre el motor con el catálogo de ejemplo: menciones 3,
    afirmaciones 0, en revisión 0, y carencias `SIN_CLAIMS`, `CADENA_DETENIDA`,
    `SIN_PLAN`. Es el caso que el primer arreglo del cero mudo NO cubría: con
    `menciones > 0` el desenlace volvía a ser `INGEST_OK` y volvía a emitir la
    frase tranquilizadora, que es la que causa la inacción.

    Los nombres salen del catálogo de ejemplo, así que se reconocen; lo que no
    hay es ninguna frase de relación entre ellos.
    """
    import shutil

    destino = tmp_path / "fuentes"
    shutil.copytree(EJEMPLOS, destino)
    (destino / "nota-cofradia-de-ambar.md").unlink()
    (destino / "nota-solo-menciones.md").write_text(
        "# Nota de sesion\n\n"
        "## Quien estaba en la mesa\n\n"
        "Sela Marrec. Bren Halloway. Vado Alto.\n\n"
        "## Lo que se hablo\n\n"
        "Se reviso el calendario y se acordo continuar la semana que viene.\n",
        encoding="utf-8",
    )
    return destino


@pytest.fixture
def fuente_abstain(tmp_path):
    """UNA SOLA FRASE del fichero de ejemplo del repo. Produce ABSTAIN y CERO REVIEW.

    No es un corpus paralelo: es la primera frase de
    `examples/ingesta-v3/nota-cofradia-de-ambar.md`, copiada tal cual. El
    corpus estándar tiene una mezcla de veredictos FIJA (`REVIEW:2, ACCEPT:1,
    ABSTAIN:2`), así que `REVIEW` siempre es > 0 y el eje «qué veredictos
    salieron» no se podía recorrer con él. Aislar la frase que ya daba los dos
    ABSTAIN es la fuente mínima que abre ese eje.

    MEDIDO contra el motor: menciones 3, `by_outcome = {'ABSTAIN': 2}`,
    `cola.propuestas = 2`. Ni un solo `REVIEW`, y aun así DOS propuestas
    revisables en la consola.
    """
    import shutil

    destino = tmp_path / "fuentes"
    shutil.copytree(EJEMPLOS, destino)
    original = (destino / "nota-cofradia-de-ambar.md").read_text(encoding="utf-8")
    frase = "Sela Marrec es miembro de la Cofradia de Ambar y vive en Vado Alto."
    assert frase in original, (
        "la frase ya no está en el fichero de ejemplo: esta fuente dejaría de "
        "ser «una frase del corpus» y pasaría a ser un corpus inventado"
    )
    (destino / "nota-cofradia-de-ambar.md").unlink()
    (destino / "nota-solo-abstain.md").write_text(
        f"# Nota de sesion\n\n## Quien estaba en la mesa\n\n{frase}\n",
        encoding="utf-8",
    )
    return destino


def _ingerir(operador, cola, fuentes, monkeypatch) -> tuple[str, dict]:
    """Una ingesta COMPLETA desde el panel. Devuelve (job_id, resultado)."""
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(fuentes))
    pantalla = operador.get(SLOT_B.prefix)
    assert pantalla.status_code == 200, pantalla.status_code
    opciones = _opciones(pantalla.text)
    assert opciones, "el catálogo no ofrece ninguna fuente"

    envio = operador.post(
        "/panel/operations/ingestas",
        data={"fuente": opciones[0], "csrf_token": _csrf(pantalla.text)},
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


def _acuse(operador, job_id):
    """La pantalla a la que el POST redirige. La que el operador VE."""
    respuesta = operador.get(f"{SLOT_B.prefix}?solicitado={job_id}")
    assert respuesta.status_code == 200, respuesta.status_code
    return respuesta.text


def _frase_del_resultado(html: str) -> str:
    """La frase del desenlace, extraída del HTML, para CITARLA en un rojo.

    Un `assert ..., html[:600]` produce un mensaje que empieza por líneas en
    blanco y se lee como un rojo sin causa. El testigo tiene que decir qué
    pone la pantalla, no enseñar el marcado entero.
    """
    bloque = re.search(r'data-role="resultado".*?<p>(.*?)</p>', html, re.S)
    return " ".join(bloque.group(1).split()) if bloque else "(sin frase)"


def _carencias_pintadas(html: str) -> list[str]:
    """Los códigos de carencia que están EN EL HTML. No en un diccionario."""
    bloque = re.search(r'data-role="carencias".*?</section>', html, re.S)
    if bloque is None:
        return []
    return re.findall(r'data-carencia="([^"]+)"', bloque.group(0))


# ===========================================================================
# 1. EL CERO MUDO
# ===========================================================================

def test_una_ingesta_que_no_cosecha_nada_lo_DICE_en_la_pantalla(
    real_app, paneles_on, cola, operador, almacen_de_propuestas,
    fuente_muda, monkeypatch,
):
    """El primer `USABLE = no` del recorrido, cerrado y MEDIDO POR PANTALLA.

    Antes: verde, `INGEST_OK`, «La ingesta ha terminado correctamente y no ha
    dejado nada en revisión», menciones 0, afirmaciones 0, propuestas 0 y
    `cadena detenida en: engine` sin destacar. El operador daba el documento
    por ingerido y limpio, archivaba el original y pasaba al siguiente. No
    entró ni una sola afirmación. Es INACCIÓN, y el motivo existía a un log
    de distancia.
    """
    job_id, resultado = _ingerir(operador, cola, fuente_muda, monkeypatch)

    # PRIMERO SE DEMUESTRA EL CASO: la corrida es de verdad una cosecha cero.
    # Sin esto el testigo se pondría verde con cualquier ingesta.
    resumen = resultado["resumen"]
    assert not resumen["menciones"], resumen
    assert not resumen["afirmaciones"], resumen
    assert not resumen["en_revision"], resumen

    html = _acuse(operador, job_id)

    # 1.a El desenlace TIENE NOMBRE PROPIO y no se disfraza de éxito limpio.
    assert 'data-resultado-code="INGEST_SIN_EXTRACCION"' in html, (
        "una corrida que no extrajo NADA se sigue acusando como una ingesta "
        "correcta cualquiera"
    )
    assert FRASE_TRANQUILIZADORA not in html, (
        "la pantalla sigue diciendo «no ha dejado nada en revisión», que es "
        "lo que el operador lee como «estaba todo claro»"
    )

    # 1.b EL MOTIVO, que el motor ya declaraba, ESTÁ EN LA PANTALLA.
    codigos = _carencias_pintadas(html)
    assert codigos, (
        "el motor declaró sus carencias y la pantalla no pinta ninguna: el "
        "motivo se sigue quedando en el log"
    )
    assert "SIN_MENCIONES" in codigos, codigos

    # 1.c Y SE LEE COMO UNA FRASE, no como un código crudo.
    assert "ningun nombre del texto figura en el glosario" in html, html[:400]

    # 1.d REPO PÚBLICO: el `detail` del motor NO cruza. Lleva `stop_reason` e
    # identificadores del grafo dentro, y la pantalla publica el CÓDIGO.
    assert str(fuente_muda) not in html
    assert "Traceback" not in html


def test_si_borro_el_bloque_de_carencias_este_testigo_se_pone_rojo(
    real_app, paneles_on, cola, operador, almacen_de_propuestas,
    fuente_muda, monkeypatch,
):
    """CONTROL NEGATIVO DE VISIBILIDAD, ejecutado, no prometido.

    La garantía de este corte es VISIBLE. Este testigo quita el apartado de
    carencias del contexto de la plantilla —exactamente lo que pasaría si
    alguien borrara el bloque del HTML— y exige que la pantalla CAMBIE. Si no
    cambiara, el apartado no lo estaría pintando la plantilla y todos los
    testigos de arriba estarían mirando otra cosa.
    """
    job_id, _ = _ingerir(operador, cola, fuente_muda, monkeypatch)
    con_bloque = _acuse(operador, job_id)
    assert _carencias_pintadas(con_bloque), "el caso base ya no pinta nada"

    from app.routers import chassis_operations

    monkeypatch.setattr(
        chassis_operations, "_carencias_del_resultado", lambda _bruto: []
    )
    sin_bloque = _acuse(operador, job_id)
    assert not _carencias_pintadas(sin_bloque), (
        "la pantalla pinta el apartado de carencias VENGA DE DONDE VENGA: no "
        "está leyendo el dato que este corte publica"
    )
    assert con_bloque != sin_bloque


def test_las_carencias_desconocidas_se_nombran_en_vez_de_desaparecer(
    real_app, paneles_on, cola, operador, almacen_de_propuestas,
    fuente_muda, monkeypatch,
):
    """Una carencia que el visor no sabe traducir NO se cae por el desagüe.

    Descartarla en silencio sería reintroducir «ausencia == cero» en la misma
    pantalla que este corte existe para arreglar.
    """
    from app import panel_errors

    assert "CARENCIA_QUE_NADIE_TRADUJO" not in panel_errors.CARENCIAS
    frase = panel_errors.carencia("CARENCIA_QUE_NADIE_TRADUJO")
    assert "CARENCIA_QUE_NADIE_TRADUJO" in frase
    assert "administra el servicio" in frase

    # Y llega HASTA LA PANTALLA, no sólo hasta la función.
    from app.routers import chassis_operations

    vistas = chassis_operations._carencias_del_resultado(
        ["CARENCIA_QUE_NADIE_TRADUJO", "no es un codigo", ""]
    )
    assert [v["code"] for v in vistas] == ["CARENCIA_QUE_NADIE_TRADUJO"], vistas


# ===========================================================================
# 2. `PLAN_SUPERSEDED` NO FABRICA CAUSALIDAD
# ===========================================================================

def test_la_pantalla_no_afirma_que_una_decision_cambio(real_app):
    """Ni en `PLAN_SUPERSEDED` ni en ninguna otra parte del catálogo.

    Se comprueba sobre el CATÁLOGO ENTERO, no sobre una fila: la frase era el
    defecto, y volver a escribirla en otra fila lo reabriría igual.
    """
    from app import panel_errors

    culpables = [
        codigo for codigo, frase in panel_errors.CATALOGO.items()
        if CAUSALIDAD_FABRICADA in frase
    ]
    assert not culpables, (
        f"{culpables} afirman una causa que el código no comprueba: al estado "
        "`superseded` se llega por tres caminos y sólo uno es ése"
    )
    limitado = panel_errors.CATALOGO["PLAN_SUPERSEDED"]
    assert "ya no es aplicable" in limitado, limitado
    assert "volver a preparar" in limitado, limitado


def test_el_camino_del_apply_fallido_se_distingue_y_se_dice(real_app):
    """MEDIDO EN EL DATO: el almacén SÍ distingue uno de los tres caminos.

    `apply_notes_json` lo escribe ÚNICAMENTE `finish_apply`: el `INSERT` del
    sellado no incluye la columna y `_supersede_sealed` sólo toca `state`. Una
    fila `superseded` CON notas de apply es, por tanto, un apply que falló — y
    ahí el mensaje anterior ocultaba que lo que falló fue la ESCRITURA.

    Este testigo lo comprueba por AST sobre el almacén, no contando texto: una
    búsqueda de la cadena `apply_notes_json` daría verde aunque el `INSERT`
    la escribiera, que es justo lo que invalidaría la distinción.
    """
    import ast
    import inspect

    from app.services import v3_review_store

    fuente = inspect.getsource(v3_review_store)
    arbol = ast.parse(fuente)

    def _sql_de(nombre: str) -> str:
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.FunctionDef) and nodo.name == nombre:
                return " ".join(
                    n.value for n in ast.walk(nodo)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                )
        raise AssertionError(f"no existe {nombre} en el almacén")

    assert "apply_notes_json" not in _sql_de("seal_plan"), (
        "el sellado escribe `apply_notes_json`: la columna deja de distinguir "
        "el camino del apply fallido"
    )
    assert "apply_notes_json" not in _sql_de("_supersede_sealed")
    assert "apply_notes_json" in _sql_de("record_apply_result")

    # Y el servicio publica ESE código cuando la distinción existe.
    from app.services import v3_apply

    assert "PLAN_SUPERSEDED_TRAS_APPLY_FALLIDO" in v3_apply.CODIGOS
    frase = __import__(
        "app.panel_errors", fromlist=["CATALOGO"]
    ).CATALOGO["PLAN_SUPERSEDED_TRAS_APPLY_FALLIDO"]
    assert "no salio bien" in frase and "no se escribio nada" in frase, frase


def test_el_rechazo_del_writer_llega_al_operador_con_su_motivo(real_app):
    """`APPLY_REJECTED` dejaba al operador reintentando en bucle.

    El motivo —`EXEC_SCHEMA_CONSTRAINTS_MISSING` entre otros— se perdía entre
    un `log.error(...)` y el `raise` de la línea siguiente. Ahora los rechazos
    que cambian LA DECISIÓN de quien lee (si reintentar sirve o no) tienen
    frase propia, y todos siguen siendo códigos del catálogo cerrado.
    """
    from app import panel_errors
    from app.services import v3_apply

    for writer_code, publico in v3_apply.RECHAZOS_CON_CAUSA.items():
        assert publico in v3_apply.CODIGOS, publico
        assert publico in panel_errors.CATALOGO, publico
        # El código INTERNO del writer no se publica como texto al operador.
        assert writer_code not in panel_errors.CATALOGO[publico]

    assert v3_apply._codigo_de_rechazo(
        ["EXEC_SCHEMA_CONSTRAINTS_MISSING"]
    ) == "APPLY_REJECTED_ESQUEMA"
    # Un rechazo que no está en el mapa NO se disfraza de uno que sí.
    assert v3_apply._codigo_de_rechazo(["EXEC_ALGO_NUEVO"]) == "APPLY_REJECTED"
    assert v3_apply._codigo_de_rechazo([]) == "APPLY_REJECTED"

    # Y NO PROMETE LO QUE NO SABE: el mismo código lo emite el writer cuando
    # faltan restricciones Y cuando no pudo consultarlas (grafo inalcanzable).
    esquema = panel_errors.CATALOGO["APPLY_REJECTED_ESQUEMA"]
    assert "no se han podido comprobar" in esquema, esquema


# ===========================================================================
# 3. EL ENLACE DEL ACUSE
# ===========================================================================

def test_la_consola_que_decide_acepta_la_corrida_puesta(real_app):
    """El destino del enlace tiene que admitir el `job_id` de ESTA corrida.

    Sin esto el enlace llevaría a la cola entera del workspace y el operador
    tendría que buscar sus propuestas a mano — o teclear identificadores, que
    es lo que el chasis prohíbe.
    """
    import inspect

    from app.routers import v3_review

    firma = inspect.signature(v3_review.queue)
    assert "job_id" in firma.parameters, (
        "la consola que decide no sabe filtrar por corrida"
    )

    decide = real_app.url_path_for("v3_review_queue")
    assert str(decide).startswith("/v3/review"), decide
    # La consola de SÓLO LECTURA sigue existiendo y sigue siendo OTRA.
    solo_lectura = real_app.url_path_for("chassis_review")
    assert str(solo_lectura).startswith(SLOT_C.prefix), solo_lectura
    assert str(decide) != str(solo_lectura)


def test_una_cosecha_esteril_no_se_anuncia_como_tranquilizadora(
    real_app, paneles_on, cola, operador, almacen_de_propuestas,
    fuente_esteril, monkeypatch,
):
    """EL RESIDUO DEL CERO MUDO: menciones > 0, afirmaciones 0, revisión 0.

    El primer arreglo condicionaba el desenlace a `menciones == 0 and
    afirmaciones == 0`, así que esta corrida seguía siendo `INGEST_OK` y seguía
    diciendo «…y no ha dejado nada en revisión» — la misma frase que el
    operador lee como «estaba todo claro» y por la que archiva la fuente.

    Y NO SE ARREGLA con un `or`: aquí el motor SÍ reconoció tres menciones, así
    que anunciar «no ha extraído nada» sería el error SIMÉTRICO y mandaría al
    operador a revisar un glosario que funciona. Lo que tiene que desaparecer
    es la TRANQUILIDAD, no la cifra.
    """
    job_id, resultado = _ingerir(operador, cola, fuente_esteril, monkeypatch)

    # EL CASO, DEMOSTRADO PRIMERO. Sin esto el testigo no distingue este
    # desenlace del doble cero que ya estaba cubierto.
    resumen = resultado["resumen"]
    assert resumen["menciones"] > 0, resumen
    assert not resumen["afirmaciones"], resumen
    assert not resumen["en_revision"], resumen

    html = _acuse(operador, job_id)

    # 1. LA FRASE TRANQUILIZADORA NO SE EMITE.
    assert FRASE_TRANQUILIZADORA not in html, (
        "con menciones cosechadas y CERO propuestas la pantalla sigue diciendo "
        "«no ha dejado nada en revisión» como si todo estuviera claro"
    )

    # 2. NI SE COMETE EL ERROR SIMÉTRICO: hubo extracción y se dice.
    assert 'data-resultado-code="INGEST_SIN_EXTRACCION"' not in html, (
        "se anuncia «no se extrajo nada» habiendo reconocido menciones: es la "
        "mentira simétrica, y manda a revisar un glosario que funciona"
    )
    assert str(resumen["menciones"]) in html

    # 3. Y EL MOTIVO ESTÁ, que es lo que convierte el vacío en accionable.
    codigos = _carencias_pintadas(html)
    assert "SIN_CLAIMS" in codigos, codigos


def test_las_cinco_ramas_del_desenlace_estan_cerradas(real_app):
    """LAS RAMAS QUE EL CORPUS NO ALCANZA, cubiertas por enumeración.

    `_desenlace` nació como un `if/elif` dentro del manejador y una de sus
    ramas —la corrida SANA— se quedó sin asignar `mensaje`: habría reventado
    con `UnboundLocalError` en producción, en la ingesta más limpia posible. La
    suite entera seguía verde porque el corpus de ejemplo no produce ese caso.
    Lo destapó una mutación.

    EL GUARDIÁN ES INSENSIBLE A MAYÚSCULAS a propósito: comparar la frase tal
    cual dejaba pasar una frase genuinamente tranquilizadora con una sola letra
    cambiada, y un guardián que se esquiva cambiando una letra no guarda nada.
    """
    import sys
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(raiz / "data-engine" / "app"))
    from jobs.handlers.ingest_v3 import CARENCIAS_DE_COSECHA, _desenlace

    def tranquiliza(mensaje: str) -> bool:
        """N-4. La comparación literal se esquiva con una mayúscula."""
        return FRASE_TRANQUILIZADORA.lower() in mensaje.lower()

    # 1. Cola con propuestas Y veredictos REVIEW: conduce, y dice las dos cifras.
    codigo, mensaje = _desenlace(
        {"en_revision": 2, "menciones": 10, "afirmaciones": 1,
         "propuestas_de_revision": 4},
        ["PLAN_REVISION_SIN_OPERACIONES", "SIN_ESCRITURA"],
    )
    assert codigo == "INGEST_OK"
    assert "2 decisiones en REVIEW" in mensaje
    assert "4 propuestas revisables" in mensaje, (
        "el acuse oculta que la cola tiene MÁS propuestas que decisiones REVIEW"
    )
    assert not tranquiliza(mensaje), f"rama 1 tranquiliza: {mensaje!r}"

    # 2. LA COSTURA DEL RECUENTO: propuestas en la cola y CERO `REVIEW`.
    #    Es el caso que hacía que el acuse se contradijera a sí mismo.
    codigo, mensaje = _desenlace(
        {"en_revision": 0, "menciones": 3, "afirmaciones": 0,
         "propuestas_de_revision": 2},
        ["PLAN_NO_APROBADO", "PLAN_REVISION_SIN_OPERACIONES"],
    )
    assert codigo == "INGEST_OK"
    assert not tranquiliza(mensaje), (
        "con DOS propuestas en la cola el acuse dice que no dejó nada que revisar"
    )
    assert "2 propuestas revisables" in mensaje, mensaje

    # 3. `None` NO ES CERO: sin cola exportada no se afirma que no quedó nada.
    codigo, mensaje = _desenlace(
        {"en_revision": 0, "menciones": 3, "afirmaciones": 0,
         "propuestas_de_revision": None},
        ["SIN_CLAIMS"],
    )
    assert not tranquiliza(mensaje), (
        "sin cola exportada se afirma que no quedó nada: eso es inventar el dato"
    )

    # 4. Doble cero: no se extrajo nada, y se dice.
    codigo, mensaje = _desenlace(
        {"en_revision": 0, "menciones": 0, "afirmaciones": 0,
         "propuestas_de_revision": 0},
        ["SIN_MENCIONES", "SIN_CLAIMS"],
    )
    assert codigo == "INGEST_SIN_EXTRACCION"
    assert not tranquiliza(mensaje), f"rama 4 (doble cero) tranquiliza: {mensaje!r}"

    # 5. Cosecha estéril: hubo menciones y aun así la cola quedó vacía. NI
    #    tranquiliza NI comete el error simétrico de negar la extracción.
    codigo, mensaje = _desenlace(
        {"en_revision": 0, "menciones": 3, "afirmaciones": 0,
         "propuestas_de_revision": 0},
        ["SIN_CLAIMS"],
    )
    assert codigo == "INGEST_OK"
    assert not tranquiliza(mensaje), (
        "rama 5: se cosecharon menciones, la cola quedó VACÍA y la pantalla lo "
        f"anuncia como si estuviera todo claro: {mensaje!r}"
    )
    assert "3 menciones" in mensaje, (
        "rama 5 no dice cuántas menciones se reconocieron, así que el operador "
        f"no puede distinguirlo de «no se extrajo nada»: {mensaje!r}"
    )

    # 6. LA RAMA SANA. Única en la que la frase tranquilizadora es cierta, y la
    #    que se quedó sin `mensaje`.
    codigo, mensaje = _desenlace(
        {"en_revision": 0, "menciones": 10, "afirmaciones": 4,
         "propuestas_de_revision": 0},
        ["SIN_ESCRITURA"],
    )
    assert codigo == "INGEST_OK"
    assert isinstance(mensaje, str) and mensaje, "la rama sana no produce frase"
    assert tranquiliza(mensaje), mensaje

    # `SIN_ESCRITURA` NO es carencia de cosecha: se emite en toda corrida sana.
    assert "SIN_ESCRITURA" not in CARENCIAS_DE_COSECHA
    # Y `PLAN_REVISION_SIN_OPERACIONES` TAMPOCO, aunque sea la séptima que el
    # motor emite: MEDIDO, el corpus estándar —sano, con 4 propuestas en la
    # cola— la declara. Tratarla como carencia de cosecha clasificaría de
    # estéril a la corrida más normal del repositorio.
    assert "PLAN_REVISION_SIN_OPERACIONES" not in CARENCIAS_DE_COSECHA


def test_con_ABSTAIN_y_sin_REVIEW_el_acuse_no_se_contradice_a_si_mismo(
    real_app, paneles_on, cola, operador, almacen_de_propuestas,
    fuente_abstain, monkeypatch,
):
    """LA COSTURA DEL RECUENTO, medida en la pantalla. Eje de VEREDICTOS.

    Había DOS autoridades en desacuerdo sobre qué es «estar en revisión»:

      · `resumen["en_revision"]` cuenta SÓLO el veredicto `REVIEW` — decisión
        deliberada y documentada del Corte 4, que lo separó de la revisión de
        identidad;
      · la cola exporta `REVIEW`, `ABSTAIN` y `REJECT_INVALID`.

    Con ABSTAIN y sin REVIEW el acuse decía «no ha dejado nada en revisión»
    MIENTRAS su propio bloque de enlace ofrecía las propuestas y enlazaba a
    ellas. Una pantalla que se contradice a sí misma: la propiedad exacta de
    este corte, una casilla de veredicto más allá del Corte 4.

    EL CONTADOR NO SE TOCA (rompería lo que el Corte 4 decidió y su testigo).
    Lo que cambia es de qué cuelga la decisión: de la COLA, que es lo que la
    consola contiene y lo que el bloque de enlace ya usaba. UNA autoridad.
    """
    job_id, resultado = _ingerir(operador, cola, fuente_abstain, monkeypatch)

    # EL CASO, DEMOSTRADO PRIMERO: la región existe y es ésta.
    resumen = resultado["resumen"]
    assert resumen["por_veredicto"].get("REVIEW", 0) == 0, resumen["por_veredicto"]
    assert resumen["por_veredicto"].get("ABSTAIN", 0) > 0, resumen["por_veredicto"]
    assert resumen["en_revision"] == 0, "el contador de REVIEW ya no es 0"
    propuestas = resumen["propuestas_de_revision"]
    assert propuestas, "sin propuestas en la cola no hay contradicción que medir"

    html = _acuse(operador, job_id)

    # 1. LA PANTALLA NO NIEGA LO QUE ELLA MISMA OFRECE.
    assert FRASE_TRANQUILIZADORA.lower() not in html.lower(), (
        f"el acuse dice «no ha dejado nada en revisión» con {propuestas} "
        "propuestas revisables en la cola, y las enlaza en el mismo acuse"
    )

    # 2. Y EL BLOQUE DE ENLACE SIGUE OFRECIÉNDOLAS: es la otra mitad de la
    #    contradicción, y tiene que seguir ahí para que el caso sea real.
    assert 'data-role="enlace-revision"' in html, (
        "el acuse ya no ofrece el enlace a la revisión: sin él no hay "
        "contradicción que medir y este testigo dejaría de vigilar el caso"
    )
    assert f'data-revision-propuestas="{propuestas}"' in html, (
        f"el bloque de enlace no declara las {propuestas} propuestas que la "
        "corrida dejó en la cola"
    )

    # 3. EL ACUSE CONDUCE: dice cuántas hay que revisar.
    #
    # EL MENSAJE DEL ROJO NOMBRA LA CAUSA, no vuelca el HTML. Volcarlo daba un
    # `AssertionError:` que empezaba por líneas en blanco y se leía como un
    # rojo sin causa — y un rojo que no dice de qué va no es una garantía.
    assert f"{propuestas} propuestas revisables" in html, (
        f"el acuse no dice que hay {propuestas} propuestas que revisar. Lo que "
        f"dice es: {_frase_del_resultado(html)!r}"
    )

    # 4. Y NO INVENTA UN `REVIEW` QUE NO HUBO.
    assert "decisiones en REVIEW" not in html, (
        "se anuncian decisiones en REVIEW cuando el motor se abstuvo en todas"
    )


def test_la_enumeracion_de_esta_cabecera_es_exhaustiva():
    """La cabecera dice ser el reparto REAL. Que lo sea no puede ser confianza.

    Esta enumeración YA se quedó corta una vez: se escribió clasificando ocho
    casos y un commit posterior añadió un noveno sin tocarla, de modo que un
    párrafo escrito para dejar de afirmar de más volvió a afirmar de más. Una
    lista que se mantiene a mano se desincroniza; una que se comprueba, no.
    """
    import re

    fuente = Path(__file__).read_text(encoding="utf-8")
    cabecera = fuente[: fuente.index("from __future__")]
    definidos = set(re.findall(r"^def (test_\w+)", fuente, re.M))
    assert definidos, "no se encontró ningún caso: el parseo está roto"
    faltan = sorted(t for t in definidos if t not in cabecera)
    assert not faltan, (
        f"la cabecera se presenta como el reparto REAL y no menciona {faltan}: "
        "clasifícalos (¿piden la pantalla o miran el dato?) y di qué mutación "
        "pone rojo a cada uno"
    )
