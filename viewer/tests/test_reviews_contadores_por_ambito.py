"""Los contadores de /reviews son un DATO: se calculan DESPUÉS de filtrar.

Defecto medido: `_list_sources` recorría el directorio del workspace en disco y
publicaba `approved/pending/rejected` de CADA subdirectorio sin pasar por
`VisibilityScope`. La guarda de la ruta es de ROL, no de ámbito: dentro de un
workspace autorizado los totales agregaban material de otras partidas, de modo
que un revisor podía inferir EXISTENCIA y VOLUMEN de material ajeno sin llegar
a leerlo.

Orden obligatorio (regla del operador):

    AUTORIZAR/FILTRAR POR ÁMBITO -> CALCULAR CONTADORES -> RESPONDER

y nunca "calcular total global -> filtrar visibles -> publicar total global".
Cuando el ámbito no permite un cálculo seguro, la salida legítima es OMITIR la
cifra (ausencia honesta), no aproximarla ni ponerla a cero.

El patrón replicado es el del panel moderno
(`app/routers/reviews_console.py`, que pasa `scope=scope` al servicio).
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


# ---------------------------------------------------------------------------
# Banco de medida
# ---------------------------------------------------------------------------
@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Auth real + REPO_ROOT falso: el material de revisión vive en disco."""
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


def _fuente(ws_dir: Path, source_id: str, partida, *,
            approved: int = 1, pending: int = 1, rejected: int = 1) -> Path:
    """Una fuente en disco tal como la escribe el pipeline, con su partida."""
    d = ws_dir / source_id
    d.mkdir(parents=True)
    meta = {"workspace": WS, "source_id": source_id}
    if partida is not None:
        meta["partida_id"] = partida
    (d / "approved_payload.json").write_text(json.dumps({
        "metadata": meta,
        "approved": [{"id": "%s-a%d" % (source_id, i)} for i in range(approved)],
    }), encoding="utf-8")
    (d / "review_queue.json").write_text(json.dumps(
        [{"id": "%s-p%d" % (source_id, i), "metadata": dict(meta)} for i in range(pending)]
    ), encoding="utf-8")
    (d / "rejected.json").write_text(json.dumps(
        [{"id": "%s-r%d" % (source_id, i), "metadata": dict(meta)} for i in range(rejected)]
    ), encoding="utf-8")
    (d / "pipeline_state.json").write_text(json.dumps(meta), encoding="utf-8")
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
    """Cliente HTTP con sesión real y (opcionalmente) partida activa concedida."""
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


# El icono de cada insignia es una entidad HTML numérica (`&#10003;`), así que
# la cifra se ancla DESPUÉS de ella: si no, el 10003 del icono se colaría como
# contador y una prueba de fuga saldría verde contando el adorno.
_BADGE = re.compile(r'counter-badge (approved|pending|rejected)[^>]*>\s*&#\d+;\s*(\d+|&#8212;)')


def _contadores_html(texto):
    """Suma de TODOS los contadores publicados en la pantalla (HTML, no JSON).

    Se lee la respuesta que ve el usuario: si la cifra se escapa por la
    plantilla, aquí se ve, aunque una API devolviese lo correcto.
    """
    total = {"approved": 0, "pending": 0, "rejected": 0}
    for clase, valor in _BADGE.findall(texto):
        if valor == "&#8212;":  # ausencia honesta: no es una cifra
            continue
        total[clase] += int(valor)
    return total


def _insignias_omitidas(texto):
    """Insignias que publican ausencia (—) en lugar de una cifra."""
    return [c for c, v in _BADGE.findall(texto) if v == "&#8212;"]


def _fuentes_listadas(texto):
    return set(re.findall(r'href="/reviews/([^"]+)"', texto))


# ---------------------------------------------------------------------------
# P1 — el contador es el del ámbito, no el del directorio
# ---------------------------------------------------------------------------
def test_contador_cuenta_solo_lo_visible(entorno):
    """A: 10 fuentes visibles · B: 100 ocultas -> el usuario de A ve 10."""
    db, ws_dir = entorno
    for i in range(10):
        _fuente(ws_dir, "a-%03d" % i, P_A)
    for i in range(100):
        _fuente(ws_dir, "b-%03d" % i, P_B)

    c = _cliente(db, _usuario(db, "revisor_a"), P_A)
    r = c.get("/reviews?workspace=%s" % WS)
    assert r.status_code == 200, r.text

    listadas = _fuentes_listadas(r.text)
    assert len(listadas) == 10, "se listaron %d fuentes: %s" % (len(listadas), sorted(listadas)[:5])
    assert all(s.startswith("a-") for s in listadas)
    assert _contadores_html(r.text) == {"approved": 10, "pending": 10, "rejected": 10}


