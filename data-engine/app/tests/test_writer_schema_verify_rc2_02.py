# -*- coding: utf-8 -*-
"""RC2-02: `writer-schema verify` con la cuenta de SOLO LECTURA, y las tres identidades.

Hallazgo (docs/94 §6.2): con el rol lector documentado, `verify` salia con rc 2
y `Forbidden`. Decision D4: separar privilegios; el rol lector gana SOLO lectura
de esquema (`SHOW CONSTRAINT`, `SHOW INDEX`), nunca escritura ni DDL. `ensure`
lo hace una identidad de esquema; el APPLY, una de escritura.

Arnes sin Neo4j: un doble de driver que MODELA lo que el servidor real hace con
cada cuenta (lee esquema / no lo lee / crea / no crea), incluido lo MEDIDO en la
CI contra Neo4j 5.26 Enterprise (run 44825358259, job «Viewer Tests»
136596455013): con el esquema completo, `ensure` con la cuenta lectora sale
rc 0, porque `CREATE ... IF NOT EXISTS` sobre un objeto que ya existe no se
deniega. El doble de la primera ronda denegaba cualquier `CREATE` y por eso su
test estaba verde mientras la CI real estaba roja.

Los casos contra Neo4j real estan en
`viewer/tests/test_corte5_credencial_solo_lectura_neo4j_real.py` (gateados por
`S9K_WRITER_NEO4J_REAL`). Aqui no se demuestra nada del servidor: se fija el
CONTRATO del codigo frente a un servidor modelado.
"""
from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from knowledge_v3 import driver_neo4j
from knowledge_v3.writer import (
    GraphWriter,
    InMemoryAppliedKeys,
    InMemoryAuditSink,
    codes,
    schema,
    schema_cli,
)

REPO = Path(__file__).resolve().parents[3]
README = REPO / "deploy" / "README.md"

FORBIDDEN = schema.NEO4J_FORBIDDEN_CODE
#: Texto crudo que el doble pone en la denegacion. NO debe llegar al operador.
TEXTO_DEL_SERVIDOR = "Permission denied for the doble: is not allowed"
#: Lo que nunca se le dice a la cuenta que fallo en `ensure` (B4).
CONSEJO_PROHIBIDO_EN_ENSURE = "conceda"


class _ErrorNeo4j(Exception):
    """Doble de `neo4j.exceptions.Neo4jError`: lo que cuenta es `code`, no el texto."""

    def __init__(self, code, mensaje=TEXTO_DEL_SERVIDOR):
        super().__init__(mensaje)
        self.code = code


class Forbidden(Exception):
    """Una clase que SE LLAMA `Forbidden` y no trae el codigo de Neo4j (O1)."""


class _Resultado:
    def consume(self):
        return None


_DDL = re.compile(r"^CREATE (CONSTRAINT|INDEX) (\S+) IF NOT EXISTS ")


class _Sesion:
    def __init__(self, drv):
        self.drv = drv

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, params=None):
        d = self.drv
        if d.fallo_ajeno is not None:
            raise d.fallo_ajeno
        if cypher.startswith("SHOW CONSTRAINTS"):
            if not d.puede_show_constraint:
                raise _ErrorNeo4j(FORBIDDEN)
            return [{"name": n} for n in sorted(d.constraints)]
        if cypher.startswith("SHOW INDEXES"):
            if not d.puede_show_index:
                raise _ErrorNeo4j(FORBIDDEN)
            return [{"name": n} for n in sorted(d.indexes)]
        m = _DDL.match(cypher)
        if m:
            tipo, nombre = m.groups()
            destino = d.constraints if tipo == "CONSTRAINT" else d.indexes
            # MEDIDO EN LA CI (ver docstring): sobre un objeto existente,
            # `IF NOT EXISTS` no se deniega aunque la cuenta no pueda crear.
            if nombre in destino:
                return _Resultado()
            permitido = (d.puede_crear_constraint if tipo == "CONSTRAINT"
                         else d.puede_crear_index)
            if not permitido:
                raise _ErrorNeo4j(FORBIDDEN)
            destino.add(nombre)
            d.creaciones.append(nombre)
            return _Resultado()
        raise AssertionError(f"consulta no modelada: {cypher}")


