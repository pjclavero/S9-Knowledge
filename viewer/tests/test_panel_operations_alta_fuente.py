"""Slice 2 · Corte 1 — alta de fuente y ejecución real desde la consola.

QUÉ DEFIENDE ESTA SUITE
-----------------------
El recorrido COMPLETO del operador, ejecutado, no descrito:

    abre /panel/operations
     -> elige una fuente SIN conocer ningún id interno
     -> solicita la ingesta
     -> recibe una confirmación comprensible
     -> aparece un JOB REAL en la cola
     -> el worker recoge `ingest_v3`
     -> el estado REAL cambia
     -> termina OK o ERROR
     -> la pantalla EXPLICA el resultado
     -> refrescar y REINICIAR no pierden el estado

Y las tres propiedades que el encargo pone como criterio de aceptación, no como
extra: que no haya DOS ingestas, que NINGUNA ruta interna llegue al cliente, y
que el contrato de escritura del chasis sea explícito.

CÓMO SE MIDE, para que estas pruebas puedan ponerse ROJAS
---------------------------------------------------------
* La aplicación es la REAL (`app.main.app`), con la guarda real
  (`require_admin`) y el interruptor real del hueco (`S9K_PANEL_B_ENABLED`).
* La cola es una `jobs.db` DE VERDAD en un `tmp_path`: se crea, se escribe y se
  lee con `job_store`. No se sustituye `create_job` por un doble: si se
  sustituyera, "aparece un job real" no significaría nada.
* El worker es el REAL (`jobs.worker.run`), con su despacho por `HANDLERS`.
* La ingesta es la REAL: el handler llama a `run_ingest` y la cadena V3 corre
  entera sobre la fuente de `examples/ingesta-v3/`.

LOS PANELES ESTÁN APAGADOS POR DEFECTO
--------------------------------------
`S9K_PANEL_B_ENABLED` falla cerrado, así que toda prueba que quiera ver la
pantalla tiene que encenderlo explícitamente (fixture `panel_on`). Se dice aquí
porque condiciona el diseño: la prueba de que un anónimo no distingue un panel
encendido de uno apagado depende de que el interruptor se evalúe DESPUÉS de la
guarda, y eso es justo lo que se comprueba.
"""
from __future__ import annotations

import ast
import json
import logging
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import jobs_client, panel_errors, sources_catalog
from app.chassis import FEATURE_SLOTS, slot_flag_env

SLOT = next(s for s in FEATURE_SLOTS if s.key == "B")
FLAG = slot_flag_env(SLOT)
PASSWORD = "PanelBAlta_1234567890!"

REPO = Path(__file__).resolve().parents[2]


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

EJEMPLOS = REPO / "examples" / "ingesta-v3"


# ---------------------------------------------------------------------------
# Fixtures: app real, auth real, cola real
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
                "S9K_INGEST_SOURCES_DIR", FLAG):
        os.environ.pop(var, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _salud_aislada(tmp_path, monkeypatch):
    monkeypatch.setenv("S9K_HEALTH_REPORT_PATH", str(tmp_path / "health" / "last.json"))


@pytest.fixture
def panel_on():
    os.environ[FLAG] = "true"
    yield
    os.environ.pop(FLAG, None)


@pytest.fixture
def cola(tmp_path):
    """Una `jobs.db` DE VERDAD. Nada de dobles: la cola es el sujeto."""
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


def _cliente(app, cookie: str | None = None) -> TestClient:
    from app.auth.config import get_auth_settings

    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    if cookie:
        c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, cookie)
    c.headers.update({"accept": "text/html"})
    return c


@pytest.fixture
def operador(real_app, auth_on):
    """Un ADMIN autenticado de verdad: la única puerta de este hueco."""
    return _cliente(real_app, _cookie(auth_on, "alta_operador", "admin"))


@pytest.fixture
def anonimo(real_app, auth_on):
    return _cliente(real_app)


def _csrf_del_formulario(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]*)"', html)
    assert m, "el formulario no trae token CSRF"
    return m.group(1)


def _opciones(html: str) -> list[str]:
    bloque = re.search(r'data-role="selector-fuente".*?</select>', html, re.S)
    assert bloque, "no hay selector de fuente en la pantalla"
    return re.findall(r'<option value="([^"]+)"', bloque.group(0))


def _csrf_valido(cliente: TestClient) -> str:
    """Un token CSRF VÁLIDO para la sesión de `cliente`, sin pasar por el panel.

    Existe por una razón concreta y medida: la prueba del rol insuficiente
    pasaba EN VERDE aunque se degradara la guarda del POST a `viewer`, porque
    el `reviewer` no podía obtener un token y lo paraba el CSRF, no la
    autorización. Un verde por la razón equivocada se lee igual que uno
    legítimo. `base.html` publica el token en todas las páginas, así que se
    toma de una que el rol SÍ pueda abrir.
    """
    r = cliente.get("/")
    assert r.status_code == 200, f"no se pudo obtener token: {r.status_code}"
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    assert m, "base.html no publicó ningún token CSRF"
    return m.group(1)


def _correr_worker(db: Path, limit: int = 1) -> int:
    """El worker REAL, con su despacho real. Devuelve trabajos procesados."""
    from jobs import worker

    return worker.run("worker-test", once=True, limit=limit, db_path=str(db))


# ===========================================================================
# 0. El arnés muerde. Sin esto, todo lo demás es adorno.
# ===========================================================================

