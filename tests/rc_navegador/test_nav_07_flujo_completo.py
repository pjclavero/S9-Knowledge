# -*- coding: utf-8 -*-
"""Flujo completo por pantalla: ingesta → revisión → preparar → APPLY →
resultado → procedencia → búsqueda.

Contrato: E8, pasos manuales 8.M1–8.M8; regresión 2 (ingesta más allá de la
observación del grafo) y regresión 15 (navegador). TODO este módulo necesita
Neo4j: sin la capacidad «grafo» queda PENDING y no cuenta como verde.

Es UN recorrido en varios pasos, en orden, y cada paso deja en un fichero de
estado (fuera del repositorio) lo que el siguiente necesita. Si un paso falla,
los siguientes fallan diciendo qué precondición les falta: no se saltan.

Ventana del recorrido (para poder intercalar el negativo de aislamiento 8.M9,
que exige reconfigurar la instalación entre «preparar» y «APPLY»):

    S9K_RC_NAV_FLUJO_DESDE = ingesta (por defecto) | aplicar
    S9K_RC_NAV_FLUJO_HASTA = busqueda (por defecto) | sellado

Los pasos fuera de la ventana quedan BLOCKED con ese motivo.

Los formularios se envían pulsando sus botones en un navegador real: los
``<select>`` de corrección se quedan en su opción por defecto («Mantener»),
que es justo lo que la sonda HTTP de la ronda anterior hacía mal (R-09).
"""
from __future__ import annotations

import json
import os
import re
import time
from urllib.parse import parse_qs, urlparse

import pytest

from soporte import ir, ruta_de, texto_visible

pytestmark = [
    pytest.mark.necesita_grafo,
    pytest.mark.requiere("panel_b", "panel_c", "ingesta"),
]

ETAPAS = ("ingesta", "worker", "revision", "altas", "sellado", "aplicar", "resultado", "procedencia", "busqueda")


def _fichero(cfg):
    return cfg.estado_dir / "flujo.json"


def _leer(cfg) -> dict:
    ruta = _fichero(cfg)
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}


def _guardar(cfg, estado: dict) -> None:
    ruta = _fichero(cfg)
    descriptor = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def _ventana(cfg, etapa: str) -> None:
    """Deja BLOCKED el paso si cae fuera de la ventana pedida."""
    for nombre, valor in (("DESDE", cfg.flujo_desde), ("HASTA", cfg.flujo_hasta)):
        if valor not in ETAPAS:
            pytest.fail(f"FLUJO: S9K_RC_NAV_FLUJO_{nombre}={valor!r} no es una etapa: {ETAPAS}")
    i = ETAPAS.index(etapa)
    if i < ETAPAS.index(cfg.flujo_desde) or i > ETAPAS.index(cfg.flujo_hasta):
        pytest.skip(
            f"BLOCKED[fase]: la etapa «{etapa}» queda fuera de la ventana pedida "
            f"({cfg.flujo_desde}…{cfg.flujo_hasta})"
        )


def _exigir(cfg, clave: str, etapa: str):
    estado = _leer(cfg)
    if not estado.get(clave):
        pytest.fail(f"FLUJO[{etapa}]: PRECONDICIÓN: un paso anterior no dejó «{clave}»")
    return estado


def _consola(pagina, cfg, job_id: str):
    return ir(pagina, cfg, f"/panel/operations/?solicitado={job_id}")


def _aviso(pagina) -> dict:
    seccion = pagina.locator("[data-role=aviso]")
    if seccion.count() == 0:
        return {}
    return {
        "tipo": seccion.get_attribute("data-aviso-tipo"),
        "code": seccion.get_attribute("data-aviso-code") or seccion.get_attribute("data-aviso-codigo"),
        "texto": " ".join(seccion.inner_text().split()),
    }


# ---------------------------------------------------------------------------
# 8.M1 / 8.M2 — la fuente está y se solicita su ingesta desde el panel
# ---------------------------------------------------------------------------