class _Driver:
    def __init__(self, constraints=None, indexes=None, show_constraint=True,
                 show_index=True, crear_constraint=False, crear_index=False,
                 fallo_ajeno=None):
        self.constraints = (set(schema.REQUIRED_CONSTRAINT_NAMES)
                            if constraints is None else set(constraints))
        self.indexes = (set(schema.REQUIRED_INDEX_NAMES)
                        if indexes is None else set(indexes))
        self.puede_show_constraint = show_constraint
        self.puede_show_index = show_index
        self.puede_crear_constraint = crear_constraint
        self.puede_crear_index = crear_index
        self.fallo_ajeno = fallo_ajeno
        self.creaciones: list[str] = []
        self.cerrado = False

    def session(self, **_kw):
        return _Sesion(self)

    def close(self):
        self.cerrado = True


def _lector(**kw):
    """La cuenta lectora: lee esquema, no crea."""
    return _Driver(**kw)


def _esquema(**kw):
    """La identidad de esquema: lee y crea."""
    return _Driver(crear_constraint=True, crear_index=True, **kw)


def _correr(drv, accion="verify", usuario="cuenta_lectora", extra=(), env=None):
    out, err = io.StringIO(), io.StringIO()
    argv = [accion, *(["--neo4j-user", usuario] if usuario else []), *extra]
    rc = schema_cli.run(argv, driver_factory=lambda: drv, stdout=out, stderr=err,
                        env=env)
    return rc, out.getvalue(), err.getvalue()


def _json_final(out: str) -> dict:
    lineas = [l for l in out.splitlines() if l.startswith("{")]
    assert lineas, "con --json no se imprimio ningun objeto JSON"
    return json.loads(lineas[-1])


# --- verify: positivo y negativos -------------------------------------------
def test_verify_con_privilegio_de_esquema_da_rc_0():
    rc, _, err = _correr(_lector())
    assert rc == schema_cli.RC_OK == 0, f"verify con esquema completo no dio 0: rc={rc} {err}"


def test_verify_con_una_restriccion_ausente_da_rc_incompleto():
    faltante = schema.REQUIRED_CONSTRAINT_NAMES[0]
    drv = _lector(constraints=set(schema.REQUIRED_CONSTRAINT_NAMES) - {faltante})
    rc, out, _ = _correr(drv)
    assert rc == schema_cli.RC_INCOMPLETO, f"restriccion ausente debia dar rc 3: rc={rc}"
    assert faltante in out, "el censo no nombra la restriccion que falta"


def test_verify_con_un_indice_ausente_da_rc_incompleto():
    rc, _, _ = _correr(_lector(indexes=set()))
    assert rc == schema_cli.RC_INCOMPLETO, f"indice ausente debia dar rc 3: rc={rc}"


def test_verify_caso_mixto_marca_solo_la_ausente():
    """O6: unas presentes y UNA ausente -> rc 3 y solo esa sale FALTA."""
    faltante = schema.REQUIRED_CONSTRAINT_NAMES[-1]
    drv = _lector(constraints=set(schema.REQUIRED_CONSTRAINT_NAMES) - {faltante})
    rc, out, _ = _correr(drv, extra=("--json",))
    assert rc == schema_cli.RC_INCOMPLETO, f"caso mixto debia dar rc 3: rc={rc}"
    censo = _json_final(out)
    assert censo["constraints_faltantes"] == [faltante], (
        f"caso mixto: faltantes mal medidos: {censo['constraints_faltantes']}"
    )
    assert censo["indices_faltantes"] == [], "caso mixto: inventa indices ausentes"
    marcadas = [l for l in out.splitlines() if "[FALTA]" in l]
    assert len(marcadas) == 1 and faltante in marcadas[0], (
        f"caso mixto: el texto no marca SOLO la ausente: {marcadas}"
    )


