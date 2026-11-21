# -*- coding: utf-8 -*-
"""Paneles (Operaciones, Review, Fuentes, Entidades), pantallas de lectura y
mensajes de error.

Contrato: E6 (6.M2 `/jobs`, `/panel/operations`), E8 (8.M3b: lo que SÍ se
observa con el worker bloqueado; pantallas de fuentes y entidades), E9
(RC1-G02: credencial inutilizable y qué ve cada rol) y regresión 15.

Qué necesita cada prueba va en sus marcadores: las de un panel exigen que la
instalación lo declare (``panel_b``, ``panel_c``, ``panel_f``, ``panel_g``);
las que leen conocimiento exigen además el grafo. Sin eso quedan BLOCKED o
PENDING, nunca verdes.

Propiedad del producto que se comprueba en todas: **la pantalla no afirma lo
que el sistema no sabe**. Un dato que no se ha podido leer no se presenta como
un cero ni como una lista vacía normal.
"""
from __future__ import annotations

import re

import pytest

from soporte import ir, ruta_de, texto_visible

# ---------------------------------------------------------------------------
# Sin base de conocimiento configurada: lo que se ve sin grafo
# ---------------------------------------------------------------------------

AVISOS_DE_PROVEEDOR = (
    "[data-testid=aviso-proveedor-no-configurado]",
    "[data-testid=aviso-proveedor-no-disponible]",
)


def _aviso_de_proveedor(pagina) -> str:
    for selector in AVISOS_DE_PROVEEDOR:
        if pagina.locator(selector).count():
            return selector
    return ""


@pytest.mark.sin_grafo
@pytest.mark.cubre("8.M3b", "6.M2", "REG-15")
@pytest.mark.parametrize("cuenta", ["lector", "revisor", "admin"])
def test_sin_grafo_cada_pantalla_avisa_de_que_no_hay_base_de_conocimiento(pagina_como, cfg, evidencia, cuenta):
    """Sólo tiene sentido —y sólo se ejecuta— si la instalación NO declara el
    grafo: entonces toda pantalla con sesión lleva el aviso, para cualquier rol."""
    if "grafo" in cfg.capacidades:
        pytest.skip("BLOCKED[config]: la instalación declara el grafo; el aviso de base no configurada no aplica")
    pagina = pagina_como(cuenta)
    sin_aviso = []
    for ruta in ("/", "/entities", "/graph", "/jobs", "/status", "/account"):
        ir(pagina, cfg, ruta)
        evidencia.paso(pagina, f"{cuenta} {ruta}")
        if not _aviso_de_proveedor(pagina):
            sin_aviso.append(ruta)
    assert not sin_aviso, f"SIN_GRAFO[{cuenta}]: pantallas sin el aviso de base de conocimiento: {sin_aviso}"


@pytest.mark.sin_grafo
@pytest.mark.cubre("8.M3b", "REG-15")
def test_sin_grafo_el_estado_no_presenta_ceros_como_medidas(pagina_como, cfg, evidencia):
    """Sin base de conocimiento, «Nodos 0 / Relaciones 0» y «OK» no son datos
    medidos. La pantalla de estado tiene que distinguirlo."""
    if "grafo" in cfg.capacidades:
        pytest.skip("BLOCKED[config]: la instalación declara el grafo; aquí se mide el caso sin él")
    pagina = pagina_como("lector")
    ir(pagina, cfg, "/status")
    evidencia.paso(pagina, "estado sin grafo")
    cuerpo = texto_visible(pagina, "main")
    evidencia.dato("estado", cuerpo)
    assert "not_configured" in cuerpo or "no configurad" in cuerpo.lower(), (
        f"ESTADO_SIN_GRAFO: la pantalla no dice que el proveedor no está configurado: {cuerpo!r}"
    )
    afirma_ok = pagina.locator("main .pill.ok", has_text="OK").count() > 0
    cuenta_ceros = bool(re.search(r"Nodos\s+0\b", cuerpo))
    assert not (afirma_ok and cuenta_ceros), (
        "ESTADO_SIN_GRAFO: con el proveedor sin configurar la pantalla dice «OK» y publica "
        f"«Nodos 0 / Relaciones 0» como si se hubieran contado: {cuerpo!r}"
    )


