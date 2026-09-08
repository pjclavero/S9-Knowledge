# -*- coding: utf-8 -*-
"""EQUIPO 8A -- una entidad creada en una corrida se REUTILIZA en la siguiente.

EL DEFECTO QUE CIERRA ESTE FICHERO
----------------------------------
Palabras del integrador: **«hoy ningun test lo detecta»**. Este es el que si.

El grafo guardaba como `name` la SUPERFICIE del alias que resolvio la mencion,
no el nombre canonico:

    lore escribe   entity:cofradia-ambar   con   name = 'la Cofradia'

En la corrida SIGUIENTE, `Neo4jEntityCatalog` deriva el `canonical_name` de ese
`name`, y "Cofradia de Ambar" no alcanzaba a "la cofradia" por ninguna via:
`CREATE_PROVISIONAL` / `NO_CANDIDATE` -> `REVIEW` -> no se aplica nada.

Y habia una SEGUNDA puerta, en la misma ruta canonica de escritura:
`list_entities_query` no devolvia alias, `GraphEntity` no tenia campo de alias
y `catalog.py` cableaba `aliases=()`. Como `step_alias` recorre
`normalized_aliases`, contra grafo real la senal 0.95 estaba
ESTRUCTURALMENTE MUERTA. El producto lo declaraba solo: `GRAFO_SIN_ALIAS`.

LA DISTINCION QUE ESTE FICHERO PROTEGE
--------------------------------------
**La superficie observada y el nombre canonico son conceptos distintos.** El
arreglo NO consiste en inferir el canonico desde la superficie que coincidio
--eso ES el defecto-- sino en persistir el nombre que el catalogo declara, y
los alias por los que se la puede volver a alcanzar.

POR QUE SE PONE ROJO SI SE REINTRODUCE
--------------------------------------
`test_caso_1_el_nombre_persistido_es_el_canonico` LEE del grafo el `name` del
nodo y exige que sea "Cofradia de Ambar". Si se vuelve a persistir la
superficie, ahi vale "la Cofradia" y el test falla ANTES de llegar a la
segunda corrida, senalando el eslabon exacto. `test_caso_2_...` exige la senal
`EXACT_ALIAS` contra el catalogo de Neo4j: si `aliases` deja de viajar o de
leerse, no hay senal que dispare y el test falla.

DISCIPLINA DE MEDIDA (reglas caras de este proyecto)
----------------------------------------------------
* El grafo arranca VACIO y se COMPRUEBA; no se presume.
* El esquema lo instala el PRODUCTO (`bootstrap_writer_schema`, en la fixture).
  Este fichero no ejecuta NI UN `CREATE`/`MERGE`/`SET` propio: todo nodo lo
  escribe el writer por la ruta de la CLI. Las unicas consultas de este fichero
  son `MATCH ... RETURN`.
* La corrida 2 va SIN `--catalogo`: el mundo sale SOLO del grafo. Es la unica
  forma de que "se reutilizo" signifique algo -- con el fichero delante, el
  enlace podria venir del fichero y no del nodo.
* UNA consulta por cosa contada, y todo censo se afirma NO VACIO antes de
  compararlo. Dos `MATCH` sueltos darian producto cartesiano y cero filas.
* `elementId` no se usa jamas como identidad; la identidad es
  `(workspace, entity_id)`.
* Valores DISTINTOS y no nulos: el canonico ("Cofradia de Ambar") y la
  superficie ("la Cofradia") son cadenas distintas, y ninguna es el
  `entity_id`, que es el tercer valor que el defecto historico producia. Los
  tres se distinguen entre si, asi que ninguna asercion puede pasar por
  coincidir con un valor por defecto.
"""
from __future__ import annotations

import os
import pathlib
import sys
from datetime import datetime, timezone

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("neo4j")

APP_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

LIVE = os.environ.get("S9K_WRITER_NEO4J_REAL", "").strip() == "1"
pytestmark = pytest.mark.skipif(
    not LIVE, reason="Neo4j real efimero: activar con S9K_WRITER_NEO4J_REAL=1"
)

from test_knowledge_v3_writer_neo4j_real import neo4j_efimero_conexion  # noqa: E402

from knowledge_v3.pipeline import (  # noqa: E402
    entity_decisions,
    graph_catalog as gc,
    ingest_cli,
)
from knowledge_v3.resolution.catalog import Neo4jEntityCatalog  # noqa: E402

