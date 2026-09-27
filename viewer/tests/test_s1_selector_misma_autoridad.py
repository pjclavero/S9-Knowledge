"""S1 — «el selector no ofrece lo que el producto rechaza».

Medido sobre 9110b67: `AuthMiddleware` pintaba `request.state.user_partidas`
con `auth_db.list_partida_access(conn, user_id=user.id)` -- SIN filtrar por
workspace -- mientras `/partida/select` autoriza con
`user_allowed_partidas(..., workspace=canónico)`. Concedida una partida en un
workspace distinto del canónico, el selector la seguía ofreciendo y elegirla
daba 403 `{"detail": "No tienes asignada esa partida."}`.

El arreglo: `app.authz.existencia.partidas_seleccionables` es la ÚNICA
respuesta a "¿qué puede elegir este usuario?", y tanto el middleware (pinta el
selector) como `/partida/select` (decide si acepta la elección) pasan por
ahí. Esta suite recorre las opciones que el selector REALMENTE pinta y las
elige de verdad -- no infiere la propiedad, la ejerce.

La garantía de que la partida activa invalidada NO sobrevive internamente
(`sessions.active_partida` en la base, no solo lo que se pinta) ya la cubre
`authz.dependencies._still_has_access` / `_clear_active_partida`, re-verificada
en cada petición vía `get_visibility_context`. Esta suite NO la duplica: la
ejercita end-to-end junto con la desaparición del selector (ver
`test_partida_invalidada_no_aparece_en_el_selector_NI_sobrevive_en_la_sesion`)
y se apoya en los testigos ya existentes de
`test_multipartida_m5a_adversarial.py`
(`test_revocar_partida_tambien_limpia_la_sesion`,
`test_reverificacion_no_cruza_desde_otro_workspace`), que este mismo corte deja
calibrados en `scripts/calibracion/mutaciones_s1_selector_misma_autoridad.py`.
"""
from __future__ import annotations

import os
import re

import pytest

WS = "juego:s1-selector"
OTRO_WS = "juego:s1-otro"
PARTIDA_A = "partida:uno"
PARTIDA_B = "partida:dos"


@pytest.fixture
def auth_env(tmp_path):
    db = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db)
    os.environ["S9K_CSRF_SECRET"] = "clave-csrf-larga-y-aleatoria-para-tests-s1-selector-1234567890"
    os.environ["S9K_SESSION_SECURE"] = "false"
    os.environ["S9K_DEFAULT_WORKSPACE"] = WS
    from app.auth.config import get_auth_settings
    from app.config import get_settings
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    from app.auth import db as auth_db
    auth_db.ensure_migrated(db)
    yield db
    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_CSRF_SECRET",
              "S9K_SESSION_SECURE", "S9K_DEFAULT_WORKSPACE"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


def _client():
    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


def _make_user(db, username, role="viewer"):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    with auth_db.get_conn(db) as conn:
        return auth_db.create_user(
            conn, username=username, display_name=username,
            password_hash=hash_password("x" * 14), role=role,
        )


def _logged_client(db, user):
    from app.auth.config import get_auth_settings
    from app.auth.sessions import create_session
    from app.auth import db as auth_db
    with auth_db.get_conn(db) as conn:
        token, _ = create_session(conn, user)
    c = _client()
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, token)
    return c


def _grant(db, user, partida_id, workspace=WS):
    from app.auth import db as auth_db
    with auth_db.get_conn(db) as conn:
        return auth_db.grant_partida_access(conn, user.id, workspace, partida_id,
                                            granted_by="admin")


def _pagina(client, path="/entities"):
    r = client.get(path, headers={"accept": "text/html"})
    assert r.status_code == 200, r.text[:300]
    return r.text


def _csrf_from(html):
    m = re.search(r'name="csrf_token" value="([^"]*)"', html)
    assert m, f"no se encontró csrf_token en la página: {html[:300]}"
    return m.group(1)


