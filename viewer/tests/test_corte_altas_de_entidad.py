# -*- coding: utf-8 -*-
"""CORTE DE ALTAS DE ENTIDAD — de «no hay :Entity» a un alta decidida por una persona.

EL DEFECTO QUE ESTE MÓDULO FIJA, Y QUE NO ES UNA TUBERÍA SUELTA
---------------------------------------------------------------
El recorrido revisión -> apply terminaba con `V3Assertion`, `V3Evidence` y
`V3Source` y SIN NINGUNA `:Entity`. El panel ofrecía entonces un enlace al
resultado que acababa en 404, porque el ámbito del lector se deriva de las
entidades. La causa estaba medida por intervención: inyectando UNA sola
`:Entity` con `entity_id`, el workspace aparecía en `workspaces()` y el mismo
destino pasaba de 404 a 200.

Pero la ausencia de `CREATE_ENTITY` era una DECISIÓN, escrita en la cabecera de
`review_plan.py`: «aprobar una propuesta de revisión NO es aprobar el alta de
una entidad, y esa frontera la cruza una persona, no este módulo». Lo que
faltaba no era emitir la operación: era la SEGUNDA DECISIÓN, que sólo se podía
tomar desde la línea de comandos y de una en una.

Por eso estas pruebas no comprueban «el plan trae un CREATE_ENTITY». Comprueban
que lo trae **si y sólo si** una persona aprobó ESA alta, por su identificador,
en la autoridad canónica, y que la frontera sigue en pie en los dos sentidos.

QUÉ SE MIDE Y QUÉ NO
--------------------
Los testigos de pantalla PIDEN LA PANTALLA (GET del HTML servido por la app
real, con auth real y CSRF real) y enumeran el marcado que el producto genera.
Los testigos de decisión miran el ALMACÉN por dentro, en sólo lectura, para
afirmar ausencia de escritura — una ausencia no se demuestra con un recuento
de pantalla.

Lo que NO se mide aquí: que el nodo quede escrito en un Neo4j real. Eso lo
cubre el recorrido con grafo de `test_panel_apply_desde_la_ui.py`, que se
SALTA sin `S9K_WRITER_NEO4J_REAL=1`. Se dice en vez de insinuar que el alta
está ejercida contra infraestructura.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

# EL ARNÉS NO SE DUPLICA. Se importan las fixtures y los pasos del recorrido
# del módulo que ya los define: una segunda copia del arnés es una segunda
# definición de «cómo se ingiere», y el día que una cambie la otra medirá otra
# cosa sin que nadie se entere.
from test_panel_apply_desde_la_ui import (  # noqa: F401
    SLOT_B,
    _aplicable,
    _aplicar,
    _aviso_de,
    _cliente,
    _cookie,
    _csrf,
    _decidir,
    _entorno_limpio,
    _filas_de_plan,
    _grafo_de_mentira,
    _ingerir,
    _propuestas,
    _salud_aislada,
    _sellar,
    almacenes,
    auth_on,
    cola,
    grafo,
    grafo_real,
    neo4j_real,
    operador,
    paneles_on,
    real_app,
    resultado_on,
    revisor,
    visor_sobre_el_grafo,
)

#: LA CLAVE DEL SOBRE, repetida a propósito. El servicio del visor la declara
#: como constante local (`v3_apply.ALTAS_KEY`) para no cargar el puente del
#: motor sólo para leer una cadena. Aquí se comprueba que las dos coinciden:
#: si el motor la renombra, esa prueba se pone roja diciendo exactamente eso,
#: en vez de que la pantalla se quede muda y nadie lo note.
CLAVE_SOBRE = "entity_altas"


# ---------------------------------------------------------------------------
# Utilidades de medición
# ---------------------------------------------------------------------------

def _altas_del_sobre(propuestas: list, job_id: str) -> dict:
    """Las altas que la CORRIDA declaró, leídas del almacén de propuestas."""
    declaradas: dict = {}
    for propuesta in propuestas:
        bloque = (propuesta.get("plan_context_by_run") or {}).get(job_id) or {}
        declaradas.update(bloque.get(CLAVE_SOBRE) or {})
    return declaradas


def _filas_de_alta(base: Path) -> list:
    """La tabla de altas POR DENTRO. Se mira para afirmar AUSENCIA de escritura."""
    if not base.exists():
        return []
    conexion = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
    conexion.row_factory = sqlite3.Row
    try:
        filas = conexion.execute(
            "SELECT * FROM entity_altas ORDER BY entity_id"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conexion.close()
    return [dict(f) for f in filas]


def _operaciones_del_plan(base: Path) -> list:
    """Las operaciones del plan VIGENTE, con su tipo. Del documento sellado."""
    for fila in _filas_de_plan(base):
        if fila["state"] != "sealed":
            continue
        documento = json.loads(fila["plan_json"])
        return list(documento.get("mutation_operations") or [])
    return []


def _altas_en_el_plan(base: Path) -> list:
    return sorted(
        op["target_entity_id"] for op in _operaciones_del_plan(base)
        if op["operation_type"] == "CREATE_ENTITY"
    )


def _propuesta_que_menciona(propuestas: list, job_id: str, entity_id: str):
    """Una propuesta APLICABLE de esta corrida que nombra a `entity_id`.

    No vale cualquiera: un alta sólo entra en el plan si alguna afirmación del
    plan menciona a la entidad (si no, sería un nodo suelto que nada sostiene).
    Elegir una propuesta al azar mediría el camino de omisión creyendo medir el
    camino feliz — exactamente el error que `_aplicable` documenta.
    """
    for propuesta in propuestas:
        if job_id not in (propuesta.get("package_runs") or ()):
            continue
        cuerpo = propuesta.get("proposal") or {}
        resolucion = propuesta.get("resolution") or {}
        if entity_id not in (resolucion.get("subject"), resolucion.get("object")):
            continue
        if (
            cuerpo.get("predicate") not in (None, "", "UNKNOWN")
            and cuerpo.get("direction") not in (None, "", "UNKNOWN")
            and resolucion.get("subject") not in (None, "", "not_available")
            and resolucion.get("object") not in (None, "", "not_available")
        ):
            return propuesta
    return None


def _pantalla_de_altas(cliente, job_id: str):
    return cliente.get(f"{SLOT_B.prefix}/altas?trabajo={job_id}")


def _aprobar(cliente, job_id: str, entity_id: str, tipo: str = ""):
    return cliente.post(
        "/panel/operations/altas",
        data={"trabajo": job_id, "entidad": entity_id, "tipo": tipo,
              "csrf_token": _csrf(cliente)},
    )


def _tarjetas(html: str) -> dict:
    """Las tarjetas de alta que el producto pintó, por `entity_id`."""
    salida: dict = {}
    for bloque in re.findall(r'<article[^>]*data-role="alta".*?</article>', html, re.S):
        identificador = re.search(r'data-alta-id="([^"]*)"', bloque)
        if not identificador:
            continue
        salida[identificador.group(1)] = {
            "aprobada": re.search(r'data-alta-aprobada="([^"]*)"', bloque).group(1),
            "tipo": re.search(r'data-alta-tipo="([^"]*)"', bloque).group(1),
            "evidencias": re.findall(r'data-role="evidencia"[^>]*>\s*<q>(.*?)</q>',
                                     bloque, re.S),
            "form": 'data-role="form-alta"' in bloque,
            "texto": bloque,
        }
    return salida


@pytest.fixture
def corrida(operador, cola, almacenes, paneles_on, monkeypatch):
    """Una ingesta REAL por el panel, con su alta declarada en el sobre.

    Falla si el corpus deja de producir altas: sin alta no hay nada que este
    corte pueda medir, y un módulo entero que se pone verde sobre cero altas
    sería la cobertura regalada que este programa prohíbe.
    """
    job_id = _ingerir(operador, cola, monkeypatch)
    propuestas = _propuestas(almacenes["propuestas"])
    declaradas = _altas_del_sobre(propuestas, job_id)
    assert declaradas, (
        "el corpus del arnés ya no declara ninguna alta de entidad: sin alta "
        "este módulo no mide nada"
    )
    # EL ALTA SOBRE LA QUE SE MIDE EL CAMINO FELIZ: la que alguna propuesta
    # aplicable de esta corrida menciona. Si no hubiera ninguna, el positivo no
    # podría distinguirse de la omisión y el módulo entero mediría de menos.
    aplicable = None
    for entity_id in sorted(declaradas):
        propuesta = _propuesta_que_menciona(propuestas, job_id, entity_id)
        if propuesta is not None:
            aplicable = (entity_id, propuesta)
            break
    assert aplicable is not None, (
        "ninguna alta del corpus está mencionada por una propuesta aplicable: "
        "el camino feliz de este corte no se podría medir"
    )
    return {"job_id": job_id, "propuestas": propuestas, "declaradas": declaradas,
            "base": almacenes["base"],
            "entidad": aplicable[0], "propuesta": aplicable[1]}


# ===========================================================================
# 0. LA RANURA DEL SOBRE: la corrida hace la pregunta, y la hace como pregunta
# ===========================================================================

def test_la_clave_del_sobre_es_la_misma_en_el_motor_y_en_el_visor():
    """Dos módulos, una cadena. Si divergen, la pantalla se queda MUDA.

    El visor la repite como constante local para no cargar el puente del motor
    por una cadena. Eso es una segunda declaración, y una segunda declaración
    se rompe en silencio: el bloque del sobre seguiría escribiéndose y la
    pantalla diría «esta ingesta no dejó constancia».

    ROJA ASÍ: `AssertionError: el motor y el visor no nombran igual el bloque
    de altas`.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data-engine" / "app"))
    from knowledge_v3 import review_plan

    from app.services import v3_apply

    assert review_plan.ALTAS_KEY == v3_apply.ALTAS_KEY == CLAVE_SOBRE, (
        "el motor y el visor no nombran igual el bloque de altas"
    )


