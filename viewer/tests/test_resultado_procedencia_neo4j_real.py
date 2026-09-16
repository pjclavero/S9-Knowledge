# -*- coding: utf-8 -*-
"""LA PRUEBA INSIGNIA: partir de un apply REAL y llegar a la evidencia.

AQUI NO SE SIEMBRA NI UNA LINEA DE CYPHER DE ESCRITURA
======================================================
Todo lo que este fichero mide lo escribio el producto por su ruta de operador:
``bootstrap_writer_schema`` + ``ingest_cli.run_ingest(..., apply=True)``
--fichero -> reconciliacion -> altas aprobadas -> apply, con procedencia--. El
unico Cypher de este fichero es de CENSO (``MATCH ... RETURN count``) y el del
borrado de su propio workspace al acabar.

    fuente real -> ingesta -> review -> apply REAL -> Neo4j
      -> provider REAL -> authz REAL -> HTTP -> la pantalla del operador

El recorrido que se exige es el del encargo, entero y por HTTP:

    abrir el resultado de ESA ejecucion
     -> comprobar que cambios produjo
     -> abrir un hecho
     -> seguir su procedencia
     -> llegar a evidencia/fuente
     -> verificar que corresponde al apply CORRECTO

LO QUE NO SE RELAJA
===================
LO NO AUTORIZADO SIGUE SIN VERSE, y el cero de quien no tiene derechos SOLO
prueba politica porque CONVIVE con un admin que SI ve exactamente el mismo
material. Sin esa pareja, "no veo nada" y "la base esta vacia" son
indistinguibles y el verde no significa nada.

El lector sin derechos es un ``reviewer`` LEGITIMO, no un anonimo ni un
``viewer``: pasa la puerta de ROL (asi que su cero no esta sobredeterminado por
un 403) y no tiene ``can_view_secret``, que es lo que el writer estampa por
defecto (``visibility='secret'``, ``visibility_source='default_fail_closed'``).
Su cero es de POLITICA DE CONTENIDO, que es justo lo que se quiere medir.

NUNCA PRODUCCION. Solo instancia efimera y local.

COMO CORRER ESTO
================
    docker run --rm -d --name <tuyo> -p 127.0.0.1:17687:7687 \\
        -e NEO4J_AUTH=neo4j/<clave> neo4j:5.26-community
    NEO4J_TEST_URI=bolt://127.0.0.1:17687 NEO4J_TEST_PASSWORD=<clave> \\
        python -m pytest viewer/tests/test_resultado_procedencia_neo4j_real.py

Sin esas variables la suite se SALTA, y un ``skipped`` NO es un verde.
"""
from __future__ import annotations

import json
import os
import pathlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

URI = os.environ.get("NEO4J_TEST_URI")
USER = os.environ.get("NEO4J_TEST_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD")

pytestmark = pytest.mark.skipif(
    not URI or not PASSWORD,
    reason="sin Neo4j efimero (define NEO4J_TEST_URI y NEO4J_TEST_PASSWORD)",
)

pytest.importorskip("jsonschema")
pytest.importorskip("neo4j")

ANFITRIONES_EFIMEROS = frozenset({"localhost", "127.0.0.1", "::1", "neo4j"})


def _exigir_efimera(uri: str) -> None:
    """Lista BLANCA. Esta suite BORRA nodos: apuntarla a produccion no puede
    depender de que nadie se equivoque de variable."""
    host = (urlparse(uri).hostname or "").strip().lower()
    if host not in ANFITRIONES_EFIMEROS:
        raise RuntimeError(
            f"NEO4J_TEST_URI apunta a {host!r}, que no es una base efimera. "
            f"Anfitriones admitidos: {sorted(ANFITRIONES_EFIMEROS)}."
        )


RAIZ = pathlib.Path(__file__).resolve().parents[2]
EJEMPLOS = RAIZ / "examples" / "ingesta-v3"
FUENTE = EJEMPLOS / "nota-cofradia-de-ambar.md"
PERFIL = EJEMPLOS / "perfil-operador.json"
CATALOGO = EJEMPLOS / "catalogo-workspace.json"

#: NO SE ELIGE: lo declara el material de ejemplo del producto. Inventarse otro
#: workspace hace que la ingesta trabaje en otro sitio y el plan salga vacio.
WS = json.loads(PERFIL.read_text())["workspace"]
OPERADOR = "carril-c-resultado"
#: Workspace APARTE para el escenario "apply SIN paquete de procedencia". No se
#: reutiliza el de arriba: aplicar dos veces el mismo plan en el mismo
#: workspace es un no-op idempotente, asi que no se podria observar nada.
WS_SIN_PROC = WS + "-sin-procedencia"
CLAVE_USUARIO = "CarrilCResultado_1234567890!"
AHORA = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

FLAG = "S9K_PANEL_RESULTADO_ENABLED"