@pytest.mark.sin_grafo
@pytest.mark.cubre("6.M2", "REG-15")
@pytest.mark.parametrize("cuenta", ["lector", "revisor", "admin"])
def test_las_pantallas_no_dejan_errores_en_la_consola_del_navegador(pagina_como, cfg, evidencia, cuenta):
    pagina = pagina_como(cuenta)
    rutas = ["/", "/entities", "/graph", "/jobs", "/status", "/account"]
    if cuenta != "lector":
        rutas += ["/sources", "/reviews", "/v3/review"]
    if cuenta == "admin":
        rutas += ["/admin/users", "/admin/partidas", "/admin/audit", "/admin/health"]
    hallazgos = []
    for ruta in rutas:
        pagina.errores_de_consola.clear()
        pagina.errores_de_pagina.clear()
        respuesta = ir(pagina, cfg, ruta)
        pagina.wait_for_load_state("networkidle")
        if respuesta.status != 200:
            hallazgos.append(f"{ruta}: respondió {respuesta.status}")
        for e in pagina.errores_de_consola:
            hallazgos.append(f"{ruta}: consola: {e['texto'][:120]} ({e['url']})")
        for e in pagina.errores_de_pagina:
            hallazgos.append(f"{ruta}: excepción JS: {e[:160]}")
    evidencia.paso(pagina, f"última pantalla de {cuenta}")
    evidencia.dato("hallazgos", hallazgos)
    assert not hallazgos, f"CONSOLA[{cuenta}]: " + "; ".join(hallazgos)


@pytest.mark.sin_grafo
@pytest.mark.cubre("6.M2", "REG-15")
def test_un_trabajo_que_no_existe_no_se_presenta_como_encontrado(pagina_como, cfg, evidencia):
    pagina = pagina_como("lector")
    respuesta = ir(pagina, cfg, "/jobs/00000000-0000-0000-0000-00000000rc3n")
    evidencia.paso(pagina, "trabajo inexistente", estado=respuesta.status)
    assert "job_not_found" in texto_visible(pagina, "main"), "JOB_AUSENTE: la pantalla no dice que el trabajo no existe"
    assert respuesta.status == 404, (
        f"JOB_AUSENTE: un trabajo inexistente responde {respuesta.status}; se esperaba 404 "
        "(la pantalla dice «job_not_found» con un estado de éxito)"
    )


# ---------------------------------------------------------------------------
# Panel · Operaciones (B)
# ---------------------------------------------------------------------------

