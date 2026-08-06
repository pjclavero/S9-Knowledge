"""Suite ADVERSARIAL de M5a (selector de partida + aislamiento en el visor).

No repite lo que ya cubren test_multipartida_isolation.py / _e2e.py (motor puro
+ rutas de entidades/grafo vía PolicyFilteredProvider). Verifica las garantías
de las superficies que NO pasan por el GraphProvider y el ciclo de vida del
acceso:

  - /review-console (contratos v1) y /v3/review (propuestas + glosario) aplican
    el ámbito de la petición (partida activa + capa juego) con el mismo motor
    de política, en listados, detalle y decisiones.
  - /jobs y /api/jobs (cola del data-engine) solo entregan trabajos del ámbito
    visible, y el detalle operativo (rutas de fichero del servidor) queda para
    admin.
  - Revocar el acceso a una partida invalida la sesión activa en la siguiente
    petición, sin esperar a un nuevo login.
  - El selector: CSRF real, sin inyección, sin open redirect, sin partidas
    inexistentes.
  - Semántica explícita de `partida_id` en blanco (fail-closed).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

FIXTURE = str(Path(__file__).resolve().parent / "fixtures" / "multipartida_graph.json")
WS = "juego:lab"
REPO_ROOT = Path(__file__).resolve().parents[2]

PARTIDA_A = "partida:uno"
PARTIDA_B = "partida:dos"


@pytest.fixture
def auth_env(tmp_path):
    db = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db)
    os.environ["S9K_CSRF_SECRET"] = "clave-csrf-larga-y-aleatoria-para-tests-m5a-adv-1234567890"
    os.environ["S9K_SESSION_SECURE"] = "false"
    os.environ["S9K_SAMPLE_GRAPH_PATH"] = FIXTURE
    os.environ["S9K_DEFAULT_WORKSPACE"] = WS
    from app.auth.config import get_auth_settings
    from app.config import get_settings
    from app.deps import get_provider
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    get_provider.cache_clear()
    from app.auth import db as auth_db
    auth_db.ensure_migrated(db)
    yield db
    for k in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_SAMPLE_GRAPH_PATH", "S9K_DEFAULT_WORKSPACE"):
        os.environ.pop(k, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    get_provider.cache_clear()


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


def _cookie_for(db, user):
    from app.auth import db as auth_db
    from app.auth.sessions import create_session
    with auth_db.get_conn(db) as conn:
        token, _ = create_session(conn, user)
    return token


def _logged_client(db, user):
    from app.auth.config import get_auth_settings
    c = _client()
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, _cookie_for(db, user))
    return c


def _entity_ids(client):
    r = client.get("/api/entities?limit=1000", headers={"accept": "application/json"})
    assert r.status_code == 200, r.text
    return {i["id"] for i in r.json()["items"]}


def _csrf_from(client, path="/entities"):
    page = client.get(path, headers={"accept": "text/html"})
    m = re.search(r'name="csrf_token" value="([^"]*)"', page.text)
    assert m, f"no se encontró csrf_token en {path}: {page.text[:300]}"
    return m.group(1)


def _grant(db, user, partida_id, workspace=WS):
    from app.auth import db as auth_db
    with auth_db.get_conn(db) as conn:
        return auth_db.grant_partida_access(conn, user.id, workspace, partida_id,
                                            granted_by="admin")


def _select(client, partida_id, expect=302):
    csrf = _csrf_from(client)
    r = client.post("/partida/select",
                    data={"partida_id": partida_id, "next": "/entities", "csrf_token": csrf})
    assert r.status_code == expect, f"{r.status_code}: {r.text[:300]}"
    return r


def _scope_for(partida_id, role="reviewer"):
    """Ámbito equivalente al de una petición de un usuario con esa partida activa."""
    from app.authz.context import build_viewer_context
    from app.authz.scope import VisibilityScope
    ctx = build_viewer_context(
        role=role, auth_enabled=True, default_workspace=WS, active_partida=partida_id,
    )
    return VisibilityScope(ctx)


# ===========================================================================
# P0 -- /review-console (contratos v1) respeta el ámbito de partida
# ===========================================================================

@pytest.fixture
def rc_fixtures(tmp_path, monkeypatch):
    """Corpus v1 real (validado contra los esquemas) con material de dos partidas.

    Se derivan tres fuentes del corpus de laboratorio existente: una de la
    partida A, una de la partida B y una de capa juego (sin partida). Los
    contratos v1 son cerrados salvo `metadata`, que es donde un documento v1
    declara su partida.
    """
    import app.services.review_console as rc

    base = tmp_path / "rc"
    shutil.copytree(rc.FIXTURES_DIR, base)
    src_summary = json.loads((base / "summaries" / "src_demo_01.json").read_text("utf-8"))
    src_candidates = [json.loads(p.read_text("utf-8"))
                      for p in sorted((base / "candidates" / "src_demo_01").glob("*.json"))]

    def derive(source_id: str, partida_id: str | None) -> None:
        summary = json.loads(json.dumps(src_summary))
        summary["source_id"] = source_id
        summary["document_id"] = f"review-source-summary_{source_id}"
        summary["provenance"]["source_id"] = source_id
        if partida_id is not None:
            summary.setdefault("metadata", {})["partida_id"] = partida_id
        (base / "summaries" / f"{source_id}.json").write_text(
            json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        target = base / "candidates" / source_id
        target.mkdir(parents=True, exist_ok=True)
        for index, original in enumerate(src_candidates):
            doc = json.loads(json.dumps(original))
            doc["source_id"] = source_id
            doc["document_id"] = f"{doc['document_id']}-{source_id}"
            doc["candidate_id"] = f"{doc['candidate_id']}-{source_id}"
            doc["provenance"]["source_id"] = source_id
            if partida_id is not None:
                doc.setdefault("metadata", {})["partida_id"] = partida_id
            (target / f"cand_{index:02d}.json").write_text(
                json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    for path in (base / "summaries").glob("*.json"):
        path.unlink()
    for path in (base / "candidates").iterdir():
        shutil.rmtree(path, ignore_errors=True)
    derive("src_partida_a", PARTIDA_A)
    derive("src_partida_b", PARTIDA_B)
    derive("src_capa_juego", None)

    monkeypatch.setattr(rc, "FIXTURES_DIR", base)
    return base


def test_review_console_solo_entrega_fuentes_del_ambito(auth_env, rc_fixtures):
    """La bandeja v1 entrega la partida activa y la capa juego; nunca la ajena."""
    user = _make_user(auth_env, "revisor_a", role="reviewer")
    _grant(auth_env, user, PARTIDA_A)
    c = _logged_client(auth_env, user)
    _select(c, PARTIDA_A)

    page = c.get("/review-console", headers={"accept": "text/html"})
    assert page.status_code == 200, page.text[:300]
    assert "src_partida_a" in page.text
    assert "src_capa_juego" in page.text
    assert "src_partida_b" not in page.text, "fuga: fuente de otra partida en la bandeja v1"


def test_review_console_detalle_de_otra_partida_responde_404(auth_env, rc_fixtures):
    """Fuera de ámbito == inexistente: el 404 no revela que la fuente existe."""
    user = _make_user(auth_env, "revisor_a2", role="reviewer")
    _grant(auth_env, user, PARTIDA_A)
    c = _logged_client(auth_env, user)
    _select(c, PARTIDA_A)

    assert c.get("/review-console/source/src_partida_a").status_code == 200
    assert c.get("/review-console/source/src_partida_b").status_code == 404
    assert c.get("/review-console/source/no_existe_en_absoluto").status_code == 404


def test_review_console_no_permite_decidir_sobre_otra_partida(auth_env, rc_fixtures, tmp_path):
    """Una decisión sobre material de otra partida se rechaza aunque se conozcan
    el candidate_id y el hash exactos: no basta con no enseñarlo."""
    import app.services.review_console as rc

    store = tmp_path / "lab-store"
    os.environ["S9K_REVIEW_LAB_DIR"] = str(store)
    try:
        candidate = rc.list_candidates("src_partida_b")[0]
        chash = rc.candidate_hash(candidate)["value"]

        user = _make_user(auth_env, "revisor_a3", role="reviewer")
        _grant(auth_env, user, PARTIDA_A)
        c = _logged_client(auth_env, user)
        _select(c, PARTIDA_A)
        csrf = _csrf_from(c, "/review-console")

        r = c.post(
            "/review-console/source/src_partida_b/decide",
            data={"candidate_id": candidate["candidate_id"], "action": "APPROVE",
                  "expected_candidate_hash": chash, "csrf_token": csrf},
        )
        assert r.status_code == 400, r.text[:300]
        assert not rc.read_decisions(), "se registró una decisión sobre material ajeno"
    finally:
        os.environ.pop("S9K_REVIEW_LAB_DIR", None)


def test_review_console_service_filtra_por_partida(rc_fixtures):
    """Garantía a nivel de servicio: el filtro vive en la capa de datos, no solo
    en la plantilla (listado, detalle y candidatos)."""
    import app.services.review_console as rc

    scope_a = _scope_for(PARTIDA_A)
    ids = {s["source_id"] for s in rc.list_source_summaries(scope=scope_a)}
    assert ids == {"src_partida_a", "src_capa_juego"}
    assert rc.get_source_summary("src_partida_b", scope=scope_a) is None
    assert rc.list_candidates("src_partida_b", scope=scope_a) == []
    assert rc.list_candidates("src_partida_a", scope=scope_a) != []

    # Sin partida activa: solo capa juego.
    scope_juego = _scope_for(None)
    assert {s["source_id"] for s in rc.list_source_summaries(scope=scope_juego)} == {"src_capa_juego"}


# ===========================================================================
# P0 -- /v3/review (propuestas + glosario) respeta el ámbito de partida
# ===========================================================================

def _v3_proposal(proposal_id: str, *, workspace: str, partida_id: str | None) -> dict:
    episode = "Ariadna protege la ciudad de Bruma durante el invierno."
    literal = "protege la ciudad de Bruma"
    start = episode.index(literal)
    doc = {
        "proposal_id": proposal_id,
        "workspace": workspace,
        "source_id": f"source-{proposal_id}",
        "episode_id": f"episode-{proposal_id}",
        "episode_text": episode,
        "evidence": {"start": start, "end": start + len(literal), "literal_text": literal},
        "proposal": {
            "subject": "Ariadna", "predicate": "PROTECTS", "object": "Bruma",
            "direction": "SUBJECT_TO_OBJECT",
            "negation": {"negated": False, "type": "NONE"},
            "scope": "durante el invierno",
        },
        "engine_decision": {"decision": "REVIEW", "reason_codes": ["AMBIGUOUS_PREDICATE"]},
        "ontology": {"version": "v1", "allowed_predicates": ["PROTECTS"]},
        "ontology_version": "v1",
        "engine_version": "knowledge-v3-test",
        "provider_trace": [{"name": "semantic-local"}],
        "metadata": {"reconciliation": {"support": []}},
    }
    if partida_id is not None:
        doc["partida_id"] = partida_id
    return doc


@pytest.fixture
def v3_service(tmp_path):
    from app.services.v3_review import ReviewService

    proposals = tmp_path / "proposals"
    proposals.mkdir()
    (proposals / "pkg.json").write_text(json.dumps([
        _v3_proposal("p-a", workspace="ws-mesa", partida_id=PARTIDA_A),
        _v3_proposal("p-b", workspace="ws-mesa", partida_id=PARTIDA_B),
        _v3_proposal("p-juego", workspace="ws-mesa", partida_id=None),
    ], ensure_ascii=False), encoding="utf-8")
    return ReviewService(proposals, tmp_path / "decisions.jsonl")


def test_v3_review_cola_solo_muestra_y_cuenta_lo_del_ambito(v3_service):
    """La partida ajena no aparece NI en los ítems NI en los totales: un conteo
    también delata material que no se puede ver."""
    view = v3_service.queue("ws-mesa", scope=_scope_for(PARTIDA_A))
    ids = {item["proposal_id"] for item in view.items}
    assert ids == {"p-a", "p-juego"}
    assert view.total == 2 and view.remaining == 2

    juego = v3_service.queue("ws-mesa", scope=_scope_for(None))
    assert {i["proposal_id"] for i in juego.items} == {"p-juego"}
    assert juego.total == 1


def test_v3_review_no_permite_decidir_sobre_propuesta_de_otra_partida(v3_service):
    from app.services.v3_review import ReviewError

    with pytest.raises(ReviewError):
        v3_service.record(
            proposal_id="p-b", workspace="ws-mesa", reviewer="revisor",
            human_decision="APPROVE", request_id="req-1", scope=_scope_for(PARTIDA_A),
        )
    # Y la misma decisión sobre la propia partida sí procede (el filtro no es
    # un "deniega siempre").
    ok = v3_service.record(
        proposal_id="p-a", workspace="ws-mesa", reviewer="revisor",
        human_decision="APPROVE", request_id="req-2", scope=_scope_for(PARTIDA_A),
    )
    assert ok["proposal"]["proposal_id"] == "p-a"


def test_v3_review_workspaces_visibles_dependen_del_ambito(tmp_path):
    from app.services.v3_review import ReviewService

    proposals = tmp_path / "proposals"
    proposals.mkdir()
    (proposals / "pkg.json").write_text(json.dumps([
        _v3_proposal("p-a", workspace="ws-a", partida_id=PARTIDA_A),
        _v3_proposal("p-b", workspace="ws-b", partida_id=PARTIDA_B),
    ], ensure_ascii=False), encoding="utf-8")
    service = ReviewService(proposals, tmp_path / "decisions.jsonl")

    assert service.workspaces(scope=_scope_for(PARTIDA_A)) == ("ws-a",)
    assert service.workspaces(scope=_scope_for(PARTIDA_B)) == ("ws-b",)
    assert service.workspaces(scope=_scope_for(None)) == ()


def test_v3_glossary_candidates_heredan_y_respetan_la_partida(v3_service):
    """Un candidato de glosario nacido de una propuesta de partida queda
    estampado con esa partida y no se filtra a otra."""
    v3_service.record(
        proposal_id="p-a", workspace="ws-mesa", reviewer="revisor",
        human_decision="CORRECT", request_id="req-glosario",
        correction={"subject_alias": "Aria"}, scope=_scope_for(PARTIDA_A),
    )
    propios = v3_service.glossary_candidates("ws-mesa", scope=_scope_for(PARTIDA_A))
    assert propios, "el candidato de la propia partida debe verse"
    assert all(c.get("partida_id") == PARTIDA_A for c in propios)
    assert v3_service.glossary_candidates("ws-mesa", scope=_scope_for(PARTIDA_B)) == []
    assert v3_service.glossary_candidates("ws-mesa", scope=_scope_for(None)) == []


def test_v3_review_ruta_html_aplica_el_ambito(auth_env, v3_service, monkeypatch):
    """La garantía no vive solo en el servicio: la ruta real inyecta el ámbito."""
    from app.routers import v3_review as router_module
    monkeypatch.setattr(router_module, "_service", lambda: v3_service)

    user = _make_user(auth_env, "revisor_v3", role="reviewer")
    _grant(auth_env, user, PARTIDA_A)
    c = _logged_client(auth_env, user)
    _select(c, PARTIDA_A)

    page = c.get("/v3/review?workspace=ws-mesa")
    assert page.status_code == 200, page.text[:300]
    assert "p-a" in page.text
    assert "p-b" not in page.text, "fuga: propuesta de otra partida en el feed V3"


# ===========================================================================
# P0 -- /api/jobs: ámbito visible + recorte del detalle operativo
# ===========================================================================

@pytest.fixture
def jobs_db(tmp_path):
    sys.path.insert(0, str(REPO_ROOT / "data-engine" / "app"))
    from jobs import job_store  # type: ignore

    db_path = str(tmp_path / "jobs.db")
    job_store.init_db(db_path)
    ids = {
        "ajeno": job_store.create_job(
            workspace="juego:otro", job_type="ingest",
            payload={"source_path": "sesion_de_otro_workspace.m4a"}, db_path=db_path),
        "partida_a": job_store.create_job(
            workspace=WS, job_type="ingest",
            payload={"partida_id": PARTIDA_A, "source_path": "sesion_a.m4a"}, db_path=db_path),
        "partida_b": job_store.create_job(
            workspace=WS, job_type="ingest",
            payload={"partida_id": PARTIDA_B, "source_path": "sesion_b.m4a"}, db_path=db_path),
        "capa_juego": job_store.create_job(
            workspace=WS, job_type="ingest",
            payload={"source_path": "manual_del_juego.pdf"}, db_path=db_path),
    }
    os.environ["S9K_JOBS_DB"] = db_path
    from app.config import get_settings
    get_settings.cache_clear()
    yield ids
    os.environ.pop("S9K_JOBS_DB", None)
    get_settings.cache_clear()


def _job_ids(client, path="/api/jobs?limit=100"):
    r = client.get(path)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body
    return {j["job_id"] for j in body["jobs"]}, body["jobs"]


def test_api_jobs_solo_entrega_los_del_ambito_visible(auth_env, jobs_db):
    """Un usuario con la partida A activa no ve jobs de la partida B ni de otro
    workspace; sí ve los suyos y los de capa juego."""
    user = _make_user(auth_env, "viewer_jobs", role="viewer")
    _grant(auth_env, user, PARTIDA_A)
    c = _logged_client(auth_env, user)
    _select(c, PARTIDA_A)

    ids, _ = _job_ids(c)
    assert jobs_db["partida_a"] in ids
    assert jobs_db["capa_juego"] in ids
    assert jobs_db["partida_b"] not in ids
    assert jobs_db["ajeno"] not in ids


def test_api_jobs_no_expone_rutas_de_fichero_a_no_admin(auth_env, jobs_db):
    """El payload lleva rutas del disco del servidor: solo admin lo ve."""
    user = _make_user(auth_env, "viewer_payload", role="viewer")
    _grant(auth_env, user, PARTIDA_A)
    c = _logged_client(auth_env, user)
    _select(c, PARTIDA_A)

    _, jobs = _job_ids(c)
    propio = next(j for j in jobs if j["job_id"] == jobs_db["partida_a"])
    assert "payload" not in propio and "payload_json" not in propio
    assert "sesion_a.m4a" not in json.dumps(jobs, ensure_ascii=False)
    assert propio["status"] and propio["workspace"] == WS  # sigue siendo útil

    admin = _make_user(auth_env, "admin_payload", role="admin")
    ca = _logged_client(auth_env, admin)
    _, jobs_admin = _job_ids(ca)
    detalle = next(j for j in jobs_admin if j["job_id"] == jobs_db["partida_a"])
    assert detalle["payload"]["source_path"] == "sesion_a.m4a"


def test_api_jobs_detalle_y_conteos_respetan_el_ambito(auth_env, jobs_db):
    """Ni el acceso por id ni los conteos delatan lo que no se puede listar."""
    user = _make_user(auth_env, "viewer_detalle", role="viewer")
    _grant(auth_env, user, PARTIDA_A)
    c = _logged_client(auth_env, user)
    _select(c, PARTIDA_A)

    propio = c.get(f"/api/jobs/{jobs_db['partida_a']}").json()
    assert propio["ok"] is True
    ajeno = c.get(f"/api/jobs/{jobs_db['partida_b']}").json()
    assert ajeno == {"ok": False, "error": "job_not_found"}
    inexistente = c.get("/api/jobs/no-existe").json()
    assert inexistente == ajeno, "el 404 debe ser indistinguible de inexistente"

    counts = c.get("/api/jobs/counts").json()["counts"]
    assert sum(counts.values()) == 2, counts  # partida A + capa juego


def test_panel_html_de_jobs_tambien_filtra(auth_env, jobs_db):
    user = _make_user(auth_env, "viewer_html", role="viewer")
    _grant(auth_env, user, PARTIDA_A)
    c = _logged_client(auth_env, user)
    _select(c, PARTIDA_A)

    page = c.get("/jobs", headers={"accept": "text/html"})
    assert page.status_code == 200
    assert jobs_db["partida_a"] in page.text
    assert jobs_db["partida_b"] not in page.text
    assert "sesion_b.m4a" not in page.text

    detalle = c.get(f"/jobs/{jobs_db['partida_b']}", headers={"accept": "text/html"})
    assert "job_not_found" in detalle.text


def test_api_jobs_sin_partida_activa_solo_ve_capa_juego(auth_env, jobs_db):
    user = _make_user(auth_env, "viewer_sin_partida", role="viewer")
    c = _logged_client(auth_env, user)
    ids, _ = _job_ids(c)
    assert ids == {jobs_db["capa_juego"]}


# ===========================================================================
# P0 -- revocar el acceso invalida la partida activa en la siguiente petición
# ===========================================================================

def test_revocar_partida_invalida_el_acceso_en_la_siguiente_peticion(auth_env):
    """``get_visibility_context`` re-verifica la partida activa contra
    ``partida_access`` en CADA petición: al revocar el acceso (p.ej. al expulsar
    a alguien de la mesa) el material deja de verse de inmediato, sin esperar a
    que la sesión expire o a que el usuario cambie de partida.
    """
    from app.auth import db as auth_db

    user = _make_user(auth_env, "jugador_expulsado")
    access = _grant(auth_env, user, PARTIDA_A)

    c = _logged_client(auth_env, user)
    _select(c, PARTIDA_A)
    assert "partida1_pc_arden" in _entity_ids(c)

    with auth_db.get_conn(auth_env) as conn:
        assert auth_db.revoke_partida_access(conn, access.id) is True

    ids_tras_revocar = _entity_ids(c)
    assert "partida1_pc_arden" not in ids_tras_revocar, (
        "la revocación debe surtir efecto en la siguiente petición")
    # Degrada a capa juego, no a "sin nada": el lore compartido sigue visible.
    assert "lore_dios_sol" in ids_tras_revocar


def test_revocar_partida_tambien_limpia_la_sesion(auth_env):
    """La degradación es persistente: la partida activa se limpia en la sesión,
    en vez de quedar almacenada como un valor ya inválido."""
    from app.auth import db as auth_db

    user = _make_user(auth_env, "jugador_expulsado_2")
    access = _grant(auth_env, user, PARTIDA_A)
    c = _logged_client(auth_env, user)
    _select(c, PARTIDA_A)
    with auth_db.get_conn(auth_env) as conn:
        auth_db.revoke_partida_access(conn, access.id)
    _entity_ids(c)  # una petición cualquiera dispara la re-verificación

    with auth_db.get_conn(auth_env) as conn:
        row = conn.execute(
            "SELECT active_partida FROM sessions WHERE user_id = ?", (user.id,)
        ).fetchone()
    assert row["active_partida"] is None


def test_reconceder_partida_vuelve_a_dar_acceso_tras_seleccionarla(auth_env):
    """Cierre del ciclo: la revocación no bloquea para siempre, pero re-conceder
    exige volver a seleccionar la partida (no se reactiva sola)."""
    from app.auth import db as auth_db

    user = _make_user(auth_env, "jugador_readmitido")
    access = _grant(auth_env, user, PARTIDA_A)
    c = _logged_client(auth_env, user)
    _select(c, PARTIDA_A)

    with auth_db.get_conn(auth_env) as conn:
        auth_db.revoke_partida_access(conn, access.id)
    assert "partida1_pc_arden" not in _entity_ids(c)

    _grant(auth_env, user, PARTIDA_A)
    assert "partida1_pc_arden" not in _entity_ids(c), (
        "re-conceder no debe reactivar sola una partida ya limpiada de la sesión")
    _select(c, PARTIDA_A)
    assert "partida1_pc_arden" in _entity_ids(c)


# ===========================================================================
# P1 -- selector: CSRF real, inyección, open redirect, partidas inexistentes
# ===========================================================================

def test_select_partida_sin_csrf_es_rechazado(auth_env):
    user = _make_user(auth_env, "sin_csrf")
    _grant(auth_env, user, PARTIDA_A)
    c = _logged_client(auth_env, user)
    # csrf_token es Form(...) obligatorio -> 422 sin el campo.
    r = c.post("/partida/select", data={"partida_id": PARTIDA_A, "next": "/entities"})
    assert r.status_code in (400, 403, 422)
    assert "partida1_pc_arden" not in _entity_ids(c)


def test_select_partida_con_csrf_de_otra_sesion_es_rechazado(auth_env):
    attacker = _make_user(auth_env, "atacante")
    victim = _make_user(auth_env, "victima")
    _grant(auth_env, victim, PARTIDA_A)

    c_attacker = _logged_client(auth_env, attacker)
    c_victim = _logged_client(auth_env, victim)

    csrf_de_atacante = _csrf_from(c_attacker)
    # El token está ligado al session.id: no vale el de otra sesión.
    r = c_victim.post(
        "/partida/select",
        data={"partida_id": PARTIDA_A, "next": "/entities", "csrf_token": csrf_de_atacante},
    )
    assert r.status_code == 403


def test_select_partida_con_caracteres_extranos_no_rompe_ni_concede(auth_env):
    user = _make_user(auth_env, "curioso")
    c = _logged_client(auth_env, user)
    csrf = _csrf_from(c)
    payloads = [
        "partida:uno' OR '1'='1",
        "../../etc/passwd",
        "juego:otro:partida:secreta",
        "\x00partida:uno",
        "partida:uno\nSet-Cookie: pwn=1",
        "a" * 5000,
    ]
    for p in payloads:
        r = c.post(
            "/partida/select",
            data={"partida_id": p, "next": "/entities", "csrf_token": csrf},
        )
        assert r.status_code == 403, f"payload aceptado indebidamente: {p!r} -> {r.status_code}"
    # La vista sigue en capa juego -- ninguna entrada rara coló una partida.
    assert _entity_ids(c) == {"lore_dios_sol", "legacy_material_sin_partida"}


def test_admin_no_puede_fijar_una_partida_inexistente(auth_env):
    """Un admin ve todo igualmente (admin_full), pero fijar una partida que no
    existe solo puede ser un error: se rechaza en vez de guardar basura en la
    sesión, y así `allowed_partida_ids` nunca contiene ids fantasma."""
    from app.auth import db as auth_db

    admin = _make_user(auth_env, "admin_curioso", role="admin")
    otro = _make_user(auth_env, "jugador_cualquiera")
    _grant(auth_env, otro, PARTIDA_A)  # esta partida sí existe

    c = _logged_client(auth_env, admin)
    csrf = _csrf_from(c)
    r = c.post("/partida/select",
               data={"partida_id": "partida:no-existe", "next": "/entities", "csrf_token": csrf})
    assert r.status_code == 400, r.text[:200]

    with auth_db.get_conn(auth_env) as conn:
        row = conn.execute("SELECT active_partida FROM sessions WHERE user_id = ?",
                           (admin.id,)).fetchone()
    assert row["active_partida"] is None

    # Una partida que sí existe sí puede activarla, y sigue viéndolo todo.
    _select(c, PARTIDA_A)
    assert {"partida1_pc_arden", "partida2_pc_bryn"} <= _entity_ids(c)


def test_next_open_redirect_bloqueado(auth_env):
    user = _make_user(auth_env, "redir")
    _grant(auth_env, user, PARTIDA_A)
    c = _logged_client(auth_env, user)
    csrf = _csrf_from(c)
    r = c.post(
        "/partida/select",
        data={"partida_id": PARTIDA_A, "next": "https://evil.example/steal", "csrf_token": csrf},
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/"


# ===========================================================================
# P1 -- `partida_id` en blanco: semántica explícita y fail-closed
# ===========================================================================

def test_partida_id_en_blanco_nunca_es_visible_ni_actua_de_comodin():
    """`partida_id: ""` no es capa juego: el contrato knowledge-v3 lo rechaza en
    el esquema (M2), así que solo puede llegar por dato corrupto. La decisión es
    explícita y fail-closed en los dos sentidos: el nodo no se ve, y un
    `active_partida` en blanco tampoco lo destapa.
    """
    from app.policies.engine import VisibilityPolicy
    from app.policies.models import ViewerContext

    policy = VisibilityPolicy()
    for blanco in ("", "   "):
        node = {"id": "n", "workspace": WS, "partida_id": blanco, "visibility": "player"}

        sin_partida = ViewerContext(
            role="viewer", allowed_workspaces=frozenset({WS}),
            allowed_partida_ids=frozenset(), can_view_reference=True, session_public=True,
        )
        d = policy.can_view(node, sin_partida)
        assert not d.visible and d.reason == "partida_id_blank"

        # Aunque alguien colase "" en allowed_partida_ids, no es un comodín.
        con_blanco = ViewerContext(
            role="viewer", allowed_workspaces=frozenset({WS}),
            active_partida=blanco, allowed_partida_ids=frozenset({blanco}),
            can_view_reference=True, session_public=True,
        )
        assert not policy.can_view(node, con_blanco).visible


def test_partida_activa_en_blanco_se_normaliza_a_capa_juego():
    """Construir el contexto con una partida en blanco equivale a no tener
    ninguna: capa juego, nunca un conjunto con la cadena vacía dentro."""
    from app.authz.context import build_viewer_context

    ctx = build_viewer_context(role="viewer", auth_enabled=True,
                               default_workspace=WS, active_partida="  ")
    assert ctx.active_partida is None
    assert ctx.allowed_partida_ids == frozenset()


def test_seleccionar_partida_vacia_vuelve_a_capa_juego(auth_env):
    """La cadena vacía en el selector significa "salir de la partida", y así
    queda almacenado (NULL), no como una partida llamada ""."""
    from app.auth import db as auth_db

    user = _make_user(auth_env, "vuelve_a_capa_juego")
    _grant(auth_env, user, PARTIDA_A)
    c = _logged_client(auth_env, user)
    _select(c, PARTIDA_A)
    assert "partida1_pc_arden" in _entity_ids(c)

    _select(c, "")
    with auth_db.get_conn(auth_env) as conn:
        row = conn.execute("SELECT active_partida FROM sessions WHERE user_id = ?",
                           (user.id,)).fetchone()
    assert row["active_partida"] is None
    assert _entity_ids(c) == {"lore_dios_sol", "legacy_material_sin_partida"}


# ===========================================================================
# P2 -- CSRF del layout: el token que ve el usuario funciona de verdad
# ===========================================================================

def test_csrf_token_no_queda_vacio_para_usuario_autenticado_en_logout(auth_env):
    """base.html usa
    `csrf_token | default(request.state.csrf_token, true) | default('')`.
    Si para un usuario autenticado `request.state.csrf_token` fuese "", el
    segundo `default('')` no dispararía (la cadena vacía no es 'undefined' para
    Jinja) y el POST /logout fallaría con 403 -- una regresión funcional real.
    Aquí se confirma que el token que llega al formulario es no vacío y sirve.
    """
    user = _make_user(auth_env, "cierra_sesion")
    c = _logged_client(auth_env, user)
    page = c.get("/entities", headers={"accept": "text/html"})
    assert page.status_code == 200
    m = re.search(r'name="csrf_token" value="([^"]*)"', page.text)
    assert m and m.group(1) != "", "csrf_token vacío para usuario autenticado -- logout se rompería"

    r = c.post("/logout", data={"csrf_token": m.group(1)})
    assert r.status_code in (302, 303), f"logout con csrf del layout falló: {r.status_code}"


def test_csrf_token_vacio_para_anonimo_no_permite_bypass(auth_env):
    """Para un anónimo el token es "": el selector exige sesión autenticada
    antes de llegar a la comprobación CSRF, así que un token vacío no abre
    nada."""
    c = _client()
    r = c.post("/partida/select", data={"partida_id": PARTIDA_A, "next": "/", "csrf_token": ""})
    assert r.status_code in (302, 401, 403), r.text
    if r.status_code == 302:
        assert "/login" in r.headers.get("location", "")
