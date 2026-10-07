# -*- coding: utf-8 -*-
"""PR-1 (USABLE-V1) — `/review-console` NO se monta por defecto.

El panel v1 (laboratorio, Equipo B) servía siempre `src_demo_01`/`src_demo_02`
desde fixtures del repo, sin estar en `NAV` ni enlazado desde ninguna otra
pantalla salvo él mismo, con `POST …/decide` vivo: un revisor que tecleara la
URL podía decidir sobre datos de laboratorio creyendo revisar de verdad —
falsa confirmación con efecto de escritura.

Decisión del operador (D1): no se convierte en consola de producto ni se
conecta al motor real; se deja de montar por defecto. `S9K_REVIEW_CONSOLE_ENABLED`
reutiliza EXACTAMENTE la misma autoridad que `app.routers.resultado` usa para
`/panel/resultado` (`app.config.effective_env_value` + `chassis.FLAG_ON_VALUES`,
fallo cerrado, se lee en cada petición).

Este testigo mide las TRES rutas, no sólo la de entrada: `GET /review-console`,
`GET /review-console/source/{id}` y `POST /review-console/source/{id}/decide`
— el `POST` es el que importa de verdad, porque es el que escribe.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import review_console as rc

FLAG = "S9K_REVIEW_CONSOLE_ENABLED"


def _client(lector_por_dependencia=None):
    """Cliente de la consola. Con `lector_por_dependencia` instala un lector
    LEGÍTIMO (ver `conftest.py`): sin él, el ámbito anónimo no entrega la capa
    juego y los tests de control positivo (bandera encendida) no verían nada
    que no sea por la propia bandera. Los de apagada no lo necesitan: el 404
    por interruptor ocurre ANTES de tocar el ámbito."""
    from app.main import app
    if lector_por_dependencia is not None:
        lector_por_dependencia(app)
    return TestClient(app, follow_redirects=False)


# ---------------------------------------------------------------------------
# Estado de fábrica: la clave AUSENTE del entorno (ni siquiera "false")
# ---------------------------------------------------------------------------
def test_sin_la_clave_en_el_entorno_get_inbox_da_404(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    r = _client().get("/review-console")
    assert r.status_code == 404


def test_sin_la_clave_en_el_entorno_get_detalle_da_404(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    r = _client().get("/review-console/source/src_demo_01")
    assert r.status_code == 404


def test_sin_la_clave_en_el_entorno_post_decide_da_404(monkeypatch):
    """EL CASO QUE IMPORTA: el `POST` que escribe también da 404 apagado."""
    monkeypatch.delenv(FLAG, raising=False)
    c = rc.get_candidate("src_demo_01", "cand_a1")
    ch = rc.candidate_hash(c)["value"]
    r = _client().post(
        "/review-console/source/src_demo_01/decide",
        data={"candidate_id": "cand_a1", "action": "APPROVE",
              "expected_candidate_hash": ch},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Valores que NO encienden: ausente, vacía, "false", ininteligible
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("valor", ["false", "0", "", "no", "TRUE_PERO_MAL"])
def test_valores_que_no_encienden_siguen_dando_404(monkeypatch, valor):
    monkeypatch.setenv(FLAG, valor)
    assert _client().get("/review-console").status_code == 404


# ---------------------------------------------------------------------------
# Control positivo: encendida, sigue viva (laboratorio legítimo)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("valor", ["true", "1", "True", "TRUE"])
def test_encendida_el_get_inbox_sigue_vivo(monkeypatch, valor, lector_por_dependencia):
    monkeypatch.setenv(FLAG, valor)
    r = _client(lector_por_dependencia).get("/review-console")
    assert r.status_code == 200
    assert "src_demo_01" in r.text


def test_encendida_el_post_decide_sigue_escribiendo(monkeypatch, tmp_path, lector_por_dependencia):
    monkeypatch.setenv(FLAG, "true")
    monkeypatch.setenv("S9K_REVIEW_LAB_DIR", str(tmp_path))
    c = rc.get_candidate("src_demo_01", "cand_a1")
    ch = rc.candidate_hash(c)["value"]
    r = _client(lector_por_dependencia).post(
        "/review-console/source/src_demo_01/decide",
        data={"candidate_id": "cand_a1", "action": "APPROVE",
              "expected_candidate_hash": ch},
    )
    assert r.status_code == 303
    assert len(rc.read_decisions(tmp_path)) == 1


# ---------------------------------------------------------------------------
# Regresión: la función no vuelve a leer os.environ a pelo (misma guarda que
# S-3 exige para chassis.slot_enabled y resultado._encendido)
# ---------------------------------------------------------------------------
def test_encendido_no_lee_os_environ_directamente():
    import inspect
    from app.routers import reviews_console

    fuente = inspect.getsource(reviews_console._encendido)
    assert "os.environ.get(" not in fuente
    assert "effective_env_value" in fuente
