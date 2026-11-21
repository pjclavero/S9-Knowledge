# -*- coding: utf-8 -*-
"""Caducidad de la sesión por inactividad, con el reloj REAL del servidor.

Contrato: E7 (7.M4, «inactividad = NO MEDIDO salvo espera») y la regresión 15.

Qué dice el producto
--------------------
``S9K_SESSION_IDLE_MINUTES`` (entero, en minutos; 60 por defecto; 0 lo
desactiva) fija la inactividad máxima. Es configurable por entorno y se lee al
arrancar el visor. El valor mínimo útil es 1 minuto. Además existe una
caducidad absoluta, ``S9K_SESSION_TTL_HOURS`` (12 por defecto).

Cómo se mide aquí
-----------------
No se toca el reloj del servidor ni la base de sesiones. Se espera de verdad.
Como la espera es larga (el valor de la instalación, que se declara en
``S9K_RC_NAV_IDLE_MINUTOS``), la prueba va en TRES TANDAS CORTAS y entre ellas
no queda ningún navegador abierto:

  sembrar    dos cuentas entran; se guardan sus cookies en un fichero 0600
             fuera del repositorio.
  tocar      hacia la mitad de la espera, SÓLO la cuenta de control navega.
  comprobar  pasado el plazo desde la siembra: la cuenta que se dejó quieta
             ya no tiene sesión; la de control —sembrada a la vez, pero con
             actividad a media espera— sigue dentro.

El control es lo que separa «caducó por inactividad» de «caducó porque pasó
ese tiempo» o «se cayó por otra causa». Las cookies guardadas se cargan en un
contexto nuevo del navegador: equivale a un navegador que se dejó abierto.

Cada tanda se pide con ``S9K_RC_NAV_FASE_INACTIVIDAD``. En una tanda normal
(sin fase) estas pruebas quedan BLOCKED con su motivo: no se dan por verdes.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from soporte import fetch_en_pagina, iniciar_sesion, ir, ruta_de

pytestmark = [pytest.mark.sin_grafo, pytest.mark.cubre("7.30", "7.31", "7.32", "7.34", "7.M4", "REG-15")]

COOKIE_SESION = "s9k_session"


def _fichero(cfg) -> Path:
    return cfg.estado_dir / "inactividad.json"


def _exigir_fase(cfg, fase: str) -> None:
    if cfg.fase_inactividad != fase:
        pytest.skip(
            f"BLOCKED[fase]: la caducidad por inactividad se mide en tandas separadas; ésta es la "
            f"fase «{fase}» y la tanda pidió «{cfg.fase_inactividad or 'ninguna'}»"
        )
    if not cfg.idle_minutos or cfg.idle_minutos < 1:
        pytest.fail("INACTIVIDAD: declara en S9K_RC_NAV_IDLE_MINUTOS el valor de S9K_SESSION_IDLE_MINUTES "
                    "de la instalación (entero >= 1)")


def _leer(cfg) -> dict:
    ruta = _fichero(cfg)
    if not ruta.exists():
        pytest.fail("INACTIVIDAD: no hay siembra previa; ejecuta antes la fase «sembrar»")
    return json.loads(ruta.read_text(encoding="utf-8"))


def _guardar(cfg, datos: dict) -> None:
    ruta = _fichero(cfg)
    descriptor = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as f:
        json.dump(datos, f)
    os.chmod(ruta, 0o600)


def _registrar_cookies(redactor, estado: dict) -> None:
    redactor.registrar_cookies(estado.get("cookies", []))


def test_inactividad_1_sembrar(contexto, cfg, evidencia, redactor):
    _exigir_fase(cfg, "sembrar")
    datos = {"idle_minutos": cfg.idle_minutos}
    for clave in ("inact_a", "inact_b"):
        ctx = contexto(clave)
        pagina = ctx.new_page()
        r = iniciar_sesion(pagina, cfg, cfg.cuenta(clave))
        assert r.status == 302, f"INACTIVIDAD[sembrar]: la cuenta {clave} no entra (POST {r.status})"
        ir(pagina, cfg, "/account")
        assert ruta_de(pagina) == "/account", f"INACTIVIDAD[sembrar]: {clave} no ve su cuenta"
        evidencia.paso(pagina, f"sembrada {clave}")
        estado = ctx.storage_state()
        _registrar_cookies(redactor, estado)
        datos[clave] = {"estado": estado, "ultima_actividad": time.time()}
    datos["sembrado_en"] = time.time()
    _guardar(cfg, datos)
    evidencia.dato("siembra", {"sembrado_utc": time.strftime("%H:%M:%SZ", time.gmtime(datos["sembrado_en"])),
                               "idle_minutos": cfg.idle_minutos})


def test_inactividad_2_tocar_el_control(contexto, cfg, evidencia, redactor):
    _exigir_fase(cfg, "tocar")
    datos = _leer(cfg)
    for clave in ("inact_a", "inact_b"):
        _registrar_cookies(redactor, datos[clave]["estado"])
    plazo = datos["idle_minutos"] * 60
    transcurrido = time.time() - datos["sembrado_en"]
    evidencia.dato("segundos desde la siembra", round(transcurrido))
    assert 0.25 * plazo <= transcurrido <= 0.85 * plazo, (
        f"INACTIVIDAD[tocar]: han pasado {transcurrido:.0f} s desde la siembra; el control se toca "
        f"entre el 25 % y el 85 % del plazo ({plazo} s) para que la medida discrimine"
    )
    ctx = contexto("inact_b", estado=datos["inact_b"]["estado"])
    pagina = ctx.new_page()
    respuesta = ir(pagina, cfg, "/account")
    evidencia.paso(pagina, "control con actividad a media espera", estado=respuesta.status)
    assert ruta_de(pagina) == "/account", (
        "INACTIVIDAD[tocar]: la sesión de control ya no vale a media espera: la medida no es válida"
    )
    datos["inact_b"]["ultima_actividad"] = time.time()
    datos["inact_b"]["estado"] = ctx.storage_state()
    _guardar(cfg, datos)


def test_inactividad_3_la_sesion_quieta_caduca_y_la_activa_no(contexto, cfg, evidencia, redactor):
    _exigir_fase(cfg, "comprobar")
    datos = _leer(cfg)
    for clave in ("inact_a", "inact_b"):
        _registrar_cookies(redactor, datos[clave]["estado"])
    plazo = datos["idle_minutos"] * 60
    ahora = time.time()
    quieta = ahora - datos["inact_a"]["ultima_actividad"]
    control_desde_siembra = ahora - datos["sembrado_en"]
    control_desde_toque = ahora - datos["inact_b"]["ultima_actividad"]
    evidencia.dato("tiempos", {
        "plazo_s": plazo,
        "quieta_s": round(quieta),
        "control_desde_la_siembra_s": round(control_desde_siembra),
        "control_desde_su_ultima_actividad_s": round(control_desde_toque),
    })
    assert quieta >= plazo + 30, (
        f"INACTIVIDAD[comprobar]: la sesión quieta lleva {quieta:.0f} s; hay que esperar a que pase "
        f"el plazo ({plazo} s) con margen"
    )
    assert control_desde_siembra >= plazo + 30, "INACTIVIDAD[comprobar]: el control no lleva más que el plazo desde la siembra"
    assert control_desde_toque < plazo - 60, (
        f"INACTIVIDAD[comprobar]: el control lleva {control_desde_toque:.0f} s sin actividad: "
        "también habría caducado y ya no discrimina"
    )

    # El control primero: si él tampoco entra, lo que se ve no es inactividad.
    ctx_b = contexto("inact_b", estado=datos["inact_b"]["estado"])
    pb = ctx_b.new_page()
    respuesta = ir(pb, cfg, "/account")
    evidencia.paso(pb, "control: sigue dentro", estado=respuesta.status)
    assert ruta_de(pb) == "/account", (
        "INACTIVIDAD[comprobar]: la sesión de CONTROL (con actividad a media espera) tampoco vale: "
        "la caída no se puede atribuir a la inactividad"
    )

    ctx_a = contexto("inact_a", estado=datos["inact_a"]["estado"])
    assert any(c["name"] == COOKIE_SESION for c in ctx_a.cookies()), (
        "INACTIVIDAD[comprobar]: el navegador ya no tiene la cookie: no se estaría midiendo al servidor"
    )
    pa = ctx_a.new_page()
    respuesta = ir(pa, cfg, "/account")
    evidencia.paso(pa, "quieta: enviada al login", estado=respuesta.status)
    assert ruta_de(pa) == "/login", (
        f"INACTIVIDAD[comprobar]: tras {quieta:.0f} s sin actividad (plazo {plazo} s) la sesión sigue "
        f"abriendo {ruta_de(pa)}"
    )
    r = fetch_en_pagina(pa, "GET", "/api/status")
    evidencia.dato("api con la sesión caducada", {"estado": r["estado"]})
    assert r["estado"] == 401, f"INACTIVIDAD[comprobar]: la API respondió {r['estado']} con la sesión caducada"

    # Y la cuenta puede volver a entrar: caducó la sesión, no la cuenta.
    r = iniciar_sesion(pa, cfg, cfg.cuenta("inact_a"))
    evidencia.paso(pa, "vuelve a entrar", estado=r.status)
    assert r.status == 302 and ruta_de(pa) == "/", "INACTIVIDAD[comprobar]: tras caducar no se puede volver a entrar"
    _fichero(cfg).unlink()