@pytest.mark.cubre("8.M2", "REG-2", "REG-15")
def test_flujo_1_solicitar_la_ingesta_desde_el_panel(pagina_como, cfg, evidencia):
    _ventana(cfg, "ingesta")
    pagina = pagina_como("admin")
    respuesta = ir(pagina, cfg, "/panel/operations")
    evidencia.paso(pagina, "consola de operaciones", estado=respuesta.status)
    assert respuesta.status == 200, f"FLUJO[ingesta]: /panel/operations respondió {respuesta.status}"
    alta = pagina.locator("[data-role=alta-de-fuente]")
    assert alta.get_attribute("data-fuentes-available") == "true", (
        "FLUJO[ingesta]: el panel dice que no puede consultar el catálogo de fuentes"
    )
    opciones = pagina.eval_on_selector_all(
        "[data-role=selector-fuente] option",
        "els => els.map(o => ({valor: o.value, texto: o.textContent.replace(/\\s+/g, ' ').trim()}))",
    )
    evidencia.dato("fuentes ofrecidas", opciones)
    reales = [o for o in opciones if o["valor"]]
    assert reales, "FLUJO[ingesta]: el selector no ofrece ninguna fuente"
    assert pagina.input_value("[data-role=selector-fuente]") == "", (
        "FLUJO[ingesta]: el selector no arranca en «Elige una fuente…»"
    )
    if cfg.fuente:
        elegidas = [o for o in reales if cfg.fuente.lower() in (o["texto"] + " " + o["valor"]).lower()]
        assert len(elegidas) == 1, (
            f"FLUJO[ingesta]: S9K_RC_NAV_FUENTE={cfg.fuente!r} casa con {len(elegidas)} fuentes, no con una"
        )
        elegida = elegidas[0]
    else:
        elegida = reales[0]
    # 8.M1: la fuente se ofrece por su nombre humano, no por un identificador.
    assert not re.fullmatch(r"[0-9a-f-]{16,}", elegida["texto"].split(" (")[0]), (
        f"FLUJO[ingesta]: la fuente se ofrece por un identificador interno: {elegida['texto']!r}"
    )
    pagina.select_option("[data-role=selector-fuente]", value=elegida["valor"])
    evidencia.paso(pagina, "fuente elegida")
    with pagina.expect_navigation():
        pagina.click("[data-role=solicitar-ingesta]")
    evidencia.paso(pagina, "ingesta solicitada")
    consulta = parse_qs(urlparse(pagina.url).query)
    aviso = _aviso(pagina)
    evidencia.dato("acuse", {"consulta": consulta, "aviso": aviso})
    assert consulta.get("solicitado"), (
        f"FLUJO[ingesta]: tras solicitar, la consola no identifica el trabajo; aviso={aviso}"
    )
    job_id = consulta["solicitado"][0]
    assert not consulta.get("aviso") or aviso.get("tipo") != "error", (
        f"FLUJO[ingesta]: la solicitud terminó en error: {aviso}"
    )
    _guardar(cfg, {"job_id": job_id, "fuente": elegida["texto"], "solicitado_en": time.time()})


# ---------------------------------------------------------------------------
# 8.M3 — el worker termina la ingesta y la consola lo dice
# ---------------------------------------------------------------------------

