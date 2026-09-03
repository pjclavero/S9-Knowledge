"""La declaración de partida puede estar a CUALQUIER profundidad.

Regresión real introducida al retirar el filtrado ítem a ítem: el lector de
ámbito descendía a los documentos que son lista de NIVEL SUPERIOR
(`review_queue.json`, `rejected.json`, `candidates.json`) pero NO a la lista
ANIDADA `approved` dentro de `approved_payload.json`, que entraba como un solo
Mapping. Una fuente de la partida propia con ítems aprobados de otra partida
pasaba la barrera de fuente y publicaba sus contadores, su vista previa y su
informe global.

La lección de fondo, y por eso este fichero existe: que NINGUNA mutación matara
el filtro ítem a ítem no demostraba que fuera inerte, sólo que el instrumento
no lo medía --ninguna prueba del repo construía esta forma--. Antes de retirar
un control de seguridad hay que CONSTRUIR la forma que lo haría necesario y
comprobar que otra barrera la ataja.

Las formas reales tienen listas anidadas por todas partes: `KnowledgePackage`
(`data-engine/app/review/export_import.py`) escribe `entities`, `relations`,
`aliases`, `events`, `other`, `evidence`, `review_queue` y un
`approved_payload` completo dentro del mismo documento, más un
`workspace_metadata.pipeline_state` anidado. Enumerar claves es perder: la
unidad de control es RECORRER TODA LA ESTRUCTURA.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

WS = "leyenda"
P_A = "partida-a"
P_B = "partida-b"
SECRETO = "SECRETO_ANIDADO_DE_OTRA_PARTIDA"


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    db = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db)
    os.environ["S9K_CSRF_SECRET"] = "clave-csrf-larga-y-aleatoria-para-estas-pruebas-1234567890"
    os.environ["S9K_SESSION_SECURE"] = "false"
    os.environ["S9K_DEFAULT_WORKSPACE"] = WS
    from app.auth.config import get_auth_settings
    from app.config import get_settings
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    from app.auth import db as auth_db
    auth_db.ensure_migrated(db)

    import app.main as main_module
    fake_root = tmp_path / "repo"
    (fake_root / "output" / "reviews" / WS).mkdir(parents=True)
    monkeypatch.setattr(main_module, "REPO_ROOT", fake_root)

    yield db, fake_root / "output" / "reviews" / WS

    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_DEFAULT_WORKSPACE"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


def _usuario(db, username, role="reviewer"):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    with auth_db.get_conn(db) as conn:
        return auth_db.create_user(
            conn, username=username, display_name=username,
            password_hash=hash_password("x" * 16), role=role,
        )


def _cliente(db, user, partida):
    from fastapi.testclient import TestClient
    from app.auth import db as auth_db
    from app.auth.config import get_auth_settings
    from app.auth.sessions import create_session
    from app.main import app

    with auth_db.get_conn(db) as conn:
        token, session = create_session(conn, user)
        if partida is not None:
            auth_db.grant_partida_access(conn, user.id, WS, partida, granted_by="admin")
            auth_db.set_session_active_partida(conn, session.id, partida)
    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, token)
    return c


_BADGE = re.compile(r'counter-badge (approved|pending|rejected)[^>]*>\s*&#\d+;\s*(\d+|&#8212;)')


def _contadores_html(texto):
    total = {"approved": 0, "pending": 0, "rejected": 0}
    for clase, valor in _BADGE.findall(texto):
        if valor != "&#8212;":
            total[clase] += int(valor)
    return total


def _fuentes_listadas(texto):
    return set(re.findall(r'href="/reviews/([^"]+)"', texto))


def _fuente_contaminada_en_profundidad(ws_dir: Path, source_id: str) -> Path:
    """Fuente declarada en la partida PROPIA con material ajeno ANIDADO.

    La contaminación no está en el nivel superior de ningún documento: vive
    dentro de la lista `approved` (nivel 2), dentro de un dict que a su vez está
    dentro de esa lista (nivel 3), y dentro de una lista dentro de un dict
    dentro de una lista (nivel 4). Si el recorrido no es de profundidad
    arbitraria, alguno de estos se escapa.
    """
    d = ws_dir / source_id
    d.mkdir(parents=True)
    (d / "approved_payload.json").write_text(json.dumps({
        "metadata": {"workspace": WS, "source_id": source_id, "partida_id": P_A},
        "approved": [
            {"id": "propio-1", "name": "material propio"},
            {"id": "propio-2", "name": "material propio"},
            # nivel 2: dict dentro de la lista anidada
            {"id": "ajeno-1", "partida_id": P_B, "name": SECRETO},
            # nivel 3: dict dentro de un dict dentro de la lista
            {"id": "ajeno-2", "metadata": {"partida_id": P_B}, "name": SECRETO},
            # nivel 4: lista dentro de un dict dentro de la lista
            {"id": "ajeno-3", "hijos": [{"partida_id": P_B, "name": SECRETO}]},
            {"id": "ajeno-4", "scope": {"partida_id": P_B}, "name": SECRETO},
        ],
    }), encoding="utf-8")
    (d / "review_queue.json").write_text(json.dumps([]), encoding="utf-8")
    (d / "rejected.json").write_text(json.dumps([]), encoding="utf-8")
    (d / "pipeline_state.json").write_text(json.dumps(
        {"extract": {"status": "done", "updated_at": "x", "details": {}}}
    ), encoding="utf-8")
    (d / "quality_report.json").write_text(json.dumps(
        {"score": 0.93, "total": 137, "issues": 4}
    ), encoding="utf-8")
    return d


def _fuente_limpia(ws_dir: Path, source_id: str, partida) -> Path:
    d = ws_dir / source_id
    d.mkdir(parents=True)
    (d / "approved_payload.json").write_text(json.dumps({
        "metadata": {"workspace": WS, "source_id": source_id, "partida_id": partida},
        "approved": [{"id": "%s-a1" % source_id}],
    }), encoding="utf-8")
    (d / "review_queue.json").write_text(json.dumps([]), encoding="utf-8")
    (d / "rejected.json").write_text(json.dumps([]), encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# La barrera de fuente TIENE que ver la contaminación anidada
# ---------------------------------------------------------------------------
def test_contaminacion_anidada_deniega_la_fuente_entera(entorno):
    """Ítems de otra partida dentro de `approved_payload.approved`.

    En b8d5604 esta fuente se listaba con `approved: 6` (4 ajenos contados),
    su detalle respondía 200, la vista previa entregaba el contenido ajeno y el
    `quality_report` global se publicaba.
    """
    db, ws_dir = entorno
    _fuente_contaminada_en_profundidad(ws_dir, "a-contaminada")
    _fuente_limpia(ws_dir, "a-limpia", P_A)

    c = _cliente(db, _usuario(db, "revisor_a"), P_A)
    r = c.get("/reviews?workspace=%s" % WS)
    assert r.status_code == 200, r.text

    assert _fuentes_listadas(r.text) == {"a-limpia"}, (
        "la contaminacion anidada atraveso la barrera de fuente"
    )
    assert _contadores_html(r.text) == {"approved": 1, "pending": 0, "rejected": 0}
    assert SECRETO not in r.text

    detalle = c.get("/reviews/a-contaminada?workspace=%s" % WS)
    assert detalle.status_code == 404, (
        "el detalle de la fuente contaminada respondio %d" % detalle.status_code
    )
    assert SECRETO not in detalle.text
    # El informe global cubre tambien el material ajeno: no puede publicarse.
    for cifra in ("137", "0.93"):
        assert cifra not in detalle.text


@pytest.mark.parametrize("ruta_ajena, descripcion", [
    ({"approved": [{"partida_id": P_B}]}, "lista anidada nivel 2"),
    ({"approved": [{"metadata": {"partida_id": P_B}}]}, "dict dentro de lista"),
    ({"approved": [{"hijos": [{"partida_id": P_B}]}]}, "lista dentro de dict dentro de lista"),
    ({"bloques": {"grupo": {"items": [{"partida_id": P_B}]}}}, "dicts anidados"),
    ({"niveles": [[{"partida_id": P_B}]]}, "lista dentro de lista"),
    ({"a": {"b": {"c": {"d": [{"partida_id": P_B}]}}}}, "profundidad 5"),
])
def test_declaracion_ajena_a_cualquier_profundidad_deniega(entorno, ruta_ajena, descripcion):
    """El recorrido es de profundidad arbitraria, no una lista de sitios.

    La unidad de control es «recorrer toda la estructura»: cada una de estas
    formas esconde la declaracion ajena en un sitio distinto, y ninguna puede
    colarse.
    """
    db, ws_dir = entorno
    d = ws_dir / "sospechosa"
    d.mkdir(parents=True)
    doc = {"metadata": {"workspace": WS, "source_id": "sospechosa", "partida_id": P_A}}
    doc.update(ruta_ajena)
    (d / "approved_payload.json").write_text(json.dumps(doc), encoding="utf-8")
    _fuente_limpia(ws_dir, "a-limpia", P_A)

    c = _cliente(db, _usuario(db, "revisor_a"), P_A)
    r = c.get("/reviews?workspace=%s" % WS)
    assert _fuentes_listadas(r.text) == {"a-limpia"}, (
        "se colo una declaracion ajena escondida en: %s" % descripcion
    )
    assert c.get("/reviews/sospechosa?workspace=%s" % WS).status_code == 404


def test_la_fuente_propia_sin_contaminacion_sigue_visible(entorno):
    """Control positivo: el recorrido profundo no puede volverse un apagon.

    Una fuente con estructura anidada rica pero TODA de la partida propia se
    sigue sirviendo con sus cifras.
    """
    db, ws_dir = entorno
    d = ws_dir / "a-rica"
    d.mkdir(parents=True)
    (d / "approved_payload.json").write_text(json.dumps({
        "metadata": {"workspace": WS, "source_id": "a-rica", "partida_id": P_A},
        "approved": [
            {"id": "e1", "hijos": [{"id": "h1"}, {"id": "h2", "scope": {"partida_id": P_A}}]},
            {"id": "e2", "metadata": {"partida_id": P_A}},
        ],
    }), encoding="utf-8")
    (d / "review_queue.json").write_text(json.dumps(
        [{"id": "p1"}, {"id": "p2", "partida_id": P_A}]), encoding="utf-8")
    (d / "rejected.json").write_text(json.dumps([]), encoding="utf-8")

    c = _cliente(db, _usuario(db, "revisor_a"), P_A)
    r = c.get("/reviews?workspace=%s" % WS)
    assert _fuentes_listadas(r.text) == {"a-rica"}
    assert _contadores_html(r.text) == {"approved": 2, "pending": 2, "rejected": 0}
    assert c.get("/reviews/a-rica?workspace=%s" % WS).status_code == 200