def _opciones_del_selector(html):
    """Las `partida_id` que el <select> del selector REALMENTE ofrece
    (excluida la opción "— Capa juego —", que vale cadena vacía)."""
    bloque = re.search(
        r'<select id="partida_id"[^>]*>(.*?)</select>', html, re.DOTALL,
    )
    if bloque is None:
        return []
    return re.findall(r'<option value="([^"]+)"', bloque.group(1))


def _select(client, csrf, partida_id, next_path="/entities"):
    return client.post(
        "/partida/select",
        data={"partida_id": partida_id, "next": next_path, "csrf_token": csrf},
    )


# ===========================================================================
# Negativo — concesión en workspace distinto del canónico: NO aparece
# ===========================================================================

def test_concesion_en_otro_workspace_no_aparece_en_el_selector(auth_env):
    user = _make_user(auth_env, "jugador_otro_ws")
    _grant(auth_env, user, PARTIDA_A, workspace=OTRO_WS)
    c = _logged_client(auth_env, user)

    html = _pagina(c)
    assert PARTIDA_A not in _opciones_del_selector(html), (
        "el selector ofrece una partida concedida en un workspace que no es "
        "el canónico -- exactamente la divergencia medida en 9110b67"
    )


# ===========================================================================
# Positivo — concesión en el workspace canónico: SÍ aparece y SÍ funciona
# ===========================================================================

def test_concesion_en_workspace_canonico_aparece_y_funciona_al_elegirla(auth_env):
    user = _make_user(auth_env, "jugador_ws_correcto")
    _grant(auth_env, user, PARTIDA_A, workspace=WS)
    c = _logged_client(auth_env, user)

    html = _pagina(c)
    opciones = _opciones_del_selector(html)
    assert PARTIDA_A in opciones, "una concesión legítima debe seguir ofreciéndose"

    r = _select(c, _csrf_from(html), PARTIDA_A)
    assert r.status_code == 302, (
        f"la partida ofrecida por el selector no se pudo elegir: {r.status_code} {r.text[:200]}"
    )


# ===========================================================================
# La propiedad, ejercida: NINGUNA opción ofrecida produce 403 al elegirla
# ===========================================================================

def test_ninguna_opcion_ofrecida_por_el_selector_produce_403(auth_env):
    user = _make_user(auth_env, "jugador_varias_partidas")
    _grant(auth_env, user, PARTIDA_A, workspace=WS)
    _grant(auth_env, user, PARTIDA_B, workspace=WS)
    # Una concesión "trampa" en otro workspace: si se colase en la lista,
    # elegirla debe dar 403 -- y por eso NO debe aparecer en las opciones.
    _grant(auth_env, user, "partida:trampa", workspace=OTRO_WS)
    c = _logged_client(auth_env, user)

    html = _pagina(c)
    opciones = _opciones_del_selector(html)
    assert set(opciones) == {PARTIDA_A, PARTIDA_B}

    resultados = {}
    for partida_id in opciones:
        html = _pagina(c)  # csrf fresco por si el anterior invalidó cookies
        r = _select(c, _csrf_from(html), partida_id)
        resultados[partida_id] = r.status_code

    assert all(codigo == 302 for codigo in resultados.values()), (
        f"una opción ofrecida por el selector fue rechazada: {resultados}"
    )


# ===========================================================================
# Sin partidas ofrecibles: la pantalla no miente ni se rompe
# ===========================================================================

def test_sin_partidas_ofrecibles_la_pantalla_es_veraz(auth_env):
    user = _make_user(auth_env, "sin_partidas")
    # Solo concesiones fuera del workspace canónico -- cero partidas ofrecibles.
    _grant(auth_env, user, PARTIDA_A, workspace=OTRO_WS)
    c = _logged_client(auth_env, user)

    html = _pagina(c)
    assert _opciones_del_selector(html) == []
    # La pantalla se sirve igual (200), sin selector roto ni una opción
    # fantasma: `{% if request.state.user_partidas %}` oculta el formulario
    # entero en vez de pintar un <select> vacío que sugiriera partidas que no
    # existen.
    assert '<select id="partida_id"' not in html