@pytest.mark.cubre("8.M3", "6.M3", "REG-2", "REG-15")
def test_flujo_2_el_worker_termina_y_la_consola_lo_muestra(pagina_como, cfg, evidencia):
    _ventana(cfg, "worker")
    estado = _exigir(cfg, "job_id", "worker")
    pagina = pagina_como("admin")
    limite = time.time() + cfg.espera_worker_s
    vistos = []
    while True:
        _consola(pagina, cfg, estado["job_id"])
        resultado = pagina.locator("[data-role=resultado]")
        if resultado.count():
            break
        en_cola = pagina.locator("[data-trabajo-estado]")
        vistos.append(en_cola.inner_text().strip() if en_cola.count() else "sin acuse")
        if time.time() > limite:
            evidencia.paso(pagina, "worker sin terminar")
            pytest.fail(
                f"FLUJO[worker]: el trabajo no tuvo desenlace en {cfg.espera_worker_s} s; "
                f"estados vistos: {sorted(set(vistos))}"
            )
        pagina.wait_for_timeout(3000)
    evidencia.paso(pagina, "desenlace de la ingesta")
    datos = {
        "estado": resultado.get_attribute("data-resultado-estado"),
        "code": resultado.get_attribute("data-resultado-code"),
        "texto": " ".join(resultado.inner_text().split())[:600],
        "estados_previos": sorted(set(vistos)),
    }
    evidencia.dato("resultado de la ingesta", datos)
    assert datos["estado"] == "ok", f"FLUJO[worker]: la ingesta no terminó bien: {datos}"
    enlace = pagina.locator("[data-role=enlace-revision]")
    assert enlace.count() == 1, "FLUJO[worker]: la consola no enlaza las propuestas de esta corrida"
    propuestas = enlace.get_attribute("data-revision-propuestas")
    assert propuestas and int(propuestas) >= 3, (
        f"FLUJO[worker]: la corrida dejó {propuestas!r} propuestas; el recorrido necesita al menos 3 "
        "(aprobar dos y rechazar una)"
    )
    estado.update({"propuestas": int(propuestas),
                   "enlace_revision": enlace.locator("a").get_attribute("href")})
    _guardar(cfg, estado)


# ---------------------------------------------------------------------------
# 8.M4 / 8.M5 — las propuestas de ESA corrida, aprobar, rechazar y deshacer
# ---------------------------------------------------------------------------

def _pendientes(pagina) -> int:
    return int(pagina.locator("[data-remaining]").first.inner_text().strip())


def _decidir(pagina, accion: str) -> None:
    articulo = pagina.locator("article[data-review-item]:not([hidden])")
    assert articulo.count() == 1, "FLUJO[revision]: no hay exactamente una propuesta a la vista"
    # R-09: en un navegador real los selectores de corrección están en su
    # opción por defecto. Se comprueba, no se supone.
    for nombre in ("predicate", "direction", "negated"):
        assert articulo.locator(f"select[name={nombre}]").input_value() == "", (
            f"FLUJO[revision]: el selector «{nombre}» no arranca en «Mantener»"
        )
    with pagina.expect_navigation():
        articulo.locator(f"button[data-action={accion}]").click()


@pytest.mark.cubre("8.M4", "8.M5", "REG-2", "REG-15")
def test_flujo_3_revisar_aprobar_rechazar_y_deshacer(pagina_como, cfg, evidencia):
    _ventana(cfg, "revision")
    estado = _exigir(cfg, "enlace_revision", "revision")
    pagina = pagina_como("admin")
    _consola(pagina, cfg, estado["job_id"])
    with pagina.expect_navigation():
        pagina.click("[data-role=enlace-revision] a")
    evidencia.paso(pagina, "cola de revisión de la corrida")
    assert ruta_de(pagina).rstrip("/") == "/v3/review", f"FLUJO[revision]: el enlace llevó a {ruta_de(pagina)}"
    assert pagina.locator(f"[data-filtro-corrida='{estado['job_id']}']").count() == 1, (
        "FLUJO[revision]: la pantalla no dice estar filtrada por esta corrida"
    )
    assert pagina.locator("[data-state=unavailable]").count() == 0, (
        "FLUJO[revision]: la cola de revisión se declara no disponible"
    )
    iniciales = _pendientes(pagina)
    evidencia.dato("pendientes al empezar", iniciales)
    assert iniciales >= 3, f"FLUJO[revision]: hay {iniciales} propuestas pendientes de esta corrida, se necesitan 3"
    literal = pagina.locator("article[data-review-item]:not([hidden]) blockquote mark").inner_text().strip()
    assert literal, "FLUJO[revision]: la propuesta no enseña el texto literal que la sostiene"

    _decidir(pagina, "approve")
    evidencia.paso(pagina, "primera aprobada")
    assert _pendientes(pagina) == iniciales - 1, "FLUJO[revision]: aprobar no descontó una pendiente"
    _decidir(pagina, "approve")
    evidencia.paso(pagina, "segunda aprobada")
    assert _pendientes(pagina) == iniciales - 2, "FLUJO[revision]: la segunda aprobación no descontó"
    _decidir(pagina, "reject")
    evidencia.paso(pagina, "tercera rechazada")
    assert _pendientes(pagina) == iniciales - 3, "FLUJO[revision]: rechazar no descontó una pendiente"

    # Deshacer la última (el rechazo) la devuelve a la cola; se vuelve a rechazar.
    with pagina.expect_navigation():
        pagina.click("form[action='/v3/review/undo'] button")
    evidencia.paso(pagina, "rechazo deshecho")
    assert _pendientes(pagina) == iniciales - 2, "FLUJO[revision]: «Deshacer última» no devolvió la propuesta a la cola"
    _decidir(pagina, "reject")
    evidencia.paso(pagina, "rechazada de nuevo")
    assert _pendientes(pagina) == iniciales - 3, "FLUJO[revision]: el segundo rechazo no descontó"

    estado.update({"aprobadas": 2, "rechazadas": 1, "revisado": True})
    _guardar(cfg, estado)


