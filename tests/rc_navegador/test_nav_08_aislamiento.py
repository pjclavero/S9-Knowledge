# -*- coding: utf-8 -*-
"""Negativo de aislamiento 8.M9: con la escritura apuntando a OTRO workspace,
el botón de aplicar no aparece y un envío directo se rechaza.

Contrato: E8, paso manual 8.M9 («con S9K_WRITER_WORKSPACE en OTRO workspace,
el botón NO aparece y el POST da APPLY_NOT_ENABLED»), no ejecutado en ninguna
de las dos rondas anteriores.

Preparación (la hace quien administra la instalación, no esta batería):

1. Recorrer el flujo hasta «preparar» con ``S9K_RC_NAV_FLUJO_HASTA=sellado``:
   queda un plan sellado y sin aplicar, y su trabajo en el fichero de estado.
2. Cambiar ``S9K_WRITER_WORKSPACE`` a otro workspace y reiniciar el visor.
3. Lanzar este módulo declarando la capacidad ``aislamiento``.
4. Restaurar ``S9K_WRITER_WORKSPACE`` y reiniciar; seguir el flujo con
   ``S9K_RC_NAV_FLUJO_DESDE=aplicar``.

El trabajo sellado se toma de ``S9K_RC_NAV_JOB_SELLADO`` o, si no se da, del
fichero de estado del flujo. Necesita Neo4j (hay un plan sellado de verdad).
"""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

from soporte import fetch_en_pagina, ir, texto_visible

pytestmark = [
    pytest.mark.necesita_grafo,
    pytest.mark.requiere("panel_b", "aislamiento"),
    pytest.mark.cubre("8.M9a", "8.M9b", "REG-15"),
]


def _job_sellado(cfg) -> str:
    if cfg.job_sellado:
        return cfg.job_sellado
    ruta = cfg.estado_dir / "flujo.json"
    estado = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
    if not estado.get("sellado") or estado.get("aplicado"):
        pytest.fail(
            "AISLAMIENTO: PRECONDICIÓN: no hay un plan sellado y sin aplicar; recorre antes el flujo "
            "con S9K_RC_NAV_FLUJO_HASTA=sellado o declara S9K_RC_NAV_JOB_SELLADO"
        )
    return estado["job_id"]


def test_con_otro_workspace_de_escritura_no_se_ofrece_aplicar(pagina_como, cfg, evidencia):
    job = _job_sellado(cfg)
    pagina = pagina_como("admin")
    respuesta = ir(pagina, cfg, f"/panel/operations/?solicitado={job}")
    evidencia.paso(pagina, "plan sellado con la escritura en otro workspace", estado=respuesta.status)
    plan = pagina.locator("[data-role=plan-revisado]")
    assert plan.count() == 1, "AISLAMIENTO: la consola no muestra el plan de esta ingesta"
    datos = {a: plan.get_attribute(f"data-plan-{a}") for a in ("estado", "habilitado", "operaciones")}
    evidencia.dato("plan", datos)
    assert pagina.locator("[data-plan-desenlace=sealed]").count() == 1, (
        f"AISLAMIENTO: PRECONDICIÓN: el plan no figura como preparado y listo: {datos}"
    )
    assert datos["habilitado"] == "false", (
        "AISLAMIENTO: con la escritura en otro workspace la consola sigue dando la aplicación por habilitada"
    )
    assert pagina.locator("[data-role=aplicar-plan]").count() == 0, (
        "AISLAMIENTO: el botón «Añadir al conocimiento» APARECE con la escritura en otro workspace"
    )
    assert pagina.locator("form[data-role=form-aplicacion]").count() == 0, (
        "AISLAMIENTO: el formulario de aplicación está en la página aunque no se vea el botón"
    )
    bloqueo = pagina.locator("[data-plan-bloqueado=no-habilitado]")
    assert bloqueo.count() == 1, (
        "AISLAMIENTO: la consola no explica por qué no se ofrece aplicar: "
        + texto_visible(pagina, "[data-role=plan-revisado]")[:300]
    )


def test_con_otro_workspace_de_escritura_el_envio_directo_se_rechaza(pagina_como, cfg, evidencia):
    job = _job_sellado(cfg)
    pagina = pagina_como("admin")
    ir(pagina, cfg, f"/panel/operations/?solicitado={job}")
    # El testigo CSRF es el REAL de la sesión (el del formulario de «Salir»):
    # lo único que falta es el botón, que es justo lo que se quiere rodear.
    testigo = pagina.locator("header.topbar form[action='/logout'] input[name=csrf_token]").get_attribute("value")
    assert testigo, "AISLAMIENTO: PRECONDICIÓN: la página no trae testigo CSRF de sesión"
    r = fetch_en_pagina(pagina, "POST", "/panel/operations/aplicaciones",
                        formulario={"csrf_token": testigo, "trabajo": job})
    consulta = parse_qs(urlparse(r["url"]).query)
    evidencia.dato("envío directo", {"estado": r["estado"], "url": r["url"], "consulta": consulta})
    assert consulta.get("aviso") == ["APPLY_NOT_ENABLED"], (
        f"AISLAMIENTO: el envío directo no se rechazó con APPLY_NOT_ENABLED: estado {r['estado']}, {r['url']}"
    )
    ir(pagina, cfg, urlparse(r["url"]).path + "?" + urlparse(r["url"]).query)
    evidencia.paso(pagina, "rechazo del envío directo")
    aviso = pagina.locator("[data-role=aviso]")
    assert aviso.get_attribute("data-aviso-tipo") == "error", "AISLAMIENTO: el rechazo no se pinta como error"
    assert aviso.get_attribute("data-aviso-code") == "APPLY_NOT_ENABLED", (
        f"AISLAMIENTO: el aviso es {aviso.get_attribute('data-aviso-code')!r}"
    )
    plan = pagina.locator("[data-role=plan-revisado]")
    assert plan.get_attribute("data-plan-estado") not in ("applied", "applying", "partial"), (
        f"AISLAMIENTO: tras el envío rechazado el plan figura como {plan.get_attribute('data-plan-estado')!r}"
    )
    assert pagina.locator("[data-role=ver-lo-aplicado]").count() == 0, (
        "AISLAMIENTO: tras el envío rechazado la consola enlaza un resultado aplicado"
    )