@pytest.mark.sin_grafo
@pytest.mark.requiere("panel_b")
@pytest.mark.cubre("6.M2", "8.M3b", "REG-15")
def test_panel_de_operaciones_muestra_cola_fuentes_y_salud(pagina_como, cfg, evidencia):
    admin = pagina_como("admin")
    respuesta = ir(admin, cfg, "/panel/operations")
    evidencia.paso(admin, "panel de operaciones", estado=respuesta.status)
    assert respuesta.status == 200, f"OPERACIONES: respondió {respuesta.status}"
    assert admin.locator("main[data-slot=B][data-console=true]").count() == 1, "OPERACIONES: no es la consola del hueco B"
    for bloque in ("alta-de-fuente", "cola", "salud", "filtros"):
        assert admin.locator(f"[data-role={bloque}]").count() == 1, f"OPERACIONES: falta el bloque «{bloque}»"
    cola = admin.locator("[data-role=cola]")
    assert cola.get_attribute("data-jobs-available") == "true", (
        "OPERACIONES: la consola dice que no encuentra la cola de trabajos"
    )
    visibles = int(admin.locator("[data-count=visible]").inner_text())
    filas = admin.locator("tr[data-job-id]").count()
    evidencia.dato("cola", {"visibles": visibles, "filas": filas,
                            "por_estado": texto_visible(admin, "[data-role=por-estado]")})
    if visibles == 0:
        assert admin.locator("[data-state=empty]").count() == 1, "OPERACIONES: cola vacía sin estado vacío"
    else:
        assert filas >= 1, "OPERACIONES: dice tener trabajos visibles y no lista ninguno"
    # El filtro por estado arranca en «Todos» y filtrar no rompe la pantalla.
    assert admin.input_value("form[data-role=filtros] select[name=status]") == "", (
        "OPERACIONES: el filtro de estado no arranca en «Todos»"
    )
    with admin.expect_navigation():
        admin.click("form[data-role=filtros] button[type=submit]")
    assert admin.locator("[data-role=cola]").count() == 1 and admin.locator("[data-state=error]").count() == 0, (
        "OPERACIONES: filtrar con los valores por defecto rompe la consola"
    )
    # Fuentes: lo que dice coincide con lo que la instalación declara.
    alta = admin.locator("[data-role=alta-de-fuente]")
    disponible = alta.get_attribute("data-fuentes-available")
    evidencia.dato("fuentes", {"disponible": disponible, "texto": texto_visible(admin, "[data-role=alta-de-fuente]")[:400]})
    if "ingesta" in cfg.capacidades:
        assert disponible == "true" and admin.locator("[data-role=selector-fuente] option").count() >= 2, (
            "OPERACIONES: la instalación declara fuentes para ingerir y la consola no ofrece ninguna"
        )
    else:
        assert admin.locator("[data-role=solicitar-ingesta]").count() == 0 or disponible == "true", (
            "OPERACIONES: se ofrece solicitar una ingesta sin catálogo de fuentes"
        )
    # Un parámetro de estado inventado se rechaza, no se ignora.
    r = ir(admin, cfg, "/panel/operations?status=inventado")
    assert r.status == 400, f"OPERACIONES: un estado inventado respondió {r.status}, se esperaba 400"


@pytest.mark.sin_grafo
@pytest.mark.requiere("panel_b")
@pytest.mark.cubre("6.M1", "6.M2", "REG-15")
def test_la_consola_muestra_la_ultima_salud_guardada(pagina_como, cfg, evidencia):
    admin = pagina_como("admin")
    ir(admin, cfg, "/admin/health")
    global_ = admin.locator("main p strong").first.inner_text().strip()
    with admin.expect_navigation():
        admin.click("form[action='/admin/health/snapshot'] button")
    ir(admin, cfg, "/panel/operations")
    evidencia.paso(admin, "salud en la consola")
    salud = admin.locator("[data-role=salud]")
    assert salud.get_attribute("data-health-available") == "true", (
        "SALUD_EN_CONSOLA: tras guardar una instantánea la consola dice no tener informe"
    )
    mostrado = admin.locator("[data-health-overall]").get_attribute("data-health-overall")
    evidencia.dato("salud", {"en /admin/health": global_, "en la consola": mostrado})
    assert mostrado == global_, f"SALUD_EN_CONSOLA: la consola dice {mostrado!r} y /admin/health decía {global_!r}"


@pytest.mark.sin_grafo
@pytest.mark.requiere("panel_b", "ingesta")
@pytest.mark.cubre("8.M1", "REG-15")
def test_la_consola_dice_con_que_alcance_entraria_cada_fuente(pagina_como, cfg, evidencia):
    admin = pagina_como("admin")
    ir(admin, cfg, "/panel/operations")
    evidencia.paso(admin, "fuentes y su alcance")
    filas = admin.locator("table[data-role=ambito-de-fuentes] tbody tr")
    assert filas.count() >= 1, "ALCANCE: la consola no dice con qué alcance entraría ninguna fuente"
    incompletas = []
    for i in range(filas.count()):
        celdas = {c: filas.nth(i).locator(f"[data-col={c}]").inner_text().strip()
                  for c in ("juego", "partida", "visibilidad", "regla")}
        if not all(celdas.values()):
            incompletas.append(celdas)
    evidencia.dato("filas incompletas", incompletas)
    assert not incompletas, f"ALCANCE: fuentes sin juego, partida, visibilidad o regla: {incompletas}"