def test_la_corrida_declara_el_alta_como_PREGUNTA_y_nunca_como_aprobada(corrida):
    """El sobre TRANSPORTA candidatas. No aprueba ninguna.

    Un sobre que llegara con la aprobación puesta convertiría la decisión
    humana en un valor por defecto del exportador, que es exactamente la
    conversión silenciosa que toda esta frontera existe para impedir.

    ROJA ASÍ: `AssertionError: el sobre trae un campo de aprobación` — o, si el
    bloque dejara de publicarse, la fixture `corrida` se pone roja antes.
    """
    for entity_id, cuerpo in corrida["declaradas"].items():
        assert set(cuerpo) <= {
            "entity_id", "entity_type", "name", "aliases", "reason_codes",
            "mention_ids", "confidence",
        }, f"el sobre trae un campo de aprobación en {entity_id}: {sorted(cuerpo)}"
    # Y NADA ESCRITO TODAVÍA: declarar no es decidir.
    assert _filas_de_alta(corrida["base"]) == []


# ===========================================================================
# 1. LA PANTALLA. Se pide la pantalla, no un diccionario de servicio.
# ===========================================================================

def test_la_pantalla_ensena_la_entidad_y_su_evidencia(operador, corrida):
    """GET del HTML real: la entidad, su tipo y el fragmento que la sostiene.

    QUÉ TENDRÍA QUE ROMPERSE PARA QUE FALLARA: que la pantalla dejara de
    pintar la tarjeta, que dejara de traer el nombre observado, o que
    presentara la entidad SIN evidencia — decidir un alta sin material es lo
    que este corte viene a evitar.

    ROJA ASÍ: `AssertionError: la pantalla no pinta la entidad <id>` o
    `... no ofrece ni un fragmento que sostenga <id>`.
    """
    respuesta = _pantalla_de_altas(operador, corrida["job_id"])
    assert respuesta.status_code == 200, respuesta.status_code
    tarjetas = _tarjetas(respuesta.text)
    for entity_id, cuerpo in corrida["declaradas"].items():
        assert entity_id in tarjetas, f"la pantalla no pinta la entidad {entity_id}"
        assert tarjetas[entity_id]["aprobada"] == "false"
        assert tarjetas[entity_id]["form"], "no ofrece la decisión"
        assert tarjetas[entity_id]["evidencias"], (
            f"la pantalla no ofrece ni un fragmento que sostenga {entity_id}"
        )
        if cuerpo.get("name"):
            assert cuerpo["name"] in respuesta.text, (
                "el nombre observado no llega a la pantalla"
            )


def test_la_pantalla_no_ofrece_aprobar_todas(operador, corrida):
    """NO HAY «APROBAR TODAS», ni con otro nombre.

    Se comprueba por ENUMERACIÓN del marcado: hay tantos formularios de
    decisión como altas pendientes, y cada uno manda UNA entidad concreta en
    un campo `hidden`. Un botón que aprobara varias tendría que mandar una
    lista, o ninguna, y las dos cosas se ven aquí.

    ROJA ASÍ: `AssertionError: hay N formularios para M altas pendientes` o
    `AssertionError: un formulario de alta no manda una entidad concreta`.
    """
    html = _pantalla_de_altas(operador, corrida["job_id"]).text
    formularios = re.findall(
        r'<form[^>]*data-role="form-alta".*?</form>', html, re.S
    )
    assert len(formularios) == len(corrida["declaradas"]), (
        f"hay {len(formularios)} formularios para "
        f"{len(corrida['declaradas'])} altas pendientes"
    )
    for formulario in formularios:
        entidades = re.findall(r'name="entidad"[^>]*value="([^"]+)"', formulario)
        assert len(entidades) == 1, (
            "un formulario de alta no manda una entidad concreta: "
            f"{entidades}"
        )


def test_una_corrida_de_otro_ambito_no_abre_la_pantalla(operador, corrida):
    """La corrida se resuelve CONTRA LA COLA, no contra el query string.

    Un `job_id` que el llamante no puede ver no abre la pantalla ni con su id
    en la URL, y no se degrada a «no hay altas»: eso se leería como «esta
    ingesta no necesita ninguna», que es una afirmación distinta.

    ROJA ASÍ: un 200 donde se espera 404, con
    `AssertionError: una corrida inexistente abrió la pantalla`.
    """
    respuesta = _pantalla_de_altas(operador, "job-que-no-existe")
    assert respuesta.status_code == 404, (
        "una corrida inexistente abrió la pantalla"
    )
    assert 'data-altas-estado="sin-corrida"' in respuesta.text
    assert 'data-role="alta"' not in respuesta.text


def test_la_consola_enlaza_a_la_decision_pendiente(operador, corrida):
    """El camino existe desde donde el operador ya está.

    Un corte anterior midió que «aplicado» era un callejón sin salida porque
    el bloque no contenía ni un enlace. Aquí se comprueba lo mismo un paso
    antes: la consola dice cuántas entidades esperan y CÓMO llegar a ellas.

    ROJA ASÍ: `AssertionError: la consola no dice que hay altas pendientes` o
    `... no ofrece camino hasta la decisión`.
    """
    html = operador.get(f"{SLOT_B.prefix}?solicitado={corrida['job_id']}").text
    bloque = re.search(
        r'<section[^>]*data-role="altas-de-entidad".*?</section>', html, re.S
    )
    assert bloque, "la consola no publica el bloque de altas"
    texto = bloque.group(0)
    assert 'data-altas-declarado="true"' in texto
    assert f'data-altas-pendientes="{len(corrida["declaradas"])}"' in texto, (
        "la consola no dice que hay altas pendientes"
    )
    assert 'data-role="enlace-altas"' in texto, (
        "la consola no ofrece camino hasta la decisión"
    )