RAIZ = APP_DIR.parents[1]
EJEMPLOS = RAIZ / "examples" / "ingesta-v3"
PERFIL = EJEMPLOS / "perfil-operador.json"
CATALOGO = EJEMPLOS / "catalogo-workspace.json"
WS = "ws-cofradia"

#: Los tres valores que el defecto confundia. DISTINTOS entre si a proposito.
ENTIDAD = "entity:cofradia-ambar"
CANONICO = "Cofradia de Ambar"      # lo que el catalogo declara
SUPERFICIE = "la Cofradia"          # el alias que menciona la fuente
# y `ENTIDAD` es el tercero: el `name = entity_id` del defecto aun anterior.

AHORA = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ENV_APPLY = {"S9K_ALLOW_REAL_INGEST": "1", "S9K_WRITER_WORKSPACE": WS}


# --- utillaje: la CLI del producto, nada mas --------------------------------
def _fuente(tmp: pathlib.Path, nombre: str, texto: str) -> pathlib.Path:
    ruta = tmp / nombre
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def _ingesta(fuente, driver, catalogo, **kw):
    return ingest_cli.run_ingest(
        fuente,
        profile_path=PERFIL,
        catalog_path=catalogo,
        driver=driver,
        now=AHORA,
        ingested_at=AHORA,
        **kw,
    )


def _resoluciones(report) -> list[dict]:
    """Las filas de `candidates.*`, con el mismo criterio que `ingest_cli`."""
    cand = report.get("candidates") or {}
    return list(
        (cand.get("link_existing") or [])
        + (cand.get("create_entity") or [])
        + (cand.get("review_identity") or [])
    )


def _ledger(report, fuente, driver, catalogo):
    """`reconcile` tal como lo llama `ingest_cli.main`, con el MISMO helper."""
    filas = gc.catalog_rows(driver, WS, None)
    mundo = ingest_cli.merge_catalogo(filas, ingest_cli.load_catalog(catalogo))
    return entity_decisions.reconcile(
        resolutions=_resoluciones(report),
        graph_entity_ids=gc.entity_ids(filas),
        workspace=WS,
        source_path=str(fuente),
        generated_at=AHORA,
        names_by_mention=ingest_cli._nombres_por_mencion(report),
        catalog_by_entity=ingest_cli.identidades_por_entidad(mundo),
    )


def _corrida_con_apply(fuente, driver, catalogo):
    """Dry-run -> aprobacion humana de las altas -> APPLY real. Sin atajos."""
    seco = _ingesta(fuente, driver, catalogo)
    ledger = _ledger(seco, fuente, driver, catalogo)
    ids = sorted({
        d.entity_id for d in ledger.altas
        if d.entity_id and not d.entity_id.startswith(("entity:prov:", "entity:new:"))
    })
    altas = []
    if ids:
        aprobado = entity_decisions.approve(ledger, ids, reviewer="pjc", at=AHORA)
        altas = entity_decisions.approved_snapshot_entities(aprobado)
    return _ingesta(
        fuente, driver, catalogo,
        approved_altas=altas,
        apply=True,
        operator_id="pjc",
        writer_env=ENV_APPLY,
    )


def _filas(driver, cypher, **params):
    with driver.session() as s:
        return [r.data() for r in s.run(cypher, params)]


def _nodo(driver, entity_id):
    """UNA consulta, UNA cosa contada. Conjunto NO vacio, y exactamente uno."""
    filas = _filas(
        driver,
        "MATCH (n:V3Entity) WHERE n.workspace = $ws AND n.entity_id = $eid "
        "RETURN n.entity_id AS entity_id, n.name AS name, "
        "n.aliases AS aliases, n.entity_type AS entity_type",
        ws=WS, eid=entity_id,
    )
    assert filas, f"censo VACIO: {entity_id} no consta en el grafo"
    assert len(filas) == 1, f"identidad duplicada para {entity_id}: {filas}"
    return filas[0]


def _resolver(catalogo):
    """El resolutor del producto, con sus umbrales POR DEFECTO.

    Nada de configuracion propia: si este fichero bajara un umbral, el verde no
    demostraria que la entidad se reutiliza, solo que el resolutor se ha vuelto
    mas credulo -- que es justo lo que el encargo prohibe. `config` se deja sin
    tocar a proposito, de modo que `link_min_score`, `ambiguity_margin` y
    `alias_score` son los del producto.
    """
    from knowledge_v3.resolution import EntityResolver
    return EntityResolver(catalog=catalogo)