def test_el_arnes_tiene_material_y_la_fuente_existe():
    """Un arnés que pasa con 0 casos está roto: aquí se exige material REAL."""
    fuentes = sources_catalog.listar_fuentes({"S9K_INGEST_SOURCES_DIR": str(EJEMPLOS)})
    assert fuentes, "sin fuentes de ejemplo no hay recorrido que probar"
    assert any(f.ruta.is_file() and f.ruta.stat().st_size > 0 for f in fuentes)


def test_el_worker_conoce_ingest_v3():
    """Si `ingest_v3` no está en HANDLERS, el recorrido no puede completarse."""
    from jobs import worker

    assert "ingest_v3" in worker.HANDLERS, (
        "El corte mete `ingest_v3` en la cola que YA existe; sin handler "
        "registrado el job se marcaría 'skipped' y no habría trabajo real."
    )


# ===========================================================================
# 1. EL CONTRATO DEL CHASIS CAMBIA, Y ES EXPLÍCITO
# ===========================================================================

#: Lo que el hueco B declara HOY, campo a campo. La tabla está aquí, en la
#: prueba, y no derivada del chasis: derivarla la haría verde por construcción
#: y dejaría de decir nada. Añadir una capacidad al chasis pone esto rojo hasta
#: que alguien la escriba también aquí — que es el acto de declararla.
#:
#: Las dos últimas son del corte de APPLY. La segunda escribe en el almacén de
#: revisión (el snapshot del plan) y la tercera escribe EN EL GRAFO.
CAPACIDADES_DECLARADAS = {
    "ingesta_de_fuente": ("/panel/operations/ingestas", frozenset({"POST"}), "admin"),
    "sellado_del_plan_revisado": (
        "/panel/operations/planes", frozenset({"POST"}), "admin",
    ),
    "aplicacion_del_plan_revisado": (
        "/panel/operations/aplicaciones", frozenset({"POST"}), "admin",
    ),
}


def test_la_escritura_del_panel_esta_declarada_en_el_chasis():
    """"Este POST es especial" tiene que ser IMPOSIBLE de colar.

    Cada capacidad existe como DATO en el chasis, con rol, métodos y auditoría.
    """
    from app.chassis import capabilities_for_slot

    caps = {c.name: c for c in capabilities_for_slot("B")}
    assert sorted(caps) == sorted(CAPACIDADES_DECLARADAS), (
        "el hueco B declara capacidades que esta prueba no conoce (o al revés)"
    )
    for nombre, (ruta, metodos, rol) in CAPACIDADES_DECLARADAS.items():
        cap = caps[nombre]
        assert cap.path == ruta
        assert cap.methods == metodos
        assert cap.role == rol
        assert cap.audited is True


def test_lectura_por_defecto_los_demas_huecos_siguen_cerrados(real_app):
    """El contrato nuevo NO abre los paneles: mantiene lectura por defecto."""
    from app.chassis import capabilities_for_slot, undeclared_writes

    for clave in ("C", "F", "G"):
        slot = next(s for s in FEATURE_SLOTS if s.key == clave)
        assert capabilities_for_slot(clave) == ()
        assert undeclared_writes(real_app, slot) == [], (
            f"El hueco {clave} no declara capacidades: no puede tener escritura"
        )


def test_una_capacidad_no_auditable_no_se_puede_declarar():
    """La palabra "AUDITABLES" del contrato tiene mecanismo, no es prosa."""
    from app.chassis import ChassisContractError, WriteCapability

    with pytest.raises(ChassisContractError, match="auditable"):
        WriteCapability(
            slot_key="B", name="x", title="x", path="/panel/operations/x",
            methods=frozenset({"POST"}), role="admin", audited=False, summary="x",
        )


def test_una_capacidad_fuera_del_espacio_de_su_hueco_no_se_puede_declarar():
    """Declarar no es poder declarar CUALQUIER COSA: el path se comprueba."""
    from app.chassis import ChassisContractError, WriteCapability

    with pytest.raises(ChassisContractError, match="fuera del espacio"):
        WriteCapability(
            slot_key="B", name="x", title="x", path="/admin/users",
            methods=frozenset({"POST"}), role="admin", audited=True, summary="x",
        )


# ===========================================================================
# 2. NO HAY DOS INGESTAS
# ===========================================================================

