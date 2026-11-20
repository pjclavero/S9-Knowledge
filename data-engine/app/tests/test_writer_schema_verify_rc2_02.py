# -*- coding: utf-8 -*-
"""RC2-02: `writer-schema verify` con la cuenta de SOLO LECTURA.

Hallazgo (docs/94 §6.2): con el rol lector documentado, `verify` salia con rc 2
y `Forbidden`. Decision D4: separar privilegios; el rol lector gana SOLO lectura
de esquema (`SHOW CONSTRAINT`, `SHOW INDEX`), nunca escritura.

Arnes sin Neo4j: un doble de driver que MODELA los privilegios de la cuenta
(lee esquema / no lo lee / no crea). El caso contra Neo4j real esta en
`viewer/tests/test_corte5_credencial_solo_lectura_neo4j_real.py` (gateado por
`S9K_WRITER_NEO4J_REAL`).
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

from knowledge_v3.writer import schema, schema_cli

REPO = Path(__file__).resolve().parents[3]
README = REPO / "deploy" / "README.md"


class _Forbidden(Exception):
    """Doble de `neo4j.exceptions.Forbidden`: lo reconoce el codigo, no el texto."""

    code = "Neo.ClientError.Security.Forbidden"


class _Resultado:
    def consume(self):
        return None


class _Sesion:
    def __init__(self, drv):
        self.drv = drv

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, params=None):
        d = self.drv
        if "SHOW CONSTRAINTS" in cypher:
            if not d.puede_show_constraint:
                raise _Forbidden("Show constraints is not allowed")
            return [{"name": n} for n in sorted(d.constraints)]
        if "SHOW INDEXES" in cypher:
            if not d.puede_show_index:
                raise _Forbidden("Show indexes is not allowed")
            return [{"name": n} for n in sorted(d.indexes)]
        if cypher.startswith("CREATE"):
            if not d.puede_crear:
                raise _Forbidden("Create constraint is not allowed")
            d.creaciones.append(cypher)
            return _Resultado()
        raise AssertionError(f"consulta no modelada: {cypher}")


class _Driver:
    def __init__(self, constraints=None, indexes=None, show_constraint=True,
                 show_index=True, crear=False):
        self.constraints = (set(schema.REQUIRED_CONSTRAINT_NAMES)
                            if constraints is None else set(constraints))
        self.indexes = (set(schema.REQUIRED_INDEX_NAMES)
                        if indexes is None else set(indexes))
        self.puede_show_constraint = show_constraint
        self.puede_show_index = show_index
        self.puede_crear = crear
        self.creaciones: list[str] = []
        self.cerrado = False

    def session(self):
        return _Sesion(self)

    def close(self):
        self.cerrado = True


def _correr(drv, accion="verify", usuario="cuenta_lectora", extra=()):
    out, err = io.StringIO(), io.StringIO()
    rc = schema_cli.run(
        [accion, "--neo4j-user", usuario, *extra],
        driver_factory=lambda: drv, stdout=out, stderr=err,
    )
    return rc, out.getvalue(), err.getvalue()


# --- verify: positivo y negativos -------------------------------------------
def test_verify_con_privilegio_de_esquema_da_rc_0():
    rc, _, err = _correr(_Driver())
    assert rc == schema_cli.RC_OK == 0, f"verify con esquema completo no dio 0: rc={rc} {err}"


def test_verify_con_una_restriccion_ausente_da_rc_incompleto():
    faltante = schema.REQUIRED_CONSTRAINT_NAMES[0]
    drv = _Driver(constraints=set(schema.REQUIRED_CONSTRAINT_NAMES) - {faltante})
    rc, out, _ = _correr(drv)
    assert rc == schema_cli.RC_INCOMPLETO, f"restriccion ausente debia dar rc 3: rc={rc}"
    assert faltante in out, "el censo no nombra la restriccion que falta"


def test_verify_con_un_indice_ausente_da_rc_incompleto():
    drv = _Driver(indexes=set())
    rc, _, _ = _correr(drv)
    assert rc == schema_cli.RC_INCOMPLETO, f"indice ausente debia dar rc 3: rc={rc}"


@pytest.mark.parametrize("show_constraint,show_index,privilegio", [
    (False, True, schema.PRIVILEGE_SHOW_CONSTRAINT),
    (True, False, schema.PRIVILEGE_SHOW_INDEX),
])
def test_forbidden_es_codigo_de_autorizacion_no_incompleto(
    show_constraint, show_index, privilegio
):
    drv = _Driver(show_constraint=show_constraint, show_index=show_index)
    cuenta = "cuenta_x"
    rc, out, err = _correr(drv, usuario=cuenta)
    assert rc == schema_cli.RC_SIN_PRIVILEGIO, f"Forbidden no dio el rc de autorizacion: {rc}"
    assert rc not in (schema_cli.RC_INCOMPLETO, schema_cli.RC_ERROR, schema_cli.RC_OK)
    assert f"error_code={schema.SCHEMA_PRIVILEGE_MISSING}" in err
    assert privilegio in err, "el mensaje no nombra el privilegio que falta"
    assert cuenta in err, "el mensaje no nombra la cuenta"
    assert "FALTA" not in out, "no debe pintar un censo de faltantes que no se pudo medir"
    assert drv.cerrado, "el driver no se cerro"


def test_el_mensaje_de_autorizacion_no_arrastra_el_texto_del_servidor():
    rc, out, err = _correr(_Driver(show_constraint=False), extra=("--json",))
    assert rc == schema_cli.RC_SIN_PRIVILEGIO
    assert "is not allowed" not in err + out, "el texto crudo del servidor se cuela al operador"


def test_un_error_que_no_es_forbidden_sigue_siendo_rc_error():
    class _Roto(_Driver):
        def session(self):
            raise OSError("conexion rota")

    rc, _, err = _correr(_Roto())
    assert rc == schema_cli.RC_ERROR, f"un fallo ajeno no debe ser de autorizacion: rc={rc}"
    assert schema.SCHEMA_PRIVILEGE_MISSING not in err


def test_los_rc_son_distintos_y_estables():
    assert (schema_cli.RC_OK, schema_cli.RC_ERROR, schema_cli.RC_INCOMPLETO,
            schema_cli.RC_SIN_PRIVILEGIO) == (0, 2, 3, 5)


# --- ensure con cuenta lectora: NO crea -------------------------------------
def test_la_cuenta_lectora_no_puede_ensure_y_no_crea_nada():
    drv = _Driver(constraints=set(), indexes=set(), crear=False)
    rc, _, err = _correr(drv, accion="ensure")
    assert rc == schema_cli.RC_SIN_PRIVILEGIO, f"ensure con lector debia denegarse: rc={rc}"
    assert schema.PRIVILEGE_CREATE_SCHEMA in err
    assert drv.creaciones == [], "la cuenta lectora creo algo"
    assert drv.constraints == set()


def test_control_positivo_la_cuenta_con_permiso_si_ejecuta_el_ddl():
    drv = _Driver(crear=True)
    rc, _, _ = _correr(drv, accion="ensure", usuario="cuenta_escritora")
    assert rc == schema_cli.RC_OK
    assert drv.creaciones, "con permiso, ensure debia emitir el DDL (si no, el negativo no mide)"


# --- el rol: una sola autoridad, y la doc no diverge -------------------------
def _bloque_rol_del_readme() -> list[str]:
    texto = README.read_text(encoding="utf-8")
    i = texto.index("Cómo se crea el rol")
    m = re.search(r"```cypher\n(.*?)```", texto[i:], re.S)
    assert m, "no se encontro el bloque cypher del rol en deploy/README.md"
    return [l.strip().rstrip(";") for l in m.group(1).splitlines() if l.strip()]


def _grants_de_privilegio(lineas: list[str]) -> list[str]:
    return [l for l in lineas if l.startswith("GRANT") and " ROLE " not in l]


def test_readme_y_codigo_definen_el_mismo_rol_lector():
    doc = _grants_de_privilegio(_bloque_rol_del_readme())
    esperado = schema.reader_role_grants(schema.READER_ROLE_NAME, "neo4j")
    assert doc == esperado, (
        f"el rol de deploy/README.md diverge del que espera el codigo: {doc} != {esperado}"
    )


def test_el_rol_incluye_lectura_de_esquema():
    grants = schema.reader_role_grants()
    assert any("SHOW CONSTRAINT" in g for g in grants), "al rol le falta SHOW CONSTRAINT"
    assert any("SHOW INDEX" in g for g in grants), "al rol le falta SHOW INDEX"


PROHIBIDOS = ("WRITE", "CREATE", "SET ", "DELETE", "MERGE", "DROP", "ALL ", "MANAGEMENT",
              "REMOVE")


def test_el_rol_lector_no_concede_escritura_ni_administracion():
    todos = schema.reader_role_grants() + _grants_de_privilegio(_bloque_rol_del_readme())
    assert todos, "no hay grants que comprobar"
    for g in todos:
        for p in PROHIBIDOS:
            assert p not in g.upper(), (
                f"el rol lector concede una capacidad de escritura/administracion ({p!r}): {g}"
            )
