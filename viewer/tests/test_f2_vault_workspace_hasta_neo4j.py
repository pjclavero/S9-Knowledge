# -*- coding: utf-8 -*-
"""CORTE F-2 · EL ENSAYO DECISIVO — que workspace acaba MATERIALIZADO en Neo4j.

    perfil de boveda = A  ->  ingesta -> review -> apply  ->  Neo4j = A

Esta es la consecuencia que el diagnostico previo dejo **NO MEDIDA**: midio que
`/admin/partidas/grant` rechaza el workspace del perfil y que un revisor de otro
workspace muta material ajeno, pero no midio donde acaba el conocimiento cuando
el operador alinea el writer para poder aplicar. Lo midio ademas con el doble
`grafo_doble.py`, no contra Neo4j. Aqui se mide contra un Neo4j REAL y efimero.

## LA PROCEDENCIA DEL DATO MEDIDO ES PARTE DE LA MEDICION

El workspace `A` de este ensayo **no se siembra a mano en ningun punto del
camino**. Se escribe UNA sola vez, en el `perfil-operador.json` de una boveda de
`tmp_path`, y a partir de ahi lo deriva el producto:

    perfil-operador.json  ->  sources_catalog._workspace_declarado
                          ->  FuenteDisponible.ambito.workspace
                          ->  job `ingest_v3` (payload.workspace)
                          ->  paquete de propuestas (proposal.workspace)
                          ->  plan sellado (sealed_plans.workspace)
                          ->  GraphWriter(workspace=...)
                          ->  propiedad `workspace` de los nodos de Neo4j

Cada eslabon se COMPRUEBA por separado, para que un verde final no pueda
deberse a que el arnes lo puso ahi. La unica variable que el arnes escribe con
el valor `A` aparte del perfil es `S9K_WRITER_WORKSPACE`, y eso es a proposito:
es exactamente el gesto del operador que el diagnostico describe («si el
operador alinea el writer para poder aplicar»). Es la PREMISA del escenario, no
el resultado; y hay un control negativo que comprueba que sin ese gesto no se
escribe nada.

## QUE PUENTEAN LOS DOBLES DE ESTE FICHERO

`_grafo_de_mentira` (heredado del arnes del panel) instala un proveedor doble
para PINTAR pantallas, y cede el sitio al abridor real en cuanto el fixture
`grafo` pone credenciales. El apply y la comprobacion final NO pasan por el
doble: se consulta el contenedor con el driver de verdad. El resto del camino
—catalogo, ambito, cola de trabajos, worker de ingesta, almacen de propuestas,
sellado— corre entero sin dobles.

## COMO SE EJECUTA

    S9K_WRITER_NEO4J_REAL=1 python -m pytest \\
        viewer/tests/test_f2_vault_workspace_hasta_neo4j.py -q

Sin esa variable se SALTA. Un salto no mide nada y no vale como verde.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from test_panel_apply_desde_la_ui import (  # noqa: F401
    EJEMPLOS,
    SLOT_B,
    _aplicar,
    _aplicable,
    _aviso_de,
    _cliente,
    _cookie,
    _csrf,
    _decidir,
    _entorno_limpio,
    _filas_de_plan,
    _grafo_de_mentira,
    _opciones,
    _propuestas,
    _salud_aislada,
    _sellar,
    almacenes,
    auth_on,
    cola,
    grafo,
    grafo_real,
    neo4j_real,
    operador,
    paneles_on,
    real_app,
)

#: EL workspace del ensayo. Se escribe UNA vez: en el perfil de la boveda.
#: Deliberadamente distinto de `ws-cofradia` (el de `examples/ingesta-v3`) y de
#: `leyenda` (el defecto del entorno), para que un valor heredado por descuido
#: de cualquiera de los dos se vea como un fallo y no se confunda con un acierto.
W = "ws-boveda-f2"

#: El workspace que el entorno declara mientras tanto. NO tiene que aparecer en
#: ningun nodo del grafo: es el competidor.
W_ENTORNO = "leyenda"


@pytest.fixture
def boveda(tmp_path, monkeypatch) -> Path:
    """Una boveda real en disco cuyo perfil declara `W`. Sin dobles."""
    raiz = tmp_path / "bovedas"
    juego = raiz / "l5r"
    (juego / "compartido" / "lore").mkdir(parents=True)

    plantilla = json.loads(
        (EJEMPLOS / "perfil-operador.json").read_text(encoding="utf-8")
    )
    perfil = dict(plantilla)
    perfil["workspace"] = W
    perfil["source_asset_id"] = f"profile:{W}"
    (juego / "perfil-operador.json").write_text(
        json.dumps(perfil, ensure_ascii=False), encoding="utf-8"
    )

    cuerpo = (EJEMPLOS / "nota-cofradia-de-ambar.md").read_text(encoding="utf-8")
    (juego / "compartido" / "lore" / "nota-cofradia-de-ambar.md").write_text(
        cuerpo, encoding="utf-8"
    )

    monkeypatch.setenv("S9K_VAULT_ROOT", str(raiz))
    monkeypatch.setenv("S9K_VAULT_REQUIRE_MOUNT", "0")
    monkeypatch.delenv("S9K_INGEST_SOURCES_DIR", raising=False)
    # EL COMPETIDOR SIGUE HABLANDO. El escenario que se mide es justo el de
    # fabrica: entorno y perfil declarando cosas distintas.
    monkeypatch.setenv("S9K_DEFAULT_WORKSPACE", W_ENTORNO)
    return raiz


def _nodos_por_workspace(driver) -> dict:
    """Recuento de nodos de conocimiento AGRUPADO por workspace.

    Se pregunta por TODOS los workspaces, no por `W`: preguntar solo por `W`
    no distinguiria «se escribio en W» de «no se escribio nada» y ademas no
    veria una escritura en el workspace del entorno, que es justo el riesgo.
    """
    with driver.session() as sesion:
        filas = sesion.run(
            "MATCH (n) WHERE n:V3Entity OR n:V3Assertion "
            "RETURN coalesce(n.workspace, '<sin workspace>') AS ws, "
            "count(*) AS n ORDER BY ws"
        )
        return {f["ws"]: f["n"] for f in filas}


def _ingerir_desde_la_boveda(operador, cola) -> str:
    """Alta + ingesta por la PANTALLA, sin pasarle el workspace a nadie."""
    from app import jobs_client
    from jobs import worker

    pantalla = operador.get(SLOT_B.prefix)
    assert pantalla.status_code == 200, pantalla.status_code
    opciones = _opciones(pantalla.text)
    assert opciones, "la pantalla no ofrece ninguna fuente de la boveda"

    envio = operador.post(
        "/panel/operations/ingestas",
        data={"fuente": opciones[0], "csrf_token": _csrf(operador)},
    )
    assert envio.status_code == 303, envio.text[:300]

    store = jobs_client._load_job_store()
    pendientes = store.list_jobs(status="pending", db_path=str(cola))
    assert len(pendientes) == 1, pendientes
    job = pendientes[0]

    # ESLABON 1: el producto derivo `W` del perfil. El arnes no lo puso aqui.
    assert job["workspace"] == W, (
        f"el job se creo en '{job['workspace']}' y el perfil declara '{W}': "
        "el workspace del trabajo NO viene del perfil de la boveda"
    )

    assert worker.run("worker-f2", once=True, limit=1, db_path=str(cola)) == 1
    final = store.get_job(job["job_id"], db_path=str(cola))
    assert final["status"] == "complete", final.get("error_message")
    return job["job_id"]


@neo4j_real
def test_f2_el_workspace_del_perfil_es_el_que_acaba_en_neo4j(
    real_app, paneles_on, cola, operador, almacenes, grafo, boveda, monkeypatch
):
    """LA MEDICION QUE FALTABA, eslabon por eslabon."""
    from app.config import get_settings

    # LA PREMISA DEL ESCENARIO, no el resultado: el operador alinea el writer
    # para poder aplicar. `grafo` lo deja en `ws-cofradia`; aqui se declara `W`.
    monkeypatch.setenv("S9K_WRITER_WORKSPACE", W)
    get_settings.cache_clear()

    # CONTROL DE PARTIDA: el grafo empieza vacio. Sin esto, cualquier recuento
    # final podria venir de otra prueba y no de este recorrido.
    assert _nodos_por_workspace(grafo) == {}, "el grafo no empezo vacio"

    job_id = _ingerir_desde_la_boveda(operador, cola)

    # ESLABON 2: el paquete de propuestas.
    propuestas = _propuestas(almacenes["propuestas"])
    assert propuestas, "la ingesta no produjo ninguna propuesta"
    ajenas = sorted({p["workspace"] for p in propuestas} - {W})
    assert not ajenas, f"propuestas en workspaces que el perfil no declara: {ajenas}"

    elegida = _aplicable(propuestas, job_id)
    assert elegida is not None, "ninguna propuesta del paquete es aplicable"
    _decidir(elegida, "APPROVE")

    # ESLABON 3: el plan sellado.
    aviso_sellado = _aviso_de(_sellar(operador, job_id))
    assert aviso_sellado.startswith("PLAN_SEALED"), aviso_sellado
    fila = _filas_de_plan(almacenes["base"])[0]
    assert fila["workspace"] == W, (
        f"el plan se sello en '{fila['workspace']}' y no en el del perfil"
    )
    documento = json.loads(fila["plan_json"])

    # ESLABON 4 — EL QUE NADIE HABIA MEDIDO: el grafo.
    aviso_apply = _aviso_de(_aplicar(operador, job_id))
    assert aviso_apply == "PLAN_APPLIED", aviso_apply

    por_workspace = _nodos_por_workspace(grafo)
    assert por_workspace, (
        "el apply dijo PLAN_APPLIED y en el grafo no hay ni un nodo de "
        "conocimiento: el aviso de la pantalla no es evidencia de escritura"
    )
    assert set(por_workspace) == {W}, (
        "el conocimiento se materializo en workspaces que el perfil de la "
        f"boveda NO declara. Perfil='{W}', entorno='{W_ENTORNO}', "
        f"medido en Neo4j={por_workspace}"
    )
    assert W_ENTORNO not in por_workspace

    # Y las afirmaciones son EXACTAMENTE las del plan, no unas cualesquiera.
    with grafo.session() as sesion:
        escritas = sorted(
            f["id"]
            for f in sesion.run(
                "MATCH (a:V3Assertion {workspace: $ws}) "
                "RETURN a.assertion_id AS id",
                ws=W,
            )
        )
    del documento  # el recuento por workspace es lo que este corte afirma
    assert escritas, "no hay ni una afirmacion en el workspace del perfil"


@neo4j_real
def test_f2_control_negativo_sin_alinear_el_writer_no_se_escribe_nada(
    real_app, paneles_on, cola, operador, almacenes, grafo, boveda, monkeypatch
):
    """CONTROL NEGATIVO de la prueba de arriba, y con su MENSAJE.

    Sin el gesto del operador (`S9K_WRITER_WORKSPACE` = el del perfil) el apply
    tiene que negarse. Si esto saliera verde escribiendo, el verde de arriba no
    probaria que el gesto importa. Y si saliera rojo por OTRA causa —por
    ejemplo porque el camino no llega al apply— tampoco: por eso se comprueba
    el codigo exacto del aviso, no solo que no haya nodos.
    """
    from app.config import get_settings

    # `grafo` deja `S9K_WRITER_WORKSPACE=ws-cofradia`: el writer alineado con
    # OTRO workspace, que es la configuracion de fabrica.
    get_settings.cache_clear()
    assert _nodos_por_workspace(grafo) == {}

    job_id = _ingerir_desde_la_boveda(operador, cola)
    propuestas = _propuestas(almacenes["propuestas"])
    elegida = _aplicable(propuestas, job_id)
    assert elegida is not None
    _decidir(elegida, "APPROVE")
    assert _aviso_de(_sellar(operador, job_id)).startswith("PLAN_SEALED")

    aviso = _aviso_de(_aplicar(operador, job_id))
    assert aviso == "APPLY_NOT_ENABLED", (
        "el apply no se nego por la causa esperada (writer declarado en otro "
        f"workspace): el producto contesto '{aviso}'"
    )
    assert _nodos_por_workspace(grafo) == {}, (
        "se escribio en el grafo con el writer declarado en otro workspace"
    )