# ===========================================================================
# La partida activa que deja de ser válida no puede seguir pintada como activa
# NI sobrevivir en el almacén de sesión (por dentro, no solo por fuera)
# ===========================================================================

def test_partida_invalidada_no_aparece_en_el_selector_ni_sobrevive_en_la_sesion(auth_env):
    """Concesión hecha en OTRO_WS, activada manipulando la sesión directamente
    (como ya hace `test_reverificacion_no_cruza_desde_otro_workspace` en
    `test_multipartida_m5a_adversarial.py`, que es la MISMA situación con la
    que WS pasa a ser el canónico y la concesión queda fuera de ámbito).

    Se mide POR EFECTO, no solo por lo que se pinta:
      - el selector ya no la ofrece (HTML);
      - `sessions.active_partida` en la base YA NO la conserva (almacén);
      - una petición posterior a una ruta con ámbito real no opera bajo ese
        contexto (contenido servido).
    """
    from app.auth import db as auth_db

    user = _make_user(auth_env, "sesion_manipulada")
    _grant(auth_env, user, PARTIDA_A, workspace=OTRO_WS)
    c = _logged_client(auth_env, user)

    with auth_db.get_conn(auth_env) as conn:
        row = conn.execute(
            "SELECT id FROM sessions WHERE user_id = ?", (user.id,)
        ).fetchone()
        auth_db.set_session_active_partida(conn, row["id"], PARTIDA_A)

    # Petición a una ruta con ámbito real: dispara la re-verificación
    # (`get_visibility_context` -> `_still_has_access` -> `_clear_active_partida`)
    # y ejercita el consumo de contenido bajo ese contexto.
    r = c.get("/api/entities?limit=1000", headers={"accept": "application/json"})
    assert r.status_code == 200, r.text[:300]
    ids = {i["id"] for i in r.json()["items"]}
    assert not any("partida1" in i or PARTIDA_A.split(":")[-1] in i for i in ids), (
        f"la petición posterior operó bajo un contexto ya inválido: {ids}"
    )

    # Por dentro: el almacén ya no conserva la partida activa.
    with auth_db.get_conn(auth_env) as conn:
        row = conn.execute(
            "SELECT active_partida FROM sessions WHERE user_id = ?", (user.id,)
        ).fetchone()
    assert row["active_partida"] is None, (
        "la partida activa sobrevivió a su invalidación en sessions.active_partida"
    )

    # Por fuera: el selector, además, ni siquiera la ofrece (nunca tuvo
    # concesión en el workspace canónico).
    html = _pagina(c)
    assert PARTIDA_A not in _opciones_del_selector(html)


# ===========================================================================
# Un administrador no pierde nada de lo que hoy tiene
# ===========================================================================

def test_admin_ve_las_partidas_del_workspace_canonico_aunque_no_sean_suyas(auth_env):
    """Antes de S1 el selector del admin salía de sus PROPIAS concesiones
    (`list_partida_access(user_id=admin.id)`), y un admin normalmente no tiene
    concesiones propias (`admin_full` ya le da acceso total). El selector
    ahora usa la misma autoridad que `/partida/select`, que para un admin
    acepta cualquier partida que EXISTA canónicamente
    (`existencia.partida_existe`) -- así que el selector debe ofrecer también
    las concesiones de otros usuarios en el workspace canónico, y elegirlas
    debe seguir funcionando exactamente igual que hoy."""
    admin = _make_user(auth_env, "admin_s1", role="admin")
    otro = _make_user(auth_env, "jugador_de_otro", role="viewer")
    _grant(auth_env, otro, PARTIDA_A, workspace=WS)
    _grant(auth_env, admin, PARTIDA_B, workspace=WS)  # el admin también puede tener las suyas

    c = _logged_client(auth_env, admin)
    html = _pagina(c)
    opciones = _opciones_del_selector(html)
    assert PARTIDA_A in opciones, "el admin pierde una partida que hoy podía elegir"
    assert PARTIDA_B in opciones

    r = _select(c, _csrf_from(html), PARTIDA_A)
    assert r.status_code == 302, f"el admin no pudo elegir una partida ofrecida: {r.text[:200]}"
