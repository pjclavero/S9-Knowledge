# -*- coding: utf-8 -*-
"""Slice 2 · APPLY DESDE LA UI — de aprobar a conocimiento materializado.

EL DEFECTO QUE ESTE MÓDULO FIJA
-------------------------------
Medido sobre `main` antes de este corte:

    apply_v3(...)            completa, con `compute_apply_id` dentro
    llamadores desde viewer/ 0

Una función completa sin llamador en el recorrido real del operador es
capacidad NO USABLE. Desde el producto, el operador aprobaba una propuesta, la
pantalla se lo confirmaba, y el grafo no cambiaba nunca. Y no había ningún
artefacto que aplicar: el plan de la corrida vive en memoria y muere con el
job.

POR QUÉ ESTAS PRUEBAS NO SE PUEDEN PONER VERDES POR BASURA ANTERIOR
--------------------------------------------------------------------
Todo el estado es de `tmp_path` y se comprueba VACÍO antes de empezar: el
almacén de propuestas, el de decisiones, la cola de trabajos y la base de auth.
Lo que se afirma después no son recuentos --«hay algo escrito» se pondría verde
con restos-- sino IDENTIDADES DURABLES: el `assertion_id` que aparece en Neo4j
es exactamente el que el plan sellado declaró, comparado por `assertion_id` y
nunca por `elementId`, que se regenera al restaurar un dump.

Y el recorrido se ejerce DESDE EL PANEL: formulario real, CSRF real, cola real,
worker real y writer real. Una prueba de apply que llamara al núcleo
directamente no diría nada sobre si la UI lo hace.

QUÉ NECESITA PARA CORRER DE VERDAD
----------------------------------
Los casos marcados `neo4j_real` se SALTAN sin `S9K_WRITER_NEO4J_REAL=1`. Un
`skipped` no es un verde: mientras no se declare la variable, la afirmación
«el conocimiento queda materializado» NO se ha comprobado, y el nombre del caso
lo dice. Los demás casos --frontera, autorización, CSRF, idempotencia de
estado, supersesión-- corren siempre y sin grafo, porque ninguno de ellos
necesita escribir para ser cierto.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import jobs_client
from app.chassis import FEATURE_SLOTS

SLOT_B = next(s for s in FEATURE_SLOTS if s.key == "B")
FLAG_B = "S9K_PANEL_B_ENABLED"
FLAG_C = "S9K_PANEL_C_ENABLED"
PASSWORD = "Contrasena-De-Prueba-1"

REPO = Path(__file__).resolve().parents[2]
EJEMPLOS = REPO / "examples" / "ingesta-v3"

#: Prefijo PROPIO de los contenedores de este módulo. Se limpian de uno en uno
#: por nombre: un `prune` global se llevaría por delante material de otro
#: carril que esté corriendo a la vez.
PREFIJO_CONTENEDOR = "s9k-carrilb-apply"

WRITER_REAL = os.environ.get("S9K_WRITER_NEO4J_REAL") == "1"
neo4j_real = pytest.mark.skipif(
    not WRITER_REAL,
    reason="sin S9K_WRITER_NEO4J_REAL=1 no hay grafo: el apply no se comprueba",
)


# ---------------------------------------------------------------------------
# Arnés: app real, auth real, cola real, almacenes reales y VACÍOS
# ---------------------------------------------------------------------------

@pytest.fixture
def real_app():
    from app.main import app
    return app


@pytest.fixture(autouse=True)
def _entorno_limpio():
    from app.auth.config import get_auth_settings
    from app.config import get_settings
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    yield
    for var in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_JOBS_DB",
                "S9K_INGEST_SOURCES_DIR", "S9K_ALLOW_REAL_INGEST",
                "S9K_WRITER_WORKSPACE", "S9K_NEO4J_URI", "S9K_NEO4J_USER",
                "S9K_NEO4J_PASSWORD", "S9K_GRAPH_PROVIDER", FLAG_B, FLAG_C):
        os.environ.pop(var, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _salud_aislada(tmp_path, monkeypatch):
    monkeypatch.setenv("S9K_HEALTH_REPORT_PATH", str(tmp_path / "health" / "last.json"))


# GRAFO DE MENTIRA PARA LOS CASOS QUE NO TRAEN GRAFO.
#
# Desde el Corte 5 la ingesta del panel abre una conexión de sólo lectura y
# falla cerrado sin ella. Los casos de frontera, autorización, CSRF y estado de
# este módulo no vienen a medir eso y corren sin Docker.
#
# CEDE EL PASO: en cuanto la fixture `grafo` declara una credencial, el doble
# se aparta y el abridor REAL toma el control. La decisión se toma cuando el
# manejador llama, no cuando pytest monta las fixtures, así que el orden entre
# esta fixture y `grafo` no puede cambiarla en silencio.
@pytest.fixture(autouse=True)
def _grafo_de_mentira(monkeypatch):
    import grafo_doble

    return grafo_doble.instalar(monkeypatch)


@pytest.fixture
def almacenes(tmp_path, monkeypatch) -> dict:
    """Propuestas y decisiones, aislados y VACÍOS. El mismo resolvedor único."""
    propuestas = tmp_path / "reviews-v3" / "proposals"
    base = tmp_path / "reviews-v3" / "review.sqlite3"
    monkeypatch.setenv("S9K_V3_REVIEW_PROPOSALS_DIR", str(propuestas))
    monkeypatch.setenv("S9K_V3_REVIEW_DECISIONS_PATH",
                       str(tmp_path / "reviews-v3" / "decisions.jsonl"))
    monkeypatch.setenv("S9K_V3_REVIEW_DATABASE_PATH", str(base))
    assert not propuestas.exists(), "el almacén tiene que empezar vacío"
    return {"propuestas": propuestas, "base": base}


@pytest.fixture
def paneles_on():
    os.environ[FLAG_B] = "true"
    os.environ[FLAG_C] = "true"
    yield
    os.environ.pop(FLAG_B, None)
    os.environ.pop(FLAG_C, None)


@pytest.fixture
def cola(tmp_path):
    from app.config import get_settings

    db = tmp_path / "jobs.db"
    os.environ["S9K_JOBS_DB"] = str(db)
    get_settings.cache_clear()
    store = jobs_client._load_job_store()
    assert store is not None, "sin job_store no hay nada que probar"
    store.init_db(str(db))
    yield db
    get_settings.cache_clear()


@pytest.fixture
def auth_on(tmp_path):
    from app.auth.config import get_auth_settings
    from app.auth import db as auth_db_mod

    db_path = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    get_auth_settings.cache_clear()
    auth_db_mod.ensure_migrated(db_path)
    return db_path


def _cookie(db_path: Path, username: str, role: str) -> str:
    from app.auth import db as auth_db_mod
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db_mod.get_conn(db_path) as conn:
        user = auth_db_mod.create_user(
            conn, username=username, display_name=username.title(),
            password_hash=hash_password(PASSWORD), role=role,
        )
        auth_db_mod.update_user(conn, user.id, must_change_password=False)
        user = auth_db_mod.get_user_by_id(conn, user.id)
        token, _ = create_session(conn, user)
    return token


def _cliente(app, cookie: str) -> TestClient:
    from app.auth.config import get_auth_settings
    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, cookie)
    c.headers.update({"accept": "text/html"})
    return c


@pytest.fixture
def operador(real_app, auth_on):
    """Un ADMIN autenticado de verdad: la única puerta de este hueco."""
    return _cliente(real_app, _cookie(auth_on, "apply_operador", "admin"))


@pytest.fixture
def revisor(real_app, auth_on):
    """Un REVIEWER autenticado. Puede revisar; NO puede aplicar."""
    return _cliente(real_app, _cookie(auth_on, "apply_revisor", "reviewer"))


def _csrf(cliente: TestClient) -> str:
    """Un token CSRF VÁLIDO para la sesión, sacado de `base.html`."""
    r = cliente.get("/")
    assert r.status_code == 200, r.status_code
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    assert m, "base.html no publicó ningún token CSRF"
    return m.group(1)


def _opciones(html: str) -> list:
    bloque = re.search(r'data-role="selector-fuente".*?</select>', html, re.S)
    assert bloque, "no hay selector de fuente en la pantalla"
    return re.findall(r'<option value="([^"]+)"', bloque.group(0))


# ---------------------------------------------------------------------------
# El recorrido del operador, por partes
# ---------------------------------------------------------------------------

def _ingerir(operador, cola, monkeypatch) -> str:
    """Formulario real -> cola real -> worker real. Devuelve el `job_id`."""
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(EJEMPLOS))
    pantalla = operador.get(SLOT_B.prefix)
    assert pantalla.status_code == 200, pantalla.status_code
    opciones = _opciones(pantalla.text)
    assert opciones, "no se ofrece ninguna fuente que elegir"
    envio = operador.post(
        "/panel/operations/ingestas",
        data={"fuente": opciones[0], "csrf_token": _csrf(operador)},
    )
    assert envio.status_code == 303, envio.text[:300]
    store = jobs_client._load_job_store()
    pendientes = store.list_jobs(status="pending", db_path=str(cola))
    assert len(pendientes) == 1, pendientes
    job_id = pendientes[0]["job_id"]

    from jobs import worker
    assert worker.run("worker-apply", once=True, limit=1, db_path=str(cola)) == 1
    final = store.get_job(job_id, db_path=str(cola))
    assert final["status"] == "complete", final.get("error_message")
    return job_id


def _propuestas(directorio: Path) -> list:
    """Las propuestas del almacén, leídas por el camino del producto."""
    from app.services.v3_review import load_proposals
    return load_proposals(directorio)


def _aplicable(propuestas: list, job_id: str):
    """La primera propuesta de la corrida que SÍ produce una operación.

    No vale cualquiera: el corpus de ejemplo deja dos `ABSTAIN` sin predicado,
    y aprobar una de ésas es legítimo y no escribe nada. Se elige por la misma
    condición que el sellado aplica, para que la prueba insignia mida el camino
    feliz y no un camino de exclusión disfrazado.
    """
    for propuesta in propuestas:
        if job_id not in (propuesta.get("package_runs") or ()):
            continue
        cuerpo = propuesta.get("proposal") or {}
        resolucion = propuesta.get("resolution") or {}
        if (
            cuerpo.get("predicate") not in (None, "", "UNKNOWN")
            and cuerpo.get("direction") not in (None, "", "UNKNOWN")
            and resolucion.get("subject") not in (None, "", "not_available")
            and resolucion.get("object") not in (None, "", "not_available")
        ):
            return propuesta
    return None


def _decidir(propuesta: dict, veredicto: str, *, reviewer: str = "apply_operador") -> str:
    """Una decisión humana por la MISMA autoridad que usa `/panel/review`."""
    from app.services.v3_review import ReviewService

    registro = ReviewService().record(
        proposal_id=propuesta["proposal_id"],
        workspace=propuesta["workspace"],
        reviewer=reviewer,
        human_decision=veredicto,
        request_id=f"req-{uuid.uuid4().hex[:12]}",
        rationale="prueba de apply desde la UI",
    )
    return registro["decision_id"] if isinstance(registro, dict) else ""


def _panel(operador, job_id: str, aviso: str | None = None):
    consulta = f"?solicitado={job_id}" + (f"&aviso={aviso}" if aviso else "")
    r = operador.get(f"{SLOT_B.prefix}{consulta}")
    assert r.status_code == 200, r.status_code
    return r.text


def _bloque_plan(html: str) -> dict:
    """Lo que el PRODUCTO pinta del plan, enumerado. No hay navegador aquí.

    El contrato de navegador no corre en esta máquina (sin Chromium), así que
    la afirmación «la pantalla ofrece/no ofrece la acción» se hace enumerando
    el marcado que el producto genera. Es una comprobación distinta de la del
    navegador y se declara como tal; lo que no es, es un `skipped` que se lee
    como verde.
    """
    seccion = re.search(r'<section[^>]*data-role="plan-revisado".*?</section>', html, re.S)
    if not seccion:
        return {}
    texto = seccion.group(0)
    atributos = dict(re.findall(r'data-plan-([a-z-]+)="([^"]*)"', texto))
    return {
        "atributos": atributos,
        "form_sellado": 'data-role="form-sellado"' in texto,
        "form_aplicacion": 'data-role="form-aplicacion"' in texto,
        "desenlace": re.findall(r'data-plan-desenlace="([^"]*)"', texto),
        "bloqueado": re.findall(r'data-plan-bloqueado="([^"]*)"', texto),
        "texto": texto,
    }


#: EL ACUSE QUE PRODUCE EL CORPUS DE ESTE ARNES, medido y determinista.
#:
#: Los casos que usan esta constante no vienen a medir la proyeccion --miden
#: supersesion, cadena de auditoria, CSRF, permisos o procedencia-- pero eso no
#: es motivo para aflojar su asercion: todos aprueban una propuesta del corpus
#: de ejemplo que NO puede proyectar (o es un hecho negado, o su sujeto es un
#: `entity:new:` que el grafo no tiene), asi que el sellado deja siempre alguna
#: relacion fuera y el acuse es siempre el mismo.
#:
#: MEDIDO sobre los 21 sitios de llamada, CON grafo real: los 21 dan
#: `PLAN_SEALED_SIN_PROYECCION` y ninguno da otra cosa. Por eso se afirma el
#: valor EXACTO en vez de "uno de los dos acuses de exito": una comprobacion
#: laxa aqui seria regalar cobertura, y el dia que uno de estos escenarios
#: empezara a sellar limpio nadie se enteraria.
#:
#: OJO AL MEDIRLO: sin `S9K_WRITER_NEO4J_REAL=1` solo fallan 11 de los 21,
#: porque los otros 9 son `neo4j_real` y se OMITEN. Medirlo sin la variable
#: puesta da 11 y hace pensar que sobran 10 sitios. No sobran.
SELLADO_DEL_ARNES = "PLAN_SEALED_SIN_PROYECCION"


def _sellar(operador, job_id: str):
    return operador.post(
        "/panel/operations/planes",
        data={"trabajo": job_id, "csrf_token": _csrf(operador)},
    )


def _aplicar(operador, job_id: str):
    return operador.post(
        "/panel/operations/aplicaciones",
        data={"trabajo": job_id, "csrf_token": _csrf(operador)},
    )


def _aviso_de(respuesta) -> str:
    assert respuesta.status_code == 303, respuesta.text[:300]
    destino = respuesta.headers["location"]
    m = re.search(r"aviso=([A-Z_]+)", destino)
    return m.group(1) if m else ""


def _filas_de_plan(base: Path) -> list:
    """El almacén POR DENTRO. Se mira para afirmar ausencia de escritura."""
    if not base.exists():
        return []
    conexion = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
    conexion.row_factory = sqlite3.Row
    try:
        filas = conexion.execute(
            "SELECT * FROM sealed_plans ORDER BY revision"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conexion.close()
    return [dict(f) for f in filas]


def _aprobar_una(operador, cola, almacenes, monkeypatch):
    job_id = _ingerir(operador, cola, monkeypatch)
    propuesta = _aplicable(_propuestas(almacenes["propuestas"]), job_id)
    assert propuesta is not None, (
        "el corpus del arnés ya no produce ninguna propuesta aplicable"
    )
    _decidir(propuesta, "APPROVE")
    return job_id, propuesta


# ===========================================================================
# 0. La frontera que NO se mueve: `/panel/review` sigue siendo solo lectura
# ===========================================================================

def test_panel_review_sigue_sin_una_sola_escritura(real_app):
    """El apply vive en Operaciones, y por eso el hueco C no cambia.

    `chassis_review.py` declara una FRONTERA DURA («aquí no hay ningún método
    que no sea GET») y se verifica por enumeración. Colgar allí el POST del
    apply habría sido cambiar el contrato de un fichero que ya es de `main`.
    Se comprueba que NO se ha hecho, en vez de prometerlo en prosa.
    """
    from app.chassis import capabilities_for_slot, undeclared_writes

    for clave in ("C", "F", "G"):
        slot = next(x for x in FEATURE_SLOTS if x.key == clave)
        assert capabilities_for_slot(clave) == ()
        assert undeclared_writes(real_app, slot) == []


def test_el_apply_esta_declarado_y_montado_bajo_operaciones(real_app):
    """Lo declarado está montado, y lo montado está declarado. Los dos lados."""
    from app.chassis import (
        capabilities_for_slot, iter_mounted_routes, route_in_prefix,
        route_path, write_methods,
    )

    declaradas = {
        (c.path, tuple(sorted(c.methods))) for c in capabilities_for_slot("B")
    }
    # Se recorre LA APP con el censo aplanado, no `app.routes` a pelo: las
    # rutas del chasis cuelgan de routers montados y una enumeración plana no
    # las ve (medido: `app.routes` devolvía el conjunto vacío y la prueba se
    # habría puesto verde por no encontrar nada).
    montadas = {
        (route_path(r), tuple(sorted(write_methods(r))))
        for r in iter_mounted_routes(real_app)
        if write_methods(r) and route_in_prefix(r, SLOT_B.prefix)
    }
    assert montadas == declaradas
    assert ("/panel/operations/planes", ("POST",)) in declaradas
    assert ("/panel/operations/aplicaciones", ("POST",)) in declaradas


# ===========================================================================
# 1. SIN APROBAR: la acción no se habilita, no se finge y NO ESCRIBE NADA
# ===========================================================================

def test_sin_aprobar_no_hay_accion_y_cero_escritura(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """Requisito 8, medido en los TRES sitios donde podría incumplirse."""
    job_id = _ingerir(operador, cola, monkeypatch)
    propuestas = _propuestas(almacenes["propuestas"])
    assert propuestas, "la fuente del arnés ya no produce propuestas revisables"

    bloque = _bloque_plan(_panel(operador, job_id))
    assert bloque, "la pantalla no dice nada de lo aprobado"
    assert bloque["atributos"]["estado"] == "sin_plan"
    assert bloque["atributos"]["aprobadas"] == "0"
    # 1. La pantalla NO ofrece ninguno de los dos botones.
    assert not bloque["form_sellado"], "se ofrece preparar sin nada aprobado"
    assert not bloque["form_aplicacion"]

    # 2. El POST directo tampoco funciona: la pantalla no es la guarda.
    assert _aviso_de(_sellar(operador, job_id)) == "NO_APPROVED_PROPOSALS"
    assert _aviso_de(_aplicar(operador, job_id)) == "PLAN_NOT_SEALED"

    # 3. CERO ESCRITURA: no hay ni una fila de plan.
    assert _filas_de_plan(almacenes["base"]) == []


def test_rechazar_no_habilita_la_accion(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """Rechazar es decidir. Decidir no es aprobar, y no abre ninguna puerta."""
    job_id = _ingerir(operador, cola, monkeypatch)
    propuesta = _aplicable(_propuestas(almacenes["propuestas"]), job_id)
    assert propuesta is not None
    _decidir(propuesta, "REJECT")

    bloque = _bloque_plan(_panel(operador, job_id))
    assert bloque["atributos"]["aprobadas"] == "0"
    assert not bloque["form_sellado"]
    assert _aviso_de(_sellar(operador, job_id)) == "NO_APPROVED_PROPOSALS"
    assert _filas_de_plan(almacenes["base"]) == []


# ===========================================================================
# 2. AUTORIZACIÓN y CSRF: por separado, y cada uno cae SOLO
# ===========================================================================
#
# En el Corte 1 una prueba de rol pasaba aunque se degradara la guarda PORQUE
# al `reviewer` lo paraba el CSRF. Por eso el caso de rol lleva un token CSRF
# VÁLIDO y el de CSRF lo lanza un ADMIN legítimo: cada uno sólo puede ponerse
# verde por su propia razón.

@pytest.fixture
def corrida_visible_para_todos(monkeypatch):
    """El workspace de la corrida ES el ámbito por defecto del despliegue.

    SIN ESTO, EL CONTROL DE ROL NO PUEDE MORDER, y está medido: el ámbito por
    defecto es `leyenda` y la corrida del arnés es de `ws-cofradia`, así que a
    un revisor lo tapaba `scoped_job` —NO el rol— y el handler contestaba
    `SOURCE_UNKNOWN` antes de llegar a ninguna guarda. La aserción de efecto
    («no se selló nada») era entonces incapaz de ponerse roja con la guarda
    degradada: verde por la razón equivocada.

    Alineando el ámbito, lo ÚNICO que puede parar al revisor es su rol.
    """
    from app.config import get_settings

    monkeypatch.setenv("S9K_DEFAULT_WORKSPACE", "ws-cofradia")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_el_revisor_ve_la_corrida_pero_no_puede_sellarla(
    real_app, paneles_on, cola, operador, revisor, almacenes,
    corrida_visible_para_todos, monkeypatch
):
    """ROJO POR AUTORIZACIÓN, y por nada más.

    EL CASO ESTÁ MONTADO PARA QUE PUEDA FALLAR. Tres cosas, las tres medidas:

    * el revisor manda un CSRF **válido para su sesión**, así que lo que le
      pare no puede ser el CSRF. En el Corte 1 una prueba de rol pasaba aunque
      se degradara la guarda precisamente porque al `reviewer` lo paraba el
      CSRF;
    * hay algo REAL que sellar: una propuesta ya aprobada por el admin;
    * y el revisor VE la corrida — se comprueba aquí mismo, antes de nada. Sin
      esa comprobación el caso quedaba verde porque `scoped_job` lo tapaba
      antes de llegar al rol.
    """
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _filas_de_plan(almacenes["base"]) == []

    # CALIBRACIÓN DEL PROPIO CASO: la corrida es visible para el revisor. Si no
    # lo fuera, lo que sigue no probaría nada sobre el rol.
    from app import jobs_client
    from app.authz.context import build_viewer_context
    from app.authz.scope import VisibilityScope
    ambito = VisibilityScope(build_viewer_context(
        role="reviewer", auth_enabled=True, default_workspace="ws-cofradia"))
    assert jobs_client.scoped_job(ambito, job_id) is not None, (
        "la corrida no es visible para un revisor: lo que lo pare no sería el rol"
    )

    token = _csrf(revisor)
    assert token, "el revisor no tiene sesión: el caso no probaría el rol"
    respuesta = revisor.post("/panel/operations/planes",
                             data={"trabajo": job_id, "csrf_token": token})

    # EL EFECTO PRIMERO, porque es la afirmación que importa y la que tiene que
    # poder ponerse roja. Con la guarda degradada el revisor SELLA de verdad:
    # medido, la fila aparece y esta línea cae antes que ninguna otra.
    assert _filas_de_plan(almacenes["base"]) == [], "un revisor selló un plan"
    assert respuesta.status_code in (302, 303, 403, 404), respuesta.status_code
    destino = respuesta.headers.get("location", "")
    assert "aviso=" not in destino, (
        f"la acción se ATENDIÓ para un revisor ({destino}): la guarda de rol no mordió"
    )


def test_el_revisor_ve_la_corrida_pero_no_puede_aplicarla(
    real_app, paneles_on, cola, operador, revisor, almacenes,
    corrida_visible_para_todos, monkeypatch
):
    """El mismo control sobre la acción que SÍ escribe en el grafo.

    La escritura se declara HABILITADA a propósito (y el grafo se deja fuera de
    alcance). Sin habilitarla, al revisor lo paraba `APPLY_NOT_ENABLED` --otra
    vez algo que no es el rol-- y la aserción de efecto no podía ponerse roja.
    Con ella habilitada, un revisor que pasara la guarda MOVERÍA el plan: el
    apply se intenta, no alcanza el grafo y la fila queda invalidada. Eso es lo
    que aquí se comprueba que NO ocurre.
    """
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES
    assert _filas_de_plan(almacenes["base"])[0]["state"] == "sealed"

    from app.config import get_settings
    monkeypatch.setenv("S9K_ALLOW_REAL_INGEST", "1")
    monkeypatch.setenv("S9K_WRITER_WORKSPACE", "ws-cofradia")
    monkeypatch.setenv("S9K_NEO4J_URI", "bolt://127.0.0.1:1")
    monkeypatch.setenv("S9K_NEO4J_PASSWORD", "no-importa")
    get_settings.cache_clear()

    token = _csrf(revisor)
    respuesta = revisor.post("/panel/operations/aplicaciones",
                             data={"trabajo": job_id, "csrf_token": token})

    # EL EFECTO PRIMERO, por la misma razón.
    assert _filas_de_plan(almacenes["base"])[0]["state"] == "sealed", (
        "un revisor movió el estado del plan"
    )
    assert respuesta.status_code in (302, 303, 403, 404), respuesta.status_code
    assert "aviso=" not in respuesta.headers.get("location", "")


def test_un_csrf_invalido_para_el_sellado_aunque_el_rol_sea_admin(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """ROJO POR CSRF, y por nada más: quien lo manda es un admin legítimo.

    Y hay algo real que sellar, para que quitar la comprobación de CSRF
    produzca un efecto observable en vez de un `SOURCE_UNKNOWN` inocuo.
    """
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    respuesta = operador.post("/panel/operations/planes",
                              data={"trabajo": job_id,
                                    "csrf_token": "token-falsificado"})
    assert respuesta.status_code == 403, respuesta.status_code
    assert _filas_de_plan(almacenes["base"]) == [], "se selló sin CSRF válido"


def test_un_csrf_invalido_para_la_aplicacion_aunque_el_rol_sea_admin(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """El mismo control sobre la acción que escribe en el grafo."""
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES
    respuesta = operador.post("/panel/operations/aplicaciones",
                              data={"trabajo": job_id,
                                    "csrf_token": "token-falsificado"})
    assert respuesta.status_code == 403, respuesta.status_code
    assert _filas_de_plan(almacenes["base"])[0]["state"] == "sealed", (
        "se aplicó sin CSRF válido"
    )


def test_una_corrida_de_otro_no_se_puede_sellar(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """El `workspace` sale del TRABAJO, no del formulario.

    Aceptarlo de la petición permitiría dirigir la escritura a otro ámbito
    escribiendo un id en un campo oculto.
    """
    _ingerir(operador, cola, monkeypatch)
    assert _aviso_de(_sellar(operador, "job-que-no-existe")) == "SOURCE_UNKNOWN"
    assert _filas_de_plan(almacenes["base"]) == []


# ===========================================================================
# 3. SELLADO: el snapshot existe, es inmutable y no lo genera el pipeline
# ===========================================================================

def test_sellar_deja_un_snapshot_vigente_y_la_pantalla_lo_dice(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """El artefacto que faltaba, ahora persistido y ligado a la corrida."""
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)

    bloque = _bloque_plan(_panel(operador, job_id))
    assert bloque["atributos"]["aprobadas"] == "1"
    assert bloque["form_sellado"], "con algo aprobado hay que ofrecer prepararlo"
    assert not bloque["form_aplicacion"], "no se ofrece aplicar sin plan sellado"

    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES

    filas = _filas_de_plan(almacenes["base"])
    assert len(filas) == 1, filas
    fila = filas[0]
    assert fila["state"] == "sealed"
    assert fila["job_id"] == job_id
    assert fila["revision"] == 1
    documento = json.loads(fila["plan_json"])
    assert documento["mutation_operations"], "un plan sellado sin operaciones"
    assert all(op["operation_type"] == "CREATE_ASSERTION"
               for op in documento["mutation_operations"])
    assert documento["local_approval"]["approved"] is True
    # El hash guardado ES el del documento guardado. Si no, el gate del writer
    # confirmaría un plan y se aplicaría otro.
    assert fila["plan_hash"] == documento["plan_hash"]["value"]


def test_el_sellado_no_reejecuta_el_pipeline(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """Sellar es leer lo persistido. Si corriera el pipeline, esto se ve.

    Se vigila el ÚNICO núcleo de ingesta del producto (`run_ingest`, el mismo
    símbolo que usan el CLI y el handler de la cola): si sellar lo invocara,
    el contador subiría. Es una observación del efecto, no una lectura del
    código.
    """
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)

    from knowledge_v3.pipeline import ingest_cli

    llamadas = []
    original = ingest_cli.run_ingest
    monkeypatch.setattr(
        ingest_cli, "run_ingest",
        lambda *a, **k: (llamadas.append(1), original(*a, **k))[1],
    )
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES
    assert llamadas == [], "sellar reejecutó el pipeline"


def test_sellar_dos_veces_no_deja_dos_planes_vigentes(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """El invariante lo impone la BASE, no una comprobación en Python.

    `idx_sealed_plan_vigente` es un índice ÚNICO PARCIAL sobre
    (workspace, job_id) WHERE state='sealed'.
    """
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES

    filas = _filas_de_plan(almacenes["base"])
    assert len(filas) == 2, filas
    vigentes = [f for f in filas if f["state"] == "sealed"]
    assert len(vigentes) == 1, vigentes
    assert vigentes[0]["revision"] == 2
    assert filas[0]["state"] == "superseded"


# ===========================================================================
# 4. SUPERSESIÓN: cambiar una decisión invalida el plan, NO lo modifica
# ===========================================================================

def test_cambiar_una_decision_tras_sellar_supersede_el_plan_v1(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """La propiedad central del contrato del operador, medida.

    Dos afirmaciones, no una: el plan pasa a `superseded` Y su contenido
    canónico sigue siendo BYTE A BYTE el mismo. Un plan que se «actualizara»
    al cambiar una decisión dejaría de ser el snapshot de nada.
    """
    job_id, propuesta = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES
    antes = _filas_de_plan(almacenes["base"])[0]
    assert antes["state"] == "sealed"

    # El operador se lo repiensa: deshace su decisión.
    from app.services.v3_review import ReviewService
    ReviewService().undo_last(
        workspace=propuesta["workspace"],
        reviewer="apply_operador",
        request_id=f"req-undo-{uuid.uuid4().hex[:8]}",
    )

    despues = _filas_de_plan(almacenes["base"])[0]
    assert despues["state"] == "superseded", "el plan v1 siguió vigente"
    assert despues["plan_json"] == antes["plan_json"], (
        "el plan sellado se MODIFICÓ; sólo puede invalidarse"
    )
    assert despues["plan_hash"] == antes["plan_hash"]

    # Y aplicar ya no es posible: exige una revisión nueva.
    assert _aviso_de(_aplicar(operador, job_id)) == "PLAN_SUPERSEDED"
    bloque = _bloque_plan(_panel(operador, job_id))
    assert bloque["atributos"]["estado"] == "superseded"
    assert not bloque["form_aplicacion"]


# ===========================================================================
# 5. Sin escritura habilitada: se dice, y no es culpa del operador
# ===========================================================================

def test_sin_declaracion_de_escritura_no_se_ofrece_ni_se_aplica(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """503 conceptual: la dependencia no está y se dice con su código."""
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES

    monkeypatch.delenv("S9K_ALLOW_REAL_INGEST", raising=False)
    bloque = _bloque_plan(_panel(operador, job_id))
    assert bloque["atributos"]["habilitado"] == "false"
    assert not bloque["form_aplicacion"], "se ofrece un botón que no puede funcionar"
    assert bloque["bloqueado"] == ["no-habilitado"]

    assert _aviso_de(_aplicar(operador, job_id)) == "APPLY_NOT_ENABLED"
    # El plan NO se toca: no se ha intentado nada.
    assert _filas_de_plan(almacenes["base"])[0]["state"] == "sealed"


# ===========================================================================
# 6. Nada técnico llega al operador
# ===========================================================================

def test_la_pantalla_no_publica_conocimiento_interno(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """Requisito 10, comprobado sobre el HTML REAL que se sirve.

    Se buscan las cadenas concretas que el servidor conoce y el operador no:
    la identidad interna del plan, el ancla de estado, el `workspace` del
    writer y la ruta del almacén. Repositorio público: una ruta en pantalla es
    una ruta publicada.
    """
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES

    fila = _filas_de_plan(almacenes["base"])[0]
    documento = json.loads(fila["plan_json"])
    html = _panel(operador, job_id)

    prohibidas = {
        "plan_id": fila["plan_id"],
        "plan_hash": fila["plan_hash"],
        "snapshot_id": documento["snapshot_id"],
        "source_asset_id": documento["source_asset_id"],
        "ruta del almacén": str(almacenes["propuestas"]),
        "ruta de la base": str(almacenes["base"]),
    }
    filtradas = {k: v for k, v in prohibidas.items() if v and v in html}
    assert not filtradas, f"la pantalla publica material interno: {filtradas}"
    for palabra in ("Traceback", "sqlite3", "neo4j://", "bolt://"):
        assert palabra not in html, f"la pantalla publica «{palabra}»"


# ===========================================================================
# 7. EL GRAFO DE VERDAD. Contenedor propio, prefijo propio, limpieza una a una
# ===========================================================================

def _docker(*args, **kwargs):
    return subprocess.run(["docker", *args], capture_output=True, text=True, **kwargs)


def _puerto_libre() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def grafo_real():
    """Un Neo4j EFÍMERO Y PROPIO. Se borra por NOMBRE, nunca con `prune`.

    Un `docker prune` global se llevaría por delante material de otro carril
    que esté corriendo a la vez en esta misma máquina. Aquí se arranca un
    contenedor con prefijo propio y se retira ese, uno.
    """
    if not WRITER_REAL:
        # ESTE `skip` SI SE QUEDA, y es el unico. No es un fallo tapado: es la
        # declaracion explicita de que este despliegue no ha pedido grafo. Los
        # dos de abajo eran otra cosa --infraestructura que falla-- y ya no lo
        # son.
        pytest.skip("sin S9K_WRITER_NEO4J_REAL=1")
    import time

    import neo4j

    imagen = os.environ.get("S9K_WRITER_NEO4J_IMAGE", "neo4j:5.26-community")
    nombre = f"{PREFIJO_CONTENEDOR}-{uuid.uuid4().hex[:10]}"
    puerto = _puerto_libre()
    clave = "s9k-apply-ui-" + uuid.uuid4().hex[:12]
    arranque = _docker(
        "run", "--rm", "--detach", "--name", nombre,
        "--publish", f"127.0.0.1:{puerto}:7687",
        "--env", f"NEO4J_AUTH=neo4j/{clave}",
        "--env", "NEO4J_server_memory_heap_max__size=512m",
        imagen,
    )
    if arranque.returncode != 0:
        # ASSERT, NO SKIP. Un `skip` aqui convierte "Docker no arranco" en
        # verde, y lo unico que hoy lo impide es el guarda anti-skip del paso
        # de CI --una defensa que vive fuera de este fichero y que no protege a
        # quien corra esto a mano--. El modulo de la credencial de solo lectura
        # ya usa este patron; aqui se unifica.
        raise AssertionError(
            "no se pudo arrancar Neo4j y sin el la materializacion NO se "
            f"comprueba; eso no puede pasar como verde: {arranque.stderr[:200]}"
        )
    uri = f"bolt://127.0.0.1:{puerto}"
    driver = None
    try:
        limite = time.time() + 180
        ultimo = None
        while time.time() < limite:
            try:
                driver = neo4j.GraphDatabase.driver(uri, auth=("neo4j", clave))
                driver.verify_connectivity()
                break
            except Exception as exc:  # noqa: BLE001
                ultimo = exc
                if driver is not None:
                    driver.close()
                    driver = None
                time.sleep(2)
        if driver is None:
            raise AssertionError(
                f"Neo4j no llego a estar listo: {ultimo}. Un `skip` aqui seria "
                "un verde sin haber escrito ni leido nada."
            )
        import sys
        raiz = str(REPO / "data-engine" / "app")
        if raiz not in sys.path:
            sys.path.insert(0, raiz)
        from knowledge_v3.writer.schema import bootstrap_writer_schema
        bootstrap_writer_schema(driver)
        yield {"driver": driver, "uri": uri, "user": "neo4j", "password": clave}
    finally:
        if driver is not None:
            driver.close()
        _docker("rm", "-f", nombre)


@pytest.fixture
def grafo(grafo_real, monkeypatch, tmp_path):
    """Grafo LIMPIO por caso, y el visor apuntando a él con permiso declarado."""
    from app.config import get_settings

    with grafo_real["driver"].session() as sesion:
        sesion.run("MATCH (n) DETACH DELETE n")
    monkeypatch.setenv("S9K_NEO4J_URI", grafo_real["uri"])
    monkeypatch.setenv("S9K_NEO4J_USER", grafo_real["user"])
    monkeypatch.setenv("S9K_NEO4J_PASSWORD", grafo_real["password"])
    # LA CREDENCIAL DEL WORKER, POR SU CAMINO DE PRODUCCIÓN (Corte 5).
    #
    # El visor admite la contraseña en una variable; `knowledge_v3.driver_neo4j`
    # --el único módulo del motor que abre conexiones-- NO: exige el camino de
    # un fichero privado. Escribirlo aquí no es un apaño de la prueba: es lo
    # que hace que el worker de estos casos se conecte por el mismo sitio y con
    # las mismas reglas que en el despliegue, permisos `0600` incluidos. Si se
    # relajaran, el handler fallaría con `GRAPH_OBSERVATION_UNCONFIGURED` y
    # este módulo se enteraría.
    fichero = tmp_path / "neo4j-password"
    fichero.write_text(grafo_real["password"], encoding="utf-8")
    fichero.chmod(0o600)
    monkeypatch.setenv("S9K_NEO4J_PASSWORD_FILE", str(fichero))
    monkeypatch.setenv("S9K_ALLOW_REAL_INGEST", "1")
    monkeypatch.setenv("S9K_WRITER_WORKSPACE", "ws-cofradia")
    get_settings.cache_clear()
    yield grafo_real["driver"]
    with grafo_real["driver"].session() as sesion:
        sesion.run("MATCH (n) DETACH DELETE n")
    get_settings.cache_clear()


def _afirmaciones(driver, workspace: str) -> list:
    """Las afirmaciones del grafo, por IDENTIDAD DURABLE.

    Una consulta por cosa contada y comparación por `assertion_id`, nunca por
    `elementId`: el `elementId` se regenera al restaurar un dump y no
    identifica nada durable.
    """
    with driver.session() as sesion:
        filas = sesion.run(
            "MATCH (a:V3Assertion {workspace: $ws}) "
            "RETURN a.assertion_id AS id, a.predicate AS predicate, "
            "       a.subject_entity_id AS sujeto, a.object_entity_id AS objeto "
            "ORDER BY a.assertion_id",
            ws=workspace,
        ).data()
    return filas


# ---------------------------------------------------------------------------
# LA PRUEBA INSIGNIA
# ---------------------------------------------------------------------------

@neo4j_real
def test_de_la_fuente_al_conocimiento_materializado_desde_la_ui(
    real_app, paneles_on, cola, operador, almacenes, grafo, monkeypatch
):
    """fuente -> ingest -> REVIEW -> aprobar -> botón -> apply REAL -> grafo.

    Todo el recorrido por el panel. Lo que se afirma al final no es «hay algo
    escrito» sino que el `assertion_id` que está en Neo4j es EXACTAMENTE el que
    el plan sellado declaró: identidad durable contra identidad durable.
    """
    workspace = "ws-cofradia"
    assert _afirmaciones(grafo, workspace) == [], "el grafo tiene que empezar vacío"

    job_id, propuesta = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES

    fila = _filas_de_plan(almacenes["base"])[0]
    documento = json.loads(fila["plan_json"])
    esperadas = sorted(op["assertion_id"] for op in documento["mutation_operations"])
    assert esperadas, "el plan sellado no declara ninguna afirmación"

    # La pantalla OFRECE la acción, y es la pantalla la que la ejerce.
    bloque = _bloque_plan(_panel(operador, job_id))
    assert bloque["atributos"]["habilitado"] == "true"
    assert bloque["form_aplicacion"], "no se ofrece el botón de aplicar"

    assert _aviso_de(_aplicar(operador, job_id)) == "PLAN_APPLIED"

    # MATERIALIZADO, y comprobado por identidad durable.
    escritas = _afirmaciones(grafo, workspace)
    assert sorted(f["id"] for f in escritas) == esperadas, escritas
    for f in escritas:
        assert f["predicate"], "una afirmación sin predicado no es conocimiento"
        assert f["sujeto"] and f["objeto"]

    # Y el estado durable lo dice: aplicado, con su `apply_id`.
    despues = _filas_de_plan(almacenes["base"])[0]
    assert despues["state"] == "applied"
    assert despues["apply_id"], "un apply sin identidad durable no es auditable"
    assert despues["plan_json"] == fila["plan_json"], (
        "el plan aplicado se modificó: tiene que quedar inmutable"
    )

    # La pantalla cuenta el desenlace y ya no ofrece repetirlo.
    final = _bloque_plan(_panel(operador, job_id))
    assert final["atributos"]["estado"] == "applied"
    assert not final["form_aplicacion"]
    assert "applied" in final["desenlace"]


@neo4j_real
def test_aplicar_dos_veces_no_duplica_conocimiento(
    real_app, paneles_on, cola, operador, almacenes, grafo, monkeypatch
):
    """Doble clic: CERO duplicación semántica, y comportamiento EXPLÍCITO.

    No basta con que el segundo intento «no rompa»: tiene que decir qué pasó.
    """
    workspace = "ws-cofradia"
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES
    assert _aviso_de(_aplicar(operador, job_id)) == "PLAN_APPLIED"

    primera = _afirmaciones(grafo, workspace)
    assert primera, "el primer apply no escribió nada: el caso no mide nada"

    # Segundo clic, exactamente igual que el primero.
    assert _aviso_de(_aplicar(operador, job_id)) == "PLAN_ALREADY_APPLIED"

    segunda = _afirmaciones(grafo, workspace)
    assert segunda == primera, "el segundo apply duplicó conocimiento"
    assert len(_filas_de_plan(almacenes["base"])) == 1


@neo4j_real
def test_apply_consume_el_snapshot_y_no_lo_que_el_pipeline_diria_ahora(
    real_app, paneles_on, cola, operador, almacenes, grafo, monkeypatch
):
    """EL CONTROL MÁS IMPORTANTE DEL CARRIL, ejercido de verdad.

    Se sella el plan y DESPUÉS se cambia el almacén de propuestas para que una
    derivación nueva produjera un plan DISTINTO: se reescribe el paquete
    cambiando el predicado, lo que cambia el `assertion_id` derivado.

    La afirmación es que lo que acaba en el grafo sigue siendo lo del SNAPSHOT
    --el `assertion_id` sellado-- y no lo que saldría de derivar otra vez. La
    mutación del producto que sustituye la carga del snapshot por una
    regeneración pone esto rojo: el grafo traería el `assertion_id` del
    predicado nuevo, que aquí se comprueba que NO está.
    """
    workspace = "ws-cofradia"
    job_id, propuesta = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES

    documento = json.loads(_filas_de_plan(almacenes["base"])[0]["plan_json"])
    sellado = sorted(op["assertion_id"] for op in documento["mutation_operations"])
    predicado_sellado = documento["mutation_operations"][0]["payload"]["predicate"]

    # --- se cambia el material del que se derivaría un plan nuevo -----------
    predicado_nuevo = "ALLIED_WITH" if predicado_sellado != "ALLIED_WITH" else "LEADS"
    tocados = 0
    for fichero in sorted(almacenes["propuestas"].glob("*.json")):
        paquete = json.loads(fichero.read_text(encoding="utf-8"))
        for item in paquete.get("items", []):
            if item.get("proposal_id") == propuesta["proposal_id"]:
                item["proposal"]["predicate"] = predicado_nuevo
                tocados += 1
        contexto = paquete.get("plan_context") or {}
        decision = (contexto.get("decisions") or {}).get(propuesta["proposal_id"])
        if decision:
            decision["predicate"] = predicado_nuevo
        fichero.write_text(json.dumps(paquete, ensure_ascii=False, sort_keys=True),
                           encoding="utf-8")
    assert tocados == 1, "el cambio no llegó a la propuesta: el control no mide nada"

    # CALIBRACIÓN: el cambio produce de verdad OTRA identidad. Sin esto, el
    # caso podría estar verde porque la derivación nueva coincide con la vieja.
    import sys
    raiz = str(REPO / "data-engine" / "app")
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    from knowledge_v3.engine.planner import assertion_identity
    otra = assertion_identity(
        workspace=workspace,
        collection_id=documento["collection_id"],
        subject_entity_id=documento["mutation_operations"][0]["payload"]["subject_entity_id"],
        object_entity_id=documento["mutation_operations"][0]["payload"]["object_entity_id"],
        predicate=predicado_nuevo,
        direction=documento["mutation_operations"][0]["payload"]["direction"],
        negated=documento["mutation_operations"][0]["payload"]["negated"],
    )
    assert otra not in sellado, (
        "la derivación nueva daría el MISMO id: el control no distinguiría nada"
    )

    assert _aviso_de(_aplicar(operador, job_id)) == "PLAN_APPLIED"

    escritas = sorted(f["id"] for f in _afirmaciones(grafo, workspace))
    assert escritas == sellado, (
        "el apply NO consumió el snapshot sellado"
    )
    assert otra not in escritas, (
        "en el grafo está la afirmación que saldría de RECALCULAR el plan: "
        "el apply regeneró en vez de consumir lo que el operador revisó"
    )


# ===========================================================================
# 8. La RESERVA del apply, calibrada. Sin esto, `claim_for_apply` es adorno
# ===========================================================================

def test_dos_llamantes_simultaneos_solo_uno_toma_el_plan(tmp_path):
    """La carrera REAL: dos hilos tomando el mismo plan a la vez.

    POR QUÉ ESTE CASO EXISTE, MEDIDO. Se mutó `claim_for_apply` para que
    siempre dijera «lo tomo yo» y la suite entera siguió VERDE: la guarda de
    estado de `aplicar` atrapa el segundo clic secuencial antes de llegar
    aquí, así que la reserva atómica no tenía ninguna prueba capaz de ponerse
    roja. Una garantía sin prueba calibrada no es una garantía.

    Lo que aquí se ejerce es lo que aquella guarda NO puede cubrir: dos
    peticiones que leen el estado a la vez. `UPDATE ... WHERE state='sealed'`
    en SQLite sólo puede tener un ganador; una comprobación en Python, no.
    """
    import threading

    from app.services.v3_review_store import SQLiteReviewStore

    store = SQLiteReviewStore(tmp_path / "review.sqlite3")
    store.seal_plan(
        workspace="ws", job_id="job-1", plan_id="plan:carrera",
        plan_json='{"mutation_operations": []}', plan_hash="a" * 64,
        decision_ids=[], proposal_ids=[], sealed_at="2026-01-01T00:00:00Z",
        expected_decision_ids=[],
    )

    listos = threading.Barrier(8)
    ganados: list = []
    cerrojo = threading.Lock()

    def intentar():
        listos.wait()
        salida = store.claim_for_apply(plan_id="plan:carrera",
                                       now="2026-01-01T00:00:01Z")
        if salida["claimed"]:
            with cerrojo:
                ganados.append(1)

    hilos = [threading.Thread(target=intentar) for _ in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    assert len(ganados) == 1, (
        f"{len(ganados)} llamantes creyeron tomar el plan: se aplicaría varias veces"
    )
    # Y el plan queda EN VUELO, no aplicado: quien lo tomó todavía no ha dicho
    # qué pasó. `applied` sólo lo pone `record_apply_result` con el desenlace
    # real del writer delante.
    assert store.last_plan(workspace="ws", job_id="job-1")["state"] == "applying"


# ===========================================================================
# 9. B1 · LA VENTANA. Una decisión que cambia MIENTRAS se compone el plan
# ===========================================================================

def test_una_decision_que_cambia_mientras_se_sella_no_puede_colarse(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """LA GARANTÍA CENTRAL, ejercida donde estaba el agujero.

    EL DEFECTO, MEDIDO POR EL CAMINO DEL PRODUCTO. El sellado construía el plan
    con las decisiones leídas en t1 y pasaba como esperadas una SEGUNDA lectura
    en t2, en otra conexión. La guarda comparaba t2 contra t3 y nunca t1 contra
    t3: un `REJECT` registrado entre t1 y t2 era INVISIBLE, el panel contestaba
    `PLAN_SEALED`, y la fila quedaba `sealed` con una afirmación cuya decisión
    efectiva era RECHAZO. Pulsar Aplicar la habría escrito en el grafo.

    No hace falta nada exótico para caer en esa ventana: un admin sellando
    mientras cualquier revisor decide en `/panel/review` es el uso normal del
    producto. Aquí se reproduce insertando la decisión ajena en el instante en
    que el plan acaba de componerse — que es exactamente la ventana.
    """
    job_id, propuesta = _aprobar_una(operador, cola, almacenes, monkeypatch)

    import sys
    raiz = str(REPO / "data-engine" / "app")
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    from knowledge_v3 import review_plan as review_plan_mod

    original = review_plan_mod.seal_review_plan
    carreras: list = []

    def con_carrera(*args, **kwargs):
        construido = original(*args, **kwargs)
        # OTRA PERSONA DECIDE AHORA, por la autoridad real de decisiones.
        if not carreras:
            carreras.append(_decidir(propuesta, "REJECT", reviewer="otra_persona"))
        return construido

    monkeypatch.setattr(review_plan_mod, "seal_review_plan", con_carrera)

    assert _aviso_de(_sellar(operador, job_id)) == "SEAL_CONFLICT", (
        "se selló un plan cuyas decisiones habían cambiado mientras se componía"
    )
    assert carreras, "la carrera no llegó a ocurrir: el caso no mide nada"
    # CERO ESCRITURA: ni una fila. Y menos aún una con la afirmación rechazada.
    assert _filas_de_plan(almacenes["base"]) == []


def test_tras_el_conflicto_la_decision_efectiva_manda(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """Y al reintentar, lo que sale es lo que la persona decidió DE VERDAD."""
    job_id, propuesta = _aprobar_una(operador, cola, almacenes, monkeypatch)
    _decidir(propuesta, "REJECT", reviewer="otra_persona")

    assert _aviso_de(_sellar(operador, job_id)) == "NO_APPROVED_PROPOSALS"
    assert _filas_de_plan(almacenes["base"]) == []


# ===========================================================================
# 10. B2 · EL PROCESO MUERE ENTRE LA RESERVA Y LA ESCRITURA
# ===========================================================================

def test_si_el_proceso_muere_tras_reservar_no_se_afirma_conocimiento(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """NADIE puede leer «aplicado» de algo que no consta que se escribiera.

    EL DEFECTO, MEDIDO. `claim_for_apply` marcaba `applied` ANTES de escribir.
    Si el proceso moría ahí, `record_apply_result` no corría nunca y no había
    barrendero: la fila quedaba `applied` con `apply_id` NULO, la pantalla
    decía «ya forma parte del conocimiento: 1 afirmación añadida», el grafo
    estaba VACÍO y el botón de aplicar desaparecía. El marcador de «en vuelo»
    existía y NADIE LO MIRABA.

    La muerte se simula con una `BaseException` que NO es `Exception`: escapa
    del `except` del servicio igual que escaparía un `SIGKILL` del proceso, así
    que `record_apply_result` no llega a correr. Es la reproducción fiel del
    modo de fallo, no una excepción de conveniencia.
    """
    monkeypatch.setenv("S9K_ALLOW_REAL_INGEST", "1")
    monkeypatch.setenv("S9K_WRITER_WORKSPACE", "ws-cofradia")
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES

    from app.services import v3_apply as servicio

    motor_real = servicio._motor

    def motor_que_muere():
        # Se sustituye LA PIEZA POR SU NOMBRE (`apply_v3`), no por su posición.
        # Cuando el puente devolvía una tupla, esto era `piezas[1] = ...`: un
        # índice que seguía siendo válido después de que el puente cambiara de
        # forma, así que la mutación habría dejado de matar nada sin decirlo.
        piezas = motor_real()
        piezas.apply_v3 = lambda *a, **k: (_ for _ in ()).throw(
            KeyboardInterrupt("el proceso muere aquí")
        )
        return piezas

    monkeypatch.setattr(servicio, "_motor", motor_que_muere)
    token = _csrf(operador)
    try:
        operador.post("/panel/operations/aplicaciones",
                      data={"trabajo": job_id, "csrf_token": token})
    except BaseException as exc:  # noqa: BLE001 - la muerte puede propagarse
        assert isinstance(exc, KeyboardInterrupt), exc
    # Se restaura SÓLO el motor. `monkeypatch.undo()` revertiría también los
    # `setenv` de las fixtures —medido: dejaba el servicio apuntando al almacén
    # por defecto y la pantalla decía «sin_plan»—, y entonces lo que se estaría
    # midiendo sería el arnés, no el producto.
    monkeypatch.setattr(servicio, "_motor", motor_real)

    fila = _filas_de_plan(almacenes["base"])[0]
    assert fila["state"] == "applying", "la fila quedó legible como un éxito"
    assert fila["apply_id"] is None
    assert fila["applied_operations"] is None, (
        "se contabilizaron afirmaciones que nadie confirmó haber escrito"
    )

    # LA PANTALLA NO AFIRMA CONOCIMIENTO.
    bloque = _bloque_plan(_panel(operador, job_id))
    assert bloque["atributos"]["estado"] == "applying"
    assert "applying" in bloque["desenlace"]
    assert "applied" not in bloque["desenlace"]
    assert "forma parte del conocimiento" not in bloque["texto"], (
        "la pantalla afirma conocimiento que no consta escrito"
    )
    assert not bloque["form_aplicacion"]

    # Y no se reintenta a ciegas: se dice qué pasa, con su código.
    assert _aviso_de(_aplicar(operador, job_id)) == "PLAN_APPLY_IN_FLIGHT"


def test_un_apply_que_no_escribe_invalida_el_plan_en_vez_de_resucitarlo(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """Un plan que no llegó a escribir NO vuelve a estar vigente.

    Devolverlo a `sealed` resucitaba un plan cuyas decisiones pudieron cambiar
    durante el apply, sin guarda de estado y sin revalidar nada. Se invalida:
    preparar de nuevo cuesta un clic y vuelve a leer las decisiones.
    """
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES

    monkeypatch.setenv("S9K_ALLOW_REAL_INGEST", "1")
    monkeypatch.setenv("S9K_WRITER_WORKSPACE", "ws-cofradia")
    # Sin Neo4j alcanzable el writer no aplica: desenlace real, no simulado.
    monkeypatch.setenv("S9K_NEO4J_URI", "bolt://127.0.0.1:1")
    monkeypatch.setenv("S9K_NEO4J_PASSWORD", "no-importa")
    from app.config import get_settings
    get_settings.cache_clear()

    codigo = _aviso_de(_aplicar(operador, job_id))
    # CORTE 2. El rechazo del writer ya no se aplana en un `APPLY_REJECTED`
    # mudo: `EXEC_SCHEMA_CONSTRAINTS_MISSING` --que es lo que emite un grafo
    # que ni siquiera se puede consultar-- llega al operador con frase propia.
    assert codigo in (
        "APPLY_REJECTED", "APPLY_REJECTED_ESQUEMA", "APPLY_REJECTED_GRAFO",
        "APPLY_FAILED",
    ), codigo

    fila = _filas_de_plan(almacenes["base"])[0]
    assert fila["state"] == "superseded", (
        "un plan que no escribió volvió a estar vigente"
    )
    assert fila["apply_id"] is None
    get_settings.cache_clear()


def test_tras_un_apply_fallido_la_pantalla_no_culpa_a_una_decision(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """CORTE 2. El tercer camino a `superseded`, DICHO POR LO QUE FUE.

    El plan queda `superseded` porque LA ESCRITURA FALLÓ, y el operador que
    vuelve a intentarlo recibía «Una decisión cambió después de preparar lo
    aprobado»: una causa que el código no comprueba y que además OCULTA que lo
    que falló fue el apply. Aquí se recorre el caso entero por la UI —sellar,
    aplicar contra un grafo inalcanzable, volver a aplicar— y se exige que el
    segundo desenlace nombre el apply fallido.
    """
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES

    monkeypatch.setenv("S9K_ALLOW_REAL_INGEST", "1")
    monkeypatch.setenv("S9K_WRITER_WORKSPACE", "ws-cofradia")
    monkeypatch.setenv("S9K_NEO4J_URI", "bolt://127.0.0.1:1")
    monkeypatch.setenv("S9K_NEO4J_PASSWORD", "no-importa")
    from app.config import get_settings
    get_settings.cache_clear()

    primero = _aviso_de(_aplicar(operador, job_id))
    assert primero != "PLAN_SUPERSEDED", primero
    fila = _filas_de_plan(almacenes["base"])[0]
    assert fila["state"] == "superseded", fila["state"]
    # EL DATO QUE DISTINGUE EL CAMINO. Lo escribe únicamente `finish_apply`.
    assert fila["apply_notes_json"], (
        "sin notas de apply no hay forma de saber que este `superseded` vino "
        "de una escritura fallida"
    )

    segundo = _aviso_de(_aplicar(operador, job_id))
    assert segundo == "PLAN_SUPERSEDED_TRAS_APPLY_FALLIDO", segundo

    # Y LA PANTALLA lo dice: el testigo pide el HTML, no el código.
    from app import panel_errors
    html = _panel(operador, job_id, aviso=segundo)
    assert "Una decision cambio" not in html, (
        "la pantalla sigue achacando a una decisión lo que fue un apply fallido"
    )
    assert panel_errors.CATALOGO[segundo] in html, html[:400]
    get_settings.cache_clear()


# ===========================================================================
# 11. La cadena de auditoría DEJA DE SER DE SÓLO ESCRITURA
# ===========================================================================

def test_el_sellado_queda_en_la_cadena_y_la_cadena_se_lee(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """Reusar `decision_audit` sólo vale si alguien la LEE."""
    from app.services.v3_review_store import SQLiteReviewStore

    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES

    eventos = SQLiteReviewStore(almacenes["base"]).audit_events("ws-cofradia")
    tipos = [e["event_type"] for e in eventos]
    assert "HUMAN_DECISION_RECORDED" in tipos
    assert "REVIEW_PLAN_SEALED" in tipos, tipos
    sellado = next(e for e in eventos if e["event_type"] == "REVIEW_PLAN_SEALED")
    assert sellado["job_id"] == job_id
    assert sellado["plan_hash"] == _filas_de_plan(almacenes["base"])[0]["plan_hash"]


def test_con_la_cadena_rota_no_se_sella_nada(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """La verificación es una PRECONDICIÓN del sellado, no un adorno.

    Se altera un `record_hash` del registro encadenado; a partir de ahí lo que
    se escribiera encima no sería auditable, y el producto se niega.
    """
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)

    conexion = sqlite3.connect(almacenes["base"])
    try:
        conexion.execute(
            "UPDATE decision_audit SET record_hash=? WHERE audit_seq=("
            "  SELECT MIN(audit_seq) FROM decision_audit)",
            ("0" * 64,),
        )
        conexion.commit()
    finally:
        conexion.close()

    assert _aviso_de(_sellar(operador, job_id)) == "AUDIT_CHAIN_BROKEN"
    assert _filas_de_plan(almacenes["base"]) == []


# ===========================================================================
# 12. B3 · LO QUE EL NÚCLEO DICE, LLEGA AL OPERADOR
# ===========================================================================

@neo4j_real
def test_la_pantalla_dice_que_lo_escrito_no_queda_navegable(
    real_app, paneles_on, cola, operador, almacenes, grafo, monkeypatch
):
    """FALSA COMPLETITUD, cerrada.

    `apply_v3` devuelve `APPLY_PROVENANCE_NOT_PERSISTED` y ENUMERA las
    referencias de evidencia que quedan colgando. Ese código llegaba al
    servicio y moría allí: el router sólo usaba el aviso del 303, y la pantalla
    decía «Lo aprobado ya forma parte del conocimiento» a secas. Quien luego
    mirase la afirmación no encontraría la evidencia que cita, y nadie se lo
    habría dicho.

    CÓMO SE ALCANZA AHORA LA CONDICIÓN (B2). El camino feliz ya NO deja la
    procedencia sin persistir: el sobre publica el paquete y el sellado lo fija
    con el plan. La propiedad que este caso protege sigue siendo necesaria
    —cuando el núcleo emita esa nota, la pantalla tiene que decirlo— así que se
    llega a ella MUTANDO EL PRODUCTO para que el paquete no se publique, en vez
    de esperarla del camino normal. La guarda del propio caso fue la que avisó
    de que ya no se alcanzaba: sin ella, esto habría seguido verde midiendo
    otra cosa.
    """
    from app.services import v3_apply as servicio

    monkeypatch.setattr(
        servicio.ReviewApplyService, "_procedencia",
        lambda self, mod, aprobadas, job_id: None,
    )
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES
    # El desenlace ya no es `PLAN_APPLIED`: sin procedencia alcanzable, un
    # apply no puede anunciarse como éxito completo.
    assert _aviso_de(_aplicar(operador, job_id)) == "APPLY_INCOMPLETE"

    fila = _filas_de_plan(almacenes["base"])[0]
    notas = json.loads(fila["apply_notes_json"] or "[]")
    assert "APPLY_PROVENANCE_NOT_PERSISTED" in notas, (
        f"el núcleo ya no emite esa nota; el caso mediría otra cosa: {notas}"
    )
    # El recuento sale de lo que el WRITER dijo, no de len(operaciones).
    assert fila["applied_operations"] is not None and fila["applied_operations"] >= 1

    bloque = _bloque_plan(_panel(operador, job_id))
    assert "APPLY_PROVENANCE_NOT_PERSISTED" in bloque["atributos"].get("aviso", "") \
        or 'data-plan-aviso="APPLY_PROVENANCE_NOT_PERSISTED"' in bloque["texto"], (
        "la pantalla no dice que lo escrito no queda navegable hasta su evidencia"
    )
    assert "no queda navegable" in bloque["texto"]


# ===========================================================================
# 10. SLICE 2 · B2 — PROCEDENCIA PERSISTIDA Y EFECTO OBSERVADO
#
# Lo que este bloque cierra, medido sobre la base de este carril: aplicar desde
# la UI escribía la afirmación, dejaba `APPLY_PROVENANCE_NOT_PERSISTED` y la
# pantalla decía «ya forma parte del conocimiento». Desde el operador eso es
# FALSO ÉXITO: la afirmación citaba fragmentos que no existían y no había forma
# de llegar desde lo escrito hasta el texto que lo sostiene.
#
# La regla que se comprueba aquí no es «siempre tiene que haber arista» —no
# toda afirmación produce una— sino: TODA OPERACIÓN PRODUCE EL EFECTO QUE
# DECLARA SU TIPO, Y ESE EFECTO ES TRAZABLE. Y se comprueba MIRANDO EL GRAFO,
# porque lo que el writer dijo haber hecho no contesta a si está hecho.
# ===========================================================================

def _fila_de_plan(base: Path) -> dict:
    filas = _filas_de_plan(base)
    assert filas, "no hay ningún plan sellado: el caso no mide nada"
    return filas[-1]


def _notas_de(base: Path) -> list:
    crudo = _fila_de_plan(base)["apply_notes_json"]
    try:
        return list(json.loads(crudo or "[]"))
    except (TypeError, ValueError):  # pragma: no cover - fila corrupta
        return []


def _motor_en_ruta():
    import sys
    raiz = str(REPO / "data-engine" / "app")
    if raiz not in sys.path:
        sys.path.insert(0, raiz)


def _recorrido(driver, workspace: str, assertion_id: str) -> list:
    """La procedencia POR EL CAMINO, con la consulta del propio producto.

    Se usa `provenance.trace_query`, que encadena
    afirmación -> evidencia -> episodio -> fuente en UN patrón sobre la misma
    fila. Escribir aquí dos `MATCH` sueltos daría el producto cartesiano y
    cero filas, que se leería como «no hay procedencia» tanto si la hay como
    si no.
    """
    _motor_en_ruta()
    from knowledge_v3.writer.provenance import trace_query

    consulta = trace_query(workspace, assertion_id)
    with driver.session() as sesion:
        return [dict(f) for f in sesion.run(consulta.cypher, **consulta.params)]


def _cuenta(driver, cypher: str, **params) -> int:
    """UNA consulta por UNA cosa contada. Nunca dos `MATCH` sueltos."""
    with driver.session() as sesion:
        return sesion.run(cypher, **params).single()["c"]


# ---------------------------------------------------------------------------
# LA PRUEBA INSIGNIA DE B2
# ---------------------------------------------------------------------------

@neo4j_real
def test_desde_el_resultado_se_llega_a_la_evidencia_CORRECTA(
    real_app, paneles_on, cola, operador, almacenes, grafo, monkeypatch
):
    """fuente -> ingest -> REVIEW -> aprobar -> sellar -> APPLY DESDE LA UI
    -> grafo real -> seguir la procedencia -> llegar a la evidencia CORRECTA.

    Lo que se afirma al final NO es «hay procedencia» —un recorrido que
    llegase a cualquier fragmento pondría eso verde— sino que el literal al
    que se llega es EXACTAMENTE el que la propuesta que el operador aprobó
    citaba. Identidad durable contra identidad durable, y además el texto.
    """
    workspace = "ws-cofradia"
    job_id, propuesta = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES

    documento = json.loads(_fila_de_plan(almacenes["base"])["plan_json"])
    operaciones = documento["mutation_operations"]
    afirmacion = operaciones[0]["assertion_id"]
    citados = sorted(operaciones[0]["evidence_fragment_ids"])
    assert citados, "la operación no cita evidencia: el caso no mide procedencia"

    assert _aviso_de(_aplicar(operador, job_id)) == "PLAN_APPLIED"

    # 1. El estado durable dice APLICADO, no PARCIAL, y lo dice porque se MIRÓ.
    fila = _fila_de_plan(almacenes["base"])
    assert fila["state"] == "applied", fila["state"]
    assert fila["apply_id"], "un apply sin identidad durable no es auditable"
    assert "APPLY_PROVENANCE_PERSISTED" in _notas_de(almacenes["base"])

    # 2. El recorrido llega, y llega A LO QUE SE CITÓ.
    recorrido = _recorrido(grafo, workspace, afirmacion)
    assert recorrido, (
        "no se llega desde la afirmación a ninguna evidencia: lo escrito no es "
        "navegable"
    )
    alcanzados = sorted({f["fragment_id"] for f in recorrido})
    assert alcanzados == citados, (recorrido, citados)

    # 3. Y el literal es el de la propuesta que se aprobó, no otro cualquiera.
    esperado = (propuesta.get("evidence") or {}).get("literal_text")
    assert esperado, "la propuesta del arnés ya no trae literal: no se puede medir"
    literales = {f["literal"] for f in recorrido}
    assert esperado in literales, (esperado, literales)

    # 4. La cadena completa está: evidencia, episodio y fuente, no sólo el
    #    primer tramo. Un `SUPPORTED_BY` suelto diría que hay procedencia con
    #    el recorrido roto más arriba.
    for tramo in recorrido:
        assert tramo["episode_id"], tramo
        assert tramo["source_asset_id"], tramo

    # 5. LA CADENA ENTERA, recorrida hop a hop desde el `apply_id`.
    #
    #    apply_id -> V3AppliedOperation -> idempotency_key -> V3Assertion
    #             -> SUPPORTED_BY -> V3Evidence -> episodio -> fuente
    #
    #    MEDIDO, y hay que decirlo: el primer tramo NO es una arista.
    #    `V3AppliedOperation` se escribe como un `MERGE` de nodo suelto
    #    (`cypher.claim_applied_operation`) y no tiene ninguna relación hacia
    #    lo que escribió: la unión es POR VALOR, por la `idempotency_key` que
    #    el writer estampa en todo lo que crea (`executor._provenance`). La
    #    cadena EXISTE y se puede recorrer —esto lo demuestra—, pero se
    #    recorre por valor y no por camino. Está en el informe como deuda; no
    #    se arregla aquí porque el writer y el esquema son contrato congelado.
    #
    #    UNA CONSULTA POR TRAMO, a propósito: encadenar dos `MATCH` sueltos
    #    daría el producto cartesiano y cero filas, que se leería igual que
    #    «la cadena está rota» tanto si lo está como si no.
    with grafo.session() as sesion:
        claves = [
            f["clave"] for f in sesion.run(
                "MATCH (o:V3AppliedOperation {workspace: $ws, apply_id: $aid}) "
                "RETURN o.idempotency_key AS clave ORDER BY clave",
                ws=workspace, aid=fila["apply_id"],
            )
        ]
    assert claves, "el apply no dejó ninguna operación marcada con su apply_id"
    assert sorted(claves) == sorted(
        op["idempotency_key"] for op in operaciones
    ), (claves, operaciones)

    for clave in claves:
        with grafo.session() as sesion:
            alcanzadas = [
                f["id"] for f in sesion.run(
                    "MATCH (a:V3Assertion {workspace: $ws, idempotency_key: $k}) "
                    "RETURN a.assertion_id AS id",
                    ws=workspace, k=clave,
                )
            ]
        assert alcanzadas == [afirmacion], (clave, alcanzadas)
        # Y desde ahí, el recorrido de procedencia ya comprobado arriba.
        assert _recorrido(grafo, workspace, alcanzadas[0]), clave


# ---------------------------------------------------------------------------
# CONTROL 2 — la afirmación se escribe y la PROCEDENCIA no: NO es éxito
# ---------------------------------------------------------------------------

@neo4j_real
def test_sin_paquete_de_procedencia_el_apply_NO_termina_como_exito(
    real_app, paneles_on, cola, operador, almacenes, grafo, monkeypatch
):
    """MUTACIÓN EN EL PRODUCTO: el sellado deja de publicar el paquete.

    Es exactamente el estado en el que estaba la base: L2 escrito, evidencia
    colgando. Antes de este carril eso salía `PLAN_APPLIED` y la pantalla
    decía «ya forma parte del conocimiento». Ahora tiene que salir ROJO, y el
    rojo tiene que ser POR ESTA CAUSA.
    """
    workspace = "ws-cofradia"
    from app.services import v3_apply as servicio

    monkeypatch.setattr(
        servicio.ReviewApplyService, "_procedencia",
        lambda self, mod, aprobadas, job_id: None,
    )
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES

    # CALIBRACIÓN DE LA MUTACIÓN: si el paquete siguiera publicándose, este
    # caso mediría otra cosa y saldría verde por el motivo equivocado.
    assert _fila_de_plan(almacenes["base"])["provenance_json"] is None, (
        "la mutación no llegó al sellado: el control no mide nada"
    )

    assert _aviso_de(_aplicar(operador, job_id)) == "APPLY_INCOMPLETE"

    # L2 SÍ se escribió: decir «no se ha escrito nada» también sería falso.
    documento = json.loads(_fila_de_plan(almacenes["base"])["plan_json"])
    afirmacion = documento["mutation_operations"][0]["assertion_id"]
    assert _afirmaciones(grafo, workspace), "el control no llegó a escribir L2"

    # Y el estado es PARCIAL, con nombre, y con la causa EXACTA.
    fila = _fila_de_plan(almacenes["base"])
    assert fila["state"] == "partial", fila["state"]
    notas = _notas_de(almacenes["base"])
    assert "APPLY_PROVENANCE_NOT_PERSISTED" in notas, notas
    assert "PROVENANCE_UNREACHABLE" in notas, notas
    assert _recorrido(grafo, workspace, afirmacion) == [], (
        "hay recorrido de procedencia sin paquete: el control no distingue nada"
    )

    # LA PANTALLA LO DICE. No basta con que la fila lo sepa.
    bloque = _bloque_plan(_panel(operador, job_id))
    assert bloque["atributos"]["estado"] == "partial"
    assert "partial" in bloque["desenlace"]
    assert "PROVENANCE_UNREACHABLE" in bloque["texto"]
    assert "ya forma parte del conocimiento" not in bloque["texto"]


# ---------------------------------------------------------------------------
# CONTROL 3 — la procedencia apunta a OTRA cosa: rojo por ATRIBUCIÓN
# ---------------------------------------------------------------------------

@neo4j_real
def test_procedencia_de_otro_material_no_pone_verde_esta_afirmacion(
    real_app, paneles_on, cola, operador, almacenes, grafo, monkeypatch
):
    """Se persiste evidencia REAL, pero de OTROS fragmentos.

    El grafo acaba con nodos `V3Evidence` de verdad colgando de la fuente. Lo
    único que falla es que no es LA de esta afirmación. Un verificador que
    contase nodos de evidencia saldría verde aquí; el rojo tiene que decir
    `PROVENANCE_UNREACHABLE` y el fragmento citado NO puede estar.
    """
    workspace = "ws-cofradia"
    from app.services import v3_apply as servicio

    original = servicio.ReviewApplyService._procedencia

    def ajena(self, mod, aprobadas, job_id):
        paquete = original(self, mod, aprobadas, job_id)
        assert paquete, "sin paquete original el control no mide atribución"
        # Mismo material, OTRAS identidades durables.
        for fragmento in paquete["fragments"]:
            fragmento["fragment_id"] = "ef-de-otra-corrida-" + fragmento["fragment_id"][-8:]
        return paquete

    monkeypatch.setattr(servicio.ReviewApplyService, "_procedencia", ajena)
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES
    assert _aviso_de(_aplicar(operador, job_id)) == "APPLY_INCOMPLETE"

    documento = json.loads(_fila_de_plan(almacenes["base"])["plan_json"])
    operacion = documento["mutation_operations"][0]
    citados = sorted(operacion["evidence_fragment_ids"])

    # HAY evidencia en el grafo, y de verdad: el rojo NO es por un grafo vacío.
    assert _cuenta(grafo, "MATCH (e:V3Evidence {workspace: $ws}) RETURN count(e) AS c",
                   ws=workspace) > 0
    # Pero ninguna es la que esta afirmación cita.
    assert _recorrido(grafo, workspace, operacion["assertion_id"]) == []
    assert _fila_de_plan(almacenes["base"])["state"] == "partial"
    notas = _notas_de(almacenes["base"])
    assert "PROVENANCE_UNREACHABLE" in notas, notas
    for fragmento in citados:
        assert _cuenta(
            grafo,
            "MATCH (e:V3Evidence {workspace: $ws, fragment_id: $fid}) RETURN count(e) AS c",
            ws=workspace, fid=fragmento,
        ) == 0, "el fragmento citado SÍ está: la mutación no cambió la identidad"


# ---------------------------------------------------------------------------
# CONTROL 4 — repetir el apply no duplica NI conocimiento NI procedencia
# ---------------------------------------------------------------------------

@neo4j_real
def test_repetir_el_apply_no_duplica_la_procedencia(
    real_app, paneles_on, cola, operador, almacenes, grafo, monkeypatch
):
    """La idempotencia se mide también en el volcado, no sólo en el plan."""
    workspace = "ws-cofradia"
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES
    assert _aviso_de(_aplicar(operador, job_id)) == "PLAN_APPLIED"

    def foto() -> tuple:
        return (
            _cuenta(grafo, "MATCH (e:V3Evidence {workspace: $ws}) RETURN count(e) AS c", ws=workspace),
            _cuenta(grafo, "MATCH (e:V3Episode {workspace: $ws}) RETURN count(e) AS c", ws=workspace),
            _cuenta(grafo, "MATCH (s:V3Source {workspace: $ws}) RETURN count(s) AS c", ws=workspace),
            _cuenta(grafo, "MATCH ()-[r:SUPPORTED_BY]->() RETURN count(r) AS c"),
        )

    primera = foto()
    assert primera[0] > 0 and primera[3] > 0, (
        "el primer apply no dejó procedencia: el control no mide nada"
    )

    assert _aviso_de(_aplicar(operador, job_id)) == "PLAN_ALREADY_APPLIED"
    assert foto() == primera, "el segundo apply duplicó procedencia"
    assert len(_filas_de_plan(almacenes["base"])) == 1


# ---------------------------------------------------------------------------
# CONTROL 5 — EL DECISIVO: se mata el volcado con L2 ya escrito
# ---------------------------------------------------------------------------

@neo4j_real
def test_matar_el_volcado_deja_estado_PARCIAL_dicho_y_reconciliable(
    real_app, paneles_on, cola, operador, almacenes, grafo, monkeypatch
):
    """Aquí se ve si hay ATOMICIDAD FINGIDA.

    El plan se ejecuta en su transacción y la procedencia en OTRA, después. No
    hay ACID entre las dos. Se mata la segunda con L2 ya escrito y se exige:

      1. que NO se anuncie éxito;
      2. que el estado tenga NOMBRE (`partial`) y no se disfrace de `applied`
         ni de `superseded` —volver a `sealed` diría que el grafo está
         intacto, y no lo está—;
      3. que la pantalla lo diga;
      4. y que la RECONCILIACIÓN lo termine: el mismo plan, reaplicado, sin
         duplicar nada.
    """
    workspace = "ws-cofradia"
    _motor_en_ruta()
    from knowledge_v3.writer import apply as apply_mod

    original = apply_mod.persist_provenance
    estado = {"matar": True, "llamadas": 0}

    def volcado(*args, **kwargs):
        estado["llamadas"] += 1
        if estado["matar"]:
            raise RuntimeError("volcado de procedencia interrumpido (control 5)")
        return original(*args, **kwargs)

    # LA MUTACIÓN SE LEVANTA CON UN INTERRUPTOR, NO CON `monkeypatch.undo()`.
    # MEDIDO: `undo()` revierte TODO lo que este `monkeypatch` hizo en el caso
    # —incluidos los `setenv` de las fixtures que apuntan el servicio al
    # almacén de `tmp_path`—, y la reconciliación acababa buscando el plan en
    # el almacén por defecto y contestando `PLAN_NOT_SEALED`. El rojo existía,
    # pero por la causa equivocada: habría dado por bueno que la
    # reconciliación no funciona cuando lo que fallaba era el arnés.
    monkeypatch.setattr(apply_mod, "persist_provenance", volcado)

    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES
    # CALIBRACIÓN: el paquete SÍ se selló. Lo que se mata es el volcado, no el
    # material; si no, este control sería el 2 otra vez.
    assert _fila_de_plan(almacenes["base"])["provenance_json"], (
        "el paquete no se selló: este control mediría la ausencia de material"
    )

    assert _aviso_de(_aplicar(operador, job_id)) == "APPLY_INCOMPLETE"
    assert estado["llamadas"] == 1, "el volcado no llegó a intentarse"

    # 1+2. L2 ESCRITO y estado PARCIAL con nombre.
    documento = json.loads(_fila_de_plan(almacenes["base"])["plan_json"])
    afirmacion = documento["mutation_operations"][0]["assertion_id"]
    assert [f["id"] for f in _afirmaciones(grafo, workspace)] == [afirmacion]
    fila = _fila_de_plan(almacenes["base"])
    assert fila["state"] == "partial", fila["state"]
    notas = _notas_de(almacenes["base"])
    assert "APPLY_PROVENANCE_FAILED" in notas, notas
    assert "PROVENANCE_UNREACHABLE" in notas, notas
    assert _cuenta(grafo, "MATCH (e:V3Evidence) RETURN count(e) AS c") == 0

    # 3. LA PANTALLA LO DICE, y sigue ofreciendo terminarlo.
    bloque = _bloque_plan(_panel(operador, job_id))
    assert "partial" in bloque["desenlace"]
    assert bloque["form_aplicacion"], (
        "sin botón, la única salida sería volver a sellar y abandonar lo escrito"
    )

    # 4. RECONCILIACIÓN: se levanta la mutación y se reaplica EL MISMO plan.
    estado["matar"] = False
    assert _aviso_de(_aplicar(operador, job_id)) == "PLAN_APPLIED"
    assert estado["llamadas"] == 2, "la reconciliación no volvió a volcar"

    final = _fila_de_plan(almacenes["base"])
    assert final["state"] == "applied", final["state"]
    assert final["plan_json"] == fila["plan_json"], (
        "la reconciliación cambió el plan: tenía que reaplicar EL MISMO"
    )
    # Sin duplicar el conocimiento que ya estaba...
    assert [f["id"] for f in _afirmaciones(grafo, workspace)] == [afirmacion]
    # ...y con la procedencia ya alcanzable.
    recorrido = _recorrido(grafo, workspace, afirmacion)
    assert recorrido, "la reconciliación no completó la procedencia"
    assert sorted({f["fragment_id"] for f in recorrido}) == sorted(
        documento["mutation_operations"][0]["evidence_fragment_ids"]
    )


# ===========================================================================
# SLICE 2 · CORTE 5 — LA PROYECCIÓN, DESDE LA UI Y CONTRA EL GRAFO DE VERDAD
# ===========================================================================
#
# EL DEFECTO QUE ESTA SECCIÓN FIJA. Medido antes del corte, de punta a punta:
# el manejador de ingesta del panel llamaba a `run_ingest` con `driver=None`
# LITERAL, y `observed=True` se pone en UN SOLO SITIO de todo el motor
# (`graph_catalog.snapshot_entities`), alcanzable sólo con driver. Resultado:
# las cuatro anclas del sobre que produce ese camino salían con
# `observed: false` y el sellado omitía TODA proyección con
# `PROJECTION_ANCHOR_NOT_OBSERVED`. La capacidad de proyectar existía, era
# correcta, y el producto no la alcanzaba.
#
# POR QUÉ ESTOS CASOS NO SE PUEDEN PONER VERDES SIN LEER EL GRAFO. El plan
# sellado se compara contra la `version` y el `state_hash` REALES del nodo, y
# los dos se siembran con valores que ningún catálogo en fichero produce: la
# versión no es el `0` por defecto de `bridge.entities_from_catalog`, y el hash
# es el que el propio writer computa sobre las propiedades del nodo, no el
# derivado de `{entity_id, entity_type, version}`.

VERSION_SEMBRADA = 7


def _sembrar_entidades(driver, workspace: str, entidades: list) -> dict:
    """Mete entidades REALES en el grafo y devuelve su ancla observable.

    El `state_hash` no se inventa: se crea el nodo, se leen sus propiedades tal
    y como quedaron, y se computa con la MISMA función que usa el writer
    (`writer/state.state_hash_value`). Un hash inventado aquí produciría un
    plan que aborta en el executor con `EXEC_HASH_MISMATCH`, es decir, un rojo
    por la causa equivocada.
    """
    from knowledge_v3.writer.state import state_hash_value

    anclas = {}
    with driver.session() as sesion:
        for entidad in entidades:
            props = {
                "entity_id": entidad["entity_id"],
                "entity_type": entidad["type"],
                "name": entidad["name"],
                "aliases": list(entidad.get("aliases") or ()),
                "workspace": workspace,
                "version": VERSION_SEMBRADA,
                "status": "ACTIVE",
            }
            fila = sesion.run(
                "CREATE (n:V3Entity) SET n = $props RETURN properties(n) AS p",
                props=props,
            ).single()
            digest = state_hash_value(fila["p"])
            sesion.run(
                "MATCH (n:V3Entity {entity_id: $id, workspace: $ws}) "
                "SET n.state_hash = $h",
                id=entidad["entity_id"], ws=workspace, h=digest,
            )
            anclas[entidad["entity_id"]] = {
                "version": VERSION_SEMBRADA, "state_hash": digest,
            }
    return anclas


def _catalogo_del_ejemplo() -> list:
    """Las entidades NO provisionales del catálogo del ejemplo."""
    documento = json.loads(
        (EJEMPLOS / "catalogo-workspace.json").read_text(encoding="utf-8")
    )
    return [e for e in documento["entities"] if not e.get("provisional")]


def _operaciones_del_plan(base: Path) -> list:
    fila = _filas_de_plan(base)[0]
    return json.loads(fila["plan_json"])["mutation_operations"]


def _proyecciones(operaciones: list) -> list:
    return [o for o in operaciones if o.get("operation_type") == "PROJECT_RELATION"]


#: NOTA PROPIA DE ESTOS DOS CASOS, y por que no vale la del arnes.
#:
#: MEDIDO sobre `examples/ingesta-v3/`: de las cuatro propuestas que esa fuente
#: deja en la cola de revision, NINGUNA puede proyectar.
#:
#:   * dos traen `predicate: UNKNOWN`, que el sellado excluye;
#:   * una es un hecho NEGADO --el grafo no aprende una relacion que el texto
#:     niega-- y sale con `PROJECTION_NEGATED_FACT`;
#:   * y la cuarta tiene por sujeto un `entity:new:...` que el grafo no tiene,
#:     asi que sale con `PROJECTION_NO_ANCHOR`.
#:
#: Los dos ultimos codigos se leen igual de rojos que el que este carril mide, y
#: usando esa fuente el control negativo enrojecia por ellos. Por eso estos dos
#: casos traen su propia nota: una relacion AFIRMATIVA, con predicado conocido y
#: entre dos entidades que SI estan sembradas en el grafo. Es el unico montaje en
#: el que "no hay proyeccion" solo puede significar "no se observo el ancla".
NOTA_PROYECTABLE = """# Nota de sesion — relacion proyectable