# ===========================================================================
# EL PRODUCTO ESCRIBE. Ruta de operador, nada sintetico.
# ===========================================================================
@pytest.fixture(scope="module")
def driver():
    from neo4j import GraphDatabase

    _exigir_efimera(URI)
    drv = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    drv.verify_connectivity()
    # Se lleva SOLO lo suyo, antes y despues: comparte instancia con otras
    # suites de contrato y no puede pisarles el material.
    for ws in (WS, WS_SIN_PROC):
        with drv.session() as s:
            s.run("MATCH (n) WHERE n.workspace = $ws DETACH DELETE n", {"ws": ws})
    yield drv
    for ws in (WS, WS_SIN_PROC):
        with drv.session() as s:
            s.run("MATCH (n) WHERE n.workspace = $ws DETACH DELETE n", {"ws": ws})
    drv.close()


@pytest.fixture(scope="module")
def apply_real(driver):
    """UN apply REAL por la ruta del producto. Devuelve su ``apply_id``.

    Y comprueba que de verdad escribio: un informe con ``apply_id`` pero con la
    escritura ABORTADA produce un identificador perfectamente valido para un
    apply que NO EXISTE. Medido en este mismo carril: sin
    ``bootstrap_writer_schema`` el writer aborta con
    ``EXEC_SCHEMA_CONSTRAINTS_MISSING``, el informe trae su ``apply_identity``
    igual, y el grafo se queda a cero. Un arnes que no lo exija mide el vacio.
    """
    from knowledge_v3.pipeline import entity_decisions, ingest_cli
    from knowledge_v3.writer import bootstrap_writer_schema

    bootstrap_writer_schema(driver)

    def ingesta(altas=(), apply=False, env=None):
        return ingest_cli.run_ingest(
            FUENTE, profile_path=PERFIL, catalog_path=CATALOGO, driver=driver,
            now=AHORA, ingested_at=AHORA, approved_altas=list(altas),
            apply=apply, operator_id=OPERADOR, writer_env=env,
        )

    primera = ingesta()
    ledger = entity_decisions.reconcile(
        resolutions=(primera["candidates"]["link_existing"]
                     + primera["candidates"]["create_entity"]),
        graph_entity_ids=[], workspace=WS, source_path=str(FUENTE),
        names_by_mention={}, catalog_by_entity={},
    )
    assert ledger.altas, "sin altas pendientes no hay nada que promocionar"
    aprobado = entity_decisions.approve(
        ledger, [d.entity_id for d in ledger.altas], reviewer=OPERADOR, at=AHORA)
    altas = entity_decisions.approved_snapshot_entities(aprobado)
    assert altas, "sin altas aprobadas el plan no traeria CREATE_ENTITY"

    informe = ingesta(altas=altas, apply=True, env={
        "S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": WS})

    escritura = informe["write"]
    assert escritura["outcome"] != "ABORTED", (
        f"la escritura ABORTO ({escritura.get('codes')}): el grafo no sostiene "
        "lo que un exito afirmaria y esta suite estaria midiendo el vacio"
    )
    assert escritura["applied_operations"] > 0, (
        f"cero operaciones aplicadas: {escritura}"
    )
    apply_id = informe["apply_identity"]["apply_id"]
    assert apply_id, "el producto no declaro apply_id"
    return apply_id


def _censo(driver, consulta, **params):
    """UNA consulta por cada cosa contada. Dos MATCH sueltos dan producto
    cartesiano y a menudo cero filas que parecen un verde."""
    with driver.session() as s:
        return s.run(consulta, {"ws": WS, **params}).single()[0]


@pytest.fixture(scope="module")
def grafo(driver, apply_real):
    """Lo que el apply dejo DE VERDAD, medido antes de mirar ninguna pantalla."""
    return {
        "marcas": _censo(driver, "MATCH (n:V3AppliedOperation) WHERE n.workspace=$ws "
                                 "AND n.apply_id=$a RETURN count(n)", a=apply_real),
        "entidades": _censo(driver, "MATCH (n:Entity {workspace:$ws}) RETURN count(n)"),
        "fuentes": _censo(driver, "MATCH (n:V3Source {workspace:$ws}) RETURN count(n)"),
        "evidencias": _censo(driver, "MATCH (n:V3Evidence {workspace:$ws}) RETURN count(n)"),
        "aserciones": _censo(driver, "MATCH (n:V3Assertion {workspace:$ws}) RETURN count(n)"),
        "soportes": _censo(driver, "MATCH (:V3Assertion {workspace:$ws})"
                                   "-[r:SUPPORTED_BY]->() RETURN count(r)"),
    }


def test_el_apply_real_dejo_material_o_esta_suite_no_mide_nada(grafo):
    """SUELO DE PLAUSIBILIDAD. Sin esto, todo lo de abajo puede pasar en vacio."""
    for clave in ("marcas", "entidades", "fuentes", "evidencias", "aserciones", "soportes"):
        assert grafo[clave] > 0, f"el apply real no dejo ni un {clave}: {grafo}"