def _resolve(res, superficie: str, *, tipos=(("Faction", 0.92),)):
    """Una mencion suelta por el resolutor, con el mismo utillaje del subsistema.

    Se reusan las fixtures de `test_knowledge_v3_resolution` (cargadas por
    ruta, como hace ese fichero) en vez de fabricar aqui una `EntityMention` a
    mano: una mencion inventada por este fichero podria no ser la que el
    producto construye, y entonces el verde no diria nada del producto.
    """
    import importlib.util

    nombre = "s9k_v3_resolution_fixtures"
    if nombre in sys.modules:
        F = sys.modules[nombre]
    else:
        ruta = pathlib.Path(__file__).resolve().parent / (
            "test_knowledge_v3_resolution_fixtures.py"
        )
        spec = importlib.util.spec_from_file_location(nombre, ruta)
        F = importlib.util.module_from_spec(spec)
        sys.modules[nombre] = F
        spec.loader.exec_module(F)

    from knowledge_v3.resolution import ResolutionRequest, normalize_surface

    mid = "mention:" + normalize_surface(superficie).replace(" ", "-")
    mencion = F.mention(mid, superficie, types=tipos, workspace=WS)
    return res.resolve(ResolutionRequest.of(mencion), record_history=False)


# --- fixtures ---------------------------------------------------------------
@pytest.fixture(scope="module")
def conexion():
    with neo4j_efimero_conexion("s9k-eq8a-reutilizacion") as cx:
        yield cx


@pytest.fixture(scope="module")
def grafo_con_la_cofradia(conexion, tmp_path_factory):
    """CORRIDA 1: la fuente menciona el ALIAS. El nodo debe nacer canonico.

    Se comprueba primero que el grafo esta VACIO: si no lo estuviera, un
    enlace posterior podria venir de un nodo que no escribio esta corrida.
    """
    driver = conexion.driver
    vacio = _filas(driver, "MATCH (n:V3Entity) WHERE n.workspace = $ws "
                           "RETURN count(n) AS n", ws=WS)
    assert vacio[0]["n"] == 0, f"el grafo NO arranca vacio: {vacio}"

    tmp = tmp_path_factory.mktemp("eq8a")
    # El predicado ("es miembro de") es uno de los que la ontologia activa
    # admite: con un verbo fuera de ella el motor abstiene con
    # `PREDICATE_ABSENT`, el plan sale sin operaciones y no se escribe nada --
    # una prueba que no probaria el defecto, sino la ontologia. MEDIDO.
    # La mencion es el ALIAS a proposito: es la superficie que el defecto
    # persistia como si fuera el nombre.
    fuente = _fuente(
        tmp, "corrida1.md",
        "# Nota de sesion\n\n"
        f"Sela Marrec es miembro de {SUPERFICIE}.\n",
    )
    report = _corrida_con_apply(fuente, driver, CATALOGO)
    return report, tmp


# --- CASO 1: reutilizacion POR NOMBRE ---------------------------------------
def test_caso_1_el_nombre_persistido_es_el_canonico(grafo_con_la_cofradia, conexion):
    """El `name` del nodo se LEE del grafo. Es el canonico, no la superficie.

    Criterio 2 del encargo, y el que se pone rojo si alguien vuelve a
    persistir la superficie.
    """
    _report, _tmp = grafo_con_la_cofradia
    nodo = _nodo(conexion.driver, ENTIDAD)
    assert nodo["name"] == CANONICO, (
        f"el grafo guardo {nodo['name']!r}. Si es {SUPERFICIE!r}, se ha vuelto "
        f"a persistir la SUPERFICIE del alias en vez del nombre canonico; si "
        f"es {ENTIDAD!r}, el nombre no llego en absoluto."
    )
    # Y no por coincidir con nada: los tres valores en juego son distintos.
    assert nodo["name"] != SUPERFICIE
    assert nodo["name"] != ENTIDAD
    # La segunda puerta, ya en el nodo: el alias se PERSISTE.
    assert SUPERFICIE in (nodo["aliases"] or []), (
        f"el nodo nacio sin alias ({nodo['aliases']!r}): `step_alias` seguiria "
        "estructuralmente muerto en la corrida siguiente"
    )


