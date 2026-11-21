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
            import sys as _sys
            _raiz = str(REPO / "data-engine" / "app")
            if _raiz not in _sys.path:
                _sys.path.insert(0, _raiz)
            from knowledge_v3.writer.schema import reader_role_grants
            for sentencia in (
                f"CREATE ROLE {ROL}",
                # RC2-02: UNA sola autoridad del rol (schema.READER_ROLE_PRIVILEGES).
                *reader_role_grants(ROL, "neo4j"),
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


# --- RC2-02: las tres identidades, medidas contra el servidor -----------------
#
# Todo lo de este bloque se demuestra por EFECTO, leido con la administradora:
# no basta con un rc. La primera ronda afirmo «ensure con la lectora se deniega»
# sobre un esquema completo y el servidor dijo rc 0 (MEDIDO en la CI, run
# 44825358259): `CREATE ... IF NOT EXISTS` sobre lo que ya existe no se
# deniega. Lo que SI se puede demostrar es que la lectora no crea lo que FALTA.

def _rc202():
    import sys

    raiz = str(REPO / "data-engine" / "app")
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    from knowledge_v3 import driver_neo4j
    from knowledge_v3.writer import schema, schema_cli

    return schema, schema_cli, driver_neo4j


def _cli(accion, driver_factory=None, argv=(), env=None):
    import io
    import json

    _, schema_cli, _ = _rc202()
    salida, error = io.StringIO(), io.StringIO()
    rc = schema_cli.run([accion, "--json", *argv], driver_factory=driver_factory,
                        env=env, stdout=salida, stderr=error)
    objetos = [json.loads(l) for l in salida.getvalue().splitlines() if l.startswith("{")]
    return rc, (objetos[-1] if objetos else {}), salida.getvalue(), error.getvalue()


def _constraints(driver) -> set:
    with driver.session() as sesion:
        return {r["name"] for r in sesion.run("SHOW CONSTRAINTS YIELD name RETURN name")}


def _indexes(driver) -> set:
    with driver.session() as sesion:
        return {r["name"] for r in sesion.run("SHOW INDEXES YIELD name RETURN name")}


def _sistema(grafo_rbac, *sentencias):
    with grafo_rbac["admin"].session(database="system") as sesion:
        for s in sentencias:
            sesion.run(s).consume()


class _Cuenta:
    """Un rol de la AUTORIDAD (`schema.role_grants`), opcionalmente sin una
    concesion, y un usuario que solo lo tiene. Se retira al salir."""

    def __init__(self, grafo_rbac, canonico, nombre, db="neo4j", quitar=()):
        schema, _, _ = _rc202()
        self.grafo = grafo_rbac
        self.rol = f"rc202_{nombre}"
        self.usuario = f"rc202_{nombre}_u"
        self.clave = "Rc202-" + uuid.uuid4().hex[:14]
        self.db = db
        concesiones = [
            g for g in schema.role_grants(canonico, self.rol, db)
            if not any(q in g for q in quitar)
        ]
        assert len(concesiones) == len(schema.role_grants(canonico, self.rol, db)) - len(quitar), (
            f"la concesion a quitar {quitar} no estaba en el rol {canonico}"
        )
        self.concesiones = concesiones

    def __enter__(self):
        _sistema(
            self.grafo,
            f"CREATE ROLE {self.rol}",
            *self.concesiones,
            f"CREATE USER {self.usuario} SET PASSWORD '{self.clave}' "
            "SET PASSWORD CHANGE NOT REQUIRED",
            f"GRANT ROLE {self.rol} TO {self.usuario}",
        )
        return self

    def __exit__(self, *exc):
        _sistema(self.grafo, f"DROP USER {self.usuario} IF EXISTS",
                 f"DROP ROLE {self.rol} IF EXISTS")
        return False

    def driver(self):
        import neo4j

        _, _, driver_neo4j = _rc202()
        crudo = neo4j.GraphDatabase.driver(
            self.grafo["uri"], auth=(self.usuario, self.clave))
        return driver_neo4j._DriverEnBase(crudo, self.db)


class _BaseFresca:
    """Una base RECIEN CREADA (Enterprise): sin etiquetas, tipos ni propiedades.
    Es lo que hace visible si un rol necesita crear nombres nuevos."""

    def __init__(self, grafo_rbac, nombre):
        self.grafo = grafo_rbac
        self.nombre = nombre

    def __enter__(self):
        _sistema(self.grafo, f"CREATE DATABASE {self.nombre} IF NOT EXISTS WAIT")
        _, _, driver_neo4j = _rc202()
        self.admin = driver_neo4j._DriverEnBase(self.grafo["admin"], self.nombre)
        return self

    def __exit__(self, *exc):
        _sistema(self.grafo, f"DROP DATABASE {self.nombre} IF EXISTS WAIT")
        return False


@neo4j_real
def test_rc2_02_la_lectora_ve_lo_que_falta_y_no_puede_crearlo(grafo_rbac):
    """B1. Con la administradora se retira una restriccion requerida; la
    lectora la ve FALTAR (rc 3) y no la puede crear (rc 5); la administradora
    comprueba que SIGUE ausente. Se repone tambien si algo falla."""
    schema, schema_cli, _ = _rc202()
    admin = grafo_rbac["admin"]
    objetivo = schema.REQUIRED_CONSTRAINT_NAMES[0]
    assert objetivo in _constraints(admin), (
        f"SUELO: la restriccion {objetivo} no estaba antes de retirarla; el caso no mediria nada"
    )
    try:
        with admin.session() as sesion:
            sesion.run(f"DROP CONSTRAINT {objetivo} IF EXISTS").consume()
        assert objetivo not in _constraints(admin), "la administradora no pudo retirar la restriccion"

        rc, censo, _, err = _cli("verify", lambda: _driver_lector(grafo_rbac))
        assert rc == schema_cli.RC_INCOMPLETO, (
            f"verify con la lectora y una restriccion ausente debia dar rc 3: rc={rc} {err}"
        )
        assert censo.get("constraints_faltantes") == [objetivo], (
            f"verify no ve exactamente la ausente: {censo}"
        )

        rc, datos, _, err = _cli("ensure", lambda: _driver_lector(grafo_rbac))
        assert rc == schema_cli.RC_SIN_PRIVILEGIO, (
            f"ensure con la lectora y una restriccion ausente debia dar rc 5: rc={rc} {err}"
        )
        assert datos.get("error_code") == schema.SCHEMA_PRIVILEGE_MISSING, (
            f"ensure de la lectora sin el codigo estable de denegacion: {datos}"
        )
        assert datos.get("operacion_denegada") == schema.OP_CREATE_CONSTRAINT, (
            f"la denegacion no se atribuye a CREATE CONSTRAINT: {datos}"
        )
        assert objetivo not in _constraints(admin), (
            "EFECTO: tras el ensure de la lectora la restriccion EXISTE: la lectora creo esquema"
        )
    finally:
        schema.bootstrap_writer_schema(admin)
    assert objetivo in _constraints(admin), "no se pudo reponer la restriccion retirada"

    # Lo OBSERVADO en la primera ronda, ahora fijado: con el esquema completo
    # la lectora sale rc 0 sin crear nada (no hay nada que denegar).
    rc, censo, _, err = _cli("ensure", lambda: _driver_lector(grafo_rbac))
    assert rc == schema_cli.RC_OK, f"ensure de la lectora con esquema completo: rc={rc} {err}"


@neo4j_real
def test_rc2_02_gemelo_del_defecto_original_sin_show_constraint_verify_da_rc_5(grafo_rbac):
    """El defecto ORIGINAL reproducido: un rol lector SIN `SHOW CONSTRAINT`.
    `verify` sale rc 5 nombrando esa operacion y ese privilegio, no rc 2."""
    schema, schema_cli, _ = _rc202()
    with _Cuenta(grafo_rbac, schema.READER_ROLE_NAME, "lector_sin_show",
                 quitar=("GRANT SHOW CONSTRAINT",)) as cuenta:
        rc, datos, _, err = _cli("verify", cuenta.driver, ["--neo4j-user", cuenta.usuario])
    assert rc == schema_cli.RC_SIN_PRIVILEGIO, (
        f"un rol sin SHOW CONSTRAINT debia dar rc 5 (denegacion), no {rc}: {err}"
    )
    assert datos.get("operacion_denegada") == schema.OP_SHOW_CONSTRAINTS, (
        f"la denegacion del gemelo no se atribuye a SHOW CONSTRAINTS: {datos}"
    )
    assert datos.get("privilegio_habitual") == schema.PRIVILEGE_SHOW_CONSTRAINT, (
        f"el gemelo no nombra SHOW CONSTRAINT como privilegio habitual: {datos}"
    )
    assert cuenta.usuario in err, "el mensaje no nombra la cuenta"


@neo4j_real
def test_rc2_02_la_identidad_de_esquema_instala_por_el_camino_del_envoltorio(
    grafo_rbac, tmp_path, monkeypatch
):
    """B5. En una base recien creada, `ensure` con la identidad de esquema
    pasada POR ARGUMENTO, mientras el entorno (lo que `s9k-cli.sh` exporta de
    worker.env) declara la cuenta lectora, y el secreto por stdin. La
    administradora observa el esquema completo. Y esa identidad no escribe datos."""
    import io

    schema, schema_cli, driver_neo4j = _rc202()
    fichero_lector = tmp_path / "clave-lector"
    fichero_lector.write_text(CLAVE_LECTOR, encoding="utf-8")
    fichero_lector.chmod(0o600)
    with _BaseFresca(grafo_rbac, "rc202esquema") as base:
        assert _constraints(base.admin) == set(), "SUELO: la base fresca ya traia restricciones"
        with _Cuenta(grafo_rbac, schema.SCHEMA_ROLE_NAME, "esquema", db=base.nombre) as cuenta:
            env = {
                driver_neo4j.ENV_URI: grafo_rbac["uri"],
                driver_neo4j.ENV_USER: USUARIO_LECTOR,
                driver_neo4j.ENV_PASSWORD_FILE: str(fichero_lector),
                driver_neo4j.ENV_DATABASE: base.nombre,
            }
            monkeypatch.setattr("sys.stdin", io.StringIO(cuenta.clave + "\n"))
            rc, censo, _, err = _cli(
                "ensure", None,
                ["--neo4j-user", cuenta.usuario, "--neo4j-password-file", "-"], env=env,
            )
            if rc != schema_cli.RC_OK:
                crudo = _denegacion_cruda(cuenta, schema.APPLIED_OPERATION_CONSTRAINT_CYPHER)
                pytest.fail(
                    f"ensure con la identidad de esquema en una base recien creada: "
                    f"rc={rc} {err} (servidor, diagnostico del test: {crudo})"
                )
            assert censo.get("completo") is True, f"el censo tras ensure no es completo: {censo}"
            faltan_c = set(schema.REQUIRED_CONSTRAINT_NAMES) - _constraints(base.admin)
            faltan_i = set(schema.REQUIRED_INDEX_NAMES) - _indexes(base.admin)
            assert not faltan_c and not faltan_i, (
                f"EFECTO: la administradora no ve el esquema instalado: {faltan_c} {faltan_i}"
            )

            drv = cuenta.driver()
            try:
                with pytest.raises(Exception) as fallo:
                    with drv.session() as sesion:
                        sesion.run("CREATE (:Intruso {x: 1})").consume()
            finally:
                drv.close()
            assert getattr(fallo.value, "code", "") == "Neo.ClientError.Security.Forbidden", (
                f"la identidad de esquema escribio datos o fallo por otra causa: {fallo.value!r}"
            )
            with base.admin.session() as sesion:
                assert sesion.run("MATCH (n) RETURN count(n) AS n").single()["n"] == 0, (
                    "la identidad de esquema dejo un nodo"
                )


def _denegacion_cruda(cuenta, cypher) -> str:
    """DIAGNOSTICO del test (no del producto): que dice el servidor ante `cypher`."""
    drv = cuenta.driver()
    try:
        with drv.session() as sesion:
            sesion.run(cypher).consume()
        return "(el servidor NO denego)"
    except Exception as exc:  # noqa: BLE001
        return f"{getattr(exc, 'code', type(exc).__name__)}: {getattr(exc, 'message', exc)}"
    finally:
        drv.close()


@neo4j_real
@pytest.mark.parametrize("quitar,base_nombre", [
    ("GRANT CREATE NEW NODE LABEL", "rc202sinlabel"),
    ("GRANT CREATE NEW PROPERTY NAME", "rc202sinprop"),
], ids=["sin-create-new-label", "sin-create-new-property-name"])
def test_rc2_02_gemelo_la_identidad_de_esquema_sin_crear_nombres_no_instala(
    grafo_rbac, quitar, base_nombre
):
    """Cada una de las dos concesiones de nombres es NECESARIA: sin ella, en una
    base recien creada, `ensure` sale rc 5 en `CREATE CONSTRAINT` y no queda
    ninguna restriccion. Una base por caso: un token creado por un caso no
    puede tapar al siguiente."""
    schema, schema_cli, _ = _rc202()
    with _BaseFresca(grafo_rbac, base_nombre) as base:
        with _Cuenta(grafo_rbac, schema.SCHEMA_ROLE_NAME, "esquema_gemelo",
                     db=base.nombre, quitar=(quitar,)) as cuenta:
            rc, datos, _, err = _cli("ensure", cuenta.driver, ["--neo4j-user", cuenta.usuario])
            crudo = _denegacion_cruda(cuenta, schema.APPLIED_OPERATION_CONSTRAINT_CYPHER)
        assert rc == schema_cli.RC_SIN_PRIVILEGIO, (
            f"sin {quitar} la identidad de esquema instalo igualmente: la concesion "
            f"no es necesaria y sobra en la lista blanca (rc={rc}; servidor: {crudo})"
        )
        assert datos.get("operacion_denegada") == schema.OP_CREATE_CONSTRAINT, (
            f"sin {quitar}: denegacion atribuida a otra operacion: {datos} (servidor: {crudo})"
        )
        assert _constraints(base.admin) == set(), (
            f"sin {quitar} quedo esquema instalado: {_constraints(base.admin)}"
        )


def _modulo_writer_real():
    """Utillaje del test real del writer (planes, sondas), sin copiarlo."""
    import importlib.util

    import sys

    nombre = "_rc202_utillaje_writer_real"
    if nombre in sys.modules:
        return sys.modules[nombre]
    ruta = REPO / "data-engine" / "app" / "tests" / "test_knowledge_v3_writer_neo4j_real.py"
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    # MEDIDO en la CI: `@dataclass` busca su modulo en `sys.modules`; sin
    # registrarlo antes, el import revienta con AttributeError.
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def _plan_con_todas_las_operaciones(W):
    return W.make_plan([
        W.create_entity("op:0001", "entity:nueva", "Nueva"),
        W.create_assertion("op:0002", "assertion:nueva", "entity:origen", "entity:destino"),
        W.link_existing("op:0003", "entity:origen", "entity:destino"),
        W.update_entity("op:0004", "entity:origen"),
        W.supersede_assertion("op:0005", "assertion:vieja", successor="assertion:nueva"),
    ])


def _sembrar(W, probe):
    probe.clean()
    probe.seed_entity("entity:origen", version=1, state_hash=W.HASH_A["value"])
    probe.seed_entity("entity:destino", version=1, state_hash=W.HASH_C["value"])
    probe.seed_assertion("assertion:vieja", version=1, state_hash=W.HASH_B["value"])


@neo4j_real
def test_rc2_02_el_writer_aplica_con_el_rol_de_escritura_y_no_con_menos(grafo_rbac):
    """B5, la cuenta del APPLY. En una base recien creada con el esquema puesto:

    * sin `NAME MANAGEMENT` el writer NO aplica y el grafo no cambia (las
      etiquetas, tipos y propiedades nuevas no existen todavia);
    * sin `SHOW CONSTRAINT` el writer NO escribe y el rechazo lo dice
      (`SCHEMA_PRIVILEGE_MISSING`, operacion denegada), sin texto del servidor;
    * con el rol EXACTO de la autoridad aplica todas las operaciones;
    * y esa cuenta no puede crear esquema.
    """
    schema, _, _ = _rc202()
    W = _modulo_writer_real()
    from knowledge_v3.writer.writer import OUTCOME_APPLIED  # noqa: PLC0415

    with _BaseFresca(grafo_rbac, "rc202escritor") as base:
        schema.bootstrap_writer_schema(base.admin)
        probe = W.GraphProbe(driver=base.admin)
        _sembrar(W, probe)
        suelo = probe.knowledge_counts()

        with _Cuenta(grafo_rbac, schema.WRITER_ROLE_NAME, "escritor_sin_nombres",
                     db=base.nombre, quitar=("GRANT NAME MANAGEMENT",)) as cuenta:
            drv = cuenta.driver()
            try:
                plan = _plan_con_todas_las_operaciones(W)
                res = W.writer(drv).write(plan, W.apply_request(plan))
            finally:
                drv.close()
        assert res.outcome != OUTCOME_APPLIED, (
            "SIN NAME MANAGEMENT el writer aplico en una base recien creada: el "
            f"privilegio no es necesario y sobra en la lista blanca ({res.codes})"
        )
        mensajes = [r.message for r in res.rejections]
        assert W.codes.EXEC_DRIVER_FAILURE in res.codes and any(
            schema.NEO4J_FORBIDDEN_CODE in m for m in mensajes
        ), (
            "sin NAME MANAGEMENT el writer no aplico, pero NO por una denegacion "
            f"del servidor: {res.codes} {mensajes}"
        )
        assert probe.knowledge_counts() == suelo, "sin NAME MANAGEMENT el grafo cambio"

        with _Cuenta(grafo_rbac, schema.WRITER_ROLE_NAME, "escritor_sin_show",
                     db=base.nombre, quitar=("GRANT SHOW CONSTRAINT",)) as cuenta:
            drv = cuenta.driver()
            try:
                plan = _plan_con_todas_las_operaciones(W)
                res = W.writer(drv).write(plan, W.apply_request(plan))
            finally:
                drv.close()
        assert res.outcome != OUTCOME_APPLIED, "sin SHOW CONSTRAINT el writer escribio"
        rechazo = next((r for r in res.rejections
                        if r.code == W.codes.EXEC_SCHEMA_CONSTRAINTS_MISSING), None)
        assert rechazo is not None, f"sin SHOW CONSTRAINT: rechazo inesperado {res.codes}"
        assert rechazo.detail == {
            "error_code": schema.SCHEMA_PRIVILEGE_MISSING,
            "operacion_denegada": schema.OP_SHOW_CONSTRAINTS,
            "privilegio_habitual": schema.PRIVILEGE_SHOW_CONSTRAINT,
        }, f"el rechazo del writer sin SHOW CONSTRAINT no dice la causa: {rechazo.detail}"
        assert probe.knowledge_counts() == suelo, "sin SHOW CONSTRAINT el grafo cambio"

        with _Cuenta(grafo_rbac, schema.WRITER_ROLE_NAME, "escritor", db=base.nombre) as cuenta:
            drv = cuenta.driver()
            try:
                plan = _plan_con_todas_las_operaciones(W)
                res = W.writer(drv).write(plan, W.apply_request(plan))
                with pytest.raises(Exception) as fallo:
                    with drv.session() as sesion:
                        sesion.run(
                            "CREATE INDEX rc202_intruso IF NOT EXISTS "
                            "FOR (n:V3Entity) ON (n.intruso)"
                        ).consume()
            finally:
                drv.close()
        assert res.outcome == OUTCOME_APPLIED, (
            f"con el rol de escritura de la autoridad el writer NO aplico: {res.codes} "
            f"{[r.message for r in res.rejections]}"
        )
        assert probe.knowledge_counts() == {"nodes": 5, "relationships": 1}, (
            f"EFECTO: el APPLY no dejo lo esperado: {probe.knowledge_counts()}"
        )
        assert getattr(fallo.value, "code", "") == "Neo.ClientError.Security.Forbidden", (
            f"la cuenta de escritura creo esquema o fallo por otra causa: {fallo.value!r}"
        )
        assert "rc202_intruso" not in _indexes(base.admin), "la cuenta de escritura creo un indice"


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