# ===========================================================================
# EL CONSUMIDOR: el visor REAL, por HTTP, con la autorizacion de verdad.
# ===========================================================================
@pytest.fixture
def entorno(tmp_path, monkeypatch):
    from app.auth.config import get_auth_settings
    from app.config import get_settings

    monkeypatch.setenv("S9K_DEFAULT_WORKSPACE", WS)
    monkeypatch.setenv("S9K_AUTH_ENABLED", "true")
    monkeypatch.setenv("S9K_AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv(FLAG, "true")
    get_settings.cache_clear()
    get_auth_settings.cache_clear()

    from app.auth import db as auth_db

    auth_db.ensure_migrated(Path(os.environ["S9K_AUTH_DB_PATH"]))
    yield Path(os.environ["S9K_AUTH_DB_PATH"])

    get_settings.cache_clear()
    get_auth_settings.cache_clear()


@pytest.fixture
def app_real():
    from app.main import app
    return app


@pytest.fixture
def proveedor(app_real):
    """El ``Neo4jGraphProvider`` REAL como proveedor BASE: se sustituye el base
    y NO el filtrado, asi que la cadena entera (``get_filtered_provider`` ->
    ``build_viewer_context`` -> ``PolicyFilteredProvider`` -> ``VisibilityPolicy``)
    se atraviesa en cada peticion."""
    import app.deps as deps
    from app.providers.neo4j_provider import Neo4jGraphProvider

    _exigir_efimera(URI)
    prov = Neo4jGraphProvider(URI, USER, PASSWORD)
    app_real.dependency_overrides[deps.get_provider] = lambda: prov
    yield prov
    app_real.dependency_overrides.pop(deps.get_provider, None)
    prov._driver.close()


def _usuario(db_path: Path, nombre: str, rol: str) -> str:
    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    from app.auth.sessions import create_session

    with auth_db.get_conn(db_path) as conn:
        u = auth_db.create_user(
            conn, username=nombre, display_name=nombre.title(),
            password_hash=hash_password(CLAVE_USUARIO), role=rol)
        auth_db.update_user(conn, u.id, must_change_password=False)
        u = auth_db.get_user_by_id(conn, u.id)
        token, _ = create_session(conn, u)
    return token


def _cliente(app, cookie: str) -> TestClient:
    from app.auth.config import get_auth_settings

    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, cookie)
    return c


@pytest.fixture
def admin(app_real, entorno, proveedor):
    """Lector CON derechos: `admin_full`."""
    return _cliente(app_real, _usuario(entorno, "carrilc-admin", "admin"))


@pytest.fixture
def sin_derechos(app_real, entorno, proveedor):
    """Lector LEGITIMO SIN derechos sobre este material.

    ``reviewer``: pasa la puerta de ROL --su cero no es un 403-- y no tiene
    ``can_view_secret``, que es lo que el writer estampa por defecto.
    """
    return _cliente(app_real, _usuario(entorno, "carrilc-revisor", "reviewer"))


def _resultado(cliente, apply_id):
    return cliente.get(f"/panel/resultado/{apply_id}", params={"workspace": WS})


# ===========================================================================
# 1. LA PRUEBA INSIGNIA, entera y por HTTP
# ===========================================================================
def test_insignia_del_apply_real_a_la_evidencia_literal(admin, apply_real, grafo, driver):
    """El recorrido del encargo, paso a paso y sobre datos que no invento yo."""
    import re

    # --- abrir el resultado de ESA ejecucion
    r = _resultado(admin, apply_real)
    assert r.status_code == 200, r.text[:400]
    assert apply_real in r.text, "la pantalla no dice de que ejecucion habla"

    # --- comprobar exactamente que cambios produjo
    assert 'data-role="entidades"' in r.text
    entidades = re.findall(r'data-entity-id="([^"]+)"', r.text)
    assert entidades, (
        "el resultado de un apply que SI escribio entidades sale sin ninguna: "
        f"el grafo tiene {grafo['entidades']} y la pantalla 0"
    )
    assert 'data-state="DISPONIBLE"' in r.text, (
        "ningun bloque se declara DISPONIBLE pese a haber material"
    )

    # --- abrir un hecho y seguir su procedencia
    hechos = re.findall(r'data-assertion-id="([^"]+)"', r.text)
    assert hechos, (
        f"el grafo tiene {grafo['aserciones']} aserciones y "
        f"{grafo['soportes']} soportes, pero la pantalla no ofrece ni un hecho "
        "que seguir: el recorrido se corta antes de la procedencia"
    )
    assertion_id = hechos[0]

    ev = admin.get(f"/panel/resultado/{apply_real}/hecho/{assertion_id}",
                   params={"workspace": WS})
    assert ev.status_code == 200, ev.text[:400]

    # --- llegar a evidencia LITERAL
    assert 'data-role="fragmento"' in ev.text, "la ficha no trae ni un fragmento"
    literales = re.findall(r'data-field="literal">\s*(.+?)\s*</blockquote>',
                           ev.text, re.S)
    assert literales and literales[0].strip(), (
        "el fragmento llega sin texto literal: no hay evidencia que ensenar"
    )

    # El literal no es una cadena que este fichero haya escrito: se coteja
    # contra lo que el writer dejo en el grafo para ESA asercion.
    with driver.session() as s:
        del_grafo = [
            reg["t"] for reg in s.run(
                "MATCH (a:V3Assertion)-[:SUPPORTED_BY]->(ev:V3Evidence) "
                "WHERE a.workspace=$ws AND a.assertion_id=$aid "
                "RETURN ev.literal_text AS t", {"ws": WS, "aid": assertion_id})
        ]
    assert del_grafo, "el grafo no tiene evidencia para ese hecho"
    import html as _html
    pintado = _html.unescape(literales[0].strip())
    assert pintado in del_grafo, (
        f"el literal pintado {pintado!r} no es ninguno de los que el writer "
        f"dejo para ese hecho: {del_grafo!r}"
    )

    # --- ...y a la FUENTE, con su localizador
    assert 'data-role="fuente"' in ev.text, "la ficha no dice de que fuente viene"
    assert 'data-role="localizador"' in ev.text, "la ficha no dice donde estaba"

    # --- verificar que corresponde al apply CORRECTO
    assert f'data-apply-id="{apply_real}"' in ev.text, (
        "la ficha de evidencia no se atribuye al apply del que se ha llegado"
    )