# ---------------------------------------------------------------------------
# Altas de entidad: la segunda decisión
# ---------------------------------------------------------------------------

@pytest.mark.cubre("extra.altas", "REG-2", "REG-15")
def test_flujo_4_dar_el_visto_bueno_a_las_entidades_nuevas(pagina_como, cfg, evidencia):
    _ventana(cfg, "altas")
    estado = _exigir(cfg, "revisado", "altas")
    pagina = pagina_como("admin")
    _consola(pagina, cfg, estado["job_id"])
    evidencia.paso(pagina, "consola tras la revisión")
    plan = pagina.locator("[data-role=plan-revisado]")
    assert plan.count() == 1, "FLUJO[altas]: la consola no muestra «Lo aprobado de esta ingesta»"
    assert plan.get_attribute("data-plan-aprobadas") == "2", (
        f"FLUJO[altas]: la consola cuenta {plan.get_attribute('data-plan-aprobadas')} aprobadas; se aprobaron 2"
    )
    bloque = pagina.locator("[data-role=altas-de-entidad]")
    assert bloque.count() == 1, "FLUJO[altas]: la consola no dice nada de las entidades nuevas de esta ingesta"
    evidencia.dato("altas", {a: bloque.get_attribute(f"data-altas-{a}")
                             for a in ("declarado", "total", "pendientes", "aprobadas", "omitidas")})
    assert bloque.get_attribute("data-altas-declarado") == "true", (
        "FLUJO[altas]: la ingesta no dejó constancia de sus entidades nuevas"
    )
    dadas = 0
    if int(bloque.get_attribute("data-altas-pendientes") or 0) > 0:
        with pagina.expect_navigation():
            pagina.click("[data-role=enlace-altas]")
        evidencia.paso(pagina, "pantalla de entidades nuevas")
        for _ in range(50):
            pendientes = pagina.locator("[data-role=alta][data-alta-aprobada=false]")
            if pendientes.count() == 0:
                break
            alta = pendientes.first
            tipo = alta.locator("input[name=tipo]")
            assert tipo.count() == 0, (
                "FLUJO[altas]: una entidad nueva llega sin tipo y la pantalla pide escribirlo a mano; "
                f"entidad {alta.get_attribute('data-alta-id')!r}"
            )
            with pagina.expect_navigation():
                alta.locator("form[data-role=form-alta] button").click()
            aviso = _aviso(pagina)
            assert aviso.get("tipo") != "error", f"FLUJO[altas]: el visto bueno terminó en error: {aviso}"
            dadas += 1
        evidencia.paso(pagina, "entidades nuevas con visto bueno")
        assert pagina.locator("[data-role=alta][data-alta-aprobada=false]").count() == 0, (
            "FLUJO[altas]: quedan entidades nuevas sin visto bueno"
        )
    estado.update({"altas_dadas": dadas, "altas": True})
    _guardar(cfg, estado)


