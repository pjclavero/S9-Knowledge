"""B1 (USABLE-V1) · H-03 — la revisión V3 no deja ver ni actuar fuera del workspace concedido.

EL DEFECTO, DEMOSTRADO EN LA AUDITORÍA GLOBAL 2026-10-10 (§9, SEC-02):

    rev1 GET  /api/workspaces                       -> ["leyenda"]
    rev1 POST /v3/review/decide workspace=bench-dev -> 303
    1 fila nueva en `human_decisions`

`services.v3_review._scoped()` devolvía `scope.partida_only()`
(`enforce_workspace=False`) y `record()` / `undo_last()` sólo exigían
`item["workspace"] == workspace`, con `workspace` LEÍDO DEL FORMULARIO. El
cliente elegía su ámbito. Origen: `f6a4f18` (M5a, 2026-08-06), anterior a F-2
(#244), que hizo canónico el workspace del perfil de la bóveda.

QUÉ MIDE ESTE FICHERO, con la app REAL (`app.main.app`), autenticación REAL
(auth.db temporal, sesiones y CSRF de verdad) y DOS workspaces con propuestas
en ambos:

- `TestDosRevisores`: dos revisores con concesiones DISTINTAS (rev_a → leyenda,
  rev_b → bench-dev) y un admin. Hoy el productor de contexto da a todo
  principal el MISMO workspace (singleton del despliegue, F-2); para tener dos
  concesiones distintas se sustituye SÓLO la dependencia
  `get_visibility_scope`, y el contexto lo sigue produciendo el productor único
  `build_viewer_context` (no se fabrica un `ViewerContext` a mano). Es el modelo
  «usuario → workspace» que el aislamiento tiene que soportar el día que exista.
- `TestProductorReal`: SIN sustituir nada. El workspace canónico lo resuelve
  `autoridad_workspace` (aquí, fallback de entorno `leyenda`) y un revisor
  autenticado intenta actuar sobre `bench-dev`: el caso literal de la auditoría.

Cada negativo cuenta las filas de `human_decisions` ANTES y DESPUÉS: el rojo de
la mutación tiene que ser el 303 / la fila nueva, no un import ni un fixture.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.authz.context import build_viewer_context
from app.authz.dependencies import get_visibility_scope
from app.authz.scope import VisibilityScope
from app.chassis import FEATURE_SLOTS, slot_flag_env
from app.routers import chassis_review as panel_router
from app.routers import v3_review as v3_router
from app.services.v3_review import ReviewService

WS_A = "leyenda"      # el workspace canónico de la suite (conftest: S9K_DEFAULT_WORKSPACE)
WS_B = "bench-dev"    # el corpus ajeno de la auditoría
WS_INEXISTENTE = "no-existe-en-ningun-sitio"
SLOT_C = next(s for s in FEATURE_SLOTS if s.key == "C")
FLAG_C = slot_flag_env(SLOT_C)
PASSWORD = "B1H03_Test_1234567890!"
#: Marca que SÓLO aparece en el material de B: si sale en una respuesta de rev_a,
#: B se ha filtrado, se llame como se llame la ruta.
MARCA_B = "MarcaSecretaDeBenchDev"
MARCA_P2 = "MarcaDeLaPartidaDos"
PARTIDA_1 = "partida:uno"
PARTIDA_2 = "partida:dos"
#: Mismo nombre que el concedido salvo la caja: la comparación es LITERAL.
WS_MAYUSCULAS = "Leyenda"

EPISODE = "Ariadna protege la ciudad de Bruma durante el invierno de sangre."
LITERAL = "protege la ciudad de Bruma"


def _propuesta(proposal_id: str, workspace: str, subject: str = "Ariadna",
               partida_id: str | None = None) -> dict:
    start = EPISODE.index(LITERAL)
    documento = {
        "proposal_id": proposal_id,
        "workspace": workspace,
        "source_id": f"source-{workspace}",
        "episode_id": f"episode-{proposal_id}",
        "episode_text": EPISODE,
        "evidence": {"start": start, "end": start + len(LITERAL), "literal_text": LITERAL},
        "claim_id": f"claim-{proposal_id}",
        "proposal": {
            "subject": subject, "predicate": "PROTECTS", "object": "Bruma",
            "direction": "SUBJECT_TO_OBJECT", "negated": False, "negation_kind": "NONE",
            "scope": "durante el invierno", "epistemic_status": "ASSERTED",
            "temporal_status": "PRESENT",
        },
        "engine_decision": {
            "decision": "REVIEW", "effective_decision": "REVIEW", "shadow_decision": None,
            "reason_codes": ["AMBIGUOUS_PREDICATE"], "confidence": 0.42,
            "provider": "local", "model": "modelo-x",
            "shadow_findings": [], "ignored_findings": [],
            "effective_findings": ["AMBIGUOUS_PREDICATE"],
            "would_emit_operations": False, "operation_kinds": [],
        },
        "resolution": {"subject": "entity-ariadna", "object": "entity-bruma"},
        "alternatives": {"predicates": [], "directions": []},
        "provenance": {
            "extractors": ["semantic-local"], "providers": ["local"],
            "models": ["modelo-x"], "independent_families": ["rules"],
        },
        "ontology_version": "bruma-v1", "engine_version": "knowledge-v3-test",
        "prompt_version": "p1", "profile_version": "perfil-1",
    }
    if partida_id:
        documento["partida_id"] = partida_id
    return documento


# ---------------------------------------------------------------------------
# Entorno: app real, auth real, dos workspaces con propuestas en ambos
# ---------------------------------------------------------------------------

@pytest.fixture
def entorno(tmp_path, monkeypatch):
    from app.auth import db as auth_db
    from app.auth.config import get_auth_settings
    from app.auth.passwords import hash_password
    from app.config import get_settings

    db_path = tmp_path / "auth.db"
    for clave, valor in {
        "S9K_AUTH_ENABLED": "true",
        "S9K_AUTH_DB_PATH": str(db_path),
        "S9K_DEFAULT_WORKSPACE": WS_A,
        FLAG_C: "true",
    }.items():
        monkeypatch.setenv(clave, valor)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    auth_db.ensure_migrated(db_path)

    proposals = tmp_path / "proposals"
    proposals.mkdir()
    (proposals / "package.json").write_text(json.dumps({"items": [
        _propuesta("pa-1", WS_A),
        _propuesta("pa-2", WS_A),
        _propuesta("pb-1", WS_B, subject=MARCA_B),
        _propuesta("pb-2", WS_B, subject=MARCA_B),
        # Dos partidas DENTRO del workspace concedido (control de partida).
        _propuesta("pa-p1", WS_A, partida_id=PARTIDA_1),
        _propuesta("pa-p2", WS_A, subject=MARCA_P2, partida_id=PARTIDA_2),
        # Un corpus cuya etiqueta sólo difiere en MAYÚSCULAS del concedido.
        _propuesta("pm-1", WS_MAYUSCULAS, subject=MARCA_B),
    ]}, ensure_ascii=False), encoding="utf-8")
    service = ReviewService(proposals, tmp_path / "decisions.jsonl")
    # B ya tiene una decisión ACTIVA (para que `undo` tenga algo que deshacer
    # allí) y un candidato de glosario (para que `glossary-candidates` tenga
    # algo que filtrar). Se siembra por el camino INTERNO (sin ámbito).
    sembrada = next(i for i in service.queue(WS_B).items if i["proposal_id"] == "pb-2")
    service.record(
        proposal_id="pb-2", workspace=WS_B, reviewer="semilla", human_decision="CORRECT",
        request_id="semilla-b", correction={"subject_alias": MARCA_B + "Alias"},
        expected_proposal_hash=sembrada["proposal_hash"],
    )
    # La partida p2 de A también tiene una decisión ACTIVA: un revisor con la
    # partida p1 activa no puede deshacerla.
    sembrada_p2 = next(
        i for i in service.queue(WS_A).items if i["proposal_id"] == "pa-p2"
    )
    service.record(
        proposal_id="pa-p2", workspace=WS_A, reviewer="semilla", human_decision="APPROVE",
        request_id="semilla-p2", expected_proposal_hash=sembrada_p2["proposal_hash"],
    )
    monkeypatch.setattr(v3_router, "_service", lambda: service)
    monkeypatch.setattr(panel_router, "_service", lambda: service)

    usuarios = {}
    with auth_db.get_conn(db_path) as conn:
        for nombre, rol in (("rev_a", "reviewer"), ("rev_b", "reviewer"), ("jefa", "admin")):
            user = auth_db.create_user(
                conn, username=nombre, display_name=nombre,
                password_hash=hash_password(PASSWORD), role=rol,
            )
            auth_db.update_user(conn, user.id, must_change_password=False)
            usuarios[nombre] = auth_db.get_user_by_id(conn, user.id)

    from app.main import app

    yield {"app": app, "service": service, "db": db_path, "usuarios": usuarios}

    app.dependency_overrides.pop(get_visibility_scope, None)
    get_auth_settings.cache_clear()
    get_settings.cache_clear()


def _cliente(entorno, nombre: str) -> TestClient:
    from app.auth import db as auth_db
    from app.auth.config import get_auth_settings
    from app.auth.sessions import create_session

    with auth_db.get_conn(entorno["db"]) as conn:
        token, _ = create_session(conn, entorno["usuarios"][nombre])
    c = TestClient(entorno["app"], raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, token)
    return c


def _csrf(cliente: TestClient, workspace: str) -> str:
    page = cliente.get(f"/v3/review?workspace={workspace}")
    assert page.status_code == 200, (page.status_code, page.text[:300])
    m = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert m, "la cola propia no pinta csrf_token"
    return m.group(1)


def _filas(entorno) -> int:
    """Filas de `human_decisions`, leídas del almacén real."""
    return len(entorno["service"].store.decisions())


def _hash(entorno, workspace: str, proposal_id: str) -> str:
    return next(
        i for i in entorno["service"].queue(workspace, include_decided=True).items
        if i["proposal_id"] == proposal_id
    )["proposal_hash"]


def _decide(cliente, csrf, *, workspace, proposal_id, proposal_hash, request_id):
    return cliente.post("/v3/review/decide", data={
        "workspace": workspace, "proposal_id": proposal_id,
        "human_decision": "APPROVE", "request_id": request_id,
        "expected_proposal_hash": proposal_hash, "csrf_token": csrf,
    })


def _undo(cliente, csrf, *, workspace, request_id):
    return cliente.post("/v3/review/undo", data={
        "workspace": workspace, "request_id": request_id, "csrf_token": csrf,
    })


@pytest.fixture
def concesiones_distintas(entorno):
    """rev_a → {leyenda}, rev_b → {bench-dev}, admin → lo que el productor dé.

    Sustituye SÓLO `get_visibility_scope` y deja que el contexto lo construya
    el productor único con el rol y el principal REALES de la petición.
    """
    mapa = {"rev_a": WS_A, "rev_b": WS_B}

    def _ambito(request: Request) -> VisibilityScope:
        user = request.state.user
        return VisibilityScope(build_viewer_context(
            role=user.role, auth_enabled=True,
            default_workspace=mapa.get(user.username, WS_A),
        ))

    entorno["app"].dependency_overrides[get_visibility_scope] = _ambito
    return entorno


# ---------------------------------------------------------------------------
# Dos revisores, concesiones distintas
# ---------------------------------------------------------------------------

class TestDosRevisores:
    # -- controles POSITIVOS: si esto falla, los negativos no prueban nada ----
    def test_positivo_rev_a_decide_y_deshace_en_su_workspace(self, concesiones_distintas):
        e = concesiones_distintas
        c = _cliente(e, "rev_a")
        csrf = _csrf(c, WS_A)
        antes = _filas(e)
        r = _decide(c, csrf, workspace=WS_A, proposal_id="pa-1",
                    proposal_hash=_hash(e, WS_A, "pa-1"), request_id="pos-a-1")
        assert r.status_code == 303, (r.status_code, r.text[:300])
        assert _filas(e) == antes + 1
        r = _undo(c, csrf, workspace=WS_A, request_id="pos-a-undo")
        assert r.status_code == 303, (r.status_code, r.text[:300])
        assert _filas(e) == antes + 2

    def test_positivo_rev_b_decide_en_su_workspace(self, concesiones_distintas):
        e = concesiones_distintas
        c = _cliente(e, "rev_b")
        csrf = _csrf(c, WS_B)
        antes = _filas(e)
        r = _decide(c, csrf, workspace=WS_B, proposal_id="pb-1",
                    proposal_hash=_hash(e, WS_B, "pb-1"), request_id="pos-b-1")
        assert r.status_code == 303, (r.status_code, r.text[:300])
        assert _filas(e) == antes + 1

    def test_positivo_admin_decide_sobre_b(self, concesiones_distintas):
        e = concesiones_distintas
        c = _cliente(e, "jefa")
        csrf = _csrf(c, WS_B)
        antes = _filas(e)
        r = _decide(c, csrf, workspace=WS_B, proposal_id="pb-1",
                    proposal_hash=_hash(e, WS_B, "pb-1"), request_id="pos-admin-b")
        assert r.status_code == 303, (r.status_code, r.text[:300])
        assert _filas(e) == antes + 1

    def test_positivo_admin_ve_los_dos_workspaces(self, concesiones_distintas):
        c = _cliente(concesiones_distintas, "jefa")
        for ws in (WS_A, WS_B):
            assert c.get(f"/v3/review?workspace={ws}").status_code == 200
        assert c.get("/panel/review/item/pb-1", params={"workspace": WS_B}).status_code == 200

    # -- controles NEGATIVOS ---------------------------------------------------
    def test_negativo_rev_a_decide_sobre_b_no_registra_nada(self, concesiones_distintas):
        e = concesiones_distintas
        c = _cliente(e, "rev_a")
        csrf = _csrf(c, WS_A)
        antes = _filas(e)
        r = _decide(c, csrf, workspace=WS_B, proposal_id="pb-1",
                    proposal_hash=_hash(e, WS_B, "pb-1"), request_id="neg-a-b")
        assert r.status_code in (403, 404), (
            f"rev_a (concesión sólo en {WS_A}) decidió sobre {WS_B}: "
            f"HTTP {r.status_code}"
        )
        assert _filas(e) == antes, "fila nueva en human_decisions desde fuera de ámbito"

    def test_negativo_rev_a_con_su_workspace_y_proposal_id_de_b(self, concesiones_distintas):
        """El workspace del formulario es el propio; el `proposal_id`, ajeno."""
        e = concesiones_distintas
        c = _cliente(e, "rev_a")
        csrf = _csrf(c, WS_A)
        antes = _filas(e)
        r = _decide(c, csrf, workspace=WS_A, proposal_id="pb-1",
                    proposal_hash=_hash(e, WS_B, "pb-1"), request_id="neg-a-pid-b")
        assert r.status_code != 303
        assert _filas(e) == antes

    def test_negativo_rev_a_deshace_en_b_no_registra_nada(self, concesiones_distintas):
        e = concesiones_distintas
        c = _cliente(e, "rev_a")
        csrf = _csrf(c, WS_A)
        antes = _filas(e)
        r = _undo(c, csrf, workspace=WS_B, request_id="neg-undo-a-b")
        assert r.status_code in (403, 404), (
            f"rev_a deshizo una decisión de {WS_B}: HTTP {r.status_code}"
        )
        assert _filas(e) == antes, "fila nueva en human_decisions desde fuera de ámbito"

    def test_negativo_get_cola_de_b_no_muestra_b(self, concesiones_distintas):
        c = _cliente(concesiones_distintas, "rev_a")
        r = c.get(f"/v3/review?workspace={WS_B}")
        assert r.status_code == 404, r.status_code
        assert MARCA_B not in r.text
        # Y la cola propia no lista B entre los workspaces elegibles.
        propia = c.get(f"/v3/review?workspace={WS_A}")
        assert propia.status_code == 200
        assert MARCA_B not in propia.text
        assert f'value="{WS_B}"' not in propia.text

    def test_negativo_panel_item_de_b_da_404(self, concesiones_distintas):
        c = _cliente(concesiones_distintas, "rev_a")
        for params in ({"workspace": WS_B}, {}):
            r = c.get("/panel/review/item/pb-1", params=params)
            assert r.status_code == 404, (params, r.status_code)
            assert MARCA_B not in r.text

    def test_negativo_panel_lista_de_b(self, concesiones_distintas):
        c = _cliente(concesiones_distintas, "rev_a")
        r = c.get("/panel/review/", params={"workspace": WS_B})
        assert r.status_code == 404, r.status_code
        assert MARCA_B not in r.text
        propia = c.get("/panel/review/")
        assert propia.status_code == 200
        assert MARCA_B not in propia.text

    def test_negativo_glossary_candidates_de_b_no_visibles(self, concesiones_distintas):
        e = concesiones_distintas
        # El candidato de B EXISTE (control: el admin lo ve).
        admin = _cliente(e, "jefa").get(f"/v3/review/glossary-candidates?workspace={WS_B}")
        assert admin.status_code == 200 and MARCA_B + "Alias" in admin.text
        r = _cliente(e, "rev_a").get(f"/v3/review/glossary-candidates?workspace={WS_B}")
        assert r.status_code == 404, r.status_code
        assert MARCA_B not in r.text

    def test_negativo_workspace_de_formulario_inexistente(self, concesiones_distintas):
        e = concesiones_distintas
        c = _cliente(e, "rev_a")
        csrf = _csrf(c, WS_A)
        antes = _filas(e)
        r = _decide(c, csrf, workspace=WS_INEXISTENTE, proposal_id="pa-1",
                    proposal_hash=_hash(e, WS_A, "pa-1"), request_id="neg-inexistente")
        assert r.status_code in (403, 404), r.status_code
        assert _undo(c, csrf, workspace=WS_INEXISTENTE,
                     request_id="neg-inexistente-undo").status_code in (403, 404)
        assert c.get(f"/v3/review?workspace={WS_INEXISTENTE}").status_code == 404
        assert _filas(e) == antes


# ---------------------------------------------------------------------------
# Productor REAL, sin sustituir nada (el caso literal de la auditoría)
# ---------------------------------------------------------------------------

class TestProductorReal:
    def test_precondicion_el_workspace_canonico_es_a(self, entorno):
        from app.authz import autoridad_workspace

        assert autoridad_workspace.resolver_por_peticion().valor == WS_A

    def test_positivo_revisor_actua_en_el_canonico(self, entorno):
        c = _cliente(entorno, "rev_a")
        csrf = _csrf(c, WS_A)
        antes = _filas(entorno)
        r = _decide(c, csrf, workspace=WS_A, proposal_id="pa-2",
                    proposal_hash=_hash(entorno, WS_A, "pa-2"), request_id="real-pos")
        assert r.status_code == 303, (r.status_code, r.text[:300])
        assert _filas(entorno) == antes + 1

    def test_negativo_revisor_no_decide_ni_deshace_en_otro_corpus(self, entorno):
        c = _cliente(entorno, "rev_a")
        csrf = _csrf(c, WS_A)
        antes = _filas(entorno)
        r = _decide(c, csrf, workspace=WS_B, proposal_id="pb-1",
                    proposal_hash=_hash(entorno, WS_B, "pb-1"), request_id="real-neg")
        assert r.status_code in (403, 404), f"decide sobre {WS_B}: HTTP {r.status_code}"
        r = _undo(c, csrf, workspace=WS_B, request_id="real-neg-undo")
        assert r.status_code in (403, 404), f"undo sobre {WS_B}: HTTP {r.status_code}"
        assert _filas(entorno) == antes
        assert c.get(f"/v3/review?workspace={WS_B}").status_code == 404

    def test_admin_real_sigue_viendo_otro_corpus(self, entorno):
        c = _cliente(entorno, "jefa")
        assert c.get(f"/v3/review?workspace={WS_B}").status_code == 200


# ---------------------------------------------------------------------------
# El lore anónimo sigue denegado (docs/81): auth off, sin principal
# ---------------------------------------------------------------------------

def test_anonimo_con_auth_off_sigue_sin_ver_nada(entorno, monkeypatch):
    from app.auth.config import get_auth_settings

    monkeypatch.setenv("S9K_AUTH_ENABLED", "false")
    get_auth_settings.cache_clear()
    c = TestClient(entorno["app"], raise_server_exceptions=False, follow_redirects=False)
    for ruta in (f"/v3/review?workspace={WS_A}", f"/v3/review?workspace={WS_B}",
                 f"/v3/review/glossary-candidates?workspace={WS_A}"):
        r = c.get(ruta)
        assert r.status_code == 404, (ruta, r.status_code)
        assert "Ariadna" not in r.text and MARCA_B not in r.text
    antes = _filas(entorno)
    r = c.post("/v3/review/decide", data={
        "workspace": WS_A, "proposal_id": "pa-1", "human_decision": "APPROVE",
        "request_id": "anon-1", "expected_proposal_hash": _hash(entorno, WS_A, "pa-1"),
    })
    assert r.status_code != 303
    assert _filas(entorno) == antes


# ---------------------------------------------------------------------------
# La función única de ámbito (unidad)
# ---------------------------------------------------------------------------

def test_ambito_de_revision_exige_workspace_y_lo_compara():
    from app.services.v3_review import _scoped

    ctx = build_viewer_context(role="reviewer", auth_enabled=True, default_workspace=WS_A)
    ambito = _scoped(VisibilityScope(ctx))
    assert ambito.allows_workspace(WS_A) is True
    assert ambito.allows_workspace(WS_B) is False
    # Fail-closed: un registro de revisión SIN workspace no es «capa juego».
    assert ambito.allows_workspace(None) is False
    assert ambito.allows_workspace("") is False
    # Un ámbito que ya llega relajado (`partida_only`) NO relaja la revisión.
    assert _scoped(VisibilityScope(ctx).partida_only()).allows_workspace(WS_B) is False
    admin = build_viewer_context(role="admin", auth_enabled=True, default_workspace=WS_A)
    assert _scoped(VisibilityScope(admin)).allows_workspace(WS_B) is True


# ---------------------------------------------------------------------------
# Ronda de corrección (revisor independiente): partida ajena, concesión vacía,
# mayúsculas y `undo_last` sin router
# ---------------------------------------------------------------------------

def _huella(entorno) -> tuple:
    """Filas de `human_decisions` + bytes del almacén: nada se escribe."""
    import hashlib

    service = entorno["service"]
    # SÓLO el almacén de revisión (SQLite + sus -wal/-shm + el JSONL de
    # auditoría). `auth.db` vive en el mismo directorio y cambia con cada
    # petición autenticada: no es almacén de revisión.
    base = Path(service.database_path)
    candidatos = [base, base.with_name(base.name + "-wal"),
                  base.with_name(base.name + "-shm"), Path(service.decisions_path)]
    ficheros = sorted(f for f in candidatos if f.is_file())
    return (
        json.dumps(service.store.decisions(), sort_keys=True),
        tuple((f.name, hashlib.sha256(f.read_bytes()).hexdigest()) for f in ficheros),
    )


@pytest.fixture
def ambito_mutable(entorno):
    """`username -> (default_workspace, partida_activa)`, MUTABLE durante el test.

    Permite sacar el CSRF con una concesión y atacar con otra en la MISMA
    sesión. El contexto lo sigue construyendo `build_viewer_context`.
    """
    mapa: dict[str, tuple[str, str | None]] = {}

    def _ambito(request: Request) -> VisibilityScope:
        user = request.state.user
        ws, partida = mapa.get(user.username, (WS_A, None))
        return VisibilityScope(build_viewer_context(
            role=user.role, auth_enabled=True, default_workspace=ws,
            active_partida=partida,
        ))

    entorno["app"].dependency_overrides[get_visibility_scope] = _ambito
    return entorno, mapa


class TestPartidaAjenaEnElWorkspacePropio:
    def test_control_la_partida_activa_si_ve_lo_suyo(self, ambito_mutable):
        e, mapa = ambito_mutable
        mapa["rev_a"] = (WS_A, PARTIDA_1)
        c = _cliente(e, "rev_a")
        html = c.get(f"/v3/review?workspace={WS_A}").text
        assert "pa-p1" in html and MARCA_P2 not in html

    def test_decide_sobre_propuesta_de_otra_partida_no_escribe(self, ambito_mutable):
        e, mapa = ambito_mutable
        mapa["rev_a"] = (WS_A, PARTIDA_1)
        c = _cliente(e, "rev_a")
        csrf = _csrf(c, WS_A)
        antes = _huella(e)
        r = _decide(c, csrf, workspace=WS_A, proposal_id="pa-p2",
                    proposal_hash=_hash(e, WS_A, "pa-p2"), request_id="partida-ajena")
        assert r.status_code != 303, f"decidió sobre la partida p2 con p1 activa: HTTP {r.status_code}"
        assert _huella(e) == antes, "el almacén cambió desde fuera de la partida activa"

    def test_undo_no_deshace_la_decision_de_otra_partida(self, ambito_mutable):
        e, mapa = ambito_mutable
        mapa["rev_a"] = (WS_A, PARTIDA_1)
        c = _cliente(e, "rev_a")
        csrf = _csrf(c, WS_A)
        antes = _huella(e)
        r = _undo(c, csrf, workspace=WS_A, request_id="partida-ajena-undo")
        assert r.status_code != 303, f"deshizo la decisión de la partida p2: HTTP {r.status_code}"
        assert _huella(e) == antes, "el almacén cambió desde fuera de la partida activa"


class TestConcesionVacia:
    """Autoridad indeterminada (`allowed_workspaces` vacío) ⇒ no se ve nada."""

    def test_sin_workspace_concedido_todo_da_404_y_nada_se_escribe(self, ambito_mutable):
        e, mapa = ambito_mutable
        c = _cliente(e, "rev_a")
        csrf = _csrf(c, WS_A)          # CSRF sacado con concesión en A...
        mapa["rev_a"] = ("", None)     # ...y la concesión desaparece.
        antes = _huella(e)
        r = c.get(f"/v3/review?workspace={WS_A}")
        assert r.status_code == 404, f"cola con concesión vacía: {r.status_code}"
        r = c.get("/panel/review/", params={"workspace": WS_A})
        assert r.status_code == 404, f"panel con concesión vacía: {r.status_code}"
        r = _decide(c, csrf, workspace=WS_A, proposal_id="pa-1",
                    proposal_hash=_hash(e, WS_A, "pa-1"), request_id="vacia-decide")
        assert r.status_code == 404, f"decide con concesión vacía: HTTP {r.status_code}"
        assert _huella(e) == antes

    def test_unidad_concesion_vacia_no_concede_nada(self):
        from app.services.v3_review import _scoped

        ctx = build_viewer_context(role="reviewer", auth_enabled=True, default_workspace="")
        assert ctx.allowed_workspaces == frozenset()
        assert _scoped(VisibilityScope(ctx)).allows_workspace(WS_A) is False


def test_negativo_mayusculas_no_abren_otro_corpus(concesiones_distintas):
    e = concesiones_distintas
    c = _cliente(e, "rev_a")
    csrf = _csrf(c, WS_A)
    antes = _filas(e)
    r = c.get(f"/v3/review?workspace={WS_MAYUSCULAS}")
    assert r.status_code == 404 and MARCA_B not in r.text, r.status_code
    r = _decide(c, csrf, workspace=WS_MAYUSCULAS, proposal_id="pm-1",
                proposal_hash=_hash(e, WS_MAYUSCULAS, "pm-1"), request_id="mayus")
    assert r.status_code in (403, 404), f"decidió sobre {WS_MAYUSCULAS!r}: HTTP {r.status_code}"
    assert _filas(e) == antes


def test_servicio_undo_last_con_ambito_ajeno_no_escribe(entorno):
    """`undo_last` acota por sí mismo, sin depender del 404 del router."""
    from app.services.v3_review import NO_ACTIVE_DECISION, ReviewError

    ctx = build_viewer_context(role="reviewer", auth_enabled=True, default_workspace=WS_A)
    antes = _huella(entorno)
    with pytest.raises(ReviewError) as exc:
        entorno["service"].undo_last(
            workspace=WS_B, reviewer="rev_a", request_id="svc-undo-ajeno",
            scope=VisibilityScope(ctx),
        )
    assert getattr(exc.value, "code", None) == NO_ACTIVE_DECISION
    assert _huella(entorno) == antes