def test_no_hay_dos_ingestas():
    """El handler reutiliza el NÚCLEO; no envuelve la CLI. Medido por AST.

    Tres afirmaciones, y ninguna es "lo he mirado":

      1. el handler IMPORTA `run_ingest` de `knowledge_v3.pipeline.ingest_cli`;
      2. el handler NO lanza procesos ni llama a `ingest_cli.main` — no hay en
         su AST ninguna llamada a `subprocess`, `os.system`, `os.popen`,
         `runpy` ni `main`;
      3. la CLI y el handler convergen en el MISMO símbolo: `ingest_cli.main`
         también llama a `run_ingest`.
    """
    from jobs.handlers import ingest_v3 as handler_mod
    from knowledge_v3.pipeline import ingest_cli

    arbol = ast.parse(Path(handler_mod.__file__).read_text(encoding="utf-8"))

    # (1) importa el núcleo, del módulo del núcleo
    importa = [
        n for n in ast.walk(arbol)
        if isinstance(n, ast.ImportFrom)
        and (n.module or "").endswith("ingest_cli")
        and any(a.name == "run_ingest" for a in n.names)
    ]
    assert importa, "el handler no importa `run_ingest` del núcleo"

    # (2) ni un solo lanzamiento de proceso, ni una llamada a la CLI
    prohibidos = {"subprocess", "os.system", "os.popen", "runpy", "popen",
                  "check_call", "check_output", "run_cli", "main"}
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call):
            nombre = ast.unparse(nodo.func)
            assert not any(p in nombre for p in prohibidos), (
                f"el handler llama a {nombre!r}: eso sería una SEGUNDA ingesta"
            )
        if isinstance(nodo, (ast.Import, ast.ImportFrom)):
            for alias in nodo.names:
                assert alias.name.split(".")[0] != "subprocess", (
                    "el handler importa subprocess"
                )

    # (3) el handler llama a `run_ingest` de verdad
    llamadas = {
        ast.unparse(n.func) for n in ast.walk(arbol) if isinstance(n, ast.Call)
    }
    assert "run_ingest" in llamadas, "el handler no llega a llamar al núcleo"

    # (4) y la CLI llama al MISMO símbolo: un solo núcleo, dos adaptadores
    arbol_cli = ast.parse(Path(ingest_cli.__file__).read_text(encoding="utf-8"))
    main_cli = next(
        n for n in ast.walk(arbol_cli)
        if isinstance(n, ast.FunctionDef) and n.name == "main"
    )
    llamadas_cli = {
        ast.unparse(n.func) for n in ast.walk(main_cli) if isinstance(n, ast.Call)
    }
    assert "run_ingest" in llamadas_cli, (
        "la CLI ya no llama a `run_ingest`: los dos adaptadores han divergido"
    )
    # Y es literalmente la misma función, no dos que se llaman igual.
    assert handler_mod.run_ingest is ingest_cli.run_ingest


# ===========================================================================
# 3. EL RECORRIDO COMPLETO DEL OPERADOR, EJECUTADO
# ===========================================================================

def test_el_recorrido_completo_del_operador(real_app, panel_on, cola, operador,
                                            monkeypatch):
    """De abrir el panel a leer el resultado explicado. Paso por paso.

    Es LA prueba del corte. Cada aserción corresponde a un punto del recorrido
    que el encargo enumera, y ninguna se da por buena leyendo código.
    """
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(EJEMPLOS))

    # --- 1. el operador abre el panel ---
    pantalla = operador.get(SLOT.prefix)
    assert pantalla.status_code == 200
    html = pantalla.text
    assert 'data-role="alta-de-fuente"' in html

    # --- 2. elige una fuente de una lista, por su NOMBRE ---
    opciones = _opciones(html)
    assert opciones, "no se ofrece ninguna fuente que elegir"
    handle = opciones[0]
    assert "/" not in handle and "\\" not in handle, (
        f"el identificador de la fuente parece una ruta: {handle!r}"
    )

    # --- 3. solicita la ingesta ---
    envio = operador.post(
        "/panel/operations/ingestas",
        data={"fuente": handle, "csrf_token": _csrf_del_formulario(html)},
    )
    assert envio.status_code == 303, envio.text[:300]
    destino = envio.headers["location"]
    assert "solicitado=" in destino

    # --- 4. recibe una confirmación comprensible ---
    acuse = operador.get(destino)
    assert acuse.status_code == 200
    assert 'data-aviso-tipo="ok"' in acuse.text
    assert "Se ha solicitado la ingesta" in acuse.text

    # --- 5. aparece un JOB REAL en la cola REAL ---
    store = jobs_client._load_job_store()
    pendientes = store.list_jobs(status="pending", db_path=str(cola))
    assert len(pendientes) == 1, pendientes
    job = pendientes[0]
    assert job["job_type"] == "ingest_v3"
    job_id = job["job_id"]
    # El trabajo se ve en la pantalla, no sólo en la base de datos.
    assert job_id in acuse.text

    # --- 6. el worker REAL lo recoge ---
    assert _correr_worker(cola) == 1

    # --- 7 y 8. el estado REAL ha cambiado y ha terminado ---
    final = store.get_job(job_id, db_path=str(cola))
    assert final["status"] == "complete", final.get("error_message")

    # --- 9. la pantalla EXPLICA el resultado ---
    despues = operador.get(destino)
    assert despues.status_code == 200
    assert 'data-resultado-estado="ok"' in despues.text
    # Corte 4: el acuse ya no es la frase pelada. Sigue diciendo que terminó
    # bien, pero AÑADE el desenlace de revisión —«ha dejado N decisiones en
    # REVIEW» o «no ha dejado nada en revisión»— porque «terminado
    # correctamente» a secas, con REVIEW>0, hacía que el operador cerrase la
    # pantalla sin abrir la consola de revisión. Se afirma el invariante, no
    # el literal exacto.
    assert "La ingesta ha terminado correctamente" in despues.text
    assert "revision" in despues.text.lower() or "revisión" in despues.text.lower()
    # Y explica QUÉ se ha obtenido, no sólo que fue bien.
    assert 'data-role="resumen"' in despues.text
    assert 'data-resumen="afirmaciones"' in despues.text