def test_solo_sale_el_fragmento_QUE_SOSTIENE_y_no_la_fuente_entera(
        admin, apply_real, driver, grafo):
    """LA POLITICA DE PROCEDENCIA, medida y no leida.

    El apply dejo VARIOS fragmentos de la misma fuente y solo UNO sostiene el
    hecho. Si la ficha ensenara los demas, ver un hecho daria acceso a la
    fuente entera -- que es exactamente lo que la politica prohibe.
    """
    import html as _html
    import re

    r = _resultado(admin, apply_real)
    assertion_id = re.findall(r'data-assertion-id="([^"]+)"', r.text)[0]

    with driver.session() as s:
        soportan = {reg["t"] for reg in s.run(
            "MATCH (a:V3Assertion)-[:SUPPORTED_BY]->(ev:V3Evidence) "
            "WHERE a.workspace=$ws AND a.assertion_id=$aid "
            "RETURN ev.literal_text AS t", {"ws": WS, "aid": assertion_id})}
        todos = {reg["t"] for reg in s.run(
            "MATCH (ev:V3Evidence {workspace:$ws}) RETURN ev.literal_text AS t",
            {"ws": WS})}

    ajenos = todos - soportan
    assert ajenos, (
        "todos los fragmentos de la fuente sostienen este hecho: este caso no "
        "puede distinguir 'el fragmento' de 'la fuente entera' y no mide nada"
    )

    ev = admin.get(f"/panel/resultado/{apply_real}/hecho/{assertion_id}",
                   params={"workspace": WS})
    texto = _html.unescape(ev.text)
    colados = [t for t in ajenos if t and t in texto]
    assert not colados, (
        f"la ficha ensena {len(colados)} fragmento(s) que NO sostienen este "
        f"hecho: {colados[:3]}. Ver una assertion ha dado acceso a la fuente "
        "entera."
    )
    # Control positivo: el que SI sostiene tiene que estar, o el cero de arriba
    # seria por una ficha vacia.
    assert any(t in texto for t in soportan if t), (
        "no esta ni el fragmento que SI sostiene el hecho: la ficha esta vacia"
    )


def test_el_texto_completo_del_episodio_no_llega_a_la_pantalla(
        admin, apply_real, driver):
    """El episodio es LOCALIZADOR, no contenido. Su ``text`` no puede salir."""
    import html as _html
    import re

    r = _resultado(admin, apply_real)
    assertion_id = re.findall(r'data-assertion-id="([^"]+)"', r.text)[0]
    ev = admin.get(f"/panel/resultado/{apply_real}/hecho/{assertion_id}",
                   params={"workspace": WS})

    with driver.session() as s:
        textos = [reg["t"] for reg in s.run(
            "MATCH (e:V3Episode {workspace:$ws}) WHERE e.text IS NOT NULL "
            "RETURN e.text AS t", {"ws": WS})]
    assert textos, "ningun episodio guarda texto: este caso no mide nada"

    # Se comparan solo los episodios cuyo texto es MAS LARGO que el fragmento
    # que lo sostiene: si coincidieran, la coincidencia no probaria una fuga.
    texto = _html.unescape(ev.text)
    largos = [t for t in textos if len(t) > 60]
    colados = [t for t in largos if t in texto]
    assert not colados, (
        f"el texto COMPLETO de un episodio ha llegado a la pantalla: "
        f"{colados[0][:120]!r}"
    )


def test_ninguna_ruta_del_servidor_llega_al_navegador(admin, apply_real, driver):
    """``original_location`` es una ruta del servidor. Este repo es PUBLICO y
    ya tuvo un incidente por topologia interna."""
    import re

    with driver.session() as s:
        rutas = [reg["l"] for reg in s.run(
            "MATCH (n:V3Source {workspace:$ws}) WHERE n.original_location IS NOT NULL "
            "RETURN n.original_location AS l", {"ws": WS})]
    assert rutas, "ninguna fuente guarda original_location: este caso no mide nada"

    r = _resultado(admin, apply_real)
    assertion_id = re.findall(r'data-assertion-id="([^"]+)"', r.text)[0]
    ev = admin.get(f"/panel/resultado/{apply_real}/hecho/{assertion_id}",
                   params={"workspace": WS})

    for ruta in rutas:
        assert ruta not in ev.text and ruta not in r.text, (
            f"la ruta interna {ruta!r} ha llegado al navegador"
        )
        assert str(RAIZ) not in ev.text, "la raiz del repo ha llegado al navegador"