# ---------------------------------------------------------------------------
# Credencial inutilizable: qué ve cada rol (RC1-G02)
# ---------------------------------------------------------------------------

RUTA_DE_SERVIDOR = re.compile(r"/(etc|var|srv|opt|home|root|run)/[\w./-]+")


@pytest.mark.sin_grafo
@pytest.mark.requiere("panel_b", "job_credencial")
@pytest.mark.cubre("E9.RC1-G02", "REG-7", "REG-15")
def test_credencial_inutilizable_en_la_consola_del_administrador(pagina_como, cfg, evidencia):
    assert cfg.job_credencial, "CREDENCIAL: declara S9K_RC_NAV_JOB_CREDENCIAL (trabajo fallido por credencial inutilizable)"
    admin = pagina_como("admin")
    ir(admin, cfg, f"/panel/operations/?solicitado={cfg.job_credencial}")
    evidencia.paso(admin, "consola con el trabajo fallido")
    resultado = admin.locator("[data-role=resultado]")
    assert resultado.count() == 1, "CREDENCIAL: la consola no muestra el desenlace del trabajo"
    datos = {"estado": resultado.get_attribute("data-resultado-estado"),
             "code": resultado.get_attribute("data-resultado-code"),
             "texto": texto_visible(admin, "[data-role=resultado]")}
    evidencia.dato("desenlace", datos)
    assert datos["estado"] == "error" and datos["code"] == "GRAPH_CREDENTIAL_UNUSABLE", (
        f"CREDENCIAL: la consola no dice GRAPH_CREDENTIAL_UNUSABLE: {datos}"
    )
    assert "credencial no se puede usar" in datos["texto"], f"CREDENCIAL: el texto no dice la causa: {datos['texto']!r}"
    assert "no tiene declarada" not in datos["texto"], (
        "CREDENCIAL: el texto dice que la conexión no está declarada, que es OTRA causa"
    )
    assert admin.locator("[data-role=aviso]").count() == 0, (
        "CREDENCIAL: con el trabajo fallido la consola sigue mostrando el acuse de «en la cola»"
    )
    assert not RUTA_DE_SERVIDOR.search(datos["texto"]), "CREDENCIAL: la consola pinta una ruta del servidor"


@pytest.mark.sin_grafo
@pytest.mark.requiere("job_credencial")
@pytest.mark.cubre("E9.RC1-G02", "REG-7", "E7.roles", "REG-15")
@pytest.mark.parametrize("cuenta", ["lector", "revisor", "admin"])
def test_credencial_inutilizable_en_el_detalle_del_trabajo_por_rol(pagina_como, cfg, evidencia, cuenta):
    """El detalle operativo (texto del error, rutas, payload) es del
    administrador; los demás roles ven, como mucho, que el trabajo falló."""
    assert cfg.job_credencial, "CREDENCIAL: declara S9K_RC_NAV_JOB_CREDENCIAL"
    pagina = pagina_como(cuenta)
    respuesta = ir(pagina, cfg, f"/jobs/{cfg.job_credencial}")
    cuerpo = texto_visible(pagina, "main")
    evidencia.paso(pagina, f"detalle del trabajo como {cuenta}", estado=respuesta.status)
    evidencia.dato("lo que ve", {"visible": "job_not_found" not in cuerpo, "texto": cuerpo[:600]})
    if cuenta == "admin":
        assert "job_not_found" not in cuerpo, "CREDENCIAL[admin]: el administrador no ve el trabajo"
        assert "GRAPH_CREDENTIAL_UNUSABLE" in cuerpo, "CREDENCIAL[admin]: el detalle no trae el código del fallo"
        assert "failed" in cuerpo, "CREDENCIAL[admin]: el detalle no dice que el trabajo falló"
        return
    # Lector y revisor: o no lo ven (fuera de su ámbito) o lo ven recortado.
    assert not RUTA_DE_SERVIDOR.search(cuerpo), (
        f"CREDENCIAL[{cuenta}]: el detalle enseña una ruta del servidor a un rol que no administra"
    )
    assert pagina.locator("main .field-label", has_text="Error").count() == 0, (
        f"CREDENCIAL[{cuenta}]: el detalle enseña el texto crudo del error a un rol que no administra"
    )
    for bloque in ("Payload", "Result"):
        tarjeta = pagina.locator("main .card", has=pagina.locator("h2", has_text=bloque))
        if tarjeta.count():
            assert tarjeta.locator("pre").inner_text().strip() in ("—", "null"), (
                f"CREDENCIAL[{cuenta}]: el detalle enseña el {bloque} del trabajo a un rol que no administra"
            )


