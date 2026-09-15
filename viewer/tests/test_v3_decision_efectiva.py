"""SLICE 2 · CORTE 2 — la decisión del operador cambia el motor, de verdad.

El defecto que esta suite cierra es un FALSO ÉXITO DE PRODUCTO: el operador
pulsaba «Aprobar», el visor lo guardaba, la pantalla confirmaba, y el motor
seguía proponiendo la misma reclamación para siempre porque nadie leía la
decisión de vuelta.

La cadena que se ejercita es la real y completa, sin dobles::

    pipeline REAL (determinista, local_only, writer dry-run)
        -> review_export.export_review_package  -> proposals/
        -> ReviewService  -> POST /v3/review/decide (auth real + CSRF real)
        -> [reinicio: servicio nuevo, export nuevo]
        -> el MOTOR lee la decisión de su autoridad y la propuesta cambia de estado

AUTORIDAD ÚNICA
---------------
La autoridad es la tabla ``human_decisions`` del SQLite del visor. El motor la
lee por un solo camino (``knowledge_v3.review_decisions``). ``decisions.jsonl``
es exportación de auditoría y NADIE la consume: hay un caso que lo demuestra
borrándola antes de que el motor lea.

Sin Ollama, sin NVIDIA, sin Neo4j; writer siempre en dry-run.
"""
from __future__ import annotations

import json
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
from app.services.v3_review import ReviewService, load_proposals  # noqa: E402

from knowledge_v3.review_export import export_review_package  # noqa: E402
from knowledge_v3 import review_decisions  # noqa: E402

WORKSPACE = "bench-dev"
PASSWORD = "TestPass_1234567890!"

_CSRF = re.compile(r'name="csrf_token" value="([^"]*)"')


# ---------------------------------------------------------------------------
# El motor, una sola vez
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def engine_result(tmp_path_factory):
    """Corre el pipeline REAL una vez y guarda su resultado reutilizable."""
    from test_knowledge_v3_e2e_fixtures import gold_dev, pipeline, snapshot_entities
    from knowledge_v3.pipeline import from_raw

    gold = gold_dev()
    entities = snapshot_entities(gold)
    engine = pipeline(gold)
    assert engine.config.workspace == WORKSPACE
    assert getattr(engine, "driver", None) is None, "writer debe ir en dry-run"

    directory = tmp_path_factory.mktemp("corte2") / "proposals"
    result = engine.run(
        [from_raw(source) for source in gold.sources],
        catalog_entities=entities,
        review_proposals_dir=directory,
    )
    documents = load_proposals(directory)
    assert documents, "el pipeline real no exportó ninguna propuesta"
    return result, directory, documents


@pytest.fixture
def workdir(tmp_path, engine_result):
    """Copia del directorio de propuestas real + almacén de decisiones vacío."""
    _result, directory, _documents = engine_result
    target = tmp_path / "proposals"
    target.mkdir()
    for package in sorted(directory.glob("*.json")):
        (target / package.name).write_bytes(package.read_bytes())
    return target, tmp_path / "decisions.jsonl"


@pytest.fixture
def service(workdir) -> ReviewService:
    proposals_dir, decisions_path = workdir
    return ReviewService(proposals_dir, decisions_path)


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


def _make_user(db_path: Path, username: str, role: str):
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    with auth_db.get_conn(db_path) as conn:
        return auth_db.create_user(
            conn, username=username, display_name=username.title(),
            password_hash=hash_password(PASSWORD), role=role,
        )


def _session_cookie(db_path: Path, user) -> str:
    from app.auth import db as auth_db
    from app.auth.sessions import create_session
    with auth_db.get_conn(db_path) as conn:
        token, _ = create_session(conn, user)
    return token


@pytest.fixture
def client_factory(auth_env, service, monkeypatch):
    monkeypatch.setattr(router_module, "_service", lambda: service)
    from fastapi.testclient import TestClient
    from app.main import app

    def build(role: str = "reviewer"):
        client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
        user = _make_user(auth_env, f"u-{role}-{uuid.uuid4().hex[:8]}", role)
        client.cookies.set("s9k_session", _session_cookie(auth_env, user))
        return client

    return build