# ===========================================================================
# 2. CONTROL DE AUTORIZACION -- con la pareja que lo hace significar algo
# ===========================================================================
def test_un_lector_sin_derechos_no_ve_el_resultado_que_el_admin_SI_ve(
        admin, sin_derechos, apply_real):
    """EL CERO DE POLITICA, calibrado contra un admin que SI ve.

    Las dos mitades se afirman en el mismo caso A PROPOSITO: por separado, "el
    revisor no ve nada" es indistinguible de "la base esta vacia". El orden de
    las aserciones importa: primero se comprueba que HAY material que ver.
    """
    import re

    con = _resultado(admin, apply_real)
    assert con.status_code == 200
    visibles = re.findall(r'data-entity-id="([^"]+)"', con.text)
    assert visibles, (
        "el admin tampoco ve material: este caso no puede probar politica, "
        "porque un cero del revisor seria indistinguible de la base vacia"
    )

    sin = _resultado(sin_derechos, apply_real)
    assert sin.status_code != 403, (
        "el revisor ha chocado con la puerta de ROL: su cero estaria "
        "sobredeterminado y no probaria la politica de CONTENIDO"
    )
    suyas = re.findall(r'data-entity-id="([^"]+)"', sin.text)
    colados = set(suyas) & set(visibles)
    assert not colados, (
        f"un lector SIN derechos ve {len(colados)} entidad(es) que el writer "
        f"estampo como secretas: {sorted(colados)[:3]}"
    )


def test_un_lector_sin_derechos_no_alcanza_la_evidencia_por_su_URL(
        admin, sin_derechos, apply_real):
    """La ficha directa tambien filtra. El listado no es la unica puerta.

    Este es el caso que separa "filtrar en el backend" de "filtrar en la
    pantalla": la URL de la ficha se conoce, y si solo se recortara la LISTA,
    pedirla directamente entregaria el literal.
    """
    import re

    r = _resultado(admin, apply_real)
    assertion_id = re.findall(r'data-assertion-id="([^"]+)"', r.text)[0]
    ruta = f"/panel/resultado/{apply_real}/hecho/{assertion_id}"

    del_admin = admin.get(ruta, params={"workspace": WS})
    assert del_admin.status_code == 200, (
        "ni el admin alcanza la ficha: sin eso, el 404 del revisor no prueba nada"
    )
    assert 'data-role="fragmento"' in del_admin.text

    del_revisor = sin_derechos.get(ruta, params={"workspace": WS})
    assert del_revisor.status_code == 404, (
        f"un lector sin derechos recibe {del_revisor.status_code} en la ficha "
        "de evidencia: la procedencia se sirve saltandose la politica"
    )
    assert 'data-role="fragmento"' not in del_revisor.text


def test_un_anonimo_no_alcanza_ninguna_de_las_dos_pantallas(
        app_real, entorno, proveedor, apply_real):
    """Contexto AUSENTE nunca es permiso maximo."""
    c = TestClient(app_real, raise_server_exceptions=False, follow_redirects=False)
    for ruta in (f"/panel/resultado/{apply_real}",
                 f"/panel/resultado/{apply_real}/hecho/assertion:loquesea"):
        r = c.get(ruta, params={"workspace": WS})
        assert r.status_code != 200, f"{ruta} sirve 200 a un anonimo"


def test_el_apply_no_se_sirve_bajo_un_workspace_que_no_es_el_suyo(admin, apply_real):
    """El apply existe, pero NO en ese workspace: no puede servirse.

    DECLARADO: este caso esta SOBREDETERMINADO y no prueba por si solo la
    puerta de ambito. El workspace pedido no existe, asi que el 404 podria
    venir igualmente de que no hay marcas ahi -- "no veo nada" y "no hay nada"
    otra vez. Lo que si afirma, y es lo que importa aqui, es que el material
    del workspace bueno NO aparece cuando se pide por otro nombre.

    La puerta de ambito PROPIAMENTE DICHA --que se comprueba ANTES de consultar
    y contra la lista del proveedor filtrado-- se aisla en la suite sin base,
    con un proveedor espia: ``test_un_workspace_fuera_de_alcance_no_consulta_nada``.
    Alli el cero es de POLITICA porque el espia declara material y aun asi no
    se le pregunta por el.
    """
    import re

    bueno = _resultado(admin, apply_real)
    suyas = set(re.findall(r'data-entity-id="([^"]+)"', bueno.text))
    assert suyas, "el apply real no ensena nada: este caso no puede medir cruce"

    r = admin.get(f"/panel/resultado/{apply_real}",
                  params={"workspace": "workspace-ajeno-inexistente"})
    coladas = set(re.findall(r'data-entity-id="([^"]+)"', r.text)) & suyas
    assert not coladas, (
        f"pedido por OTRO workspace, el apply ensena {len(coladas)} entidad(es) "
        f"del suyo: {sorted(coladas)[:3]}. El workspace de la URL no acota."
    )
    assert r.status_code == 404, (
        f"un workspace ajeno devuelve {r.status_code}: la pantalla cruza ambitos"
    )