def test_el_estado_sobrevive_al_refresco_y_al_reinicio(real_app, panel_on, cola,
                                                       operador, monkeypatch):
    """Condición del corte, no detalle: refrescar y REINICIAR no pierden nada.

    El "reinicio" se simula de la única forma que significa algo: tirando todo
    el estado en memoria del proceso (las cachés de configuración y el módulo
    del job_store ya importado) y volviendo a construir el cliente. Lo único
    que sobrevive es lo que está en disco — que es justo lo que se afirma.
    """
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(EJEMPLOS))
    html = operador.get(SLOT.prefix).text
    envio = operador.post(
        "/panel/operations/ingestas",
        data={"fuente": _opciones(html)[0], "csrf_token": _csrf_del_formulario(html)},
    )
    destino = envio.headers["location"]
    assert _correr_worker(cola) == 1

    # Refrescar N veces da SIEMPRE lo mismo, y no re-envía nada (PRG).
    primero = operador.get(destino).text
    for _ in range(3):
        assert operador.get(destino).text == primero
    store = jobs_client._load_job_store()
    assert len(store.list_jobs(db_path=str(cola))) == 1, (
        "refrescar ha creado trabajos: el POST no está detrás de un redirect"
    )

    # "Reinicio": se tiran las cachés de proceso y se rehace el cliente.
    from app.auth.config import get_auth_settings
    from app.config import get_settings
    get_settings.cache_clear()
    get_auth_settings.cache_clear()
    nuevo = _cliente(real_app, _cookie(
        Path(os.environ["S9K_AUTH_DB_PATH"]), "tras_reinicio", "admin"))

    tras = nuevo.get(destino)
    assert tras.status_code == 200
    assert 'data-resultado-estado="ok"' in tras.text, (
        "tras el reinicio el resultado se ha perdido: el estado no estaba en disco"
    )


# ===========================================================================
# 4. CERO CONOCIMIENTO INTERNO
# ===========================================================================

def test_la_pantalla_no_exige_ni_revela_nada_interno(real_app, panel_on, cola,
                                                     operador, monkeypatch):
    """Si el operador necesita saber algo de las tripas, el paso no está hecho.

    Se comprueba en las dos direcciones: ni se le PIDE (no hay campo de
    formulario para nada interno) ni se le ENSEÑA (el HTML no contiene rutas
    del servidor, ni el workspace, ni identificadores de plan o partida).
    """
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(EJEMPLOS))
    html = operador.get(SLOT.prefix).text

    formulario = re.search(r'data-role="form-ingesta".*?</form>', html, re.S)
    assert formulario, "no hay formulario de ingesta"
    campos = set(re.findall(r'name="([^"]+)"', formulario.group(0)))
    assert campos == {"fuente", "csrf_token"}, (
        f"el formulario pide más de lo debido: {campos}"
    )

    # (a) EN EL PASO: la sección de alta no nombra NADA interno. Es la parte
    # que el operador tiene que completar, y la definición de USABLE se aplica
    # aquí. El filtro de la cola que ya existía (que tiene una caja
    # "Workspace") es otra cosa: es observación del panel de siempre, no un
    # requisito para dar de alta una fuente, y este corte no lo toca.
    seccion = re.search(r'data-role="alta-de-fuente".*?</section>', html, re.S)
    assert seccion, "no hay sección de alta de fuente"
    for aguja in ("plan_id", "partida_id", "workspace", "collection"):
        assert aguja not in seccion.group(0).lower(), (
            f"el paso de alta exige conocimiento interno: {aguja!r}"
        )

    # (b) EN TODA LA PÁGINA: nada del servidor ni del backend, nunca.
    prohibidas = [str(EJEMPLOS), str(REPO), "perfil-operador.json",
                  "catalogo-workspace.json", "ingest_cli", "--perfil",
                  "--dry-run", "PYTHONPATH", "run_ingest", "/home/"]
    bajo = html.lower()
    for aguja in prohibidas:
        assert aguja.lower() not in bajo, (
            f"la pantalla revela conocimiento interno: {aguja!r}"
        )


def test_el_identificador_de_la_fuente_no_es_una_ruta(monkeypatch):
    """El handle es un slug, y una ruta del cliente NUNCA resuelve.

    Es la propiedad que hace que aceptar la elección del operador sea seguro.
    """
    entorno = {"S9K_INGEST_SOURCES_DIR": str(EJEMPLOS)}
    for f in sources_catalog.listar_fuentes(entorno):
        assert "/" not in f.handle and ".." not in f.handle

    for intento in ["../../etc/passwd", "/etc/passwd", str(EJEMPLOS / "perfil-operador.json"),
                    "nota-cofradia-de-ambar.md", ".."]:
        assert sources_catalog.resolver(intento, entorno) is None, (
            f"una entrada de cliente ha resuelto a una fuente: {intento!r}"
        )


def test_el_perfil_y_el_catalogo_no_se_ofrecen_como_fuentes(monkeypatch):
    """Ingerir la ontología del propio workspace no es una opción de producto."""
    entorno = {"S9K_INGEST_SOURCES_DIR": str(EJEMPLOS)}
    titulos = {f.ruta.name for f in sources_catalog.listar_fuentes(entorno)}
    assert "perfil-operador.json" not in titulos
    assert "catalogo-workspace.json" not in titulos
    assert "README.md" not in titulos


# ===========================================================================
# 5. EL CAMINO DE ERROR: NINGUNA RUTA INTERNA LLEGA AL CLIENTE
# ===========================================================================