def test_contador_del_listado_excluye_items_infiltrados(entorno):
    """Una fuente VISIBLE cuyos ficheros llevan ítems de otra partida: la cifra
    del listado cuenta los propios, no el total del fichero.

    Sin esto, filtrar la fuente y luego contar el fichero entero seguiría
    publicando el volumen ajeno: es exactamente el orden prohibido.
    """
    db, ws_dir = entorno
    d = _fuente(ws_dir, "a-mixta", P_A, approved=2, pending=2, rejected=1)
    for fichero, extra in (("review_queue.json", 40), ("rejected.json", 7)):
        datos = json.loads((d / fichero).read_text())
        datos += [{"id": "intruso-%d" % i, "metadata": {"partida_id": P_B}}
                  for i in range(extra)]
        (d / fichero).write_text(json.dumps(datos), encoding="utf-8")
    payload = json.loads((d / "approved_payload.json").read_text())
    payload["approved"] += [{"id": "intruso-a%d" % i, "partida_id": P_B} for i in range(60)]
    (d / "approved_payload.json").write_text(json.dumps(payload), encoding="utf-8")

    c = _cliente(db, _usuario(db, "revisor_a"), P_A)
    r = c.get("/reviews?workspace=%s" % WS)
    assert r.status_code == 200, r.text
    assert _fuentes_listadas(r.text) == {"a-mixta"}
    assert _contadores_html(r.text) == {"approved": 2, "pending": 2, "rejected": 1}


# ---------------------------------------------------------------------------
# P2 — crecer el material oculto no mueve NINGUNA cifra del usuario limitado
# ---------------------------------------------------------------------------
def test_material_oculto_no_altera_la_respuesta(entorno):
    """Añadir 500 fuentes a B deja la respuesta de A byte a byte igual."""
    db, ws_dir = entorno
    for i in range(10):
        _fuente(ws_dir, "a-%03d" % i, P_A)
    for i in range(100):
        _fuente(ws_dir, "b-%03d" % i, P_B)

    c = _cliente(db, _usuario(db, "revisor_a"), P_A)
    antes = c.get("/reviews?workspace=%s" % WS).text

    for i in range(100, 600):
        _fuente(ws_dir, "b-%03d" % i, P_B, approved=7, pending=3, rejected=2)

    despues = c.get("/reviews?workspace=%s" % WS).text
    assert despues == antes, "la respuesta cambió al crecer material de otra partida"


# ---------------------------------------------------------------------------
# P3 — indistinguibilidad: sin acceso a B no se infiere que B existe
# ---------------------------------------------------------------------------
def test_sin_acceso_no_se_infiere_la_existencia_del_material_ajeno(entorno):
    """Con B y sin B, la respuesta del usuario de A es la misma; y el detalle
    de una fuente de B responde 404, no 403 (no confirma existencia)."""
    db, ws_dir = entorno
    for i in range(10):
        _fuente(ws_dir, "a-%03d" % i, P_A)

    c = _cliente(db, _usuario(db, "revisor_a"), P_A)
    sin_b = c.get("/reviews?workspace=%s" % WS).text

    for i in range(100):
        _fuente(ws_dir, "b-%03d" % i, P_B)
    con_b = c.get("/reviews?workspace=%s" % WS).text

    assert con_b == sin_b
    assert "b-0" not in con_b and "partida-b" not in con_b

    detalle = c.get("/reviews/b-000?workspace=%s" % WS)
    assert detalle.status_code == 404, (
        "el detalle de material ajeno respondió %d: confirma su existencia"
        % detalle.status_code
    )


# ---------------------------------------------------------------------------
# P4 — ámbito inexistente / inválido -> FAIL-CLOSED
# ---------------------------------------------------------------------------
def test_ambito_invalido_es_fail_closed(entorno):
    """Sin partida activa no se recibe material de partida, y una partida
    inexistente no se activa (no hay concesión): nada de A ni de B."""
    db, ws_dir = entorno
    for i in range(10):
        _fuente(ws_dir, "a-%03d" % i, P_A)
    for i in range(5):
        _fuente(ws_dir, "b-%03d" % i, P_B)

    c = _cliente(db, _usuario(db, "revisor_sin_partida"), None)
    r = c.get("/reviews?workspace=%s" % WS)
    assert r.status_code == 200, r.text
    assert _fuentes_listadas(r.text) == set()
    assert _contadores_html(r.text) == {"approved": 0, "pending": 0, "rejected": 0}

    # Partida que no existe en la tabla de concesiones: no se activa.
    from app.auth import db as auth_db
    from app.auth.config import get_auth_settings
    from app.auth.sessions import create_session
    from fastapi.testclient import TestClient
    from app.main import app
    u = _usuario(db, "revisor_partida_fantasma")
    with auth_db.get_conn(db) as conn:
        token, session = create_session(conn, u)
        auth_db.set_session_active_partida(conn, session.id, "partida-que-no-existe")
    c2 = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c2.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, token)
    r2 = c2.get("/reviews?workspace=%s" % WS)
    assert r2.status_code == 200, r2.text
    assert _fuentes_listadas(r2.text) == set()