@pytest.mark.parametrize("show_constraint,show_index,operacion", [
    (False, True, schema.OP_SHOW_CONSTRAINTS),
    (True, False, schema.OP_SHOW_INDEXES),
])
def test_forbidden_es_codigo_de_autorizacion_no_incompleto(
    show_constraint, show_index, operacion
):
    drv = _lector(show_constraint=show_constraint, show_index=show_index)
    cuenta = "cuenta_x"
    rc, out, err = _correr(drv, usuario=cuenta)
    assert rc == schema_cli.RC_SIN_PRIVILEGIO, f"Forbidden no dio el rc de autorizacion: {rc}"
    marca = f"error_code={schema.SCHEMA_PRIVILEGE_MISSING}"
    assert marca in err, "el mensaje no lleva el codigo estable"
    assert operacion in err, "el mensaje no nombra la operacion que denego el servidor"
    privilegio = schema.PRIVILEGIO_HABITUAL[operacion]
    assert privilegio in err, "el mensaje no nombra el privilegio que habitualmente falta"
    assert cuenta in err, "el mensaje no nombra la cuenta"
    assert "FALTA" not in out, "no debe pintar un censo de faltantes que no se pudo medir"
    assert drv.cerrado, "el driver no se cerro"


def test_verify_aconseja_la_lectura_de_esquema_para_el_rol_lector():
    rc, _, err = _correr(_lector(show_constraint=False))
    assert rc == schema_cli.RC_SIN_PRIVILEGIO, f"verify sin SHOW CONSTRAINT: rc={rc}"
    assert schema.READER_ROLE_NAME in err, "verify no remite al rol lector documentado"
    habitual = "habitualmente"
    assert habitual in err, (
        "el mensaje afirma con certeza el privilegio que falta: Neo4j usa el "
        "mismo codigo para otras denegaciones (O1)"
    )


def test_el_mensaje_de_autorizacion_no_arrastra_el_texto_del_servidor():
    rc, out, err = _correr(_lector(show_constraint=False), extra=("--json",))
    assert rc == schema_cli.RC_SIN_PRIVILEGIO
    assert TEXTO_DEL_SERVIDOR not in err + out, (
        "FUGA: el texto crudo del servidor se cuela al operador"
    )


def test_el_json_de_error_lleva_operacion_privilegio_cuenta_y_completo_nulo():
    """O6: contenido EXACTO del JSON de error con --json."""
    rc, out, _ = _correr(_lector(show_index=False), usuario="cuenta_json",
                         extra=("--json",))
    assert rc == schema_cli.RC_SIN_PRIVILEGIO
    assert _json_final(out) == {
        "error_code": schema.SCHEMA_PRIVILEGE_MISSING,
        "operacion_denegada": schema.OP_SHOW_INDEXES,
        "privilegio_habitual": schema.PRIVILEGE_SHOW_INDEX,
        "accion": "verify",
        "cuenta": "cuenta_json",
        "completo": None,
    }, "el JSON de error no dice lo que se observo"


def test_la_cuenta_del_mensaje_sale_del_entorno_si_no_va_en_argv():
    """O6: `_cuenta` cuando el usuario sale del entorno."""
    cuenta = "cuenta_del_entorno"
    rc, _, err = _correr(_lector(show_constraint=False), usuario=None,
                         env={driver_neo4j.ENV_USER: cuenta})
    assert rc == schema_cli.RC_SIN_PRIVILEGIO
    assert cuenta in err, "el mensaje no nombra la cuenta tomada del entorno"


@pytest.mark.parametrize("fallo", [
    OSError("conexion rota"),
    _ErrorNeo4j("Neo.ClientError.Statement.SyntaxError"),
    Forbidden("se llama Forbidden pero no trae el codigo de Neo4j"),
], ids=["oserror", "otro-codigo-neo4j", "clase-llamada-Forbidden-sin-codigo"])
def test_lo_que_no_trae_el_codigo_forbidden_sigue_siendo_rc_error(fallo):
    """O1: solo el CODIGO de Neo4j es una denegacion; ni el nombre de clase ni el texto."""
    assert not schema.is_forbidden(fallo), f"is_forbidden acepta algo sin el codigo: {fallo!r}"
    rc, _, err = _correr(_lector(fallo_ajeno=fallo))
    assert rc == schema_cli.RC_ERROR, f"un fallo ajeno no debe ser de autorizacion: rc={rc}"
    assert schema.SCHEMA_PRIVILEGE_MISSING not in err


def test_is_forbidden_reconoce_el_codigo_de_neo4j():
    assert schema.is_forbidden(_ErrorNeo4j(FORBIDDEN)), "is_forbidden no reconoce el codigo"