def test_caso_1_la_corrida_siguiente_reutiliza_por_nombre(
    grafo_con_la_cofradia, conexion
):
    """CORRIDA 2, SIN `--catalogo`: el mundo sale SOLO del grafo.

    "Cofradia de Ambar" -> catalogo Neo4j -> LINK_EXISTING, nunca
    CREATE_PROVISIONAL.
    """
    _report, tmp = grafo_con_la_cofradia
    fuente = _fuente(tmp, "corrida2.md",
                     f"# Nota posterior\n\nSela Marrec lidera {CANONICO}.\n")
    seco = _ingesta(fuente, conexion.driver, None)  # <-- sin fichero de catalogo

    enlaces = [
        f for f in (seco["candidates"].get("link_existing") or [])
        if f.get("selected_entity_id") == ENTIDAD
    ]
    assert enlaces, (
        "la entidad NO se reutilizo: "
        f"link_existing={seco['candidates'].get('link_existing')} "
        f"create_entity={seco['candidates'].get('create_entity')}"
    )
    altas = [
        f for f in (seco["candidates"].get("create_entity") or [])
        if "cofradia" in str(f.get("assigned_entity_id", "")).lower()
    ]
    assert not altas, f"se propuso un alta para algo ya existente: {altas}"


# --- CASO 2: reutilizacion POR ALIAS (la senal 0.95, viva) -------------------
def test_caso_2_step_alias_dispara_contra_el_grafo_real(
    grafo_con_la_cofradia, conexion
):
    """La senal `EXACT_ALIAS` vuelve a existir contra un catalogo de Neo4j.

    Se ataca el catalogo REAL (`Neo4jEntityCatalog`), no un
    `InMemoryEntityCatalog`: el defecto vivia precisamente en que el catalogo
    de grafo no traia alias, asi que probarlo en memoria no probaria nada.
    """
    catalogo = Neo4jEntityCatalog(conexion.driver)
    entidades = {e.entity_id: e for e in catalogo.entities(WS)}
    assert entidades, "censo VACIO: el catalogo de grafo no devolvio entidades"

    cofradia = entidades.get(ENTIDAD)
    assert cofradia is not None, f"{ENTIDAD} no esta en el catalogo de grafo"
    assert cofradia.canonical_name == CANONICO
    assert SUPERFICIE in cofradia.aliases, (
        f"el catalogo de grafo no trae alias ({cofradia.aliases!r}): "
        "`step_alias` seguiria estructuralmente muerto"
    )

    salida = _resolve(_resolver(catalogo), SUPERFICIE)
    assert salida.entity_id == ENTIDAD, f"resolvio a {salida.entity_id!r}"
    assert "EXACT_ALIAS" in salida.resolution.reason_codes, (
        f"la senal de alias no disparo: {salida.resolution.reason_codes}"
    )


def test_caso_2_la_corrida_siguiente_reutiliza_por_alias(
    grafo_con_la_cofradia, conexion
):
    """Y por la ruta del producto: corrida SIN catalogo que menciona el alias."""
    _report, tmp = grafo_con_la_cofradia
    fuente = _fuente(tmp, "corrida3.md",
                     f"# Otra nota\n\nSela Marrec lidera {SUPERFICIE}.\n")
    seco = _ingesta(fuente, conexion.driver, None)
    enlaces = [
        f for f in (seco["candidates"].get("link_existing") or [])
        if f.get("selected_entity_id") == ENTIDAD
    ]
    assert enlaces, (
        "el alias no reutilizo la entidad: "
        f"{seco['candidates'].get('create_entity')}"
    )


# --- CASO 3: la ambiguedad SIGUE degradando ---------------------------------
def test_caso_3_la_ambiguedad_genuina_sigue_degradando():
    """Dos entidades que declaran el MISMO alias exacto -> REVIEW.

    No depende de ningun umbral: son dos alias identicos, empate perfecto. Este
    caso debe dar EXACTAMENTE lo mismo antes y despues del arreglo, y es la
    condicion de aceptacion que impide "arreglar" la reutilizacion volviendo el
    resolutor mas agresivo.
    """
    from knowledge_v3.resolution.catalog import CatalogEntity, InMemoryEntityCatalog

    def faccion(eid, nombre, alias):
        return CatalogEntity(entity_id=eid, workspace=WS, entity_type="Faction",
                             canonical_name=nombre, aliases=alias)

    catalogo = InMemoryEntityCatalog([
        faccion("entity:faction:marea-negra", "Marea Negra", ("la Marea",)),
        faccion("entity:faction:marea-roja", "Marea Roja", ("la Marea",)),
    ])
    salida = _resolve(_resolver(catalogo), "la Marea")
    assert salida.action == "REVIEW"
    assert salida.entity_id is None
    assert salida.resolution.reason_codes.count("AMBIGUOUS_CANDIDATES") == 1
