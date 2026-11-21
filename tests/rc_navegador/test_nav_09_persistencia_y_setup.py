# -*- coding: utf-8 -*-
"""Sesión abierta a través de un reinicio, y configuración inicial por pantalla.

Contrato RC-3: 7.M3 (sesión abierta en pantalla y ``restart`` del visor),
14.M2a (navegador tras reiniciar la máquina), 1.M1 (pantalla ``/setup/admin``
sin aviso de certificado) y 7.B1 (primer administrador creado en el navegador).

Ninguna necesita Neo4j, pero todas necesitan algo que esta batería NO hace:

* 7.M3 / 14.M2a: alguien reinicia el visor o la máquina ENTRE dos tandas.
  ``S9K_RC_NAV_FASE_PERSISTENCIA=sembrar`` deja una sesión abierta y guarda su
  cookie (0600, fuera del repo); tras el reinicio, ``=comprobar`` la carga en
  un contexto nuevo. Criterio del contrato (el de 7.23j): o la sesión sigue
  válida, o pide entrar y la entrada funciona; nunca un 5xx ni un bucle.
* 1.M1 / 7.B1: la instalación tiene que estar SIN primer administrador
  (capacidad ``setup_abierto``). El alta crea el administrador con la cuenta
  ``admin`` del fichero de credenciales.

Fuera de su fase o sin su capacidad quedan BLOCKED, no verdes.
"""
from __future__ import annotations

import json
import os
import time

import pytest

from soporte import cadena_de_redirecciones, iniciar_sesion, ir, ruta_de, texto_visible

pytestmark = [pytest.mark.sin_grafo]


def _fichero(cfg):
    return cfg.estado_dir / "persistencia.json"


def _fase(cfg, fase: str) -> None:
    if cfg.fase_persistencia != fase:
        pytest.skip(
            f"BLOCKED[fase]: la sesión a través de un reinicio se mide en dos tandas con el reinicio "
            f"en medio; ésta es «{fase}» y la tanda pidió «{cfg.fase_persistencia or 'ninguna'}»"
        )


