# -*- coding: utf-8 -*-
"""Slice 2 · Corte 3 — la ingesta del panel produce propuestas REVISABLES.

EL DEFECTO QUE ESTE MÓDULO FIJA
-------------------------------
Medido antes del corte, ejecutando::

    job complete · episodios 7 · menciones 10 · claims 5
    por_veredicto {ABSTAIN: 2, ACCEPT: 1, REVIEW: 2}
    PROPUESTAS ESCRITAS POR LA INGESTA DEL PANEL: []
    /panel/review -> «Sin propuestas visibles»

`REVIEW=2` en el informe y CERO propuestas revisables. El operador ve
`complete`, concluye que no hay nada que revisar, y da por buena una ingesta
cuyas ambigüedades no vio nunca. `review_proposals_dir` existía sólo como
parámetro de `Pipeline.run`: una capacidad completa y SIN LLAMADOR en el camino
del producto, que desde el código se lee igual que una viva.

POR QUÉ ESTA PRUEBA NO PUEDE PONERSE VERDE POR BASURA ANTERIOR
--------------------------------------------------------------
El almacén de propuestas se crea VACÍO en cada caso (`tmp_path`) y se comprueba
vacío antes de empezar. Lo que se afirma después no es un recuento —«hay algún
fichero» se pondría verde con restos de otra corrida— sino la IDENTIDAD: los
`proposal_id` que `/panel/review` enseña son exactamente los que escribió ESTA
ejecución, para ESE workspace.

Y la ingesta se lanza DESDE EL PANEL: formulario real, CSRF real, cola real y
worker real. No se llama a `run_ingest` a mano, porque el defecto era
justamente que el camino del panel no pasaba por donde se creía.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import jobs_client
from app.chassis import FEATURE_SLOTS

SLOT_B = next(s for s in FEATURE_SLOTS if s.key == "B")
SLOT_C = next(s for s in FEATURE_SLOTS if s.key == "C")
FLAG_B = "S9K_PANEL_B_ENABLED"
FLAG_C = "S9K_PANEL_C_ENABLED"
PASSWORD = "Contrasena-De-Prueba-1"

REPO = Path(__file__).resolve().parents[2]
EJEMPLOS = REPO / "examples" / "ingesta-v3"


# ---------------------------------------------------------------------------
# Fixtures: app real, auth real, cola real, almacén de propuestas real y VACÍO
# ---------------------------------------------------------------------------

@pytest.fixture
def real_app():
    from app.main import app
    return app


@pytest.fixture(autouse=True)
def _entorno_limpio():
    from app.auth.config import get_auth_settings
    from app.config import get_settings
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    yield
    for var in ("S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_JOBS_DB",
                "S9K_INGEST_SOURCES_DIR", FLAG_B, FLAG_C):
        os.environ.pop(var, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _salud_aislada(tmp_path, monkeypatch):
    monkeypatch.setenv("S9K_HEALTH_REPORT_PATH", str(tmp_path / "health" / "last.json"))


@pytest.fixture
def almacen_de_propuestas(tmp_path, monkeypatch) -> Path:
    """EL INVARIANTE DE DESPLIEGUE, ejercido: escritor y lector, un almacén.

    Se declara UNA variable y la ven los dos lados porque los dos la resuelven
    por el MISMO resolvedor (`knowledge_v3.review_paths`). Si el visor
    conservara su derivación propia, esta fixture no bastaría para alinearlos y
    la prueba insignia se pondría roja — que es justo lo que se quiere.
    """
    directorio = tmp_path / "reviews-v3" / "proposals"
    monkeypatch.setenv("S9K_V3_REVIEW_PROPOSALS_DIR", str(directorio))
    # Las decisiones humanas viven en otro almacén, y también aislado: una
    # decisión heredada de otra corrida sacaría propuestas de la cola.
    monkeypatch.setenv("S9K_V3_REVIEW_DECISIONS_PATH",
                       str(tmp_path / "reviews-v3" / "decisions.jsonl"))
    monkeypatch.setenv("S9K_V3_REVIEW_DATABASE_PATH",
                       str(tmp_path / "reviews-v3" / "review.sqlite3"))
    return directorio


@pytest.fixture
def paneles_on():
    os.environ[FLAG_B] = "true"
    os.environ[FLAG_C] = "true"
    yield
    os.environ.pop(FLAG_B, None)
    os.environ.pop(FLAG_C, None)


@pytest.fixture
def cola(tmp_path):
    from app.config import get_settings

    db = tmp_path / "jobs.db"
    os.environ["S9K_JOBS_DB"] = str(db)
    get_settings.cache_clear()
    store = jobs_client._load_job_store()
    assert store is not None, "sin job_store no hay nada que probar"
    store.init_db(str(db))
    yield db
    get_settings.cache_clear()


@pytest.fixture
def auth_on(tmp_path):
    from app.auth.config import get_auth_settings
    from app.auth import db as auth_db_mod

    db_path = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    get_auth_settings.cache_clear()
    auth_db_mod.ensure_migrated(db_path)
    return db_path


def _cookie(db_path: Path, username: str, role: str) -> str:
    from app.auth import db as auth_db_mod
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db_mod.get_conn(db_path) as conn:
        user = auth_db_mod.create_user(
            conn, username=username, display_name=username.title(),
            password_hash=hash_password(PASSWORD), role=role,
        )
        auth_db_mod.update_user(conn, user.id, must_change_password=False)
        user = auth_db_mod.get_user_by_id(conn, user.id)
        token, _ = create_session(conn, user)
    return token


@pytest.fixture
def operador(real_app, auth_on):
    from app.auth.config import get_auth_settings

    c = TestClient(real_app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME,
                  _cookie(auth_on, "corte3_operador", "admin"))
    c.headers.update({"accept": "text/html"})
    return c


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]*)"', html)
    assert m, "el formulario no trae token CSRF"
    return m.group(1)


def _opciones(html: str) -> list[str]:
    bloque = re.search(r'data-role="selector-fuente".*?</select>', html, re.S)
    assert bloque, "no hay selector de fuente en la pantalla"
    return re.findall(r'<option value="([^"]+)"', bloque.group(0))


def _copia_de_fuentes(destino: Path) -> Path:
    """Una copia ESCRIBIBLE del catálogo de ejemplo, para poder romperla."""
    import shutil

    shutil.copytree(EJEMPLOS, destino)
    return destino


def _correr_worker(db: Path, limit: int = 1) -> int:
    from jobs import worker

    return worker.run("worker-test", once=True, limit=limit, db_path=str(db))


def _propuestas_escritas(directorio: Path) -> tuple[list[str], set[str]]:
    """Los `proposal_id` que hay AHORA en el almacén, y sus workspaces."""
    ids: list[str] = []
    workspaces: set[str] = set()
    if not directorio.exists():
        return ids, workspaces
    for fichero in sorted(directorio.glob("*.json")):
        paquete = json.loads(fichero.read_text(encoding="utf-8"))
        workspaces.add(paquete["workspace"])
        ids.extend(item["proposal_id"] for item in paquete.get("items", []))
    return ids, workspaces


def _lanzar_ingesta_desde_el_panel(operador, cola, monkeypatch) -> str:
    """El recorrido REAL del operador. Devuelve el `job_id` ya terminado."""
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(EJEMPLOS))

    pantalla = operador.get(SLOT_B.prefix)
    assert pantalla.status_code == 200, pantalla.status_code
    html = pantalla.text
    opciones = _opciones(html)
    assert opciones, "no se ofrece ninguna fuente que elegir"

    envio = operador.post(
        "/panel/operations/ingestas",
        data={"fuente": opciones[0], "csrf_token": _csrf(html)},
    )
    assert envio.status_code == 303, envio.text[:300]

    store = jobs_client._load_job_store()
    pendientes = store.list_jobs(status="pending", db_path=str(cola))
    assert len(pendientes) == 1, pendientes
    job_id = pendientes[0]["job_id"]

    assert _correr_worker(cola) == 1
    final = store.get_job(job_id, db_path=str(cola))
    assert final["status"] == "complete", final.get("error_message")
    return job_id


# ===========================================================================
# 1. LA PRUEBA INSIGNIA
# ===========================================================================

def test_la_ingesta_del_panel_produce_propuestas_que_panel_review_ensena(
    real_app, paneles_on, cola, operador, almacen_de_propuestas, monkeypatch
):
    """De «lanzar desde el panel» a «verlas en la cola de revisión».

    Es LA prueba del corte y recorre exactamente el guion del encargo:
    almacén vacío -> ingesta desde el panel -> fuente con REVIEW > 0 ->
    esperar a `complete` -> ESAS propuestas en `/panel/review`.
    """
    # --- 1. el almacén está VACÍO al empezar. Se comprueba, no se supone. ---
    previas, _ = _propuestas_escritas(almacen_de_propuestas)
    assert previas == [], (
        "el almacén de propuestas no estaba vacío: cualquier verde posterior "
        f"podría venir de estos restos: {previas}"
    )

    # --- 2 y 3. la ingesta se lanza DESDE EL PANEL y termina ---
    job_id = _lanzar_ingesta_desde_el_panel(operador, cola, monkeypatch)

    # --- 4. la fuente produce REVISIÓN DE VERDAD ---
    store = jobs_client._load_job_store()
    resultado = json.loads(store.get_job(job_id, db_path=str(cola))["result_json"])
    veredictos = resultado["resumen"]["por_veredicto"]
    assert veredictos.get("REVIEW", 0) > 0, (
        "la fuente del arnés ya no produce REVIEW; sin ambigüedades que "
        f"revisar esta prueba no demuestra nada: {veredictos}"
    )

    # --- 5. la ingesta ESCRIBIÓ propuestas (era el llamador que faltaba) ---
    escritas, workspaces = _propuestas_escritas(almacen_de_propuestas)
    assert escritas, (
        "la ingesta del panel no escribió NI UNA propuesta pese a informar "
        f"{veredictos}. Es el defecto del Corte 3: informe con REVIEW y cola "
        "de revisión vacía."
    )
    assert len(workspaces) == 1, workspaces
    workspace = workspaces.pop()

    # --- 6. ESAS propuestas, de ESA corrida, en `/panel/review` ---
    pantalla = operador.get(f"{SLOT_C.prefix}?workspace={workspace}")
    assert pantalla.status_code == 200, pantalla.status_code
    html = pantalla.text
    assert "Sin propuestas visibles" not in html, (
        "el panel de revisión sigue diciendo que no hay nada que revisar"
    )

    # IDENTIDAD, no recuento: cada propuesta que escribió esta ejecución tiene
    # que estar en la pantalla. Un recuento se pondría verde con basura ajena.
    ausentes = [pid for pid in escritas if pid not in html]
    assert not ausentes, (
        f"{len(ausentes)} de {len(escritas)} propuestas de esta ejecución no "
        f"aparecen en /panel/review: {ausentes}"
    )


def test_el_operador_lee_el_motivo_en_castellano_no_el_codigo_crudo(
    real_app, paneles_on, cola, operador, almacen_de_propuestas, monkeypatch
):
    """El paso 5 no es usable si el motivo llega como código crudo.

    Medido antes del corte: el 100 % de los motivos reales caía al `code`
    verbatim, y además duplicado (`CESSATION_WITHOUT_ACTIVE_ASSERTION:
    CESSATION_WITHOUT_ACTIVE_ASSERTION`).
    """
    from app.services.v3_review import REASON_LABELS

    _lanzar_ingesta_desde_el_panel(operador, cola, monkeypatch)
    escritas, workspaces = _propuestas_escritas(almacen_de_propuestas)
    assert escritas, "sin propuestas no hay motivos que leer"
    workspace = workspaces.pop()

    # Los motivos que ESTA corrida emitió de verdad.
    emitidos: set[str] = set()
    for fichero in almacen_de_propuestas.glob("*.json"):
        paquete = json.loads(fichero.read_text(encoding="utf-8"))
        for item in paquete["items"]:
            emitidos.update(item["engine_decision"].get("reason_codes") or [])
    assert emitidos, "la corrida no emitió ningún motivo"

    crudos = sorted(c for c in emitidos if c not in REASON_LABELS)
    assert not crudos, (
        f"{len(crudos)} motivos REALES de esta ingesta no tienen "
        f"representación humana: {crudos}"
    )

    html = operador.get(f"{SLOT_C.prefix}?workspace={workspace}").text
    algun_motivo = sorted(emitidos)[0]
    assert REASON_LABELS[algun_motivo] in html or any(
        REASON_LABELS[c] in html for c in emitidos
    ), "la pantalla no pinta ni una sola explicación en castellano"


# ===========================================================================
# 2. QUE NO SE VUELVAN A DESALINEAR
# ===========================================================================

def test_todo_motivo_emitible_por_el_motor_tiene_representacion_humana():
    """Códigos EMITIBLES contra códigos PRESENTABLES, sin listas a mano.

    Los emitibles se DERIVAN del catálogo del motor
    (`engine.findings.emittable_reason_codes`, que invoca cada entrada del
    catálogo y recoge su `code` y su `canonical`). Copiarlos a mano aquí sería
    reproducir el defecto: la tabla de etiquetas se quedó desalineada
    precisamente porque nadie comparaba nada.
    """
    from knowledge_v3.engine.findings import emittable_reason_codes
    from app.services.v3_review import REASON_LABELS

    emitibles = emittable_reason_codes()
    assert len(emitibles) > 50, (
        "la derivación ha dejado de ver el catálogo del motor; una prueba que "
        f"compara contra un conjunto casi vacío no protege nada: {emitibles}"
    )

    sin_etiqueta = sorted(emitibles - set(REASON_LABELS))
    assert not sin_etiqueta, (
        f"{len(sin_etiqueta)} códigos que el motor PUEDE emitir llegarían al "
        f"operador como código crudo: {sin_etiqueta}"
    )

    # Y al revés: una etiqueta que ya no corresponde a ningún código del motor
    # es texto muerto que aparenta cobertura.
    sobrantes = sorted(set(REASON_LABELS) - emitibles)
    assert not sobrantes, (
        f"{len(sobrantes)} etiquetas no corresponden a ningún código emitible: "
        f"{sobrantes}"
    )


def test_ninguna_etiqueta_repite_el_codigo():
    """`CODIGO: CODIGO` era el síntoma visible del desajuste."""
    from app.services.v3_review import REASON_LABELS

    iguales = sorted(c for c, texto in REASON_LABELS.items() if texto.strip() == c)
    assert not iguales, f"etiquetas que sólo repiten el código: {iguales}"


def test_solo_hay_un_resolvedor_del_almacen_de_propuestas():
    """UNA derivación de la ruta, y se comprueba por ENUMERACIÓN.

    Si hay dos derivaciones hay dos verdades, y el síntoma —motor escribiendo
    en una carpeta, visor mirando otra— se lee como «no hay nada que revisar»,
    sin un solo error. Por eso el nombre de la variable sólo puede aparecer en
    el resolvedor canónico: cualquier otro módulo del producto que lo lea está
    derivando la ruta por su cuenta.
    """
    import ast

    from knowledge_v3 import review_paths

    raices = [REPO / "viewer" / "app", REPO / "data-engine" / "app"]
    culpables: list[str] = []
    for raiz in raices:
        for fichero in raiz.rglob("*.py"):
            if "/tests/" in fichero.as_posix() or fichero.name.startswith("test_"):
                continue
            if fichero.resolve() == Path(review_paths.__file__).resolve():
                continue
            arbol = ast.parse(fichero.read_text(encoding="utf-8"), str(fichero))
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.Constant) and nodo.value == "S9K_V3_REVIEW_PROPOSALS_DIR":
                    culpables.append(f"{fichero.relative_to(REPO)}:{nodo.lineno}")
    assert not culpables, (
        "segunda derivación de la ruta del almacén de propuestas en: "
        + ", ".join(culpables)
    )


def test_el_visor_y_el_motor_resuelven_la_misma_ruta(monkeypatch, tmp_path):
    """No basta con que el nombre aparezca una vez: tienen que COINCIDIR."""
    from knowledge_v3.review_paths import default_proposals_dir as motor
    from app.services.v3_review import default_proposals_dir as visor

    assert visor() == motor()

    elegida = tmp_path / "otro" / "almacen"
    monkeypatch.setenv("S9K_V3_REVIEW_PROPOSALS_DIR", str(elegida))
    assert visor() == elegida
    assert motor() == elegida


# ===========================================================================
# 3. UN TRABAJO FALLIDO NO SE PRESENTA CON UN MENSAJE TRANQUILIZADOR
# ===========================================================================

def test_un_trabajo_fallido_no_se_anuncia_como_encolado(
    real_app, paneles_on, cola, operador, monkeypatch, tmp_path
):
    """Estado y causa, UNA sola presentación, y el fallo no va detrás.

    Medido antes del corte: con el job en `failed` la pantalla mostraba PRIMERO
    «Se ha solicitado la ingesta. El trabajo ya está en la cola.» y DESPUÉS
    `estado failed`. El texto tranquilizador iba delante, y es el que se lee.
    """
    # Un catálogo PROPIO y escribible: el fallo se provoca quitando la fuente
    # entre el encolado y la corrida, que es un fallo REAL del handler
    # (`SOURCE_PACKAGE_INVALID`, permanente) y no una fila retocada a mano.
    fuentes = _copia_de_fuentes(tmp_path / "fuentes")
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(fuentes))
    store = jobs_client._load_job_store()

    pantalla = operador.get(SLOT_B.prefix)
    html = pantalla.text
    envio = operador.post(
        "/panel/operations/ingestas",
        data={"fuente": _opciones(html)[0], "csrf_token": _csrf(html)},
    )
    assert envio.status_code == 303
    destino = envio.headers["location"]
    job_id = store.list_jobs(status="pending", db_path=str(cola))[0]["job_id"]

    for fichero in fuentes.glob("*.md"):
        fichero.unlink()
    _correr_worker(cola)
    estado = store.get_job(job_id, db_path=str(cola))
    assert estado["status"] == "failed", estado

    despues = operador.get(destino)
    assert despues.status_code == 200
    texto = despues.text

    assert "Se ha solicitado la ingesta" not in texto, (
        "la pantalla sigue anunciando «encolado» sobre un trabajo que ya falló"
    )
    assert 'data-resultado-estado="error"' in texto, (
        "el fallo no se presenta como fallo"
    )
    # Estado Y causa comprensible, juntos.
    assert "El paquete de la fuente no es valido." in texto

    # El detalle técnico se queda en el servidor.
    assert "SOURCE_PACKAGE_INVALID:" not in texto or texto.count("SOURCE_PACKAGE_INVALID:") == 0


def test_mientras_esta_en_la_cola_el_acuse_sigue_siendo_correcto(
    real_app, paneles_on, cola, operador, monkeypatch
):
    """Control del control: no se ha silenciado el acuse legítimo.

    Suprimir el acuse SIEMPRE dejaría el caso anterior en verde por la razón
    equivocada. Mientras el trabajo está pendiente, «está en la cola» es cierto
    y tiene que decirse.
    """
    monkeypatch.setenv("S9K_INGEST_SOURCES_DIR", str(EJEMPLOS))
    pantalla = operador.get(SLOT_B.prefix)
    html = pantalla.text
    envio = operador.post(
        "/panel/operations/ingestas",
        data={"fuente": _opciones(html)[0], "csrf_token": _csrf(html)},
    )
    destino = envio.headers["location"]

    acuse = operador.get(destino)
    assert 'data-aviso-tipo="ok"' in acuse.text
    assert "Se ha solicitado la ingesta" in acuse.text
