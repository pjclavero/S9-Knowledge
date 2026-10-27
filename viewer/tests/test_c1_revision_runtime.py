# -*- coding: utf-8 -*-
"""C1 (USABLE-V1) · H-04 + H-18 — testigo del lado RUNTIME (visor, motor, worker).

CONTRATO DEL OPERADOR (resumen de lo que aqui se ejerce)
--------------------------------------------------------
* DEPLOY es la autoridad que decide y prepara `review.sqlite3`. El RUNTIME
  (visor y motor) lo CONSUME y VERIFICA; con la ruta DECLARADA nunca lo crea y
  falla cerrado con la causa real: «no existe» != «no escribible» != «no es un
  fichero» != «schema invalido».
* UNA sola resolucion canonica de la ruta (`review_paths.default_review_db`)
  compartida por visor, motor y preflight.
* Sin variable declarada (desarrollo) se conserva el defecto del repo como
  TECHO DECLARADO, con su test propio.

ESTADO
------
::

    CODE         PASS      este modulo
    CALIBRATION  PASS      scripts/calibracion/mutaciones_c1_persistencia_revision.py
    RC-E2E       PENDING   sin systemd, sin VM limpia, sin usuario de servicio real

MATRIZ (identificador -> test)
------------------------------
N2   motor con ruta declarada inexistente           test_n2_*
N3   visor con ruta declarada ausente               test_n3_*
N7-10 VAR vacia / espacios / relativa / directorio  test_n7_n10_*
N13  permisos erroneos -> diagnostico de permisos   test_n13_*
N17  worker sin lectura del directorio              test_n17_*
N18  dos resoluciones divergentes: imposible        test_n18_*
P1   fresh -> ingesta lee `{}` de BD EXISTENTE -> decision -> excluida
P2   upgrade normal: visor y motor ven lo mismo, nada creado
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_ENGINE = _REPO / "data-engine" / "app"
for _p in (str(_ENGINE), str(_ENGINE / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("jsonschema")

from app.services import v3_review  # noqa: E402
from app.services.v3_review import (  # noqa: E402
    DecisionStoreUnavailable, ReviewService, ProposalStoreUnavailable,
)
from app.services.v3_review_store import SQLiteReviewStore  # noqa: E402

from knowledge_v3 import review_decisions, review_paths  # noqa: E402

# Los fixtures y utilidades del recorrido real (pipeline + UI + motor) se
# REUTILIZAN, no se copian: son los de `test_v3_decision_efectiva`.
from test_v3_decision_efectiva import (  # noqa: E402,F401
    WORKSPACE, _decide, _engine_rerun, _first_pending, _ids, auth_env,
    client_factory, engine_result, service, workdir,
)

VAR = "S9K_V3_REVIEW_DATABASE_PATH"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _declarar(monkeypatch, valor):
    monkeypatch.setenv(VAR, valor)


@pytest.fixture
def ausente(tmp_path, monkeypatch) -> Path:
    """Ruta DECLARADA, absoluta, bajo un directorio que TAMPOCO existe."""
    ruta = tmp_path / "no-existe-nunca" / "reviews-v3" / "review.sqlite3"
    _declarar(monkeypatch, str(ruta))
    assert not ruta.parent.exists(), "premisa rota: tiene que estar AUSENTE de verdad"
    return ruta


# ===========================================================================
# N2 — motor con ruta declarada inexistente
# ===========================================================================

def test_n2_motor_con_ruta_declarada_inexistente_levanta(ausente):
    with pytest.raises(review_decisions.ReviewDecisionsError) as excinfo:
        review_decisions.read_active_decisions(workspace=WORKSPACE)
    assert excinfo.value.causa == review_paths.CAUSA_NO_EXISTE
    assert not ausente.parent.exists(), "el motor jamas crea nada"


def test_n2_resolved_proposal_ids_tampoco_cae_en_vacio(ausente):
    """El camino por el que el exportador lee (`resolved_proposal_ids`)."""
    with pytest.raises(review_decisions.ReviewDecisionsError):
        review_decisions.resolved_proposal_ids(workspace=WORKSPACE)


def _job_de_ingesta(tmp_path, ruta_fuente=True):
    from jobs import job_store  # noqa: PLC0415

    fuente = tmp_path / "fuente.md"
    perfil = tmp_path / "perfil.json"
    fuente.write_text("texto\n", encoding="utf-8")
    perfil.write_text("{}", encoding="utf-8")
    db = str(tmp_path / "jobs.db")
    job_store.init_db(db)
    job_id = job_store.create_job(
        workspace=WORKSPACE, db_path=db, job_type="ingest_v3",
        payload={"source_path": str(fuente), "profile_path": str(perfil),
                 "workspace": WORKSPACE},
    )
    return db, job_id


def test_n2_la_ingesta_termina_failed_sin_publicar_paquete(ausente, tmp_path, monkeypatch):
    """Por el WORKER real (`process_one`): FAILED con codigo y 0 paquetes."""
    from jobs import job_store, worker  # noqa: PLC0415

    propuestas = tmp_path / "propuestas"
    propuestas.mkdir()
    monkeypatch.setenv("S9K_V3_REVIEW_PROPOSALS_DIR", str(propuestas))
    db, job_id = _job_de_ingesta(tmp_path)
    assert worker.process_one("w-c1", ["ingest_v3"], None, db) is True
    job = job_store.get_job(job_id, db_path=db)
    assert job["status"] == "failed", job
    assert job["error_message"].startswith("REVIEW_STORE_UNAVAILABLE:"), (
        "N2 INGESTA NO FALLO POR EL ALMACEN: " + job["error_message"])
    assert str(ausente) not in job["error_message"], "repo publico: sin rutas"
    assert list(propuestas.iterdir()) == [], "0 paquetes publicados"
    # PERMANENTE: una ruta mal declarada no se arregla reintentando.
    assert job["attempts"] == 1 and job["next_retry_at"] is None, job


# ===========================================================================
# N3 — visor con ruta declarada ausente: no disponible, NADA creado en disco
# ===========================================================================

def test_n3_servicio_con_ruta_declarada_ausente_no_crea_nada(ausente):
    servicio = ReviewService()
    with pytest.raises(DecisionStoreUnavailable) as excinfo:
        servicio.store  # noqa: B018
    assert excinfo.value.code == v3_review.DECISIONS_STORE_MISSING
    assert isinstance(excinfo.value, ProposalStoreUnavailable)
    assert not ausente.parent.exists(), "el visor NO crea ni el directorio"
    # No se cachea el fallo: reintentar vuelve a preguntar.
    with pytest.raises(DecisionStoreUnavailable):
        servicio.store  # noqa: B018
    assert not ausente.parent.exists()


def test_n3_el_store_sin_crear_no_hace_mkdir_ni_fichero(ausente):
    """El freno esta TAMBIEN en el almacen, no solo en la guarda del servicio."""
    try:
        SQLiteReviewStore(ausente, crear=False)
    except Exception:  # noqa: BLE001 - lo que importa es el EFECTO en disco
        pass
    assert not ausente.parent.exists(), "N3 STORE: crear=False no puede hacer mkdir"
    # y con el directorio presente tampoco crea el fichero
    ausente.parent.mkdir(parents=True)
    try:
        SQLiteReviewStore(ausente, crear=False)
    except Exception:  # noqa: BLE001
        pass
    assert not ausente.exists(), "N3 STORE: crear=False no puede crear la base"
    with pytest.raises(Exception):
        SQLiteReviewStore(ausente, crear=False)


def test_n3_las_dos_superficies_http_lo_declaran_y_no_lo_pintan_vacio(
    ausente, workdir, auth_env, client_factory, monkeypatch
):
    """`/v3/review` y `/panel/review`: «el dato no esta», nunca cola vacia ni 500."""
    proposals_dir, _ = workdir
    monkeypatch.setenv("S9K_V3_REVIEW_PROPOSALS_DIR", str(proposals_dir))
    monkeypatch.setenv("S9K_PANEL_C_ENABLED", "true")
    # `client_factory` fija un servicio por monkeypatch; aqui se quiere el REAL
    # del entorno (ruta declarada ausente).
    from app.routers import chassis_review, v3_review as router_v3  # noqa: PLC0415
    monkeypatch.setattr(router_v3, "_service", lambda: ReviewService())
    monkeypatch.setattr(chassis_review, "_service", lambda: ReviewService())
    client = client_factory("admin")
    for ruta in (f"/v3/review?workspace={WORKSPACE}",
                 f"/panel/review?workspace={WORKSPACE}"):
        r = client.get(ruta)
        assert r.status_code in (200, 503), (ruta, r.status_code)
        assert "DECISIONS_STORE_MISSING" in r.text and "DECISIONES humanas" in r.text, (
            f"N3 HTTP NO DECLARA EL ALMACEN AUSENTE en {ruta}: {r.text[:200]}")
        assert "Sin propuestas" not in r.text and "no hay nada" not in r.text.lower()
        assert str(ausente.parent) not in r.text, "repo publico: sin rutas"
    assert not ausente.parent.exists(), "ni una peticion crea el almacen"


# ===========================================================================
# N7-N10 — variable declarada pero inservible: causa real, en runtime
# ===========================================================================

@pytest.mark.parametrize("valor, causa, codigo", [
    ("", review_paths.CAUSA_VAR_VACIA, v3_review.DECISIONS_STORE_BAD_CONFIG),            # N7
    ("   ", review_paths.CAUSA_VAR_VACIA, v3_review.DECISIONS_STORE_BAD_CONFIG),         # N8
    ("relativa/review.sqlite3", review_paths.CAUSA_VAR_RELATIVA,
     v3_review.DECISIONS_STORE_BAD_CONFIG),                                              # N9
    ("@DIR@", review_paths.CAUSA_NO_ES_FICHERO, v3_review.DECISIONS_STORE_BAD_CONFIG),   # N10
], ids=["N7-vacia", "N8-espacios", "N9-relativa", "N10-directorio"])
def test_n7_n10_variable_invalida_nombra_la_causa_real(tmp_path, monkeypatch, valor, causa, codigo):
    if valor == "@DIR@":
        valor = str(tmp_path)
    _declarar(monkeypatch, valor)
    # motor
    with pytest.raises(review_decisions.ReviewDecisionsError) as motor:
        review_decisions.read_active_decisions(workspace=WORKSPACE)
    assert motor.value.causa == causa
    # resolucion canonica
    with pytest.raises(review_paths.ReviewDbConfigError) as canon:
        review_paths.default_review_db()
    assert canon.value.causa == causa
    # visor
    with pytest.raises(DecisionStoreUnavailable) as visor:
        ReviewService().store  # noqa: B018
    esperado = (v3_review.DECISIONS_STORE_NOT_A_FILE
                if causa == review_paths.CAUSA_NO_ES_FICHERO else codigo)
    assert visor.value.code == esperado


def test_n7_n10_una_variable_invalida_no_cae_al_defecto(tmp_path, monkeypatch):
    """«Vacia» NO es «no declarada»: no se vuelve al defecto del repo."""
    _declarar(monkeypatch, "")
    with pytest.raises(review_paths.ReviewDbConfigError):
        review_paths.resolve_review_db()


# ===========================================================================
# N13 / N17 — permisos: diagnostico de permisos, no «no existe»
# ===========================================================================

def _sin_acceso(monkeypatch, ruta: Path, *, w_only: bool):
    """Simula LO QUE OBSERVA el proceso: root lo saltaria con chmod real."""
    real_access = os.access

    def access(p, modo, *a, **k):
        if Path(p) == ruta and (not w_only or modo & os.W_OK):
            return False
        return real_access(p, modo, *a, **k)

    monkeypatch.setattr(os, "access", access)


def test_n13_sin_escritura_el_visor_dice_permisos_y_no_no_existe(tmp_path, monkeypatch, almacen_fresh):
    ruta = almacen_fresh(tmp_path / "x" / "review.sqlite3")
    _declarar(monkeypatch, str(ruta))
    _sin_acceso(monkeypatch, ruta, w_only=True)
    with pytest.raises(DecisionStoreUnavailable) as excinfo:
        ReviewService().store  # noqa: B018
    assert excinfo.value.code == v3_review.DECISIONS_STORE_PERMISSIONS
    assert excinfo.value.code != v3_review.DECISIONS_STORE_MISSING


def test_n13_chmod_real_cuando_el_proceso_no_es_root(tmp_path, monkeypatch, almacen_fresh):
    ruta = almacen_fresh(tmp_path / "y" / "review.sqlite3")
    _declarar(monkeypatch, str(ruta))
    if os.geteuid() == 0:
        # root atraviesa los bits de modo: lo observable ya lo cubre el caso
        # simulado de arriba y `como=` en el testigo de deploy.
        ins = review_paths.inspect_review_db(ruta, escritura=True, como=(4242, frozenset({4242})))
        assert ins.causa == review_paths.CAUSA_SIN_PERMISOS
        return
    ruta.chmod(0o444)
    with pytest.raises(DecisionStoreUnavailable) as excinfo:
        ReviewService().store  # noqa: B018
    assert excinfo.value.code == v3_review.DECISIONS_STORE_PERMISSIONS


def test_n13_las_causas_tienen_cada_una_su_frase(tmp_path, almacen_fresh):
    textos = {review_paths.CAUSAS[c] for c in review_paths.CAUSAS}
    assert len(textos) == len(review_paths.CAUSAS), "dos causas comparten frase"
    assert len({v3_review.PROPOSALS_STORE_MESSAGES[c] for c in
                v3_review.PROPOSALS_STORE_MESSAGES if c.startswith("DECISIONS_")}) == 6


def test_n17_worker_sin_lectura_del_directorio_falla_con_causa_permisos(tmp_path, monkeypatch, almacen_fresh):
    """El worker no puede ni atravesar el directorio: FAILED, causa PERMISOS."""
    from jobs import job_store, worker  # noqa: PLC0415

    ruta = almacen_fresh(tmp_path / "estado" / "reviews-v3" / "review.sqlite3")
    _declarar(monkeypatch, str(ruta))
    propuestas = tmp_path / "propuestas"
    propuestas.mkdir()
    monkeypatch.setenv("S9K_V3_REVIEW_PROPOSALS_DIR", str(propuestas))
    db, job_id = _job_de_ingesta(tmp_path)

    real_stat = os.stat

    def stat(p, *a, **k):
        if Path(p) == ruta:
            raise PermissionError(13, "Permission denied")
        return real_stat(p, *a, **k)

    monkeypatch.setattr(os, "stat", stat)
    # (y, si no es root, el efecto REAL del directorio sin permiso de acceso)
    assert worker.process_one("w-c1-perm", ["ingest_v3"], None, db) is True
    monkeypatch.undo()
    job = job_store.get_job(job_id, db_path=db)
    assert job["status"] == "failed", job
    assert job["error_message"].startswith("REVIEW_STORE_PERMISSIONS:"), (
        "N17 INGESTA NO FALLO POR PERMISOS: " + job["error_message"])
    assert "PERMISOS" in job["error_message"]
    assert list(propuestas.iterdir()) == []
    assert job["attempts"] == 1 and job["next_retry_at"] is None


def test_n17_chmod_000_del_directorio_cuando_no_es_root(tmp_path, monkeypatch, almacen_fresh):
    ruta = almacen_fresh(tmp_path / "estado" / "review.sqlite3")
    _declarar(monkeypatch, str(ruta))
    if os.geteuid() == 0:
        return  # root ignora los bits: cubierto por el caso simulado
    ruta.parent.chmod(0o000)
    try:
        with pytest.raises(review_decisions.ReviewDecisionsError) as excinfo:
            review_decisions.read_active_decisions(workspace=WORKSPACE)
        assert excinfo.value.causa == review_paths.CAUSA_SIN_PERMISOS
    finally:
        ruta.parent.chmod(0o755)


# ===========================================================================
# N18 — dos resoluciones divergentes: imposible por construccion
# ===========================================================================

_ESCENARIOS = {
    "declarada": {VAR: "/var/lib/s9k-test/reviews-v3/review.sqlite3"},
    "declarada-y-decisions": {VAR: "/var/lib/s9k-test/a/review.sqlite3",
                              "S9K_V3_REVIEW_DECISIONS_PATH": "/var/lib/otra/decisions.jsonl"},
    "solo-decisions": {"S9K_V3_REVIEW_DECISIONS_PATH": "/var/lib/otra/decisions.jsonl"},
    "defecto-del-repo": {},
}


@pytest.mark.parametrize("nombre", sorted(_ESCENARIOS))
def test_n18_visor_motor_y_canonica_resuelven_la_misma_ruta(nombre, monkeypatch):
    monkeypatch.delenv(VAR, raising=False)
    monkeypatch.delenv("S9K_V3_REVIEW_DECISIONS_PATH", raising=False)
    for clave, valor in _ESCENARIOS[nombre].items():
        monkeypatch.setenv(clave, valor)
    canonica = review_paths.default_review_db()
    assert Path(v3_review.default_database_path()) == canonica, (
        "VISOR DIVERGE de la resolucion canonica")
    assert Path(review_decisions.default_decisions_db()) == canonica, (
        "MOTOR DIVERGE de la resolucion canonica")
    if "S9K_V3_REVIEW_DATABASE_PATH" in _ESCENARIOS[nombre]:
        assert canonica == Path(_ESCENARIOS[nombre][VAR])


def _lee_entorno(fn) -> bool:
    arbol = ast.parse(inspect.getsource(fn).lstrip())
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Attribute) and nodo.attr in ("environ", "getenv"):
            return True
    return False


def test_n18_ni_el_visor_ni_el_motor_vuelven_a_leer_el_entorno_ni_derivar():
    assert not _lee_entorno(v3_review.default_database_path), (
        "el visor VUELVE a derivar su ruta: segunda verdad")
    assert not _lee_entorno(review_decisions.default_decisions_db), (
        "el motor VUELVE a derivar su ruta: segunda verdad")


def test_n18_la_variable_solo_se_lee_en_review_paths():
    """Censo POR AST del producto: nadie mas lee `S9K_V3_REVIEW_DATABASE_PATH`."""
    lectores = []
    for raiz in (_REPO / "viewer" / "app", _REPO / "data-engine" / "app"):
        for fichero in raiz.rglob("*.py"):
            if "tests" in fichero.parts or "__pycache__" in fichero.parts:
                continue
            texto = fichero.read_text(encoding="utf-8")
            if VAR not in texto:
                continue
            for nodo in ast.walk(ast.parse(texto)):
                if isinstance(nodo, ast.Constant) and nodo.value == VAR:
                    lectores.append(fichero.relative_to(_REPO).as_posix())
                    break
    assert lectores == ["data-engine/app/knowledge_v3/review_paths.py"], lectores


def test_n18_el_servicio_no_deriva_la_base_de_decisions_path(tmp_path, monkeypatch):
    """D4 retirado: `decisions_path.with_suffix(".sqlite3")` ya no decide nada."""
    destino = tmp_path / "otro" / "base.sqlite3"
    servicio = ReviewService(tmp_path / "p", tmp_path / "d" / "decisions.jsonl")
    assert servicio.database_path == review_paths.default_review_db()
    explicito = ReviewService(tmp_path / "p", tmp_path / "d" / "decisions.jsonl",
                              database_path=destino)
    assert explicito.database_path == destino
    arbol = ast.parse(inspect.getsource(ReviewService.__init__).lstrip())
    derivaciones = {n.attr for n in ast.walk(arbol) if isinstance(n, ast.Attribute)
                    and n.attr in ("with_suffix", "with_name")}
    assert not derivaciones, "ReviewService vuelve a DERIVAR la base: %s" % derivaciones


# ===========================================================================
# TECHO DECLARADO — sin variable declarada (desarrollo)
# ===========================================================================

def test_techo_sin_variable_el_visor_conserva_el_defecto_y_lo_crea(tmp_path, monkeypatch):
    monkeypatch.delenv(VAR, raising=False)
    monkeypatch.setenv("S9K_V3_REVIEW_DECISIONS_PATH", str(tmp_path / "dev" / "decisions.jsonl"))
    servicio = ReviewService()
    assert servicio.store.path == tmp_path / "dev" / "review.sqlite3"
    assert (tmp_path / "dev" / "review.sqlite3").is_file(), (
        "TECHO DECLARADO: sin variable declarada (desarrollo) el visor puede crear")


def test_techo_sin_variable_y_sin_fichero_el_motor_lee_vacio(tmp_path, monkeypatch):
    monkeypatch.delenv(VAR, raising=False)
    monkeypatch.setenv("S9K_V3_REVIEW_DECISIONS_PATH", str(tmp_path / "dev2" / "decisions.jsonl"))
    assert review_decisions.read_active_decisions(workspace=WORKSPACE) == {}
    assert not (tmp_path / "dev2").exists()


def test_techo_un_defecto_existente_pero_invalido_tambien_levanta(tmp_path, monkeypatch):
    """El techo es sobre la AUSENCIA, no sobre la corrupcion."""
    monkeypatch.delenv(VAR, raising=False)
    monkeypatch.setenv("S9K_V3_REVIEW_DECISIONS_PATH", str(tmp_path / "decisions.jsonl"))
    (tmp_path / "review.sqlite3").write_bytes(b"basura" * 40)
    with pytest.raises(review_decisions.ReviewDecisionsError) as excinfo:
        review_decisions.read_active_decisions(workspace=WORKSPACE)
    assert excinfo.value.causa == review_paths.CAUSA_CORRUPTA


# ===========================================================================
# N4 (lado runtime) — un SQLite ajeno no se adopta
# ===========================================================================

def test_n4_un_sqlite_ajeno_sin_human_decisions_no_se_adopta(tmp_path, monkeypatch):
    import sqlite3

    ajeno = tmp_path / "ajeno.sqlite3"
    con = sqlite3.connect(ajeno)
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    con.commit()
    con.close()
    antes = _sha(ajeno)
    _declarar(monkeypatch, str(ajeno))
    with pytest.raises(DecisionStoreUnavailable) as visor:
        ReviewService().store  # noqa: B018
    assert visor.value.code == v3_review.DECISIONS_STORE_FOREIGN
    with pytest.raises(review_decisions.ReviewDecisionsError) as motor:
        review_decisions.read_active_decisions(workspace=WORKSPACE)
    assert motor.value.causa == review_paths.CAUSA_SCHEMA_INVALIDO
    assert _sha(ajeno) == antes, "el runtime no toca (no adopta ni 'repara') un SQLite ajeno"
    con = sqlite3.connect(ajeno)
    tablas = {f[0] for f in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert tablas == {"users"}


def test_n11_base_corrupta_no_se_sobrescribe_en_runtime(tmp_path, monkeypatch):
    ruta = tmp_path / "c.sqlite3"
    ruta.write_bytes(b"esto no es sqlite " * 20)
    antes = _sha(ruta)
    _declarar(monkeypatch, str(ruta))
    with pytest.raises(DecisionStoreUnavailable) as visor:
        ReviewService().store  # noqa: B018
    assert visor.value.code == v3_review.DECISIONS_STORE_CORRUPT
    assert _sha(ruta) == antes


# ===========================================================================
# P1 — fresh -> ingesta lee {} de la BD EXISTENTE -> decision -> excluida
# ===========================================================================

def test_p1_fresh_decision_en_panel_excluida_en_la_siguiente_ingesta(
    service, auth_env, client_factory, engine_result, tmp_path
):
    # FRESH: el almacen lo creo el DESPLIEGUE (fixture autouse de la raiz, que
    # usa la misma herramienta que deploy.sh) ANTES de que nadie lo abra.
    ruta = Path(os.environ[VAR])
    assert ruta.is_file() and review_paths.inspect_review_db(ruta).valido
    assert service.database_path == ruta                          # ruta DECLARADA
    assert service.store.decisions() == []

    # 1.a ingesta: el motor LEE `{}` de una BD EXISTENTE (no de una ausencia).
    assert review_decisions.read_active_decisions(workspace=WORKSPACE) == {}
    primera = _engine_rerun(engine_result, tmp_path, None, "primera")
    item = _first_pending(service)
    assert item["proposal_id"] in _ids(primera)

    # La decision se toma en la UI REAL.
    cliente = client_factory("reviewer")
    assert _decide(cliente, service, proposal_id=item["proposal_id"],
                   hash_=item["proposal_hash"], human_decision="APPROVE").status_code == 303

    # 2.a ingesta: el motor, SIN que nadie le pase la ruta, la excluye.
    segunda = _engine_rerun(engine_result, tmp_path, None, "segunda")
    assert item["proposal_id"] not in _ids(segunda)
    assert {r["proposal_id"] for r in segunda["resolved"]} == {item["proposal_id"]}


# ===========================================================================
# P2 — upgrade normal: visor y motor ven lo mismo, ningun fichero creado
# ===========================================================================

def test_p2_upgrade_normal_misma_ruta_con_decisiones_nada_se_crea(
    workdir, auth_env, client_factory, engine_result, tmp_path, monkeypatch
):
    proposals_dir, decisions_path = workdir
    ruta = Path(os.environ[VAR])                      # el que dejo la fixture "fresh"
    servicio = ReviewService(proposals_dir, decisions_path)
    item = _first_pending(servicio)
    assert _decide(client_factory("reviewer"), servicio, proposal_id=item["proposal_id"],
                   hash_=item["proposal_hash"], human_decision="REJECT").status_code == 303

    # --- "UPGRADE": otra release (otro objeto de servicio, otro proceso logico),
    # MISMA ruta declarada. Solo se LEE y se VERIFICA.
    antes_ficheros = sorted(p.name for p in ruta.parent.iterdir()
                            if not p.name.endswith(("-wal", "-shm")))
    antes_hash = _sha(ruta)
    import sqlite3
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    antes_tablas = sorted(f[0] for f in con.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','index') ORDER BY name"))
    con.close()

    release_b = ReviewService(proposals_dir, decisions_path)
    vistas_visor = {d["proposal"]["proposal_id"]: d["human_decision"]
                    for d in release_b.store.decisions()}
    vistas_motor = review_decisions.read_active_decisions(workspace=WORKSPACE)

    assert vistas_visor == {item["proposal_id"]: "REJECT"}
    assert {k: v.human_decision for k, v in vistas_motor.items()} == vistas_visor, (
        "visor y motor ven cosas distintas del mismo almacen")

    despues_ficheros = sorted(p.name for p in ruta.parent.iterdir()
                              if not p.name.endswith(("-wal", "-shm")))
    assert despues_ficheros == antes_ficheros, "el upgrade no crea ni mueve ficheros"
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    despues_tablas = sorted(f[0] for f in con.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','index') ORDER BY name"))
    con.close()
    assert despues_tablas == antes_tablas, "el upgrade no cambia tablas"
    assert _sha(ruta) == antes_hash, "el upgrade no reescribe la base"
