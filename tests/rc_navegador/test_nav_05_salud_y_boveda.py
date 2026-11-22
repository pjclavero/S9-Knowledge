# -*- coding: utf-8 -*-
"""Estado operacional (`/admin/health`) y bóveda externa por la web.

Contrato: E6 (6.M1 `/admin/health`), E10 (10.M1 renombrar con bóveda
escribible, 10.M2 bóveda no escribible ⇒ 409 exacto y fichero intacto, 10.M3
`/admin/health` READ_ONLY, 10.M4 bóveda inexistente) y regresión 15. La parte
web de la bóveda no se ejecutó en ninguna de las dos rondas anteriores.

Ninguna prueba de este módulo necesita Neo4j. Las de bóveda necesitan que la
instalación la tenga declarada (capacidades ``boveda``, ``boveda_solo_lectura``,
``boveda_inexistente``); sin eso quedan BLOCKED.

Lo que un navegador no puede ver (inodo, dueño, grupo y modo del perfil) se
comprueba aparte SÓLO si se declara ``S9K_RC_NAV_PERFIL_BOVEDA`` y el fichero
es legible desde donde corre la batería; si no, la prueba dice que esa parte
no se midió.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets

import pytest

from soporte import fetch_en_pagina, ir, ruta_de, texto_visible

pytestmark = [pytest.mark.sin_grafo]

ESTADOS_DE_SALUD = {"HEALTHY", "DEGRADED", "UNHEALTHY"}


def _tabla_de_salud(pagina) -> list[dict]:
    return pagina.eval_on_selector_all(
        "main table tbody tr",
        """els => els.map(tr => { const td = tr.querySelectorAll('td');
            return {componente: td[0].textContent.trim(), estado: td[1].textContent.trim(),
                    mensaje: td[2].textContent.trim()}; })""",
    )


# ---------------------------------------------------------------------------
# /admin/health
# ---------------------------------------------------------------------------

@pytest.mark.cubre("6.M1", "REG-15")
def test_estado_operacional_visto_por_el_administrador(pagina_como, cfg, evidencia):
    admin = pagina_como("admin")
    respuesta = ir(admin, cfg, "/admin/health")
    evidencia.paso(admin, "estado operacional", estado=respuesta.status)
    assert respuesta.status == 200, f"SALUD: /admin/health respondió {respuesta.status} al administrador"
    global_ = admin.locator("main p strong").first.inner_text().strip()
    tabla = _tabla_de_salud(admin)
    evidencia.dato("salud en pantalla", {"global": global_, "componentes": tabla})
    assert global_ in ESTADOS_DE_SALUD, f"SALUD: el estado global es {global_!r}"
    assert tabla, "SALUD: la pantalla no lista ningún componente"
    for fila in tabla:
        assert fila["estado"] in ESTADOS_DE_SALUD | {"UNKNOWN", "SKIPPED"}, f"SALUD: estado no reconocido: {fila}"
        assert fila["mensaje"], f"SALUD: el componente {fila['componente']} no explica su estado"
    componentes = {f["componente"]: f for f in tabla}
    for obligatorio in ("viewer", "auth_db", "job_store", "vault"):
        assert obligatorio in componentes, f"SALUD: falta el componente {obligatorio}: {sorted(componentes)}"

    # La pantalla y la API dicen lo mismo (misma lectura, dos presentaciones).
    r = fetch_en_pagina(admin, "GET", "/api/admin/health")
    assert r["estado"] == 200, f"SALUD: /api/admin/health respondió {r['estado']} al administrador"
    api = json.loads(admin.evaluate(
        "async () => (await (await fetch('/api/admin/health', {credentials: 'same-origin'})).text())"
    ))
    por_api = {c["component"]: c["status"] for c in api["components"]}
    evidencia.dato("salud por la API", {"global": api.get("overall"), "componentes": por_api})
    assert set(por_api) == set(componentes), (
        f"SALUD: la pantalla y la API no listan los mismos componentes: {sorted(set(por_api) ^ set(componentes))}"
    )

    # La bóveda: lo que dice la pantalla coincide con lo que la instalación declara.
    boveda = componentes["vault"]["mensaje"]
    if "boveda_solo_lectura" in cfg.capacidades:
        assert "READ_ONLY" in boveda, f"SALUD: bóveda declarada de sólo lectura y la pantalla dice {boveda!r}"
    elif "boveda" in cfg.capacidades:
        assert "AVAILABLE" in boveda and "UNAVAILABLE" not in boveda, (
            f"SALUD: bóveda declarada escribible y la pantalla dice {boveda!r}"
        )
    elif "boveda_inexistente" not in cfg.capacidades:
        assert "no configurada" in boveda, (
            f"SALUD: la instalación no declara bóveda y la pantalla dice {boveda!r}"
        )
        assert componentes["vault"]["estado"] == "HEALTHY", (
            "SALUD: una bóveda no configurada (dependencia opcional) degrada la salud"
        )


@pytest.mark.cubre("extra.salud", "REG-15")
def test_guardar_la_instantanea_de_salud(pagina_como, cfg, evidencia):
    admin = pagina_como("admin")
    ir(admin, cfg, "/admin/health")
    with admin.expect_navigation():
        admin.click("form[action='/admin/health/snapshot'] button")
    evidencia.paso(admin, "tras guardar la instantánea")
    assert ruta_de(admin) == "/admin/health", f"INSTANTÁNEA: tras guardar se acabó en {ruta_de(admin)}"
    assert "Hay un informe guardado." in texto_visible(admin, "main"), (
        "INSTANTÁNEA: tras guardar, la pantalla no dice que haya un informe guardado"
    )


@pytest.mark.cubre("extra.roles", "REG-15")
@pytest.mark.parametrize("cuenta", ["lector", "revisor"])
def test_el_estado_operacional_no_se_sirve_a_quien_no_administra(pagina_como, cfg, evidencia, cuenta):
    pagina = pagina_como(cuenta)
    respuesta = ir(pagina, cfg, "/admin/health")
    evidencia.paso(pagina, f"salud como {cuenta}", estado=respuesta.status)
    assert respuesta.status == 403, f"SALUD[{cuenta}]: /admin/health respondió {respuesta.status}"
    assert "Componente" not in texto_visible(pagina), f"SALUD[{cuenta}]: la respuesta trae la tabla de componentes"
    ir(pagina, cfg, "/")
    r = fetch_en_pagina(pagina, "GET", "/api/admin/health")
    evidencia.dato("api", {"estado": r["estado"]})
    assert r["estado"] == 403, f"SALUD[{cuenta}]: /api/admin/health respondió {r['estado']}"
    assert "components" not in r["texto"], f"SALUD[{cuenta}]: la API entregó componentes"


@pytest.mark.cubre("10.M3", "REG-15")
@pytest.mark.requiere("boveda", "boveda_solo_lectura")
def test_el_estado_operacional_dice_boveda_de_solo_lectura(pagina_como, cfg, evidencia):
    admin = pagina_como("admin")
    respuesta = ir(admin, cfg, "/admin/health")
    evidencia.paso(admin, "estado operacional con la bóveda no escribible", estado=respuesta.status)
    boveda = [f for f in _tabla_de_salud(admin) if f["componente"] == "vault"]
    evidencia.dato("bóveda", boveda)
    assert boveda and "READ_ONLY" in boveda[0]["mensaje"], (
        f"SALUD: con la bóveda no escribible la pantalla dice {boveda}"
    )


# ---------------------------------------------------------------------------
# Bóveda externa por la web
# ---------------------------------------------------------------------------

def _huella_del_perfil(cfg):
    """Inodo, dueño, grupo, modo y resumen del perfil; None si no se puede medir."""
    if not cfg.perfil_boveda:
        return None
    try:
        st = os.stat(cfg.perfil_boveda)
        with open(cfg.perfil_boveda, "rb") as f:
            resumen = hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None
    return {"inodo": st.st_ino, "uid": st.st_uid, "gid": st.st_gid, "modo": oct(st.st_mode & 0o7777), "sha256": resumen}


def _formulario_de_nombre(admin):
    return admin.locator("form[action='/admin/partidas/label']")


@pytest.mark.cubre("10.M1", "REG-15")
@pytest.mark.requiere("boveda")
def test_renombrar_el_workspace_con_la_boveda_escribible(pagina_como, cfg, evidencia):
    if "boveda_solo_lectura" in cfg.capacidades:
        pytest.skip("BLOCKED[config]: la instalación declara la bóveda de sólo lectura; el éxito se mide con ella escribible")
    admin = pagina_como("admin")
    ir(admin, cfg, "/admin/partidas")
    evidencia.paso(admin, "partidas antes de renombrar")
    formulario = _formulario_de_nombre(admin)
    assert formulario.count() == 1, (
        "BÓVEDA: la pantalla no ofrece editar el nombre del workspace: "
        + texto_visible(admin, "main section")[:300]
    )
    original = formulario.locator("#label").input_value()
    antes = _huella_del_perfil(cfg)
    nuevo = "Ensayo RC3 " + secrets.token_hex(2)
    try:
        formulario.locator("#label").fill(nuevo)
        with admin.expect_navigation() as nav:
            formulario.locator("button[type=submit]").click()
        evidencia.paso(admin, "tras guardar el nombre", estado=nav.value.status if nav.value else None)
        assert ruta_de(admin) == "/admin/partidas" and (nav.value is None or nav.value.status == 200), (
            f"BÓVEDA: guardar el nombre no volvió limpio a la pantalla: {texto_visible(admin)[:300]}"
        )
        assert _formulario_de_nombre(admin).locator("#label").input_value() == nuevo, (
            "BÓVEDA: tras guardar, el formulario no muestra el nombre nuevo"
        )
        # El nombre humano se usa en el resto del producto.
        ir(admin, cfg, "/")
        evidencia.paso(admin, "inicio con el nombre nuevo")
        assert nuevo in texto_visible(admin, "main"), "BÓVEDA: el inicio no muestra el nombre humano nuevo del workspace"
        despues = _huella_del_perfil(cfg)
        evidencia.dato("perfil antes y después", {"antes": antes, "después": despues})
        if antes and despues:
            for campo in ("uid", "gid", "modo"):
                assert antes[campo] == despues[campo], (
                    f"BÓVEDA: escribir el nombre cambió {campo} del perfil: {antes[campo]} -> {despues[campo]}"
                )
            assert antes["sha256"] != despues["sha256"], "BÓVEDA: el perfil no cambió en disco"
        else:
            evidencia.dato("NO MEDIDO", "inodo/dueño/grupo/modo del perfil: S9K_RC_NAV_PERFIL_BOVEDA no declarado o ilegible")
    finally:
        ir(admin, cfg, "/admin/partidas")
        formulario = _formulario_de_nombre(admin)
        if formulario.count() == 1 and formulario.locator("#label").input_value() != original:
            formulario.locator("#label").fill(original)
            with admin.expect_navigation():
                formulario.locator("button[type=submit]").click()
    ir(admin, cfg, "/admin/partidas")
    assert _formulario_de_nombre(admin).locator("#label").input_value() == original, (
        "BÓVEDA: REPOSICIÓN fallida: el nombre del workspace no volvió a su valor original"
    )


@pytest.mark.cubre("10.M2", "REG-15")
@pytest.mark.requiere("boveda", "boveda_solo_lectura")
def test_renombrar_con_la_boveda_no_escribible_da_409_y_no_toca_el_perfil(pagina_como, cfg, evidencia):
    admin = pagina_como("admin")
    ir(admin, cfg, "/admin/partidas")
    evidencia.paso(admin, "partidas con la bóveda no escribible")
    formulario = _formulario_de_nombre(admin)
    assert formulario.count() == 1, (
        "BÓVEDA_409: PRECONDICIÓN: la pantalla no ofrece el formulario de nombre: "
        + texto_visible(admin, "main section")[:300]
    )
    original = formulario.locator("#label").input_value()
    antes = _huella_del_perfil(cfg)
    formulario.locator("#label").fill("No se guarda " + secrets.token_hex(2))
    with admin.expect_navigation() as nav:
        formulario.locator("button[type=submit]").click()
    estado = nav.value.status if nav.value else None
    cuerpo = texto_visible(admin)
    evidencia.paso(admin, "respuesta al guardar", estado=estado)
    assert estado == 409, f"BÓVEDA_409: guardar con la bóveda no escribible respondió {estado}: {cuerpo[:200]}"
    assert "no es escribible por el usuario" in cuerpo and "contenido del operador" in cuerpo, (
        f"BÓVEDA_409: el rechazo no dice la causa ni de quién es la bóveda: {cuerpo[:300]}"
    )
    ir(admin, cfg, "/admin/partidas")
    assert _formulario_de_nombre(admin).locator("#label").input_value() == original, (
        "BÓVEDA_409: tras el rechazo, el nombre mostrado cambió"
    )
    despues = _huella_del_perfil(cfg)
    evidencia.dato("perfil antes y después", {"antes": antes, "después": despues})
    if antes and despues:
        assert antes == despues, f"BÓVEDA_409: el perfil cambió en disco pese al rechazo: {antes} -> {despues}"
    else:
        evidencia.dato("NO MEDIDO", "que el fichero quedó intacto: S9K_RC_NAV_PERFIL_BOVEDA no declarado o ilegible")


@pytest.mark.cubre("10.M4", "REG-15")
@pytest.mark.requiere("boveda_inexistente")
def test_boveda_inexistente_no_ofrece_editar_y_el_envio_directo_da_404(pagina_como, cfg, evidencia):
    assert cfg.workspace, "BÓVEDA_AUSENTE: declara S9K_RC_NAV_WORKSPACE (el workspace de la instalación)"
    admin = pagina_como("admin")
    ir(admin, cfg, "/admin/partidas")
    evidencia.paso(admin, "partidas sin bóveda resoluble")
    assert _formulario_de_nombre(admin).count() == 0, "BÓVEDA_AUSENTE: se ofrece editar el nombre sin bóveda"
    testigo = admin.locator("header.topbar form[action='/logout'] input[name=csrf_token]").get_attribute("value")
    r = fetch_en_pagina(admin, "POST", "/admin/partidas/label", formulario={
        "csrf_token": testigo, "workspace": cfg.workspace, "label": "No se crea", "fingerprint": "x",
    })
    evidencia.dato("envío directo", {"estado": r["estado"], "texto": r["texto"][:300]})
    assert r["estado"] == 404, f"BÓVEDA_AUSENTE: el envío directo respondió {r['estado']}, se esperaba 404"
    assert "no hay nada que editar" in r["texto"], "BÓVEDA_AUSENTE: el 404 no explica que no hay bóveda"


@pytest.mark.cubre("extra.boveda", "REG-15")
def test_la_pantalla_de_partidas_dice_lo_que_sabe_de_la_boveda(pagina_como, cfg, evidencia):
    """Sin bóveda consultable no se ofrece conceder acceso a un identificador
    tecleado a mano; y no se enlaza la consola si está apagada."""
    admin = pagina_como("admin")
    respuesta = ir(admin, cfg, "/admin/partidas")
    evidencia.paso(admin, "partidas", estado=respuesta.status)
    assert respuesta.status == 200, f"PARTIDAS: respondió {respuesta.status}"
    concesion = admin.locator("form[action='/admin/partidas/grant']")
    assert concesion.count() == 1, "PARTIDAS: la pantalla no trae el formulario de concesión"
    assert concesion.locator("input[name=partida_id]").count() == 0, (
        "PARTIDAS: la partida se puede teclear a mano"
    )
    hay_selector = concesion.locator("select#partida_id").count() == 1
    evidencia.dato("estado", {
        "selector_de_partida": hay_selector,
        "aviso_no_disponible": admin.locator("#aviso_boveda_no_disponible").count(),
        "aviso_vacia": admin.locator("#aviso_boveda_vacia").count(),
    })
    if "partidas" in cfg.capacidades:
        assert hay_selector, "PARTIDAS: la instalación declara partidas y la pantalla no las ofrece"
    elif "boveda" not in cfg.capacidades:
        assert not hay_selector, "PARTIDAS: sin bóveda declarada la pantalla ofrece elegir partida"
        assert admin.locator("#aviso_boveda_no_disponible, #aviso_boveda_vacia").count() == 1, (
            "PARTIDAS: sin bóveda la pantalla no explica por qué no se puede conceder"
        )
        assert concesion.locator("button[type=submit]").count() == 0, (
            "PARTIDAS: sin partidas que elegir se ofrece el botón «Conceder»"
        )
    enlace_consola = admin.locator("main a[href='/panel/operations']").count()
    if "panel_b" not in cfg.capacidades:
        assert enlace_consola == 0, "PARTIDAS: se enlaza la consola de operador estando apagada (daría 404)"