# ---------------------------------------------------------------------------
# Panel · Review (C)
# ---------------------------------------------------------------------------

@pytest.mark.sin_grafo
@pytest.mark.requiere("panel_c")
@pytest.mark.cubre("8.M4", "REG-15")
@pytest.mark.parametrize("cuenta", ["revisor", "admin"])
def test_panel_de_revision_es_de_solo_lectura_y_cuenta_lo_que_ve(pagina_como, cfg, evidencia, cuenta):
    pagina = pagina_como(cuenta)
    respuesta = ir(pagina, cfg, "/panel/review")
    evidencia.paso(pagina, f"panel de revisión como {cuenta}", estado=respuesta.status)
    assert respuesta.status == 200, f"REVISIÓN[{cuenta}]: respondió {respuesta.status}"
    principal = pagina.locator("main[data-slot=C]")
    assert principal.get_attribute("data-readonly") == "true", "REVISIÓN: el panel no se declara de sólo lectura"
    assert pagina.locator("main form[method=post]").count() == 0, "REVISIÓN: el panel de sólo lectura trae un formulario de escritura"
    if pagina.locator("[data-state=error]").count():
        pytest.fail(f"REVISIÓN[{cuenta}]: el panel no pudo cargar: {texto_visible(pagina, '[data-state=error]')}")
    contadores = {c: pagina.locator(f"[data-role=contadores] [data-count={c}]").inner_text().strip()
                  for c in ("visible", "filtered", "decided")} if pagina.locator("[data-role=contadores]").count() else {}
    filas = pagina.locator("tr[data-proposal-id]").count()
    evidencia.dato("revisión", {"contadores": contadores, "filas": filas})
    if filas == 0:
        vacio = pagina.locator("[data-state=empty]")
        assert vacio.count() == 1, "REVISIÓN: sin propuestas y sin estado vacío"
        assert "leído correctamente" in vacio.inner_text() or "No hay propuestas" in vacio.inner_text(), (
            f"REVISIÓN: el estado vacío no dice si el almacén se leyó: {vacio.inner_text()!r}"
        )
    else:
        assert contadores and int(contadores["filtered"]) >= filas, "REVISIÓN: lista más filas de las que cuenta"
        with pagina.expect_navigation():
            pagina.locator("tr[data-proposal-id] td a").first.click()
        evidencia.paso(pagina, "ficha de una propuesta")
        assert ruta_de(pagina).startswith("/panel/review/item/"), "REVISIÓN: la ficha de la propuesta no abre"


# ---------------------------------------------------------------------------
# Panel · Fuentes (F) y Panel · Entidades (G)
# ---------------------------------------------------------------------------