# ---------------------------------------------------------------------------
# 8.M6 — preparar (sellar) y APLICAR
# ---------------------------------------------------------------------------

@pytest.mark.cubre("8.M6a", "REG-2", "REG-15")
def test_flujo_5_preparar_lo_aprobado(pagina_como, cfg, evidencia):
    _ventana(cfg, "sellado")
    estado = _exigir(cfg, "altas", "sellado")
    pagina = pagina_como("admin")
    _consola(pagina, cfg, estado["job_id"])
    evidencia.paso(pagina, "antes de preparar")
    assert pagina.locator("[data-role=sellar-plan]").count() == 1, (
        "FLUJO[sellado]: la consola no ofrece «Preparar lo aprobado»"
    )
    with pagina.expect_navigation():
        pagina.click("[data-role=sellar-plan]")
    evidencia.paso(pagina, "tras preparar")
    aviso = _aviso(pagina)
    plan = pagina.locator("[data-role=plan-revisado]")
    datos = {"aviso": aviso, "plan_estado": plan.get_attribute("data-plan-estado"),
             "operaciones": plan.get_attribute("data-plan-operaciones")}
    evidencia.dato("sellado", datos)
    assert (aviso.get("code") or "").startswith("PLAN_SEALED"), f"FLUJO[sellado]: preparar no selló el plan: {aviso}"
    assert pagina.locator("[data-plan-desenlace=sealed]").count() == 1, (
        "FLUJO[sellado]: la consola no muestra el plan como preparado y listo"
    )
    estado.update({"sellado": True, "aviso_sellado": aviso.get("code")})
    _guardar(cfg, estado)
    # El sellado limpio se juzga aparte del recorrido: un sellado con salvedad
    # (sin proyección, sin altas, incompleto) permite seguir, pero no es un
    # sellado limpio y se dice.
    assert aviso.get("code") == "PLAN_SEALED", (
        f"FLUJO[sellado]: el plan se selló CON SALVEDAD ({aviso.get('code')}): {aviso.get('texto')}"
    )


@pytest.mark.cubre("8.M6b", "REG-2", "REG-15")
@pytest.mark.requiere("apply")
def test_flujo_6_aplicar_al_conocimiento(pagina_como, cfg, evidencia):
    _ventana(cfg, "aplicar")
    estado = _exigir(cfg, "sellado", "aplicar")
    pagina = pagina_como("admin")
    _consola(pagina, cfg, estado["job_id"])
    evidencia.paso(pagina, "antes de aplicar")
    plan = pagina.locator("[data-role=plan-revisado]")
    assert plan.get_attribute("data-plan-habilitado") == "true", (
        "FLUJO[aplicar]: la consola dice que este despliegue no tiene habilitada la escritura"
    )
    assert pagina.locator("[data-role=aplicar-plan]").count() == 1, (
        "FLUJO[aplicar]: la consola no ofrece «Añadir al conocimiento»"
    )
    with pagina.expect_navigation():
        pagina.click("[data-role=aplicar-plan]")
    evidencia.paso(pagina, "tras aplicar")
    aviso = _aviso(pagina)
    plan = pagina.locator("[data-role=plan-revisado]")
    datos = {"aviso": aviso, "plan_estado": plan.get_attribute("data-plan-estado"),
             "avisos_del_plan": pagina.eval_on_selector_all(
                 "[data-plan-aviso]", "els => els.map(e => e.dataset.planAviso)")}
    evidencia.dato("aplicación", datos)
    assert aviso.get("code") == "PLAN_APPLIED", f"FLUJO[aplicar]: aplicar no terminó en PLAN_APPLIED: {aviso}"
    assert plan.get_attribute("data-plan-estado") == "applied", (
        f"FLUJO[aplicar]: el plan quedó en estado {plan.get_attribute('data-plan-estado')!r}"
    )
    assert datos["avisos_del_plan"] == [], f"FLUJO[aplicar]: la aplicación dejó avisos: {datos['avisos_del_plan']}"
    # Aplicado una vez, no se vuelve a ofrecer.
    assert pagina.locator("[data-role=aplicar-plan]").count() == 0, (
        "FLUJO[aplicar]: tras aplicar, la consola sigue ofreciendo «Añadir al conocimiento»"
    )
    estado.update({"aplicado": True})
    _guardar(cfg, estado)