# ===========================================================================
# 3. ATRIBUCION -- un apply no ensena el resultado de otro
# ===========================================================================
def test_un_apply_id_ajeno_no_ensena_el_material_de_otro_apply(admin, apply_real):
    """ATRIBUCION CRUZADA, con base REAL detras.

    El workspace tiene UN apply con material. Se pide OTRO identificador, bien
    formado y sin marcas. El orden de las aserciones es deliberado: primero la
    que explica el defecto --que no salga el material del apply de al lado--,
    porque un 404 puede darse por mil motivos y solo esa dice cual importa.
    """
    import re

    verdadero = _resultado(admin, apply_real)
    suyas = set(re.findall(r'data-entity-id="([^"]+)"', verdadero.text))
    assert suyas, "el apply real no ensena nada: este caso no puede medir cruce"

    ajeno = _resultado(admin, "apply:" + "0" * 32)
    coladas = set(re.findall(r'data-entity-id="([^"]+)"', ajeno.text)) & suyas
    assert not coladas, (
        f"la pantalla de un apply SIN marcas ensena {len(coladas)} entidad(es) "
        f"del apply de al lado: {sorted(coladas)[:3]}. ATRIBUCION CRUZADA: el "
        "apply_id de la URL no esta acotando nada."
    )
    assert ajeno.status_code == 404, (
        f"un apply que no existe devuelve {ajeno.status_code}: una pantalla "
        "vacia afirmaria que ese apply existe y no cambio nada"
    )


def test_la_ficha_de_evidencia_exige_que_el_hecho_sea_de_ESE_apply(admin, apply_real):
    """La misma atribucion, en la ficha directa: la URL es adivinable."""
    import re

    r = _resultado(admin, apply_real)
    assertion_id = re.findall(r'data-assertion-id="([^"]+)"', r.text)[0]

    suya = admin.get(f"/panel/resultado/{apply_real}/hecho/{assertion_id}",
                     params={"workspace": WS})
    assert suya.status_code == 200, "ni por su propio apply se sirve: no mide nada"

    ajena = admin.get(f"/panel/resultado/apply:{'0' * 32}/hecho/{assertion_id}",
                      params={"workspace": WS})
    assert 'data-role="fragmento"' not in ajena.text, (
        "la evidencia de un hecho se sirve bajo el identificador de un apply "
        "que NO lo produjo: ATRIBUCION CRUZADA de procedencia."
    )
    assert ajena.status_code == 404


def test_el_invariante_congelado_sigue_en_pie(driver, grafo):
    """La procedencia NO ha entrado en la superficie publica.

    Esta pantalla no la alcanza por politica propia --los nodos siguen SIN
    ``visibility``, SIN ``known_by`` y SIN la etiqueta publica ``:Entity``--,
    sino por la politica de la entidad que el lector ya podia ver. Que ese
    invariante siga intacto DESPUES de abrir la superficie se afirma aqui, en
    el mismo sitio donde se abre.
    """
    for etiqueta in ("V3Source", "V3Episode", "V3Evidence", "V3Assertion"):
        colados = _censo(
            driver,
            f"MATCH (n:{etiqueta} {{workspace:$ws}}) WHERE n:Entity RETURN count(n)")
        assert colados == 0, (
            f"{colados} nodos :{etiqueta} llevan la etiqueta publica :Entity. "
            "La procedencia ha quedado al alcance del visor generico."
        )
    sin_visibilidad = _censo(
        driver, "MATCH (n:V3Evidence {workspace:$ws}) "
                "WHERE n.visibility IS NOT NULL RETURN count(n)")
    assert sin_visibilidad == 0, (
        "algun nodo de evidencia ha ganado `visibility`: esta superficie no "
        "puede haber creado una ACL nueva sobre la procedencia"
    )


# ===========================================================================
# 4. LA RUTA DE LA INTERFAZ: apply SIN paquete de procedencia
# ===========================================================================
# El Carril B midio que un apply lanzado desde la interfaz va SIN
# `ProvenanceBundle`. Y el propio producto lo dice en `pipeline.py`:
#
#   "EL PAQUETE ES LO QUE DISTINGUE LAS DOS RUTAS, y no es codigo: son datos.
#    La ingesta SI tiene los documentos [...]. Un mando al que solo se le da
#    `plan.json` no los tiene, y por eso la funcion canonica le contesta con
#    APPLY_PROVENANCE_NOT_PERSISTED en vez de con un APPLIED silencioso."
#
# Aqui NO se cree eso: se REPRODUCE, llamando a `apply_v3` --la definicion de
# "aplicar V3", la misma funcion que usa toda ruta de apply-- sin paquete, y
# se mira que ensena la pantalla. Workspace propio: aplicar dos veces el mismo
# plan en el mismo sitio es un no-op y no se observaria nada.