def test_los_rc_son_distintos_y_estables():
    assert (schema_cli.RC_OK, schema_cli.RC_ERROR, schema_cli.RC_INCOMPLETO,
            schema_cli.RC_SIN_PRIVILEGIO) == (0, 2, 3, 5)


# --- ensure con la cuenta lectora: no puede crear lo que FALTA ---------------
def test_ensure_con_la_lectora_y_esquema_completo_sale_0_sin_crear_nada():
    """Lo OBSERVADO en la CI real (run 44825358259): rc 0, «creadas: 0»."""
    drv = _lector()
    rc, out, err = _correr(drv, accion="ensure")
    assert rc == schema_cli.RC_OK, f"esquema completo + lectora: rc={rc} {err}"
    assert drv.creaciones == [], "la lectora creo algo con el esquema completo"
    no_op = "(ya estaban: no-op)"
    assert no_op in out, "ensure no dice que no habia nada que crear"


def test_la_cuenta_lectora_no_puede_crear_una_restriccion_que_falta():
    faltante = schema.REQUIRED_CONSTRAINT_NAMES[1]
    drv = _lector(constraints=set(schema.REQUIRED_CONSTRAINT_NAMES) - {faltante})
    rc, out, err = _correr(drv, accion="ensure", extra=("--json",))
    assert rc == schema_cli.RC_SIN_PRIVILEGIO, f"ensure con lector debia denegarse: rc={rc}"
    assert faltante not in drv.constraints, "la cuenta lectora creo la restriccion"
    assert drv.creaciones == [], "la cuenta lectora creo algo"
    datos = _json_final(out)
    assert datos["operacion_denegada"] == schema.OP_CREATE_CONSTRAINT, (
        f"atribucion: la denegacion de una restriccion no sale como CREATE "
        f"CONSTRAINT: {datos['operacion_denegada']}"
    )


def test_la_cuenta_lectora_no_puede_crear_un_indice_que_falta():
    faltante = schema.REQUIRED_INDEX_NAMES[0]
    drv = _lector(indexes=set(schema.REQUIRED_INDEX_NAMES) - {faltante})
    rc, out, _ = _correr(drv, accion="ensure", extra=("--json",))
    assert rc == schema_cli.RC_SIN_PRIVILEGIO, f"ensure sin CREATE INDEX: rc={rc}"
    assert faltante not in drv.indexes, "la cuenta lectora creo el indice"
    datos = _json_final(out)
    assert datos["operacion_denegada"] == schema.OP_CREATE_INDEX, (
        f"atribucion: la denegacion de un indice no sale como CREATE INDEX: "
        f"{datos['operacion_denegada']}"
    )


def test_ensure_nunca_aconseja_dar_ddl_a_la_cuenta_que_fallo():
    """B4: remite a la identidad de esquema y a su comando, no a «concedalo»."""
    drv = _lector(constraints=set())
    rc, _, err = _correr(drv, accion="ensure")
    assert rc == schema_cli.RC_SIN_PRIVILEGIO
    assert CONSEJO_PROHIBIDO_EN_ENSURE not in err, (
        f"CONSEJO DDL A LA LECTORA: ensure aconseja conceder el privilegio a la "
        f"cuenta que fallo: {err}"
    )
    assert schema.SCHEMA_ROLE_NAME in err, "ensure no remite a la identidad de esquema"
    assert schema_cli.COMANDO_ENSURE in err, "ensure no da el comando canonico"


def test_ensure_con_create_pero_sin_show_recibe_el_consejo_de_ensure():
    """O2: la operacion que fallo es SHOW; el consejo NO es el del rol lector."""
    drv = _esquema(show_constraint=False)
    rc, _, err = _correr(drv, accion="ensure", usuario="cuenta_sin_show")
    assert rc == schema_cli.RC_SIN_PRIVILEGIO, f"ensure sin SHOW: rc={rc}"
    assert schema.OP_SHOW_CONSTRAINTS in err, "no nombra la operacion denegada"
    assert schema.READER_ROLE_NAME not in err, (
        "a una cuenta de ensure se le da el consejo del rol lector (O2)"
    )
    assert schema.SCHEMA_ROLE_NAME in err, "no remite a la identidad de esquema"
    assert CONSEJO_PROHIBIDO_EN_ENSURE not in err