Sela Marrec se rumorea que pertenece al Consejo de Umbra.

Parece que la Cofradia de Ambar es aliada del Consejo de Umbra.

Quiza Sela Marrec vive en Vado Alto.

La Casa del Ciervo podria ser aliada del Consejo de Umbra.

Se dice que Sela Marrec lidera la Casa del Ciervo.
"""


@pytest.fixture
def fuente_proyectable(tmp_path) -> Path:
    """Un directorio de fuentes propio, con el MISMO perfil y catalogo.

    Se copian los del ejemplo en vez de escribir otros: el workspace, el perfil
    y el catalogo tienen que seguir siendo los que el resto del arnes usa, o
    las entidades sembradas no serian las que la corrida resuelve.
    """
    directorio = tmp_path / "fuentes-proyeccion"
    directorio.mkdir()
    for nombre in ("perfil-operador.json", "catalogo-workspace.json"):
        shutil.copy(EJEMPLOS / nombre, directorio / nombre)
    (directorio / "nota-relacion-proyectable.md").write_text(
        NOTA_PROYECTABLE, encoding="utf-8"
    )
    return directorio


def _ingerir_desde(operador, cola, monkeypatch, directorio: Path) -> str:
    """Como `_ingerir`, pero sobre el catalogo de fuentes que se le diga."""
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(directorio))
    pantalla = operador.get(SLOT_B.prefix)
    assert pantalla.status_code == 200, pantalla.status_code
    opciones = _opciones(pantalla.text)
    assert opciones, "no se ofrece ninguna fuente que elegir"
    envio = operador.post(
        "/panel/operations/ingestas",
        data={"fuente": opciones[0], "csrf_token": _csrf(operador)},
    )
    assert envio.status_code == 303, envio.text[:300]
    store = jobs_client._load_job_store()
    pendientes = store.list_jobs(status="pending", db_path=str(cola))
    assert len(pendientes) == 1, pendientes
    job_id = pendientes[0]["job_id"]

    from jobs import worker
    assert worker.run("worker-proyeccion", once=True, limit=1, db_path=str(cola)) == 1
    final = store.get_job(job_id, db_path=str(cola))
    assert final["status"] == "complete", final.get("error_message")
    return job_id


def _proyectable(propuestas: list, job_id: str, existentes: set):
    """La propuesta de la corrida que PUEDE llegar a proyectar. Tres filtros.

    Los tres corresponden a los tres motivos de omision que NO son el de este
    carril, y estan aqui para que ninguno de ellos pueda explicar un rojo:

      * predicado y direccion conocidos --si no, el sellado la excluye antes;
      * hecho NO negado --`PROJECTION_NEGATED_FACT`--;
      * y sujeto y objeto que EXISTEN en el grafo --`PROJECTION_NO_ANCHOR` y
        `PROJECTION_ENTITY_NOT_IN_GRAPH`--.

    Lo que queda despues de los tres solo puede caerse por no haber observado.
    """
    for propuesta in propuestas:
        if job_id not in (propuesta.get("package_runs") or ()):
            continue
        cuerpo = propuesta.get("proposal") or {}
        resolucion = propuesta.get("resolution") or {}
        if cuerpo.get("negated"):
            continue
        if cuerpo.get("predicate") in (None, "", "UNKNOWN"):
            continue
        if cuerpo.get("direction") in (None, "", "UNKNOWN"):
            continue
        if resolucion.get("subject") not in existentes:
            continue
        if resolucion.get("object") not in existentes:
            continue
        return propuesta
    return None


def _aprobar_proyectable(operador, cola, almacenes, monkeypatch, directorio,
                         existentes):
    job_id = _ingerir_desde(operador, cola, monkeypatch, directorio)
    propuesta = _proyectable(_propuestas(almacenes["propuestas"]), job_id, existentes)
    assert propuesta is not None, (
        "la nota de estos casos ya no produce ninguna propuesta que pueda "
        "proyectar (sin negar, con predicado y direccion, y entre entidades "
        "sembradas). Sin una, ni la insignia ni su control negativo miden nada."
    )
    _decidir(propuesta, "APPROVE")
    return job_id, propuesta


@neo4j_real
def test_insignia_la_ui_proyecta_una_relacion_anclada_en_lo_OBSERVADO(
    real_app, paneles_on, cola, operador, almacenes, grafo, monkeypatch,
    fuente_proyectable
):
    """/panel -> apply -> worker REAL -> Neo4j -> observación -> proyección.

    LA RELACIÓN QUE SÓLO PUEDE PROYECTARSE SI SE LEYÓ EL GRAFO. El ancla de la
    operación `PROJECT_RELATION` lleva `expected_version = 7` y un
    `expected_hash` computado sobre las propiedades REALES del nodo sembrado.
    Ninguna de las dos cosas es derivable de un fichero:

      * `bridge.entities_from_catalog` pone `version = 0`, no 7;
      * y su `state_hash` sale de `sha256({entity_id, entity_type, version})`,
        que es reconstruible sin haber mirado el grafo -- plausible y falso.

    Por eso la comparación final no es «hay una proyección» (eso se pondría
    verde con un ancla inventada) sino que el ancla del plan es IGUAL a la del
    nodo que está en Neo4j.
    """
    workspace = "ws-cofradia"
    anclas = _sembrar_entidades(grafo, workspace, _catalogo_del_ejemplo())
    assert anclas, "sin entidades sembradas este caso no mide nada"

    job_id, _ = _aprobar_proyectable(
        operador, cola, almacenes, monkeypatch, fuente_proyectable, set(anclas)
    )
    # SELLADO LIMPIO, y desde el Corte 5 eso AFIRMA algo: el acuse sólo es
    # `PLAN_SEALED` a secas cuando NINGUNA relación aprobada se quedó sin
    # proyectar. Si se hubiera quedado alguna, el panel diría
    # `PLAN_SEALED_SIN_PROYECCION` y este caso lo vería.
    assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED"

    operaciones = _operaciones_del_plan(almacenes["base"])
    proyecciones = _proyecciones(operaciones)
    assert proyecciones, (
        "el plan sellado desde la UI no trae ni una `PROJECT_RELATION` pese a "
        "haber leído el grafo. Operaciones: "
        f"{sorted({o.get('operation_type') for o in operaciones})}"
    )

    # EL ANCLA ES LA DEL NODO OBSERVADO, no una plausible.
    for operacion in proyecciones:
        objetivo = operacion["target_entity_id"]
        assert objetivo in anclas, (
            f"la proyección se ancló en {objetivo}, que no está sembrada en el "
            "grafo: el ancla no puede venir de una observación"
        )
        esperada = anclas[objetivo]
        assert operacion["expected_version"] == esperada["version"], operacion
        assert operacion["expected_hash"]["value"] == esperada["state_hash"], (
            "el `expected_hash` del plan no es el del nodo real: el ancla se "
            "derivó en vez de observarse"
        )

    # Y LA RELACIÓN QUEDA NAVEGABLE EN EL GRAFO, con procedencia.
    assert _aviso_de(_aplicar(operador, job_id)) == "PLAN_APPLIED"
    esperadas = {
        (o["payload"]["subject_entity_id"], o["payload"]["object_entity_id"])
        for o in proyecciones
    }
    with grafo.session() as sesion:
        aristas = sesion.run(
            "MATCH (a:V3Entity {workspace: $ws})-[r]->(b:V3Entity {workspace: $ws}) "
            "RETURN a.entity_id AS sujeto, b.entity_id AS objeto, type(r) AS tipo "
            "ORDER BY a.entity_id, b.entity_id",
            ws=workspace,
        ).data()
    assert aristas, "el apply no dejó ninguna arista entre entidades"
    observadas = {(f["sujeto"], f["objeto"]) for f in aristas}
    assert esperadas <= observadas, (
        f"lo proyectado por el plan no está en el grafo: plan={sorted(esperadas)} "
        f"grafo={sorted(observadas)}"
    )

    # LA PROCEDENCIA SIGUE INTACTA: el apply se completó entero, no a medias.
    fila = _filas_de_plan(almacenes["base"])[0]
    assert fila["state"] == "applied", fila["state"]
    assert fila["apply_id"], "un apply sin identidad durable no es auditable"


@neo4j_real
def test_control_con_driver_None_la_relacion_se_cae_POR_NO_OBSERVAR(
    real_app, paneles_on, cola, operador, almacenes, grafo, monkeypatch, caplog,
    fuente_proyectable
):
    """EL CONTROL QUE DECIDE EL CARRIL: el rojo, y POR QUÉ es rojo.

    Mismo montaje exacto que la insignia --mismas entidades sembradas, misma
    fuente, mismo operador, mismo grafo-- y UNA sola mutación: la llamada al
    núcleo vuelve a recibir `driver=None`, que es literalmente el estado del
    producto antes de este corte.

    Lo que se comprueba no es «se puso rojo». Un rojo por credenciales, por el
    gate, por `PLAN_NOT_SEALED` o por una excepción se leería igual y no
    probaría nada. Se comprueba que:

      1. TODO LO DEMÁS SIGUE FUNCIONANDO: la ingesta termina `complete`, la
         propuesta aparece, la aprobación se registra y el sellado responde
         `PLAN_SEALED`. No hay ningún otro fallo que pudiera explicar la
         ausencia.
      2. Lo ÚNICO que desaparece del plan es la `PROJECT_RELATION`.
      3. Y el motivo que el producto declara es EXACTAMENTE
         `PROJECTION_ANCHOR_NOT_OBSERVED`, sin ningún otro código mezclado.
    """
    workspace = "ws-cofradia"
    anclas = _sembrar_entidades(grafo, workspace, _catalogo_del_ejemplo())

    # LA MUTACIÓN. Se envuelve la llamada al núcleo en vez de devolver `None`
    # desde el abridor: así el resto del manejador --incluido el `close()` del
    # bloque `finally`-- se ejerce igual, y lo único que cambia es el argumento
    # bajo estudio. Devolver `None` del abridor rompería el cierre y el caso se
    # pondría rojo por un `AttributeError`, que es el rojo equivocado.
    from jobs.handlers import ingest_v3 as handler_mod

    nucleo = handler_mod.run_ingest

    def sin_observar(*args, **kwargs):
        kwargs["driver"] = None
        return nucleo(*args, **kwargs)

    monkeypatch.setattr(handler_mod, "run_ingest", sin_observar)

    with caplog.at_level("WARNING", logger="panel.v3_apply"):
        job_id, _ = _aprobar_proyectable(
            operador, cola, almacenes, monkeypatch, fuente_proyectable,
            set(anclas),
        )
        # (1) NADA MÁS SE HA ROTO, **Y EL OPERADOR SE ENTERA**.
        #
        # Las dos mitades importan. Que el sellado termine bien descarta que
        # este rojo venga de otro sitio; y que el acuse sea
        # `PLAN_SEALED_SIN_PROYECCION` --y no `PLAN_SEALED` a secas-- es lo que
        # convierte la omisión en algo que una persona ve. Antes del Corte 5
        # esto era un `PLAN_SEALED` limpio con cero proyecciones: cierto y
        # engañoso a la vez.
        assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED_SIN_PROYECCION"

    operaciones = _operaciones_del_plan(almacenes["base"])
    assert operaciones, (
        "el plan sellado salió vacío: entonces la ausencia de proyección no se "
        "distingue de «no había nada que planificar» y el control no mide nada"
    )

    # (2) LO ÚNICO QUE FALTA ES LA PROYECCIÓN.
    assert _proyecciones(operaciones) == [], (
        "con `driver=None` el plan trae una proyección: entonces el ancla se "
        "está dando por observada sin haber mirado el grafo, que es justo lo "
        "que la integridad del apply prohíbe"
    )

    # (3) Y EL MOTIVO ES EL QUE TIENE QUE SER, no otro.
    avisos = [r.getMessage() for r in caplog.records
              if "sin proyeccion" in r.getMessage()]
    assert avisos, (
        "el producto omitió la proyección SIN DECIRLO. Una omisión en silencio "
        f"es el defecto original. Avisos: {[r.getMessage() for r in caplog.records]}"
    )
    codigos = set()
    for aviso in avisos:
        for codigo in ("PROJECTION_ANCHOR_NOT_OBSERVED", "PROJECTION_NO_ANCHOR",
                       "PROJECTION_NEGATED_FACT", "PROJECTION_ENTITY_NOT_IN_GRAPH"):
            if codigo in aviso:
                codigos.add(codigo)
    assert codigos == {"PROJECTION_ANCHOR_NOT_OBSERVED"}, (
        f"el rojo llegó por otro motivo: {sorted(codigos)}. Con las entidades "
        "sembradas en el grafo y el hecho sin negar, el ÚNICO motivo legítimo "
        "de omisión es no haber observado el ancla. Si aparece otro código, "
        "este control no está midiendo lo que dice."
    )


@neo4j_real
def test_el_worker_observa_pero_NO_escribe_durante_la_ingesta(
    real_app, paneles_on, cola, operador, almacenes, grafo, monkeypatch
):
    """LA FRONTERA NUEVA, MEDIDA POR EFECTO: la ingesta lee y no toca nada.

    El worker gana capacidad de LEER el grafo. Que no gane la de escribir no se
    afirma leyendo un comentario ni contando apariciones de `apply=False`: se
    mide comparando el grafo ANTES y DESPUÉS de la ingesta, por identidad
    durable y con una consulta por cosa contada.

    CALIBRACIÓN. El testigo sabe ponerse rojo: sembrar una entidad más entre
    las dos fotos cambia el conjunto y la comparación falla. Por eso la
    afirmación es de igualdad de conjuntos y no «no hubo excepciones».
    """
    workspace = "ws-cofradia"
    _sembrar_entidades(grafo, workspace, _catalogo_del_ejemplo())

    def foto() -> dict:
        with grafo.session() as sesion:
            entidades = sesion.run(
                "MATCH (n:V3Entity {workspace: $ws}) "
                "RETURN n.entity_id AS id, n.version AS v, n.state_hash AS h "
                "ORDER BY n.entity_id", ws=workspace,
            ).data()
            afirmaciones = sesion.run(
                "MATCH (a:V3Assertion {workspace: $ws}) "
                "RETURN a.assertion_id AS id ORDER BY a.assertion_id", ws=workspace,
            ).data()
            aristas = sesion.run(
                "MATCH (:V3Entity {workspace: $ws})-[r]->(:V3Entity {workspace: $ws}) "
                "RETURN count(r) AS n", ws=workspace,
            ).single()["n"]
        return {"entidades": entidades, "afirmaciones": afirmaciones, "aristas": aristas}

    antes = foto()
    assert antes["entidades"], "sin entidades sembradas la foto no compara nada"

    job_id = _ingerir(operador, cola, monkeypatch)
    assert job_id, "la ingesta no llegó a correr"

    despues = foto()
    assert despues == antes, (
        "la ingesta modificó el grafo. La conexión que el Corte 5 abre es de "
        f"SOLO LECTURA. antes={antes} despues={despues}"
    )


# ===========================================================================
# SLICE 2 · CORTE 5 — FALLO CERRADO: SIN GRAFO NO HAY INGESTA
# ===========================================================================
#
# LA REGLA. Desde el Corte 5 la ingesta del panel necesita OBSERVAR el grafo:
# sin driver, el ancla del plan sale con `observed: false` y el sellado omite
# toda proyección. Si el grafo no se puede mirar, el job no se completa en
# silencio con una corrida que parece buena: falla, y dice por qué.
#
# LO QUE ESTOS CASOS IMPIDEN QUE VUELVA. Una «ruta de repuesto» que degradase a
# `driver=None` produciría exactamente el defecto original —una ingesta que
# termina `complete` y cuyo plan no puede proyectar nada— sin un solo error por
# el camino. Aquí se comprueba que no existe.

def _sin_doble(monkeypatch, doble):
    """Devuelve el abridor DE VERDAD a su sitio.

    El módulo instala un grafo de mentira para todos sus casos; estos tres
    vienen precisamente a medir qué pasa cuando no hay grafo, así que con el
    doble puesto no medirían nada.
    """
    from jobs.handlers import ingest_v3 as handler_mod

    monkeypatch.setattr(handler_mod, "_driver_de_observacion", doble.real)


def _ingesta_fallida(operador, cola, monkeypatch) -> dict:
    """Encola desde el panel, corre el worker, y devuelve el job resultante."""
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(EJEMPLOS))
    pantalla = operador.get(SLOT_B.prefix)
    assert pantalla.status_code == 200, pantalla.status_code
    opciones = _opciones(pantalla.text)
    assert opciones, "no se ofrece ninguna fuente que elegir"
    envio = operador.post(
        "/panel/operations/ingestas",
        data={"fuente": opciones[0], "csrf_token": _csrf(operador)},
    )
    assert envio.status_code == 303, envio.text[:300]
    store = jobs_client._load_job_store()
    job_id = store.list_jobs(status="pending", db_path=str(cola))[0]["job_id"]

    from jobs import worker
    worker.run("worker-fallo-cerrado", once=True, limit=1, db_path=str(cola))
    return store.get_job(job_id, db_path=str(cola))


def test_sin_conexion_declarada_la_ingesta_NO_se_completa(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch, _grafo_de_mentira
):
    """No hay grafo declarado -> ERROR con código estable, y NADA ingerido.

    Lo que se mide no es sólo que falle: que el desenlace sea PERMANENTE (el
    worker no lo devuelve a la cola, porque nadie va a declarar la conexión
    entre el primer intento y el tercero) y que el almacén de propuestas se
    quede VACÍO. Una ingesta a medias que dejara propuestas sin observar sería
    el defecto original con otro nombre.
    """
    _sin_doble(monkeypatch, _grafo_de_mentira)
    for variable in ("S9K_NEO4J_URI", "S9K_NEO4J_USER", "S9K_NEO4J_PASSWORD_FILE"):
        monkeypatch.delenv(variable, raising=False)

    job = _ingesta_fallida(operador, cola, monkeypatch)

    assert job["status"] == "failed", job
    assert job["error_message"].startswith("GRAPH_OBSERVATION_UNCONFIGURED:"), (
        f"el operador lee otro motivo: {job['error_message']!r}"
    )
    # NI UNA RUTA NI UN DETALLE TÉCNICO EN LO QUE EL PANEL ENSEÑA.
    assert "/" not in job["error_message"], job["error_message"]
    # NI UNA PROPUESTA. `tmp_path` siempre existe, así que «no hay fichero» se
    # comprueba enumerando el directorio, no preguntando si está.
    escritas = (
        sorted(almacenes["propuestas"].glob("*.json"))
        if almacenes["propuestas"].exists() else []
    )
    assert escritas == [], (
        f"la ingesta falló y aun así dejó propuestas sin observar: {escritas}"
    )


def test_el_codigo_de_grafo_ausente_NO_se_reintenta(monkeypatch):
    """PERMANENTE, y declarado por el handler, no adivinado por el worker.

    `worker.process_one` decide si devuelve el job a la cola consultando
    `exc.retryable`. Aquí se comprueba la declaración de los dos códigos, que
    es lo único que el worker no puede saber por su cuenta: una conexión que
    nadie ha declarado no aparece entre dos intentos; un grafo que no responde
    ahora sí puede responder luego.
    """
    from jobs.handlers.ingest_v3 import IngestV3Error

    assert IngestV3Error("GRAPH_OBSERVATION_UNCONFIGURED").retryable is False
    assert IngestV3Error("GRAPH_OBSERVATION_UNAVAILABLE").retryable is True


def test_una_credencial_legible_por_todos_no_se_usa(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch, tmp_path,
    _grafo_de_mentira
):
    """Un secreto legible por la máquina entera no es un secreto.

    `knowledge_v3.driver_neo4j` rechaza el fichero antes de leerlo, y el
    handler lo trata como defecto de DECLARACIÓN (permanente), no como
    indisponibilidad: unos permisos flojos no se arreglan reintentando.
    """
    _sin_doble(monkeypatch, _grafo_de_mentira)
    fichero = tmp_path / "clave-abierta"
    fichero.write_text("lo-que-sea", encoding="utf-8")
    fichero.chmod(0o644)
    monkeypatch.setenv("S9K_NEO4J_URI", "bolt://127.0.0.1:7687")
    monkeypatch.setenv("S9K_NEO4J_USER", "neo4j")
    monkeypatch.setenv("S9K_NEO4J_PASSWORD_FILE", str(fichero))

    job = _ingesta_fallida(operador, cola, monkeypatch)

    assert job["status"] == "failed", job
    assert job["error_message"].startswith("GRAPH_OBSERVATION_UNCONFIGURED:"), (
        f"un fichero de credencial abierto se está tratando como otra cosa: "
        f"{job['error_message']!r}"
    )


def test_un_grafo_que_no_responde_se_distingue_de_uno_no_declarado(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch, tmp_path,
    _grafo_de_mentira
):
    """DECLARADO pero CAÍDO: otro código, y reintentable.

    Los dos desenlaces acaban en ERROR y para el operador no son lo mismo: uno
    lo arregla quien administra el despliegue y el otro se pasa solo. Un único
    código para los dos convertiría «vuelve a intentarlo» en un consejo falso
    la mitad de las veces.

    La conexión apunta a un puerto libre de loopback: se rechaza de inmediato,
    sin esperas ni red externa.
    """
    _sin_doble(monkeypatch, _grafo_de_mentira)
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]

    fichero = tmp_path / "clave-cerrada"
    fichero.write_text("lo-que-sea", encoding="utf-8")
    fichero.chmod(0o600)
    monkeypatch.setenv("S9K_NEO4J_URI", f"bolt://127.0.0.1:{puerto}")
    monkeypatch.setenv("S9K_NEO4J_USER", "neo4j")
    monkeypatch.setenv("S9K_NEO4J_PASSWORD_FILE", str(fichero))

    job = _ingesta_fallida(operador, cola, monkeypatch)

    assert job["error_message"].startswith("GRAPH_OBSERVATION_UNAVAILABLE:"), (
        f"un grafo declarado y caído no se distingue de uno sin declarar: "
        f"{job['error_message']!r}"
    )


def test_los_codigos_nuevos_los_sabe_pintar_el_panel():
    """Un código que el panel no sabe pintar es un mensaje mudo.

    Misma comprobación cruzada que ya existía para el resto del vocabulario del
    handler, extendida a los dos códigos del Corte 5.
    """
    from app import panel_errors
    from jobs.handlers.ingest_v3 import CODIGOS

    for codigo in ("GRAPH_OBSERVATION_UNCONFIGURED", "GRAPH_OBSERVATION_UNAVAILABLE"):
        assert codigo in CODIGOS, codigo
        assert codigo in panel_errors.CATALOGO, (
            f"{codigo} sale del worker y el panel no tiene frase para él"
        )


def test_una_URI_con_esquema_no_soportado_es_PERMANENTE(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch, tmp_path,
    _grafo_de_mentira
):
    """Un defecto de DECLARACIÓN no se puede disfrazar de indisponibilidad.

    `http://` no es un esquema que el controlador soporte, y nadie lo va a
    corregir entre el primer intento y el tercero. Antes salía
    `GRAPH_OBSERVATION_UNAVAILABLE`, que es REINTENTABLE y cuya frase dice
    «puedes volver a intentarlo cuando el grafo responda»: un consejo falso que
    además gasta los tres intentos del worker mientras la pantalla sigue
    diciendo que el trabajo está en la cola.
    """
    _sin_doble(monkeypatch, _grafo_de_mentira)
    fichero = tmp_path / "clave-esquema"
    fichero.write_text("lo-que-sea", encoding="utf-8")
    fichero.chmod(0o600)
    monkeypatch.setenv("S9K_NEO4J_URI", "http://127.0.0.1:7687")
    monkeypatch.setenv("S9K_NEO4J_USER", "neo4j")
    monkeypatch.setenv("S9K_NEO4J_PASSWORD_FILE", str(fichero))

    job = _ingesta_fallida(operador, cola, monkeypatch)

    assert job["error_message"].startswith("GRAPH_OBSERVATION_UNCONFIGURED:"), (
        f"una URI con esquema no soportado sigue clasificándose mal: "
        f"{job['error_message']!r}"
    )


def test_una_credencial_rechazada_por_el_servidor_es_PERMANENTE(monkeypatch):
    """Usuario o contraseña que el servidor rechaza: el grafo responde BIEN.

    Lo que está mal es lo declarado, así que reintentar no lo arregla. Se mide
    sobre el clasificador y por CLASE de excepción --no por el texto del
    mensaje, que cambia entre versiones del controlador-- que es exactamente
    como lo decide el producto.
    """
    from neo4j.exceptions import AuthError, ConfigurationError, ServiceUnavailable

    from jobs.handlers import ingest_v3

    assert ingest_v3._clasificar(AuthError("credencial rechazada")) == \
        "GRAPH_OBSERVATION_UNCONFIGURED"
    assert ingest_v3._clasificar(ConfigurationError("esquema raro")) == \
        "GRAPH_OBSERVATION_UNCONFIGURED"
    # EL CONTROL POSITIVO: lo que SÍ es transitorio se queda reintentable.
    # Sin esto, clasificarlo TODO como permanente pasaría igual de verde.
    assert ingest_v3._clasificar(ServiceUnavailable("el grafo no responde")) == \
        "GRAPH_OBSERVATION_UNAVAILABLE"
    assert ingest_v3._clasificar(RuntimeError("cualquier otra cosa")) == \
        "GRAPH_OBSERVATION_UNAVAILABLE"


# ===========================================================================
# EL AVISO DE LA OMISIÓN, PINTADO — la mitad de (d) que mira al operador
# ===========================================================================
#
# POR QUÉ ESTE BLOQUE EXISTE, Y POR QUÉ ES EL MISMO ERROR DOS VECES.
#
# El Corte 5 hace que el sellado con relaciones omitidas responda
# `PLAN_SEALED_SIN_PROYECCION` en vez de `PLAN_SEALED`. Todos los casos de
# arriba comprueban ese código **en el parámetro de la redirección**, y ni uno
# pide la página. Medido: retirando `PLAN_SEALED_SIN_PROYECCION` de
# `ACUSES_DE_EXITO`, `_aviso()` devuelve `None` --el código deja de estar en el
# catálogo de éxitos y tampoco está en `panel_errors.CATALOGO`--, **el bloque
# del aviso desaparece entero de la pantalla**, el operador vuelve al éxito
# mudo exacto que este corte viene a cerrar, y la suite del visor seguía en
# VERDE e idéntica al baseline.
#
# Es la misma forma de falso verde que ya se cerró en la pantalla de resultado
# (`test_resultado_procedencia.py`): afirmar la PROPIEDAD y no el HTML. Aquí se
# cierra en la superficie que de verdad avisa al operador.

def _pantalla_operaciones(operador, job_id: str, aviso: str) -> str:
    """La pantalla de Operaciones tal y como la deja el 303 del sellado.

    Se pide el MISMO GET al que el POST redirige --mismo `solicitado`, mismo
    `aviso`-- en vez de seguir la redirección, porque el cliente del arnés no
    la sigue. Lo que se mira es el HTML servido, no el destino del `Location`.
    """
    r = operador.get(f"{SLOT_B.prefix}?solicitado={job_id}&aviso={aviso}")
    assert r.status_code == 200, r.status_code
    return r.text


def _bloque_aviso(html: str) -> str:
    """El bloque del acuse, o cadena vacía si la pantalla no pinta ninguno."""
    hallazgo = re.search(r'<section[^>]*data-role="aviso".*?</section>', html, re.S)
    return hallazgo.group(0) if hallazgo else ""


def test_la_pantalla_AVISA_de_que_alguna_relacion_no_se_anadira(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch,
    _grafo_de_mentira
):
    """EL TESTIGO QUE FALTABA. El aviso tiene que estar en el HTML.

    Recorrido real: se ingiere desde el panel, se aprueba una propuesta que no
    puede proyectar, se sella con el formulario real, y **se pide la pantalla**
    con el acuse que el sellado dejó en la URL.

    Lo que se afirma no es el código en el `Location` --eso ya lo miden los
    casos de arriba-- sino que el operador **lee una advertencia**: el bloque
    del acuse existe, lleva ese código, y su texto dice que algo aprobado no se
    va a añadir.
    """
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    respuesta = _sellar(operador, job_id)
    aviso = _aviso_de(respuesta)
    assert aviso == SELLADO_DEL_ARNES, aviso

    bloque = _bloque_aviso(_pantalla_operaciones(operador, job_id, aviso))

    assert bloque, (
        "la pantalla no pinta NINGÚN bloque de acuse para "
        f"{SELLADO_DEL_ARNES}. El operador recibe un éxito mudo: sellado, cero "
        "relaciones añadidas y ni una palabra. Es EL defecto que este corte "
        "cierra."
    )
    assert f'data-aviso-code="{SELLADO_DEL_ARNES}"' in bloque, bloque[:300]
    # Y DICE LO QUE HA PASADO, no sólo que algo pasó. Se comprueba el fondo del
    # mensaje --que algo aprobado NO se va a añadir-- y no la frase literal,
    # que se puede reescribir sin que el defecto vuelva.
    assert "no se va a añadir" in bloque, bloque[:400]
    assert "relaciones" in bloque, bloque[:400]


def test_el_sellado_limpio_NO_asusta_al_operador(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch,
    _grafo_de_mentira
):
    """CONTROL POSITIVO del anterior: la pantalla sabe decir las dos cosas.

    Sin éste, pintar SIEMPRE la advertencia --incluso cuando no falta nada--
    pasaría igual de verde, y el aviso se volvería ruido que el operador
    aprende a ignorar. Que es otra forma de no avisar.

    `PLAN_SEALED` se pide directamente: es un acuse del catálogo cerrado y la
    pantalla lo valida contra él, así que no hace falta fabricar una corrida
    que selle limpio para comprobar qué pinta con ese código.
    """
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    _sellar(operador, job_id)

    bloque = _bloque_aviso(_pantalla_operaciones(operador, job_id, "PLAN_SEALED"))

    assert bloque, "la pantalla tampoco pinta el acuse limpio"
    assert 'data-aviso-code="PLAN_SEALED"' in bloque, bloque[:300]
    assert "no se va a añadir" not in bloque, (
        "el sellado LIMPIO está avisando de relaciones que no se añaden: un "
        "aviso que sale siempre es un aviso que nadie lee"
    )


# ===========================================================================
# SLICE 2 · CORTE 3 — DE «APLICADO» A LO QUE REALMENTE SE APLICÓ
#
# EL DEFECTO, MEDIDO sobre el HTML real que servía `/panel/operations` con un
# plan en `applied`, antes de este corte:
#
#     data-plan-desenlace  ['applied']
#     <a href=...>         []          <-- CERO enlaces en todo el bloque
#
# La operación terminaba, la pantalla decía «ya forma parte del conocimiento»
# y ahí se acababa el producto. Para ver QUÉ se escribió, de dónde venía y con
# qué evidencia había que salir a la línea de comandos o a Neo4j Browser.
#
# LO QUE NO SE CONSTRUYE AQUÍ. La pantalla de resultado (`/panel/resultado`) y
# la de evidencia ya existían, montadas y con su autorización; el `apply_id`
# ya estaba en la fila de `sealed_plans`. El corte PUBLICA EL CAMINO; no
# inventa una consulta al grafo, no toca el writer y no añade ninguna ACL.
#
# EN QUÉ CAPA MIDE CADA CASO, dicho y no presupuesto:
#
#   * capa «usable desde el producto» — los casos de esta sección sin marca
#     corren siempre: piden el HTML real, enumeran lo que el bloque ofrece y
#     comprueban que la identidad enlazada es EXACTAMENTE la que el almacén
#     registró. No necesitan grafo para ser ciertos, y no lo fingen.
#   * capa «ejercida contra infra real» — el caso `neo4j_real` recorre el
#     camino entero: aplica de verdad, SIGUE el enlace y comprueba que la
#     pantalla de destino responde y enseña lo que esa ejecución escribió.
#     Sin `S9K_WRITER_NEO4J_REAL=1` se OMITE, y omitido no es verde.
# ===========================================================================

#: La forma que el producto exige a un `apply_id` (`writer/apply_identity.py`).
#: Se escribe aquí con un dígito distinto en cada caso para que dos ejecuciones
#: del arnés NO compartan identidad: si las compartieran, un enlace cruzado
#: —el defecto de atribución que este corte tiene que impedir— se vería igual
#: de bien que uno correcto.
def _identidad_de_apply(semilla: str) -> str:
    return "apply:" + (semilla * 32)[:32]


#: La pantalla de destino está APAGADA por defecto (`S9K_PANEL_RESULTADO_ENABLED`).
FLAG_RESULTADO = "S9K_PANEL_RESULTADO_ENABLED"


@pytest.fixture
def resultado_on(monkeypatch):
    """La pantalla de destino, SERVIDA. Se enciende explícitamente.

    No se mete en `paneles_on`: que el destino esté apagado es un estado
    legítimo del despliegue y hay un caso que lo mide. Si estuviera siempre
    encendido, ese caso no podría existir.
    """
    monkeypatch.setenv(FLAG_RESULTADO, "true")


def _aplicar_en_el_almacen(almacenes, *, apply_id, complete=True, notes=None):
    """Lleva el plan a `applied`/`partial` POR EL CAMINO DEL PRODUCTO.

    `claim_for_apply` + `record_apply_result` son los dos únicos sitios del
    producto que mueven ese estado; el apply real los llama a ellos. Escribir
    el `UPDATE` a mano aquí mediría una fila que el producto no sabe producir.

    Esto NO sustituye al caso con grafo: deja el ALMACÉN como lo dejaría un
    apply, que es lo que la pantalla lee, y por eso sirve para medir la
    pantalla. Lo que no mide —y no dice medir— es que el conocimiento esté
    materializado; de eso se ocupa el caso `neo4j_real` de más abajo.
    """
    from app.services.v3_review import ReviewService

    fila = _fila_de_plan(almacenes["base"])
    store = ReviewService().store
    reserva = store.claim_for_apply(plan_id=fila["plan_id"], now="2026-01-01T00:00:00Z")
    assert reserva["claimed"], (
        "el plan no se dejó reservar: el caso no llega a medir ningún desenlace"
    )
    store.record_apply_result(
        plan_id=fila["plan_id"], apply_id=apply_id, ok=True,
        now="2026-01-01T00:00:01Z", applied_operations=1,
        notes=list(notes or ["APPLY_PROVENANCE_PERSISTED"]), complete=complete,
    )
    return _fila_de_plan(almacenes["base"])


def _camino(bloque: dict) -> dict:
    """Lo que el bloque ofrece COMO CAMINO. Enumerado del marcado real.

    Devuelve el código del desenlace del camino y los `href` que el bloque
    contiene. Los `href` se leen de TODO el bloque, no sólo del párrafo
    esperado: así un enlace que apareciera donde no debe también se ve.
    """
    texto = bloque.get("texto", "")
    codigos = re.findall(r'data-plan-resultado="([^"]*)"', texto)
    enlaces = re.findall(r'<a [^>]*href="([^"]*)"', texto)
    return {"codigos": codigos, "enlaces": enlaces, "texto": texto}


def _primer_enlace(camino: dict) -> str:
    """El enlace del camino, o un ROJO QUE DICE SU CAUSA.

    Sin esto, un bloque sin enlaces se cae con un `IndexError` pelado, y un
    rojo que no dice por qué se lee igual que una avería del arnés. La
    calibración de este corte exige lo contrario: cada rojo nombra el defecto
    que lo produce.
    """
    assert camino["enlaces"], (
        "el bloque del plan no publica NINGÚN enlace, así que desde «aplicado» "
        "no se puede llegar a lo que se aplicó; desenlace del camino "
        f"pintado: {camino['codigos']}"
    )
    return camino["enlaces"][0]


def _vista_aplicada(operador, cola, almacenes, monkeypatch, *, apply_id,
                    complete=True):
    """Aprobar -> sellar -> dejar el almacén aplicado -> PEDIR LA PANTALLA."""
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES
    fila = _aplicar_en_el_almacen(almacenes, apply_id=apply_id, complete=complete)
    bloque = _bloque_plan(_panel(operador, job_id))
    assert bloque, "la pantalla no pinta el bloque del plan: no se mide nada"
    return job_id, fila, bloque


# ---------------------------------------------------------------------------
# EL CASO QUE FIJA EL DEFECTO: desde «aplicado» HAY camino, y es EL SUYO
# ---------------------------------------------------------------------------

def test_desde_aplicado_la_pantalla_OFRECE_el_camino_a_lo_aplicado(
    real_app, paneles_on, resultado_on, cola, operador, almacenes, monkeypatch
):
    """El acuse de «aplicado» deja de ser un callejón sin salida.

    Se pide el HTML REAL y se enumera el bloque. Lo que se afirma no es «hay
    un enlace» —cualquier enlace pondría eso verde— sino que el enlace apunta
    a la pantalla de resultado CON LA IDENTIDAD DURABLE QUE EL ALMACÉN
    REGISTRÓ. Identidad contra identidad: un `apply_id` plausible pero distinto
    llevaría al operador al resultado de otra ejecución, y eso es fabricar
    procedencia.
    """
    identidad = _identidad_de_apply("b")
    _, fila, bloque = _vista_aplicada(
        operador, cola, almacenes, monkeypatch, apply_id=identidad)

    assert bloque["atributos"]["estado"] == "applied", bloque["atributos"]
    camino = _camino(bloque)
    assert camino["codigos"] == ["disponible"], (
        "desde «aplicado» la pantalla no ofrece camino a lo aplicado: el "
        f"desenlace del camino es {camino['codigos']}"
    )
    assert camino["enlaces"], (
        "el bloque dice que hay camino y no publica ningún enlace: el operador "
        "sigue sin poder llegar a lo que se escribió"
    )
    destino = _primer_enlace(camino)

    # LA IDENTIDAD, contra la del almacén. No contra una cadena escrita aquí.
    assert fila["apply_id"] == identidad, fila["apply_id"]
    assert identidad in destino, (
        f"el enlace no lleva la identidad de ESTA ejecución: destino={destino} "
        f"identidad registrada={fila['apply_id']}"
    )
    # Y el ÁMBITO, sin el cual el destino caería al workspace por defecto y
    # enseñaría —o negaría— una ejecución que no es ésta.
    assert f"workspace={fila['workspace']}" in destino, (
        "el enlace no lleva el ámbito de la ejecución, así que el destino caerá "
        "al workspace por defecto del despliegue y enseñará —o negará— una "
        f"ejecución que no es ésta: destino={destino}")
    assert 'data-role="ver-lo-aplicado"' in camino["texto"]


def test_el_enlace_resuelve_a_la_pantalla_de_resultado_y_esta_responde(
    real_app, paneles_on, resultado_on, cola, operador, almacenes, monkeypatch
):
    """El enlace se SIGUE, y el destino es la pantalla de resultado.

    QUÉ MIDE Y QUÉ NO. Mide que el `href` publicado es una ruta REAL de esta
    app —resuelve al endpoint `resultado_de_ejecucion` con ESTE `apply_id`— y
    que al pedirla NO se responde con el 404 del interruptor apagado ni con un
    error del servidor. NO mide que la pantalla enseñe conocimiento: sin grafo
    no hay nada que enseñar, y afirmar lo contrario sería el falso verde que
    este programa persigue. Eso lo mide el caso `neo4j_real`.
    """
    identidad = _identidad_de_apply("c")
    _, _, bloque = _vista_aplicada(
        operador, cola, almacenes, monkeypatch, apply_id=identidad)
    destino = _primer_enlace(_camino(bloque))

    # RESUELVE, y resuelve a ESE endpoint. `route_index` da el patrón; aquí se
    # comprueba que la ruta pedida es la de esa pantalla y no otra parecida.
    from urllib.parse import urlsplit

    from app.routers.resultado import PREFIJO, RUTA_RESULTADO
    esperado = real_app.url_path_for(RUTA_RESULTADO, apply_id=identidad)
    camino_del_enlace = urlsplit(destino).path
    assert camino_del_enlace == esperado, (
        "el enlace del acuse no es la ruta de la pantalla de resultado para "
        f"ESTA ejecución: publicado={camino_del_enlace} esperado={esperado}")
    assert camino_del_enlace.startswith(PREFIJO), (
        f"el enlace sale del espacio de la pantalla de resultado: {destino}")

    respuesta = operador.get(destino)
    assert respuesta.status_code != 500, respuesta.text[:300]
    assert respuesta.status_code != 302, (
        "el enlace lleva a un login: el rol que puede aplicar no puede ver lo "
        "que aplicó"
    )
    # 404 aquí sería el `RESULT_NOT_FOUND` legítimo (no hay grafo), NO el del
    # interruptor: eso se distingue porque el interruptor está encendido y el
    # caso de apagado, abajo, mide la otra mitad.
    assert respuesta.status_code in (200, 404, 503), respuesta.status_code


# ---------------------------------------------------------------------------
# CONTROLES NEGATIVOS EN LAS DOS DIRECCIONES
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("estado_esperado", ["sealed"])
def test_sin_haber_escrito_NO_se_ofrece_camino_a_lo_aplicado(
    real_app, paneles_on, resultado_on, cola, operador, almacenes, monkeypatch,
    estado_esperado,
):
    """LA OTRA DIRECCIÓN. Un plan sellado no ha escrito nada todavía.

    El arreglo podía derivar a ofrecer el camino siempre que hubiera plan. Un
    enlace a «lo que se aplicó» sobre algo que no se ha aplicado afirma una
    escritura que no ocurrió — la misma clase de falso éxito que este módulo
    lleva cerrando desde B2.
    """
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES
    bloque = _bloque_plan(_panel(operador, job_id))
    assert bloque["atributos"]["estado"] == estado_esperado, bloque["atributos"]

    camino = _camino(bloque)
    assert camino["codigos"] == [], (
        "la pantalla ofrece un camino a «lo aplicado» sobre un plan que NO se "
        f"ha aplicado: {camino['codigos']}"
    )
    assert "ver-lo-aplicado" not in camino["texto"], (
        "hay un enlace a lo aplicado sin que se haya aplicado nada"
    )


def test_en_vuelo_NO_se_ofrece_camino_porque_NO_SE_SABE_como_termino(
    real_app, paneles_on, resultado_on, cola, operador, almacenes, monkeypatch
):
    """`applying`: apply RESERVADO y SIN desenlace conocido.

    Ofrecer aquí el camino a «lo que se aplicó» contradiría, en la misma
    pantalla, al párrafo de arriba que dice que no consta cómo terminó.

    QUÉ CUBRE HOY ESTE CASO, DICHO CON PRECISIÓN. Se MIDIÓ: `claim_for_apply`
    no estampa la identidad —la pone `record_apply_result`, y sólo con
    desenlace—, así que en `applying` la columna está a NULL y el camino se
    cierra por AUSENCIA DE IDENTIDAD, no por la guarda de estado. Las dos
    guardas están, y este caso no distingue cuál actúa. No es cobertura
    regalada y tampoco se presenta como más de lo que es: fija el
    COMPORTAMIENTO visible —en vuelo no hay camino— contra el día en que la
    reserva estampe la identidad por adelantado, que es cuando la guarda de
    estado pasará a ser la única que lo impide.
    """
    from app.services.v3_review import ReviewService

    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES
    fila = _fila_de_plan(almacenes["base"])
    ReviewService().store.claim_for_apply(
        plan_id=fila["plan_id"], now="2026-01-01T00:00:00Z")

    bloque = _bloque_plan(_panel(operador, job_id))
    assert bloque["atributos"]["estado"] == "applying", bloque["atributos"]
    assert "applying" in bloque["desenlace"], bloque["desenlace"]
    camino = _camino(bloque)
    assert camino["codigos"] == [], (
        "con el apply EN VUELO la pantalla ofrece camino a lo aplicado: eso "
        f"afirma un desenlace que ella misma dice no conocer ({camino['codigos']})"
    )


def test_escrito_y_sin_identidad_durable_se_dice_AUSENTE_y_no_se_calla(
    real_app, paneles_on, resultado_on, cola, operador, almacenes, monkeypatch
):
    """AUSENCIA != CERO, y tampoco silencio.

    Una fila `applied` cuya columna de identidad no tiene forma de `apply_id`
    es un apply del que SÍ hay conocimiento escrito y al que este producto no
    sabe llevar. Las dos salidas fáciles son falsas: enlazar igualmente (a un
    identificador que no existe) y no decir nada (que se lee como «no hay nada
    que ver»). La pantalla lo NOMBRA.
    """
    _, fila, bloque = _vista_aplicada(
        operador, cola, almacenes, monkeypatch, apply_id="no-es-un-apply-id")

    assert fila["state"] == "applied", fila["state"]
    assert fila["apply_id"] == "no-es-un-apply-id", fila["apply_id"]
    camino = _camino(bloque)
    assert camino["codigos"] == ["sin_identidad"], (
        "un apply escrito sin identidad durable no se está nombrando como "
        f"ausencia: {camino['codigos']}"
    )
    assert not camino["enlaces"], (
        "se publica un enlace construido sobre una identidad que no tiene "
        f"forma de apply_id: {camino['enlaces']}"
    )
    # Y la cadena inválida NO se publica: sería material del almacén en la UI.
    assert "no-es-un-apply-id" not in bloque["texto"]


def test_con_la_pantalla_de_destino_APAGADA_se_dice_y_no_se_ofrece_un_404(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """NI HABILITAR NI FINGIR, la regla de los botones de este panel.

    Sin `resultado_on` la pantalla de destino no se sirve. Ofrecer el enlace
    igualmente daría un 404 con la pinta de un camino que existe; callarse
    diría que no hay nada. Se nombra la situación.
    """
    monkeypatch.delenv(FLAG_RESULTADO, raising=False)
    _, fila, bloque = _vista_aplicada(
        operador, cola, almacenes, monkeypatch,
        apply_id=_identidad_de_apply("d"))

    assert fila["state"] == "applied", fila["state"]
    camino = _camino(bloque)
    assert camino["codigos"] == ["apagado"], (
        "con la pantalla de resultado apagada el panel no lo dice: "
        f"{camino['codigos']}"
    )
    assert not camino["enlaces"], (
        "se ofrece un enlace a una pantalla que este despliegue no sirve"
    )
    # Y la identidad TAMPOCO se publica: no hay a dónde ir con ella.
    assert fila["apply_id"] not in bloque["texto"], (
        "se publica la identidad de la ejecución sin ofrecer camino: material "
        "del almacén en pantalla sin ninguna razón"
    )


def test_el_desenlace_PARCIAL_tambien_ofrece_el_camino(
    real_app, paneles_on, resultado_on, cola, operador, almacenes, monkeypatch
):
    """`partial` ES escritura: hay conocimiento nuevo al que llegar.

    Región que el corpus no alcanzaría sola, cubierta a propósito. Dejar
    `partial` sin camino sería precisamente el peor caso: un apply incompleto
    es cuando MÁS falta hace poder mirar qué quedó escrito.
    """
    identidad = _identidad_de_apply("e")
    _, fila, bloque = _vista_aplicada(
        operador, cola, almacenes, monkeypatch, apply_id=identidad,
        complete=False)

    assert fila["state"] == "partial", fila["state"]
    assert "partial" in bloque["desenlace"], bloque["desenlace"]
    camino = _camino(bloque)
    assert camino["codigos"] == ["disponible"], (
        "un apply PARCIAL no ofrece camino a lo que si quedo escrito: "
        f"{camino['codigos']}")
    assert identidad in _primer_enlace(camino), (
        "el camino del desenlace PARCIAL no lleva la identidad de esta "
        f"ejecución: {camino['enlaces']}")


def test_los_CUATRO_desenlaces_del_camino_estan_declarados_y_pintados():
    """Un vocabulario cerrado que la pantalla sepa pintar ENTERO.

    Se enumera contra la plantilla, no contra el código: un código nuevo que
    el visor no supiera traducir saldría en blanco, y un desenlace mudo se lee
    como «no hay nada». `no_procede` es el único que NO se pinta a propósito
    —no hay escritura de la que hablar— y se afirma que no se pinta.
    """
    from app.routers.chassis_operations import CAMINOS_AL_RESULTADO

    ruta = (Path(__file__).resolve().parents[1] / "app" / "templates" /
            "chassis" / "operations.html")
    marcado = re.sub(r"\{#.*?#\}", "", ruta.read_text(encoding="utf-8"), flags=re.S)
    pintados = set(re.findall(r"plan\.resultado == '([a-z_]+)'", marcado))

    assert set(CAMINOS_AL_RESULTADO) == {"no_procede", "disponible",
                                         "sin_identidad", "apagado"}
    assert pintados == set(CAMINOS_AL_RESULTADO) - {"no_procede"}, (
        f"hay desenlaces del camino que la pantalla no sabe pintar: "
        f"{set(CAMINOS_AL_RESULTADO) - {'no_procede'} - pintados}"
    )


def test_ningun_desenlace_del_camino_escapa_al_vocabulario_declarado():
    """Por AST, no contando texto: ningún código sale del vocabulario cerrado.

    Este control existe porque el defecto ya se cometió en este mismo corte:
    la rama de «almacén no consultable» devolvía un QUINTO código propio
    (`sin_escritura`) que la plantilla no sabía pintar. La consecuencia no es
    una excepción —Jinja no falla— sino un párrafo que no sale: el desenlace
    se queda MUDO, y un desenlace mudo se lee como «no hay nada que ver».

    Se PARSEA el módulo y se leen los valores literales asignados a la clave
    `resultado` en los diccionarios que el router construye. Contar
    apariciones de las cadenas daría un falso negativo en cuanto alguien
    escribiera el código en una variable; esto ve la estructura.
    """
    import ast

    from app.routers import chassis_operations as panel_ops

    ruta = Path(panel_ops.__file__)
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    emitidos = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Dict):
            continue
        for clave, valor in zip(nodo.keys, nodo.values):
            if (isinstance(clave, ast.Constant) and clave.value == "resultado"
                    and isinstance(valor, ast.Constant)):
                emitidos.add(valor.value)

    assert emitidos, (
        "el análisis no encontró NINGÚN desenlace del camino en el router: el "
        "instrumento ha dejado de ver lo que dice mirar, y un verde así no "
        "cubre nada"
    )
    fuera = emitidos - set(panel_ops.CAMINOS_AL_RESULTADO)
    assert not fuera, (
        "el router emite desenlaces del camino que NO están en el vocabulario "
        f"declarado, así que la pantalla no sabrá pintarlos: {sorted(fuera)}"
    )


def test_el_camino_no_publica_conocimiento_interno_nuevo(
    real_app, paneles_on, resultado_on, cola, operador, almacenes, monkeypatch
):
    """Repositorio PÚBLICO. El enlace no puede ser una rendija.

    Mismo censo que el caso de la sección 6, aplicado al HTML que ahora lleva
    un enlace nuevo: el `plan_id`, el `plan_hash`, el `snapshot_id`, el
    `source_asset_id` y las rutas del servidor siguen sin aparecer.
    """
    _, fila, bloque = _vista_aplicada(
        operador, cola, almacenes, monkeypatch,
        apply_id=_identidad_de_apply("f"))
    documento = json.loads(fila["plan_json"])
    html = bloque["texto"]

    prohibidas = {
        "plan_id": fila["plan_id"],
        "plan_hash": fila["plan_hash"],
        "snapshot_id": documento["snapshot_id"],
        "source_asset_id": documento["source_asset_id"],
        "ruta del almacén": str(almacenes["propuestas"]),
        "ruta de la base": str(almacenes["base"]),
    }
    filtradas = {k: v for k, v in prohibidas.items() if v and v in html}
    assert not filtradas, f"el camino publica material interno: {filtradas}"
    for palabra in ("Traceback", "sqlite3", "neo4j://", "bolt://"):
        assert palabra not in html, f"el camino publica «{palabra}»"


def test_el_enlace_no_concede_nada_a_quien_no_puede_ver_el_resultado(
    real_app, auth_on, paneles_on, resultado_on, cola, operador, almacenes,
    monkeypatch
):
    """PERMISOS EN EL BACKEND, no en el marcado.

    Se construye el enlace desde el panel del ADMIN y se SIGUE con un cliente
    que no tiene rol para la pantalla de destino. Si la autorización viviera
    en el frontend —en no pintar el enlace— esta petición devolvería
    contenido. La guarda del destino es la misma que ya existía; aquí se
    comprueba que este corte no la ha esquivado.
    """
    _, _, bloque = _vista_aplicada(
        operador, cola, almacenes, monkeypatch,
        apply_id=_identidad_de_apply("a"))
    destino = _primer_enlace(_camino(bloque))

    miron = _cliente(real_app, _cookie(auth_on, "apply_miron", "viewer"))
    respuesta = miron.get(destino)
    assert respuesta.status_code in (302, 403), (
        "el backend NO deniega a un rol insuficiente que sigue el enlace del "
        f"panel: respondió {respuesta.status_code}. CALIBRADO: relajar la "
        "guarda del destino produce aquí un 404 —el rol pasa y sólo lo para la "
        "ausencia de contenido—, y un 404 no es una autorización: el día que "
        "hubiera contenido, ese mismo camino lo entregaría"
    )
    anonimo = TestClient(real_app, raise_server_exceptions=False,
                         follow_redirects=False)
    anonimo.headers.update({"accept": "text/html"})
    assert anonimo.get(destino).status_code == 302, (
        "un anónimo entra en la pantalla de resultado por el enlace del panel"
    )


# ---------------------------------------------------------------------------
# CAPA 3 — EJERCIDO CONTRA INFRA REAL
#
# Aquí se intentó cerrar la propiedad de punta a punta y NO se pudo. Lo que
# sigue son las dos mitades honestas de esa medición: lo que SÍ quedó
# comprobado contra un grafo de verdad, y el BLOQUEO que lo impide, fijado por
# su CAUSA para que no se pueda olvidar ni leer como si no existiera.
# ---------------------------------------------------------------------------

@pytest.fixture
def visor_sobre_el_grafo(real_app, grafo_real):
    """El VISOR leyendo el MISMO grafo en el que se acaba de aplicar.

    El resto de este módulo no lo necesita —mide la cola, el almacén y lo que
    el writer dejó, y comprueba el grafo con Cypher propio—, así que la app
    servía el proveedor por defecto y la pantalla de resultado no tenía de
    dónde leer. Sin esto, cualquier medición del destino habría sido un rojo
    del arnés disfrazado de defecto del producto.

    Se sustituye el proveedor BASE y no el filtrado, así que la cadena entera
    de autorización (`get_filtered_provider` -> `PolicyFilteredProvider` ->
    `VisibilityPolicy`) se atraviesa en cada petición: este arnés no relaja ni
    una regla, sólo conecta el visor a la fuente.
    """
    import app.deps as deps
    from app.providers.neo4j_provider import Neo4jGraphProvider

    proveedor = Neo4jGraphProvider(
        grafo_real["uri"], grafo_real["user"], grafo_real["password"])
    real_app.dependency_overrides[deps.get_provider] = lambda: proveedor
    yield proveedor
    real_app.dependency_overrides.pop(deps.get_provider, None)
    proveedor._driver.close()


@neo4j_real
def test_tras_un_apply_REAL_el_acuse_ofrece_el_camino_con_su_identidad(
    real_app, paneles_on, resultado_on, cola, operador, almacenes, grafo,
    visor_sobre_el_grafo, monkeypatch
):
    """LO QUE SÍ CIERRA ESTE CORTE, ejercido contra un grafo de verdad.

    fuente -> ingesta -> revisión -> aprobar -> sellar -> APLICAR DE VERDAD ->
    el acuse de «aplicado» OFRECE el camino, y lo ofrece con la identidad
    durable que el almacén registró para ESA ejecución.

    Todo por HTTP. Lo que NO afirma este caso es que el destino entregue el
    contenido: eso se midió, no se cumple hoy, y tiene su propio caso abajo.
    """
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES
    assert _aviso_de(_aplicar(operador, job_id)) == "PLAN_APPLIED"

    fila = _fila_de_plan(almacenes["base"])
    assert fila["state"] == "applied", fila["state"]
    assert fila["apply_id"], "sin identidad durable no hay nada que enlazar"

    bloque = _bloque_plan(_panel(operador, job_id))
    camino = _camino(bloque)
    assert camino["codigos"] == ["disponible"], (
        "tras un apply REAL el acuse no ofrece camino a lo aplicado: "
        f"{camino['codigos']}")
    destino = _primer_enlace(camino)
    assert fila["apply_id"] in destino, (
        "el enlace no lleva la identidad durable que el almacén registró para "
        f"este apply: destino={destino} registrada={fila['apply_id']}")

    # Y la identidad enlazada es la que el GRAFO tiene marcada, no sólo la que
    # el almacén anotó. Las dos autoridades, y coinciden.
    with grafo.session() as sesion:
        marcadas = [f["aid"] for f in sesion.run(
            "MATCH (o:V3AppliedOperation {workspace: $ws}) "
            "RETURN DISTINCT o.apply_id AS aid", ws="ws-cofradia")]
    assert marcadas == [fila["apply_id"]], (
        "la identidad que el panel enlaza no es la que el grafo tiene marcada: "
        f"enlazada={fila['apply_id']} en el grafo={marcadas}")


@neo4j_real
def test_BLOQUEO_el_destino_niega_el_apply_que_acaba_de_ocurrir(
    real_app, paneles_on, resultado_on, cola, operador, almacenes, grafo,
    visor_sobre_el_grafo, monkeypatch
):
    """EL BLOQUEO, MEDIDO Y FIJADO POR SU CAUSA. No cierra la propiedad.

    Este caso NO celebra un comportamiento: lo DENUNCIA. Se aplica de verdad,
    se sigue el enlace que el panel publica —el correcto, con la identidad
    correcta— y la pantalla de destino responde **404 RESULT_NOT_FOUND** sobre
    la ejecución que acaba de ocurrir.

    LA CAUSA, MEDIDA y no supuesta:

        etiquetas en el grafo tras el apply REAL
            V3AppliedOperation 1 · V3Assertion 1 · V3Episode 4
            V3Evidence 4 · V3Source 1 · **Entity 0**

        reader.operations_of_apply(ws, apply_id)   -> 1 fila (el apply ESTÁ)
        provider.workspaces()                      -> []   (el ámbito NO)

    `resultado_de_apply` comprueba el ÁMBITO antes que nada, y
    `Neo4jGraphProvider.workspaces()` deriva la lista de nodos `:Entity` con
    `entity_id`. El writer V3 de este recorrido no escribe ni un `:Entity`, así
    que el workspace donde SÍ hay conocimiento nuevo no aparece en la lista y
    la pantalla lo niega. La ausencia de entidades se convierte en ausencia de
    ámbito, y la ausencia de ámbito en «no existe».

    POR QUÉ NO SE ARREGLA AQUÍ. Tocarlo es tocar la SEMÁNTICA DE AUTORIZACIÓN
    del visor —de dónde sale el ámbito de un lector—, que es contrato
    congelado, y hacerlo desde este corte sería abrir por mi cuenta un frente
    que no me toca. Queda elevado con esta evidencia.

    POR QUÉ ES UNA PRUEBA Y NO UN COMENTARIO. Un párrafo en un informe no se
    entera de nada. Esto se pone ROJO el día que el bloqueo se levante —o el
    día que la causa cambie por otra— y obliga a releerlo y a promover el caso
    de arriba a la propiedad entera. Un `skip` aquí sería un verde sin haber
    mirado.
    """
    from app.providers.provenance_reader import reader_for

    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == SELLADO_DEL_ARNES
    assert _aviso_de(_aplicar(operador, job_id)) == "PLAN_APPLIED"
    fila = _fila_de_plan(almacenes["base"])
    destino = _primer_enlace(_camino(_bloque_plan(_panel(operador, job_id))))

    # 1. EL APPLY ESTÁ, y el lector de procedencia lo alcanza sin problemas.
    lector = reader_for(visor_sobre_el_grafo)
    assert lector is not None, (
        "no hay lector de procedencia: el arnés no está conectado al grafo y "
        "este caso no mediría el bloqueo sino su propio cableado")
    operaciones = lector.operations_of_apply("ws-cofradia", fila["apply_id"])
    assert operaciones, (
        "el apply no dejó marca alcanzable: entonces el 404 de abajo sería "
        "legítimo y este caso estaría midiendo otra cosa")

    # 2. Y AUN ASÍ EL ÁMBITO NO EXISTE PARA EL LECTOR. Ésta es la causa.
    ambitos = list(visor_sobre_el_grafo.workspaces() or ())
    assert "ws-cofradia" not in ambitos, (
        "EL BLOQUEO SE HA LEVANTADO: el workspace del apply ya aparece en el "
        f"ámbito del lector ({ambitos}). Relee este caso: el camino de este "
        "corte probablemente ya llegue hasta el final, y el caso de arriba "
        "debe promoverse a la propiedad completa")

    # 3. Y el destino niega la ejecución que acaba de ocurrir.
    pantalla = operador.get(destino)
    assert pantalla.status_code == 404, (
        "el destino ya no responde 404 al apply recién hecho "
        f"({pantalla.status_code}): el bloqueo ha cambiado y hay que remedirlo")
    assert "RESULT_NOT_FOUND" in pantalla.text, (
        "el destino niega por una causa DISTINTA de la medida; un rojo por la "
        f"razón equivocada se lee igual que éste: {pantalla.text[:200]}")
