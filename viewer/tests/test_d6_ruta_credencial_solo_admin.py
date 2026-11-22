"""D6: la ruta del fichero de credencial sólo la ven administradores.

Contexto: desde #291 un fallo de credencial del grafo guarda en el job
`error_code=GRAPH_CREDENTIAL_UNUSABLE` y un `error_message` con la ruta del
fichero y el motivo. Decisión del operador (D6): la ruta completa sólo es
visible para administración; el resto recibe código estable + explicación +
a quién avisar. El detalle se conserva en el almacén de jobs y en el log.

Sujeto: los caminos REALES del visor (HTML `/jobs`, `/jobs/{id}`, `/status`;
API `/api/jobs`, `/api/jobs/{id}`, `/api/jobs/counts`, `/api/status`,
`/api/admin/health`) con usuarios autenticados de verdad por rol
(`cliente_lector`), sobre una cola SQLite escrita por el `job_store` real.
"""
from __future__ import annotations

import logging
import re

import pytest

from app import jobs_client

CODIGO = "GRAPH_CREDENTIAL_UNUSABLE"
#: Ruta y fichero inventados, sin relación con ninguna máquina real.
DIRECTORIO = "/srv/secretos-d6"
FICHERO = "neo4j-clave-d6.pass"
RUTA = f"{DIRECTORIO}/{FICHERO}"
MENSAJE = (
    f"{CODIGO}: La conexion al grafo esta declarada, pero el fichero con su "
    f"credencial no se puede usar. Causa: el fichero {RUTA} tiene un modo "
    "no permitido por la politica."
)
FRAGMENTOS_DE_LA_RUTA = (RUTA, DIRECTORIO, "secretos-d6", FICHERO, "neo4j-clave")
ROLES = ("viewer", "reviewer", "admin")


def _cola(tmp_path, monkeypatch, *, mensaje=MENSAJE, codigo=CODIGO):
    store = jobs_client._load_job_store()
    assert store is not None, "el visor no encuentra data-engine/app/jobs"
    db = str(tmp_path / "jobs.db")
    store.init_db(db)
    job_id = store.create_job("leyenda", job_type="ingest_v3", db_path=db)
    store.claim_next_job("w1", db_path=db)
    store.mark_failed(job_id, mensaje, retry=False, db_path=db, error_code=codigo)
    monkeypatch.setenv("S9K_JOBS_DB", db)
    return store, db, job_id


def _respuestas(cliente, job_id) -> dict[str, str]:
    """Todo lo que un usuario recibe de la cola, camino por camino."""
    respuestas = {
        "html_lista": cliente.get("/jobs"),
        "html_detalle": cliente.get(f"/jobs/{job_id}"),
        "api_lista": cliente.get("/api/jobs", params={"workspace": "leyenda"}),
        "api_detalle": cliente.get(f"/api/jobs/{job_id}"),
        "api_conteos": cliente.get("/api/jobs/counts", params={"workspace": "leyenda"}),
    }
    # Un 500 no contiene la ruta y haría pasar en falso toda la batería.
    for camino, r in respuestas.items():
        assert r.status_code == 200, (
            f"D6: el camino {camino} no responde 200 ({r.status_code}): la "
            "comprobación de ausencia de la ruta no mediría nada"
        )
    return {camino: r.text for camino, r in respuestas.items()}


def _contiene_ruta(texto: str) -> list[str]:
    return [f for f in FRAGMENTOS_DE_LA_RUTA if f in texto]


# --------------------------------------------------------------------------
# Por rol
# --------------------------------------------------------------------------
@pytest.mark.parametrize("rol", ["viewer", "reviewer"])
def test_un_no_admin_no_ve_la_ruta_ni_fragmentos_en_ningun_camino(
    rol, tmp_path, monkeypatch, cliente_lector
):
    from app.main import app

    _, _, job_id = _cola(tmp_path, monkeypatch)
    cliente = cliente_lector(app, role=rol, username=f"u_{rol}")
    for camino, texto in _respuestas(cliente, job_id).items():
        fugas = _contiene_ruta(texto)
        assert not fugas, (
            f"D6: el rol {rol} recibe la ruta de la credencial por {camino}: {fugas}"
        )


