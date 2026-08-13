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


def test_no_mounted_route_serves_200_to_anonymous(real_app, auth_on):
    """Con auth activada y SIN sesión, ninguna ruta devuelve 200.

    Ésta es la forma operativa de "ausencia de dato nunca es permiso máximo":
    el anónimo es exactamente el caso de contexto ausente.
    """
    client = _client(real_app)
    fugas = []
    for route in iter_mounted_routes(real_app):
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if not path or path in ANON_ALLOWED_PATHS:
            continue
        for method in sorted(m for m in methods if m in {"GET", "POST"}):
            r = client.request(method, _sample_path(path),
                               headers={"accept": "text/html"})
            if r.status_code == 200:
                fugas.append(f"{method} {path}")
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

@pytest.mark.parametrize("slot", FEATURE_SLOTS, ids=lambda s: s.key)
def test_slot_renders_empty_state_instead_of_exploding(real_app, auth_on, slot):
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
