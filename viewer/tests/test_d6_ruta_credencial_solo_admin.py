"""D6: la ruta del fichero de credencial del grafo sólo la ven administradores.

Contexto: desde #291 un fallo de credencial del grafo guarda en el job
`error_code=GRAPH_CREDENTIAL_UNUSABLE` y un `error_message` con la ruta del
fichero y el motivo. Decisión del operador (D6): la ruta completa sólo es
visible para administración; el resto recibe código estable + explicación +
a quién avisar. El detalle se conserva en el almacén de jobs y en el log.

Sujeto: los caminos REALES del visor (HTML `/jobs`, `/jobs/{id}`, API
`/api/jobs`, `/api/jobs/{id}`, panel del chasis) con usuarios autenticados de
verdad por rol (`cliente_lector`), sobre una cola SQLite escrita por el
`job_store` real.
"""
from __future__ import annotations

import logging

import pytest

from app import jobs_client

CODIGO = "GRAPH_CREDENTIAL_UNUSABLE"
#: Ruta y fichero inventados, sin relación con ninguna máquina real.
DIRECTORIO = "/srv/secretos-d6"
FICHERO = "neo4j-clave-d6.pass"
RUTA = f"{DIRECTORIO}/{FICHERO}"
SECRETO = "S3CRETO-D6-QUE-NO-DEBE-SALIR-0123456789-abcdef"
MENSAJE = (
    f"{CODIGO}: La conexion al grafo esta declarada, pero el fichero con su "
    f"credencial no se puede usar. Causa: el fichero {RUTA} tiene un modo "
    "no permitido por la politica."
)
FRAGMENTOS_DE_LA_RUTA = (RUTA, DIRECTORIO, "secretos-d6", FICHERO, "neo4j-clave")


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


@pytest.mark.parametrize("rol", ["viewer", "reviewer", "admin"])
def test_nadie_ve_el_contenido_del_secreto(rol, tmp_path, monkeypatch, cliente_lector):
    from app.main import app

    _, _, job_id = _cola(tmp_path, monkeypatch)
    cliente = cliente_lector(app, role=rol, username=f"u_{rol}")
    for camino, texto in _respuestas(cliente, job_id).items():
        assert SECRETO not in texto, f"D6: el contenido del secreto sale por {camino} ({rol})"
        assert SECRETO[:12] not in texto, (
            f"D6: un valor parcial del secreto sale por {camino} ({rol})"
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
# Por defecto, redactado
# --------------------------------------------------------------------------
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


def test_el_panel_del_chasis_da_el_codigo_real_y_nunca_la_ruta(
    tmp_path, monkeypatch, cliente_lector
):
    from app.main import app

    _, _, job_id = _cola(tmp_path, monkeypatch)
    for rol in ("reviewer", "admin"):
        cliente = cliente_lector(app, role=rol, username=f"u_{rol}")
        pagina = cliente.get("/panel/operations", params={"solicitado": job_id})
        if rol != "admin" and pagina.status_code in (302, 303, 401, 403):
            continue  # la losa puede estar vedada a ese rol: entonces no hay nada que filtrar
        assert pagina.status_code == 200, (
            f"D6: el panel del chasis no responde 200 al rol {rol} ({pagina.status_code})"
        )
        assert not _contiene_ruta(pagina.text), (
            f"D6: el panel del chasis pinta la ruta al rol {rol}"
        )
        assert CODIGO in pagina.text, (
            f"D6: el panel del chasis no da el código estable al rol {rol}"
        )


# --------------------------------------------------------------------------
# El detalle se conserva en registros protegidos
# --------------------------------------------------------------------------
def test_el_almacen_de_jobs_conserva_el_detalle_completo(tmp_path, monkeypatch):
    store, db, job_id = _cola(tmp_path, monkeypatch)
    crudo = store.get_job(job_id, db_path=db)
    assert RUTA in (crudo["error_message"] or ""), (
        "D6: la redacción se aplicó en el almacén y se perdió el detalle técnico"
    )
    assert crudo["error_code"] == CODIGO, "el código estable debe quedar en el almacén"


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