@pytest.mark.parametrize("rol", ["viewer", "reviewer"])
def test_un_no_admin_recibe_codigo_explicacion_y_a_quien_avisar(
    rol, tmp_path, monkeypatch, cliente_lector
):
    from app.main import app

    _, _, job_id = _cola(tmp_path, monkeypatch)
    cliente = cliente_lector(app, role=rol, username=f"u_{rol}")
    pagina = cliente.get(f"/jobs/{job_id}")
    assert pagina.status_code == 200, f"D6: el detalle da {pagina.status_code} al rol {rol}"
    detalle = pagina.text
    assert CODIGO in detalle, f"D6: el rol {rol} no recibe el código estable"
    assert "Avisa a quien administra el servicio" in detalle, (
        f"D6: el rol {rol} no sabe a quién acudir"
    )
    publico = cliente.get(f"/api/jobs/{job_id}").json()["job"]
    assert publico["error_public"]["code"] == CODIGO, "D6: la API no da el código estable"
    assert "administra" in publico["error_public"]["message"], (
        "D6: la API no da una explicación con a quién avisar"
    )
    assert "error_message" not in publico, "D6: la API entrega el texto técnico a un no-admin"


def test_el_admin_si_ve_la_ruta_en_html_y_en_json(tmp_path, monkeypatch, cliente_lector):
    from app.main import app

    _, _, job_id = _cola(tmp_path, monkeypatch)
    cliente = cliente_lector(app, role="admin", username="operador_x")
    respuestas = _respuestas(cliente, job_id)
    assert RUTA in respuestas["html_detalle"], "D6: el admin no ve la ruta en el HTML del detalle"
    assert RUTA in respuestas["api_detalle"].replace("\\/", "/"), (
        "D6: el admin no ve la ruta en el JSON del detalle"
    )
    # Y además recibe la explicación pública, igual que los demás.
    assert "Avisa a quien administra el servicio" in respuestas["html_detalle"], (
        "D6: al admin se le ha quitado la explicación pública"
    )


def test_la_decision_es_por_rol_no_por_nombre_de_usuario(tmp_path, monkeypatch, cliente_lector):
    from app.main import app

    _, _, job_id = _cola(tmp_path, monkeypatch)
    falso_admin = cliente_lector(app, role="reviewer", username="admin")
    for camino, texto in _respuestas(falso_admin, job_id).items():
        assert not _contiene_ruta(texto), (
            f"D6: un revisor llamado «admin» recibe la ruta por {camino}"
        )


def test_un_admin_con_otro_nombre_sigue_viendo_la_ruta(tmp_path, monkeypatch, cliente_lector):
    from app.main import app

    _, _, job_id = _cola(tmp_path, monkeypatch)
    admin = cliente_lector(app, role="admin", username="persona_cualquiera")
    assert RUTA in admin.get(f"/jobs/{job_id}").text, (
        "D6: un admin con otro nombre de usuario no ve la ruta"
    )


