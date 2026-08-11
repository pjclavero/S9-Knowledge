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