def test_una_fuente_invalida_no_filtra_la_ruta_al_cliente_y_si_al_log(
        real_app, panel_on, cola, operador, tmp_path, monkeypatch, caplog):
    """Fuente inválida: caso propio, con las DOS mitades comprobadas.

    El fichero vacío es el defecto medido del núcleo: `build_source` levanta
    `PipelineError(f"{path}: fichero vacio; no hay fuente que ingerir")`, con la
    ruta DENTRO del mensaje. Sin traducción, esa ruta acaba en `error_message`
    del job y de ahí en la pantalla.

    Se exige: (a) el cliente ve CÓDIGO + FRASE y ninguna ruta; (b) el servidor
    SÍ registra el detalle, porque un error que no se puede diagnosticar
    tampoco sirve.
    """
    fuentes = tmp_path / "fuentes"
    fuentes.mkdir()
    (fuentes / "nota-rota.md").write_text("", encoding="utf-8")   # vacío = inválido
    for aux in ("perfil-operador.json", "catalogo-workspace.json"):
        (fuentes / aux).write_text((EJEMPLOS / aux).read_text(encoding="utf-8"),
                                   encoding="utf-8")
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(fuentes))

    html = operador.get(SLOT.prefix).text
    envio = operador.post(
        "/panel/operations/ingestas",
        data={"fuente": _opciones(html)[0], "csrf_token": _csrf_del_formulario(html)},
    )
    assert envio.status_code == 303
    destino = envio.headers["location"]

    with caplog.at_level(logging.ERROR, logger="jobs.handlers.ingest_v3"):
        assert _correr_worker(cola) == 1

    store = jobs_client._load_job_store()
    job = store.list_jobs(db_path=str(cola))[0]
    assert job["status"] == "failed"

    # (a) NI EN LA BASE NI EN LA PANTALLA hay ruta del servidor.
    assert job["error_message"].startswith("SOURCE_PACKAGE_INVALID:")
    assert str(fuentes) not in (job["error_message"] or "")

    pantalla = operador.get(destino)
    assert pantalla.status_code == 200
    assert 'data-resultado-estado="error"' in pantalla.text
    assert 'data-resultado-code="SOURCE_PACKAGE_INVALID"' in pantalla.text
    assert "El paquete de la fuente no es valido." in pantalla.text
    for aguja in [str(fuentes), str(tmp_path), "nota-rota.md", "Traceback",
                  "PipelineError", "/home/"]:
        assert aguja not in pantalla.text, (
            f"la pantalla de error revela algo del servidor: {aguja!r}"
        )

    # (b) el detalle SÍ está en el log del servidor.
    registrado = "\n".join(r.getMessage() + (r.exc_text or "") for r in caplog.records)
    assert "nota-rota.md" in registrado or str(fuentes) in registrado, (
        "el detalle técnico no ha llegado al log: el error es indiagnosticable"
    )


def test_el_error_del_handler_nunca_lleva_detalle_tecnico():
    """`IngestV3Error` no tiene dónde meter una ruta. Por construcción."""
    from jobs.handlers.ingest_v3 import CODIGOS, IngestV3Error

    err = IngestV3Error("SOURCE_PACKAGE_INVALID")
    assert str(err) == "SOURCE_PACKAGE_INVALID: " + CODIGOS["SOURCE_PACKAGE_INVALID"]
    with pytest.raises(KeyError):
        IngestV3Error("CODIGO_INVENTADO")


def test_los_codigos_del_handler_los_sabe_pintar_el_panel():
    """Un código que el panel no conoce sería un mensaje mudo para el operador."""
    from jobs.handlers.ingest_v3 import CODIGOS

    faltan = set(CODIGOS) - set(panel_errors.CATALOGO)
    assert not faltan, f"códigos que el panel no sabe pintar: {faltan}"


def test_un_codigo_inventado_en_la_url_no_pinta_texto_arbitrario(
        real_app, panel_on, cola, operador, monkeypatch):
    """El aviso se valida contra el catálogo CERRADO, no se refleja."""
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(EJEMPLOS))
    r = operador.get(f"{SLOT.prefix}?aviso=<script>alert(1)</script>")
    assert r.status_code == 200
    assert 'data-role="aviso"' not in r.text
    assert "<script>alert(1)</script>" not in r.text


def test_sin_elegir_fuente_el_mensaje_es_accionable(real_app, panel_on, cola,
                                                    operador, monkeypatch):
    """CÓDIGO + FRASE que dice QUÉ HACER, no `KeyError`."""
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(EJEMPLOS))
    html = operador.get(SLOT.prefix).text
    envio = operador.post(
        "/panel/operations/ingestas",
        data={"fuente": "", "csrf_token": _csrf_del_formulario(html)},
    )
    assert envio.status_code == 303
    pantalla = operador.get(envio.headers["location"])
    assert 'data-aviso-code="SOURCE_NOT_SELECTED"' in pantalla.text
    assert "Selecciona una de la lista" in pantalla.text
    # Y no se ha encolado nada.
    store = jobs_client._load_job_store()
    assert store.list_jobs(db_path=str(cola)) == []


def test_una_fuente_que_no_existe_no_encola_nada(real_app, panel_on, cola,
                                                 operador, monkeypatch):
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(EJEMPLOS))
    html = operador.get(SLOT.prefix).text
    envio = operador.post(
        "/panel/operations/ingestas",
        data={"fuente": "no-existe-esta-fuente",
              "csrf_token": _csrf_del_formulario(html)},
    )
    pantalla = operador.get(envio.headers["location"])
    assert 'data-aviso-code="SOURCE_UNKNOWN"' in pantalla.text
    store = jobs_client._load_job_store()
    assert store.list_jobs(db_path=str(cola)) == []


def test_un_catalogo_ausente_no_se_pinta_como_lista_vacia(real_app, panel_on, cola,
                                                          operador, tmp_path,
                                                          monkeypatch):
    """AUSENCIA != CERO, también en la capacidad nueva."""
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(tmp_path / "no-existe"))
    html = operador.get(SLOT.prefix).text
    assert 'data-fuentes-available="false"' in html
    assert "es que el dato no está" in html
    assert 'data-role="form-ingesta"' not in html, (
        "se ofrece el formulario sin saber si hay fuentes"
    )