@pytest.mark.cubre("7.M3", "14.M2a", "REG-15")
def test_persistencia_1_dejar_una_sesion_abierta(contexto, cfg, evidencia, redactor):
    _fase(cfg, "sembrar")
    ctx = contexto("sesion")
    pagina = ctx.new_page()
    r = iniciar_sesion(pagina, cfg, cfg.cuenta("sesion"))
    assert r.status == 302, f"PERSISTENCIA[sembrar]: la cuenta no entra (POST {r.status})"
    ir(pagina, cfg, "/account")
    evidencia.paso(pagina, "sesión abierta antes del reinicio")
    assert ruta_de(pagina) == "/account", "PERSISTENCIA[sembrar]: la sesión no abre /account"
    estado = ctx.storage_state()
    redactor.registrar_cookies(estado.get("cookies", []))
    descriptor = os.open(_fichero(cfg), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as f:
        json.dump({"estado": estado, "sembrado_en": time.time()}, f)


@pytest.mark.cubre("7.M3", "14.M2a", "REG-15")
def test_persistencia_2_la_sesion_tras_el_reinicio(contexto, cfg, evidencia, redactor):
    _fase(cfg, "comprobar")
    ruta = _fichero(cfg)
    assert ruta.exists(), "PERSISTENCIA[comprobar]: no hay siembra previa; ejecuta antes la fase «sembrar»"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    redactor.registrar_cookies(datos["estado"].get("cookies", []))
    ctx = contexto("sesion", estado=datos["estado"])
    pagina = ctx.new_page()
    respuesta = ir(pagina, cfg, "/account")
    cadena = cadena_de_redirecciones(respuesta)
    evidencia.paso(pagina, "primera pantalla tras el reinicio", estado=respuesta.status)
    sigue = ruta_de(pagina) == "/account"
    evidencia.dato("desenlace", {
        "segundos_desde_la_siembra": round(time.time() - datos["sembrado_en"]),
        "cadena": cadena, "la_sesion_sigue_valida": sigue,
    })
    assert all(estado < 500 for estado, _ in cadena), f"PERSISTENCIA: error del servidor tras el reinicio: {cadena}"
    assert len(cadena) <= 2, f"PERSISTENCIA: la primera pantalla encadena redirecciones (bucle): {cadena}"
    if not sigue:
        assert ruta_de(pagina) == "/login", (
            f"PERSISTENCIA: la sesión no vale y tampoco se pide entrar: se acabó en {ruta_de(pagina)}"
        )
        r = iniciar_sesion(pagina, cfg, cfg.cuenta("sesion"))
        evidencia.paso(pagina, "vuelve a entrar tras el reinicio", estado=r.status)
        assert r.status == 302 and ruta_de(pagina) == "/", (
            f"PERSISTENCIA: tras el reinicio no se puede volver a entrar (POST {r.status}, {ruta_de(pagina)})"
        )
    # Con sesión (la de antes o la nueva), el producto se sirve.
    for destino in ("/", "/jobs"):
        r = ir(pagina, cfg, destino)
        assert r.status == 200 and ruta_de(pagina) == destino, (
            f"PERSISTENCIA: tras el reinicio {destino} respondió {r.status} ({ruta_de(pagina)})"
        )
    evidencia.paso(pagina, "navegando tras el reinicio")
    ruta.unlink()


@pytest.mark.cubre("1.M1", "REG-15")
@pytest.mark.requiere("setup_abierto")
def test_la_configuracion_inicial_se_sirve_por_https_verificado(pagina_anonima, cfg, evidencia, tls):
    """«Sin aviso de certificado»: la cadena que sirve la instalación verifica
    contra la CA declarada (handshake estricto previo) y el navegador, que sólo
    acepta la clave de esa cadena, carga la pantalla sin error de TLS."""
    respuesta = ir(pagina_anonima, cfg, "/setup/admin")
    evidencia.paso(pagina_anonima, "configuración inicial", estado=respuesta.status)
    evidencia.dato("tls", {"protocolo": tls["protocolo"], "caduca": tls["caduca"]})
    assert respuesta.status == 200, f"SETUP: /setup/admin respondió {respuesta.status} con la instalación sin administrador"
    assert pagina_anonima.url.startswith("https://"), "SETUP: la pantalla no se sirvió por https"
    for campo in ("#username", "#password"):
        assert pagina_anonima.locator(campo).count() == 1, f"SETUP: falta el campo {campo}"
    # Y el formulario de entrada conduce aquí: no hay credencial que acertar.
    respuesta = ir(pagina_anonima, cfg, "/login")
    assert ruta_de(pagina_anonima) == "/setup/admin", (
        f"SETUP: sin administrador, /login llevó a {ruta_de(pagina_anonima)}"
    )


@pytest.mark.cubre("7.B1", "REG-15")
@pytest.mark.requiere("setup_abierto")
def test_el_primer_administrador_se_crea_en_el_navegador(contexto, cfg, evidencia):
    cuenta = cfg.cuenta("admin")
    ctx = contexto("alta-del-primer-administrador")
    pagina = ctx.new_page()
    ir(pagina, cfg, "/setup/admin")
    pagina.fill("#username", cuenta["username"])
    pagina.fill("#display_name", "Primer administrador (navegador)")
    pagina.fill("#password", cuenta["password"])
    evidencia.paso(pagina, "formulario de alta")
    with pagina.expect_navigation():
        pagina.click("form button[type=submit]")
    evidencia.paso(pagina, "tras el alta")
    assert ruta_de(pagina) == "/login" and "bootstrap_ok" in pagina.url, (
        f"ALTA: el alta no llevó al formulario de entrada con su acuse: {pagina.url} · {texto_visible(pagina)[:200]}"
    )
    assert pagina.locator("[role=status]").count() == 1, "ALTA: el formulario de entrada no acusa el alta"
    r = iniciar_sesion(pagina, cfg, cuenta)
    evidencia.paso(pagina, "el administrador entra", estado=r.status)
    assert r.status == 302 and ruta_de(pagina) == "/", f"ALTA: el administrador recién creado no entra (POST {r.status})"
    assert pagina.locator("header.topbar .role-badge").inner_text().strip() == "admin", "ALTA: la cuenta creada no es admin"
    # La configuración inicial queda cerrada (N9).
    respuesta = ir(pagina, cfg, "/setup/admin")
    assert respuesta.status == 404, f"ALTA: tras el alta /setup/admin respondió {respuesta.status}, se esperaba 404"