# ---------------------------------------------------------------------------
# Utilidades del recorrido
# ---------------------------------------------------------------------------

def _open_queue(client):
    page = client.get(f"/v3/review?workspace={WORKSPACE}")
    assert page.status_code == 200, page.status_code
    return page.text


def _first_pending(service):
    view = service.queue(WORKSPACE)
    assert view.items, "la cola debería tener propuestas pendientes"
    return view.items[0]


def _decide(client, service, *, proposal_id, hash_, human_decision):
    """Pulsa el botón de verdad: POST real con CSRF real."""
    html = _open_queue(client)
    token = _CSRF.search(html).group(1)
    return client.post("/v3/review/decide", data={
        "workspace": WORKSPACE,
        "proposal_id": proposal_id,
        "human_decision": human_decision,
        "request_id": str(uuid.uuid4()),
        "expected_proposal_hash": hash_,
        "csrf_token": token,
    })


def _engine_rerun(engine_result, tmp_path, db_path, name="rerun"):
    """REINICIO del motor: export nuevo que lee la autoridad persistida."""
    result, _directory, _documents = engine_result
    out = tmp_path / name
    out.mkdir(parents=True, exist_ok=True)
    package = export_review_package(
        result, out, workspace=WORKSPACE, decisions_db=db_path
    )
    # `export_review_package` devuelve desde el Corte 4 un `ReviewPackageExport`
    # (ruta + propuestas + corrida), no la ruta pelada: el resumen de la ingesta
    # necesita saber CUÁNTAS propuestas dejó la corrida sin volver a leer la
    # carpeta. Aquí sólo interesa el cuerpo del paquete.
    return json.loads(package.path.read_text(encoding="utf-8"))


def _ids(package_body):
    return {item["proposal_id"] for item in package_body["items"]}


# ---------------------------------------------------------------------------
# 1-2 · PRUEBA DE ACEPTACIÓN: approve y reject, ejecutadas
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("human_decision", ["APPROVE", "REJECT"])
def test_la_decision_de_la_ui_cambia_el_comportamiento_del_motor(
    client_factory, service, engine_result, tmp_path, human_decision
):
    """Aprobar/Rechazar en la UI -> el motor deja de proponerlo. El defecto."""
    client = client_factory("reviewer")
    item = _first_pending(service)
    proposal_id = item["proposal_id"]

    # ANTES: el motor propone esta reclamación.
    antes = _engine_rerun(engine_result, tmp_path, service.database_path, "antes")
    assert proposal_id in _ids(antes)
    assert antes["resolved"] == []

    # El operador decide, por la superficie HTTP real.
    response = _decide(
        client, service, proposal_id=proposal_id,
        hash_=item["proposal_hash"], human_decision=human_decision,
    )
    assert response.status_code == 303, response.status_code

    # REINICIO: servicio nuevo sobre el mismo almacén persistido.
    reiniciado = ReviewService(service.proposals_dir, service.decisions_path)
    activos = {
        d["proposal"]["proposal_id"]: d for d in reiniciado.store.decisions()
    }
    assert proposal_id in activos, (
        "la decisión NO llegó a la autoridad canónica tras un 303 de éxito: "
        "el visor la escribió en otro almacén"
    )
    assert activos[proposal_id]["human_decision"] == human_decision

    # DESPUÉS: el motor lee ESA decisión y la propuesta cambia de estado.
    despues = _engine_rerun(engine_result, tmp_path, service.database_path, "despues")
    assert proposal_id not in _ids(despues), (
        "el motor sigue proponiendo una reclamación ya resuelta por un humano"
    )
    resueltas = {r["proposal_id"]: r for r in despues["resolved"]}
    assert resueltas[proposal_id]["human_decision"] == human_decision
    assert resueltas[proposal_id]["decision_id"].startswith("human:")


# ---------------------------------------------------------------------------
# 3 · NO queda un segundo almacén capaz de contradecir
# ---------------------------------------------------------------------------