def test_control_positivo_la_identidad_de_esquema_crea_lo_que_falta():
    drv = _esquema(constraints=set(), indexes=set())
    rc, _, err = _correr(drv, accion="ensure", usuario="identidad_esquema")
    assert rc == schema_cli.RC_OK, f"la identidad de esquema no completo el esquema: {rc} {err}"
    assert set(drv.creaciones) == (
        set(schema.REQUIRED_CONSTRAINT_NAMES) | set(schema.REQUIRED_INDEX_NAMES)
    ), "con permiso, ensure debia crear exactamente lo requerido (si no, el negativo no mide)"


# --- el envoltorio: el argumento explicito gana al entorno (B5) --------------
def test_el_argumento_explicito_gana_a_worker_env(monkeypatch):
    """`s9k-cli.sh` exporta worker.env (cuenta lectora); `--neo4j-user` y
    `--neo4j-password-file -` tienen que mandar sobre el."""
    capturado = {}

    def fabrica(config):
        capturado["config"] = config
        return lambda: _esquema()

    monkeypatch.setattr(schema_cli, "build_driver_factory", fabrica)
    env = {
        driver_neo4j.ENV_URI: "bolt://grafo.invalid:7687",
        driver_neo4j.ENV_USER: "s9k_worker_lector",
        driver_neo4j.ENV_PASSWORD_FILE: "fichero-del-lector",
    }
    out, err = io.StringIO(), io.StringIO()
    rc = schema_cli.run(
        ["ensure", "--neo4j-user", "s9k_esquema_operador", "--neo4j-password-file", "-"],
        env=env, stdout=out, stderr=err,
    )
    assert rc == schema_cli.RC_OK, f"ensure por el camino del envoltorio: rc={rc} {err.getvalue()}"
    config = capturado["config"]
    assert config.user == "s9k_esquema_operador", (
        f"ENTORNO GANA: el usuario de worker.env pisa el argumento: {config.user}"
    )
    assert config.password_file == driver_neo4j.STDIN_SENTINEL, (
        f"ENTORNO GANA: el fichero de worker.env pisa el argumento: {config.password_file}"
    )
    assert config.uri == env[driver_neo4j.ENV_URI], "la URI debia seguir saliendo del entorno"


def test_el_secreto_por_stdin_no_pasa_por_argv(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("secreto-de-esquema\n"))
    assert driver_neo4j.read_secret(driver_neo4j.STDIN_SENTINEL) == "secreto-de-esquema"


# --- el writer real ante la denegacion de SHOW CONSTRAINTS (O6) -------------
def test_el_writer_sin_show_constraint_no_escribe_y_lo_dice():
    drv = _Driver(show_constraint=False)
    writer = GraphWriter(
        workspace="ws-rc2-02", driver=drv, audit=InMemoryAuditSink(),
        applied_keys=InMemoryAppliedKeys(),
        clock=lambda: datetime(2026, 11, 21, tzinfo=timezone.utc),
    )
    rechazo = writer._schema_incompleto(drv)
    assert rechazo is not None, "el writer sigue adelante sin poder observar el esquema"
    assert rechazo.code == codes.EXEC_SCHEMA_CONSTRAINTS_MISSING
    assert rechazo.detail == {
        "error_code": schema.SCHEMA_PRIVILEGE_MISSING,
        "operacion_denegada": schema.OP_SHOW_CONSTRAINTS,
        "privilegio_habitual": schema.PRIVILEGE_SHOW_CONSTRAINT,
    }, f"el detalle del rechazo no dice la causa observada: {rechazo.detail}"
    assert TEXTO_DEL_SERVIDOR not in json.dumps(rechazo.detail) + rechazo.message, (
        "FUGA: el rechazo del writer arrastra el texto del servidor"
    )


