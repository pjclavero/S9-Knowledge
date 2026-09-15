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


def _panel(operador, job_id: str):
    r = operador.get(f"{SLOT_B.prefix}?solicitado={job_id}")
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

    assert respuesta.status_code in (302, 303, 403, 404), respuesta.status_code
    destino = respuesta.headers.get("location", "")
    assert "aviso=" not in destino, (
        f"la acción se ATENDIÓ para un revisor ({destino}): la guarda de rol no mordió"
    )
    # Y EL EFECTO, que ahora SÍ puede ponerse rojo.
    assert _filas_de_plan(almacenes["base"]) == [], "un revisor selló un plan"


def test_el_revisor_ve_la_corrida_pero_no_puede_aplicarla(
    real_app, paneles_on, cola, operador, revisor, almacenes,
    corrida_visible_para_todos, monkeypatch
):
    """El mismo control sobre la acción que SÍ escribe en el grafo."""
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED"
    assert _filas_de_plan(almacenes["base"])[0]["state"] == "sealed"

    token = _csrf(revisor)
    respuesta = revisor.post("/panel/operations/aplicaciones",
                             data={"trabajo": job_id, "csrf_token": token})

    assert respuesta.status_code in (302, 303, 403, 404), respuesta.status_code
    assert "aviso=" not in respuesta.headers.get("location", "")
    assert _filas_de_plan(almacenes["base"])[0]["state"] == "sealed", (
        "un revisor movió el estado del plan"
    )


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
    assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED"
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

    assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED"

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
    assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED"
    assert llamadas == [], "sellar reejecutó el pipeline"


def test_sellar_dos_veces_no_deja_dos_planes_vigentes(
    real_app, paneles_on, cola, operador, almacenes, monkeypatch
):
    """El invariante lo impone la BASE, no una comprobación en Python.

    `idx_sealed_plan_vigente` es un índice ÚNICO PARCIAL sobre
    (workspace, job_id) WHERE state='sealed'.
    """
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED"
    assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED"

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
    assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED"
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
    assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED"

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
    assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED"

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
        pytest.skip(f"no se pudo arrancar Neo4j: {arranque.stderr[:200]}")
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
            pytest.skip(f"Neo4j no llegó a estar listo: {ultimo}")
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
def grafo(grafo_real, monkeypatch):
    """Grafo LIMPIO por caso, y el visor apuntando a él con permiso declarado."""
    from app.config import get_settings

    with grafo_real["driver"].session() as sesion:
        sesion.run("MATCH (n) DETACH DELETE n")
    monkeypatch.setenv("S9K_NEO4J_URI", grafo_real["uri"])
    monkeypatch.setenv("S9K_NEO4J_USER", grafo_real["user"])
    monkeypatch.setenv("S9K_NEO4J_PASSWORD", grafo_real["password"])
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
    assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED"

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
    assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED"
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
    assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED"

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
    assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED"

    from app.services import v3_apply as servicio

    motor_real = servicio._motor

    def motor_que_muere():
        piezas = list(motor_real())

        def apply_que_muere(*args, **kwargs):
            raise KeyboardInterrupt("el proceso muere aquí")

        piezas[1] = apply_que_muere
        return tuple(piezas)

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
    assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED"

    monkeypatch.setenv("S9K_ALLOW_REAL_INGEST", "1")
    monkeypatch.setenv("S9K_WRITER_WORKSPACE", "ws-cofradia")
    # Sin Neo4j alcanzable el writer no aplica: desenlace real, no simulado.
    monkeypatch.setenv("S9K_NEO4J_URI", "bolt://127.0.0.1:1")
    monkeypatch.setenv("S9K_NEO4J_PASSWORD", "no-importa")
    from app.config import get_settings
    get_settings.cache_clear()

    codigo = _aviso_de(_aplicar(operador, job_id))
    assert codigo in ("APPLY_REJECTED", "APPLY_FAILED"), codigo

    fila = _filas_de_plan(almacenes["base"])[0]
    assert fila["state"] == "superseded", (
        "un plan que no escribió volvió a estar vigente"
    )
    assert fila["apply_id"] is None
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
    assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED"

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
    """
    job_id, _ = _aprobar_una(operador, cola, almacenes, monkeypatch)
    assert _aviso_de(_sellar(operador, job_id)) == "PLAN_SEALED"
    assert _aviso_de(_aplicar(operador, job_id)) == "PLAN_APPLIED"

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