@pytest.fixture(scope="module")
def material_sin_proc(tmp_path_factory):
    """Perfil y catalogo del workspace APARTE.

    No se le pide a `run_ingest` que reescriba el workspace del perfil: el
    producto se NIEGA a hacerlo en silencio --"corrige uno de los dos"-- y
    tiene razon. Se le dan los documentos coherentes, que es lo que haria un
    operador.
    """
    destino = tmp_path_factory.mktemp("sin-procedencia")
    salida = {}
    for nombre, origen in (("perfil", PERFIL), ("catalogo", CATALOGO)):
        doc = json.loads(origen.read_text())
        doc["workspace"] = WS_SIN_PROC
        if doc.get("source_asset_id") == f"profile:{WS}":
            doc["source_asset_id"] = f"profile:{WS_SIN_PROC}"
        # IDENTIDADES PROPIAS, y no por capricho de la prueba.
        # -----------------------------------------------------
        # MEDIDO aqui: con el catalogo copiado tal cual, el MISMO `entity_id`
        # acaba existiendo en los DOS workspaces. Y `Neo4jGraphProvider.entity`
        # busca por identificador SIN acotar cuando el lector es admin
        # (`_scope_workspaces()` devuelve `None` para `admin_full`), encuentra
        # dos nodos, declara IDENTIDAD DURABLE AMBIGUA y devuelve `None`.
        # Resultado: el admin no ve NADA de ninguno de los dos workspaces.
        #
        # Es comportamiento del producto --fallo cerrado ante identidad
        # ambigua, correcto-- y esta pantalla lo respeta: `None` es `None`. Lo
        # que no vale es montar un escenario que lo dispare sin querer y leer
        # el vacio resultante como si dijera algo de la procedencia. Dos
        # workspaces de verdad no comparten `entity_id`.
        for entidad in doc.get("entities") or []:
            entidad["entity_id"] = entidad["entity_id"] + "-sp"
        ruta = destino / origen.name
        ruta.write_text(json.dumps(doc, ensure_ascii=False))
        salida[nombre] = ruta
    return salida


@pytest.fixture(scope="module")
def apply_sin_procedencia(driver, material_sin_proc):
    """UN apply REAL por la ruta que NO aporta procedencia. Su ``apply_id``."""
    from knowledge_v3.pipeline import entity_decisions, ingest_cli
    from knowledge_v3.writer import bootstrap_writer_schema
    from knowledge_v3.writer.apply import apply_v3
    from knowledge_v3.writer.gate import OperatorRequest
    from knowledge_v3.writer.writer import GraphWriter

    bootstrap_writer_schema(driver)

    def ingesta(altas=(), apply=False):
        return ingest_cli.run_ingest(
            FUENTE, profile_path=material_sin_proc["perfil"],
            catalog_path=material_sin_proc["catalogo"], driver=driver,
            workspace=WS_SIN_PROC, now=AHORA, ingested_at=AHORA,
            approved_altas=list(altas), apply=apply, operator_id=OPERADOR,
        )

    primera = ingesta()
    ledger = entity_decisions.reconcile(
        resolutions=(primera["candidates"]["link_existing"]
                     + primera["candidates"]["create_entity"]),
        graph_entity_ids=[], workspace=WS_SIN_PROC, source_path=str(FUENTE),
        names_by_mention={}, catalog_by_entity={})
    aprobado = entity_decisions.approve(
        ledger, [d.entity_id for d in ledger.altas], reviewer=OPERADOR, at=AHORA)
    altas = entity_decisions.approved_snapshot_entities(aprobado)

    # El plan SELLADO, sin aplicar. De aqui sale lo que la interfaz tendria.
    informe = ingesta(altas=altas, apply=False)
    plan = informe["plan"]

    request = OperatorRequest(
        apply=True, operator_id=OPERADOR, workspace=WS_SIN_PROC,
        expected_plan_hash=plan["plan_hash"]["value"],
        current_snapshot_id=plan["snapshot_id"],
        env={"S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": WS_SIN_PROC},
    )
    # `provenance=None`: LA RUTA DE LA INTERFAZ. No se omite por comodidad de
    # la prueba, se omite porque es lo que esa ruta hace hoy.
    outcome = apply_v3(plan, request,
                       writer=GraphWriter(workspace=WS_SIN_PROC, driver=driver),
                       provenance=None, driver=driver)

    codigos = {n["code"] for n in outcome.notes}
    assert "APPLY_PROVENANCE_NOT_PERSISTED" in codigos, (
        f"el producto NO aviso de que no persistia procedencia: {codigos}. "
        "Si esto cambia, esta prueba esta midiendo otra cosa."
    )
    assert getattr(outcome.write_result, "ok", False), (
        f"la escritura no fue bien: {outcome.write_result}"
    )
    return outcome.apply_id