# --- los roles: una sola autoridad, lista blanca exacta, y la doc no diverge -
#: LISTA BLANCA por rol (O5). Escrita aqui A MANO a proposito: es el segundo
#: testigo de la autoridad del codigo. Cambiar un rol exige cambiar las dos.
LISTA_BLANCA = {
    schema.READER_ROLE_NAME: {
        "GRANT ACCESS ON DATABASE {db} TO {role}",
        "GRANT MATCH {*} ON GRAPH {db} NODES * TO {role}",
        "GRANT MATCH {*} ON GRAPH {db} RELATIONSHIPS * TO {role}",
        "GRANT SHOW CONSTRAINT ON DATABASE {db} TO {role}",
        "GRANT SHOW INDEX ON DATABASE {db} TO {role}",
    },
    schema.SCHEMA_ROLE_NAME: {
        "GRANT ACCESS ON DATABASE {db} TO {role}",
        "GRANT SHOW CONSTRAINT ON DATABASE {db} TO {role}",
        "GRANT SHOW INDEX ON DATABASE {db} TO {role}",
        "GRANT CREATE CONSTRAINT ON DATABASE {db} TO {role}",
        "GRANT CREATE INDEX ON DATABASE {db} TO {role}",
    },
    schema.WRITER_ROLE_NAME: {
        "GRANT ACCESS ON DATABASE {db} TO {role}",
        "GRANT MATCH {*} ON GRAPH {db} NODES * TO {role}",
        "GRANT MATCH {*} ON GRAPH {db} RELATIONSHIPS * TO {role}",
        "GRANT WRITE ON GRAPH {db} TO {role}",
        "GRANT NAME MANAGEMENT ON DATABASE {db} TO {role}",
        "GRANT SHOW CONSTRAINT ON DATABASE {db} TO {role}",
    },
}


@pytest.mark.parametrize("rol", sorted(LISTA_BLANCA))
def test_cada_rol_concede_exactamente_su_lista_blanca(rol):
    codigo = schema.ROLE_PRIVILEGES[rol]
    assert len(codigo) == len(set(codigo)), f"el rol {rol} repite un privilegio"
    assert set(codigo) == LISTA_BLANCA[rol], (
        f"LISTA BLANCA ROTA: el rol {rol} del codigo no concede exactamente lo "
        f"permitido: sobra {sorted(set(codigo) - LISTA_BLANCA[rol])}, falta "
        f"{sorted(LISTA_BLANCA[rol] - set(codigo))}"
    )


def test_los_roles_del_codigo_son_exactamente_los_tres():
    assert set(schema.ROLE_PRIVILEGES) == set(LISTA_BLANCA), (
        f"hay un rol fuera de la lista blanca: {sorted(schema.ROLE_PRIVILEGES)}"
    )


INICIO_APARTADO = "### La cuenta del worker ES de sólo lectura"
FIN_APARTADO = "### Lo que el worker necesita"
_BLOQUE = re.compile(r"^```[^\n]*\n(.*?)^```", re.S | re.M)
_INLINE = re.compile(r"`([^`\n]+)`")
_TO_ROL = re.compile(r"\sTO\s+([A-Za-z0-9_]+)\s*$", re.I)
_VERBOS = ("GRANT", "DENY", "REVOKE")


def _normal(sentencia: str) -> str:
    return " ".join(sentencia.strip().rstrip(";").split()).upper()


def analizar_privilegios(texto: str) -> dict:
    """Censo de TODAS las sentencias de privilegio del apartado del README.

    Mira todos los bloques de codigo (cualquier lenguaje) y, en la prosa, el
    codigo en linea que sea una sentencia completa (`GRANT ... TO x`). Sin
    distinguir mayusculas. Devuelve privilegios por rol, roles otorgados a
    usuarios, roles creados y las sentencias que no se admiten (DENY, REVOKE,
    o cualquier otra linea en un bloque cypher).
    """
    try:
        i = texto.index(INICIO_APARTADO)
        j = texto.index(FIN_APARTADO, i)
    except ValueError as exc:
        raise AssertionError(f"no se encontro el apartado de roles en el README: {exc}")
    apartado = texto[i:j]
    sentencias: list[tuple[str, bool]] = []  # (sentencia, viene de bloque cypher)
    for m in _BLOQUE.finditer(apartado):
        es_cypher = apartado[m.start():].split("\n", 1)[0].strip().lower() == "```cypher"
        for linea in m.group(1).splitlines():
            if linea.strip():
                sentencias.append((linea, es_cypher))
    prosa = _BLOQUE.sub("", apartado)
    for m in _INLINE.finditer(prosa):
        frag = m.group(1)
        if frag.strip().upper().startswith(_VERBOS) and _TO_ROL.search(frag):
            sentencias.append((frag, False))

    censo = {"privilegios": {}, "roles_otorgados": [], "roles_creados": [],
             "no_admitidas": []}
    for crudo, es_cypher in sentencias:
        s = _normal(crudo)
        if s.startswith(("DENY", "REVOKE")):
            censo["no_admitidas"].append(s)
        elif s.startswith("GRANT ROLE"):
            partes = s.split()
            censo["roles_otorgados"].append(partes[2].lower() if len(partes) > 2 else "")
        elif s.startswith("GRANT"):
            m = _TO_ROL.search(s)
            rol = m.group(1).lower() if m else ""
            censo["privilegios"].setdefault(rol, []).append(s)
        elif s.startswith("CREATE ROLE"):
            censo["roles_creados"].append(s.split()[2].lower())
        elif s.startswith("CREATE USER"):
            continue
        elif es_cypher:
            censo["no_admitidas"].append(s)
    return censo