# ===========================================================================
# 6. AUTENTICADA, AUTORIZADA, CSRF, AUDITADA
# ===========================================================================

def test_un_anonimo_no_puede_solicitar_ingestas(real_app, panel_on, cola, anonimo):
    r = anonimo.post("/panel/operations/ingestas", data={"fuente": "x"})
    assert r.status_code in (302, 401, 403), r.status_code
    store = jobs_client._load_job_store()
    assert store.list_jobs(db_path=str(cola)) == []


def test_un_rol_insuficiente_no_puede_solicitar_ingestas(real_app, panel_on, cola,
                                                         auth_on):
    """`reviewer` ve otras pantallas del visor, pero esta capacidad es `admin`."""
    cliente = _cliente(real_app, _cookie(auth_on, "revisor_alta", "reviewer"))
    # CSRF VÁLIDO a propósito: si el reviewer se parara por falta de token,
    # esta prueba saldría verde aunque la guarda del POST fuera `viewer`.
    r = cliente.post("/panel/operations/ingestas",
                     data={"fuente": "x", "csrf_token": _csrf_valido(cliente)})
    assert r.status_code in (302, 401, 403), r.status_code
    store = jobs_client._load_job_store()
    assert store.list_jobs(db_path=str(cola)) == []


def test_la_guarda_del_post_es_la_misma_del_panel(real_app):
    """La puerta del POST es `require_admin`, COMPROBADO sobre la app real.

    Complementa a las pruebas de comportamiento en vez de repetirlas: degradar
    la guarda a un rol menor se ve aquí de inmediato y sin depender de que el
    CSRF no tape el resultado.
    """
    from app.chassis import iter_mounted_routes

    ruta = next(
        r for r in iter_mounted_routes(real_app)
        if getattr(r, "path", "") == "/panel/operations/ingestas"
    )
    guardas = {getattr(d.call, "__name__", str(d.call)) for d in ruta.dependant.dependencies}
    assert "require_admin" in guardas, (
        f"la capacidad de escritura no está detrás de require_admin: {guardas}"
    )


def test_sin_csrf_valido_no_se_encola_nada(real_app, panel_on, cola, operador,
                                           monkeypatch):
    """La protección CSRF es del contrato, no un adorno del formulario."""
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(EJEMPLOS))
    html = operador.get(SLOT.prefix).text
    handle = _opciones(html)[0]

    for token in ("", "token-inventado"):
        r = operador.post("/panel/operations/ingestas",
                          data={"fuente": handle, "csrf_token": token})
        assert r.status_code == 403, (token, r.status_code)
    store = jobs_client._load_job_store()
    assert store.list_jobs(db_path=str(cola)) == [], "se ha encolado sin CSRF"


def test_con_el_panel_apagado_la_capacidad_no_existe(real_app, cola, operador,
                                                     monkeypatch):
    """El interruptor apaga también la escritura, no sólo la pantalla."""
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(EJEMPLOS))
    os.environ.pop(FLAG, None)
    r = operador.post("/panel/operations/ingestas", data={"fuente": "x"})
    assert r.status_code == 404
    store = jobs_client._load_job_store()
    assert store.list_jobs(db_path=str(cola)) == []


def test_la_solicitud_queda_auditada(real_app, panel_on, cola, operador,
                                     monkeypatch, caplog):
    """AUDITABLE: quién, qué capacidad, sobre qué fuente y con qué resultado."""
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(EJEMPLOS))
    html = operador.get(SLOT.prefix).text
    with caplog.at_level(logging.INFO, logger="panel.audit"):
        operador.post("/panel/operations/ingestas",
                      data={"fuente": _opciones(html)[0],
                            "csrf_token": _csrf_del_formulario(html)})
    rastro = "\n".join(r.getMessage() for r in caplog.records)
    assert "capacidad=ingesta_de_fuente" in rastro
    assert "operador=alta_operador" in rastro
    assert "resultado=ENCOLADO" in rastro


def test_la_atribucion_queda_en_el_propio_trabajo(real_app, panel_on, cola,
                                                  operador, monkeypatch):
    """Rastro DURABLE: quién pidió la ingesta vive en el job, no sólo en un log."""
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(EJEMPLOS))
    html = operador.get(SLOT.prefix).text
    operador.post("/panel/operations/ingestas",
                  data={"fuente": _opciones(html)[0],
                        "csrf_token": _csrf_del_formulario(html)})
    store = jobs_client._load_job_store()
    job = store.list_jobs(db_path=str(cola))[0]
    assert json.loads(job["payload_json"])["requested_by"] == "alta_operador"


# ===========================================================================
# 7. LA INGESTA ES REAL Y NO ESCRIBE EN EL GRAFO
# ===========================================================================

def test_la_ingesta_corre_de_verdad_y_produce_conocimiento(tmp_path):
    """El handler no simula: la cadena V3 corre entera sobre la fuente."""
    from jobs.handlers.ingest_v3 import handle_ingest_v3

    r = handle_ingest_v3({
        "source_path": str(EJEMPLOS / "nota-cofradia-de-ambar.md"),
        "profile_path": str(EJEMPLOS / "perfil-operador.json"),
        "catalog_path": str(EJEMPLOS / "catalogo-workspace.json"),
        "source_title": "Nota de la Cofradía",
    })
    assert r["ok"] is True
    resumen = r["resumen"]
    assert resumen["menciones"] > 0, "cero menciones: la cadena no ha corrido"
    assert resumen["claims"] > 0
    assert resumen["escritura"] == "NO (simulacion)"