# ---------------------------------------------------------------------------
# 8.M7 — resultado, procedencia y evidencia literal
# ---------------------------------------------------------------------------

@pytest.mark.cubre("8.M7", "9.M2", "REG-2", "REG-15")
@pytest.mark.requiere("apply", "resultado")
def test_flujo_7_resultado_de_la_ejecucion(pagina_como, cfg, evidencia):
    _ventana(cfg, "resultado")
    estado = _exigir(cfg, "aplicado", "resultado")
    pagina = pagina_como("admin")
    _consola(pagina, cfg, estado["job_id"])
    enlace = pagina.locator("[data-role=ver-lo-aplicado]")
    evidencia.paso(pagina, "consola con el plan aplicado")
    assert enlace.count() == 1, (
        "FLUJO[resultado]: la consola no enlaza «Ver qué se añadió y de dónde sale»; "
        f"dice: {texto_visible(pagina, '[data-role=plan-revisado]')[:300]}"
    )
    with pagina.expect_navigation():
        enlace.click()
    evidencia.paso(pagina, "resultado de la ejecución")
    assert pagina.locator("main[data-page=resultado]").count() == 1, (
        f"FLUJO[resultado]: el enlace no llevó a la pantalla de resultado ({ruta_de(pagina)})"
    )
    recuentos = {}
    for bloque in ("entidades", "relaciones", "hechos"):
        seccion = pagina.locator(f"section[data-role={bloque}]")
        recuentos[bloque] = {
            "estado": seccion.get_attribute("data-state"),
            "total": seccion.locator("h2 [data-count]").get_attribute("data-count"),
        }
    evidencia.dato("recuentos del resultado", recuentos)
    assert int(recuentos["entidades"]["total"] or 0) >= 1, f"FLUJO[resultado]: sin entidades afectadas: {recuentos}"
    assert int(recuentos["hechos"]["total"] or 0) == 2, (
        f"FLUJO[resultado]: se aprobaron 2 propuestas y el resultado registra {recuentos['hechos']['total']} hechos"
    )
    entidad = pagina.locator("section[data-role=entidades] li a").first.inner_text().strip()
    estado.update({"resultado_url": urlparse(pagina.url).path + "?" + urlparse(pagina.url).query,
                   "entidad": entidad, "recuentos": recuentos})
    _guardar(cfg, estado)


@pytest.mark.cubre("8.M7", "REG-22", "REG-2")
@pytest.mark.requiere("apply", "resultado")
def test_flujo_7b_el_resultado_trae_relaciones(cfg, evidencia):
    """RC2-05: la primera ingesta dejaba «Relaciones añadidas (0)»."""
    _ventana(cfg, "resultado")
    estado = _exigir(cfg, "recuentos", "resultado")
    relaciones = estado["recuentos"]["relaciones"]
    evidencia.dato("relaciones", relaciones)
    assert int(relaciones["total"] or 0) >= 1, (
        f"FLUJO[relaciones]: el resultado no trae ninguna relación añadida ({relaciones}); "
        f"sellado: {estado.get('aviso_sellado')}"
    )