# ===========================================================================
# 2. AUTORIZACIÓN Y AUDITORÍA de una decisión que es distinta de las demás
# ===========================================================================

def test_un_revisor_no_puede_aprobar_un_alta(revisor, corrida, almacenes):
    """Aprobar una entidad NUEVA es un acto de administración, no de revisión.

    ESTE VERDE ESTÁ SOBREDETERMINADO, Y SE DICE — porque se MIDIÓ. Retirando la
    guarda de rol del manejador, esta prueba SIGUE EN VERDE: al `reviewer` lo
    para además la resolución de la corrida con ámbito (`_corrida_visible`),
    que no le deja ver ese trabajo. Comprueba «un reviewer no aprueba», que es
    cierto y es lo que le importa al producto, pero NO aísla cuál de las dos
    puertas lo impide, y leerla como prueba de la guarda de rol sería leer un
    verde por la razón equivocada.

    La guarda de rol, aislada, la mide por estructura
    `test_el_manejador_del_alta_pasa_por_la_guarda_del_hueco`. Hacen falta las
    dos.

    ROJA ASÍ: `AssertionError: un reviewer aprobó un alta` — y lo que la pone
    roja es la TABLA, no el código de respuesta: una ausencia de escritura no
    se demuestra con un 403.
    """
    entity_id = sorted(corrida["declaradas"])[0]
    respuesta = _aprobar(revisor, corrida["job_id"], entity_id)
    assert respuesta.status_code in (302, 303, 403), respuesta.status_code
    assert _filas_de_alta(almacenes["base"]) == [], "un reviewer aprobó un alta"


