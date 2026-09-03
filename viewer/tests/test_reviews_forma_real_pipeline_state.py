"""La forma REAL de `pipeline_state.json` no puede ensombrecer la declaración
de ámbito de una fuente.

`data-engine/app/review/review_store.py::ReviewStore.save_step` escribe un
documento INDEXADO POR PASO --`state[step] = {"status", "updated_at",
"details"}`-- y no escribe `partida_id` en ninguna parte (de hecho, todo
`data-engine/app/review/` no contiene esa cadena ni una vez). Un lector de
ámbito que se detenga en el PRIMER documento que sea un dict se queda con ese
estado del pipeline, no llega nunca a la declaración de
`approved_payload.metadata`, y una fuente ajena acaba tratada como material sin
partida --es decir, capa juego-- y se lista.

Estas pruebas derivan la forma del documento del código que lo escribe, no de
una suposición: `_pipeline_state_real()` reproduce literalmente lo que
`save_step` deja en disco.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

WS = "leyenda"
P_A = "partida-a"
P_B = "partida-b"


def _pipeline_state_real(pasos=("extract", "resolve", "approve")) -> dict:
    """Lo que `ReviewStore.save_step` escribe de verdad en `pipeline_state.json`.

    Un dict indexado por paso. Sin `partida_id`, sin `workspace`: ninguna de
    las rutas de declaración que `VisibilityScope` sabe leer.
    """
    ahora = datetime.now(timezone.utc).isoformat()
    return {
        paso: {"status": "done", "updated_at": ahora, "details": {"count": 3}}
        for paso in pasos
    }


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


def _fuente_realista(ws_dir: Path, source_id: str, partida, *,
                     con_pipeline_state: bool = True, secreto: str = "") -> Path:
    """Fuente con la forma que produce el pipeline de verdad.

    La partida SOLO se declara donde un paquete v1 puede declararla
    (`approved_payload.metadata`); `pipeline_state.json` va con su forma real,
    que no la lleva.
    """
    d = ws_dir / source_id
    d.mkdir(parents=True)
    meta = {"workspace": WS, "source_id": source_id, "schema_version": "1.0"}
    if partida is not None:
        meta["partida_id"] = partida
    (d / "approved_payload.json").write_text(json.dumps({
        "metadata": meta,
        "approved": [{"id": "%s-a%d" % (source_id, i), "name": secreto or source_id}
                     for i in range(3)],
    }), encoding="utf-8")
    (d / "review_queue.json").write_text(json.dumps(
        [{"id": "%s-p%d" % (source_id, i), "label": secreto or source_id} for i in range(2)]
    ), encoding="utf-8")
    (d / "rejected.json").write_text(json.dumps([]), encoding="utf-8")
    if con_pipeline_state:
        (d / "pipeline_state.json").write_text(
            json.dumps(_pipeline_state_real()), encoding="utf-8")
    return d


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


def _fuentes_listadas(texto):
    return set(re.findall(r'href="/reviews/([^"]+)"', texto))


# ---------------------------------------------------------------------------
# El defecto: precedencia ensombrecida por la forma real
# ---------------------------------------------------------------------------
def test_pipeline_state_real_no_ensombrece_la_declaracion_de_partida(entorno):
    """Con `pipeline_state.json` en su forma REAL, la fuente ajena sigue oculta.

    Este es el caso que el pipeline produce siempre: un estado por pasos, sin
    partida. Si el lector de ámbito se detiene ahí, la declaración de
    `approved_payload.metadata` no se lee nunca y la fuente de otra partida se
    trata como capa juego.
    """
    db, ws_dir = entorno
    _fuente_realista(ws_dir, "a-propia", P_A)
    _fuente_realista(ws_dir, "b-ajena", P_B, secreto="SECRETO_DE_OTRA_PARTIDA")

    c = _cliente(db, _usuario(db, "revisor_a"), P_A)
    r = c.get("/reviews?workspace=%s" % WS)
    assert r.status_code == 200, r.text
    assert _fuentes_listadas(r.text) == {"a-propia"}, (
        "la declaracion de partida quedo ensombrecida por pipeline_state.json"
    )
    assert "b-ajena" not in r.text

    detalle = c.get("/reviews/b-ajena?workspace=%s" % WS)
    assert detalle.status_code == 404, (
        "el detalle de la fuente ajena respondio %d" % detalle.status_code
    )
    assert "SECRETO_DE_OTRA_PARTIDA" not in detalle.text


def test_control_diferencial_pipeline_state_es_la_causa(entorno):
    """La MISMA fuente ajena, con y sin `pipeline_state.json`, queda oculta.

    Aisla la causa: si borrar un fichero que no declara nada cambiara la
    decision de ambito, la precedencia estaria mal.
    """
    db, ws_dir = entorno
    _fuente_realista(ws_dir, "b-con-estado", P_B)
    _fuente_realista(ws_dir, "b-sin-estado", P_B, con_pipeline_state=False)
    _fuente_realista(ws_dir, "a-propia", P_A)

    c = _cliente(db, _usuario(db, "revisor_a"), P_A)
    r = c.get("/reviews?workspace=%s" % WS)
    assert _fuentes_listadas(r.text) == {"a-propia"}
    for ajena in ("b-con-estado", "b-sin-estado"):
        assert c.get("/reviews/%s?workspace=%s" % (ajena, WS)).status_code == 404


# ---------------------------------------------------------------------------
# Regimen del corpus v1 sin atribucion posible
# ---------------------------------------------------------------------------
def test_fuente_sin_partida_determinable_no_se_lista_con_partida_activa(entorno):
    """Ninguna declaracion de partida en ningun documento: no se lista.

    «Si no podemos calcular el contador con seguridad, prefiero no mostrarlo.»
    Con una partida activa, una fuente cuya partida no se puede determinar NO
    es lore por omision: es material no atribuible, y no se publica.
    """
    db, ws_dir = entorno
    _fuente_realista(ws_dir, "a-propia", P_A)
    _fuente_realista(ws_dir, "sin-declaracion", None)

    c = _cliente(db, _usuario(db, "revisor_a"), P_A)
    r = c.get("/reviews?workspace=%s" % WS)
    assert _fuentes_listadas(r.text) == {"a-propia"}
    assert c.get("/reviews/sin-declaracion?workspace=%s" % WS).status_code == 404


def test_sin_partida_activa_el_corpus_sin_atribucion_sigue_siendo_capa_juego(entorno):
    """Sin partida activa, el corpus sin declaracion es capa juego y se ve.

    La regla anterior no puede convertirse en "nunca se ve nada": un lector con
    la llave de capa juego y sin partida activa sigue recibiendo el material
    que no pertenece a ninguna partida. Sin esto, el arreglo seria un apagon.
    """
    db, ws_dir = entorno
    _fuente_realista(ws_dir, "sin-declaracion", None)
    _fuente_realista(ws_dir, "b-ajena", P_B)

    c = _cliente(db, _usuario(db, "revisor_lore"), None)
    r = c.get("/reviews?workspace=%s" % WS)
    assert r.status_code == 200, r.text
    assert _fuentes_listadas(r.text) == {"sin-declaracion"}
    assert c.get("/reviews/b-ajena?workspace=%s" % WS).status_code == 404


def test_declaracion_mas_restrictiva_si_varios_documentos_declaran(entorno):
    """Si dos documentos declaran partidas distintas, manda la MAS restrictiva.

    Un documento no puede ampliar el ambito de otro: si `pipeline_state.json`
    dijera la partida del lector y `approved_payload` otra, la fuente sigue
    fuera de alcance.
    """
    db, ws_dir = entorno
    d = _fuente_realista(ws_dir, "contradictoria", P_B)
    estado = _pipeline_state_real()
    estado["partida_id"] = P_A  # declaracion mas permisiva, no debe ganar
    (d / "pipeline_state.json").write_text(json.dumps(estado), encoding="utf-8")
    _fuente_realista(ws_dir, "a-propia", P_A)

    c = _cliente(db, _usuario(db, "revisor_a"), P_A)
    r = c.get("/reviews?workspace=%s" % WS)
    assert _fuentes_listadas(r.text) == {"a-propia"}
    assert c.get("/reviews/contradictoria?workspace=%s" % WS).status_code == 404