@pytest.mark.cubre("8.M7", "REG-2", "REG-15")
@pytest.mark.requiere("apply", "resultado")
def test_flujo_8_procedencia_y_evidencia_literal(pagina_como, cfg, evidencia):
    _ventana(cfg, "procedencia")
    estado = _exigir(cfg, "resultado_url", "procedencia")
    pagina = pagina_como("admin")
    ir(pagina, cfg, estado["resultado_url"])
    hechos = pagina.locator("section[data-role=hechos] li[data-assertion-id]")
    assert hechos.count() >= 1, "FLUJO[procedencia]: el resultado no lista hechos"
    with pagina.expect_navigation():
        hechos.first.locator("[data-role=ver-procedencia]").click()
    evidencia.paso(pagina, "procedencia del hecho")
    assert pagina.locator("main[data-page=evidencia]").count() == 1, (
        f"FLUJO[procedencia]: «ver de dónde sale» llevó a {ruta_de(pagina)}"
    )
    fragmentos = pagina.locator("[data-role=fragmento]")
    assert fragmentos.count() >= 1, (
        "FLUJO[procedencia]: el hecho no enseña ninguna evidencia: "
        + texto_visible(pagina, "section[data-role=evidencia]")[:300]
    )
    literal = fragmentos.first.locator("[data-field=literal]")
    assert literal.locator("[data-state=empty]").count() == 0 and literal.inner_text().strip(), (
        "FLUJO[procedencia]: el fragmento no guarda texto literal"
    )
    fuente = fragmentos.first.locator("[data-role=fuente]")
    assert fuente.get_attribute("data-state") != "missing", "FLUJO[procedencia]: no consta la fuente del fragmento"
    nombre = fuente.locator("[data-field=nombre]").inner_text().strip()
    evidencia.dato("evidencia", {"literal": literal.inner_text().strip()[:300], "fuente": nombre})
    assert nombre, "FLUJO[procedencia]: la fuente del fragmento no tiene nombre"
    # Y se puede volver al resultado.
    with pagina.expect_navigation():
        pagina.click("[data-role=volver]")
    assert pagina.locator("main[data-page=resultado]").count() == 1, "FLUJO[procedencia]: «Volver» no vuelve al resultado"
    estado.update({"procedencia": True})
    _guardar(cfg, estado)


# ---------------------------------------------------------------------------
# 8.M8 — búsqueda
# ---------------------------------------------------------------------------

@pytest.mark.cubre("8.M8", "REG-17", "REG-15")
@pytest.mark.requiere("apply", "resultado", "panel_g")
def test_flujo_9_la_busqueda_encuentra_lo_aplicado(pagina_como, cfg, evidencia):
    _ventana(cfg, "busqueda")
    estado = _exigir(cfg, "entidad", "busqueda")
    termino = cfg.termino or estado["entidad"]
    pagina = pagina_como("admin")
    ir(pagina, cfg, "/panel/entities")
    pagina.fill("form[data-role=filtros] input[name=q]", termino)
    with pagina.expect_navigation():
        pagina.click("form[data-role=filtros] button[type=submit]")
    evidencia.paso(pagina, "búsqueda en el panel de entidades")
    filas = pagina.locator("section[data-state=ready] tr[data-entity-id]")
    evidencia.dato("búsqueda", {"termino": termino, "filas": filas.count(),
                                "contadores": texto_visible(pagina, "[data-role=contadores]")})
    assert filas.count() >= 1, f"FLUJO[busqueda]: buscar {termino!r} no devuelve ninguna entidad"
    with pagina.expect_navigation():
        filas.first.locator("a").click()
    evidencia.paso(pagina, "ficha de la entidad encontrada")
    assert pagina.locator("section[data-state=ready][data-entity-id]").count() == 1, (
        "FLUJO[busqueda]: la ficha de la entidad encontrada no se pinta"
    )
    # Un término que no existe no devuelve nada (la búsqueda discrimina).
    ir(pagina, cfg, "/panel/entities?q=zzz-no-existe-rc3nav")
    evidencia.paso(pagina, "búsqueda sin resultados")
    assert pagina.locator("tr[data-entity-id]").count() == 0, "FLUJO[busqueda]: un término inexistente devuelve entidades"
    assert pagina.locator("[data-state=empty]").count() == 1, "FLUJO[busqueda]: sin resultados no se pinta el estado vacío"