def test_el_resumen_no_publica_la_ruta_de_la_fuente(tmp_path):
    """El informe trae `run.source_path`; el resumen se construye por lista blanca."""
    from jobs.handlers.ingest_v3 import handle_ingest_v3

    r = handle_ingest_v3({
        "source_path": str(EJEMPLOS / "nota-cofradia-de-ambar.md"),
        "profile_path": str(EJEMPLOS / "perfil-operador.json"),
        "catalog_path": str(EJEMPLOS / "catalogo-workspace.json"),
    })
    serializado = json.dumps(r, ensure_ascii=False)
    assert str(EJEMPLOS) not in serializado
    assert "source_path" not in serializado


def test_este_corte_no_aplica_nada_al_grafo():
    """La ingesta del panel LEE el grafo, y sigue sin ESCRIBIR en él.

    Antes del Slice 2 · Corte 5 este caso exigía las dos constantes juntas:
    `apply=False` **y** `driver=None`. Las dos cosas se leían como una sola
    --«no toca el grafo»-- y no lo son. `driver=None` no significaba «no
    escribe»: significaba «no mira», y ésa era justo la costura que dejaba las
    anclas del plan en `observed: false` y la proyección omitida para siempre.

    Lo que se mide ahora, por AST y por separado:

      * `apply=False` LITERAL: es lo único que gobierna la escritura, porque
        `run_ingest` hace `writer_driver=driver if apply else None`. Mientras
        esa constante esté, el writer no ve la conexión aunque exista.
      * `driver` NO es una constante: la llamada recibe una conexión de sólo
        lectura, que es lo que permite observar el catálogo del workspace.

    Un futuro cambio que active la escritura tendrá que pasar por aquí igual
    que antes: lo que cambia es que ya no hace falta romper esto para poder
    MIRAR.
    """
    from jobs.handlers import ingest_v3 as handler_mod

    arbol = ast.parse(Path(handler_mod.__file__).read_text(encoding="utf-8"))
    llamada = next(
        n for n in ast.walk(arbol)
        if isinstance(n, ast.Call) and ast.unparse(n.func) == "run_ingest"
    )
    kwargs = {k.arg: ast.unparse(k.value) for k in llamada.keywords}
    assert kwargs.get("apply") == "False", kwargs
    assert kwargs.get("driver") not in (None, "None"), (
        f"la ingesta del panel ha vuelto a llamar al núcleo sin grafo: {kwargs}. "
        "Sin driver ningún ancla sale observada y el sellado omite toda "
        "proyección con `PROJECTION_ANCHOR_NOT_OBSERVED`."
    )


# ===========================================================================
# 9. CARRIL B · M1 — la partida llega HASTA EL ALTA, y el ámbito se VE
# ---------------------------------------------------------------------------
# Lo de arriba corre sobre el catálogo PLANO heredado. Esto corre sobre una
# BÓVEDA: el descubrimiento jerárquico con clasificación ruta -> ámbito. Se
# ejecuta contra la app real, la cola real y el worker real, igual que el resto
# de la suite: nada de esto se afirma leyendo código.
# ===========================================================================

from test_vault_descubrimiento_ambito import (  # noqa: E402
    PARTIDAS_L5R,
    boveda,  # noqa: F401 - fixture
)


@pytest.fixture
def boveda_montada(boveda, monkeypatch):  # noqa: F811
    """Bóveda encendida para la app real, sin exigir montaje (es un tmp_path)."""
    monkeypatch.setenv(sources_catalog.ENV_RAIZ_BOVEDAS, str(boveda))
    monkeypatch.setenv(sources_catalog.ENV_EXIGIR_MONTAJE, "0")
    return boveda


def _fila_de_ambito(html: str, handle: str) -> dict:
    """La fila de ESE handle en la tabla de ámbito de la pantalla.

    Levanta si la tabla no está: es lo que hace que BORRAR la pantalla ponga
    esto rojo. Una garantía que no se pinta no la puede comprobar quien opera,
    así que el testigo PIDE LA PANTALLA y no se conforma con el payload.
    """
    tabla = re.search(r'data-role="ambito-de-fuentes".*?</table>', html, re.S)
    assert tabla, (
        "no se pinta el ámbito de las fuentes: el operador no puede ver con qué "
        "alcance va a entrar lo que elige"
    )
    fila = re.search(r'<tr data-handle="%s">.*?</tr>' % re.escape(handle),
                     tabla.group(0), re.S)
    assert fila, f"la fuente {handle!r} no aparece en la tabla de ámbito"
    return {k: v.strip() for k, v in re.findall(
        r'data-col="([^"]+)">(.*?)</td>', fila.group(0), re.S)}


def _handle_de(html: str, aguja: str) -> str:
    """El handle de la opción cuyo texto contiene `aguja`."""
    bloque = re.search(r'data-role="selector-fuente".*?</select>', html, re.S)
    assert bloque
    for opcion in re.findall(r'<option value="([^"]+)"[^>]*>(.*?)</option>',
                             bloque.group(0), re.S):
        if aguja.lower() in opcion[1].lower():
            return opcion[0]
    raise AssertionError(f"no hay ninguna fuente que contenga {aguja!r}")


