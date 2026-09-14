"""SLICE 2 · CORTE 2 — controles negativos SEPARADOS de las dos puertas.

Corte 1 enseñó el fallo a evitar: una prueba de rol que seguía pasando aunque
se degradara la guarda de autorización, porque al `reviewer` lo paraba el CSRF
y no el rol. El rojo venía de la puerta equivocada.

Aquí las dos puertas se prueban POR SEPARADO, y cada caso construye a propósito
la situación en la que **sólo su puerta** puede parar la petición:

  * autorización: token CSRF VÁLIDO de la propia sesión, rol insuficiente;
  * CSRF: rol SUFICIENTE y sesión válida (se comprueba antes con un GET 200),
    token ausente/inválido.

Cada aserción lleva el código observado en el mensaje, para que un rojo por
otra causa se distinga de un rojo legítimo.
"""
from __future__ import annotations

import uuid

import pytest

from test_v3_decision_efectiva import (  # noqa: F401  (fixtures reutilizadas)
    WORKSPACE,
    _CSRF,
    _first_pending,
    _open_queue,
    auth_env,
    client_factory,
    engine_result,
    service,
    workdir,
)


def _payload(item):
    return {
        "workspace": WORKSPACE,
        "proposal_id": item["proposal_id"],
        "human_decision": "APPROVE",
        "request_id": str(uuid.uuid4()),
        "expected_proposal_hash": item["proposal_hash"],
    }


def test_autorizacion_rol_insuficiente_con_csrf_valido(client_factory, service):
    """AUTORIZACIÓN, aislada: el CSRF es correcto; lo que falla es el rol."""
    espectador = client_factory("viewer")
    item = _first_pending(service)

    # El CSRF se toma de la sesión DEL PROPIO espectador: así, si la guarda de
    # rol se degradara, el token sería válido y la petición pasaría.
    pagina = espectador.get(f"/v3/review?workspace={WORKSPACE}")
    if pagina.status_code == 200 and _CSRF.search(pagina.text):
        token = _CSRF.search(pagina.text).group(1)
    else:
        # El rol ni siquiera puede abrir la cola: la puerta de autorización ya
        # actuó aquí. Se deja constancia explícita en vez de fingir un token.
        assert pagina.status_code in (302, 403), pagina.status_code
        token = ""

    datos = _payload(item)
    datos["csrf_token"] = token
    respuesta = espectador.post("/v3/review/decide", data=datos)

    assert respuesta.status_code == 403, (
        "la puerta de AUTORIZACIÓN no paró a un rol insuficiente; "
        f"código observado: {respuesta.status_code}"
    )
    assert service.store.decisions() == [], "un rol insuficiente ha persistido"


def test_csrf_reviewer_legitimo_sin_token_valido(client_factory, service):
    """CSRF, aislado: el rol es suficiente; lo que falla es el token."""
    client = client_factory("reviewer")
    item = _first_pending(service)

    # Se DEMUESTRA primero que la autorización no es lo que para a este cliente.
    pagina = client.get(f"/v3/review?workspace={WORKSPACE}")
    assert pagina.status_code == 200, (
        "este cliente debe pasar la autorización para que el caso aísle el "
        f"CSRF; código observado: {pagina.status_code}"
    )

    datos = _payload(item)
    datos["csrf_token"] = "token-que-no-corresponde-a-esta-sesion"
    respuesta = client.post("/v3/review/decide", data=datos)

    assert respuesta.status_code == 403, (
        "la puerta CSRF no paró una petición con token inválido; "
        f"código observado: {respuesta.status_code}"
    )
    assert service.store.decisions() == [], "un token inválido ha persistido"


def test_anonimo_ni_siquiera_llega(client_factory, service):
    """Sin sesión no hay decisión: redirección a login, nunca 303 de éxito."""
    from fastapi.testclient import TestClient
    from app.main import app

    anonimo = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    item = _first_pending(service)
    datos = _payload(item)
    datos["csrf_token"] = ""
    respuesta = anonimo.post("/v3/review/decide", data=datos)

    assert respuesta.status_code in (302, 403), respuesta.status_code
    if respuesta.status_code == 302:
        assert "/login" in respuesta.headers.get("location", "")
    assert service.store.decisions() == []
