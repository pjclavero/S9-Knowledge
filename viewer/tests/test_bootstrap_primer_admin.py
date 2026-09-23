"""Bootstrap web del primer administrador: los tres estados y las siete condiciones.

QUE SOSTIENE CADA COSA
----------------------
Los testigos PIDEN LA PANTALLA: `client.get`/`client.post` sobre la aplicacion
real, con su middleware, su arranque y su base en disco. No se interroga un
diccionario de servicio, porque lo que se afirma es «el operador puede hacer
esto con un navegador», y eso solo lo demuestra una peticion.

Lo unico que NO pasa por HTTP es la atomicidad multiproceso: ahi el sujeto es
el candado de SQLite entre PROCESOS distintos, y meterlo en un servidor solo
anadiria ruido entre la barrera y la seccion critica. La medicion equivalente
por HTTP real (uvicorn, 8 peticiones simultaneas) esta en el informe del corte.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PW_VALIDA = "clave-ficticia-de-pruebas-1"


# ---------------------------------------------------------------------------
# Utillaje
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _entorno_limpio():
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    yield
    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()


def _activar(db_path: Path) -> None:
    from app.auth.config import get_auth_settings
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    get_auth_settings.cache_clear()


def _cliente():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


def _con_arranque():
    """Cliente que EJECUTA el arranque de la aplicacion.

    Es lo que distingue el estado A: sin esto, un test podria declarar que «el
    servicio arranca» sin haber ejecutado nunca el codigo de arranque.
    """
    from app.main import app
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


def _csrf(html: str) -> str:
    import re
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "la pantalla no trae token CSRF"
    return m.group(1)


def _crear_admin_por_pantalla(client, username=("admin-ficticio")):
    r = client.get("/setup/admin")
    assert r.status_code == 200, r.status_code
    tok = _csrf(r.text)
    return client.post("/setup/admin", data={
        "username": username, "display_name": "Admin Ficticio",
        "password": PW_VALIDA, "csrf_token": tok,
    })


def _usuarios(db_path: Path):
    con = sqlite3.connect(str(db_path))
    try:
        return list(con.execute("SELECT username, role, is_active FROM users"))
    finally:
        con.close()


# ---------------------------------------------------------------------------
# ESTADO A - auth.db inexistente: el servicio ARRANCA y ofrece la pantalla
# ---------------------------------------------------------------------------

def test_A_sin_base_el_servicio_arranca_y_muestra_configuracion_inicial(tmp_path):
    """ROJO SI: el arranque vuelve a abortar con la base ausente.

    Antes de este corte, `enforce_auth_security` levantaba AUTH_DB_PATH_MISSING
    y `uvicorn` terminaba con RC=3: cero superficie HTTP. Si alguien restaura
    ese fail-closed, `with TestClient(app)` levanta la excepcion del startup y
    este test se pone rojo ANTES de llegar a ninguna asercion.
    """
    db = tmp_path / "nunca-creada" / "auth.db"
    _activar(db)
    assert not db.exists()

    with _con_arranque() as c:
        r = c.get("/setup/admin")
        assert r.status_code == 200, (
            "SIN BASE, LA INSTALACION NO OFRECE CONFIGURACION INICIAL: "
            f"/setup/admin respondio {r.status_code}")
        assert "Configuración inicial" in r.text

    assert db.exists(), "el arranque no creo la base de la primera instalacion"
    assert _usuarios(db) == [], "una instalacion nueva no trae usuarios"


# ---------------------------------------------------------------------------
# ESTADO B - base creada, bootstrap pendiente: /login CONDUCE a /setup/admin
# ---------------------------------------------------------------------------

def test_B_login_no_finge_credenciales_incorrectas(tmp_path):
    """ROJO SI: el login vuelve a responder «usuario o contrasena incorrectos».

    Ese mensaje, sobre una instalacion sin ningun usuario, atribuye a un error
    del operador lo que causa una instalacion sin administrador.
    """
    db = tmp_path / "auth.db"
    _activar(db)
    from app.auth import db as auth_db
    auth_db.ensure_migrated(db)

    with _con_arranque() as c:
        get = c.get("/login")
        assert get.status_code == 303, (
            "EL LOGIN NO CONDUCE A LA CONFIGURACION INICIAL: "
            f"GET /login respondio {get.status_code}")
        assert get.headers["location"] == "/setup/admin"

        post = c.post("/login", data={
            "username": "usuario-ficticio", "password": "da-igual-lo-que-ponga",
            "csrf_token": "x", "next": "/",
        })
        assert post.status_code == 303, (
            "EL LOGIN FINGE UN ERROR DE CREDENCIALES SOBRE UNA INSTALACION "
            f"SIN ADMINISTRADOR: POST /login respondio {post.status_code}")
        assert post.headers["location"] == "/setup/admin"
        assert "incorrect" not in post.text.lower()


# ---------------------------------------------------------------------------
# ESTADO C - bootstrap completado
# ---------------------------------------------------------------------------

def test_C_completado_la_ruta_no_existe_en_GET_ni_en_POST(tmp_path):
    """CONDICION 2. ROJO SI: el POST deja de comprobar el estado en servidor.

    El caso que importa no es el enlace que no se pinta: es el `curl` que va
    directo al POST sin pasar por el GET.
    """
    db = tmp_path / "auth.db"
    _activar(db)
    with _con_arranque() as c:
        assert _crear_admin_por_pantalla(c).status_code == 303

        assert c.get("/setup/admin").status_code == 404
        directo = c.post("/setup/admin", data={
            "username": "intruso-ficticio", "password": PW_VALIDA, "csrf_token": "x",
        })
        assert directo.status_code == 404, (
            "EL POST NO COMPRUEBA EL ESTADO EN SERVIDOR: con el bootstrap "
            f"completado, POST directo respondio {directo.status_code}")
    assert [u[0] for u in _usuarios(db)] == ["admin-ficticio"]


def test_C_el_login_normal_y_admin_users_new_siguen_funcionando(tmp_path):
    """EL SIMETRICO. ROJO SI: la puerta se cierra de mas.

    Cerrar `/setup/admin` no puede llevarse por delante el camino normal de
    alta de usuarios. Se recorre entero: login real del administrador recien
    creado y GET de la pantalla existente con su sesion.
    """
    db = tmp_path / "auth.db"
    _activar(db)
    with _con_arranque() as c:
        assert _crear_admin_por_pantalla(c).status_code == 303

        pagina = c.get("/login")
        assert pagina.status_code == 200
        entrada = c.post("/login", data={
            "username": "admin-ficticio", "password": PW_VALIDA,
            "csrf_token": _csrf(pagina.text), "next": "/",
        })
        assert entrada.status_code == 302, (
            "EL LOGIN NORMAL DEJO DE FUNCIONAR TRAS EL BOOTSTRAP: "
            f"respondio {entrada.status_code}")
        nuevo = c.get("/admin/users/new")
        assert nuevo.status_code == 200, (
            "LA PUERTA SE CERRO DE MAS: /admin/users/new respondio "
            f"{nuevo.status_code} tras el bootstrap")
        assert c.get("/admin/users").status_code == 200


# ---------------------------------------------------------------------------
# CONDICION 1 + EL NEGATIVO MAS IMPORTANTE
# ---------------------------------------------------------------------------

def test_cond1_quedarse_sin_administradores_NO_reabre_la_puerta(tmp_path):
    """EL NEGATIVO. ROJO SI: la puerta se decide por `count_active_admins()`.

    Se ejercita de verdad: se completa el bootstrap, se BORRA al unico
    administrador (y, en el segundo tramo, se DESACTIVA), y se vuelve a pedir
    la pantalla por GET y por POST.
    """
    db = tmp_path / "auth.db"
    _activar(db)
    from app.auth import db as auth_db

    with _con_arranque() as c:
        assert _crear_admin_por_pantalla(c).status_code == 303

        # (a) desactivado
        with auth_db.get_conn(db) as conn:
            uid = conn.execute("SELECT id FROM users").fetchone()[0]
            auth_db.update_user(conn, uid, is_active=False)
            assert auth_db.count_active_admins(conn) == 0
        g = c.get("/setup/admin")
        pp = c.post("/setup/admin", data={
            "username": "intruso-ficticio", "password": PW_VALIDA, "csrf_token": "x"})
        assert (g.status_code, pp.status_code) == (404, 404), (
            "LA PUERTA DE BOOTSTRAP SE REABRIO AL DESACTIVAR AL ULTIMO "
            f"ADMINISTRADOR: GET={g.status_code} POST={pp.status_code}")

        # (b) eliminado
        with auth_db.get_conn(db) as conn:
            conn.execute("DELETE FROM users")
            conn.commit()
            assert auth_db.count_active_admins(conn) == 0
        g = c.get("/setup/admin")
        pp = c.post("/setup/admin", data={
            "username": "intruso-ficticio", "password": PW_VALIDA, "csrf_token": "x"})
        assert (g.status_code, pp.status_code) == (404, 404), (
            "LA PUERTA DE BOOTSTRAP SE REABRIO AL ELIMINAR AL ULTIMO "
            f"ADMINISTRADOR: GET={g.status_code} POST={pp.status_code}")
        assert _usuarios(db) == []


def test_cond1_lo_que_decide_es_el_SELLO_y_no_otra_cosa(tmp_path):
    """Control POSITIVO del test anterior.

    Un 404 puede salir por el motivo equivocado (ruta mal montada, guarda que
    siempre corta). Aqui se retira EL SELLO de `install_state` dejando la base
    igual en todo lo demas, y la pantalla vuelve: eso demuestra que el 404 de
    arriba lo producia el sello y no un apagado generico.
    """
    db = tmp_path / "auth.db"
    _activar(db)
    with _con_arranque() as c:
        assert _crear_admin_por_pantalla(c).status_code == 303
        assert c.get("/setup/admin").status_code == 404

        con = sqlite3.connect(str(db))
        con.execute("DELETE FROM install_state WHERE key = 'bootstrap_completed'")
        con.commit()
        con.close()

        vuelta = c.get("/setup/admin")
        assert vuelta.status_code == 200, (
            "RETIRAR EL SELLO NO REABRE LA PANTALLA: el 404 anterior no lo "
            f"producia el sello. Respondio {vuelta.status_code}")


# ---------------------------------------------------------------------------
# CONDICION 3 - atomicidad con concurrencia REAL
# ---------------------------------------------------------------------------

def _intento_en_proceso(args):
    db_path, i, cola = args
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.auth import bootstrap
    try:
        bootstrap.crear_primer_admin(
            Path(db_path), username=f"admin-concurrente-{i}",
            display_name=f"Admin {i}", password_hash="hash-ficticio-no-verificable",
        )
        return "creado"
    except bootstrap.BootstrapCerrado:
        return "rechazado"


def _worker(db_path, i, cola, barrera):
    barrera.wait()
    cola.put(_intento_en_proceso((db_path, i, cola)))


def test_cond3_ocho_procesos_a_la_vez_producen_exactamente_un_administrador(tmp_path):
    """CONDICION 3. ROJO SI: la exclusion vuelve a ser «leer y luego escribir».

    Ocho PROCESOS —concurrencia real de SQLite, no hilos de un mismo
    interprete— sueltos a la vez sobre la misma base tras una barrera. Si la
    puerta fuese `if count_active_admins() == 0:` seguido de un INSERT, varios
    leerian 0 y entrarian: el recuento de usuarios saldria > 1 y este test se
    pondria rojo por esa causa exacta.
    """
    db = tmp_path / "auth.db"
    _activar(db)
    from app.auth import db as auth_db
    auth_db.ensure_migrated(db)

    n = 8
    ctx = mp.get_context("fork")
    barrera = ctx.Barrier(n)
    cola = ctx.Queue()
    procesos = [ctx.Process(target=_worker, args=(str(db), i, cola, barrera))
                for i in range(n)]
    for p in procesos:
        p.start()
    for p in procesos:
        p.join(timeout=60)

    resultados = [cola.get() for _ in range(n)]
    assert resultados.count("creado") == 1, (
        "LA CREACION DEL PRIMER ADMINISTRADOR NO ES ATOMICA: "
        f"{resultados.count('creado')} procesos crearon administrador. {resultados}")
    assert resultados.count("rechazado") == n - 1, resultados

    usuarios = _usuarios(db)
    assert len(usuarios) == 1, (
        "LA CREACION DEL PRIMER ADMINISTRADOR NO ES ATOMICA: la base tiene "
        f"{len(usuarios)} administradores iniciales. {usuarios}")
    assert usuarios[0][1] == "admin"


# ---------------------------------------------------------------------------
# CONDICION 4 - CSRF real durante el bootstrap
# ---------------------------------------------------------------------------

def test_cond4_csrf_invalido_rechaza_y_no_crea_nada(tmp_path):
    """CONDICION 4. ROJO SI: el bootstrap se salta el CSRF «porque aun no hay sesion».

    Se comprueban las dos mitades del double-submit: token inventado con cookie
    buena, y token bueno SIN su cookie.
    """
    db = tmp_path / "auth.db"
    _activar(db)
    with _con_arranque() as c:
        pagina = c.get("/setup/admin")
        tok = _csrf(pagina.text)

        inventado = c.post("/setup/admin", data={
            "username": "admin-ficticio", "password": PW_VALIDA,
            "csrf_token": "0.0.token-inventado",
        })
        assert inventado.status_code == 403, (
            "EL BOOTSTRAP ACEPTA UN POST SIN CSRF VALIDO: "
            f"respondio {inventado.status_code}")
        assert _usuarios(db) == []

        c.cookies.clear()
        sin_cookie = c.post("/setup/admin", data={
            "username": "admin-ficticio", "password": PW_VALIDA, "csrf_token": tok,
        })
        assert sin_cookie.status_code == 403, (
            "EL BOOTSTRAP ACEPTA UN POST SIN CSRF VALIDO (falta la cookie del "
            f"double-submit): respondio {sin_cookie.status_code}")
        assert _usuarios(db) == []


def test_cond4_un_token_de_login_no_sirve_en_el_bootstrap(tmp_path):
    """El `purpose` firmado. ROJO SI: los dos formularios anonimos comparten token.

    Un token emitido para `/login` esta firmado con `login:`; si la firma
    dejase de llevar el proposito, este token valdria en `/setup/admin` y el
    POST saldria 303 en vez de 403.
    """
    db = tmp_path / "auth.db"
    _activar(db)
    from app.auth.config import get_auth_settings
    from app.auth.csrf import SETUP_CSRF_COOKIE, issue_login_csrf

    with _con_arranque() as c:
        ajeno = issue_login_csrf(get_auth_settings().S9K_CSRF_SECRET)  # purpose=login
        c.cookies.set(SETUP_CSRF_COOKIE, ajeno)
        r = c.post("/setup/admin", data={
            "username": "admin-ficticio", "password": PW_VALIDA, "csrf_token": ajeno,
        })
        assert r.status_code == 403, (
            "UN TOKEN CSRF EMITIDO PARA OTRO FORMULARIO VALE EN EL BOOTSTRAP: "
            f"respondio {r.status_code}")
        assert _usuarios(db) == []


# ---------------------------------------------------------------------------
# CONDICION 5 - el navegador NO decide el rol
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rol_enviado", ["viewer", "reviewer", "admin", "superadmin"])
def test_cond5_el_rol_enviado_por_el_cliente_se_ignora(tmp_path, rol_enviado):
    """CONDICION 5. ROJO SI: el endpoint empieza a aceptar `role` del formulario.

    El usuario resultante es admin SIEMPRE, y con cualquier valor: ni un
    `role=viewer` degrada la operacion ni un `role=superadmin` inventa un rol.
    """
    db = tmp_path / "auth.db"
    _activar(db)
    with _con_arranque() as c:
        pagina = c.get("/setup/admin")
        r = c.post("/setup/admin", data={
            "username": "admin-ficticio", "display_name": "Admin",
            "role": rol_enviado, "password": PW_VALIDA,
            "csrf_token": _csrf(pagina.text),
        })
        assert r.status_code == 303, r.status_code
    usuarios = _usuarios(db)
    assert usuarios == [("admin-ficticio", "admin", 1)], (
        "EL NAVEGADOR DECIDIO EL ROL DEL PRIMER ADMINISTRADOR: "
        f"se envio role={rol_enviado!r} y la base guardo {usuarios}")


def test_cond5_el_endpoint_no_declara_ningun_parametro_de_rol():
    """La misma condicion, por la firma. ROJO SI: alguien anade `role: str = Form(...)`.

    El test de arriba se quedaria verde si el parametro existiese pero el valor
    se sobreescribiese despues; este mira la FIRMA (via `inspect`, no texto) y
    se pone rojo en cuanto aparece el parametro.

    TECHO DECLARADO: esto ve los parametros del endpoint. No veria un rol que
    llegase por otra via (cabecera leida del `Request`, o una dependencia). Lo
    que cubre esa otra via es el test parametrizado de arriba, que mira el
    EFECTO en la base.
    """
    import inspect
    from app.routers.setup import setup_admin_submit

    params = set(inspect.signature(setup_admin_submit).parameters)
    assert "role" not in params, (
        "EL ENDPOINT DEL BOOTSTRAP DECLARA UN PARAMETRO DE ROL: "
        f"{sorted(params)}")
    assert "rol" not in params, params


# ---------------------------------------------------------------------------
# CONDICION 6 - las mismas reglas de usuario y contrasena
# ---------------------------------------------------------------------------

def test_cond6_las_reglas_son_LAS_MISMAS_funcion_que_la_pantalla_existente(tmp_path):
    """CONDICION 6. ROJO SI: el bootstrap se monta su propio validador.

    Se ejerce la regla en las DOS pantallas con el MISMO material y se exige el
    mismo desenlace. Si el bootstrap relajase el minimo a 8 caracteres, aqui
    saldria 303 donde la pantalla existente sigue dando 400.
    """
    db = tmp_path / "auth.db"
    _activar(db)
    from app.auth.passwords import MIN_LENGTH

    corta = "a" * (MIN_LENGTH - 1)
    with _con_arranque() as c:
        pagina = c.get("/setup/admin")
        r = c.post("/setup/admin", data={
            "username": "admin-ficticio", "password": corta,
            "csrf_token": _csrf(pagina.text),
        })
        assert r.status_code == 400, (
            "EL BOOTSTRAP NO APLICA LAS MISMAS REGLAS DE CONTRASENA QUE "
            f"/admin/users/new: una de {MIN_LENGTH - 1} caracteres dio "
            f"{r.status_code}")
        assert str(MIN_LENGTH) in r.text
        assert _usuarios(db) == []

        # Segunda regla de la misma funcion: contrasena igual al usuario.
        pagina = c.get("/setup/admin")
        r = c.post("/setup/admin", data={
            "username": "usuarioficticiolargo", "password": "usuarioficticiolargo",
            "csrf_token": _csrf(pagina.text),
        })
        assert r.status_code == 400, (
            "EL BOOTSTRAP NO APLICA LAS MISMAS REGLAS: contrasena igual al "
            f"nombre de usuario dio {r.status_code}")
        assert _usuarios(db) == []


def test_cond6_usuario_vacio_rechazado(tmp_path):
    """ROJO SI: se puede crear un administrador sin nombre.

    La pantalla existente se apoya en el `required` del HTML; aqui la comprueba
    el servidor, porque un `curl` no ejecuta HTML.
    """
    db = tmp_path / "auth.db"
    _activar(db)
    with _con_arranque() as c:
        pagina = c.get("/setup/admin")
        r = c.post("/setup/admin", data={
            "username": "   ", "password": PW_VALIDA, "csrf_token": _csrf(pagina.text),
        })
        assert r.status_code == 400, (
            "SE PUEDE CREAR UN ADMINISTRADOR SIN NOMBRE DE USUARIO: "
            f"respondio {r.status_code}")
        assert _usuarios(db) == []


# ---------------------------------------------------------------------------
# CONDICION 7 - AUSENCIA != ERROR
# ---------------------------------------------------------------------------

def test_cond7_base_corrupta_NO_es_primera_instalacion(tmp_path):
    """CONDICION 7. ROJO SI: un almacen ilegible se lee como «instalacion nueva».

    Es la distincion que mas facil se pierde: si `estado_instalacion` colapsase
    el fallo de lectura a «pendiente», esta peticion devolveria 200 con el
    formulario de crear administrador sobre una base que quiza tiene datos.
    Aqui se exige 503 con CODIGO, y que la ruta del servidor no viaje al
    cliente (repo publico).
    """
    db = tmp_path / "auth.db"
    _activar(db)
    from app.auth import db as auth_db
    auth_db.ensure_migrated(db)

    with _con_arranque() as c:
        assert c.get("/setup/admin").status_code == 200  # antes de romperla
        for sufijo in ("", "-wal", "-shm"):
            p = Path(str(db) + sufijo)
            if p.exists() and sufijo:
                p.unlink()
        db.write_bytes(b"esto no es una base sqlite\n")

        r = c.get("/setup/admin")
        assert r.status_code == 503, (
            "UN ALMACEN DE AUTH ILEGIBLE SE ESTA LEYENDO COMO PRIMERA "
            f"INSTALACION: /setup/admin respondio {r.status_code}")
        assert "AUTH_STORE_UNAVAILABLE" in r.text
        assert "S9K_AUTH_DB_PATH" in r.text, "la pantalla no nombra la variable"
        assert str(tmp_path) not in r.text, "se ha filtrado una ruta del servidor"

        post = c.post("/setup/admin", data={
            "username": "admin-ficticio", "password": PW_VALIDA, "csrf_token": "x",
        })
        assert post.status_code == 503, post.status_code


def test_cond7_base_ausente_SI_es_primera_instalacion(tmp_path):
    """El otro lado de la condicion 7. ROJO SI: la ausencia se trata como error.

    Sin este control, cerrar el caso corrupto se podria «arreglar» cerrando
    tambien el ausente, y la propiedad entera desapareceria.
    """
    db = tmp_path / "no-existe" / "auth.db"
    _activar(db)
    with _con_arranque() as c:
        r = c.get("/setup/admin")
        assert r.status_code == 200, (
            "LA AUSENCIA DE BASE SE ESTA TRATANDO COMO ERROR: "
            f"/setup/admin respondio {r.status_code}")


# ---------------------------------------------------------------------------
# COMPATIBILIDAD HACIA ATRAS
# ---------------------------------------------------------------------------

def _base_v3(tmp_path: Path, con_usuarios: bool) -> Path:
    """Base con el ESQUEMA ANTERIOR (v3), sin `install_state`.

    Se construye ejecutando el DDL v1..v3 tal y como lo tiene el modulo y
    sellando `schema_version = 3`: es la forma que tiene en disco una
    instalacion desplegada antes de este corte.
    """
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password

    db = tmp_path / "auth.db"
    con = sqlite3.connect(str(db))
    for stmt in auth_db._DDL:
        con.execute(stmt)
    for stmt in auth_db._DDL_V2_ALTER + auth_db._DDL_V2_CREATE + auth_db._DDL_V3_ALTER:
        try:
            con.execute(stmt)
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise
    con.execute("INSERT OR REPLACE INTO schema_version (version, applied_at) "
                "VALUES (3, '2026-01-01T00:00:00')")
    if con_usuarios:
        con.execute(
            "INSERT INTO users (username, display_name, password_hash, role, is_active,"
            " must_change_password, created_at, updated_at, failed_login_count, created_by)"
            " VALUES ('admin-cli-ficticio','Admin CLI',?,'admin',1,0,"
            "'2026-01-01T00:00:00','2026-01-01T00:00:00',0,'cli')",
            (hash_password(PW_VALIDA),),
        )
    con.commit()
    con.close()
    assert "install_state" not in {
        r[0] for r in sqlite3.connect(str(db)).execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
    }
    return db


def test_compat_instalacion_con_admin_de_CLI_queda_CERRADA(tmp_path):
    """EL CASO MAS PELIGROSO. ROJO SI: migrar a v4 deja el bootstrap ABIERTO.

    Una instalacion ya desplegada, con administradores creados por la CLI
    antes de que existiese esta pantalla, no puede despertar con una puerta
    anonima de creacion de administrador. Aqui se migra de verdad (v3 -> v4) y
    se comprueba por HTTP que la pantalla NO existe y que el login de siempre
    sigue funcionando.
    """
    db = _base_v3(tmp_path, con_usuarios=True)
    _activar(db)
    with _con_arranque() as c:
        g = c.get("/setup/admin")
        pp = c.post("/setup/admin", data={
            "username": "intruso-ficticio", "password": PW_VALIDA, "csrf_token": "x"})
        assert (g.status_code, pp.status_code) == (404, 404), (
            "UNA INSTALACION QUE YA TENIA ADMINISTRADORES POR CLI DESPIERTA "
            f"CON LA PUERTA ANONIMA ABIERTA: GET={g.status_code} POST={pp.status_code}")

        pagina = c.get("/login")
        assert pagina.status_code == 200
        entrada = c.post("/login", data={
            "username": "admin-cli-ficticio", "password": PW_VALIDA,
            "csrf_token": _csrf(pagina.text), "next": "/",
        })
        assert entrada.status_code == 302, entrada.status_code
        assert c.get("/admin/users/new").status_code == 200


def test_compat_instalacion_v3_sin_usuarios_queda_PENDIENTE(tmp_path):
    """El simetrico. ROJO SI: se cierra el bootstrap de toda base preexistente.

    Una base v3 creada pero nunca provisionada es exactamente el estado B: hay
    que ofrecerle la configuracion inicial, no dejarla inservible.
    """
    db = _base_v3(tmp_path, con_usuarios=False)
    _activar(db)
    with _con_arranque() as c:
        r = c.get("/setup/admin")
        assert r.status_code == 200, (
            "UNA BASE PREEXISTENTE SIN USUARIOS SE QUEDA SIN CONFIGURACION "
            f"INICIAL: /setup/admin respondio {r.status_code}")
        assert c.get("/login").status_code == 303


def test_compat_create_admin_de_la_CLI_cierra_el_bootstrap(tmp_path):
    """ROJO SI: provisionar por terminal deja la puerta anonima abierta.

    `cli.auth create-admin` es una via legitima y vigente de crear el primer
    administrador; si no sellase el bootstrap, la instalacion quedaria con
    `/setup/admin` sirviendo a cualquiera.
    """
    db = tmp_path / "auth.db"
    _activar(db)
    from app.auth import bootstrap, db as auth_db
    from app.auth.passwords import hash_password

    auth_db.ensure_migrated(db)
    with auth_db.get_conn(db) as conn:
        auth_db.create_user(conn, username="admin-cli-ficticio",
                            display_name="Admin CLI",
                            password_hash=hash_password(PW_VALIDA), role="admin")
        bootstrap.marcar_completado(conn)

    with _con_arranque() as c:
        r = c.get("/setup/admin")
        assert r.status_code == 404, (
            "PROVISIONAR POR CLI DEJA LA PUERTA ANONIMA ABIERTA: "
            f"/setup/admin respondio {r.status_code}")


# ---------------------------------------------------------------------------
# La pantalla no existe con la autenticacion apagada
# ---------------------------------------------------------------------------

def test_sin_auth_activa_la_pantalla_no_existe(tmp_path):
    """ROJO SI: `/setup/admin` sirve con `S9K_AUTH_ENABLED=false`.

    Con la autenticacion apagada no hay administradores que crear: crear uno
    ahi solo dejaria el sello puesto y un usuario que nadie consulta.
    """
    from app.auth.config import get_auth_settings
    os.environ["S9K_AUTH_ENABLED"] = "false"
    os.environ["S9K_AUTH_DB_PATH"] = str(tmp_path / "auth.db")
    get_auth_settings.cache_clear()
    with _con_arranque() as c:
        assert c.get("/setup/admin").status_code == 404
        assert c.post("/setup/admin", data={
            "username": "admin-ficticio", "password": PW_VALIDA, "csrf_token": "x",
        }).status_code == 404
