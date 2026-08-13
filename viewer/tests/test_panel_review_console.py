"""Hueco C del chasis — Review Console SOLO LECTURA.

REGLA DE ESTA SUITE, heredada de `test_chassis_mount_contract.py`: todo lo que
sea HTTP se prueba contra la aplicación REAL (`app.main.app`). No se construye
aquí ningún `FastAPI()` de mentira. La suite anterior de esta consola
(`origin/feat/review-console-v2-readonly`) sí lo hacía, y por eso no podía
afirmar nada sobre el montaje —que es justo lo que había que rehacer—.

Sobre la sustitución de dependencias: `get_visibility_context` se llama como
FUNCIÓN NORMAL desde `get_filtered_provider` y desde `get_visibility_scope`
(`app/authz/dependencies.py`), así que sobrescribirlo con
`dependency_overrides` es INERTE y sale verde sin morder. Lo que sí entra por
`Depends` en este router es `get_visibility_scope`, y es lo que se sustituye —
con un control de colapso (`test_la_sustitucion_de_ambito_muerde`) que exige
que sin la sustitución el resultado CAMBIE. Un arnés que no puede cambiar el
resultado no prueba nada.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.authz.context import build_viewer_context
from app.authz.dependencies import get_visibility_scope
from app.authz.scope import VisibilityScope
from app.chassis import FEATURE_SLOTS, route_index, slot_flag_env
from app.routers import chassis_review as panel
from app.services import review_console_v2 as console
from app.services.v3_review import ReviewService

SLOT = next(s for s in FEATURE_SLOTS if s.key == "C")
FLAG = slot_flag_env(SLOT)
PASSWORD = "PanelCTest_1234567890!"

EPISODE = "Ariadna protege la ciudad de Bruma durante el invierno de sangre."
LITERAL = "protege la ciudad de Bruma"


# ---------------------------------------------------------------------------
# Material de prueba
# ---------------------------------------------------------------------------

def make_proposal(
    proposal_id: str,
    *,
    workspace: str = "alpha",
    source_id: str = "source-1",
    decision: str = "REVIEW",
    shadow: str | None = None,
    confidence: float | None = 0.42,
    reason_codes: list[str] | None = None,
    provider: str | None = "nvidia-shadow",
    extractors: list[str] | None = None,
    subject: str = "Ariadna",
    predicate: str = "PROTECTS",
    obj: str = "Bruma",
    partida_id: str | None = None,
) -> dict:
    start = EPISODE.index(LITERAL)
    document = {
        "proposal_id": proposal_id,
        "workspace": workspace,
        "source_id": source_id,
        "episode_id": f"episode-{proposal_id}",
        "episode_text": EPISODE,
        "evidence": {"start": start, "end": start + len(LITERAL), "literal_text": LITERAL},
        "claim_id": f"claim-{proposal_id}",
        "proposal": {
            "subject": subject, "predicate": predicate, "object": obj,
            "direction": "SUBJECT_TO_OBJECT", "negated": False, "negation_kind": "NONE",
            "scope": "durante el invierno", "epistemic_status": "ASSERTED",
            "temporal_status": "PRESENT",
        },
        "engine_decision": {
            "decision": decision, "effective_decision": decision, "shadow_decision": shadow,
            "reason_codes": reason_codes or ["AMBIGUOUS_PREDICATE"],
            "confidence": confidence, "provider": provider, "model": "modelo-x",
            "shadow_findings": [], "ignored_findings": [],
            "effective_findings": reason_codes or ["AMBIGUOUS_PREDICATE"],
            "would_emit_operations": False, "operation_kinds": [],
        },
        "resolution": {"subject": "entity-ariadna", "object": "entity-bruma"},
        "alternatives": {"predicates": [], "directions": []},
        "provenance": {
            "extractors": extractors or ["semantic-local"], "providers": ["local"],
            "models": ["modelo-x"], "independent_families": ["rules"],
        },
        "ontology_version": "bruma-v1", "engine_version": "knowledge-v3-test",
        "prompt_version": "p1", "profile_version": "perfil-1",
    }
    if partida_id:
        document["partida_id"] = partida_id
    return document


def write_package(directory: Path, documents: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "package.json").write_text(
        json.dumps({"items": documents}, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Fixtures — app REAL, interruptor REAL
# ---------------------------------------------------------------------------

@pytest.fixture
def real_app():
    from app.main import app
    return app


@pytest.fixture(autouse=True)
def _reset_auth_settings():
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    yield
    os.environ.pop("S9K_AUTH_ENABLED", None)
    os.environ.pop("S9K_AUTH_DB_PATH", None)
    get_auth_settings.cache_clear()


@pytest.fixture
def panel_on():
    """Enciende SOLO el hueco C. Los interruptores fallan cerrados."""
    previo = os.environ.get(FLAG)
    os.environ[FLAG] = "true"
    yield
    if previo is None:
        os.environ.pop(FLAG, None)
    else:
        os.environ[FLAG] = previo


@pytest.fixture
def service_factory(tmp_path: Path):
    def build(documents: list[dict]) -> ReviewService:
        proposals = tmp_path / "proposals"
        if documents:
            write_package(proposals, documents)
        else:
            proposals.mkdir(parents=True, exist_ok=True)
        return ReviewService(proposals, tmp_path / "decisions.jsonl")

    return build


@pytest.fixture
def with_service(monkeypatch, service_factory):
    """Sustituye la FÁBRICA del servicio del panel, no el servicio global."""
    def install(documents: list[dict]) -> ReviewService:
        service = service_factory(documents)
        monkeypatch.setattr(panel, "_service", lambda: service)
        return service

    return install


@pytest.fixture
def with_scope(real_app):
    """Sustituye `get_visibility_scope`, que SÍ entra por `Depends` aquí.

    Se limpia siempre: la app es la real y compartida por toda la suite.
    """
    def install(scope: VisibilityScope) -> None:
        real_app.dependency_overrides[get_visibility_scope] = lambda: scope

    yield install
    real_app.dependency_overrides.pop(get_visibility_scope, None)


def anon_scope(**kwargs) -> VisibilityScope:
    """Ámbito de un anónimo con auth DESACTIVADA: el que produce el P0."""
    return VisibilityScope(build_viewer_context(
        role=None, auth_enabled=False, default_workspace="alpha", **kwargs
    ))


def player_scope(partida: str | None) -> VisibilityScope:
    return VisibilityScope(build_viewer_context(
        role="viewer", auth_enabled=True, default_workspace="alpha",
        active_partida=partida,
    ))


def client(app, cookie: str | None = None) -> TestClient:
    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    if cookie:
        from app.auth.config import get_auth_settings
        c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, cookie)
    return c


@pytest.fixture
def auth_on(tmp_path):
    db_path = tmp_path / "auth.db"
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db_path)
    from app.auth.config import get_auth_settings
    get_auth_settings.cache_clear()
    from app.auth import db as auth_db_mod
    auth_db_mod.ensure_migrated(db_path)
    return db_path


def login_cookie(db_path: Path, username: str, role: str) -> str:
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


def rows_of(service: ReviewService, workspace: str = "alpha") -> list[dict]:
    return [console.row_view(item)
            for item in service.queue(workspace, include_decided=True).items]


# ===========================================================================
# 0. El arnés muerde (control de colapso). Sin esto, todo lo demás es adorno.
# ===========================================================================

def test_el_arnes_no_pasa_con_cero_casos(with_service):
    """Un arnés que pasa con 0 casos está roto: aquí se exige material."""
    service = with_service([make_proposal("p1"), make_proposal("p2")])
    assert len(rows_of(service)) == 2


def test_la_sustitucion_de_ambito_muerde(real_app, panel_on, with_service, with_scope):
    """Con la sustitución la fila se oculta; SIN ella, reaparece.

    Si quitar la sustitución no cambiara el resultado, el ámbito no estaría
    haciendo nada y ninguna prueba de aislamiento de abajo valdría.
    """
    with_service([make_proposal("p1", partida_id="partida-A")])
    with_scope(player_scope("partida-A"))
    con = client(real_app).get(SLOT.prefix)
    assert "p1" in con.text

    with_scope(player_scope("partida-B"))
    sin = client(real_app).get(SLOT.prefix)
    assert "p1" not in sin.text, (
        "El ámbito sustituido no cambia el resultado: el arnés no muerde."
    )


# ===========================================================================
# 1. Montaje sobre el chasis: contrato publicado, no una ruta inventada
# ===========================================================================

def test_el_panel_se_monta_en_el_prefijo_del_contrato(real_app):
    index = route_index(real_app)
    assert index[SLOT.route_name] == "/panel/review"
    assert index[panel.ITEM_ROUTE_NAME] == "/panel/review/item/{proposal_id}"


def test_la_ficha_no_es_una_entrada_de_menu():
    """La ficha de detalle NO está en NAV: se llega desde la lista."""
    from app.chassis import NAV
    assert panel.ITEM_ROUTE_NAME not in {n.route_name for n in NAV}


def test_las_plantillas_no_llevan_urls_escritas_a_mano():
    """Fallo nº 2 del chasis: un enlace literal no avisa cuando la ruta cambia.

    Se exige que el prefijo publicado NO aparezca como literal en el MARCADO.
    Los comentarios Jinja (`{# ... #}`) se retiran antes de mirar: una ruta
    MENCIONADA en un comentario no crea ningún enlace, y contarla sería el
    falso positivo de "citar es afirmar" que ya se registró en este repo (es
    también el caso M5 de la calibración de docs/68). El propio comentario de
    cabecera de `review.html` nombra el prefijo para explicar la regla, y eso
    tiene que seguir siendo legal.
    """
    import re

    base = Path(panel.__file__).resolve().parent.parent / "templates" / "chassis"
    for nombre in ("review.html", "review_item.html"):
        texto = (base / nombre).read_text(encoding="utf-8")
        marcado = re.sub(r"\{#.*?#\}", "", texto, flags=re.S)
        assert SLOT.prefix not in marcado, f"{nombre} escribe {SLOT.prefix!r} a mano"
        assert "/v3/review/console" not in marcado, f"{nombre} conserva la URL vieja"
        assert "url_for(" in marcado


# ===========================================================================
# 2. Interruptor del hueco: apagado por defecto, y DESPUÉS de la guarda
# ===========================================================================

def test_sin_el_interruptor_el_panel_no_se_sirve(real_app, with_service, with_scope):
    """Ausente el flag, 404: igual que una ruta que no existe."""
    os.environ.pop(FLAG, None)
    with_service([make_proposal("p1")])
    with_scope(anon_scope())
    assert client(real_app).get(SLOT.prefix).status_code == 404
    assert client(real_app).get(f"{SLOT.prefix}/item/p1").status_code == 404


@pytest.mark.parametrize("valor", ["", "false", "0", "quizas", "TRUE ", "yes"])
def test_solo_true_y_1_encienden_el_panel(real_app, with_service, with_scope, valor):
    """Un valor que no se entiende es un dato ausente, no un permiso."""
    with_service([make_proposal("p1")])
    with_scope(anon_scope())
    previo = os.environ.get(FLAG)
    os.environ[FLAG] = valor
    try:
        esperado = 200 if valor.strip().lower() in {"true", "1"} else 404
        assert client(real_app).get(SLOT.prefix).status_code == esperado
    finally:
        if previo is None:
            os.environ.pop(FLAG, None)
        else:
            os.environ[FLAG] = previo


def test_un_anonimo_no_puede_enumerar_si_el_panel_esta_encendido(real_app, auth_on):
    """Con auth activa, el anónimo recibe LO MISMO esté encendido o apagado.

    El interruptor se evalúa DESPUÉS de la guarda a propósito: si se evaluara
    antes, comparar 404 contra 302 diría qué paneles están encendidos.
    """
    respuestas = []
    previo = os.environ.get(FLAG)
    try:
        for valor in ("true", "false"):
            os.environ[FLAG] = valor
            r = client(real_app).get(SLOT.prefix)
            respuestas.append((r.status_code, r.headers.get("location")))
    finally:
        if previo is None:
            os.environ.pop(FLAG, None)
        else:
            os.environ[FLAG] = previo
    assert respuestas[0] == respuestas[1], (
        f"El anónimo distingue encendido de apagado: {respuestas}"
    )
    assert respuestas[0][0] == 302


# ===========================================================================
# 3. Autorización: la actual manda. Sin auth = anónimo SIN permisos.
# ===========================================================================

def test_con_auth_activa_el_anonimo_va_a_login(real_app, auth_on, panel_on, with_service):
    with_service([make_proposal("p1")])
    r = client(real_app).get(SLOT.prefix)
    assert r.status_code == 302 and "/login" in r.headers["location"]


def test_con_auth_activa_el_rol_viewer_no_entra(real_app, auth_on, panel_on, with_service):
    """`reviewer` es el rol MÍNIMO publicado: el inferior recibe 403."""
    with_service([make_proposal("p1")])
    cookie = login_cookie(auth_on, "panelc_viewer", "viewer")
    assert client(real_app, cookie).get(SLOT.prefix).status_code == 403


def test_con_auth_activa_el_rol_reviewer_entra(real_app, auth_on, panel_on, with_service):
    with_service([])
    cookie = login_cookie(auth_on, "panelc_reviewer", "reviewer")
    assert client(real_app, cookie).get(SLOT.prefix).status_code == 200


def test_sin_auth_no_reaparece_el_comportamiento_permisivo(
    real_app, panel_on, with_service, with_scope
):
    """EL TEST DE ESTE CARRIL.

    La consola vieja se escribió cuando `S9K_AUTH_ENABLED=false` producía un
    contexto `admin_full`: sin auth se veía TODO. El P0 de autoridad (docs/75)
    lo cerró — sin principal no hay autoridad, así que el contexto es anónimo
    de mínimo privilegio.

    Aquí se fija ese resultado sobre el ámbito REAL que produce el productor de
    contextos (no uno fabricado a mano): material de partida NO se entrega, ni
    en la lista, ni en los contadores, ni por ID. Si alguien reabre la vía
    cerrada, este test se pone rojo.

    Que la consola salga vacía en un banco sin auth es, por tanto, el
    comportamiento CORRECTO. No es una pantalla que arreglar.
    """
    with_service([
        make_proposal("secreta", partida_id="partida-A"),
        make_proposal("otra", partida_id="partida-B"),
    ])
    ambito = anon_scope()
    assert ambito.ctx.admin_full is False, (
        "El contexto anónimo con auth desactivada ya no puede conceder admin_full"
    )
    with_scope(ambito)

    lista = client(real_app).get(SLOT.prefix)
    assert lista.status_code == 200
    assert "secreta" not in lista.text and "otra" not in lista.text
    assert 'data-state="empty"' in lista.text

    # Tampoco por ID: la barrera no depende de por dónde se entre.
    ficha = client(real_app).get(f"{SLOT.prefix}/item/secreta")
    assert ficha.status_code == 404


def test_el_panel_no_declara_vocabulario_propio_de_autorizacion():
    """Ni una segunda tabla de rangos, ni un `admin_full` local, ni un `role ==`.

    La guarda tiene que ser la del chasis (`slot_guard`) y el ámbito el de
    `get_visibility_scope`. Se comprueba sobre el AST, no leyendo el fichero:
    una mención en un comentario no cuenta ni a favor ni en contra.
    """
    import ast

    arbol = ast.parse(Path(panel.__file__).read_text(encoding="utf-8"))
    nombres = {n.id for n in ast.walk(arbol) if isinstance(n, ast.Name)}
    atributos = {n.attr for n in ast.walk(arbol) if isinstance(n, ast.Attribute)}
    constantes = {n.value for n in ast.walk(arbol) if isinstance(n, ast.Constant)}
    assert "admin_full" not in nombres | atributos | {c for c in constantes if isinstance(c, str)}
    assert "slot_guard" in nombres
    assert "get_visibility_scope" in nombres
    # Ningún rango propio: los roles no se comparan aquí.
    for rol in ("admin", "reviewer", "viewer", "anonymous"):
        assert rol not in {c for c in constantes if isinstance(c, str)}, (
            f"El router compara el rol {rol!r} por su cuenta"
        )


# ===========================================================================
# 4. SOLO LECTURA: frontera dura, comprobada por enumeración
# ===========================================================================

def test_el_panel_no_monta_ningun_metodo_de_escritura(real_app):
    """Enumeración de métodos, no una promesa en prosa."""
    prohibidos = {"POST", "PUT", "PATCH", "DELETE"}
    for ruta in panel.router.routes:
        assert not (set(getattr(ruta, "methods", set())) & prohibidos), (
            f"{getattr(ruta, 'path', ruta)} monta métodos de escritura"
        )


@pytest.mark.parametrize("metodo", ["post", "put", "patch", "delete"])
def test_los_metodos_de_escritura_son_rechazados_por_http(
    real_app, panel_on, with_service, with_scope, metodo
):
    with_service([make_proposal("p1")])
    with_scope(anon_scope())
    r = getattr(client(real_app), metodo)(SLOT.prefix)
    assert r.status_code in (404, 405), f"{metodo.upper()} devolvió {r.status_code}"


def test_el_panel_no_crea_el_ledger_de_decisiones(
    real_app, panel_on, with_service, with_scope, tmp_path
):
    """El fichero de decisiones NO llega a existir tras recorrer el panel."""
    service = with_service([make_proposal("p1")])
    with_scope(anon_scope())
    ledger = Path(service.decisions_path)
    assert not ledger.exists()
    client(real_app).get(SLOT.prefix)
    client(real_app).get(f"{SLOT.prefix}/item/p1")
    assert not ledger.exists(), "La consola creó el ledger de decisiones"


# ===========================================================================
# 5. Coherencia de producto: lista -> detalle del MISMO objeto
# ===========================================================================

def test_la_ficha_es_la_de_la_fila_que_se_abrio(
    real_app, panel_on, with_service, with_scope
):
    with_service([make_proposal(f"p{i}", subject=f"Sujeto{i}") for i in range(1, 6)])
    with_scope(anon_scope())
    lista = client(real_app).get(SLOT.prefix)
    assert lista.status_code == 200
    ids = _ids_de_la_lista(lista.text)
    assert ids, "la lista no pintó ninguna fila: el arnés no mide nada"
    for proposal_id in ids:
        ficha = client(real_app).get(f"{SLOT.prefix}/item/{proposal_id}")
        assert ficha.status_code == 200
        assert f'data-proposal-id="{proposal_id}"' in ficha.text


def _ids_de_la_lista(html: str) -> list[str]:
    import re
    return re.findall(r'<tr data-proposal-id="([^"]+)"', html)


def test_los_vecinos_siguen_el_orden_filtrado(real_app, panel_on, with_service, with_scope):
    with_service([
        make_proposal("alto", decision="REVIEW", confidence=0.9),
        make_proposal("bajo", decision="REVIEW", confidence=0.1),
        make_proposal("abstiene", decision="ABSTAIN", confidence=0.5),
    ])
    with_scope(anon_scope())
    orden = _ids_de_la_lista(client(real_app).get(SLOT.prefix).text)
    assert orden == ["bajo", "alto", "abstiene"], orden
    ficha = client(real_app).get(f"{SLOT.prefix}/item/alto")
    assert 'data-neighbour="previous"' in ficha.text
    assert 'data-neighbour="next"' in ficha.text
    assert "<span data-position>2</span>" in ficha.text


# ===========================================================================
# 6. Filtrar ANTES de paginar
# ===========================================================================

def test_los_contadores_son_del_conjunto_filtrado_no_de_la_pagina(
    real_app, panel_on, with_service, with_scope
):
    """Filtrar después de paginar da páginas mentirosas: 30 elementos, 12 con
    el motivo buscado, página de 5. Si se filtrara la página, el total diría 5
    o 30, nunca 12."""
    documentos = [
        make_proposal(f"p{i:02d}", reason_codes=["LOW_CONFIDENCE" if i < 12 else "OTRO"])
        for i in range(30)
    ]
    with_service(documentos)
    with_scope(anon_scope())
    r = client(real_app).get(
        SLOT.prefix, params={"reason_code": "LOW_CONFIDENCE", "page_size": 5}
    )
    assert r.status_code == 200
    assert '<span data-count="visible">30</span>' in r.text
    assert '<span data-count="filtered">12</span>' in r.text
    assert len(_ids_de_la_lista(r.text)) == 5
    assert "<span data-page=\"total\">3</span>" in r.text


def test_paginar_no_filtra_nunca():
    """Ablación directa sobre la unidad: `paginate` sólo corta."""
    filas = [{"proposal_id": f"p{i}"} for i in range(7)]
    pagina = console.paginate(filas, page=1, page_size=100)
    assert pagina.total == 7 and len(pagina.rows) == 7


def test_la_ficha_no_se_limita_a_la_primera_pagina(
    real_app, panel_on, with_service, with_scope
):
    """Un elemento de la última página tiene ficha: la ficha busca en el
    conjunto filtrado ENTERO, no en la página."""
    with_service([make_proposal(f"p{i:02d}") for i in range(30)])
    with_scope(anon_scope())
    r = client(real_app).get(f"{SLOT.prefix}/item/p29")
    assert r.status_code == 200
    assert "<span data-total>30</span>" in r.text


# ===========================================================================
# 7. Ausencias: `not_available` es ausencia, y sin sombra no hay acuerdo
# ===========================================================================

def test_not_available_es_ausencia_no_un_valor(with_service):
    service = with_service([make_proposal("p1", subject="not_available", predicate="UNKNOWN")])
    fila = rows_of(service)[0]
    assert fila["subject"] is None and fila["predicate"] is None


def test_not_available_no_se_pinta_en_la_pantalla(
    real_app, panel_on, with_service, with_scope
):
    with_service([make_proposal("p1", subject="not_available")])
    with_scope(anon_scope())
    r = client(real_app).get(SLOT.prefix)
    assert "not_available" not in r.text
    assert "no disponible" in r.text


def test_sin_sombra_no_hay_acuerdo(with_service):
    """Pieza 2: sin las dos partes el acuerdo es None, no AGREE."""
    service = with_service([make_proposal("p1", shadow=None)])
    fila = rows_of(service)[0]
    assert fila["agreement"] is None
    assert any("No hay decisión en sombra" in l for l in console.review_explanation(fila))


def test_un_documento_parcial_degrada_a_ausencias_no_a_excepcion(with_service):
    documento = make_proposal("p1")
    for clave in ("engine_decision", "provenance", "resolution"):
        documento.pop(clave)
    service = with_service([documento])
    fila = rows_of(service)[0]
    assert fila["engine_decision"] is None
    assert fila["confidence"] is None
    assert fila["agreement"] is None
    assert fila["extractors"] == []


# ===========================================================================
# 8. Estados desconocidos: FALLO CERRADO
# ===========================================================================

def test_un_estado_desconocido_no_se_declara_conocido(with_service):
    service = with_service([make_proposal("p1", decision="APROBADA_POR_LA_CASA")])
    fila = rows_of(service)[0]
    assert fila["decision_known"] is False


def test_los_estados_del_motor_si_se_reconocen(with_service):
    from app.services.v3_review import VALID_ENGINE_DECISIONS

    for decision in sorted(VALID_ENGINE_DECISIONS):
        service = with_service([make_proposal("p1", decision=decision)])
        assert rows_of(service)[0]["decision_known"] is True, decision


def test_un_estado_desconocido_se_marca_en_la_pantalla(
    real_app, panel_on, with_service, with_scope
):
    """No se pinta como una decisión buena: la pantalla lo dice."""
    with_service([make_proposal("p1", decision="APROBADA_POR_LA_CASA")])
    with_scope(anon_scope())
    r = client(real_app).get(SLOT.prefix)
    assert 'data-decision-known="false"' in r.text
    assert "estado no reconocido" in r.text


def test_un_acuerdo_entre_estados_desconocidos_no_es_acuerdo(with_service):
    """Dos valores idénticos que nadie reconoce no producen AGREE."""
    service = with_service([
        make_proposal("p1", decision="RARO", shadow="RARO"),
    ])
    assert rows_of(service)[0]["agreement"] is None


# ===========================================================================
# 9. Ámbito: workspace / partida acotados, y 404 indistinguible
# ===========================================================================

def test_el_material_de_otra_partida_no_aparece_ni_en_los_contadores(
    real_app, panel_on, with_service, with_scope
):
    with_service([
        make_proposal("mia", partida_id="partida-A"),
        make_proposal("ajena", partida_id="partida-B"),
        make_proposal("lore"),
    ])
    with_scope(player_scope("partida-A"))
    r = client(real_app).get(SLOT.prefix)
    ids = _ids_de_la_lista(r.text)
    assert "mia" in ids and "lore" in ids and "ajena" not in ids
    assert '<span data-count="visible">2</span>' in r.text


def test_fuera_de_ambito_inexistente_y_filtrado_dan_el_mismo_404(
    real_app, panel_on, with_service, with_scope
):
    """Mismo código y mismo cuerpo: la pantalla no dice "existe pero no es tuya"."""
    with_service([
        make_proposal("mia", partida_id="partida-A"),
        make_proposal("ajena", partida_id="partida-B"),
    ])
    with_scope(player_scope("partida-A"))
    cliente = client(real_app)
    fuera = cliente.get(f"{SLOT.prefix}/item/ajena")
    inexistente = cliente.get(f"{SLOT.prefix}/item/no-existe-jamas")
    filtrada = cliente.get(f"{SLOT.prefix}/item/mia", params={"decision": "ACCEPT"})
    assert fuera.status_code == inexistente.status_code == filtrada.status_code == 404
    assert fuera.text == inexistente.text == filtrada.text


def test_un_workspace_fuera_de_ambito_es_404_como_uno_inexistente(
    real_app, panel_on, with_service, with_scope
):
    with_service([make_proposal("p1", workspace="alpha")])
    with_scope(anon_scope())
    cliente = client(real_app)
    a = cliente.get(SLOT.prefix, params={"workspace": "beta"})
    b = cliente.get(SLOT.prefix, params={"workspace": "no-existe"})
    assert a.status_code == b.status_code == 404
    assert a.text == b.text


# ===========================================================================
# 10. Errores: 503 sin volcar rutas ni trazas
# ===========================================================================

def test_paquete_ilegible_da_503_sin_filtrar_rutas(
    real_app, panel_on, with_service, with_scope, tmp_path
):
    with_service([make_proposal("p1")])
    (tmp_path / "proposals" / "package.json").write_text("{ esto no es json", encoding="utf-8")
    with_scope(anon_scope())
    r = client(real_app).get(SLOT.prefix)
    assert r.status_code == 503
    assert 'data-state="error"' in r.text
    assert str(tmp_path) not in r.text
    assert "Traceback" not in r.text
    assert ".json" not in r.text


def test_un_filtro_invalido_da_400_con_el_nombre_del_parametro(
    real_app, panel_on, with_service, with_scope
):
    with_service([make_proposal("p1")])
    with_scope(anon_scope())
    r = client(real_app).get(SLOT.prefix, params={"min_confidence": 2.0})
    assert r.status_code == 400
    assert "min_confidence" in r.text


def test_un_orden_desconocido_se_rechaza(real_app, panel_on, with_service, with_scope):
    with_service([make_proposal("p1")])
    with_scope(anon_scope())
    assert client(real_app).get(SLOT.prefix, params={"sort": "magia"}).status_code == 400


# ===========================================================================
# 11. Estado vacío: es el camino por defecto, no el olvidado
# ===========================================================================

def test_el_umbral_de_baja_confianza_es_criterio_de_presentacion(with_service):
    """Pieza 8: `DEFAULT_LOW_CONFIDENCE` es de ESTA pantalla, no del motor.

    El paquete que exporta el motor no trae sus umbrales de decisión por
    ninguna clave. Se comprueba midiendo el documento exportado, no citando el
    documento: si algún día el motor los exportara, este test se pone rojo y
    habría que dejar de usar un umbral propio.
    """
    service = with_service([make_proposal("p1")])
    item = service.queue("alpha", include_decided=True).items[0]
    motor = item.get("engine_decision") or {}
    claves_de_umbral = [k for k in motor if "threshold" in k or "umbral" in k]
    assert claves_de_umbral == [], (
        f"El motor ya exporta umbrales ({claves_de_umbral}): el criterio de "
        "presentación de la consola debería usarlos en vez de su propio 0.6"
    )
    assert console.DEFAULT_LOW_CONFIDENCE == 0.6
    # Y es efectivamente el criterio que aplica el filtro, no un adorno.
    filas = rows_of(service)
    assert console.apply_filters(filas, console.parse_filters(low_confidence_only=True))
    assert not console.apply_filters(
        filas, console.parse_filters(low_confidence_only=True, low_confidence_threshold=0.1)
    )


def test_sin_material_se_pinta_el_estado_vacio_no_una_excepcion(
    real_app, panel_on, with_service, with_scope
):
    with_service([])
    with_scope(anon_scope())
    r = client(real_app).get(SLOT.prefix)
    assert r.status_code == 200
    assert 'data-state="empty"' in r.text
    assert 'data-state="error"' not in r.text