@pytest.mark.sin_grafo
@pytest.mark.requiere("panel_f")
@pytest.mark.cubre("8.M3b", "REG-15")
def test_panel_de_fuentes_sin_grafo_no_presenta_un_inventario_vacio_como_real(pagina_como, cfg, evidencia):
    if "grafo" in cfg.capacidades:
        pytest.skip("BLOCKED[config]: la instalación declara el grafo; aquí se mide el caso sin él")
    pagina = pagina_como("revisor")
    respuesta = ir(pagina, cfg, "/panel/sources")
    evidencia.paso(pagina, "panel de fuentes sin grafo", estado=respuesta.status)
    cuerpo = texto_visible(pagina)
    evidencia.dato("texto", cuerpo[:600])
    assert pagina.locator("section[data-state=ready]").count() == 0, "FUENTES_SIN_GRAFO: lista fuentes sin base de conocimiento"
    explica = (pagina.locator("[data-state=error]").count() or _aviso_de_proveedor(pagina) or respuesta.status in (409, 503))
    assert explica, f"FUENTES_SIN_GRAFO: «sin fuentes» se presenta sin decir que no hay base de conocimiento: {cuerpo[:300]!r}"


@pytest.mark.necesita_grafo
@pytest.mark.requiere("panel_f")
@pytest.mark.cubre("8.M1", "8.M7", "REG-15")
def test_panel_de_fuentes_lista_las_fuentes_del_conocimiento_aplicado(pagina_como, cfg, evidencia):
    pagina = pagina_como("revisor")
    respuesta = ir(pagina, cfg, "/panel/sources")
    evidencia.paso(pagina, "panel de fuentes", estado=respuesta.status)
    assert respuesta.status == 200, f"FUENTES: respondió {respuesta.status}"
    assert pagina.locator("[data-state=error]").count() == 0, (
        f"FUENTES: no pudo cargar: {texto_visible(pagina, '[data-state=error]') if pagina.locator('[data-state=error]').count() else ''}"
    )
    filas = pagina.locator("tr[data-source-handle]")
    evidencia.dato("fuentes", {"filas": filas.count(), "contadores": texto_visible(pagina, "[data-role=contadores]")})
    assert filas.count() >= 1, (
        "FUENTES: con conocimiento aplicado el panel no lista ninguna fuente: "
        + texto_visible(pagina, "main")[:300]
    )
    etiqueta = filas.first.locator("td a").inner_text().strip()
    # 8.M1: la fuente aparece por su nombre, sin identificadores internos ni rutas.
    assert not RUTA_DE_SERVIDOR.search(texto_visible(pagina, "main")), "FUENTES: el panel publica una ruta del servidor"
    assert not re.fullmatch(r"[0-9a-f]{16,}", etiqueta), f"FUENTES: la fuente se nombra por un identificador: {etiqueta!r}"
    with pagina.expect_navigation():
        filas.first.locator("td a").click()
    evidencia.paso(pagina, "ficha de la fuente")
    assert pagina.locator("main[data-source-handle]").count() == 1, "FUENTES: la ficha de la fuente no abre"
    assert int(pagina.locator("[data-role=resumen] [data-count=entities]").inner_text()) >= 1, (
        "FUENTES: la ficha no cuenta ninguna entidad de una fuente listada"
    )


@pytest.mark.sin_grafo
@pytest.mark.requiere("panel_g")
@pytest.mark.cubre("8.M3b", "REG-15")
def test_panel_de_entidades_sin_grafo_no_presenta_un_listado_vacio_como_real(pagina_como, cfg, evidencia):
    if "grafo" in cfg.capacidades:
        pytest.skip("BLOCKED[config]: la instalación declara el grafo; aquí se mide el caso sin él")
    pagina = pagina_como("lector")
    respuesta = ir(pagina, cfg, "/panel/entities")
    evidencia.paso(pagina, "panel de entidades sin grafo", estado=respuesta.status)
    cuerpo = texto_visible(pagina)
    evidencia.dato("texto", cuerpo[:600])
    assert pagina.locator("tr[data-entity-id]").count() == 0, "ENTIDADES_SIN_GRAFO: lista entidades sin base de conocimiento"
    explica = (pagina.locator("[data-state=error]").count() or _aviso_de_proveedor(pagina) or respuesta.status in (409, 503))
    assert explica, f"ENTIDADES_SIN_GRAFO: «sin entidades» se presenta sin decir que no hay base de conocimiento: {cuerpo[:300]!r}"