# --------------------------------------------------------------------------
# H8: autenticación apagada, rol desconocido, conteos
# --------------------------------------------------------------------------
def test_con_la_autenticacion_apagada_nadie_recibe_la_ruta(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    _, _, job_id = _cola(tmp_path, monkeypatch)
    monkeypatch.setenv("S9K_AUTH_ENABLED", "false")
    anonimo = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    for url in ("/jobs", f"/jobs/{job_id}", "/api/jobs", f"/api/jobs/{job_id}",
                "/api/jobs/counts"):
        r = anonimo.get(url)
        assert not _contiene_ruta(r.text), (
            f"D6: un anónimo (auth apagada) recibe la ruta por {url}"
        )


def test_un_rol_desconocido_se_trata_como_no_admin():
    from app.authz.context import build_viewer_context
    from app.authz.scope import VisibilityScope

    ctx = build_viewer_context(role="rol_inventado", auth_enabled=True,
                               default_workspace="leyenda")
    scope = VisibilityScope(ctx)
    assert scope.sees_operational_detail is False, "un rol desconocido ve el detalle operativo"
    job = {"job_id": "j", "status": "failed", "error_code": CODIGO, "error_message": MENSAJE}
    recortado = jobs_client.redact_job(job, scope)
    assert "error_message" not in recortado, "un rol desconocido recibe el texto técnico"
    assert not _contiene_ruta(str(recortado)), "un rol desconocido recibe la ruta"


@pytest.mark.parametrize("rol", ROLES)
def test_los_conteos_no_llevan_ni_ruta_ni_texto_de_error(
    rol, tmp_path, monkeypatch, cliente_lector
):
    from app.main import app

    _, _, _ = _cola(tmp_path, monkeypatch)
    cliente = cliente_lector(app, role=rol, username=f"u_{rol}")
    r = cliente.get("/api/jobs/counts", params={"workspace": "leyenda"})
    assert r.status_code == 200, f"D6: /api/jobs/counts da {r.status_code} al rol {rol}"
    assert not _contiene_ruta(r.text), f"D6: los conteos llevan la ruta al rol {rol}"
    assert r.json()["counts"] == {"failed": 1}, "los conteos no son los de la cola"


# --------------------------------------------------------------------------
# H5: por defecto, redactado
# --------------------------------------------------------------------------
def test_sin_ambito_no_se_entrega_nada(tmp_path, monkeypatch):
    _, _, job_id = _cola(tmp_path, monkeypatch)
    assert jobs_client.scoped_job(None, job_id) is None, "scoped_job(None) entrega el job"
    assert jobs_client.scoped_jobs(None) == [], "scoped_jobs(None) entrega la cola"
    assert jobs_client.scoped_counts(None) == {}, "scoped_counts(None) cuenta la cola"
    job = {"job_id": "j", "status": "failed", "error_code": CODIGO, "error_message": MENSAJE}
    recortado = jobs_client.redact_job(job, None)
    assert "error_message" not in recortado, "redact_job(None) entrega el texto técnico"
    assert not _contiene_ruta(str(recortado)), "redact_job(None) entrega la ruta"


def test_el_ambito_sin_restricciones_explicito_si_ve_el_detalle(tmp_path, monkeypatch):
    from app.authz.scope import UNRESTRICTED

    _, _, job_id = _cola(tmp_path, monkeypatch)
    job = jobs_client.scoped_job(UNRESTRICTED, job_id)
    assert job is not None and RUTA in job["error_message"], (
        "el llamador interno explícito (UNRESTRICTED) debe seguir viendo todo"
    )


def test_un_codigo_nuevo_con_ruta_no_se_cuela_por_defecto(
    tmp_path, monkeypatch, cliente_lector
):
    from app.main import app

    ruta_nueva = "/srv/otro-sitio-d6/clave-nueva.pass"
    _, _, job_id = _cola(
        tmp_path, monkeypatch,
        mensaje=f"CODIGO_NUEVO_D6: causa nueva en {ruta_nueva}",
        codigo="CODIGO_NUEVO_D6",
    )
    cliente = cliente_lector(app, role="reviewer", username="revisora")
    for camino, texto in _respuestas(cliente, job_id).items():
        assert "otro-sitio-d6" not in texto and "clave-nueva" not in texto, (
            f"D6: un código nuevo con ruta se cuela por {camino}"
        )
    detalle = cliente.get(f"/api/jobs/{job_id}").json()["job"]
    assert detalle["error_public"]["code"] == "CODIGO_NUEVO_D6", "el código estable debía verse"
    assert "administra" in detalle["error_public"]["message"], (
        "un código sin frase propia debe recibir la explicación genérica"
    )


def test_un_error_code_con_forma_de_ruta_se_sustituye_por_el_generico(
    tmp_path, monkeypatch, cliente_lector
):
    from app.main import app

    _, _, job_id = _cola(
        tmp_path, monkeypatch,
        mensaje="fallo en /srv/raro-d6/fichero.pass", codigo="/srv/raro-d6/fichero.pass",
    )
    cliente = cliente_lector(app, role="reviewer", username="revisora")
    for camino, texto in _respuestas(cliente, job_id).items():
        assert "raro-d6" not in texto, f"D6: un error_code con ruta sale por {camino}"
    job = cliente.get(f"/api/jobs/{job_id}").json()["job"]
    assert job["error_code"] == jobs_client.CODIGO_GENERICO, (
        "un error_code que no es un código estable debe sustituirse por JOB_FAILED"
    )


def test_el_codigo_extraido_de_texto_libre_exige_pertenencia_al_catalogo(
    tmp_path, monkeypatch, cliente_lector
):
    """H6: un prefijo con forma de código pero DESCONOCIDO no se publica."""
    from app.main import app

    _, _, job_id = _cola(
        tmp_path, monkeypatch,
        mensaje="PREFIJO_LIBRE_D6: causa en /srv/prefijo-d6/f.pass", codigo=None,
    )
    cliente = cliente_lector(app, role="reviewer", username="revisora")
    texto = cliente.get(f"/api/jobs/{job_id}").text
    assert "PREFIJO_LIBRE_D6" not in texto and "prefijo-d6" not in texto, (
        "D6: el prefijo de un mensaje libre se publica como código sin estar en el catálogo"
    )
    assert cliente.get(f"/api/jobs/{job_id}").json()["job"]["error_public"]["code"] == (
        jobs_client.CODIGO_GENERICO
    ), "sin código conocido debe publicarse JOB_FAILED"


def test_un_error_code_con_salto_de_linea_no_pasa_el_fullmatch():
    job = {"job_id": "j", "status": "failed", "error_code": "ABC\n/srv/x",
           "error_message": "x"}
    recortado = jobs_client.redact_job(job, None)
    assert recortado["error_code"] == jobs_client.CODIGO_GENERICO, (
        "un error_code con salto de línea se coló por la forma de código"
    )


# --------------------------------------------------------------------------
# H4: la frase y el código públicos dependen del ESTADO
# --------------------------------------------------------------------------
def _job_en_estado(tmp_path, monkeypatch, estado):
    store = jobs_client._load_job_store()
    db = str(tmp_path / "estados.db")
    store.init_db(db)
    job_id = store.create_job("leyenda", job_type="ingest_v3", db_path=db)
    monkeypatch.setenv("S9K_JOBS_DB", db)
    store.claim_next_job("w1", db_path=db)
    if estado == "reintento":
        store.mark_failed(job_id, MENSAJE, retry=True, db_path=db, error_code=CODIGO)
    elif estado == "stale":
        store.release_stale_jobs(-5, db_path=db)
    elif estado == "skipped":
        store.mark_skipped(job_id, f"sin handler en {RUTA}", db_path=db)
    elif estado == "cancelled":
        store.mark_failed(job_id, MENSAJE, retry=False, db_path=db, error_code=CODIGO)
        store.mark_cancelled(job_id, db_path=db)
    elif estado == "failed":
        store.mark_failed(job_id, MENSAJE, retry=False, db_path=db, error_code=CODIGO)
    return store, db, job_id


@pytest.mark.parametrize("estado,estado_esperado,codigo_esperado", [
    ("reintento", "pending", jobs_client.CODIGO_REINTENTO),
    ("stale", "pending", jobs_client.CODIGO_REINTENTO),
    ("skipped", "skipped", jobs_client.CODIGO_OMITIDO),
    ("cancelled", "cancelled", jobs_client.CODIGO_CANCELADO),
    ("failed", "failed", CODIGO),
])
def test_la_frase_publica_depende_del_estado(
    estado, estado_esperado, codigo_esperado, tmp_path, monkeypatch, cliente_lector
):
    from app.main import app

    _, _, job_id = _job_en_estado(tmp_path, monkeypatch, estado)
    cliente = cliente_lector(app, role="reviewer", username="revisora")
    job = cliente.get(f"/api/jobs/{job_id}").json()["job"]
    assert job["status"] == estado_esperado, f"el escenario {estado} no llegó a {estado_esperado}"
    publico = job["error_public"]
    assert publico["code"] == codigo_esperado, (
        f"estado {estado_esperado}: el código público es {publico['code']}"
    )
    if estado_esperado != "failed":
        assert "ha fallado" not in publico["message"].lower(), (
            f"D6: la pantalla dice «ha fallado» de un job en estado {estado_esperado}"
        )
        assert publico["code"] != jobs_client.CODIGO_GENERICO, (
            f"D6: JOB_FAILED junto a un job en estado {estado_esperado}"
        )
    assert not _contiene_ruta(cliente.get(f"/api/jobs/{job_id}").text), (
        f"D6: la ruta se cuela en el estado {estado}"
    )


def test_un_job_completado_no_muestra_error_publico():
    job = {"job_id": "j", "status": "complete", "error_code": None, "error_message": None}
    assert "error_public" not in jobs_client.redact_job(job, None), (
        "un job completado no puede llevar un error público"
    )


# --------------------------------------------------------------------------
# H10: /jobs no pinta la ruta de la base a quien no es admin
# --------------------------------------------------------------------------
@pytest.mark.parametrize("rol", ROLES)
def test_la_ruta_de_la_base_de_trabajos_sale_solo_al_admin(
    rol, tmp_path, monkeypatch, cliente_lector
):
    from app.main import app

    ausente = tmp_path / "sin-base-d6" / "jobs.db"
    monkeypatch.setenv("S9K_JOBS_DB", str(ausente))
    cliente = cliente_lector(app, role=rol, username=f"u_{rol}")
    r = cliente.get("/jobs")
    assert r.status_code == 200, f"/jobs da {r.status_code} al rol {rol}"
    assert "jobs_db_not_found" in r.text, "la pantalla no dice la causa"
    if rol == "admin":
        assert "sin-base-d6" in r.text, "el admin no ve la ruta de la base de trabajos"
    else:
        assert "sin-base-d6" not in r.text and str(tmp_path) not in r.text, (
            f"D6: el rol {rol} recibe la ruta de la base de trabajos"
        )


# --------------------------------------------------------------------------
# H11: /status y /api/status no entregan str(exc) del proveedor
# --------------------------------------------------------------------------
class _ProveedorRoto:
    name = "neo4j"

    def is_connected(self):
        raise RuntimeError("no se pudo abrir bolt://grafo-interno-d6:7687")


@pytest.mark.parametrize("rol", ROLES)
def test_el_fallo_del_proveedor_solo_llega_con_detalle_al_admin(
    rol, monkeypatch, cliente_lector
):
    from app.authz.dependencies import get_filtered_provider
    from app.main import app

    app.dependency_overrides[get_filtered_provider] = lambda: _ProveedorRoto()
    try:
        cliente = cliente_lector(app, role=rol, username=f"u_{rol}")
        api = cliente.get("/api/status")
        html = cliente.get("/status")
    finally:
        app.dependency_overrides.pop(get_filtered_provider, None)
    assert api.status_code == 200 and html.status_code == 200, (
        f"/api/status {api.status_code}, /status {html.status_code} para {rol}"
    )
    for camino, texto in (("api", api.text), ("html", html.text)):
        if rol == "admin":
            assert "grafo-interno-d6" in texto, f"el admin no ve el detalle por {camino}"
        else:
            assert "grafo-interno-d6" not in texto and "7687" not in texto, (
                f"D6: el rol {rol} recibe host/puerto del grafo por {camino}"
            )
            assert "GRAPH_PROVIDER_ERROR" in texto, (
                f"D6: el rol {rol} no recibe el código estable por {camino}"
            )


# --------------------------------------------------------------------------
# H9: /api/admin/health no se abre al anónimo con la autenticación apagada
# --------------------------------------------------------------------------
def test_la_violacion_del_state_root_lleva_la_ruta_en_su_mensaje():
    """Premisa de H9: lo que `check_state_runtime` vuelca al informe es
    `Violation.message()`, y ese texto lleva la RUTA del fichero."""
    from app import service_identity

    ss = service_identity.service_state()
    mensaje = ss.Violation("UNREADABLE", RUTA, "esta vacio").message()
    assert RUTA in mensaje, "la premisa de H9 ha cambiado: el mensaje ya no lleva la ruta"


def _informe_con_ruta(monkeypatch):
    from app import service_identity
    from app.health.models import ComponentResult, HealthReport, HealthStatus

    ss = service_identity.service_state()
    texto = ss.Violation("UNREADABLE", RUTA, "esta vacio").message()
    informe = HealthReport([ComponentResult(
        "state_runtime", HealthStatus.UNHEALTHY,
        message=f"STATE_RUNTIME FAIL: 1 hallazgo(s): {texto}",
        details={"hallazgos": [texto]},
    )])
    monkeypatch.setattr("app.routers.health_admin.runner.run_report", lambda **k: informe)


def test_el_informe_de_salud_no_se_entrega_a_un_anonimo_con_la_auth_apagada(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    _informe_con_ruta(monkeypatch)
    monkeypatch.setenv("S9K_AUTH_ENABLED", "false")
    anonimo = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    r = anonimo.get("/api/admin/health", headers={"accept": "application/json"})
    assert r.status_code in (401, 403), (
        f"D6: /api/admin/health responde {r.status_code} a un anónimo con la auth apagada"
    )
    assert not _contiene_ruta(r.text), "D6: el informe de salud entrega la ruta a un anónimo"


@pytest.mark.parametrize("rol,esperado", [("viewer", 403), ("reviewer", 403), ("admin", 200)])
def test_el_informe_de_salud_por_rol(rol, esperado, monkeypatch, cliente_lector):
    from app.main import app

    _informe_con_ruta(monkeypatch)
    cliente = cliente_lector(app, role=rol, username=f"u_{rol}")
    r = cliente.get("/api/admin/health", headers={"accept": "application/json"})
    assert r.status_code == esperado, f"/api/admin/health da {r.status_code} al rol {rol}"
    if rol != "admin":
        assert not _contiene_ruta(r.text), f"D6: el rol {rol} recibe la ruta por la salud"


# --------------------------------------------------------------------------
# H1: el secreto REAL no sale por ningún camino
# --------------------------------------------------------------------------
#: 69 caracteres (70 con el salto de línea del fichero): una longitud que no puede salir de un reloj ni de un contador.
SECRETO = "Zq7-secreto-real-de-d6-NO-DEBE-SALIR-" + "x9k2" * 7 + "-fin"
assert len(SECRETO) == 69


def _tokens_del_secreto() -> list[str]:
    return [SECRETO, SECRETO[:10], SECRETO[-10:]]


def _longitudes() -> list[int]:
    # con y sin el salto de línea final que lleva el fichero
    return [len(SECRETO), len(SECRETO) + 1]


def _sin_secreto(texto: str, donde: str) -> None:
    for token in _tokens_del_secreto():
        assert token not in texto, f"H1: el secreto (o un trozo) sale por {donde}"
    for n in _longitudes():
        assert not re.search(rf"\b{n}\b", texto), (
            f"H1: la longitud del secreto ({n}) sale por {donde}"
        )


def _preparar_fichero(tmp_path, variante):
    jobs_client._load_job_store()  # deja `data-engine/app` en sys.path
    destino = tmp_path / f"cred-{variante}" / FICHERO
    destino.parent.mkdir()
    if variante == "ausente":
        return destino
    if variante == "vacio":
        destino.write_text("", encoding="utf-8")
        destino.chmod(0o600)
    elif variante == "permisos":
        destino.write_text(SECRETO + "\n", encoding="utf-8")
        destino.chmod(0o644)
    elif variante == "symlink":
        real = tmp_path / f"cred-{variante}" / "real.pass"
        real.write_text(SECRETO + "\n", encoding="utf-8")
        real.chmod(0o600)
        destino.symlink_to(real)
    return destino


@pytest.mark.parametrize("variante", ["ausente", "vacio", "permisos", "symlink"])
def test_el_secreto_real_no_sale_por_ningun_camino(
    variante, tmp_path, monkeypatch, caplog, cliente_lector
):
    from app.main import app
    from jobs.handlers import ingest_v3

    fichero = _preparar_fichero(tmp_path, variante)
    monkeypatch.setenv("S9K_NEO4J_URI", "bolt://127.0.0.1:7687")
    monkeypatch.setenv("S9K_NEO4J_USER", "neo4j")
    monkeypatch.setenv("S9K_NEO4J_PASSWORD_FILE", str(fichero))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ingest_v3.IngestV3Error) as info:
            ingest_v3._driver_de_observacion()
    fallo = info.value
    assert fallo.code == CODIGO, f"la variante {variante} no dio un fallo de credencial"
    # El detalle técnico SÍ lleva la ruta (es lo que ve el admin y el log)...
    assert FICHERO in str(fallo), "el detalle técnico perdió la ruta"
    # ...pero nunca el secreto, ni un trozo, ni su longitud.
    _sin_secreto(str(fallo), "el error_message del handler")
    _sin_secreto("\n".join(r.getMessage() for r in caplog.records), "el log capturado")

    # Se guarda como lo hace el worker y se mira por todos los caminos y roles.
    store = jobs_client._load_job_store()
    db = str(tmp_path / "jobs-h1.db")
    store.init_db(db)
    job_id = store.create_job("leyenda", job_type="ingest_v3", db_path=db)
    store.claim_next_job("w1", db_path=db)
    store.mark_failed(job_id, str(fallo), retry=False, db_path=db, error_code=fallo.error_code)
    monkeypatch.setenv("S9K_JOBS_DB", db)
    assert store.get_job(job_id, db_path=db)["error_code"] == CODIGO
    for rol in ROLES:
        cliente = cliente_lector(app, role=rol, username=f"h1_{rol}")
        for camino, texto in _respuestas(cliente, job_id).items():
            _sin_secreto(texto, f"{camino} ({rol}, variante {variante})")
            if rol != "admin":
                assert not _contiene_ruta(texto) and FICHERO not in texto, (
                    f"D6: la ruta sale por {camino} al rol {rol} (variante {variante})"
                )


def test_el_log_del_servicio_conserva_la_ruta(tmp_path, monkeypatch, caplog):
    jobs_client._load_job_store()  # deja `data-engine/app` en sys.path
    from jobs.handlers import ingest_v3

    fichero = tmp_path / "no-existe" / FICHERO
    monkeypatch.setenv("S9K_NEO4J_URI", "bolt://127.0.0.1:7687")
    monkeypatch.setenv("S9K_NEO4J_USER", "neo4j")
    monkeypatch.setenv("S9K_NEO4J_PASSWORD_FILE", str(fichero))
    with caplog.at_level(logging.ERROR):
        with pytest.raises(ingest_v3.IngestV3Error) as info:
            ingest_v3._driver_de_observacion()
    assert info.value.code == CODIGO, "el fallo no es de credencial inutilizable"
    registrado = " ".join(r.getMessage() for r in caplog.records)
    assert FICHERO in registrado, "D6: el log del servicio no conserva el detalle técnico"


def test_el_almacen_de_jobs_conserva_el_detalle_completo(tmp_path, monkeypatch):
    store, db, job_id = _cola(tmp_path, monkeypatch)
    crudo = store.get_job(job_id, db_path=db)
    assert RUTA in (crudo["error_message"] or ""), (
        "D6: la redacción se aplicó en el almacén y se perdió el detalle técnico"
    )
    assert crudo["error_code"] == CODIGO, "el código estable debe quedar en el almacén"