def _comparar_con_el_codigo(censo: dict) -> list[str]:
    problemas = []
    esperado = {
        rol: sorted(_normal(g) for g in schema.role_grants(rol, rol, "neo4j"))
        for rol in schema.ROLE_PRIVILEGES
    }
    doc = {rol: sorted(v) for rol, v in censo["privilegios"].items()}
    for rol in sorted(set(doc) | set(esperado)):
        if doc.get(rol) != esperado.get(rol):
            problemas.append(f"rol {rol}: README {doc.get(rol)} != codigo {esperado.get(rol)}")
    ajenos = sorted(set(censo["roles_otorgados"]) - set(esperado))
    if ajenos:
        problemas.append(f"se otorga un rol que no es de la autoridad: {ajenos}")
    if sorted(set(censo["roles_creados"])) != sorted(esperado):
        problemas.append(f"roles creados en el README: {censo['roles_creados']}")
    if censo["no_admitidas"]:
        problemas.append(f"sentencias no admitidas: {censo['no_admitidas']}")
    return problemas


def test_readme_y_codigo_definen_los_mismos_tres_roles():
    problemas = _comparar_con_el_codigo(analizar_privilegios(README.read_text(encoding="utf-8")))
    assert not problemas, (
        f"el apartado de roles de deploy/README.md diverge de la autoridad del codigo: {problemas}"
    )


def _readme_valido() -> str:
    """Un apartado minimo y CORRECTO, para que los gemelos de abajo midan."""
    bloques = []
    for rol in schema.ROLE_PRIVILEGES:
        lineas = [f"CREATE ROLE {rol};"]
        lineas += [g + ";" for g in schema.role_grants(rol, rol, "neo4j")]
        lineas += [f"GRANT ROLE {rol} TO usuario_{rol};"]
        bloques.append("```cypher\n" + "\n".join(lineas) + "\n```\n")
    return f"{INICIO_APARTADO}\n\n" + "\n".join(bloques) + f"\n{FIN_APARTADO}\n"


def test_el_comparador_acepta_el_apartado_correcto():
    assert _comparar_con_el_codigo(analizar_privilegios(_readme_valido())) == [], (
        "el comparador rechaza un apartado correcto: sus rojos no medirian nada"
    )


@pytest.mark.parametrize("inyeccion", [
    "grant write on graph neo4j to s9k_observador;",
    "GRANT ROLE editor TO s9k_worker_lector;",
    "GRANT INDEX ON DATABASE neo4j TO s9k_esquema;",
    "DENY MATCH {*} ON GRAPH neo4j NODES * TO s9k_escritor;",
], ids=["minusculas", "grant-role-ajeno", "index-sin-management", "deny"])
@pytest.mark.parametrize("donde", ["bloque-nuevo", "prosa"])
def test_el_comparador_ve_cualquier_privilegio_colado(inyeccion, donde):
    """O4: ni mayusculas, ni `GRANT ROLE`, ni el segundo bloque, ni la prosa."""
    base = _readme_valido()
    if donde == "bloque-nuevo":
        extra = f"\n```cypher\n{inyeccion}\n```\n"
    else:
        extra = f"\nTambien puede ejecutar `{inyeccion.rstrip(';')}` si hace falta.\n"
    texto = base.replace(f"\n{FIN_APARTADO}", extra + f"\n{FIN_APARTADO}")
    assert _comparar_con_el_codigo(analizar_privilegios(texto)), (
        f"COMPARADOR CIEGO: no ve {inyeccion!r} en {donde}"
    )
