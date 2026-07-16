"""Tests del visor de solo lectura (Tarea C): entidades paginadas, fuentes, vendoring."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

VIEWER = Path(__file__).resolve().parents[1]


def _client():
    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


# ---------------------------------------------------------------------------
# API /api/entities (auth off => público, provider mock)
# ---------------------------------------------------------------------------

def test_api_entities_envelope():
    r = _client().get("/api/entities", headers={"accept": "application/json"})
    assert r.status_code == 200
    j = r.json()
    # Nuevo envelope: {items, pagination, filters}
    assert "items" in j
    assert "pagination" in j
    assert "filters" in j
    assert isinstance(j["items"], list)
    pag = j["pagination"]
    for k in ("total", "limit", "offset", "has_next", "has_previous"):
        assert k in pag, f"falta '{k}' en pagination"
    filt = j["filters"]
    for k in ("workspace", "q", "entity_type"):
        assert k in filt, f"falta '{k}' en filters"


def test_api_entities_pagination():
    c = _client()
    r1 = c.get("/api/entities?limit=1&offset=0")
    j1 = r1.json()
    assert len(j1["items"]) <= 1
    pag1 = j1["pagination"]
    assert pag1["limit"] == 1
    if pag1["total"] > 1:
        assert pag1["has_next"] is True
        r2 = c.get("/api/entities?limit=1&offset=1")
        assert r2.json()["items"] != j1["items"]


def test_api_entities_filter_type():
    r = _client().get("/api/entities?entity_type=Character&limit=100")
    for it in r.json()["items"]:
        assert it["type"] == "Character"


def test_api_entities_limit_capped():
    # limit=99999 → se capea silenciosamente a S9K_VIEWER_MAX_PAGE_SIZE (200); 200 OK
    r = _client().get("/api/entities?limit=99999")
    assert r.status_code == 200
    assert r.json()["pagination"]["limit"] <= 200


# ---------------------------------------------------------------------------
# Página HTML /entities
# ---------------------------------------------------------------------------

def test_entities_page_renders():
    r = _client().get("/entities", headers={"accept": "text/html"})
    assert r.status_code == 200
    assert "Entidades" in r.text


# ---------------------------------------------------------------------------
# vis-network vendorizado (sin CDN)
# ---------------------------------------------------------------------------

def test_graph_no_cdn():
    html = (VIEWER / "app/templates/graph.html").read_text(encoding="utf-8")
    # Ningún <script src> externo (unpkg/jsdelivr/http(s) remoto)
    assert "unpkg" not in html and "jsdelivr" not in html
    assert 'src="https://' not in html and 'src="http://' not in html
    assert "/static/js/vendor/vis-network.min.js" in html
    assert "integrity=" in html  # SRI presente


def test_vendor_file_present():
    f = VIEWER / "app/static/js/vendor/vis-network.min.js"
    assert f.exists() and f.stat().st_size > 100_000


# ---------------------------------------------------------------------------
# Solo lectura: el router no expone métodos de escritura
# ---------------------------------------------------------------------------

def test_readonly_router_has_no_write_methods():
    from app.routers import readonly
    for route in readonly.router.routes:
        methods = getattr(route, "methods", set()) or set()
        assert not (methods & {"POST", "PUT", "PATCH", "DELETE"}), route.path


# ---------------------------------------------------------------------------
# Roles con auth activada
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_env(tmp_path):
    db = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db)
    os.environ["S9K_CSRF_SECRET"] = "clave-csrf-larga-y-aleatoria-para-tests-1234567890"
    os.environ["S9K_SESSION_SECURE"] = "false"
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    from app.auth import db as auth_db
    auth_db.ensure_migrated(db)
    yield db
    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()


def _cookie(db, username, role):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session
    with auth_db.get_conn(db) as conn:
        u = auth_db.create_user(conn, username=username, display_name=username,
                                password_hash=hash_password("x" * 14), role=role)
        token, _ = create_session(conn, u)
    return token


def test_api_entities_anon_401(auth_env):
    r = _client().get("/api/entities", headers={"accept": "application/json"})
    assert r.status_code == 401


def test_entities_html_anon_redirect(auth_env):
    r = _client().get("/entities", headers={"accept": "text/html"})
    assert r.status_code == 302 and "/login" in r.headers.get("location", "")


def test_sources_viewer_forbidden(auth_env):
    from app.auth.config import get_auth_settings
    tok = _cookie(auth_env, "v", "viewer")
    c = _client()
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, tok)
    assert c.get("/sources", headers={"accept": "text/html"}).status_code == 403


def test_sources_reviewer_ok(auth_env):
    from app.auth.config import get_auth_settings
    tok = _cookie(auth_env, "rev", "reviewer")
    c = _client()
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, tok)
    assert c.get("/sources", headers={"accept": "text/html"}).status_code == 200


def test_entities_viewer_ok(auth_env):
    from app.auth.config import get_auth_settings
    tok = _cookie(auth_env, "v2", "viewer")
    c = _client()
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, tok)
    assert c.get("/entities", headers={"accept": "text/html"}).status_code == 200


# ===========================================================================
# Tests Tarea C — nuevas rutas, paginación real, seguridad, calidad (tests 14-34)
# ===========================================================================

# ---------------------------------------------------------------------------
# 14-15. Paginación: items <= limit, total correcto
# ---------------------------------------------------------------------------

def test_listado_paginado_items_le_limit():
    r = _client().get("/api/entities?limit=2&offset=0")
    assert r.status_code == 200
    j = r.json()
    assert len(j["items"]) <= 2
    assert j["pagination"]["limit"] == 2


def test_pagination_total_correcto():
    r_all = _client().get("/api/entities?limit=200&offset=0")
    total_all = r_all.json()["pagination"]["total"]
    r_p1 = _client().get("/api/entities?limit=1&offset=0")
    assert r_p1.json()["pagination"]["total"] == total_all


# ---------------------------------------------------------------------------
# 16-17. Parámetros SKIP/LIMIT llegan al proveedor (mock soporta paginación real)
# ---------------------------------------------------------------------------

def test_skip_parametrizado_en_provider():
    """Resultados en offset=0 y offset=1 son diferentes (si hay >1 entidad)."""
    r0 = _client().get("/api/entities?limit=1&offset=0")
    r1 = _client().get("/api/entities?limit=1&offset=1")
    j0 = r0.json()
    if j0["pagination"]["total"] > 1:
        assert r0.json()["items"] != r1.json()["items"]


def test_limit_parametrizado_en_provider():
    r1 = _client().get("/api/entities?limit=1")
    r3 = _client().get("/api/entities?limit=3")
    assert len(r1.json()["items"]) <= 1
    assert len(r3.json()["items"]) <= 3


# ---------------------------------------------------------------------------
# 18. Limit máximo respetado
# ---------------------------------------------------------------------------

def test_limit_maximo_respetado():
    r = _client().get("/api/entities?limit=99999")
    assert r.status_code == 200
    assert r.json()["pagination"]["limit"] <= 200


# ---------------------------------------------------------------------------
# 19. Offset negativo → 400
# ---------------------------------------------------------------------------

def test_offset_negativo_400():
    r = _client().get("/api/entities?offset=-1")
    assert r.status_code in (400, 422)


# ---------------------------------------------------------------------------
# 20-22. Filtros
# ---------------------------------------------------------------------------

def test_filtro_entity_type():
    r = _client().get("/api/entities?entity_type=Character&limit=50")
    j = r.json()
    for item in j["items"]:
        assert item["type"] == "Character"


def test_filtro_review_status():
    # No hay entidades con review_status=XXXX_NO_EXISTE → total=0, items vacíos
    r = _client().get("/api/entities?review_status=XXXX_NO_EXISTE")
    assert r.status_code == 200
    assert r.json()["pagination"]["total"] == 0


def test_filtro_confidence_min():
    r = _client().get("/api/entities?min_confidence=0.99")
    assert r.status_code == 200
    for item in r.json()["items"]:
        if item["confidence"] is not None:
            assert float(item["confidence"]) >= 0.99


# ---------------------------------------------------------------------------
# 23. Búsqueda q — parámetro Cypher, no concatenación
# ---------------------------------------------------------------------------

def test_busqueda_q_parametro():
    r = _client().get("/api/entities?q=tamori")
    assert r.status_code == 200
    j = r.json()
    assert j["filters"]["q"] == "tamori"
    # Todos los resultados deben contener "tamori" (insensible a mayúsculas)
    for item in j["items"]:
        haystack = (
            (item.get("label") or "") + " " +
            (item.get("description") or "") + " " +
            " ".join(item.get("aliases") or [])
        ).lower()
        assert "tamori" in haystack


# ---------------------------------------------------------------------------
# 24. Inyección SQL-style en q debe ser segura (no explota, devuelve items vacíos o con escaping)
# ---------------------------------------------------------------------------

def test_inyeccion_q_safe():
    payload = "' OR 1=1 --"
    r = _client().get(f"/api/entities?q={payload}")
    assert r.status_code == 200
    # No debe explotar; total puede ser 0 o mayor pero la respuesta es 200
    assert "items" in r.json()


# ---------------------------------------------------------------------------
# 25. Sort inválido → allowlist silenciosa (no error)
# ---------------------------------------------------------------------------

def test_sort_invalido_allowlist_silenciosa():
    r = _client().get("/api/entities?sort=__proto__&order=asc")
    assert r.status_code == 200  # se normaliza a canonical_name


# ---------------------------------------------------------------------------
# 26-27. Ficha de entidad
# ---------------------------------------------------------------------------

def test_entity_detail_existente():
    # Obtenemos el primer item para saber qué id usar
    r = _client().get("/api/entities?limit=1")
    items = r.json()["items"]
    if not items:
        return  # skip si no hay datos
    eid = items[0]["id"]
    r2 = _client().get(f"/api/entities/{eid}")
    assert r2.status_code == 200
    j = r2.json()
    assert "entity" in j
    assert "outgoing" in j
    assert "incoming" in j
    assert j["entity"]["id"] == eid


def test_entity_detail_inexistente_404():
    r = _client().get("/api/entities/id-que-no-existe-123456789")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 28. Propiedades ausentes → campo None/null, no error
# ---------------------------------------------------------------------------

def test_propiedades_ausentes_no_error():
    r = _client().get("/api/entities?limit=50")
    assert r.status_code == 200
    for item in r.json()["items"]:
        # El campo "description" puede ser None, "" o string — no KeyError
        _ = item.get("description")
        _ = item.get("confidence")  # puede ser None


# ---------------------------------------------------------------------------
# 29-31. Relaciones en ficha (mock sólo tiene edges entre nodos del sample)
# ---------------------------------------------------------------------------

def test_relaciones_entrantes_en_ficha():
    r = _client().get("/api/entities?limit=1")
    items = r.json()["items"]
    if not items:
        return
    eid = items[0]["id"]
    r2 = _client().get(f"/api/entities/{eid}")
    assert r2.status_code == 200
    assert isinstance(r2.json()["incoming"], list)


def test_relaciones_salientes_en_ficha():
    r = _client().get("/api/entities?limit=1")
    items = r.json()["items"]
    if not items:
        return
    eid = items[0]["id"]
    r2 = _client().get(f"/api/entities/{eid}")
    assert r2.status_code == 200
    assert isinstance(r2.json()["outgoing"], list)


# ---------------------------------------------------------------------------
# 32-33. Listado y detalle de fuentes
# ---------------------------------------------------------------------------

def test_listado_fuentes():
    r = _client().get("/api/sources")
    assert r.status_code == 200
    j = r.json()
    assert "workspace" in j
    assert "sources" in j
    assert isinstance(j["sources"], list)


def test_detalle_fuente_inexistente_404():
    r = _client().get("/api/sources/fuente-que-no-existe-xyz")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 34. Métricas de calidad — estructura correcta
# ---------------------------------------------------------------------------

def test_metricas_calidad_estructura():
    r = _client().get("/api/quality")
    assert r.status_code == 200
    j = r.json()
    assert "total_entities" in j
    assert "total_relations" in j
    assert "confidence_distribution" in j
    assert "data_gaps" in j
    cd = j["confidence_distribution"]
    for k in ("high_gte_0_8", "mid_gte_0_5", "low_lt_0_5", "no_value"):
        assert k in cd
    gaps = j["data_gaps"]
    for k in ("no_source_document", "no_description", "no_entity_type"):
        assert k in gaps


# ---------------------------------------------------------------------------
# 35-36. Roles con auth: anónimo HTML→302, anónimo API→401
# ---------------------------------------------------------------------------

def test_anon_html_quality_redirect(auth_env):
    r = _client().get("/quality", headers={"accept": "text/html"})
    assert r.status_code == 302 and "/login" in r.headers.get("location", "")


def test_anon_api_quality_401(auth_env):
    r = _client().get("/api/quality", headers={"accept": "application/json"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# 37-39. Roles: viewer NO accede a /sources, reviewer SÍ
# ---------------------------------------------------------------------------

def test_viewer_accede_entities(auth_env):
    from app.auth.config import get_auth_settings
    tok = _cookie(auth_env, "vv1", "viewer")
    c = _client()
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, tok)
    assert c.get("/entities").status_code == 200


def test_viewer_bloqueado_sources(auth_env):
    from app.auth.config import get_auth_settings
    tok = _cookie(auth_env, "vv2", "viewer")
    c = _client()
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, tok)
    assert c.get("/sources").status_code == 403


def test_reviewer_accede_sources(auth_env):
    from app.auth.config import get_auth_settings
    tok = _cookie(auth_env, "rev2", "reviewer")
    c = _client()
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, tok)
    assert c.get("/sources").status_code == 200


# ---------------------------------------------------------------------------
# 40-41. Router no tiene métodos de escritura (GET/HEAD/OPTIONS únicamente)
# ---------------------------------------------------------------------------

def test_router_sin_post():
    from app.routers import readonly
    for route in readonly.router.routes:
        methods = getattr(route, "methods", set()) or set()
        assert "POST" not in methods, f"POST encontrado en {route.path}"


def test_router_sin_put_patch_delete():
    from app.routers import readonly
    for route in readonly.router.routes:
        methods = getattr(route, "methods", set()) or set()
        assert not (methods & {"PUT", "PATCH", "DELETE"}), f"Método de escritura en {route.path}"


# ---------------------------------------------------------------------------
# 42. Auditoría Cypher: no hay tokens de escritura en readonly.py
# ---------------------------------------------------------------------------

def test_cypher_sin_tokens_escritura():
    """Verifica que el router readonly no contiene tokens Cypher de escritura."""
    import re
    WRITE_TOKENS = ["CREATE ", "MERGE ", " SET ", "DELETE ", "DETACH ", "REMOVE ", "DROP ", "LOAD CSV"]
    source = (VIEWER / "app/routers/readonly.py").read_text(encoding="utf-8")
    # Ignorar comentarios y strings de test/documentación
    for token in WRITE_TOKENS:
        assert token not in source, f"Token de escritura Cypher encontrado en readonly.py: '{token}'"


# ---------------------------------------------------------------------------
# 43. Sin CDN — vis-network vendor local (verificación extendida)
# ---------------------------------------------------------------------------

def test_no_cdn_confirmado():
    vendor = VIEWER / "app/static/js/vendor/vis-network.min.js"
    assert vendor.exists(), "vis-network.min.js no encontrado en vendor/"
    html_path = VIEWER / "app/templates/graph.html"
    content = html_path.read_text(encoding="utf-8")
    assert "unpkg" not in content
    assert "jsdelivr" not in content
    assert 'src="https://' not in content
    assert "/static/js/vendor/vis-network.min.js" in content


# ---------------------------------------------------------------------------
# 44. Páginas HTML de error: entity y source inexistentes dan 404 HTML
# ---------------------------------------------------------------------------

def test_entity_detail_html_404():
    r = _client().get("/entities/id-que-no-existe-xyz")
    assert r.status_code == 404


def test_source_detail_html_404():
    r = _client().get("/sources/fuente-que-no-existe-xyz")
    # Con auth off, reviewer es público, debe devolver 404
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 45. Panel de calidad HTML — accesible con auth off
# ---------------------------------------------------------------------------

def test_quality_html_renders():
    r = _client().get("/quality")
    assert r.status_code == 200
    assert "calidad" in r.text.lower() or "entidades" in r.text.lower()


# ---------------------------------------------------------------------------
# 46. Detalle de entidad HTML — accesible con auth off
# ---------------------------------------------------------------------------

def test_entity_detail_html_renders():
    r = _client().get("/api/entities?limit=1")
    items = r.json()["items"]
    if not items:
        return
    eid = items[0]["id"]
    r2 = _client().get(f"/entities/{eid}")
    assert r2.status_code == 200
    assert "Relaciones" in r2.text or "relaciones" in r2.text.lower()