@pytest.mark.necesita_grafo
@pytest.mark.requiere("panel_g")
@pytest.mark.cubre("9.13", "8.M8", "REG-15")
@pytest.mark.parametrize("cuenta", ["lector", "revisor", "admin"])
def test_panel_de_entidades_lista_y_abre_fichas(pagina_como, cfg, evidencia, cuenta):
    pagina = pagina_como(cuenta)
    respuesta = ir(pagina, cfg, "/panel/entities")
    evidencia.paso(pagina, f"panel de entidades como {cuenta}", estado=respuesta.status)
    assert respuesta.status == 200, f"ENTIDADES[{cuenta}]: respondió {respuesta.status}"
    assert pagina.locator("main[data-slot=G][data-readonly=true]").count() == 1, "ENTIDADES: no es el hueco G de sólo lectura"
    assert pagina.locator("main form[method=post]").count() == 0, "ENTIDADES: trae un formulario de escritura"
    contadores = {c: int(pagina.locator(f"[data-role=contadores] [data-count={c}]").inner_text())
                  for c in ("visible", "filtered", "shown")}
    filas = pagina.locator("tr[data-entity-id]")
    evidencia.dato("entidades", {"contadores": contadores, "filas": filas.count()})
    assert contadores["shown"] == filas.count(), "ENTIDADES: «en esta página» no coincide con las filas pintadas"
    assert contadores["visible"] >= contadores["filtered"] >= contadores["shown"], (
        f"ENTIDADES: recuentos incoherentes: {contadores}"
    )
    if cuenta == "admin":
        assert filas.count() >= 1, "ENTIDADES[admin]: con conocimiento aplicado el administrador no ve ninguna entidad"
    if filas.count():
        with pagina.expect_navigation():
            filas.first.locator("td a").click()
        evidencia.paso(pagina, "ficha de entidad")
        assert pagina.locator("section[data-state=ready][data-entity-id]").count() == 1, "ENTIDADES: la ficha no abre"
        for bloque in ("hechos", "relaciones"):
            assert pagina.locator(f"section[data-role={bloque}]").count() == 1, f"ENTIDADES: la ficha no trae «{bloque}»"


@pytest.mark.necesita_grafo
@pytest.mark.requiere("panel_g")
@pytest.mark.cubre("E7.ambito", "E8.aislamiento", "REG-15")
def test_un_lector_no_ve_mas_entidades_que_el_administrador(pagina_como, cfg, evidencia):
    """Coherencia mínima de la autorización sobre el conocimiento real: lo que
    ve el lector es un subconjunto de lo que ve el administrador."""
    def _ids(cuenta: str) -> set[str]:
        pagina = pagina_como(cuenta)
        ir(pagina, cfg, "/panel/entities?limit=200")
        evidencia.paso(pagina, f"entidades de {cuenta}")
        return set(pagina.eval_on_selector_all("tr[data-entity-id]", "els => els.map(e => e.dataset.entityId)"))

    del_admin, del_lector = _ids("admin"), _ids("lector")
    evidencia.dato("recuentos", {"admin": len(del_admin), "lector": len(del_lector)})
    assert del_admin, "SUBCONJUNTO: PRECONDICIÓN: el administrador no ve ninguna entidad"
    assert del_lector <= del_admin, (
        f"SUBCONJUNTO: el lector ve entidades que el administrador no: {sorted(del_lector - del_admin)[:5]}"
    )