def test_la_ruta_de_la_interfaz_deja_conocimiento_y_CERO_procedencia(
        driver, apply_sin_procedencia):
    """El hecho medido, antes de mirar ninguna pantalla. Una consulta por cosa."""
    def censo(q):
        with driver.session() as s:
            return s.run(q, {"ws": WS_SIN_PROC}).single()[0]

    assert censo("MATCH (n:V3Assertion {workspace:$ws}) RETURN count(n)") > 0, (
        "ni una asercion: este escenario no ha escrito nada y no mide nada"
    )
    assert censo("MATCH (n:V3Evidence {workspace:$ws}) RETURN count(n)") == 0, (
        "hay evidencia: este apply SI persistio procedencia y el escenario no "
        "reproduce la ruta de la interfaz"
    )
    assert censo("MATCH (:V3Assertion {workspace:$ws})-[r:SUPPORTED_BY]->() "
                 "RETURN count(r)") == 0


def test_la_pantalla_DICE_que_la_ejecucion_no_dejo_procedencia_y_no_la_inventa(
        admin, apply_sin_procedencia, apply_real):
    """El requisito entero: si no existe procedencia, se DICE. Nunca se inventa.

    Y se afirma contra el OTRO apply --el que si la tiene-- para que quede
    claro que la pantalla distingue, en vez de decir siempre lo mismo.
    """
    import re

    r = admin.get(f"/panel/resultado/{apply_sin_procedencia}",
                  params={"workspace": WS_SIN_PROC})
    assert r.status_code == 200, r.text[:300]

    hechos = re.findall(r'data-assertion-id="([^"]+)"', r.text)
    assert hechos, "la pantalla no ofrece ni un hecho de un apply que SI escribio"

    ev = admin.get(
        f"/panel/resultado/{apply_sin_procedencia}/hecho/{hechos[0]}",
        params={"workspace": WS_SIN_PROC})
    assert ev.status_code == 200, ev.text[:300]

    assert 'data-state="sin-procedencia"' in ev.text, (
        "La ficha no declara que la EJECUCION no dejo procedencia. O dice que "
        "el hecho no tiene evidencia --que confunde dos cosas distintas-- o "
        "no dice nada."
    )
    assert 'data-role="fragmento"' not in ev.text, (
        "Se ha pintado un fragmento donde el grafo no tiene NINGUNO: la "
        "pantalla se esta inventando la procedencia."
    )

    # CONTRASTE: el apply que SI la tiene no dice lo mismo. Sin esto, una
    # pantalla que dijera SIEMPRE "sin procedencia" pasaria el caso de arriba.
    r2 = admin.get(f"/panel/resultado/{apply_real}", params={"workspace": WS})
    otro = re.findall(r'data-assertion-id="([^"]+)"', r2.text)[0]
    ev2 = admin.get(f"/panel/resultado/{apply_real}/hecho/{otro}",
                    params={"workspace": WS})
    assert 'data-state="sin-procedencia"' not in ev2.text, (
        "La pantalla dice 'sin procedencia' TAMBIEN cuando la hay: no "
        "distingue nada, solo repite una frase."
    )
    assert 'data-role="fragmento"' in ev2.text


def test_que_deja_un_apply_SIN_paquete_de_procedencia(driver, apply_sin_procedencia):
    """Lo que quita el paquete es la PROCEDENCIA, no la proyeccion.

    Sobre el plan que sella la ruta de ingesta --cuyas operaciones incluyen
    `PROJECT_RELATION`-- aplicar SIN paquete deja la arista IGUALMENTE y deja
    la evidencia a cero. Son dos carencias distintas y este caso impide
    confundirlas.

    OJO CON LO QUE ESTE CASO **NO** VIGILA: el plan de la INTERFAZ es otro, y
    lo vigila `test_el_plan_sellado_de_la_interfaz_solo_emite_CREATE_ASSERTION`.
    Este fichero tuvo ese testigo apuntando aqui, y era mirar al otro lado: el
    plan de la interfaz ya llevaba solo `CREATE_ASSERTION` y este caso seguia
    verde, porque mide el plan de ingesta.
    """
    with driver.session() as s:
        aristas = s.run(
            "MATCH (:Entity {workspace:$ws})-[r]->(:Entity {workspace:$ws}) "
            "RETURN count(r) AS c", {"ws": WS_SIN_PROC}).single()["c"]
        aserciones = s.run(
            "MATCH (n:V3Assertion {workspace:$ws}) RETURN count(n) AS c",
            {"ws": WS_SIN_PROC}).single()["c"]
        evidencias = s.run(
            "MATCH (n:V3Evidence {workspace:$ws}) RETURN count(n) AS c",
            {"ws": WS_SIN_PROC}).single()["c"]

    assert aserciones > 0, "sin aserciones este caso no compara nada"
    assert evidencias == 0, (
        "hay evidencia: el apply SI persistio procedencia y este caso no "
        "esta midiendo la carencia que dice medir"
    )
    assert aristas > 0, (
        "el plan DE INGESTA ya NO materializa la arista. Es un cambio real del "
        "producto: revisar la prueba insignia, que da por hecho que hay una "
        "relacion que abrir."
    )
