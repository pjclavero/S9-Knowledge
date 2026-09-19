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
la suite se moviera. Todos los testigos de aquí hacen un GET de la pantalla
real del operador y leen el HTML que llega al navegador.
"""
from __future__ import annotations

import json
import re

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