def test_la_pantalla_ensena_el_ambito_de_cada_fuente(real_app, panel_on, cola,
                                                     operador, boveda_montada):
    """Dos fuentes del MISMO juego, con ámbitos distintos, se distinguen.

    Es el contraste directo con el defecto: con el ámbito único de la raíz,
    «ingerir los clanes» y «ingerir un secreto de la campaña Grulla» se leerían
    exactamente igual en la pantalla.
    """
    html = operador.get(SLOT.prefix).text

    clanes = _fila_de_ambito(html, _handle_de(html, "clanes"))
    assert clanes["juego"] == "leyenda", clanes
    assert clanes["partida"] == "todo el juego", clanes
    assert clanes["visibilidad"] == "player", clanes

    impostor = _fila_de_ambito(html, _handle_de(html, "impostor"))
    assert impostor["visibilidad"] == "secret", impostor
    assert impostor["partida"] in PARTIDAS_L5R, impostor

    assert clanes != impostor, (
        "dos fuentes de ámbito distinto se pintan igual: el ámbito uniforme "
        "de la raíz habría pasado desapercibido"
    )


def test_la_pantalla_ensena_lo_que_NO_entra(real_app, panel_on, cola, operador,
                                            boveda_montada):
    """`archivo/` no se ingiere, y el operador se entera.

    El defecto original no era sólo clasificar mal: era descartar EN SILENCIO,
    sin warning y con `stderr` vacío.
    """
    html = operador.get(SLOT.prefix).text
    bloque = re.search(r'data-role="fuentes-rechazadas".*?</div>', html, re.S)
    assert bloque, "lo que no entra no se ve en ninguna parte"
    assert "archivo/retirado.md" in bloque.group(0)
    assert "no se ingiere nunca" in bloque.group(0)


def _payload_del_unico_job(cola):
    store = jobs_client._load_job_store()
    jobs = store.list_jobs(status="pending", db_path=str(cola))
    assert len(jobs) == 1, jobs
    return jobs[0], json.loads(jobs[0]["payload_json"])


def test_la_partida_viaja_EXPLICITA_hasta_el_trabajo(real_app, panel_on, cola,
                                                     operador, boveda_montada):
    """EVIDENCIA EJECUTADA de la instrucción 9, sobre la cola REAL.

    El motor ya aceptaba partida (`run_ingest(partida_id=...)`); el hueco era el
    alta de producto. Aquí se solicita una ingesta de material de partida y se
    lee del job REAL que la partida llegó.
    """
    html = operador.get(SLOT.prefix).text
    handle = _handle_de(html, "impostor")
    envio = operador.post(
        "/panel/operations/ingestas",
        data={"fuente": handle, "csrf_token": _csrf_del_formulario(html)},
    )
    assert envio.status_code == 303, envio.text[:300]

    _job, payload = _payload_del_unico_job(cola)

    assert payload["partida_id"] in PARTIDAS_L5R, (
        "la partida NO llegó al alta: el payload encolado sigue sin dimensión "
        f"de partida. payload={sorted(payload)}"
    )
    assert payload["visibility"] == "secret"
    assert payload["workspace"] == "leyenda"

    # Y NO se coló dentro de la colección. La identidad del asset sigue siendo
    # independiente de la ruta y del renombrado (instrucción 6).
    assert "collection_id" not in payload
    assert ":" not in payload["workspace"]


def test_una_fuente_de_capa_juego_no_inventa_partida(real_app, panel_on, cola,
                                                     operador, boveda_montada):
    """El otro lado: `compartido/` es capa juego y viaja SIN partida."""
    html = operador.get(SLOT.prefix).text
    handle = _handle_de(html, "clanes")
    operador.post("/panel/operations/ingestas",
                  data={"fuente": handle, "csrf_token": _csrf_del_formulario(html)})
    _job, payload = _payload_del_unico_job(cola)
    assert payload["partida_id"] is None
    assert payload["visibility"] == "player"


def test_la_partida_llega_hasta_EL_MOTOR_y_alli_falla_cerrado(
        real_app, panel_on, cola, operador, boveda_montada):
    """La prueba de que la partida no se queda en el payload: el motor la ve.

    El motor exige, para ámbito de partida, la SESIÓN DE REVELACIÓN. La carpeta
    `sesion-NN` NO la declara —es contrato de ENTRADA, no una declaración de qué
    se reveló ni a quién— y derivarla sería conceder conocimiento por inferencia
    de directorio, que es justo lo prohibido (instrucción 10).

    Así que este recorrido termina en ERROR, y esa es la conducta correcta: el
    diagnóstico exacto lo demuestra. Si la partida NO llegase al motor, la
    ingesta terminaría «correctamente» en capa juego — silenciosamente en el
    ámbito equivocado, que es el desenlace que este corte existe para impedir.
    """
    html = operador.get(SLOT.prefix).text
    handle = _handle_de(html, "impostor")
    operador.post("/panel/operations/ingestas",
                  data={"fuente": handle, "csrf_token": _csrf_del_formulario(html)})

    store = jobs_client._load_job_store()
    job_id = store.list_jobs(status="pending", db_path=str(cola))[0]["job_id"]
    _correr_worker(cola)
    final = store.get_job(job_id, db_path=str(cola))

    assert final["status"] == "failed", (
        "una fuente de partida sin sesión de revelación declarada terminó "
        f"'{final['status']}': el motor no vio la partida, o la degradó a capa "
        "juego y la ingesta pasó por buena en el ámbito equivocado"
    )
    mensaje = final.get("error_message") or ""
    assert "PARTIDA_SIN_SESION_DECLARADA" in mensaje, (
        f"el rojo no dice su causa: {mensaje!r}"
    )
    assert "sesion" in mensaje.lower() or "sesión" in mensaje.lower()
    # Y no se filtra ni la ruta del servidor ni la traza.
    assert str(boveda_montada) not in mensaje
