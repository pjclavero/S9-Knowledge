"""Hueco B del chasis — Operations Dashboard, SOLO LECTURA.

REGLA DE ESTA SUITE, heredada de `test_chassis_mount_contract.py` y de la del
hueco C: todo lo que sea HTTP se prueba contra la aplicación REAL
(`app.main.app`). Aquí no se construye ningún `FastAPI()` de mentira salvo para
calibrar el instrumento de enumeración (los dos tests de frontera de segmento,
que necesitan una app con un defecto plantado).

DÓNDE SE INYECTA EL MATERIAL, y por qué ahí
-------------------------------------------
Se sustituyen `jobs_client.list_jobs` / `get_counts_by_status` /
`jobs_db_status`, que son las lecturas CRUDAS del puente, y NO
`scoped_jobs`/`scoped_counts`. La diferencia importa: sustituyendo las de
arriba, el filtrado por ámbito de producción sigue ejecutándose sobre el
material del test, así que las pruebas de aislamiento miden el código real.
Sustituyendo las de abajo, el ámbito no se ejercitaría y todas ellas serían
adorno.

Sobre la sustitución de dependencias: `get_visibility_context` se llama como
FUNCIÓN NORMAL desde `get_filtered_provider` y desde `get_visibility_scope`
(`app/authz/dependencies.py`), así que sobrescribirlo con
`dependency_overrides` es INERTE y sale verde sin morder. Lo que sí entra por
`Depends` en este router es `get_visibility_scope`, y es lo que se sustituye,
con un control de colapso (`test_la_sustitucion_de_ambito_muerde`) que exige
que sin la sustitución el resultado CAMBIE.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import jobs_client
from app.authz.context import build_viewer_context
from app.authz.dependencies import get_visibility_scope
from app.authz.scope import VisibilityScope
from app.chassis import FEATURE_SLOTS, route_index, slot_flag_env
from app.routers import chassis_operations as panel

SLOT = next(s for s in FEATURE_SLOTS if s.key == "B")
FLAG = slot_flag_env(SLOT)
PASSWORD = "PanelBTest_1234567890!"

METODOS_DE_ESCRITURA = {"POST", "PUT", "PATCH", "DELETE"}


# ---------------------------------------------------------------------------
# Material de prueba
# ---------------------------------------------------------------------------

def make_job(
    job_id: str,
    *,
    workspace: str = "bruma",
    status: str = "pending",
    job_type: str = "ingest",
    partida_id: str | None = None,
    attempts: int = 0,
    error_message: str | None = None,
) -> dict:
    """Una fila CRUDA de la cola, tal y como la devuelve `job_store.list_jobs`."""
    payload: dict = {"origen": "test"}
    if partida_id:
        payload["partida_id"] = partida_id
    return {
        "job_id": job_id,
        "workspace": workspace,
        "status": status,
        "job_type": job_type,
        "source_kind": None,
        "created_at": "2026-08-01T10:00:00+00:00",
        "updated_at": "2026-08-01T11:00:00+00:00",
        "attempts": attempts,
        "max_attempts": 3,
        "payload_json": json.dumps(payload),
        "result_json": None,
        "error_message": error_message,
        "error_code": "E_TEST" if error_message else None,
    }


# ---------------------------------------------------------------------------
# Fixtures — app REAL, interruptor REAL, ámbito REAL
# ---------------------------------------------------------------------------

@pytest.fixture
def real_app():
    from app.main import app
    return app


@pytest.fixture(autouse=True)
def _reset_auth_settings():
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    yield
    os.environ.pop("S9K_AUTH_ENABLED", None)
    os.environ.pop("S9K_AUTH_DB_PATH", None)
    get_auth_settings.cache_clear()


@pytest.fixture(autouse=True)
def _health_report_aislado(tmp_path, monkeypatch):
    """El informe de salud vive en un tmp: la suite jamás mira ni toca el real."""
    monkeypatch.setenv("S9K_HEALTH_REPORT_PATH", str(tmp_path / "health" / "last.json"))


@pytest.fixture
def panel_on():
    """Enciende SOLO el hueco B. Los interruptores fallan cerrados."""
    previo = os.environ.get(FLAG)
    os.environ[FLAG] = "true"
    yield
    if previo is None:
        os.environ.pop(FLAG, None)
    else:
        os.environ[FLAG] = previo


@pytest.fixture
def with_jobs(monkeypatch):
    """Instala una cola DISPONIBLE con el material dado, en la capa cruda.

    Ver la cabecera del módulo: se sustituye la lectura cruda para que
    `scoped_jobs`/`scoped_counts` —el filtrado real por ámbito— sí se ejecuten.
    """
    def install(jobs: list[dict]) -> list[dict]:
        monkeypatch.setattr(
            jobs_client, "jobs_db_status",
            lambda: {"ok": True, "db_path": "/ruta/secreta/del/servidor/jobs.db"},
        )

        def _list(workspace=None, status=None, job_type=None, limit=100):
            filas = jobs
            if workspace is not None:
                filas = [j for j in filas if j.get("workspace") == workspace]
            if status is not None:
                filas = [j for j in filas if j.get("status") == status]
            if job_type is not None:
                filas = [j for j in filas if j.get("job_type") == job_type]
            return filas[:limit]

        def _counts(workspace=None, db_path=None):
            salida: dict[str, int] = {}
            for j in _list(workspace=workspace, limit=1_000_000):
                salida[j["status"]] = salida.get(j["status"], 0) + 1
            return salida

        monkeypatch.setattr(jobs_client, "list_jobs", _list)
        monkeypatch.setattr(jobs_client, "get_counts_by_status", _counts)
        return jobs

    return install


@pytest.fixture
def sin_cola(monkeypatch):
    """La cola NO está disponible: es el caso por defecto de un banco limpio."""
    monkeypatch.setattr(
        jobs_client, "jobs_db_status",
        lambda: {"ok": False, "error": "jobs_db_not_found",
                 "db_path": "/ruta/secreta/del/servidor/jobs.db"},
    )


@pytest.fixture
def with_scope(real_app):
    """Sustituye `get_visibility_scope`, que SÍ entra por `Depends` aquí."""
    def install(scope: VisibilityScope) -> None:
        real_app.dependency_overrides[get_visibility_scope] = lambda: scope

    yield install
    real_app.dependency_overrides.pop(get_visibility_scope, None)


def anon_scope() -> VisibilityScope:
    """Ámbito de un anónimo con auth DESACTIVADA: el que produce el P0."""
    return VisibilityScope(build_viewer_context(
        role=None, auth_enabled=False, default_workspace="bruma",
    ))


def player_scope(partida: str | None, workspace: str = "bruma") -> VisibilityScope:
    return VisibilityScope(build_viewer_context(
        role="viewer", auth_enabled=True, default_workspace=workspace,
        active_partida=partida,
    ))


def client(app, cookie: str | None = None) -> TestClient:
    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    if cookie:
        from app.auth.config import get_auth_settings
        c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, cookie)
    return c


@pytest.fixture
def auth_on(tmp_path):
    db_path = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    from app.auth import db as auth_db_mod
    auth_db_mod.ensure_migrated(db_path)
    return db_path


def login_cookie(db_path: Path, username: str, role: str) -> str:
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



@pytest.fixture
def operador(real_app, auth_on):
    """Cliente de un ADMIN autenticado de verdad, que es quien abre este hueco.

    El rol publicado de B es `admin` y su guarda es `require_admin`, así que a
    diferencia del hueco C aquí NO hay forma de llegar al cuerpo del panel sin
    principal: con la auth desactivada la guarda redirige a /login (medido, y
    fijado en `test_sin_auth_no_reaparece_el_comportamiento_permisivo`). Todo
    test que necesite ver la pantalla entra por esta puerta, la de verdad.

    El ÁMBITO DE DATOS se sustituye aparte (`with_scope`): la puerta y el
    recorte de contenido son dos cosas distintas, y este panel las mantiene
    separadas igual que el resto del visor.
    """
    c = client(real_app, login_cookie(auth_on, "panelb_operador", "admin"))
    c.headers.update({"accept": "text/html"})
    return c


def _ids_de_la_lista(html: str) -> list[str]:
    return re.findall(r'<tr data-job-id="([^"]+)"', html)


# ===========================================================================
# 0. El arnés muerde (control de colapso). Sin esto, todo lo demás es adorno.
# ===========================================================================

def test_el_arnes_no_pasa_con_cero_casos(with_jobs):
    """Un arnés que pasa con 0 casos está roto: aquí se exige material.

    Y se exige que el material LLEGUE por el camino de producción
    (`scoped_jobs` con ámbito sin restricciones), no sólo que la fixture haya
    devuelto una lista.
    """
    with_jobs([make_job("j1"), make_job("j2")])
    from app.authz.scope import UNRESTRICTED

    assert len(jobs_client.scoped_jobs(UNRESTRICTED)) == 2


def test_la_sustitucion_de_ambito_muerde(real_app, panel_on, with_jobs, with_scope, operador):
    """Con la sustitución la fila se oculta; SIN ella, reaparece.

    Si quitar la sustitución no cambiara el resultado, el ámbito no estaría
    haciendo nada y ninguna prueba de aislamiento de abajo valdría.
    """
    with_jobs([make_job("j-a", partida_id="partida-A")])

    with_scope(player_scope("partida-A"))
    con = operador.get(SLOT.prefix)
    assert "j-a" in con.text

    with_scope(player_scope("partida-B"))
    sin = operador.get(SLOT.prefix)
    assert "j-a" not in sin.text, (
        "El ámbito sustituido no cambia el resultado: el arnés no muerde."
    )


# ===========================================================================
# 1. Montaje sobre el chasis: contrato publicado, no una ruta inventada
# ===========================================================================

def test_el_panel_se_monta_en_el_prefijo_del_contrato(real_app):
    index = route_index(real_app)
    assert index[SLOT.route_name] == "/panel/operations"


def test_la_plantilla_no_lleva_urls_escritas_a_mano():
    """Fallo nº 2 del chasis: un enlace literal no avisa cuando la ruta cambia.

    Se exige que el prefijo publicado NO aparezca como literal en el MARCADO.
    Los comentarios Jinja (`{# ... #}`) se retiran antes de mirar: una ruta
    MENCIONADA en un comentario no crea ningún enlace, y contarla sería el
    falso positivo de "citar es afirmar" ya registrado en este repo.
    """
    ruta = Path(panel.__file__).resolve().parent.parent / "templates" / "chassis" / "operations.html"
    marcado = re.sub(r"\{#.*?#\}", "", ruta.read_text(encoding="utf-8"), flags=re.S)
    assert SLOT.prefix not in marcado, f"operations.html escribe {SLOT.prefix!r} a mano"
    assert "url_for(" in marcado


def test_la_plantilla_no_ofrece_ningun_formulario_de_escritura():
    """Frontera de producto: el único formulario es un GET de filtros.

    Un `method="post"` en la plantilla sería una acción ofrecida al humano
    aunque el backend la rechazara; y la enumeración de rutas no lo vería.
    """
    ruta = Path(panel.__file__).resolve().parent.parent / "templates" / "chassis" / "operations.html"
    marcado = re.sub(r"\{#.*?#\}", "", ruta.read_text(encoding="utf-8"), flags=re.S)
    for metodo in ("post", "put", "patch", "delete"):
        assert f'method="{metodo}"' not in marcado.lower(), (
            f"La plantilla ofrece un formulario {metodo.upper()}"
        )
    assert marcado.lower().count('method="get"') == 1


# ===========================================================================
# 2. Interruptor del hueco: apagado por defecto, y DESPUÉS de la guarda
# ===========================================================================

def test_sin_el_interruptor_el_panel_no_se_sirve(real_app, with_jobs, with_scope, operador):
    """Ausente el flag, 404: igual que una ruta que no existe."""
    os.environ.pop(FLAG, None)
    with_jobs([make_job("j1")])
    with_scope(anon_scope())
    assert operador.get(SLOT.prefix).status_code == 404


@pytest.mark.parametrize("valor", ["", "false", "0", "quizas", "TRUE ", "yes"])
def test_solo_true_y_1_encienden_el_panel(real_app, with_jobs, with_scope, valor, operador):
    """Un valor que no se entiende es un dato ausente, no un permiso."""
    with_jobs([make_job("j1")])
    with_scope(anon_scope())
    previo = os.environ.get(FLAG)
    os.environ[FLAG] = valor
    try:
        esperado = 200 if valor.strip().lower() in {"true", "1"} else 404
        assert operador.get(SLOT.prefix).status_code == esperado
    finally:
        if previo is None:
            os.environ.pop(FLAG, None)
        else:
            os.environ[FLAG] = previo


def test_un_anonimo_no_puede_enumerar_si_el_panel_esta_encendido(real_app, auth_on):
    """Con auth activa, el anónimo recibe LO MISMO esté encendido o apagado.

    El interruptor se evalúa DESPUÉS de la guarda a propósito: si se evaluara
    antes, comparar 404 contra 302 diría qué paneles están encendidos.
    """
    respuestas = []
    previo = os.environ.get(FLAG)
    try:
        for valor in ("true", "false"):
            os.environ[FLAG] = valor
            r = client(real_app).get(SLOT.prefix, headers={"accept": "text/html"})
            respuestas.append((r.status_code, r.headers.get("location")))
    finally:
        if previo is None:
            os.environ.pop(FLAG, None)
        else:
            os.environ[FLAG] = previo
    assert respuestas[0] == respuestas[1], (
        f"El anónimo distingue encendido de apagado: {respuestas}"
    )
    assert respuestas[0][0] == 302


# ===========================================================================
# 3. Autorización: la actual manda. Sin auth = sin principal = sin autoridad.
# ===========================================================================

def test_con_auth_activa_el_anonimo_va_a_login(real_app, auth_on, panel_on, with_jobs):
    with_jobs([make_job("j1")])
    r = client(real_app).get(SLOT.prefix, headers={"accept": "text/html"})
    assert r.status_code == 302 and "/login" in r.headers["location"]


def test_con_auth_activa_el_rol_reviewer_no_entra(real_app, auth_on, panel_on, with_jobs):
    """`admin` es el rol MÍNIMO publicado: el inferior recibe 403."""
    with_jobs([make_job("j1")])
    cookie = login_cookie(auth_on, "panelb_reviewer", "reviewer")
    r = client(real_app, cookie).get(SLOT.prefix, headers={"accept": "text/html"})
    assert r.status_code == 403


def test_con_auth_activa_el_rol_admin_entra(real_app, auth_on, panel_on, sin_cola):
    cookie = login_cookie(auth_on, "panelb_admin", "admin")
    r = client(real_app, cookie).get(SLOT.prefix, headers={"accept": "text/html"})
    assert r.status_code == 200


def test_sin_auth_no_reaparece_el_comportamiento_permisivo(
    real_app, panel_on, with_jobs, tmp_path
):
    """EL TEST DE ESTE CARRIL, y es BIDIRECCIONAL.

    Mitad A — con `S9K_AUTH_ENABLED` desactivado no hay principal, luego no hay
    autoridad (docs/75): la guarda del hueco `admin` es `require_admin`, así que
    el panel NO se sirve y no se entrega ni un identificador de trabajo. Si
    alguien devolviera este hueco a una guarda no-op (que es lo que hacía
    `html_role_guard` con la auth apagada, y por lo que el panel de
    administración quedaba por DEBAJO de sus pares), esta mitad se pone roja.

    Mitad B — el contrapeso. Con auth activa y un admin de verdad, EL MISMO
    material SÍ se entrega. Sin esta mitad, "ocultarlo todo siempre" pasaría la
    mitad A en verde, y un panel que no enseña nada no es una defensa: es una
    avería que se lee como defensa.
    """
    material = [make_job("j-visible"), make_job("j-otro")]
    with_jobs(material)

    # -- Mitad A: sin auth, sin principal, sin datos ------------------------
    os.environ.pop("S9K_AUTH_ENABLED", None)
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    ambito = anon_scope()
    assert ambito.ctx.admin_full is False, (
        "El contexto anónimo con auth desactivada ya no puede conceder admin_full"
    )
    sin_auth = client(real_app).get(SLOT.prefix, headers={"accept": "text/html"})
    assert sin_auth.status_code == 302, sin_auth.status_code
    assert "j-visible" not in sin_auth.text and "j-otro" not in sin_auth.text

    # -- Mitad B: con auth y autoridad, el mismo material SÍ se ve ----------
    db_path = tmp_path / "auth_b.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    get_auth_settings.cache_clear()
    from app.auth import db as auth_db_mod
    auth_db_mod.ensure_migrated(db_path)
    cookie = login_cookie(db_path, "panelb_bidireccional", "admin")
    con_auth = client(real_app, cookie).get(SLOT.prefix, headers={"accept": "text/html"})
    assert con_auth.status_code == 200
    assert _ids_de_la_lista(con_auth.text) == ["j-visible", "j-otro"], (
        "El panel oculta a quien SÍ está autorizado: la mitad B del control "
        "bidireccional no puede quedarse vacía."
    )


def test_el_panel_no_declara_vocabulario_propio_de_autorizacion():
    """Ni una segunda tabla de rangos, ni un `admin_full` local, ni un `role ==`.

    Se comprueba sobre el AST, no leyendo el fichero: una mención en un
    comentario no cuenta ni a favor ni en contra.
    """
    import ast

    arbol = ast.parse(Path(panel.__file__).read_text(encoding="utf-8"))
    nombres = {n.id for n in ast.walk(arbol) if isinstance(n, ast.Name)}
    atributos = {n.attr for n in ast.walk(arbol) if isinstance(n, ast.Attribute)}
    constantes = {n.value for n in ast.walk(arbol) if isinstance(n, ast.Constant)}
    cadenas = {c for c in constantes if isinstance(c, str)}
    assert "admin_full" not in nombres | atributos | cadenas
    assert "slot_guard" in nombres
    assert "get_visibility_scope" in nombres
    for rol in ("admin", "reviewer", "viewer", "anonymous"):
        assert rol not in cadenas, f"El router compara el rol {rol!r} por su cuenta"


# ===========================================================================
# 4. SOLO LECTURA: frontera dura, comprobada por enumeración
# ===========================================================================

def rutas_del_espacio_del_panel(app) -> list:
    """Todas las rutas de la APP bajo `/panel/operations`, a cualquier profundidad.

    Se recorre **la app**, no `panel.router.routes`: la frontera de solo lectura
    es del ESPACIO DE URL, no del módulo. Un `@app.post("/panel/operations/...")`
    escrito desde `app/main.py` —o desde cualquier otro carril— cuelga escritura
    en este prefijo sin tocar este fichero, y una enumeración del propio router
    lo daría por bueno.

    Se usa `iter_mounted_routes` (el censo aplanado COMPARTIDO con el barrido de
    autorización del chasis), que ya resuelve por su cuenta las tres trampas
    medidas en el carril del censo: compone el prefijo de los `Mount`, trata
    `methods` y `path` como TRI-ESTADO (ausencia => fallo cerrado) y compara el
    prefijo por SEGMENTOS. Nada de eso se rehace aquí.
    """
    from app.chassis import iter_mounted_routes, route_in_prefix

    return [r for r in iter_mounted_routes(app) if route_in_prefix(r, SLOT.prefix)]


def test_la_enumeracion_del_espacio_del_panel_no_puede_salir_vacia(real_app):
    """Suelo de plausibilidad: 0 rutas no es "no hay defecto", es "no he mirado".

    El recuento sólo cuenta rutas con path RESOLUBLE. `route_in_prefix` falla
    cerrado, así que una ristra de rutas con path indeterminable caería "dentro"
    del prefijo y podría satisfacer el suelo sin que el censo viese nada real:
    el suelo se estaría autocumpliendo con el propio fallo cerrado.

    Y se nombran los paths CONCRETOS de este carril: un suelo que se conforma
    con "hay dos rutas por ahí" no distingue las mías de las de nadie.
    """
    from app.chassis import effective_path

    rutas = rutas_del_espacio_del_panel(real_app)
    caminos = {getattr(r, "path", "") for r in rutas}
    resolubles = [r for r in rutas if effective_path(r) is not None]
    assert len(resolubles) >= 2, (
        f"La enumeración de {SLOT.prefix} sólo ve {len(resolubles)} rutas con "
        f"path resoluble ({caminos}): el barrido no está aplanando los routers "
        "incluidos"
    )
    assert SLOT.prefix in caminos
    assert f"{SLOT.prefix}/" in caminos


def test_el_gate_no_acusa_a_un_vecino_de_prefijo():
    """FALSO POSITIVO: la frontera es de SEGMENTO, no de texto.

    `POST /panel/operationsXYZ/purgar` no está en el espacio de URL de este
    panel y el gate no puede reportarlo. Un rojo por el motivo equivocado es más
    peligroso que un verde: entrena a ignorar el gate.
    """
    from fastapi import FastAPI

    vecino = FastAPI()

    @vecino.post(f"{SLOT.prefix}XYZ/purgar")
    def _purgar():  # pragma: no cover - nunca se invoca
        return {"ok": True}

    @vecino.post(f"{SLOT.prefix}-legacy/purgar")
    def _purgar_legacy():  # pragma: no cover
        return {"ok": True}

    caminos = [getattr(r, "path", "") for r in rutas_del_espacio_del_panel(vecino)]
    assert caminos == [], (
        f"El gate reclama como suyas rutas que no están bajo {SLOT.prefix}: {caminos}"
    )


def test_el_gate_si_reclama_lo_que_es_suyo():
    """Contrapeso del anterior: la frontera de segmento no lo apaga.

    Sin este control, `path_in_prefix` podría devolver `False` siempre y el test
    del vecino seguiría verde mientras el gate dejaba de mirar.
    """
    from fastapi import FastAPI

    propio = FastAPI()

    @propio.post(f"{SLOT.prefix}/purgar")
    def _purgar():  # pragma: no cover
        return {"ok": True}

    caminos = [getattr(r, "path", "") for r in rutas_del_espacio_del_panel(propio)]
    assert caminos == [f"{SLOT.prefix}/purgar"], caminos


def test_ninguna_ruta_del_espacio_del_panel_acepta_escritura(real_app):
    """LA frontera: nadie cuelga escritura bajo `/panel/operations`.

    Se afirma sobre la app real y sobre todo el prefijo, no sobre este módulo:
    comprobar el propio router deja la puerta abierta a que otro carril monte un
    POST en tu espacio de URL. La superficie de escritura se pregunta a
    `app.chassis.write_methods`, que FALLA CERRADO ante una ruta sin `methods`
    enumerables (un WebSocket, un `Mount` opaco).
    """
    from app.chassis import route_path, write_methods

    culpables = [
        (route_path(r), list(write_methods(r)))
        for r in rutas_del_espacio_del_panel(real_app)
        if write_methods(r)
    ]
    assert not culpables, (
        f"Hay escritura montada bajo {SLOT.prefix}: {culpables}. "
        "Este panel es de solo lectura y su espacio de URL también."
    )


def test_el_panel_no_monta_ningun_metodo_de_escritura(real_app):
    """El MÓDULO tampoco, comprobado aparte del espacio de URL.

    Redundante con el anterior por construcción, y se conserva porque LOCALIZA
    el fallo: dice que el POST lo puso ESTE fichero, no otro.
    """
    for ruta in panel.router.routes:
        assert not (set(getattr(ruta, "methods", set())) & METODOS_DE_ESCRITURA), (
            f"{getattr(ruta, 'path', ruta)} monta métodos de escritura"
        )


@pytest.mark.parametrize("metodo", ["post", "put", "patch", "delete"])
def test_los_metodos_de_escritura_son_rechazados_por_http(  # noqa: D401
    # NO ES UNA GARANTÍA: sondea SÓLO el prefijo raíz. Un POST colgado en
    # cualquier subruta lo deja verde. Se conserva como redundancia inofensiva;
    # la defensa es la enumeración del espacio de URL, de la que este test NO
    # es sustituto.
    real_app, panel_on, with_jobs, with_scope, metodo, operador):
    with_jobs([make_job("j1")])
    with_scope(anon_scope())
    r = getattr(operador, metodo)(SLOT.prefix)
    assert r.status_code in (404, 405), f"{metodo.upper()} devolvió {r.status_code}"


def test_el_panel_no_ejecuta_healthchecks_ni_escribe_el_informe(
    real_app, panel_on, with_jobs, with_scope, tmp_path, operador):
    """La frontera que distingue este panel de `/admin/health`.

    `/admin/health` llama a `runner.run_report()`, que EJECUTA las
    comprobaciones y guarda el informe en disco: un GET con efecto lateral. Este
    panel lee el último informe ya guardado. Se comprueba de dos formas
    independientes: el fichero no llega a existir tras recorrer el panel, y el
    módulo no nombra al ejecutor en su AST.
    """
    import ast

    from app.health import storage

    with_jobs([make_job("j1")])
    with_scope(anon_scope())
    informe = storage.default_report_path()
    assert not informe.exists()

    assert operador.get(SLOT.prefix).status_code == 200
    assert not informe.exists(), "El panel escribió el informe de salud"

    arbol = ast.parse(Path(panel.__file__).read_text(encoding="utf-8"))
    llamadas = {
        n.func.attr for n in ast.walk(arbol)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    for prohibida in ("run_report", "save_report"):
        assert prohibida not in llamadas, f"El panel llama a {prohibida}()"


def test_el_panel_no_crea_la_base_de_datos_de_trabajos(
    real_app, panel_on, with_scope, sin_cola, monkeypatch, tmp_path, operador):
    """Una cola ausente se declara ausente; no se crea para poder enseñarla."""
    db = tmp_path / "jobs.db"
    monkeypatch.setenv("S9K_JOBS_DB", str(db))
    with_scope(anon_scope())
    assert operador.get(SLOT.prefix).status_code == 200
    assert not db.exists(), "El panel creó la base de datos de trabajos"


# ===========================================================================
# 5. Ausencia != cero, y ningún contador antes de la autorización
# ===========================================================================

def test_una_cola_no_disponible_no_se_pinta_como_cero(
    real_app, panel_on, with_scope, sin_cola, operador):
    """No hay dato: se dice. Un 0 inventado es una afirmación falsa."""
    with_scope(anon_scope())
    r = operador.get(SLOT.prefix)
    assert r.status_code == 200
    assert 'data-jobs-available="false"' in r.text
    assert 'data-availability="unavailable"' in r.text
    assert 'data-count="visible"' not in r.text, (
        "Con la cola ausente el panel publica un recuento: eso es inventarse el dato"
    )
    assert 'data-state="error"' not in r.text


def test_la_ruta_de_la_base_de_datos_nunca_se_publica(
    real_app, panel_on, with_scope, sin_cola, with_jobs, operador):
    """`jobs_db_status` trae `db_path`: una ruta del servidor. No sale a pantalla."""
    with_scope(anon_scope())
    caido = operador.get(SLOT.prefix)
    assert "/ruta/secreta/del/servidor" not in caido.text

    with_jobs([make_job("j1")])
    vivo = operador.get(SLOT.prefix)
    assert "/ruta/secreta/del/servidor" not in vivo.text


def test_los_contadores_se_calculan_DESPUES_de_la_autorizacion(
    real_app, panel_on, with_jobs, with_scope, operador):
    """Seis trabajos en la base, dos visibles: el panel publica 2, no 6.

    Un total calculado antes de filtrar revelaría por diferencia la existencia
    de lo que la política acaba de ocultar (misma doctrina que docs/73).
    """
    with_jobs(
        [make_job(f"mio-{i}", partida_id="partida-A") for i in range(2)]
        + [make_job(f"ajeno-{i}", partida_id="partida-B") for i in range(4)]
    )
    with_scope(player_scope("partida-A"))
    r = operador.get(SLOT.prefix)
    assert r.status_code == 200
    assert '<span data-count="visible">2</span>' in r.text, r.text[:400]
    assert "6" not in re.findall(r'data-count="visible">(\d+)<', r.text)
    ids = _ids_de_la_lista(r.text)
    assert ids == ["mio-0", "mio-1"], ids
    for i in range(4):
        assert f"ajeno-{i}" not in r.text


def test_el_recuento_por_estado_tambien_es_del_conjunto_visible(
    real_app, panel_on, with_jobs, with_scope, operador):
    with_jobs(
        [make_job("mio", status="failed", partida_id="partida-A")]
        + [make_job(f"ajeno-{i}", status="failed", partida_id="partida-B") for i in range(3)]
    )
    with_scope(player_scope("partida-A"))
    r = operador.get(SLOT.prefix)
    assert '<span data-count-status="failed">1</span>' in r.text, r.text[:400]


def test_el_detalle_operativo_se_recorta_a_quien_no_es_autoridad_plena(
    real_app, panel_on, with_jobs, with_scope, operador):
    """El texto del error no sale nunca; la SEÑAL de incidencia, sí.

    Dos afirmaciones, y la segunda es la que muerde. Que la PANTALLA no
    contenga el texto es cierto por partida doble: `redact_job` lo quita aguas
    arriba para quien no es autoridad plena Y la plantilla no lo pinta. Eso hace
    que la primera comprobación NO pueda cobrarse como defensa de este carril:
    seguiría verde con la redacción desactivada. La que sí es de este carril es
    la segunda: `_fila` recibe el trabajo SIN redactar (ámbito interno) y aun
    así no puede emitir el texto del error.
    """
    material = with_jobs([make_job("j1", error_message="cayó leyendo /srv/secreto/fichero.txt")])
    with_scope(player_scope(None))
    r = operador.get(SLOT.prefix)
    assert "/srv/secreto" not in r.text
    assert 'data-has-error="true"' in r.text

    from app.authz.scope import UNRESTRICTED

    sin_redactar = jobs_client.scoped_jobs(UNRESTRICTED)
    assert len(sin_redactar) == len(material)
    assert sin_redactar[0].get("error_message"), (
        "el material del test no lleva texto de error: no se está midiendo nada"
    )
    fila = panel._fila(sin_redactar[0], panel.known_job_statuses())
    assert "/srv/secreto" not in str(fila), fila
    assert fila["has_error"] is True


# ===========================================================================
# 6. Estados desconocidos: FALLO CERRADO
# ===========================================================================

def test_un_estado_de_trabajo_desconocido_no_se_declara_conocido(
    real_app, panel_on, with_jobs, with_scope, operador):
    with_jobs([make_job("j1", status="TERMINADO_POR_LA_CASA")])
    with_scope(anon_scope())
    r = operador.get(SLOT.prefix)
    assert 'data-status-known="false"' in r.text
    assert "estado no reconocido" in r.text


def test_los_estados_del_motor_si_se_reconocen(real_app, panel_on, with_jobs, with_scope, operador):
    """Contrapeso: si NADA se reconociera, el test de arriba pasaría igual."""
    vocabulario = panel.known_job_statuses()
    assert vocabulario, "no se ha podido leer el vocabulario del motor"
    for estado in sorted(vocabulario):
        assert panel.job_status_known(estado, vocabulario) is True, estado

    with_jobs([make_job("j1", status="pending")])
    with_scope(anon_scope())
    r = operador.get(SLOT.prefix)
    assert 'data-status-known="true"' in r.text
    assert "estado no reconocido" not in r.text


def test_sin_vocabulario_no_se_reconoce_ningun_estado(
    real_app, panel_on, with_jobs, with_scope, monkeypatch, operador):
    """Tri-estado: no poder leer el vocabulario no concede.

    Con data-engine ausente, `pending` —un estado perfectamente legítimo— deja
    de poder contrastarse, así que no se pinta como bueno.
    """
    monkeypatch.setattr(jobs_client, "_load_job_store", lambda: None)
    assert panel.known_job_statuses() is None
    assert panel.job_status_known("pending", None) is False

    with_jobs([make_job("j1", status="pending")])
    with_scope(anon_scope())
    r = operador.get(SLOT.prefix)
    assert 'data-status-known="false"' in r.text


def test_un_filtro_de_estado_no_reconocido_se_rechaza_con_el_nombre_del_parametro(
    real_app, panel_on, with_jobs, with_scope, operador):
    """400 con el parámetro nombrado, no un 500 con traza del motor.

    `job_store.list_jobs` levanta `ValueError` ante un estado inválido: pasarle
    el parámetro sin contrastar convertía una consulta en un error de servidor.
    """
    with_jobs([make_job("j1")])
    with_scope(anon_scope())
    r = operador.get(SLOT.prefix, params={"status": "inventado"})
    assert r.status_code == 400
    assert "status" in r.text
    assert "Traceback" not in r.text


def test_un_filtro_de_estado_valido_si_pasa(real_app, panel_on, with_jobs, with_scope, operador):
    """Contrapeso del anterior: la validación no es un "rechaza siempre"."""
    with_jobs([make_job("j1", status="failed"), make_job("j2", status="pending")])
    with_scope(anon_scope())
    r = operador.get(SLOT.prefix, params={"status": "failed"})
    assert r.status_code == 200
    assert _ids_de_la_lista(r.text) == ["j1"]


def test_un_estado_de_salud_desconocido_no_se_pinta_como_bueno(
    real_app, panel_on, with_scope, sin_cola, monkeypatch, operador):
    monkeypatch.setattr(panel, "_health_report", lambda: {
        "overall": "TODO_ESTUPENDO",
        "generated_at": "2026-08-01T10:00:00+00:00",
        "components": [{"component": "neo4j", "status": "TODO_ESTUPENDO"}],
    })
    with_scope(anon_scope())
    r = operador.get(SLOT.prefix)
    assert 'data-health-overall-known="false"' in r.text
    assert 'data-component-status-known="false"' in r.text
    assert "estado no reconocido" in r.text


def test_los_estados_de_salud_del_subsistema_si_se_reconocen():
    from app.health.models import HealthStatus

    for estado in HealthStatus:
        assert panel.health_status_known(estado.value) is True, estado
    assert panel.health_status_known("TODO_ESTUPENDO") is False
    assert panel.health_status_known(None) is False


def test_sin_informe_de_salud_no_se_dice_que_todo_va_bien(
    real_app, panel_on, with_scope, sin_cola, operador):
    with_scope(anon_scope())
    r = operador.get(SLOT.prefix)
    assert 'data-health-available="false"' in r.text
    assert 'data-availability="absent"' in r.text
    assert "HEALTHY" not in r.text


def test_un_informe_ilegible_se_distingue_de_uno_ausente(
    real_app, panel_on, with_scope, sin_cola, monkeypatch, operador):
    """Tres desenlaces, tres mensajes: ausente, ilegible, disponible."""
    monkeypatch.setattr(panel, "_health_report", lambda: None)
    monkeypatch.setattr(panel, "_health_report_exists", lambda: True)
    with_scope(anon_scope())
    r = operador.get(SLOT.prefix)
    assert 'data-availability="unreadable"' in r.text
    assert 'data-health-available="false"' in r.text


def test_el_informe_de_salud_no_publica_mensajes_ni_detalles(
    real_app, panel_on, with_scope, sin_cola, monkeypatch, operador):
    """`message` y `details` pueden traer rutas, hosts o comandos del servidor."""
    monkeypatch.setattr(panel, "_health_report", lambda: {
        "overall": "DEGRADED",
        "generated_at": "2026-08-01T10:00:00+00:00",
        "components": [{
            "component": "neo4j", "status": "DEGRADED",
            "message": "bolt://192.168.1.77:7687 rechaza la conexion",
            "details": {"db_path": "/srv/neo4j/data"},
        }],
    })
    with_scope(anon_scope())
    r = operador.get(SLOT.prefix)
    assert "DEGRADED" in r.text and "neo4j" in r.text
    assert "192.168" not in r.text
    assert "/srv/neo4j" not in r.text


# ===========================================================================
# 7. Errores: 503 sin volcar rutas ni trazas
# ===========================================================================

def test_una_cola_que_revienta_da_503_sin_filtrar_rutas(
    real_app, panel_on, with_scope, monkeypatch, operador):
    monkeypatch.setattr(
        jobs_client, "jobs_db_status", lambda: {"ok": True, "db_path": "/srv/oculto/jobs.db"}
    )

    def _explota(*a, **k):
        raise RuntimeError("no such table: jobs en /srv/oculto/jobs.db")

    monkeypatch.setattr(jobs_client, "list_jobs", _explota)
    with_scope(anon_scope())
    r = operador.get(SLOT.prefix)
    assert r.status_code == 503
    assert 'data-state="error"' in r.text
    assert "RuntimeError" in r.text
    assert "/srv/oculto" not in r.text
    assert "no such table" not in r.text
    assert "Traceback" not in r.text


# ===========================================================================
# 8. Estado vacío: es el camino por defecto, no el olvidado
# ===========================================================================

def test_sin_material_se_pinta_el_estado_vacio_no_una_excepcion(
    real_app, panel_on, with_jobs, with_scope, operador):
    with_jobs([])
    with_scope(anon_scope())
    r = operador.get(SLOT.prefix)
    assert r.status_code == 200
    assert 'data-state="empty"' in r.text
    assert 'data-state="error"' not in r.text


def test_el_techo_de_filas_no_miente_sobre_el_total(
    real_app, panel_on, with_jobs, with_scope, operador):
    """Se muestran `limit` filas, pero el recuento visible sigue siendo el real."""
    with_jobs([make_job(f"j{i:02d}") for i in range(30)])
    with_scope(anon_scope())
    r = operador.get(SLOT.prefix, params={"limit": 5})
    assert len(_ids_de_la_lista(r.text)) == 5
    assert '<span data-count="visible">30</span>' in r.text
    assert '<span data-count="shown">5</span>' in r.text


def test_el_techo_de_filas_tiene_maximo(real_app, panel_on, with_jobs, with_scope, operador):
    """Una página sin techo es una petición que materializa la cola entera."""
    with_jobs([make_job("j1")])
    with_scope(anon_scope())
    r = operador.get(SLOT.prefix, params={"limit": panel.MAX_ROWS + 1})
    assert r.status_code == 422