def test_el_manejador_del_alta_pasa_por_la_guarda_del_hueco():
    """La guarda de rol, AISLADA y por estructura. Se PARSEA, no se cuenta.

    Existe porque el testigo de comportamiento de arriba está sobredeterminado:
    con la guarda retirada sigue verde, porque al revisor lo para también el
    ámbito. Aquí se mira el ÁRBOL del manejador y se exige lo que la guarda es:

      * que su parámetro `user` venga de `Depends(slot_guard(SLOT))` — la misma
        puerta del hueco que usan el sellado y el apply, no una propia;
      * que el cuerpo delegue en `_accion`, que es quien llama a `_authorize`
        ANTES que a nada. Un manejador que hiciera el trabajo por su cuenta se
        saltaría ese orden sin que el rol declarado cambiara de sitio.

    EL TECHO DE ESTA RED, DECLARADO — una red que no dice qué no ve se lee como
    completa. Ve la FORMA del manejador; NO ve:

      * que `slot_guard` siga exigiendo `admin` (eso lo fija la capacidad
        declarada, y lo comprueba `test_la_capacidad_esta_declarada_...`);
      * un `_accion` degradado POR DENTRO (lo cubren los negativos de los otros
        dos POST del hueco, que comparten esqueleto);
      * una guarda retirada en tiempo de ejecución (monkeypatch, decorador).

    ROJA ASÍ: `AssertionError: el manejador del alta no pasa por slot_guard` o
    `AssertionError: el manejador del alta no delega en _accion`.
    """
    import ast

    from app.routers import chassis_operations as panel_ops

    arbol = ast.parse(Path(panel_ops.__file__).read_text(encoding="utf-8"))
    manejador = next(
        (n for n in ast.walk(arbol)
         if isinstance(n, ast.FunctionDef) and n.name == "aprobar_alta"),
        None,
    )
    assert manejador is not None, "no existe el manejador del alta"
    defectos = [
        ast.unparse(d) for d in manejador.args.defaults if isinstance(d, ast.Call)
    ]
    assert any("slot_guard(SLOT)" in d for d in defectos), (
        f"el manejador del alta no pasa por slot_guard: {defectos}"
    )
    llamadas = {
        n.func.id for n in ast.walk(manejador)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "_accion" in llamadas, (
        f"el manejador del alta no delega en _accion: {sorted(llamadas)}"
    )


def test_sin_csrf_no_se_aprueba_ningun_alta(operador, corrida, almacenes):
    """La segunda mitad de la puerta, medida aparte de la primera.

    ROJA ASÍ: la tabla de altas deja de estar vacía tras un POST sin token.
    """
    entity_id = sorted(corrida["declaradas"])[0]
    respuesta = operador.post(
        "/panel/operations/altas",
        data={"trabajo": corrida["job_id"], "entidad": entity_id, "tipo": "",
              "csrf_token": "token-invalido"},
    )
    assert respuesta.status_code in (302, 303, 403), respuesta.status_code
    assert _filas_de_alta(almacenes["base"]) == [], "se aprobó sin CSRF válido"


def test_la_aprobacion_deja_autor_momento_y_alcance(operador, corrida, almacenes):
    """Una aprobación tiene autor, momento y alcance. Los tres CONSTAN.

    Y el autor sale de la SESIÓN, no del formulario: una atribución que
    escribe el cliente no es una atribución.

    ROJA ASÍ: `AssertionError: la aprobación no consta con autor` /
    `... sin momento` / `... sin el ámbito en el que se tomó`.
    """
    entity_id = sorted(corrida["declaradas"])[0]
    assert _aviso_de(_aprobar(operador, corrida["job_id"], entity_id)) == "ALTA_APPROVED"
    filas = _filas_de_alta(almacenes["base"])
    assert len(filas) == 1, filas
    fila = filas[0]
    assert fila["approved_by"], "la aprobación no consta con autor"
    assert "apply_operador" in fila["approved_by"], (
        "el autor no es el de la sesión autenticada"
    )
    assert fila["approved_at"], "la aprobación consta sin momento"
    assert fila["workspace"] and fila["job_id"] == corrida["job_id"], (
        "la aprobación consta sin el ámbito en el que se tomó"
    )


def test_la_aprobacion_entra_en_la_cadena_de_auditoria(operador, corrida):
    """Un acto que decide qué nace en el grafo deja rastro ENCADENADO.

    No se lee un log: se lee la cadena del workspace por su propio verificador,
    que es lo que hace que el rastro no sea reescribible sin que se note.

    ROJA ASÍ: `AssertionError: la aprobación no dejó evento en la cadena`.
    """
    from app.services.v3_apply import ReviewApplyService

    entity_id = sorted(corrida["declaradas"])[0]
    _aprobar(operador, corrida["job_id"], entity_id)
    servicio = ReviewApplyService()
    workspace = corrida["propuestas"][0]["workspace"]
    eventos = servicio.store.audit_events(workspace)
    propios = [e for e in eventos if e.get("event") == "ENTITY_ALTA_APPROVED"]
    assert propios, (
        "la aprobación no dejó evento en la cadena: "
        f"{[e.get('event') for e in eventos]}"
    )
    assert propios[0]["entity_id"] == entity_id
    assert propios[0]["approved_by"], "el evento de auditoría no dice quién"
    # LA CADENA VERIFICA. Un rastro que no encadena no es un rastro.
    with servicio.store.connection() as conexion:
        servicio.store.verify_audit_chain(conexion, workspace)


# ===========================================================================
# 3. LOS SEIS NEGATIVOS DUROS
# ===========================================================================

def test_negativo_aprobar_una_afirmacion_no_aprueba_ninguna_entidad(
    operador, corrida, almacenes
):
    """NEGATIVO 1 — aprobar assertion != aprobar entity.

    Se aprueba una PROPUESTA por el camino de producción y se sella. El plan
    sale con sus afirmaciones y con CERO `CREATE_ENTITY`, porque nadie aprobó
    ningún alta. Si alguien «arreglara» esto emitiendo el alta al ver un
    extremo pendiente, esta prueba se pone roja.

    ROJA ASÍ: `AssertionError: aprobar una propuesta dio de alta entidades:
    ['entity:new:...']`.
    """
    _decidir(corrida["propuesta"], "APPROVE")
    assert _aviso_de(_sellar(operador, corrida["job_id"])).startswith("PLAN_SEALED")
    assert _filas_de_alta(almacenes["base"]) == []
    altas = _altas_en_el_plan(almacenes["base"])
    assert altas == [], f"aprobar una propuesta dio de alta entidades: {altas}"
    # Y EL PLAN NO ESTÁ VACÍO: si lo estuviera, el cero de arriba no diría nada.
    assert _operaciones_del_plan(almacenes["base"]), (
        "el plan salió vacío: el cero de altas no demuestra nada"
    )


def test_negativo_entidad_no_aprobada_no_produce_create_entity(
    operador, corrida, almacenes
):
    """NEGATIVO 2 — entidad DECLARADA y no aprobada -> 0 `CREATE_ENTITY`.

    Es distinto del anterior: aquí la entidad SÍ está en el sobre, con nombre y
    con tipo, lista para crearse. Lo único que falta es la decisión, y eso
    basta para que no se emita nada.

    ROJA ASÍ: `AssertionError: se dio de alta una entidad que nadie aprobó`.
    """
    # LA PROPUESTA QUE SÍ MENCIONA A LA ENTIDAD. Con otra, el cero de altas
    # sería cierto por el motivo equivocado (`ALTA_NOT_REFERENCED`) y esta
    # prueba no mediría la falta de aprobación, que es lo que dice medir.
    _decidir(corrida["propuesta"], "APPROVE")
    assert _aviso_de(_sellar(operador, corrida["job_id"])).startswith("PLAN_SEALED")
    assert corrida["declaradas"], "sin candidata declarada la prueba es vacía"
    # D-9. ESTE `assert` FALTABA, y mi informe de la ronda 1 afirmaba que
    # estaba: sin él, el caso seguía verde con el plan VACÍO y sin sellarse
    # siquiera —miraba el sobre, no el plan—, así que el cero de altas era
    # trivialmente cierto sobre una tubería desconectada.
    assert _operaciones_del_plan(almacenes["base"]), (
        "el plan salió vacío: el cero de altas no demuestra nada"
    )
    assert _altas_en_el_plan(almacenes["base"]) == [], (
        "se dio de alta una entidad que nadie aprobó"
    )


def test_negativo_un_alta_de_otro_workspace_es_rechazada(
    operador, corrida, almacenes, tmp_path
):
    """NEGATIVO 3 — un id que no es de ESTA corrida no se aprueba.

    Cubre de una vez el alta de otro workspace, la de otra corrida y la
    inventada, y a propósito con el MISMO código: darles códigos distintos
    convertiría el formulario en un oráculo que revela si cierta entidad existe
    en otro ámbito.

    El id que se usa está construido con la forma exacta de uno real
    (`entity:new:<16hex>`), para que el rechazo no pueda venir de un filtro de
    sintaxis en vez de la comprobación de pertenencia.

    ROJA ASÍ: `AssertionError: se aprobó un alta que no es de esta corrida`.
    """
    ajeno = "entity:new:ffffffffffffffff"
    assert ajeno not in corrida["declaradas"]
    respuesta = _aprobar(operador, corrida["job_id"], ajeno, tipo="Character")
    assert _aviso_de(respuesta) == "ALTA_DESCONOCIDA"
    assert _filas_de_alta(almacenes["base"]) == [], (
        "se aprobó un alta que no es de esta corrida"
    )


def test_negativo_un_id_inventado_es_rechazado(operador, corrida, almacenes):
    """NEGATIVO 4 — id inventado -> rechazado, y sin escribir nada.

    Se prueba aparte del anterior aunque compartan código de salida: son dos
    entradas distintas del operador y una podría dejar de estar cubierta sin
    que la otra lo notara.

    ROJA ASÍ: `AssertionError: un id inventado dejó fila en el almacén`.
    """
    respuesta = _aprobar(operador, corrida["job_id"], "no-soy-un-id", tipo="Character")
    assert _aviso_de(respuesta) == "ALTA_DESCONOCIDA"
    assert _filas_de_alta(almacenes["base"]) == [], (
        "un id inventado dejó fila en el almacén"
    )
    # Y SIN DECIR CUÁL: el rechazo no publica el id, ni el ámbito, ni la lista.
    assert "no-soy-un-id" not in respuesta.headers.get("location", "")


def test_negativo_repetir_la_aprobacion_no_duplica_la_entidad(
    operador, corrida, almacenes
):
    """NEGATIVO 5 — aprobar dos veces deja UNA fila y UN `CREATE_ENTITY`.

    Las dos mitades importan y se miden las dos: la fila y la operación (dos
    `CREATE_ENTITY` del mismo id abortarían el apply entero con
    `EXEC_TARGET_EXISTS`, o sea cambiarían «falta un nodo» por «no se escribe
    nada»).

    DÓNDE VIVE LA IDEMPOTENCIA, RECTIFICADO: no «en la base». El manejador
    DECIDE con un `SELECT` dentro de la transacción y no llega al `INSERT`
    cuando la fila ya existe; la clave primaria es la red de seguridad frente
    a dos escritores a la vez, no el mecanismo del caso normal. La versión
    anterior de este párrafo describía mal el código que mide.

    Y el acuse DISTINGUE los dos casos: repetir no dice «aprobada».

    ROJA ASÍ: `AssertionError: la segunda aprobación duplicó la fila` o
    `... duplicó el CREATE_ENTITY`.
    """
    entity_id = corrida["entidad"]
    assert _aviso_de(_aprobar(operador, corrida["job_id"], entity_id)) == "ALTA_APPROVED"
    assert _aviso_de(
        _aprobar(operador, corrida["job_id"], entity_id)
    ) == "ALTA_YA_APROBADA", "el segundo acuse finge una decisión nueva"
    filas = _filas_de_alta(almacenes["base"])
    assert len(filas) == 1, f"la segunda aprobación duplicó la fila: {filas}"
    _decidir(corrida["propuesta"], "APPROVE")
    _sellar(operador, corrida["job_id"])
    altas = _altas_en_el_plan(almacenes["base"])
    assert len(altas) == len(set(altas)), f"duplicó el CREATE_ENTITY: {altas}"


def test_negativo_cambiar_la_decision_tras_sellar_invalida_el_plan(
    operador, corrida, almacenes
):
    """NEGATIVO 6 — aprobar un alta DESPUÉS de sellar invalida el plan.

    Es la propiedad que sostiene todo lo demás: no puede existir un plan
    considerado aplicable que no corresponda al conjunto confirmado de
    decisiones. Un plan sellado ANTES de esta aprobación no la contiene, así
    que seguir ofreciéndolo sería ofrecer un plan que ya no es el que se
    decidió. No se edita: se invalida.

    ROJA ASÍ: `AssertionError: el plan sellado sobrevivió a una aprobación
    posterior` — y entonces el apply escribiría un plan sin la entidad que el
    operador acaba de aprobar.
    """
    _decidir(corrida["propuesta"], "APPROVE")
    _sellar(operador, corrida["job_id"])
    vigentes = [f for f in _filas_de_plan(almacenes["base"]) if f["state"] == "sealed"]
    assert len(vigentes) == 1, "no había plan vigente que invalidar"
    _aprobar(operador, corrida["job_id"], corrida["entidad"])
    despues = _filas_de_plan(almacenes["base"])
    assert [f for f in despues if f["state"] == "sealed"] == [], (
        "el plan sellado sobrevivió a una aprobación posterior"
    )
    assert any(f["state"] == "superseded" for f in despues)


# ===========================================================================
# 4. EL RECORRIDO COMPLETO: aprobar el alta SÍ produce el `CREATE_ENTITY`
# ===========================================================================

def test_el_alta_aprobada_produce_su_create_entity_en_el_plan_sellado(
    operador, corrida, almacenes
):
    """EL POSITIVO, que es lo que hace ROJOS DE VERDAD a los seis negativos.

    Sin este caso, todos los negativos se pondrían verdes con una tubería
    desconectada: «cero `CREATE_ENTITY`» es trivialmente cierto si el camino no
    existe. Aquí se recorre entero desde HTTP —revisar, aprobar el alta,
    sellar— y se comprueba que el plan trae el alta, con el tipo y el nombre
    OBSERVADOS y no inventados, y que la operación declara crear algo nuevo.

    ROJA ASÍ: `AssertionError: el alta aprobada no llegó al plan` o
    `... el plan nombra la entidad con algo que nadie observó`.
    """
    entity_id = corrida["entidad"]
    declarada = corrida["declaradas"][entity_id]
    _decidir(corrida["propuesta"], "APPROVE")
    assert _aviso_de(_aprobar(operador, corrida["job_id"], entity_id)) == "ALTA_APPROVED"
    assert _aviso_de(_sellar(operador, corrida["job_id"])).startswith("PLAN_SEALED")

    operaciones = _operaciones_del_plan(almacenes["base"])
    altas = [op for op in operaciones if op["operation_type"] == "CREATE_ENTITY"]
    assert [op["target_entity_id"] for op in altas] == [entity_id], (
        f"el alta aprobada no llegó al plan: {[op['target_entity_id'] for op in altas]}"
    )
    operacion = altas[0]
    assert operacion["expected_state"] == "WOULD_CREATE"
    assert operacion["expected_version"] is None and operacion["expected_hash"] is None
    assert operacion["payload"]["entity_type"] == declarada["entity_type"]
    assert operacion["payload"]["name"] == declarada["name"], (
        "el plan nombra la entidad con algo que nadie observó"
    )
    # LA OPERACIÓN CUELGA DE UNA DECISIÓN REAL QUE NOMBRA A LA ENTIDAD. El
    # contrato congelado exige que toda operación tenga su decisión; atarla a
    # una que no la menciona falsearía la procedencia del nodo.
    documento = json.loads(
        [f for f in _filas_de_plan(almacenes["base"]) if f["state"] == "sealed"][0]["plan_json"]
    )
    decision = next(
        d for d in documento["decisions"] if d["decision_id"] == operacion["decision_id"]
    )
    assert entity_id in (decision["subject_entity_id"], decision["object_entity_id"]), (
        "el alta cuelga de una decisión que no menciona a la entidad"
    )


def test_el_plan_con_alta_sigue_validando_contra_el_contrato_congelado(
    operador, corrida, almacenes
):
    """El documento sellado se valida contra el schema de `main`, sin tocarlo.

    `CREATE_ENTITY` YA estaba en el enum del contrato congelado y el executor
    YA sabía ejecutarlo: este corte no versiona nada. Se comprueba, en vez de
    afirmarlo: si emitir el alta exigiera un campo nuevo, esto se pone rojo con
    el mensaje del validador congelado y el corte se para y se eleva.

    ROJA ASÍ: `ContractV3Error: ...` desde el validador de `contracts/`.
    """
    import sys

    entity_id = corrida["entidad"]
    _decidir(corrida["propuesta"], "APPROVE")
    _aprobar(operador, corrida["job_id"], entity_id)
    _sellar(operador, corrida["job_id"])

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data-engine" / "app"))
    from knowledge_v3.contracts.mutation_plan import GraphMutationPlan

    documento = json.loads(
        [f for f in _filas_de_plan(almacenes["base"]) if f["state"] == "sealed"][0]["plan_json"]
    )
    assert any(
        op["operation_type"] == "CREATE_ENTITY"
        for op in documento["mutation_operations"]
    ), "sin alta en el plan esta validación no mide lo que dice medir"
    GraphMutationPlan.from_dict(documento)


def test_tras_aprobar_la_pantalla_dice_quien_y_cuando_y_no_vuelve_a_ofrecerlo(
    operador, corrida
):
    """La pantalla cuenta el desenlace, y no reofrece lo ya decidido.

    ROJA ASÍ: `AssertionError: la pantalla vuelve a ofrecer un alta ya
    aprobada` o `... no dice quién la aprobó`.
    """
    entity_id = sorted(corrida["declaradas"])[0]
    _aprobar(operador, corrida["job_id"], entity_id)
    html = _pantalla_de_altas(operador, corrida["job_id"]).text
    tarjeta = _tarjetas(html)[entity_id]
    assert tarjeta["aprobada"] == "true"
    assert not tarjeta["form"], "la pantalla vuelve a ofrecer un alta ya aprobada"
    assert "apply_operador" in tarjeta["texto"], "no dice quién la aprobó"


# ===========================================================================
# 5. HIGIENE DE SUPERFICIE PÚBLICA
# ===========================================================================

def test_la_pantalla_de_altas_no_publica_nada_interno(operador, corrida):
    """Repositorio público: ni rutas, ni `plan_id`, ni workspace, ni trazas.

    El `entity_id` SÍ viaja, y es la única identidad interna que lo hace: es lo
    que el formulario devuelve para decir CUÁL se aprueba, igual que el CLI
    aprueba por id. Aprobar por posición sería aprobar lo que la pantalla
    ordenó, no lo que la persona miró.

    ROJA ASÍ: `AssertionError: la pantalla publica <cosa interna>`.
    """
    html = _pantalla_de_altas(operador, corrida["job_id"]).text
    prohibidos = ["plan:", "snapshot:", "/home/", "Traceback",
                  "S9K_V3_REVIEW", "sqlite3", ".sqlite3"]
    # D-7. EL WORKSPACE FALTABA de esta lista, y el docstring lo prometía: es
    # identidad del servidor, el operador no lo teclea nunca y el manejador lo
    # resuelve él solo desde la corrida. Prometerlo y no comprobarlo es la
    # clase de higiene que se lee como cubierta sin estarlo.
    prohibidos.append(str(corrida["propuestas"][0]["workspace"]))
    for prohibido in prohibidos:
        assert prohibido not in html, f"la pantalla publica {prohibido!r}"


def test_la_capacidad_esta_declarada_y_montada_bajo_operaciones(real_app):
    """Lo declarado está montado y lo montado está declarado. Los dos lados.

    Una escritura bajo `/panel/*` sin entrada en `WRITE_CAPABILITIES` es un
    defecto que la enumeración del chasis ve; una entrada sin ruta montada es
    una promesa que nadie cumple.

    ROJA ASÍ: `AssertionError: hay escrituras sin declarar en el hueco B` o
    `AssertionError: la capacidad de alta no está montada`.
    """
    from app.chassis import (
        FEATURE_SLOTS, capabilities_for_slot, iter_mounted_routes, route_path,
        undeclared_writes, write_methods,
    )

    slot = next(s for s in FEATURE_SLOTS if s.key == "B")
    capacidad = next(
        c for c in capabilities_for_slot("B") if c.name == "alta_de_entidad"
    )
    assert capacidad.role == "admin" and capacidad.audited
    montadas = {
        route_path(r) for r in iter_mounted_routes(real_app) if write_methods(r)
    }
    assert capacidad.path in montadas, "la capacidad de alta no está montada"
    assert undeclared_writes(real_app, slot) == [], (
        "hay escrituras sin declarar en el hueco B"
    )


# ===========================================================================
# RONDA 2 · lo que el revisor derrotó, y el arnés que lo impide
# ===========================================================================
#
# Los bloques de abajo existen porque un revisor independiente ROMPIÓ lo de
# arriba con mutaciones VIVAS y las 22 pruebas siguieron verdes. Cada uno
# nombra la mutación que lo derrotó, para que nadie tenga que reconstruirla.


def _reescribir_el_sobre(directorio: Path, mutador) -> None:
    """Aplica `mutador(paquete)` a CADA paquete del almacén de propuestas.

    POR QUÉ SE TOCA EL SOBRE Y NO SE FABRICA UNA PANTALLA
    -----------------------------------------------------
    El sobre es la ENTRADA del producto: lo escribe la corrida y lo lee el
    visor. Cambiarlo pone al producto delante de un caso que el corpus de
    ejemplo no produce (varias altas, material de otra partida) sin tocar ni
    una línea del camino que se está midiendo. La alternativa —construir a
    mano el diccionario que la plantilla recibe— mediría la plantilla y no el
    recorrido, que es justo lo que este módulo no puede permitirse.

    El `proposal_hash` no se toca: el cargador lo RECALCULA en su frontera de
    confianza, así que un paquete reescrito entra por el camino normal.
    """
    ficheros = sorted(directorio.glob("*.json"))
    assert ficheros, "no hay paquetes que reescribir: el arnés no ingirió nada"
    for ruta in ficheros:
        paquete = json.loads(ruta.read_text(encoding="utf-8"))
        mutador(paquete)
        ruta.write_text(
            json.dumps(paquete, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _declarar_altas_extra(paquete: dict, cuantas: int) -> list:
    """Añade altas DECLARADAS al sobre. Devuelve sus ids, en orden.

    Son altas que ninguna propuesta menciona: al sellar producirán
    `ALTA_NOT_REFERENCED`, que es exactamente el motivo de omisión que el
    operador no veía. Sirven para dos cosas a la vez — tener VARIAS altas en
    pantalla (sin eso, «no hay aprobar todas» se medía sobre `1 == 1`) y tener
    una omisión real que el acuse tiene que decir.
    """
    contexto = paquete.get("plan_context")
    assert isinstance(contexto, dict), "el paquete no trae contexto de plan"
    altas = contexto.setdefault(CLAVE_SOBRE, {})
    creadas = []
    for indice in range(cuantas):
        entity_id = "entity:new:extra%d%s" % (indice, "0" * 10)
        altas[entity_id] = {
            "entity_id": entity_id,
            "entity_type": "Character",
            "name": "Figurante %d" % indice,
            "aliases": [],
            "reason_codes": ["NO_CANDIDATE", "AUSENTE_DEL_GRAFO"],
            "mention_ids": [],
            "confidence": 0.9,
        }
        creadas.append(entity_id)
    return creadas


@pytest.fixture
def corrida_con_varias_altas(corrida, almacenes):
    """La misma corrida, con TRES altas declaradas en vez de una.

    El corpus de ejemplo declara UNA sola, y con una sola varias afirmaciones
    de este módulo se cumplían por aritmética (`1 == 1`) sin distinguir el
    singular del plural. Aquí hay un alta real —la que el plan sí puede
    crear— y dos que ninguna propuesta menciona.
    """
    extra = []

    def _mutar(paquete):
        extra.extend(_declarar_altas_extra(paquete, 2))

    _reescribir_el_sobre(almacenes["propuestas"], _mutar)
    propuestas = _propuestas(almacenes["propuestas"])
    declaradas = _altas_del_sobre(propuestas, corrida["job_id"])
    assert len(declaradas) == 3, (
        "el sobre no quedó con tres altas: %s" % sorted(declaradas))
    return {**corrida, "propuestas": propuestas, "declaradas": declaradas,
            "extra": sorted(set(extra))}


# ---------------------------------------------------------------------------
# D-1 · LA GUARDA DE ROL, MEDIDA POR COMPORTAMIENTO Y SIN SOBREDETERMINAR
# ---------------------------------------------------------------------------

@pytest.fixture
def ambito_abierto(real_app):
    """Sustituye el ámbito de la petición por uno SIN restricción.

    Existe para DESACTIVAR la segunda puerta. El testigo de rol de la ronda 1
    seguía verde con la guarda retirada porque al `reviewer` lo paraba además
    la resolución de la corrida con ámbito: dos puertas, una sola prueba, y
    ninguna de las dos aislada. Con el ámbito abierto, lo único que puede
    parar a un rol insuficiente es la guarda del hueco.
    """
    from app.authz.dependencies import get_visibility_scope
    from app.authz.scope import UNRESTRICTED

    real_app.dependency_overrides[get_visibility_scope] = lambda: UNRESTRICTED
    yield
    real_app.dependency_overrides.pop(get_visibility_scope, None)


def test_con_el_ambito_abierto_el_admin_SI_aprueba(
    operador, corrida, almacenes, ambito_abierto
):
    """CONTROL POSITIVO del aislamiento de D-1. Sin esto, el rojo no vale.

    Si con el ámbito abierto el admin tampoco pudiera aprobar, el caso de
    abajo estaría midiendo una tercera cosa y su verde no diría nada sobre el
    rol. Esto fija que la única diferencia entre los dos casos es QUIÉN pide.

    ROJA ASÍ: `AssertionError: con el ámbito abierto el admin tampoco aprueba`.
    """
    entity_id = sorted(corrida["declaradas"])[0]
    assert _aviso_de(_aprobar(operador, corrida["job_id"], entity_id)) == "ALTA_APPROVED", (
        "con el ámbito abierto el admin tampoco aprueba: este arnés no aísla "
        "el rol, mide otra cosa"
    )
    assert len(_filas_de_alta(almacenes["base"])) == 1


def test_un_rol_insuficiente_no_aprueba_AUNQUE_la_corrida_le_sea_visible(
    revisor, corrida, almacenes, ambito_abierto
):
    """LA GUARDA DE ROL, AISLADA. Lo que la ronda 1 no medía.

    QUÉ DERROTÓ AL TESTIGO ANTERIOR, medido por el revisor: envolvió la
    dependencia en un wrapper que devolvía `html_role_guard("reviewer")`
    conservando el texto `slot_guard(SLOT)` en el árbol. La prueba estructural
    exigía dos subcadenas del AST desparseado y no vio nada: 22 passed. Y la
    degradación efectiva NO era «a reviewer»: `html_role_guard` es NO-OP
    cuando `S9K_AUTH_ENABLED` está ausente, así que era A CUALQUIERA.

    Parsear estructura no sustituye a ejercer comportamiento cuando lo que se
    vigila es una guarda. Esto ejerce el POST con un rol insuficiente y un
    ámbito que NO le esconde la corrida, y comprueba la TABLA.

    ROJA ASÍ: `AssertionError: un rol insuficiente aprobó un alta con la
    corrida visible` — y se pone roja con el wrapper del revisor puesto,
    porque no mira el árbol sino lo que la base acaba teniendo.
    """
    entity_id = sorted(corrida["declaradas"])[0]
    respuesta = _aprobar(revisor, corrida["job_id"], entity_id)
    assert respuesta.status_code in (302, 303, 403), respuesta.status_code
    assert _filas_de_alta(almacenes["base"]) == [], (
        "un rol insuficiente aprobó un alta con la corrida visible: la guarda "
        "del hueco no está parando nada"
    )


# ---------------------------------------------------------------------------
# D-0 · EL ACUSE DEL SELLADO NO PUEDE CALLAR LO QUE NO LLEGÓ AL PLAN
# ---------------------------------------------------------------------------

def test_el_acuse_dice_las_altas_aprobadas_que_el_plan_deja_fuera(
    operador, corrida_con_varias_altas, almacenes
):
    """FALSA CONFIRMACIÓN, CERRADA. Hallazgo del revisor, medido en vivo.

    Aprobó seis altas, dos llegaron al plan, el acuse dijo
    `PLAN_SEALED_SIN_PROYECCION` y no mencionó las otras cuatro. `sellar()`
    calculaba `altas_omitidas` y lo devolvía; NO TENÍA NI UN CONSUMIDOR en
    todo `viewer/`. Los `ALTA_CODES` sólo iban a `log.warning`.

    Aquí se aprueban tres altas —una que el plan sí puede crear y dos que
    ninguna propuesta menciona— y se exige que el acuse lo DIGA.

    ROJA ASÍ: `AssertionError: el acuse calla las altas que no llegaron al
    plan: PLAN_SEALED_SIN_PROYECCION`.
    """
    corrida = corrida_con_varias_altas
    _decidir(corrida["propuesta"], "APPROVE")
    for entity_id in sorted(corrida["declaradas"]):
        assert _aviso_de(_aprobar(operador, corrida["job_id"], entity_id)) == "ALTA_APPROVED"
    aviso = _aviso_de(_sellar(operador, corrida["job_id"]))
    assert aviso in ("PLAN_SEALED_SIN_ALTAS", "PLAN_SEALED_INCOMPLETO"), (
        "el acuse calla las altas que no llegaron al plan: %s" % aviso
    )
    # Y NO ES UN ACUSE HUECO: el plan de verdad dejó fuera a las dos extra.
    en_el_plan = _altas_en_el_plan(almacenes["base"])
    assert corrida["entidad"] in en_el_plan
    for ajena in corrida["extra"]:
        assert ajena not in en_el_plan, (
            "el plan creó una entidad que ninguna afirmación menciona: este "
            "caso ya no mide una omisión"
        )


def test_la_pantalla_dice_POR_QUE_no_se_anadio_cada_alta_omitida(
    operador, corrida_con_varias_altas, almacenes
):
    """El motivo llega a la persona, traducido, y NO como código del motor.

    El acuse dice que falta algo; esto comprueba que la pantalla dice CUÁL y
    POR QUÉ, con la frase del visor y sin publicar el código interno.

    ROJA ASÍ: `AssertionError: la pantalla no dice que <id> se quedó fuera`.
    """
    corrida = corrida_con_varias_altas
    _decidir(corrida["propuesta"], "APPROVE")
    for entity_id in sorted(corrida["declaradas"]):
        _aprobar(operador, corrida["job_id"], entity_id)
    _sellar(operador, corrida["job_id"])

    html = _pantalla_de_altas(operador, corrida["job_id"]).text
    tarjetas = _tarjetas(html)
    for ajena in corrida["extra"]:
        assert 'data-alta-omitida="true"' in tarjetas[ajena]["texto"], (
            "la pantalla no dice que %s se quedó fuera" % ajena
        )
    assert 'data-alta-omitida="true"' not in tarjetas[corrida["entidad"]]["texto"], (
        "la pantalla declara omitida una entidad que SÍ está en el plan"
    )
    # EL CÓDIGO DEL MOTOR NO SE PUBLICA: se traduce.
    for codigo in ("ALTA_NOT_REFERENCED", "ALTA_NOT_DECLARED_IN_RUN",
                   "ALTA_WITHOUT_TYPE"):
        assert codigo not in html, (
            "la pantalla publica el código interno %s" % codigo)


def test_un_motivo_de_omision_desconocido_se_NOMBRA_y_no_se_descarta():
    """AUSENCIA != CERO en la tabla de traducción.

    Un código que este despliegue no sepa interpretar no puede desaparecer de
    la pantalla: eso reintroduciría la omisión muda por otra puerta.

    ROJA ASÍ: `AssertionError: un motivo desconocido se traduce a nada`.
    """
    from app.services.v3_apply import MOTIVOS_DE_ALTA_OMITIDA, motivo_de_omision

    frase = motivo_de_omision("ALTA_DE_UN_CORTE_FUTURO")
    assert frase and "no sabe interpretar" in frase, (
        "un motivo desconocido se traduce a nada: %r" % frase
    )
    assert set(MOTIVOS_DE_ALTA_OMITIDA) == {
        "ALTA_NOT_DECLARED_IN_RUN", "ALTA_NOT_REFERENCED", "ALTA_WITHOUT_TYPE",
    }, "la tabla del visor y los ALTA_CODES del motor han dejado de coincidir"


# ---------------------------------------------------------------------------
# D-2 · EL FILTRO DE ÁMBITO, CON CONTROL NEGATIVO PROPIO
# ---------------------------------------------------------------------------

def test_negativo_el_ambito_recorta_las_altas_ANTES_de_componerlas(
    corrida, almacenes
):
    """SEGURIDAD: «lo que la política oculta no se envía», GUARDADO.

    Quitando `permitido.allows(p)` de `v3_apply.altas`, las 22 de la ronda 1
    seguían verdes: ni el caso de otra corrida lo veía (lo para
    `_corrida_visible`, otra puerta) ni el de otro workspace (muere por
    pertenencia). La propiedad era cierta por lectura y no estaba vigilada.

    Este caso mata POR ÁMBITO y por nada más: mismo servicio, misma corrida,
    mismo workspace, mismas propuestas. Lo único que cambia es la partida
    activa del lector, y las propuestas llevan la suya declarada.

    ROJA ASÍ: `AssertionError: el ámbito no recorta nada: N altas visibles
    desde una partida ajena`.
    """
    from app.authz.context import build_viewer_context
    from app.authz.scope import UNRESTRICTED, VisibilityScope
    from app.services.v3_apply import ReviewApplyService

    def _marcar(paquete):
        for item in paquete.get("items", []):
            item["partida_id"] = "partida:alfa"

    _reescribir_el_sobre(almacenes["propuestas"], _marcar)
    workspace = _propuestas(almacenes["propuestas"])[0]["workspace"]
    servicio = ReviewApplyService()

    # CONTROL POSITIVO: sin restricción, el material está y se ve.
    visibles, declarado = servicio.altas(
        workspace=workspace, job_id=corrida["job_id"], scope=UNRESTRICTED)
    assert declarado and visibles, (
        "sin restricción tampoco hay altas: este caso no mediría el ámbito "
        "sino un almacén vacío"
    )

    # Y AHORA EL MISMO SERVICIO, con un lector de OTRA partida.
    ajeno = VisibilityScope(build_viewer_context(
        role="viewer", auth_enabled=True, default_workspace=workspace,
        active_partida="partida:beta",
    ))
    recortadas, _ = servicio.altas(
        workspace=workspace, job_id=corrida["job_id"], scope=ajeno)
    assert recortadas == (), (
        "el ámbito no recorta nada: %d altas visibles desde una partida ajena"
        % len(recortadas)
    )


# ---------------------------------------------------------------------------
# D-3 · «NO HAY APROBAR TODAS», SIN AUTORREFERENCIA Y EN PLURAL
# ---------------------------------------------------------------------------

def _formularios_al_alta(html: str) -> list:
    """TODO formulario que apunte al alta, lleve o no la marca del producto.

    La versión de la ronda 1 enumeraba `data-role="form-alta"`, que es
    justamente la marca que un «APROBAR TODAS» no llevaría: el revisor añadió
    uno real a la plantilla y pasaron las 22. Aquí el criterio es el DESTINO
    —el `action` del formulario—, que un botón masivo no puede evitar si de
    verdad quiere aprobar por esa ruta.
    """
    return [
        bloque for bloque in re.findall(r"<form\b.*?</form>", html, re.S)
        if "/panel/operations/altas" in bloque
    ]


def test_no_existe_NINGUNA_forma_de_aprobar_varias_altas_de_un_golpe(
    operador, corrida_con_varias_altas
):
    """La frontera, en plural y sin depender de una marca del propio producto.

    TRES comprobaciones, y cada una mata un «aprobar todas» distinto:
      1. hay tantos formularios al alta como altas pendientes — uno extra
         sobra;
      2. cada uno manda EXACTAMENTE UNA entidad, y no vacía — un masivo o no
         manda ninguna o manda varias;
      3. los ids mandados son los de las altas, sin repetir — nadie cuela un
         comodín.

    ROJA ASÍ: `AssertionError: hay 4 formularios al alta para 3 pendientes` o
    `AssertionError: un formulario al alta manda 0 entidades`.
    """
    corrida = corrida_con_varias_altas
    html = _pantalla_de_altas(operador, corrida["job_id"]).text
    formularios = _formularios_al_alta(html)
    pendientes = sorted(corrida["declaradas"])
    assert len(pendientes) >= 3, (
        "el corpus volvió a declarar menos de tres altas: en singular este "
        "caso se cumple por aritmética y no mide el plural"
    )
    assert len(formularios) == len(pendientes), (
        "hay %d formularios al alta para %d pendientes"
        % (len(formularios), len(pendientes))
    )
    mandados = []
    for formulario in formularios:
        entidades = re.findall(r'name="entidad"[^>]*value="([^"]*)"', formulario)
        assert len(entidades) == 1, (
            "un formulario al alta manda %d entidades: %s"
            % (len(entidades), entidades)
        )
        assert entidades[0].strip(), "un formulario al alta manda una entidad vacía"
        mandados.append(entidades[0])
    assert sorted(mandados) == pendientes, (
        "los formularios no mandan las altas pendientes: %s" % sorted(mandados)
    )


# ---------------------------------------------------------------------------
# D-6 · LA FUENTE DE LA ATRIBUCIÓN, NO SÓLO SU VALOR
# ---------------------------------------------------------------------------

def test_la_atribucion_sale_de_la_SESION_y_el_cliente_no_puede_ponerla(
    operador, corrida, almacenes
):
    """Lo que el docstring promete, GUARDADO.

    El revisor hizo que el autor se tomara de `?autor=` y pasó todo, dejando
    `approved_by=['FIRMA_FALSIFICADA']`. El valor estaba comprobado; la FUENTE
    no. Aquí la petición lleva el nombre falsificado por varias puertas —query
    y formulario, con cuatro nombres plausibles— y se exige que la tabla
    conserve al usuario de la sesión.

    ROJA ASÍ: `AssertionError: la atribución la escribió el cliente:
    'panel:FIRMA_FALSIFICADA'`.
    """
    entity_id = sorted(corrida["declaradas"])[0]
    falsa = "FIRMA_FALSIFICADA"
    respuesta = operador.post(
        "/panel/operations/altas?autor=%s&approved_by=%s" % (falsa, falsa),
        data={
            "trabajo": corrida["job_id"], "entidad": entity_id, "tipo": "",
            "csrf_token": _csrf(operador),
            "autor": falsa, "approved_by": falsa, "revisor": falsa,
            "quien": falsa,
        },
    )
    assert _aviso_de(respuesta) == "ALTA_APPROVED"
    filas = _filas_de_alta(almacenes["base"])
    assert len(filas) == 1, filas
    autor = filas[0]["approved_by"]
    assert falsa not in autor, (
        "la atribución la escribió el cliente: %r" % autor)
    assert "apply_operador" in autor, (
        "la atribución no es la de la sesión autenticada: %r" % autor
    )


# ---------------------------------------------------------------------------
# D-4 · EL RECORRIDO ENTERO, CONTRA UN GRAFO DE VERDAD
# ---------------------------------------------------------------------------

@neo4j_real
def test_E2E_aprobar_el_alta_hace_que_el_destino_deje_de_dar_404(
    real_app, paneles_on, resultado_on, cola, operador, almacenes, grafo,
    visor_sobre_el_grafo, monkeypatch
):
    """LA PROPIEDAD ENTERA, EJERCIDA CONTRA INFRA REAL.

    Mi informe de la ronda 1 dijo que esto «no se puede medir aquí». Era
    FALSO: el arnés de Neo4j efímero ya existía en este mismo repositorio
    desde cortes anteriores, y el revisor lo levantó y midió el recorrido
    completo por esta superficie web. Se añade aquí como testigo propio.

    Lo que se recorre, todo por HTTP y sin tocar el grafo a mano: ingesta ->
    aprobar la propuesta -> **aprobar el alta** -> sellar -> aplicar -> seguir
    el enlace que el panel publica.

    Y lo que se comprueba, que es lo que el corte anterior no podía:
      * el plan sellado trae `CREATE_ENTITY`;
      * tras el apply hay nodos `:Entity` CON `entity_id` y `workspace`;
      * `provider.workspaces()` incluye el workspace (antes `[]`);
      * el destino responde **200** (antes 404).

    ROJA ASÍ: `AssertionError: el apply no creó ninguna :Entity` o
    `AssertionError: el destino sigue negando el apply (404)`.
    """
    from test_panel_apply_desde_la_ui import (
        _bloque_plan, _camino, _panel, _primer_enlace,
    )

    job_id = _ingerir(operador, cola, monkeypatch)
    propuestas = _propuestas(almacenes["propuestas"])
    declaradas = _altas_del_sobre(propuestas, job_id)
    assert declaradas, "la corrida no declaró ninguna alta: no hay nada que medir"
    entity_id, propuesta = None, None
    for candidato in sorted(declaradas):
        elegida = _propuesta_que_menciona(propuestas, job_id, candidato)
        if elegida is not None:
            entity_id, propuesta = candidato, elegida
            break
    assert propuesta is not None, "ninguna alta está mencionada por una propuesta"

    _decidir(propuesta, "APPROVE")
    assert _aviso_de(_aprobar(operador, job_id, entity_id)) == "ALTA_APPROVED"
    assert _aviso_de(_sellar(operador, job_id)).startswith("PLAN_SEALED")
    assert entity_id in _altas_en_el_plan(almacenes["base"]), (
        "el plan sellado no trae el CREATE_ENTITY del alta aprobada"
    )
    assert _aviso_de(_aplicar(operador, job_id)) == "PLAN_APPLIED"

    # 1. EL NODO ESTÁ, y con las dos propiedades de las que depende el ámbito.
    with grafo.session() as sesion:
        entidades = sesion.run(
            "MATCH (e:Entity) RETURN e.entity_id AS id, e.workspace AS ws"
        ).data()
    assert entidades, "el apply no creó ninguna :Entity"
    assert all(f["id"] and f["ws"] for f in entidades), (
        "hay :Entity sin entity_id o sin workspace: %s" % entidades
    )
    assert entity_id in [f["id"] for f in entidades], (
        "la entidad aprobada no está en el grafo: %s" % entidades
    )

    # 2. EL ÁMBITO EXISTE PARA EL LECTOR — lo que antes daba [].
    ambitos = list(visor_sobre_el_grafo.workspaces() or ())
    assert "ws-cofradia" in ambitos, (
        "el workspace del apply sigue sin aparecer en el ámbito: %s" % ambitos
    )

    # 3. Y EL ENLACE QUE EL PANEL PUBLICA YA NO PROMETE UN 404.
    destino = _primer_enlace(_camino(_bloque_plan(_panel(operador, job_id))))
    pantalla = operador.get(destino)
    assert pantalla.status_code == 200, (
        "el destino sigue negando el apply (%s): el recorrido no llega hasta "
        "el final" % pantalla.status_code
    )
