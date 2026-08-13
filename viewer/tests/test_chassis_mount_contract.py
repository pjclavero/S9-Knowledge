"""Contrato de montaje del chasis del visor.

REGLA DE ESTA SUITE: todo lo que sea HTTP se prueba contra la aplicación REAL
``app.main.app``. Nunca se construye un ``FastAPI()`` de mentira en el test.
Una app privada del test comparte el código de los routers pero no el montaje,
y el montaje es justamente lo que aquí se afirma. Ese atajo ya escondió un
defecto real en este repo: un handler pasaba ``admin`` a la plantilla mientras
``base.html`` leía ``auth_user``, así que la barra superior salía vacía y
ningún test lo notó porque ninguno pintaba la plantilla real.

Lo que se afirma, en orden:
  1. cada hueco declarado está MONTADO (router muerto -> rojo);
  2. cada enlace de navegación resuelve a una ruta montada (enlace roto -> rojo);
  3. toda ruta montada pasa por autorización; sin contexto se DENIEGA;
  4. la plantilla recibe las variables que `base.html` espera;
  5. sin datos se pinta el estado vacío, no una excepción.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.chassis import (
    FEATURE_SLOTS,
    NAV,
    ChassisContractError,
    effective_path,
    enumerable_methods,
    iter_mounted_routes,
    nav_for,
    route_index,
)

PASSWORD = "ChasisTest_1234567890!"


# ---------------------------------------------------------------------------
# Fixtures — app REAL, auth REAL
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
def _panels_on():
    """Enciende los cuatro huecos para el resto de la suite.

    Los interruptores fallan CERRADOS, así que sin esta fixture los paneles
    devuelven 404 y las pruebas de guarda no probarían nada. Encenderlos aquí es
    deliberado y explícito; los tests del propio interruptor los apagan.
    """
    from app.chassis import FEATURE_SLOTS, slot_flag_env

    previo = {slot_flag_env(s): os.environ.get(slot_flag_env(s)) for s in FEATURE_SLOTS}
    for var in previo:
        os.environ[var] = "true"
    yield
    for var, valor in previo.items():
        if valor is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = valor


@pytest.fixture
def auth_on(tmp_path):
    """Auth activada con una base de datos temporal. Nunca toca producción."""
    db_path = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    from app.auth import db as auth_db_mod
    auth_db_mod.ensure_migrated(db_path)
    return db_path


def _make_user(db_path: Path, username: str, role: str):
    from app.auth import db as auth_db_mod
    from app.auth.passwords import hash_password

    with auth_db_mod.get_conn(db_path) as conn:
        user = auth_db_mod.create_user(
            conn, username=username, display_name=username.title(),
            password_hash=hash_password(PASSWORD), role=role,
        )
        # `must_change_password` cortaría toda navegación en el middleware; esta
        # suite prueba montaje, no el flujo de primera contraseña.
        auth_db_mod.update_user(conn, user.id, must_change_password=False)
        return auth_db_mod.get_user_by_id(conn, user.id)


def _client(app, cookie: str | None = None) -> TestClient:
    client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    if cookie:
        from app.auth.config import get_auth_settings
        client.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, cookie)
    return client


def _login_cookie(db_path: Path, username: str, role: str) -> str:
    from app.auth import db as auth_db_mod
    from app.auth.sessions import create_session

    user = _make_user(db_path, username, role)
    with auth_db_mod.get_conn(db_path) as conn:
        token, _ = create_session(conn, user)
    return token


# ---------------------------------------------------------------------------
# 1. Un router declarado y NO montado debe ser detectable
# ---------------------------------------------------------------------------

def test_every_declared_slot_is_actually_mounted(real_app):
    """El contrato declara cuatro huecos; los cuatro deben existir en la app."""
    index = route_index(real_app)
    faltan = [s.key for s in FEATURE_SLOTS if s.route_name not in index]
    assert not faltan, (
        f"Huecos declarados en FEATURE_SLOTS pero sin ruta montada: {faltan}. "
        "Un router definido y no incluido es una ruta muerta."
    )


def test_mounted_slot_path_matches_declared_prefix(real_app):
    index = route_index(real_app)
    for slot in FEATURE_SLOTS:
        assert index[slot.route_name].rstrip("/") == slot.prefix, (
            f"Hueco {slot.key}: montado en {index[slot.route_name]!r}, "
            f"el contrato dice {slot.prefix!r}"
        )


def test_slot_prefixes_do_not_collide(real_app):
    """Ningún hueco puede quedar tapado por una ruta preexistente.

    `/sources/panel`, por ejemplo, lo capturaría `/sources/{source_id}`: la
    pantalla nueva nunca se serviría y no habría error en ninguna parte.
    """
    propios = {s.route_name for s in FEATURE_SLOTS}
    ajenas = [
        getattr(r, "path", "")
        for r in iter_mounted_routes(real_app)
        if getattr(r, "name", None) not in propios
    ]
    for slot in FEATURE_SLOTS:
        for path in ajenas:
            if "{" not in path:
                continue
            # Una ruta dinámica de un solo segmento tapa cualquier hijo directo.
            padre = path.rsplit("/", 1)[0]
            assert not (slot.prefix.startswith(padre + "/")
                        and slot.prefix.count("/") == path.count("/")), (
                f"El prefijo {slot.prefix!r} del hueco {slot.key} queda "
                f"capturado por la ruta dinámica {path!r}"
            )


def test_slot_routers_are_importable_and_export_router():
    import importlib

    for slot in FEATURE_SLOTS:
        module = importlib.import_module(slot.module)
        assert getattr(module, "router", None) is not None, (
            f"{slot.module} no exporta `router`"
        )


# ---------------------------------------------------------------------------
# 1bis. El contrato ESCRITO A MANO, no leído del propio FEATURE_SLOTS
# ---------------------------------------------------------------------------
# Todo lo de arriba compara `FEATURE_SLOTS` consigo mismo: afirma coherencia
# interna. Cambiar el rol de B a `viewer` o el prefijo de C a `/panel/revision`
# pasaba esa suite en VERDE (medido: 40 passed/2 skipped y 41 passed), porque el
# test leía el mismo dato que estaba comprobando. Autorreferencia.
#
# Esta tabla es la copia INDEPENDIENTE del contrato publicado en
# `docs/69-chasis-de-montaje.md`. Está escrita a mano a propósito: si alguien
# cambia `FEATURE_SLOTS`, aquí sale rojo y hay que cambiar también el documento
# y a los carriles que se montan encima. Es exactamente la fricción que se
# quiere: C, B, F y G se construyen en paralelo contra estos valores.

#: key -> (prefix, route_name, role, module, template)
CONTRATO_PUBLICADO = {
    "C": ("/panel/review", "chassis_review", "reviewer",
          "app.routers.chassis_review", "chassis/review.html"),
    "B": ("/panel/operations", "chassis_operations", "admin",
          "app.routers.chassis_operations", "chassis/operations.html"),
    "F": ("/panel/sources", "chassis_sources", "reviewer",
          "app.routers.chassis_sources", "chassis/sources.html"),
    "G": ("/panel/entities", "chassis_entities", "viewer",
          "app.routers.chassis_entities", "chassis/entities.html"),
}


def test_feature_slots_match_the_published_contract():
    declarado = {
        s.key: (s.prefix, s.route_name, s.role, s.module, s.template)
        for s in FEATURE_SLOTS
    }
    assert declarado == CONTRATO_PUBLICADO, (
        "FEATURE_SLOTS ya no coincide con el contrato publicado en docs/69. "
        "Si el cambio es intencionado, hay que actualizar el documento, esta "
        "tabla y avisar a los carriles C/B/F/G: se están montando sobre estos "
        "prefijos y estos roles."
    )


@pytest.mark.parametrize("key,esperado", sorted(CONTRATO_PUBLICADO.items()))
def test_published_prefix_and_role_are_served_as_such(real_app, auth_on, key, esperado):
    """El prefijo y el rol del contrato, comprobados por HTTP contra la app real.

    No basta con que `FEATURE_SLOTS` diga lo correcto: lo que importa es que la
    URL publicada responda y que el rol publicado sea el que abre la puerta. Se
    pide la URL literal de la tabla, nunca `slot.prefix`.
    """
    prefix, route_name, role, _module, _template = esperado
    index = route_index(real_app)
    assert index.get(route_name) == prefix, (
        f"Hueco {key}: el contrato publica {prefix!r} para {route_name!r}; "
        f"montado en {index.get(route_name)!r}"
    )
    cookie = _login_cookie(auth_on, f"contrato_{key.lower()}", role)
    r = _client(real_app, cookie).get(prefix, headers={"accept": "text/html"})
    assert r.status_code == 200, (
        f"Hueco {key}: el rol publicado {role!r} recibe {r.status_code} en {prefix}"
    )


@pytest.mark.parametrize("key,esperado", sorted(CONTRATO_PUBLICADO.items()))
def test_published_role_is_the_minimum_not_a_wider_one(real_app, auth_on, key, esperado):
    """El rol publicado es MÍNIMO: el inmediatamente inferior debe recibir 403.

    Sin esto, subir el rol de un hueco (G: `viewer` -> `admin`) pasaría verde:
    nadie afirma que un `viewer` deba entrar en G.
    """
    prefix, _route_name, role, _module, _template = esperado
    inferior = {"admin": "reviewer", "reviewer": "viewer", "viewer": None}[role]
    cliente = lambda rol: _client(  # noqa: E731
        real_app, _login_cookie(auth_on, f"min_{key.lower()}_{rol}", rol)
    ).get(prefix, headers={"accept": "text/html"})
    if inferior is not None:
        assert cliente(inferior).status_code == 403, (
            f"Hueco {key}: el contrato publica {role!r} como mínimo, pero "
            f"{inferior!r} entra."
        )
    # ...y el rol publicado sí entra: un rol de más tampoco es el contrato.
    assert cliente(role).status_code == 200


# ---------------------------------------------------------------------------
# 2. Un elemento de navegación a una ruta inexistente rompe
# ---------------------------------------------------------------------------

def test_every_nav_item_resolves_to_a_mounted_route(real_app):
    index = route_index(real_app)
    rotos = [n.label for n in NAV if n.route_name not in index]
    assert not rotos, f"Enlaces de navegación sin ruta montada: {rotos}"


def test_nav_raises_loudly_when_a_route_is_missing(real_app, monkeypatch):
    """La navegación NO se autocensura: un enlace huérfano levanta error.

    Degradar a "no pinto ese enlace" convertiría el defecto en invisible, que es
    justo lo contrario de lo que pide el chasis.
    """
    from app import chassis

    monkeypatch.setattr(
        chassis, "NAV",
        NAV + (chassis.NavItem("Fantasma", "ruta_que_no_existe", None, 99),),
    )
    with pytest.raises(ChassisContractError):
        chassis.nav_for(real_app, None)


def test_nav_urls_are_reachable_not_404(real_app, auth_on):
    """Cada URL del menú, tal y como se pinta, responde algo que no es 404."""
    cookie = _login_cookie(auth_on, "nav_admin", "admin")
    client = _client(real_app, cookie)
    from app.auth import db as auth_db_mod
    with auth_db_mod.get_conn(auth_on) as conn:
        user = auth_db_mod.get_user_by_username(conn, "nav_admin")
    for item in nav_for(real_app, user):
        r = client.get(item["url"], headers={"accept": "text/html"})
        assert r.status_code != 404, f"{item['label']} -> {item['url']} da 404"


def test_every_template_environment_can_render_the_nav(real_app):
    """Ningún entorno Jinja de la aplicación se queda sin `chassis_nav`.

    Cada router trae su propia instancia de Jinja2Templates. Si una se queda sin
    el global, sus pantallas revientan al pintar `base.html`. Se comprueba por
    enumeración para que un router nuevo con su propio entorno no se escape.
    """
    import sys

    from fastapi.templating import Jinja2Templates

    from app.chassis import NAV_GLOBAL

    huerfanos = []
    for name, module in list(sys.modules.items()):
        if name != "app" and not name.startswith("app."):
            continue
        for attr_name, attr in list(vars(module).items()) if module else ():
            if isinstance(attr, Jinja2Templates) and NAV_GLOBAL not in attr.env.globals:
                huerfanos.append(f"{name}.{attr_name}")
    assert not huerfanos, f"Entornos de plantillas sin {NAV_GLOBAL}: {huerfanos}"


def test_base_html_has_no_hardcoded_nav_links():
    """La navegación tiene una única fuente: el registro, no el HTML."""
    base = (Path(__file__).resolve().parents[1]
            / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    nav = base.split("<nav>", 1)[1].split("</nav>", 1)[0]
    assert "chassis_nav" in nav
    assert 'href="/' not in nav, (
        "base.html vuelve a llevar enlaces escritos a mano; un enlace a mano no "
        "se entera de que su ruta ha desaparecido."
    )


# ---------------------------------------------------------------------------
# 3. Toda ruta montada pasa por autorización
# ---------------------------------------------------------------------------

#: Rutas que legítimamente sirven contenido a un anónimo. Es una lista BLANCA:
#: una ruta nueva sin autorización no se cuela porque no está aquí.
ANON_ALLOWED_PATHS = frozenset({
    "/login",       # el formulario de acceso
    "/logout",      # cerrar sesión sin sesión es inofensivo
    "/static",      # activos estáticos
    "/favicon.ico",
})


def _sample_path(path: str) -> str:
    """Sustituye los parámetros de ruta por un valor inocuo."""
    out = []
    for seg in path.split("/"):
        out.append("chasis-inexistente" if seg.startswith("{") else seg)
    return "/".join(out)


def clasificar_para_el_barrido(rutas):
    """Reparte el censo en (sondeables, opacas, sin_path). FALLA CERRADO dos veces.

    Se extrae del test para que el caso real y el sintético muerdan EXACTAMENTE
    el mismo código: si esta clasificación se relaja, los dos se ponen rojos.
    Un test sintético que reimplementa la lógica que dice vigilar no vigila nada.
    """
    sondeables, opacas, sin_path = [], [], []
    for route in rutas:
        path = effective_path(route)
        if path is None:
            # Antes esto era `if not path: continue`, es decir: una ruta cuyo
            # path el censo no sabe resolver se SALTABA en silencio, que es
            # exactamente la que se colaría. Medido: un `Mount` dentro de un
            # `APIRouter` incluido con prefijo llegaba aquí con `path=''` y
            # servía 200 sin que este barrido lo mirase.
            sin_path.append(f"{type(route).__name__} {getattr(route, 'name', '')!r}")
            continue
        if path in ANON_ALLOWED_PATHS:
            continue
        metodos = enumerable_methods(route)
        if metodos is None:
            # No se puede sondear lo que no declara métodos (WebSocket, `Mount`
            # opaco). Eso NO la absuelve: se declara y el barrido falla CERRADO,
            # porque una ruta que este barrido no puede examinar es exactamente
            # la que se le escaparía. Para eximirla hay que ponerla en la lista
            # blanca a mano, que es una decisión visible.
            opacas.append(path)
            continue
        sondeables.append((path, sorted(m for m in metodos if m in {"GET", "POST"})))
    return sondeables, opacas, sin_path


def test_el_barrido_de_autorizacion_no_se_salta_un_path_irresoluble():
    """Suelo del barrido: lo que no sabe resolver, lo DECLARA.

    Hoy la app real no tiene ninguna ruta así (el arreglo de `_walk` resuelve el
    único vector vivo), así que este caso se prueba con una ruta fabricada: es
    el suelo que queda si un tipo de ruta futuro vuelve a llegar sin path.
    """
    class RutaSinPath:
        path = ""
        name = "fantasma"

    _sondeables, _opacas, sin_path = clasificar_para_el_barrido([RutaSinPath()])
    assert sin_path, (
        "El barrido se saltó en silencio una ruta cuyo path no sabe resolver"
    )


def test_no_mounted_route_serves_200_to_anonymous(real_app, auth_on):
    """Con auth activada y SIN sesión, ninguna ruta devuelve 200.

    Ésta es la forma operativa de "ausencia de dato nunca es permiso máximo":
    el anónimo es exactamente el caso de contexto ausente.
    """
    client = _client(real_app)
    fugas = []
    sondeables, opacas, sin_path = clasificar_para_el_barrido(
        iter_mounted_routes(real_app))
    for path, metodos in sondeables:
        for method in metodos:
            r = client.request(method, _sample_path(path),
                               headers={"accept": "text/html"})
            if r.status_code == 200:
                fugas.append(f"{method} {path}")
    assert sondeables, (
        "El barrido no sondeó ni una sola ruta: un arnés vacío no demuestra nada"
    )
    assert not sin_path, (
        f"Rutas cuyo path el censo no sabe resolver: {sin_path}. No saber dónde "
        "está una ruta no la absuelve: este barrido no puede sondearla y por eso "
        "es precisamente la que se colaría."
    )
    assert not opacas, (
        f"Rutas que el barrido de autorización no puede examinar porque no "
        f"declaran métodos enumerables: {opacas}. Ausencia de dato no es "
        "ausencia de superficie: decláralas en ANON_ALLOWED_PATHS si son "
        "legítimas, o quítalas."
    )
    assert not fugas, f"Rutas que sirven 200 a un anónimo: {fugas}"


@pytest.mark.parametrize("slot", FEATURE_SLOTS, ids=lambda s: s.key)
def test_slot_denies_anonymous(real_app, auth_on, slot):
    client = _client(real_app)
    r = client.get(slot.prefix, headers={"accept": "text/html"})
    assert r.status_code in (302, 401), (
        f"Hueco {slot.key}: anónimo recibe {r.status_code}"
    )


@pytest.mark.parametrize("slot", FEATURE_SLOTS, ids=lambda s: s.key)
def test_slot_denies_insufficient_role(real_app, auth_on, slot):
    """Un rol por debajo del declarado recibe 403, no la pantalla."""
    inferior = {"admin": "reviewer", "reviewer": "viewer", "viewer": None}[slot.role]
    if inferior is None:
        pytest.skip("'viewer' es el rol más bajo: no hay uno inferior")
    cookie = _login_cookie(auth_on, f"low_{slot.key.lower()}", inferior)
    r = _client(real_app, cookie).get(slot.prefix, headers={"accept": "text/html"})
    assert r.status_code == 403, f"Hueco {slot.key}: {inferior} recibe {r.status_code}"


@pytest.mark.parametrize("slot", FEATURE_SLOTS, ids=lambda s: s.key)
def test_slot_allows_declared_role(real_app, auth_on, slot):
    cookie = _login_cookie(auth_on, f"ok_{slot.key.lower()}", slot.role)
    r = _client(real_app, cookie).get(slot.prefix, headers={"accept": "text/html"})
    assert r.status_code == 200, f"Hueco {slot.key}: {slot.role} recibe {r.status_code}"


def test_admin_slot_denies_anonymous_with_auth_disabled(real_app, monkeypatch):
    """Un hueco `admin` no puede ser MÁS permisivo que `/admin/users`.

    Con `S9K_AUTH_ENABLED` ausente, `html_role_guard` es no-op y servía la
    pantalla a un anónimo (200) mientras `/admin/users` y `/admin/partidas`
    respondían 302. Misma área, dos posturas: eso es una degradación, aunque no
    haya vocabulario de autorización nuevo. Se compara contra los pares REALES,
    no contra una constante escrita en el test.
    """
    monkeypatch.delenv("S9K_AUTH_ENABLED", raising=False)
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()

    client = _client(real_app)
    pares = [client.get(p, headers={"accept": "text/html"}).status_code
             for p in ("/admin/users", "/admin/partidas")]
    for slot in FEATURE_SLOTS:
        if slot.role != "admin":
            continue
        r = client.get(slot.prefix, headers={"accept": "text/html"})
        assert r.status_code in pares, (
            f"Hueco {slot.key} ({slot.role}): con auth desactivada responde "
            f"{r.status_code} a un anónimo; sus pares de administración "
            f"responden {pares}."
        )


# ---------------------------------------------------------------------------
# 3bis. Interruptor por hueco: apagar un panel a medio construir
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("slot", FEATURE_SLOTS, ids=lambda s: s.key)
def test_slot_is_off_when_flag_is_absent(real_app, auth_on, slot, monkeypatch):
    """Sin flag NO hay panel, ni siquiera para quien tiene el rol.

    La ausencia de dato nunca es permiso máximo: es la variante de "apagado".
    """
    from app.chassis import slot_flag_env

    monkeypatch.delenv(slot_flag_env(slot), raising=False)
    cookie = _login_cookie(auth_on, f"off_{slot.key.lower()}", slot.role)
    r = _client(real_app, cookie).get(slot.prefix, headers={"accept": "text/html"})
    assert r.status_code == 404, (
        f"Hueco {slot.key}: sin {slot_flag_env(slot)} responde {r.status_code}"
    )
    # El cuerpo del 404 no enseña cómo se enciende el panel. No es un secreto
    # —está en docs/69 y en `.env.example`—, pero una respuesta de error no es
    # el sitio donde publicarlo.
    assert slot_flag_env(slot) not in r.text, (
        f"El 404 del hueco {slot.key} nombra su variable de entorno: {r.text}"
    )


@pytest.mark.parametrize("valor", ["quizas", "", "false", "TRUE-ish", "0", "yes"])
def test_slot_is_off_when_flag_is_garbage(real_app, auth_on, valor, monkeypatch):
    """Un valor que no se entiende es un dato ausente: panel apagado.

    Incluye `yes` y `0` a propósito: valores plausibles que NO están en
    `FLAG_ON_VALUES`. Si mañana se amplía el vocabulario, este test lo obliga a
    ser una decisión escrita, no un descuido de parsing.
    """
    from app.chassis import slot_flag_env

    slot = FEATURE_SLOTS[0]
    monkeypatch.setenv(slot_flag_env(slot), valor)
    cookie = _login_cookie(auth_on, f"raro_{abs(hash(valor)) % 9999}", slot.role)
    r = _client(real_app, cookie).get(slot.prefix, headers={"accept": "text/html"})
    assert r.status_code == 404, f"valor {valor!r} enciende el panel ({r.status_code})"


@pytest.mark.parametrize("slot", FEATURE_SLOTS, ids=lambda s: s.key)
def test_slot_is_on_only_with_an_explicit_flag(real_app, auth_on, slot, monkeypatch):
    from app.chassis import FLAG_ON_VALUES, slot_flag_env

    for valor in sorted(FLAG_ON_VALUES):
        monkeypatch.setenv(slot_flag_env(slot), valor)
        cookie = _login_cookie(auth_on, f"on_{slot.key.lower()}_{valor}", slot.role)
        r = _client(real_app, cookie).get(slot.prefix, headers={"accept": "text/html"})
        assert r.status_code == 200, f"Hueco {slot.key} con {valor!r}: {r.status_code}"


def test_flag_does_not_bypass_authorization(real_app, auth_on, monkeypatch):
    """Encender el panel no es autorizar: el anónimo sigue fuera.

    El interruptor se comprueba DESPUÉS de la guarda; un flag no puede
    convertirse nunca en una puerta lateral.
    """
    from app.chassis import slot_flag_env

    for slot in FEATURE_SLOTS:
        monkeypatch.setenv(slot_flag_env(slot), "true")
        r = _client(real_app).get(slot.prefix, headers={"accept": "text/html"})
        assert r.status_code in (302, 401), f"Hueco {slot.key}: {r.status_code}"


def test_disabled_slots_are_not_enumerable_by_an_anonymous(real_app, auth_on, monkeypatch):
    """Un anónimo recibe el MISMO estado para un panel encendido y uno apagado.

    El orden importa y hasta ahora sólo estaba *afirmado en prosa*: comprobar el
    interruptor ANTES de la guarda deja todo verde, y sin embargo con C
    encendido y B/F/G apagados un anónimo obtiene `302 / 404 / 404 / 404` y
    enumera qué paneles están encendidos. Medido, no supuesto. Aquí queda con
    número y con red: un carril futuro que reordene esas dos líneas se pone
    rojo en vez de perder la propiedad en silencio.

    La comparación es entre respuestas al MISMO anónimo, no contra un código
    escrito a mano: lo que se afirma es indistinguibilidad, no "302".
    """
    from app.chassis import slot_flag_env

    encendido, *apagados = FEATURE_SLOTS
    monkeypatch.setenv(slot_flag_env(encendido), "true")
    for slot in apagados:
        monkeypatch.delenv(slot_flag_env(slot), raising=False)

    client = _client(real_app)
    estados = {}
    for slot in FEATURE_SLOTS:
        for url in (slot.prefix, slot.prefix + "/"):
            estados[(slot.key, url)] = client.get(
                url, headers={"accept": "text/html"}).status_code

    distintos = sorted(set(estados.values()))
    assert len(distintos) == 1, (
        "Un anónimo distingue paneles encendidos de apagados y puede "
        f"enumerarlos: {estados}. El interruptor tiene que evaluarse DESPUÉS "
        "de la guarda."
    )


def test_disabled_slot_is_not_linked_in_the_nav(real_app, auth_on, monkeypatch):
    """Un panel apagado desaparece del menú; los demás enlaces siguen ahí.

    Enlazar un panel apagado sería un enlace roto — el fallo que el chasis
    persigue— y omitirlo es la ÚNICA excusa admitida: un hueco declarado y
    explícitamente apagado, nunca una ruta que falta por error.
    """
    from app.auth import db as auth_db_mod
    from app.chassis import slot_flag_env

    _login_cookie(auth_on, "nav_off", "admin")
    with auth_db_mod.get_conn(auth_on) as conn:
        user = auth_db_mod.get_user_by_username(conn, "nav_off")

    apagado = FEATURE_SLOTS[0]
    monkeypatch.delenv(slot_flag_env(apagado), raising=False)
    nombres = {i["route_name"] for i in nav_for(real_app, user)}
    assert apagado.route_name not in nombres
    for otro in FEATURE_SLOTS[1:]:
        assert otro.route_name in nombres, f"{otro.key} desapareció sin motivo"


# ---------------------------------------------------------------------------
# 4. La plantilla recibe lo que `base.html` espera
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("slot", FEATURE_SLOTS, ids=lambda s: s.key)
def test_slot_renders_topbar_identity(real_app, auth_on, slot):
    """El HTML servido muestra al usuario.

    Si el handler pasa la identidad con otro nombre (`user`, `admin`...) la
    barra sale vacía sin fallar: exactamente el defecto que este test existe
    para cazar. Se comprueba sobre el HTML REAL de la app real.
    """
    username = f"tpl_{slot.key.lower()}"
    cookie = _login_cookie(auth_on, username, slot.role)
    html = _client(real_app, cookie).get(
        slot.prefix, headers={"accept": "text/html"}).text
    assert username.title() in html, (
        f"Hueco {slot.key}: el nombre del usuario no aparece; la plantilla no "
        "recibió `auth_user`."
    )
    assert f'role-{slot.role}' in html


@pytest.mark.parametrize("slot", FEATURE_SLOTS, ids=lambda s: s.key)
def test_slot_context_keys_are_the_contract(slot):
    from app.routers.chassis_slot import SLOT_CONTEXT_KEYS, slot_context

    assert set(slot_context(slot, None)) == set(SLOT_CONTEXT_KEYS)


# ---------------------------------------------------------------------------
# 5. Estado vacío y estado de error explícitos
# ---------------------------------------------------------------------------

@pytest.fixture
def _sin_datos_de_grafo(real_app):
    """Establece la premisa «sin datos» en vez de darla por supuesta.

    Este test decía «sin datos» y NO lo montaba: se apoyaba en que los cuatro
    huecos estaban vacíos, que es una propiedad accidental del chasis recién
    puesto y no de la pantalla. El proveedor por defecto del banco es
    `MockGraphProvider` sobre `examples/sample_graph.json`, así que en cuanto un
    carril montó su funcionalidad encima (hueco G, docs/77) la pantalla pasó a
    pintar 9 filas y el estado `ready` — comportamiento CORRECTO que el test
    leía como fallo. Un test cuya premisa nunca se comprueba mide otra cosa que
    la que dice.

    La premisa se monta ahora sustituyendo el proveedor BASE por uno vacío. La
    afirmación no se toca ni se debilita: sigue exigiendo `empty` y prohibiendo
    `error`, sólo que ahora sobre el caso que nombra. Vale para los cuatro
    huecos: los que no leen del grafo no se enteran.
    """
    import app.deps as deps
    from app.providers.base import GraphProvider

    class _ProveedorVacio(GraphProvider):
        name = "vacio"

        def is_connected(self):
            return True

        def workspaces(self):
            return []

        def counts(self, workspace=None):
            return 0, 0

        def entity_types(self, workspace):
            return []

        def search(self, workspace, q, limit=50):
            return []

        def graph(self, workspace, limit=300, entity_type=None, q=None):
            return [], []

        def entity(self, entity_id, *, workspaces=None):
            return None

        def relations_for_entity(self, entity_id):
            return [], []

        def list_entities(self, workspace, **kwargs):
            return [], 0

        def list_sources(self, workspace):
            return []

        def source_detail(self, workspace, source_id):
            return None

        def quality_metrics(self, workspace=None):
            return {}

    real_app.dependency_overrides[deps.get_provider] = lambda: _ProveedorVacio()
    yield
    real_app.dependency_overrides.pop(deps.get_provider, None)


@pytest.mark.parametrize("slot", FEATURE_SLOTS, ids=lambda s: s.key)
def test_slot_renders_empty_state_instead_of_exploding(
    real_app, auth_on, _sin_datos_de_grafo, slot
):
    """Sin datos, la pantalla se pinta. No revienta ni devuelve 500."""
    cookie = _login_cookie(auth_on, f"empty_{slot.key.lower()}", slot.role)
    r = _client(real_app, cookie).get(slot.prefix, headers={"accept": "text/html"})
    assert r.status_code == 200
    assert 'data-state="empty"' in r.text
    assert 'data-state="error"' not in r.text


@pytest.mark.parametrize("slot", FEATURE_SLOTS, ids=lambda s: s.key)
def test_slot_template_has_an_error_state(slot):
    """La plantilla sabe pintar un fallo sin traza ni pantalla en blanco."""
    from app.routers.chassis_slot import slot_context, templates

    html = templates.get_template(slot.template).render(
        {"request": None, **slot_context(slot, None, items=[],
                                         error="proveedor no disponible")}
    )
    assert 'data-state="error"' in html
    assert "proveedor no disponible" in html
    assert 'data-state="empty"' not in html


@pytest.mark.parametrize("slot", FEATURE_SLOTS, ids=lambda s: s.key)
def test_slot_template_renders_ready_state_with_items(slot):
    from app.routers.chassis_slot import slot_context, templates

    html = templates.get_template(slot.template).render(
        {"request": None, **slot_context(slot, None, items=["uno"], error=None)}
    )
    assert 'data-state="ready"' in html


# ===========================================================================
# El CENSO COMPARTIDO como instrumento: `iter_mounted_routes` lo usan el
# barrido de autorización de arriba, `route_index` y el gate de solo lectura
# del hueco C. Un punto ciego del censo es un punto ciego de los tres a la vez,
# así que se prueba aquí, sobre apps sintéticas, además de sobre la real.
# ===========================================================================

def _app_con_submontaje():
    """App mínima con una sub-app montada bajo `/panel/review/admin`."""
    from fastapi import FastAPI

    principal = FastAPI()
    sub = FastAPI()

    @sub.post("/aprobar")
    def _aprobar():  # pragma: no cover - nunca se invoca
        return {"ok": True}

    principal.mount("/panel/review/admin", sub)
    return principal


def test_el_censo_compone_el_prefijo_de_los_mount():
    """El path emitido es el EFECTIVO, no el relativo al punto de montaje.

    Éste es el defecto medido: Starlette guarda `'/aprobar'` en la ruta interna,
    y cualquier consumidor que filtre por `startswith('/panel/review')` la
    descartaba mientras `POST /panel/review/admin/aprobar` respondía 200.
    """
    app = _app_con_submontaje()
    caminos = {str(getattr(r, "path", "")) for r in iter_mounted_routes(app)}

    assert "/panel/review/admin/aprobar" in caminos, (
        f"El censo no compone el prefijo del Mount: {sorted(caminos)}"
    )
    assert "/aprobar" not in caminos, (
        "El censo sigue emitiendo el path relativo al punto de montaje"
    )


def _app_con_mount_dentro_de_router_incluido():
    """El vector M-G: un `Mount` DENTRO de un `APIRouter` incluido con prefijo.

    FastAPI sólo rellena el `_EffectiveRouteContext` para las `APIRoute`; si el
    contexto envuelve un `Mount`, llega con `path=''`.
    """
    from fastapi import APIRouter, FastAPI

    app = FastAPI()
    router = APIRouter()
    sub = FastAPI()

    @sub.post("/aprobar")
    def _aprobar():  # pragma: no cover
        return {"ok": True}

    router.mount("/m", sub)
    app.include_router(router, prefix="/panel/review/inc")
    return app


def test_un_mount_dentro_de_un_router_incluido_no_pierde_el_path():
    """M-G: sin esto el censo emitía `path=''` y NADIE lo veía.

    Medido antes del arreglo: `POST /panel/review/inc/m/aprobar` respondía 200 y
    escribía, el censo lo emitía como `_EffectiveRouteContext` con `path=''`, el
    filtro por prefijo lo descartaba (`''.startswith(...)` es False) y el barrido
    de autorización lo saltaba con `if not path: continue`.
    """
    from app.chassis import route_in_prefix, write_methods

    app = _app_con_mount_dentro_de_router_incluido()
    caminos = {str(getattr(r, "path", "")) for r in iter_mounted_routes(app)}
    assert "/panel/review/inc/m/aprobar" in caminos, sorted(caminos)
    assert "" not in caminos, "El censo sigue emitiendo una ruta con path vacío"

    escrituras = [(r.path, write_methods(r)) for r in iter_mounted_routes(app)
                  if route_in_prefix(r, "/panel/review") and write_methods(r)]
    assert escrituras == [("/panel/review/inc/m/aprobar", ("POST",))]


def test_el_mount_de_ese_vector_responde_de_verdad():
    """Control positivo: si la ruta no sirviera, el caso no probaría nada."""
    from fastapi.testclient import TestClient

    app = _app_con_mount_dentro_de_router_incluido()
    assert TestClient(app).post("/panel/review/inc/m/aprobar").status_code == 200


def test_el_censo_compone_el_prefijo_a_dos_niveles():
    from fastapi import FastAPI

    principal, n1, n2 = FastAPI(), FastAPI(), FastAPI()

    @n2.post("/z")
    def _z():  # pragma: no cover
        return {}

    n1.mount("/y", n2)
    principal.mount("/panel/review/x", n1)

    caminos = {str(getattr(r, "path", "")) for r in iter_mounted_routes(principal)}
    assert "/panel/review/x/y/z" in caminos, sorted(caminos)


def test_el_censo_no_altera_las_rutas_sin_montaje():
    """Control de no-regresión: sin `Mount`, el censo es idéntico al de antes.

    Si el envoltorio se aplicara siempre, `type(r)` cambiaría para toda la app y
    los tres consumidores heredarían un cambio que nadie pidió.
    """
    from fastapi import FastAPI
    from fastapi.routing import APIRoute

    app = FastAPI()

    @app.get("/simple")
    def _simple():  # pragma: no cover
        return {}

    rutas = [r for r in iter_mounted_routes(app)
             if str(getattr(r, "path", "")) == "/simple"]
    assert len(rutas) == 1
    assert isinstance(rutas[0], APIRoute), (
        "Una ruta sin Mount por encima no debe llegar envuelta"
    )


def test_la_ruta_compuesta_conserva_nombre_y_metodos():
    """El envoltorio delega todo lo que no sea el path."""
    app = _app_con_submontaje()
    (ruta,) = [r for r in iter_mounted_routes(app)
               if str(getattr(r, "path", "")) == "/panel/review/admin/aprobar"]
    assert ruta.name == "_aprobar"
    assert "POST" in ruta.methods
    assert callable(ruta.endpoint)


def test_el_censo_de_la_app_real_no_puede_salir_vacio(real_app):
    """Suelo de plausibilidad del instrumento compartido.

    Un censo de 0 rutas "demuestra" que no hay ninguna fuga y que no hay ninguna
    escritura. Si un cambio lo vacía, esto cae antes y con el motivo escrito.
    """
    rutas = list(iter_mounted_routes(real_app))
    assert len(rutas) >= 20, f"El censo aplanado sólo ve {len(rutas)} rutas"
    caminos = {str(getattr(r, "path", "")) for r in rutas}
    for slot in FEATURE_SLOTS:
        assert slot.prefix in caminos, f"El censo perdió el hueco {slot.key}"


# --- Ausencia de `methods` != ausencia de escritura -------------------------

def test_un_websocket_no_declara_metodos_enumerables():
    """El hecho medido del que sale el criterio, comprobado y no supuesto."""
    from fastapi import FastAPI

    app = FastAPI()

    @app.websocket("/ws")
    async def _ws(websocket):  # pragma: no cover
        await websocket.accept()

    (ruta,) = [r for r in iter_mounted_routes(app)
               if str(getattr(r, "path", "")) == "/ws"]
    assert getattr(ruta, "methods", None) is None
    assert enumerable_methods(ruta) is None


def test_write_methods_falla_cerrado_sin_metodos_enumerables():
    from app.chassis import METHODS_NOT_ENUMERABLE, is_write_capable, write_methods

    class SinMetodos:
        path = "/opaca"

    class MetodosNulos:
        path = "/opaca"
        methods = None

    class MetodosVacios:
        path = "/opaca"
        methods = set()

    for opaca in (SinMetodos(), MetodosNulos(), MetodosVacios()):
        assert write_methods(opaca) == (METHODS_NOT_ENUMERABLE,), (
            f"{type(opaca).__name__}: la ausencia de métodos se dio por buena"
        )
        assert is_write_capable(opaca) is True


def test_write_methods_no_inventa_escritura_donde_no_la_hay():
    """El otro lado del criterio: un GET declarado sigue siendo solo lectura.

    Sin esto, "falla cerrado" degeneraría en "siempre rojo", que no distingue
    nada y no es una defensa.
    """
    from app.chassis import is_write_capable, write_methods

    class SoloLectura:
        path = "/leer"
        methods = {"GET", "HEAD"}

    class Escribe:
        path = "/escribir"
        methods = {"POST"}

    assert write_methods(SoloLectura()) == ()
    assert is_write_capable(SoloLectura()) is False
    assert write_methods(Escribe()) == ("POST",)
    assert is_write_capable(Escribe()) is True


def test_un_websocket_bajo_el_prefijo_se_declara_capaz_de_escribir():
    """R10 de punta a punta sobre el helper compartido."""
    from fastapi import FastAPI

    from app.chassis import METHODS_NOT_ENUMERABLE, write_methods

    app = FastAPI()

    @app.websocket("/panel/review/ws")
    async def _ws(websocket):  # pragma: no cover
        await websocket.accept()

    culpables = [(str(getattr(r, "path", "")), write_methods(r))
                 for r in iter_mounted_routes(app)
                 if str(getattr(r, "path", "")).startswith("/panel/review")
                 and write_methods(r)]
    assert culpables == [("/panel/review/ws", (METHODS_NOT_ENUMERABLE,))]


# --- El `path` es tri-estado, y el filtro tiene frontera de SEGMENTO --------

def test_effective_path_distingue_ausencia_de_raiz():
    """`''` es ausencia de dato, no "la raíz". Misma doctrina que `methods`."""
    from app.chassis import PATH_NOT_RESOLVABLE, effective_path, route_path

    class SinPath:
        pass

    class PathNulo:
        path = None

    class PathVacio:
        path = ""

    class PathReal:
        path = "/panel/review"

    for opaca in (SinPath(), PathNulo(), PathVacio()):
        assert effective_path(opaca) is None, type(opaca).__name__
        assert route_path(opaca) == PATH_NOT_RESOLVABLE
    assert effective_path(PathReal()) == "/panel/review"
    assert route_path(PathReal()) == "/panel/review"


def test_una_ruta_con_path_irresoluble_cae_DENTRO_de_cualquier_prefijo():
    """FALLA CERRADO: no saber dónde está una ruta no la pone fuera.

    Es el suelo que queda si un tipo de ruta futuro vuelve a llegar sin path
    resoluble: el consumidor la reporta en vez de saltársela en silencio.
    """
    from app.chassis import route_in_prefix, write_methods

    class Irresoluble:
        path = ""

    r = Irresoluble()
    assert route_in_prefix(r, "/panel/review") is True
    assert route_in_prefix(r, "/panel/operations") is True
    # Y ademas es capaz de escribir, asi que el consumidor la saca por rojo.
    assert write_methods(r)


def test_el_filtro_de_prefijo_respeta_la_frontera_de_segmento():
    """FALSO POSITIVO (M-E): `/panel/review` no contiene a `/panel/reviewXYZ`.

    Un rojo por el motivo equivocado es más peligroso que un verde: acusar al
    hueco C de una escritura que no está en su espacio de URL entrena a ignorar
    el gate. Y B/F/G van a tener prefijos vecinos.
    """
    from app.chassis import path_in_prefix

    dentro = ["/panel/review", "/panel/review/", "/panel/review/item/{id}",
              "/panel/review/inc/m/aprobar"]
    fuera = ["/panel/reviewXYZ/borrar", "/panel/reviews", "/panel/review-legacy",
             "/panel", "/panel/operations", "/otro/panel/review"]

    for path in dentro:
        assert path_in_prefix(path, "/panel/review"), path
    for path in fuera:
        assert not path_in_prefix(path, "/panel/review"), path


def test_el_prefijo_con_barra_final_no_cambia_la_frontera():
    from app.chassis import path_in_prefix

    for prefijo in ("/panel/review", "/panel/review/"):
        assert path_in_prefix("/panel/review/item/{id}", prefijo)
        assert not path_in_prefix("/panel/reviewXYZ/borrar", prefijo)


@pytest.mark.parametrize("slot", FEATURE_SLOTS, ids=lambda s: s.key)
def test_ningun_hueco_captura_el_espacio_de_otro(slot):
    """Los cuatro prefijos son disjuntos POR SEGMENTOS, no sólo por texto."""
    from app.chassis import path_in_prefix

    for otro in FEATURE_SLOTS:
        if otro.key == slot.key:
            continue
        assert not path_in_prefix(otro.prefix, slot.prefix), (
            f"El espacio del hueco {slot.key} ({slot.prefix}) se traga al "
            f"del hueco {otro.key} ({otro.prefix})"
        )
