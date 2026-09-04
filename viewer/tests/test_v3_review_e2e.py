"""PUERTA 6B — 36 casos extremo a extremo de revisión humana V3, SIN fixtures.

La cadena que se ejercita aquí es la real y completa::

    texto real del split dev
        -> KnowledgePipeline (extracción DETERMINISTA, local_only, writer dry-run)
        -> review_export.export_review_package
        -> directorio proposals/
        -> ReviewService (cola + ledger append-only)
        -> GET/POST /v3/review vía TestClient de FastAPI (auth real, roles reales)

No hay ninguna propuesta pregrabada en el camino principal: el paquete de
`proposals/` lo escribe el motor en la fixture de sesión `real_proposals`.
Las únicas propuestas construidas a mano son las de los casos de control
(hash cruzado, paquete inválido), y están marcadas como tales.

Prohibiciones respetadas: sin Ollama, sin NVIDIA, sin Neo4j, writer siempre
en dry-run (el pipeline de test nunca recibe driver).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import uuid
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_ENGINE = _REPO / "data-engine" / "app"
_ENGINE_TESTS = _ENGINE / "tests"
for _p in (str(_ENGINE), str(_ENGINE_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("jsonschema")

from app.routers import v3_review as router_module  # noqa: E402
from app.services.v3_glossary_candidates import GlossaryCandidateStore  # noqa: E402
from app.services import v3_review as v3r  # noqa: E402
from exception_codes import raises_code  # noqa: E402
from app.services.v3_review import (  # noqa: E402
    HistoryIntegrityError,
    ReviewError,
    ReviewService,
    StaleReviewError,
    load_proposals,
    proposal_hash,
    read_history,
)

WORKSPACE = "bench-dev"
OTHER_WORKSPACE = "bench-ajeno"
PASSWORD = "TestPass_1234567890!"


# ---------------------------------------------------------------------------
# Cadena real: motor -> proposals/
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def real_proposals(tmp_path_factory) -> tuple[Path, list[dict], str]:
    """Ejecuta el pipeline REAL sobre el texto real del split dev.

    Devuelve `(directorio, documentos, hash_del_glosario_efectivo)`. El hash del
    glosario se calcula ANTES de exportar nada: es el punto de partida de la
    prueba de no-mutación (caso 36).
    """
    from test_knowledge_v3_e2e_fixtures import (  # noqa: E402
        gold_dev,
        pipeline,
        snapshot_entities,
    )
    from knowledge_v3.pipeline import from_raw  # noqa: E402

    gold = gold_dev()
    entities = snapshot_entities(gold)
    engine = pipeline(gold)
    assert engine.config.workspace == WORKSPACE
    # Writer en dry-run: el pipeline de pruebas no construye ningún driver.
    assert getattr(engine, "driver", None) is None

    glossary_before = effective_glossary_hash(engine)

    directory = tmp_path_factory.mktemp("v3-review-e2e") / "proposals"
    result = engine.run(
        [from_raw(source) for source in gold.sources],
        catalog_entities=entities,
        review_proposals_dir=directory,
    )
    assert result.runs, "el pipeline no produjo ninguna corrida"
    documents = load_proposals(directory)
    assert documents, "el pipeline real no exportó ninguna propuesta"
    # El glosario efectivo no puede haber cambiado por correr el motor.
    assert effective_glossary_hash(engine) == glossary_before
    return directory, documents, glossary_before


def effective_glossary_hash(engine) -> str:
    """Hash canónico del glosario EFECTIVO que ve la cadena.

    El glosario efectivo de V3 es el `Lexicon` del workspace (alias del perfil
    + nombres y tipos del catálogo) más la fuente de glosario de la cascada de
    resolución. Ninguna de las dos tiene API de escritura desde el viewer: eso
    es exactamente lo que la prueba de no-mutación debe demostrar.
    """
    lexicon = engine.config.lexicon
    entries = []
    for entry in getattr(lexicon, "entries", ()) or ():
        entries.append({
            "canonical": getattr(entry, "canonical", None),
            "entity_type": getattr(entry, "entity_type", None),
            "variants": sorted(getattr(entry, "variants", ()) or ()),
            "confidence": getattr(entry, "confidence", None),
            "origin": getattr(entry, "origin", None),
        })
    entries.sort(key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
    body = {
        "lexicon": entries,
        "glossary_source": type(getattr(engine.config, "glossary", None)).__name__,
        "workspace": engine.config.workspace,
    }
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@pytest.fixture
def workdir(tmp_path, real_proposals) -> tuple[Path, Path]:
    """Directorio de propuestas REAL (copiado tal cual) + ledger vacío."""
    directory, _documents, _hash = real_proposals
    target = tmp_path / "proposals"
    target.mkdir()
    for package in sorted(directory.glob("*.json")):
        (target / package.name).write_bytes(package.read_bytes())
    return target, tmp_path / "decisions.jsonl"


@pytest.fixture
def service(workdir) -> ReviewService:
    proposals_dir, decisions_path = workdir
    return ReviewService(proposals_dir, decisions_path)


# ---------------------------------------------------------------------------
# App real con auth real
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_env(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    monkeypatch.setenv("S9K_AUTH_ENABLED", "true")
    monkeypatch.setenv("S9K_AUTH_DB_PATH", str(db_path))
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    from app.auth import db as auth_db
    auth_db.ensure_migrated(db_path)
    yield db_path
    get_auth_settings.cache_clear()


def make_user(db_path: Path, username: str, role: str):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    with auth_db.get_conn(db_path) as conn:
        return auth_db.create_user(
            conn, username=username, display_name=username.title(),
            password_hash=hash_password(PASSWORD), role=role,
        )


def session_cookie(db_path: Path, user) -> str:
    from app.auth import db as auth_db
    from app.auth.sessions import create_session
    with auth_db.get_conn(db_path) as conn:
        token, _ = create_session(conn, user)
    return token


@pytest.fixture
def client_factory(auth_env, service, monkeypatch):
    """TestClient contra la app REAL, con el servicio apuntando al dir real."""
    monkeypatch.setattr(router_module, "_service", lambda: service)
    from fastapi.testclient import TestClient
    from app.main import app

    def build(role: str | None = None, username: str | None = None):
        client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
        if role is not None:
            user = make_user(auth_env, username or f"u-{role}-{uuid.uuid4().hex[:8]}", role)
            client.cookies.set("s9k_session", session_cookie(auth_env, user))
        return client

    return build


_CSRF = re.compile(r'name="csrf_token" value="([^"]*)"')
_HASH = re.compile(r'name="expected_proposal_hash" value="([^"]*)"')
_REQ = re.compile(r'name="request_id" value="([^"]*)"')


def rendered_form(client, workspace: str = WORKSPACE) -> tuple[str, list[str], str]:
    """Lee el feed y devuelve lo que el revisor REALMENTE vio."""
    response = client.get(f"/v3/review?workspace={workspace}")
    assert response.status_code == 200, response.status_code
    csrf = _CSRF.search(response.text).group(1)
    hashes = _HASH.findall(response.text)
    request_id = _REQ.search(response.text).group(1)
    return csrf, hashes, request_id


def decide_form(*, workspace, proposal_id, decision, request_id, csrf, expected_hash, **extra):
    form = {
        "workspace": workspace, "proposal_id": proposal_id,
        "human_decision": decision, "request_id": request_id,
        "csrf_token": csrf, "expected_proposal_hash": expected_hash,
    }
    form.update(extra)
    return form


def first_item(service: ReviewService, workspace: str = WORKSPACE) -> dict:
    return service.queue(workspace).items[0]


# ===========================================================================
# GRUPO A — ACCESO Y ROLES (casos 1-8)
# ===========================================================================

def test_01_anonimo_no_lee_el_feed(client_factory):
    response = client_factory().get(f"/v3/review?workspace={WORKSPACE}")
    assert response.status_code == 302
    assert "/login" in response.headers["location"]


def test_02_anonimo_no_puede_decidir(client_factory, service, workdir):
    _proposals, decisions = workdir
    item = first_item(service)
    response = client_factory().post("/v3/review/decide", data=decide_form(
        workspace=WORKSPACE, proposal_id=item["proposal_id"], decision="APPROVE",
        request_id="anon-1", csrf="", expected_hash=item["proposal_hash"]))
    assert response.status_code == 302
    assert "/login" in response.headers["location"]
    assert not decisions.exists(), "un anónimo escribió en el ledger"


def test_03_rol_viewer_insuficiente_para_leer(client_factory):
    response = client_factory("viewer").get(f"/v3/review?workspace={WORKSPACE}")
    assert response.status_code == 403


def test_04_rol_viewer_insuficiente_para_decidir(client_factory, service, workdir):
    _proposals, decisions = workdir
    item = first_item(service)
    response = client_factory("viewer").post("/v3/review/decide", data=decide_form(
        workspace=WORKSPACE, proposal_id=item["proposal_id"], decision="APPROVE",
        request_id="viewer-1", csrf="", expected_hash=item["proposal_hash"]))
    assert response.status_code == 403
    assert not decisions.exists()


def test_05_rol_reviewer_lee_el_feed(client_factory):
    assert client_factory("reviewer").get(f"/v3/review?workspace={WORKSPACE}").status_code == 200


def test_06_rol_admin_lee_el_feed(client_factory):
    assert client_factory("admin").get(f"/v3/review?workspace={WORKSPACE}").status_code == 200


def test_07_sesion_invalida_no_escala_a_reviewer(client_factory):
    client = client_factory()
    client.cookies.set("s9k_session", "no-es-una-sesion-valida")
    response = client.get(f"/v3/review?workspace={WORKSPACE}")
    assert response.status_code == 302
    assert "/login" in response.headers["location"]


def test_08_csrf_invalido_no_registra_decision(client_factory, service, workdir):
    _proposals, decisions = workdir
    client = client_factory("reviewer")
    _csrf, _hashes, request_id = rendered_form(client)
    item = first_item(service)
    response = client.post("/v3/review/decide", data=decide_form(
        workspace=WORKSPACE, proposal_id=item["proposal_id"], decision="APPROVE",
        request_id=request_id, csrf="csrf-falsificado",
        expected_hash=item["proposal_hash"]))
    assert response.status_code == 403
    assert read_history(decisions) == []


# ===========================================================================
# GRUPO B — CARGA DEL FEED DESDE PROPUESTAS REALES (casos 9-17)
# ===========================================================================

def test_09_el_paquete_lo_escribio_el_motor_no_una_fixture(real_proposals):
    directory, documents, _hash = real_proposals
    packages = sorted(directory.glob("*.json"))
    assert len(packages) == 1
    assert packages[0].name.startswith(f"{WORKSPACE}--")
    # El nombre es content-addressed: el digest del cuerpo es el del fichero.
    body = json.loads(packages[0].read_text(encoding="utf-8"))
    assert body["workspace"] == WORKSPACE
    assert len(body["items"]) == len(documents) > 0


def test_10_toda_propuesta_real_cita_texto_literal_del_episodio(real_proposals):
    _directory, documents, _hash = real_proposals
    for document in documents:
        start = document["evidence"]["start"]
        end = document["evidence"]["end"]
        assert document["episode_text"][start:end] == document["evidence"]["literal_text"]
        assert document["evidence"]["literal_text"].strip(), document["proposal_id"]


def test_11_solo_se_exportan_decisiones_revisables(real_proposals):
    _directory, documents, _hash = real_proposals
    outcomes = {d["engine_decision"]["decision"] for d in documents}
    assert outcomes <= {"REVIEW", "ABSTAIN", "REJECT_INVALID"}
    assert "ACCEPT" not in outcomes


def test_12_el_feed_html_muestra_las_propuestas_reales(client_factory, service):
    response = client_factory("reviewer").get(f"/v3/review?workspace={WORKSPACE}")
    view = service.queue(WORKSPACE)
    assert view.total == len(service.queue(WORKSPACE, include_decided=True).items)
    for item in view.items:
        assert item["proposal_id"] in response.text
        assert f"<mark>{item['evidence_literal']}</mark>" in response.text


def test_13_el_feed_es_estable_entre_dos_cargas(client_factory, service):
    client = client_factory("reviewer")
    key = lambda i: (i["source_id"], i["episode_id"], i["proposal_id"])  # noqa: E731
    first = [key(i) for i in service.queue(WORKSPACE).items]
    client.get(f"/v3/review?workspace={WORKSPACE}")
    second = [key(i) for i in service.queue(WORKSPACE).items]
    assert first == second, "el feed no es estable entre dos cargas"
    assert first == sorted(first), "el orden del feed no es determinista"


def test_14_filtro_por_source_id_real(service):
    sources = service.queue(WORKSPACE).sources
    assert len(sources) >= 2, "el corpus real debe tener más de una fuente"
    for source in sources:
        view = service.queue(WORKSPACE, source_id=source)
        assert view.items and all(i["source_id"] == source for i in view.items)


def test_15_filtro_por_engine_decision_real(service):
    decisions = service.queue(WORKSPACE).decisions
    assert decisions
    for decision in decisions:
        view = service.queue(WORKSPACE, engine_decision=decision)
        assert all(i["engine_decision"]["decision"] == decision for i in view.items)


def test_16_workspace_desconocido_es_404(client_factory):
    response = client_factory("reviewer").get("/v3/review?workspace=no-existe")
    assert response.status_code == 404


def test_17_el_feed_no_cruza_workspaces(service, workdir, real_proposals):
    """Un paquete de OTRO workspace no puede aparecer en el feed de éste."""
    proposals_dir, _decisions = workdir
    _directory, documents, _hash = real_proposals
    ajeno = json.loads(json.dumps(documents[0]))
    ajeno["workspace"] = OTHER_WORKSPACE
    ajeno["proposal_id"] = "review:ajeno"
    (proposals_dir / "ajeno.json").write_text(
        json.dumps({"workspace": OTHER_WORKSPACE, "items": [ajeno]}), encoding="utf-8")
    assert set(service.workspaces()) == {WORKSPACE, OTHER_WORKSPACE}
    assert all(i["workspace"] == WORKSPACE for i in service.queue(WORKSPACE).items)
    assert [i["proposal_id"] for i in service.queue(OTHER_WORKSPACE).items] == ["review:ajeno"]


# ===========================================================================
# GRUPO C — DECISIONES: APROBAR / RECHAZAR / EDITAR (casos 18-26)
# ===========================================================================

def test_18_aprobar_via_http_sobre_propuesta_real(client_factory, service, workdir):
    _proposals, decisions = workdir
    client = client_factory("reviewer", username="mara")
    csrf, hashes, request_id = rendered_form(client)
    item = first_item(service)
    assert item["proposal_hash"] in hashes, "el HTML no mostró el hash real"
    response = client.post("/v3/review/decide", data=decide_form(
        workspace=WORKSPACE, proposal_id=item["proposal_id"], decision="APPROVE",
        request_id=request_id, csrf=csrf, expected_hash=item["proposal_hash"]))
    assert response.status_code == 303
    history = read_history(decisions)
    assert len(history) == 1
    assert history[0]["human_decision"] == "APPROVE"
    assert history[0]["reviewer"] == "mara"
    assert history[0]["proposal_id"] == item["proposal_id"]


def test_19_rechazar_via_http(client_factory, service, workdir):
    _proposals, decisions = workdir
    client = client_factory("reviewer")
    csrf, _hashes, request_id = rendered_form(client)
    item = first_item(service)
    assert client.post("/v3/review/decide", data=decide_form(
        workspace=WORKSPACE, proposal_id=item["proposal_id"], decision="REJECT",
        request_id=request_id, csrf=csrf, expected_hash=item["proposal_hash"],
        rationale="No se sostiene con la evidencia citada.",
    )).status_code == 303
    record = read_history(decisions)[0]
    assert record["human_decision"] == "REJECT"
    assert record["rationale"] == "No se sostiene con la evidencia citada."


def test_20_editar_requiere_al_menos_un_cambio(client_factory, service, workdir):
    _proposals, decisions = workdir
    client = client_factory("reviewer")
    csrf, _hashes, request_id = rendered_form(client)
    item = first_item(service)
    response = client.post("/v3/review/decide", data=decide_form(
        workspace=WORKSPACE, proposal_id=item["proposal_id"], decision="CORRECT",
        request_id=request_id, csrf=csrf, expected_hash=item["proposal_hash"]))
    assert response.status_code == 400
    assert read_history(decisions) == []


def test_21_editar_registra_la_correccion(client_factory, service, workdir):
    _proposals, decisions = workdir
    client = client_factory("reviewer")
    csrf, _hashes, request_id = rendered_form(client)
    item = first_item(service)
    assert client.post("/v3/review/decide", data=decide_form(
        workspace=WORKSPACE, proposal_id=item["proposal_id"], decision="CORRECT",
        request_id=request_id, csrf=csrf, expected_hash=item["proposal_hash"],
        predicate="leads", direction="subject_to_object",
    )).status_code == 303
    record = read_history(decisions)[0]
    assert record["correction"] == {"predicate": "leads", "direction": "subject_to_object"}
    assert record["human_decision"] == "CORRECT"


def test_22_decision_desconocida_se_rechaza(service):
    item = first_item(service)
    with raises_code(ReviewError, v3r.INVALID_HUMAN_DECISION):
        service.record(proposal_id=item["proposal_id"], workspace=WORKSPACE,
                       reviewer="mara", human_decision="MAYBE", request_id="bad-1",
                       expected_proposal_hash=item["proposal_hash"])


def test_23_falta_el_hash_esperado_es_400(client_factory, service, workdir):
    _proposals, decisions = workdir
    client = client_factory("reviewer")
    csrf, _hashes, request_id = rendered_form(client)
    item = first_item(service)
    form = decide_form(workspace=WORKSPACE, proposal_id=item["proposal_id"],
                       decision="APPROVE", request_id=request_id, csrf=csrf,
                       expected_hash="")
    assert client.post("/v3/review/decide", data=form).status_code == 400
    assert read_history(decisions) == []


def test_24_propuesta_inexistente_en_el_workspace(service):
    with raises_code(ReviewError, v3r.PROPOSAL_NOT_FOUND):
        service.record(proposal_id="review:no-existe", workspace=WORKSPACE,
                       reviewer="mara", human_decision="APPROVE", request_id="ghost-1",
                       expected_proposal_hash="0" * 64)


def test_25_la_decision_saca_la_propuesta_de_la_cola(client_factory, service):
    before = service.queue(WORKSPACE)
    client = client_factory("reviewer")
    csrf, _hashes, request_id = rendered_form(client)
    item = before.items[0]
    client.post("/v3/review/decide", data=decide_form(
        workspace=WORKSPACE, proposal_id=item["proposal_id"], decision="APPROVE",
        request_id=request_id, csrf=csrf, expected_hash=item["proposal_hash"]))
    after = service.queue(WORKSPACE)
    assert after.remaining == before.remaining - 1
    assert item["proposal_id"] not in {i["proposal_id"] for i in after.items}
    assert after.total == before.total, "decidir no puede borrar propuestas"


def test_26_una_decision_humana_no_es_un_plan_de_mutacion(client_factory, service, workdir):
    """Aprobar no produce plan, ni escritura de grafo, ni toque al motor."""
    proposals_dir, decisions = workdir

    class ExplotaSiSeUsa:
        def __getattr__(self, name):
            raise AssertionError(f"el servicio de revisión tocó el grafo: {name}")

    guarded = ReviewService(proposals_dir, decisions, graph_driver=ExplotaSiSeUsa())
    item = guarded.queue(WORKSPACE).items[0]
    record = guarded.record(proposal_id=item["proposal_id"], workspace=WORKSPACE,
                            reviewer="mara", human_decision="APPROVE",
                            request_id="no-plan-1",
                            expected_proposal_hash=item["proposal_hash"])
    assert "plan" not in record and "mutation_plan" not in record
    assert not any("plan" in key for key in record)
    assert record["human_decision"] == "APPROVE"


# ===========================================================================
# GRUPO D — INTEGRIDAD APPEND-ONLY DEL LEDGER (casos 27-32)
# ===========================================================================

def test_27_el_reenvio_del_formulario_no_duplica(client_factory, service, workdir):
    _proposals, decisions = workdir
    client = client_factory("reviewer")
    csrf, _hashes, request_id = rendered_form(client)
    item = first_item(service)
    form = decide_form(workspace=WORKSPACE, proposal_id=item["proposal_id"],
                       decision="APPROVE", request_id=request_id, csrf=csrf,
                       expected_hash=item["proposal_hash"])
    assert client.post("/v3/review/decide", data=form).status_code == 303
    assert client.post("/v3/review/decide", data=form).status_code == 303
    assert client.post("/v3/review/decide", data=form).status_code == 303
    assert len(read_history(decisions)) == 1


def test_28_dos_decisiones_distintas_se_encadenan(client_factory, service, workdir):
    _proposals, decisions = workdir
    client = client_factory("reviewer")
    items = service.queue(WORKSPACE).items
    assert len(items) >= 2, "el corpus real debe dar al menos dos propuestas"
    for index, item in enumerate(items[:2]):
        csrf, _hashes, request_id = rendered_form(client)
        assert client.post("/v3/review/decide", data=decide_form(
            workspace=WORKSPACE, proposal_id=item["proposal_id"], decision="APPROVE",
            request_id=f"{request_id}-{index}", csrf=csrf,
            expected_hash=item["proposal_hash"])).status_code == 303
    history = read_history(decisions)
    assert len(history) == 2
    assert history[0]["previous_hash"] is None
    assert history[1]["previous_hash"] == history[0]["record_hash"]


def test_29_corregir_no_borra_la_decision_anterior(service, workdir):
    _proposals, decisions = workdir
    item = first_item(service)
    first = service.record(proposal_id=item["proposal_id"], workspace=WORKSPACE,
                           reviewer="mara", human_decision="APPROVE",
                           request_id="d-1",
                           expected_proposal_hash=item["proposal_hash"])
    second = service.record(proposal_id=item["proposal_id"], workspace=WORKSPACE,
                            reviewer="mara", human_decision="REJECT",
                            request_id="d-2", rationale="Me equivoqué.",
                            supersedes_decision_id=first["decision_id"],
                            expected_proposal_hash=item["proposal_hash"])
    history = read_history(decisions)
    assert [r["decision_id"] for r in history] == [first["decision_id"], second["decision_id"]]
    assert history[0] == first, "la entrada original fue modificada"
    assert second["supersedes_decision_id"] == first["decision_id"]


def test_30_reescribir_una_entrada_rompe_la_cadena(service, workdir):
    _proposals, decisions = workdir
    item = first_item(service)
    service.record(proposal_id=item["proposal_id"], workspace=WORKSPACE, reviewer="mara",
                   human_decision="APPROVE", request_id="t-1",
                   expected_proposal_hash=item["proposal_hash"])
    record = json.loads(decisions.read_text(encoding="utf-8").splitlines()[0])
    record["human_decision"] = "REJECT"
    decisions.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    with raises_code(HistoryIntegrityError, v3r.HISTORY_HASH_INVALID):
        read_history(decisions)


def test_31_borrar_una_entrada_rompe_la_cadena(service, workdir):
    _proposals, decisions = workdir
    items = service.queue(WORKSPACE).items[:2]
    for index, item in enumerate(items):
        service.record(proposal_id=item["proposal_id"], workspace=WORKSPACE,
                       reviewer="mara", human_decision="APPROVE",
                       request_id=f"del-{index}",
                       expected_proposal_hash=item["proposal_hash"])
    lines = decisions.read_text(encoding="utf-8").splitlines()
    decisions.write_text(lines[1] + "\n", encoding="utf-8")
    with raises_code(HistoryIntegrityError, v3r.HISTORY_CHAIN_BROKEN):
        read_history(decisions)


def test_32_request_id_no_se_reutiliza_para_otra_decision(service):
    items = service.queue(WORKSPACE).items[:2]
    service.record(proposal_id=items[0]["proposal_id"], workspace=WORKSPACE,
                   reviewer="mara", human_decision="APPROVE", request_id="reuse-1",
                   expected_proposal_hash=items[0]["proposal_hash"])
    with raises_code(ReviewError, v3r.REQUEST_ID_REUSED):
        service.record(proposal_id=items[1]["proposal_id"], workspace=WORKSPACE,
                       reviewer="mara", human_decision="APPROVE", request_id="reuse-1",
                       expected_proposal_hash=items[1]["proposal_hash"])


# ===========================================================================
# GRUPO E — STALE_REVIEW (casos 33-36)
# ===========================================================================

def test_33_hash_que_el_revisor_nunca_vio_es_stale(service, workdir):
    _proposals, decisions = workdir
    item = first_item(service)
    with raises_code(StaleReviewError, v3r.STALE_REVIEW):
        service.record(proposal_id=item["proposal_id"], workspace=WORKSPACE,
                       reviewer="mara", human_decision="APPROVE",
                       request_id="stale-1", expected_proposal_hash="0" * 64)
    assert read_history(decisions) == []
    audit = [json.loads(line) for line in
             (decisions.parent / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert audit[-1]["event"] == "STALE_REVIEW"
    assert audit[-1]["proposal_id"] == item["proposal_id"]


def test_34_hash_de_otra_propuesta_real_es_stale(service, workdir):
    """Base cambiada de verdad: el hash es el de OTRA propuesta real del motor."""
    _proposals, decisions = workdir
    items = service.queue(WORKSPACE).items
    assert len(items) >= 2
    with raises_code(StaleReviewError, v3r.STALE_REVIEW):
        service.record(proposal_id=items[0]["proposal_id"], workspace=WORKSPACE,
                       reviewer="mara", human_decision="APPROVE",
                       request_id="stale-2",
                       expected_proposal_hash=items[1]["proposal_hash"])
    assert read_history(decisions) == []


def test_35_stale_via_http_redirige_con_aviso_y_no_escribe(client_factory, service, workdir):
    _proposals, decisions = workdir
    client = client_factory("reviewer")
    csrf, _hashes, request_id = rendered_form(client)
    item = first_item(service)
    response = client.post("/v3/review/decide", data=decide_form(
        workspace=WORKSPACE, proposal_id=item["proposal_id"], decision="APPROVE",
        request_id=request_id, csrf=csrf, expected_hash="f" * 64))
    assert response.status_code == 303
    assert "notice=STALE_REVIEW" in response.headers["location"]
    assert read_history(decisions) == []
    # Y la propuesta sigue pendiente: nada se perdió.
    assert item["proposal_id"] in {i["proposal_id"] for i in service.queue(WORKSPACE).items}


def test_36_stale_no_altera_el_historial_valido_previo(service, workdir):
    _proposals, decisions = workdir
    items = service.queue(WORKSPACE).items
    good = service.record(proposal_id=items[0]["proposal_id"], workspace=WORKSPACE,
                          reviewer="mara", human_decision="APPROVE",
                          request_id="good-1",
                          expected_proposal_hash=items[0]["proposal_hash"])
    before = decisions.read_bytes()
    with pytest.raises(StaleReviewError):
        service.record(proposal_id=items[1]["proposal_id"], workspace=WORKSPACE,
                       reviewer="mara", human_decision="REJECT",
                       request_id="stale-3", expected_proposal_hash="a" * 64)
    assert decisions.read_bytes() == before
    assert read_history(decisions) == [good]


# ===========================================================================
# PRUEBA DE NO-MUTACIÓN DEL GLOSARIO (obligatoria, transversal)
# ===========================================================================

def test_no_mutacion_del_glosario_en_el_flujo_completo(
    real_proposals, client_factory, service, workdir, tmp_path
):
    """Hash del glosario efectivo ANTES y DESPUÉS de TODO el flujo.

    Flujo: pipeline + exportación (ya hechos en la fixture de sesión) +
    carga del feed + APPROVE + REJECT + CORRECT con campos de glosario.
    El flujo propone candidatos; el glosario efectivo debe quedar idéntico.
    """
    from test_knowledge_v3_e2e_fixtures import gold_dev, pipeline  # noqa: E402
    _directory, _documents, hash_inicial = real_proposals
    proposals_dir, decisions = workdir

    engine = pipeline(gold_dev())
    antes = effective_glossary_hash(engine)
    assert antes == hash_inicial, "el glosario ya había cambiado antes de empezar"

    client = client_factory("reviewer", username="mara")
    items = service.queue(WORKSPACE).items
    assert len(items) >= 3, "hacen falta 3 propuestas reales para el flujo completo"
    plan = [
        ("APPROVE", {}),
        ("REJECT", {"rationale": "Sin evidencia suficiente."}),
        ("CORRECT", {"subject_alias": "Ilaria", "subject_canonical_name": "Ilaria Vandreth",
                     "spoken_form": "ilaría", "misrecognition": "Ylaria",
                     "suggested_entity_type": "PERSON", "is_ocr_asr_error": "true"}),
    ]
    for index, (decision, extra) in enumerate(plan):
        csrf, _hashes, request_id = rendered_form(client)
        item = items[index]
        response = client.post("/v3/review/decide", data=decide_form(
            workspace=WORKSPACE, proposal_id=item["proposal_id"], decision=decision,
            request_id=f"{request_id}-glos-{index}", csrf=csrf,
            expected_hash=item["proposal_hash"], **extra))
        assert response.status_code == 303, (decision, response.status_code)

    assert len(read_history(decisions)) == 3
    candidates = service.glossary_candidates(WORKSPACE)
    assert candidates, "la corrección explícita no propuso ningún candidato"
    assert {c["status"] for c in candidates} == {"PROPOSED"}

    despues = effective_glossary_hash(pipeline(gold_dev()))
    assert despues == antes, (
        "el flujo de revisión mutó el glosario efectivo\n"
        f"  antes:   {antes}\n  después: {despues}"
    )
    # Deja constancia de los dos hashes para el artefacto de la puerta.
    print(f"\nGLOSARIO_ANTES={antes}\nGLOSARIO_DESPUES={despues}")