# ---------------------------------------------------------------------------
# P5 — el detalle tampoco publica cifras de otra partida
# ---------------------------------------------------------------------------
def test_detalle_no_publica_items_de_otra_partida(entorno):
    """Una fuente de la partida activa con ítems infiltrados de otra partida:
    los contadores y la vista previa del detalle sólo cuentan los propios."""
    db, ws_dir = entorno
    d = _fuente(ws_dir, "mixta", P_A, approved=2, pending=2, rejected=0)
    # Se infiltran ítems de otra partida en los mismos ficheros.
    cola = json.loads((d / "review_queue.json").read_text())
    cola += [{"id": "intruso-%d" % i, "metadata": {"partida_id": P_B}} for i in range(9)]
    (d / "review_queue.json").write_text(json.dumps(cola), encoding="utf-8")
    payload = json.loads((d / "approved_payload.json").read_text())
    payload["approved"] += [{"id": "intruso-a%d" % i, "partida_id": P_B} for i in range(30)]
    (d / "approved_payload.json").write_text(json.dumps(payload), encoding="utf-8")

    c = _cliente(db, _usuario(db, "revisor_a"), P_A)
    r = c.get("/reviews/mixta?workspace=%s" % WS)
    assert r.status_code == 200, r.text
    assert "intruso" not in r.text, "la vista previa filtró contenido de otra partida"
    assert _contadores_html(r.text) == {"approved": 2, "pending": 2, "rejected": 0}


def test_quality_report_no_publica_cifras_de_una_fuente_mezclada(entorno):
    """El `quality_report` cubre la fuente entera y no trae atribución por ítem:
    si la fuente mezcla partidas, sus cifras se omiten; si es homogénea, salen.
    """
    db, ws_dir = entorno
    informe = json.dumps({"score": 0.91, "total": 137, "issues": 4, "warnings": 11})

    limpia = _fuente(ws_dir, "a-limpia", P_A, approved=1, pending=1, rejected=1)
    (limpia / "quality_report.json").write_text(informe, encoding="utf-8")

    mezclada = _fuente(ws_dir, "a-mezclada", P_A, approved=1, pending=1, rejected=1)
    (mezclada / "quality_report.json").write_text(informe, encoding="utf-8")
    cola = json.loads((mezclada / "review_queue.json").read_text())
    cola.append({"id": "intruso", "metadata": {"partida_id": P_B}})
    (mezclada / "review_queue.json").write_text(json.dumps(cola), encoding="utf-8")

    c = _cliente(db, _usuario(db, "revisor_a"), P_A)

    r_ok = c.get("/reviews/a-limpia?workspace=%s" % WS)
    assert r_ok.status_code == 200, r_ok.text
    assert "137" in r_ok.text and "Informe de calidad" in r_ok.text

    r_mix = c.get("/reviews/a-mezclada?workspace=%s" % WS)
    assert r_mix.status_code == 200, r_mix.text
    assert "Informe de calidad" not in r_mix.text, (
        "se publicó un informe calculado también sobre material de otra partida"
    )
    for cifra in ("137", "0.91", "intruso"):
        assert cifra not in r_mix.text


# ---------------------------------------------------------------------------
# Ausencia honesta: si no se puede contar con seguridad, no se publica cifra
# ---------------------------------------------------------------------------
def test_contador_no_atribuible_se_omite_no_se_pone_a_cero(entorno):
    """`review_queue.json` con una forma que no permite atribuir ítem a ítem:
    la pantalla omite la cifra (—), no publica 0 ni el total global."""
    db, ws_dir = entorno
    d = _fuente(ws_dir, "opaca", P_A, approved=1, pending=1, rejected=1)
    # Forma no enumerable por ítems: un blob sin registros atribuibles.
    (d / "review_queue.json").write_text(json.dumps({"a": 1, "b": 2, "c": 3}), encoding="utf-8")

    c = _cliente(db, _usuario(db, "revisor_a"), P_A)
    r = c.get("/reviews?workspace=%s" % WS)
    assert r.status_code == 200, r.text
    conts = _contadores_html(r.text)
    assert conts["approved"] == 1 and conts["rejected"] == 1
    assert conts["pending"] == 0, "se publicó un total no atribuible como cifra"
    assert _insignias_omitidas(r.text) == ["pending"], (
        "el contador no atribuible debe omitirse con una marca de ausencia, no valer 0 "
        "ni publicar el total global"
    )
    assert "3" not in _BADGE.findall(r.text)[1][1], "se publicó el total global (3)"