def test_el_motor_no_consulta_el_jsonl_de_auditoria(
    client_factory, service, engine_result, tmp_path
):
    """Borrado el JSONL, el motor sigue observando la decisión. Y al revés."""
    client = client_factory("reviewer")
    item = _first_pending(service)
    proposal_id = item["proposal_id"]
    assert _decide(
        client, service, proposal_id=proposal_id,
        hash_=item["proposal_hash"], human_decision="APPROVE",
    ).status_code == 303

    # Precondición: la decisión está en la AUTORIDAD. Sin esto, el caso se
    # pondría rojo por falta de persistencia y no por la causa que mide.
    assert proposal_id in {
        d["proposal"]["proposal_id"] for d in service.store.decisions()
    }, "precondición: la decisión debe estar en la autoridad canónica"
    # El JSONL existe (auditoría) pero NO es la autoridad: se destruye.
    assert service.decisions_path.exists()
    service.decisions_path.unlink()

    despues = _engine_rerun(engine_result, tmp_path, service.database_path, "sin-jsonl")
    assert proposal_id not in _ids(despues), (
        "el motor dependía del JSONL: eso es una segunda autoridad"
    )


def test_un_jsonl_que_contradice_a_la_autoridad_no_cambia_nada(
    client_factory, service, engine_result, tmp_path
):
    """Un JSONL falsificado no consigue resolver ni desresolver nada."""
    client = client_factory("reviewer")
    item = _first_pending(service)
    otro = service.queue(WORKSPACE).items[1]

    assert _decide(
        client, service, proposal_id=item["proposal_id"],
        hash_=item["proposal_hash"], human_decision="APPROVE",
    ).status_code == 303

    # Se falsifica el JSONL: dice lo contrario de lo que dice la autoridad.
    service.decisions_path.write_text(json.dumps({
        "decision_id": "human:falsificada",
        "workspace": WORKSPACE,
        "human_decision": "APPROVE",
        "proposal": {"proposal_id": otro["proposal_id"]},
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    assert item["proposal_id"] in {
        d["proposal"]["proposal_id"] for d in service.store.decisions()
    }, "precondición: la decisión real debe estar en la autoridad canónica"

    despues = _engine_rerun(engine_result, tmp_path, service.database_path, "falso")
    ids = _ids(despues)
    assert item["proposal_id"] not in ids, "la autoridad debe seguir mandando"
    assert otro["proposal_id"] in ids, (
        "el JSONL falsificado ha resuelto una propuesta: hay dos autoridades"
    )


def test_el_motor_no_nombra_el_jsonl_en_su_camino_de_lectura():
    """Enumeración, no prosa: el módulo lector no referencia el export."""
    import ast
    import inspect

    arbol = ast.parse(inspect.getsource(review_decisions))

    # Las cadenas de DOCUMENTACIÓN pueden (y deben) nombrar el fichero para
    # declarar la prohibición. Lo que no puede existir es una cadena que el
    # código EJECUTE, que es la que construiría una segunda lectura.
    documentacion = {
        id(nodo.value)
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Expr)
        and isinstance(nodo.value, ast.Constant)
        and isinstance(nodo.value.value, str)
    }
    ejecutadas = {
        nodo.value
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Constant)
        and isinstance(nodo.value, str)
        and id(nodo) not in documentacion
    }
    # La única aparición admisible es la constante que DECLARA la prohibición.
    usados = {
        texto for texto in ejecutadas
        if "decisions.jsonl" in texto and texto != "decisions.jsonl"
    }
    assert not usados, f"el lector construye una ruta al export de auditoría: {usados}"

    # Y la lectura va a SQLite, no a un JSONL: se comprueba por estructura.
    llamadas = {
        nodo.func.attr
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
    }
    assert "connect" in llamadas
    assert review_decisions.NON_AUTHORITATIVE_EXPORT == "decisions.jsonl"


# ---------------------------------------------------------------------------
# 4 · undo: mismo modelo de decisión, mismo lector
# ---------------------------------------------------------------------------

def test_deshacer_devuelve_la_propuesta_al_motor(
    client_factory, service, engine_result, tmp_path
):
    """`undo` es el mismo contrato de decisión: el motor vuelve a proponerla."""
    client = client_factory("reviewer")
    item = _first_pending(service)
    proposal_id = item["proposal_id"]

    assert _decide(
        client, service, proposal_id=proposal_id,
        hash_=item["proposal_hash"], human_decision="APPROVE",
    ).status_code == 303
    assert proposal_id not in _ids(
        _engine_rerun(engine_result, tmp_path, service.database_path, "u1")
    ), "el motor no observó la decisión antes de deshacerla"

    html = _open_queue(client)
    token = _CSRF.search(html).group(1)
    undo = client.post("/v3/review/undo", data={
        "workspace": WORKSPACE,
        "request_id": str(uuid.uuid4()),
        "csrf_token": token,
    })
    assert undo.status_code == 303, undo.status_code

    vuelta = _engine_rerun(engine_result, tmp_path, service.database_path, "u2")
    assert proposal_id in _ids(vuelta), (
        "tras deshacer, el motor debe volver a proponer la reclamación"
    )
    assert vuelta["resolved"] == []


# ---------------------------------------------------------------------------
# 5 · el éxito llega DESPUÉS de la persistencia, nunca antes
# ---------------------------------------------------------------------------

def test_si_la_persistencia_falla_el_operador_ve_error_no_exito(
    client_factory, service, monkeypatch
):
    """Almacén roto -> nada de 303 «guardado». El orden es la garantía."""
    client = client_factory("reviewer")
    item = _first_pending(service)

    def explota(*_a, **_k):
        raise RuntimeError("almacen caido")

    monkeypatch.setattr(
        type(service.store), "append_decision_and_outbox", explota
    )
    response = _decide(
        client, service, proposal_id=item["proposal_id"],
        hash_=item["proposal_hash"], human_decision="APPROVE",
    )
    assert response.status_code >= 400, (
        "se anunció éxito sin que la autoridad confirmara la persistencia"
    )
    assert response.status_code != 303
    # Y no ha quedado rastro de decisión en la autoridad.
    assert service.store.decisions() == []


def test_sin_decision_persistida_el_motor_no_cambia(
    service, engine_result, tmp_path
):
    """Control: sin decisiones, el motor propone exactamente lo de siempre."""
    paquete = _engine_rerun(engine_result, tmp_path, service.database_path, "vacio")
    assert paquete["resolved"] == []
    assert _ids(paquete) == {
        item["proposal_id"] for item in service.queue(WORKSPACE).items
    }


# ---------------------------------------------------------------------------
# 6 · el lector falla CERRADO
# ---------------------------------------------------------------------------

def test_almacen_ilegible_no_se_confunde_con_almacen_vacio(tmp_path):
    """Un SQLite corrupto es un fallo, no «nadie ha decidido nada»."""
    roto = tmp_path / "review.sqlite3"
    roto.write_bytes(b"esto no es una base de datos")
    with pytest.raises(review_decisions.ReviewDecisionsError):
        review_decisions.read_active_decisions(roto, workspace=WORKSPACE)


def test_sin_almacen_el_motor_se_comporta_como_siempre(tmp_path):
    """Sin visor montado no hay decisiones: vacío, sin reventar."""
    assert review_decisions.read_active_decisions(
        tmp_path / "no-existe.sqlite3", workspace=WORKSPACE
    ) == {}


def test_el_ambito_de_workspace_se_respeta(
    client_factory, service, engine_result, tmp_path
):
    """Una decisión de otro workspace no resuelve nada en este."""
    client = client_factory("reviewer")
    item = _first_pending(service)
    assert _decide(
        client, service, proposal_id=item["proposal_id"],
        hash_=item["proposal_hash"], human_decision="APPROVE",
    ).status_code == 303

    ajenas = review_decisions.read_active_decisions(
        service.database_path, workspace="workspace-ajeno"
    )
    assert ajenas == {}
    propias = review_decisions.read_active_decisions(
        service.database_path, workspace=WORKSPACE
    )
    assert item["proposal_id"] in propias, (
        "el motor no observa en su propio workspace una decisión persistida"
    )
