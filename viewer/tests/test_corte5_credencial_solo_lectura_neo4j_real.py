# -*- coding: utf-8 -*-
"""Slice 2 · Corte 5 — la credencial del worker es de SÓLO LECTURA de verdad.

POR QUÉ EXISTE ESTE MÓDULO
--------------------------
El Corte 5 le da al worker capacidad de LEER el grafo. En la primera vuelta eso
se documentó como «credencial mínima: basta permiso de lectura» y se afirmó que
la conexión era de sólo lectura. **Era una intención, no una propiedad.** Una
revisión independiente escribió con éxito por esa conexión y ninguna prueba se
puso roja: lo único que impedía una escritura era que ningún camino de código
emitiera una.

Aquí la propiedad pasa a ser de la CUENTA, y se comprueba:

* se crea un rol de Neo4j con `ACCESS` + `MATCH` y **ninguna** capacidad de
  escritura, y un usuario que sólo tiene ese rol;
* se comprueba que ese usuario **lee**;
* se comprueba que **no puede escribir**, y no por «no hubo excepción» sino por
  las dos cosas a la vez: el servidor responde
  `Neo.ClientError.Security.Forbidden` **y** el recuento de nodos no se mueve;
* y se comprueba que **la ingesta del panel funciona entera con esa cuenta**,
  que es lo que demuestra que el producto no necesita más privilegio del que se
  le concede.

LA CALIBRACIÓN VA DENTRO, NO AL LADO
------------------------------------
Cada denegación se acompaña de su GEMELA con la cuenta administradora, que sí
escribe. Sin ese par, «no pudo escribir» podría significar «la sentencia era
inválida», «no había nodos que tocar» o «el contenedor estaba caído», y las
tres se leen igual de verdes. MEDIDO durante la construcción de este módulo:
`MATCH (n) SET n.x = 1` sobre un grafo **vacío** sale OK con la cuenta de sólo
lectura --no matchea nada, luego no intenta escribir-- y habría publicado un
falso «puede escribir». Por eso se siembra antes y se afirma el suelo.

EDICIÓN DE NEO4J: ESTO NO ES UN DETALLE DE ARNÉS
------------------------------------------------
MEDIDO contra `neo4j:5.26-community`: `CREATE USER` funciona, pero `CREATE
ROLE`, `SHOW ROLES` y `ALTER DATABASE ... SET ACCESS READ ONLY` responden
`UnsupportedAdministrationCommand`, y un usuario creado en Community **escribe
sin restricción**. Es decir: **en Community una cuenta de sólo lectura no se
puede expresar.** Por eso este módulo levanta una instancia ENTERPRISE, y por
eso `deploy/README.md` convierte la edición en una condición de despliegue en
vez de una recomendación.

Aceptar la licencia de evaluación de Neo4j para el contenedor efímero de esta
prueba es una decisión del operador; está declarada abajo en una sola línea
visible (`NEO4J_ACCEPT_LICENSE_AGREEMENT`) para que se pueda vetar.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EJEMPLOS = REPO / "examples" / "ingesta-v3"

#: Prefijo PROPIO. Se retira por NOMBRE; nunca un `prune` global, que se
#: llevaría por delante material de otros carriles vivos en esta máquina.
PREFIJO = "s9k-corte5-rbac"

#: Imagen con RBAC. Community NO sirve, y el docstring dice por qué medido.
IMAGEN = os.environ.get("S9K_RBAC_NEO4J_IMAGE", "neo4j:5.26-enterprise")

#: LA DECLARACIÓN DE LICENCIA, en una línea y a la vista. Es de evaluación y
#: sólo para el contenedor efímero de esta prueba.
LICENCIA = "eval"

WRITER_REAL = os.environ.get("S9K_WRITER_NEO4J_REAL") == "1"
neo4j_real = pytest.mark.skipif(
    not WRITER_REAL,
    reason="sin S9K_WRITER_NEO4J_REAL=1 no hay grafo: la credencial no se comprueba",
)

ROL = "s9k_observador"
USUARIO_LECTOR = "s9k_worker_lector"
CLAVE_LECTOR = "Observador-Corte5-" + uuid.uuid4().hex[:10]


def _docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True)


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def grafo_rbac():
    """Neo4j Enterprise efímero con un rol de sólo lectura de verdad."""
    if not WRITER_REAL:
        pytest.skip("sin S9K_WRITER_NEO4J_REAL=1")
    import neo4j

    nombre = f"{PREFIJO}-{uuid.uuid4().hex[:10]}"
    puerto = _puerto_libre()
    clave_admin = "Admin-Corte5-" + uuid.uuid4().hex[:12]
    arranque = _docker(
        "run", "--rm", "--detach", "--name", nombre,
        "--publish", f"127.0.0.1:{puerto}:7687",
        "--env", f"NEO4J_AUTH=neo4j/{clave_admin}",
        "--env", f"NEO4J_ACCEPT_LICENSE_AGREEMENT={LICENCIA}",
        "--env", "NEO4J_server_memory_heap_max__size=512m",
        IMAGEN,
    )
    assert arranque.returncode == 0, (
        "no se pudo arrancar Neo4j Enterprise; sin él la credencial de sólo "
        f"lectura NO se comprueba y eso no puede pasar como verde: "
        f"{arranque.stderr[:300]}"
    )
    uri = f"bolt://127.0.0.1:{puerto}"
    admin = None
    try:
        limite = time.time() + 300
        ultimo = None
        while time.time() < limite:
            try:
                admin = neo4j.GraphDatabase.driver(uri, auth=("neo4j", clave_admin))
                admin.verify_connectivity()
                break
            except Exception as exc:  # noqa: BLE001
                ultimo = exc
                if admin is not None:
                    admin.close()
                    admin = None
                time.sleep(3)
        assert admin is not None, f"Neo4j Enterprise no llegó a estar listo: {ultimo}"

        # EL ROL: acceso y lectura, y NADA de escritura. No se concede
        # `WRITE`, ni `CREATE`, ni `SET`, ni `DELETE`, ni `MERGE`. Lo que no se
        # concede aquí es lo que las denegaciones de abajo comprueban.
        with admin.session(database="system") as sesion:
            for sentencia in (
                f"CREATE ROLE {ROL}",
                f"GRANT ACCESS ON DATABASE neo4j TO {ROL}",
                f"GRANT MATCH {{*}} ON GRAPH neo4j NODES * TO {ROL}",
                f"GRANT MATCH {{*}} ON GRAPH neo4j RELATIONSHIPS * TO {ROL}",
                f"CREATE USER {USUARIO_LECTOR} SET PASSWORD '{CLAVE_LECTOR}' "
                f"SET PASSWORD CHANGE NOT REQUIRED",
                f"GRANT ROLE {ROL} TO {USUARIO_LECTOR}",
            ):
                sesion.run(sentencia).consume()

        import sys
        raiz = str(REPO / "data-engine" / "app")
        if raiz not in sys.path:
            sys.path.insert(0, raiz)
        from knowledge_v3.writer.schema import bootstrap_writer_schema
        bootstrap_writer_schema(admin)

        yield {"uri": uri, "admin": admin, "clave_admin": clave_admin}
    finally:
        if admin is not None:
            admin.close()
        _docker("rm", "-f", nombre)


@pytest.fixture
def sembrado(grafo_rbac):
    """Un grafo con MATERIAL. Sin él, las denegaciones no medirían nada.

    `MATCH ... SET` sobre un grafo vacío no intenta escribir y sale OK incluso
    sin permiso. Ese falso verde se dio de verdad al construir este módulo.
    """
    admin = grafo_rbac["admin"]
    with admin.session() as sesion:
        sesion.run("MATCH (n) DETACH DELETE n").consume()
        sesion.run(
            "CREATE (:V3Entity {entity_id:'entity:sela-marrec', "
            "workspace:'ws-cofradia', entity_type:'Character', "
            "name:'Sela Marrec', version:7, status:'ACTIVE'})"
        ).consume()
        total = sesion.run("MATCH (n) RETURN count(n) AS n").single()["n"]
    assert total > 0, "el suelo no se cumple: sin nodos nada de esto mide nada"
    yield total
    with admin.session() as sesion:
        sesion.run("MATCH (n) DETACH DELETE n").consume()


def _driver_lector(grafo_rbac):
    import neo4j

    return neo4j.GraphDatabase.driver(
        grafo_rbac["uri"], auth=(USUARIO_LECTOR, CLAVE_LECTOR)
    )


def _cuantos(grafo_rbac) -> int:
    with grafo_rbac["admin"].session() as sesion:
        return sesion.run("MATCH (n) RETURN count(n) AS n").single()["n"]


#: Las cuatro formas de escribir que el motor podría emitir. Se prueban las
#: cuatro: conceder `MATCH` y olvidar que `MERGE` es otra capacidad sería
#: exactamente el hueco por el que se cuela una escritura.
ESCRITURAS = [
    ("CREATE", "CREATE (:Intruso {x: 1})"),
    ("SET", "MATCH (n:V3Entity) SET n.intruso = 1"),
    ("DELETE", "MATCH (n:V3Entity) DETACH DELETE n"),
    ("MERGE", "MERGE (:Intruso {x: 2})"),
]


@neo4j_real
def test_la_cuenta_del_worker_SI_lee(grafo_rbac, sembrado):
    """SUELO. Una cuenta que no leyera haría verdes las denegaciones de abajo.

    Si el usuario no pudiera ni conectar, los cuatro casos siguientes saldrían
    «denegado» por el motivo equivocado y este módulo afirmaría una propiedad
    de seguridad que en realidad no ha ejercido.
    """
    lector = _driver_lector(grafo_rbac)
    try:
        lector.verify_connectivity()
        with lector.session() as sesion:
            filas = sesion.run(
                "MATCH (n:V3Entity {workspace:'ws-cofradia'}) "
                "RETURN n.entity_id AS id ORDER BY n.entity_id"
            ).data()
    finally:
        lector.close()
    assert [f["id"] for f in filas] == ["entity:sela-marrec"], filas


@neo4j_real
@pytest.mark.parametrize("forma,cypher", ESCRITURAS,
                         ids=[f[0] for f in ESCRITURAS])
def test_la_cuenta_del_worker_NO_PUEDE_escribir(grafo_rbac, sembrado, forma, cypher):
    """LA PRUEBA NEGATIVA QUE FALTABA. Dos afirmaciones, no una.

    1. el servidor responde `Neo.ClientError.Security.Forbidden` -- o sea, lo
       para la AUTORIZACIÓN de Neo4j, no una sentencia mal escrita;
    2. y el EFECTO no ocurre: el recuento de nodos, leído con la cuenta
       administradora, es el mismo antes y después.

    La segunda sobra si te fías de la primera, y está justamente porque no hay
    que fiarse: una excepción puede llegar después de un cambio parcial.
    """
    antes = _cuantos(grafo_rbac)
    lector = _driver_lector(grafo_rbac)
    try:
        with pytest.raises(Exception) as fallo:
            with lector.session() as sesion:
                sesion.run(cypher).consume()
    finally:
        lector.close()

    codigo = getattr(fallo.value, "code", "")
    assert codigo == "Neo.ClientError.Security.Forbidden", (
        f"la escritura {forma} no la paró la AUTORIZACIÓN de Neo4j, sino "
        f"{codigo or type(fallo.value).__name__!r}. Un rojo por otra causa no "
        "demuestra que la cuenta sea de sólo lectura."
    )
    assert _cuantos(grafo_rbac) == antes, (
        f"la escritura {forma} fue denegada y aun así el grafo cambió"
    )


@neo4j_real
@pytest.mark.parametrize("forma,cypher", ESCRITURAS,
                         ids=[f[0] for f in ESCRITURAS])
def test_CALIBRACION_la_misma_escritura_SI_pasa_con_una_cuenta_con_permiso(
    grafo_rbac, sembrado, forma, cypher
):
    """EL GEMELO. Sin él, «denegado» no distingue de «sentencia imposible».

    La MISMA sentencia, el MISMO grafo, el MISMO momento; lo único distinto es
    la credencial. Con la administradora pasa. Es lo que convierte el caso de
    arriba en una medida de la CUENTA y no del Cypher.

    Esto es también la respuesta al hallazgo de la revisión: con una credencial
    con permisos de escritura, la comprobación de arriba enrojece.
    """
    antes = _cuantos(grafo_rbac)
    with grafo_rbac["admin"].session() as sesion:
        sesion.run(cypher).consume()
    despues = _cuantos(grafo_rbac)
    assert despues != antes or forma == "SET", (
        f"la escritura {forma} no cambió nada ni con la cuenta administradora: "
        "entonces la denegación de arriba no prueba nada, porque esta "
        "sentencia no escribe en este montaje"
    )
    if forma == "SET":
        with grafo_rbac["admin"].session() as sesion:
            marcadas = sesion.run(
                "MATCH (n:V3Entity) WHERE n.intruso IS NOT NULL "
                "RETURN count(n) AS n"
            ).single()["n"]
        assert marcadas > 0, (
            "el `SET` no marcó ni un nodo ni con la cuenta administradora: la "
            "denegación de arriba sería la de una sentencia que no escribe"
        )


@neo4j_real
def test_la_ingesta_DEL_PANEL_funciona_entera_con_la_cuenta_de_solo_lectura(
    grafo_rbac, sembrado, tmp_path, monkeypatch
):
    """EL PRODUCTO, CON EL PRIVILEGIO MÍNIMO. Es la otra mitad de la prueba.

    Que la cuenta no pueda escribir sólo es útil si el producto FUNCIONA con
    ella. Aquí se corre el manejador de ingesta del panel --el mismo símbolo
    que despacha el worker-- configurado con la credencial de sólo lectura, y
    se exige que la corrida termine y haya OBSERVADO el grafo.

    Y se comprueba el efecto: el grafo no se mueve.
    """
    import sys

    raiz = str(REPO / "data-engine" / "app")
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    from jobs.handlers.ingest_v3 import handle_ingest_v3

    fichero = tmp_path / "clave-lector"
    fichero.write_text(CLAVE_LECTOR, encoding="utf-8")
    fichero.chmod(0o600)
    monkeypatch.setenv("S9K_NEO4J_URI", grafo_rbac["uri"])
    monkeypatch.setenv("S9K_NEO4J_USER", USUARIO_LECTOR)
    monkeypatch.setenv("S9K_NEO4J_PASSWORD_FILE", str(fichero))
    monkeypatch.delenv("S9K_NEO4J_DATABASE", raising=False)

    fuentes = tmp_path / "fuentes"
    fuentes.mkdir()
    for nombre in ("perfil-operador.json", "catalogo-workspace.json"):
        shutil.copy(EJEMPLOS / nombre, fuentes / nombre)
    shutil.copy(EJEMPLOS / "nota-cofradia-de-ambar.md",
                fuentes / "nota-cofradia-de-ambar.md")

    antes = _cuantos(grafo_rbac)
    resultado = handle_ingest_v3({
        "source_path": str(fuentes / "nota-cofradia-de-ambar.md"),
        "profile_path": str(fuentes / "perfil-operador.json"),
        "catalog_path": str(fuentes / "catalogo-workspace.json"),
        "workspace": "ws-cofradia",
    }, job_id="job-rbac-corte5")

    resumen = resultado.get("resumen") or resultado
    assert resumen.get("observacion") == "SI (grafo, solo lectura)", resultado
    assert resumen.get("escritura") == "NO (simulacion)", resultado
    assert _cuantos(grafo_rbac) == antes, (
        "la ingesta con credencial de sólo lectura cambió el grafo"
    )
