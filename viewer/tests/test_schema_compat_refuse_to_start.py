"""Rango de esquema soportado y negativa a arrancar (carril I, release readiness).

Decisión del operador que se prueba aquí:

    «auth_db.v3: N-1 no puede arrancar sobre schema v3 si pierde controles.
     Rango de schema soportado + REFUSE TO START; rollback antes de abrir
     escrituras = código N-1 + restaurar v2.»

Cada prueba de este fichero está escrita para poder ponerse ROJA: la violación
que detecta se puede introducir en una línea (ver la tabla de calibración en
`docs/65-preparacion-de-release.md`). Un test que no puede fallar no prueba
nada.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.auth import db as auth_db
from app.auth import schema_compat


# ---------------------------------------------------------------------------
# Utilidades: bases sintéticas en estados concretos
# ---------------------------------------------------------------------------

def _stamp(path: Path, version, *, with_tables: bool = True,
           with_version_table: bool = True) -> Path:
    conn = sqlite3.connect(path)
    if with_tables:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
        conn.execute("INSERT INTO users (username) VALUES ('ana')")
        conn.execute(
            "CREATE TABLE partida_access (id INTEGER PRIMARY KEY, workspace TEXT)"
        )
    if with_version_table:
        conn.execute(
            "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT)"
        )
        if version is not None:
            conn.execute(
                "INSERT INTO schema_version VALUES (?, '2026-01-01T00:00:00')",
                (version,),
            )
    conn.commit()
    conn.close()
    return path


# ---------------------------------------------------------------------------
# 1. El rango está declarado y es coherente con la versión que escribe el código
# ---------------------------------------------------------------------------

def test_el_rango_declarado_contiene_la_version_que_escribe_el_codigo():
    assert schema_compat.MIN_SUPPORTED_SCHEMA <= auth_db.SCHEMA_VERSION
    assert schema_compat.MAX_SUPPORTED_SCHEMA == auth_db.SCHEMA_VERSION, (
        "El máximo soportado debe SER la versión que el código escribe, no una "
        "copia que pueda quedarse atrás."
    )


# ---------------------------------------------------------------------------
# 2. Fuera de rango por ARRIBA (el caso N-1 sobre datos N) -> REHÚSA ARRANCAR
# ---------------------------------------------------------------------------

def test_schema_mas_nuevo_que_el_codigo_rehusa_arrancar(tmp_path):
    """Código N-1 encontrándose una base v(N): no arranca, no degrada."""
    db = _stamp(tmp_path / "auth.db", schema_compat.MAX_SUPPORTED_SCHEMA + 1)

    with pytest.raises(schema_compat.SchemaCompatibilityError) as exc:
        schema_compat.assert_compatible(db)

    msg = str(exc.value)
    assert "SE REHÚSA ARRANCAR" in msg
    assert "N-1" in msg, "el error debe decir QUÉ situación es, no sólo que falla"
    assert "RESTAURAR" in msg, "el error debe decir cómo salir de ahí"


def test_ensure_migrated_es_el_punto_de_estrangulamiento(tmp_path):
    """Todo entrypoint pasa por ensure_migrated: la puerta vive ahí."""
    db = _stamp(tmp_path / "auth.db", schema_compat.MAX_SUPPORTED_SCHEMA + 1)
    with pytest.raises(schema_compat.SchemaCompatibilityError):
        auth_db.ensure_migrated(db)


def test_migrate_directo_tampoco_traga_una_base_mas_nueva(tmp_path):
    """`migrate()` devolvía None en silencio ante una base más nueva."""
    db = _stamp(tmp_path / "auth.db", schema_compat.MAX_SUPPORTED_SCHEMA + 5)
    with pytest.raises(schema_compat.SchemaCompatibilityError):
        auth_db.migrate(db)


def test_la_base_no_se_toca_cuando_se_rehusa(tmp_path):
    """Rehusar es rehusar: ni migración parcial ni escritura de versión."""
    db = _stamp(tmp_path / "auth.db", 99)
    antes = db.read_bytes()
    with pytest.raises(schema_compat.SchemaCompatibilityError):
        auth_db.ensure_migrated(db)
    assert db.read_bytes() == antes


# ---------------------------------------------------------------------------
# 3. Versión AUSENTE -> REHÚSA (la ausencia nunca es permiso)
# ---------------------------------------------------------------------------

def test_base_poblada_sin_tabla_de_version_rehusa(tmp_path):
    """El caso que antes se leía como «versión 0» y disparaba una migración."""
    db = _stamp(tmp_path / "auth.db", None, with_version_table=False)
    with pytest.raises(schema_compat.SchemaVersionUnknown) as exc:
        schema_compat.assert_compatible(db)
    assert "no es permiso" in str(exc.value)


def test_tabla_de_version_vacia_rehusa(tmp_path):
    """`MAX(version)` sobre tabla vacía es NULL; `NULL or 0` daba 0."""
    db = _stamp(tmp_path / "auth.db", None)
    with pytest.raises(schema_compat.SchemaVersionUnknown):
        schema_compat.assert_compatible(db)


def test_fichero_que_no_es_sqlite_rehusa(tmp_path):
    db = tmp_path / "auth.db"
    db.write_bytes(b"esto no es una base de datos" * 10)
    with pytest.raises(schema_compat.SchemaVersionUnknown):
        schema_compat.assert_compatible(db)


def test_version_no_numerica_rehusa(tmp_path):
    db = tmp_path / "auth.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE schema_version (version, applied_at TEXT)")
    conn.execute("INSERT INTO schema_version VALUES ('tres', 'x')")
    conn.commit()
    conn.close()
    with pytest.raises(schema_compat.SchemaVersionUnknown):
        schema_compat.assert_compatible(db)


def test_ninguna_ausencia_devuelve_una_version_util():
    """Ninguna rama de fallo puede devolver un entero: o versión, o error."""
    import inspect

    fuente = inspect.getsource(schema_compat.read_schema_version)
    assert "return 0" not in fuente, (
        "devolver 0 ante un fallo es convertir «no sé» en «versión buena»"
    )


# ---------------------------------------------------------------------------
# 4. DENTRO de rango -> arranca (control positivo: la puerta no está soldada)
# ---------------------------------------------------------------------------

def test_base_inexistente_es_instalacion_nueva_y_se_permite(tmp_path):
    """Único caso de ausencia tolerado: no hay datos que malinterpretar."""
    db = tmp_path / "auth.db"
    assert schema_compat.assert_compatible(db) is None
    auth_db.ensure_migrated(db)  # crea y migra
    assert schema_compat.read_schema_version(db) == auth_db.SCHEMA_VERSION


def test_base_en_la_version_actual_arranca(tmp_path):
    db = tmp_path / "auth.db"
    auth_db.ensure_migrated(db)
    assert schema_compat.assert_compatible(db) == auth_db.SCHEMA_VERSION
    auth_db.ensure_migrated(db)  # idempotente


def test_base_antigua_dentro_de_rango_migra_hacia_delante(tmp_path):
    db = tmp_path / "auth.db"
    auth_db.migrate(db)  # crea en v3
    # Rebobina el sello a v1: dentro del rango, hay ruta hacia delante.
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version VALUES (1, '2026-01-01T00:00:00')")
    conn.commit()
    conn.close()
    assert schema_compat.assert_compatible(db) == 1
    auth_db.ensure_migrated(db)
    assert schema_compat.read_schema_version(db) == auth_db.SCHEMA_VERSION


def test_fuera_de_rango_por_abajo_rehusa(tmp_path):
    db = _stamp(tmp_path / "auth.db", schema_compat.MIN_SUPPORTED_SCHEMA - 1)
    with pytest.raises(schema_compat.SchemaCompatibilityError):
        schema_compat.assert_compatible(db)


# ---------------------------------------------------------------------------
# 5. El control que se perdería: v3 añade `max_visible_session`
# ---------------------------------------------------------------------------

def test_v3_aporta_el_control_que_n_menos_1_no_conoce(tmp_path):
    """Documenta POR QUÉ el límite superior muerde, con la columna real.

    Si esta columna dejase de ser exclusiva de v3, el argumento del rango
    cambiaría y habría que revisarlo: por eso se comprueba.
    """
    db = tmp_path / "auth.db"
    auth_db.migrate(db)
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(partida_access)")}
    conn.close()
    assert "max_visible_session" in cols
    assert "character_id" in cols
    assert any("max_visible_session" in stmt for stmt in auth_db._DDL_V3_ALTER)


# ---------------------------------------------------------------------------
# 6. HASTA DONDE LLEGA LA PUERTA (observacion O-1 de la revision)
#
# La primera redaccion de este carril afirmaba que la puerta vivia en
# `ensure_migrated()` "asi que no se rodea olvidando llamarla en un entrypoint
# nuevo". Es falso: `ensure_migrated` es punto de paso del ARRANQUE, no del
# ACCESO A DATOS. `get_conn()` no la llama y tiene ~20 llamadores directos.
#
# Se decidio NO llevar la puerta a `get_conn()`, por coste medido:
# `assert_compatible()` abre su propia conexion de solo lectura y encarece cada
# `get_conn` un 113 % (390 us -> 832 us por llamada, 2000 iteraciones).
# Cachearlo devolveria el problema a su sitio peor: una cache obsoleta serviria
# una base cambiada bajo los pies, en la comprobacion que debe ser fail-closed.
#
# Como la garantia se estrecha, el limite se FIJA POR PRUEBA en vez de quedar
# en un comentario. Si alguien cierra el hueco algun dia, esta prueba se pone
# roja y le obliga a actualizar la afirmacion en los tres sitios donde vive.
# ---------------------------------------------------------------------------

def test_la_puerta_cubre_el_arranque_no_cada_acceso(tmp_path):
    """Caracteriza el limite REAL, no el que nos gustaria tener.

    Documenta el hueco P-5: sobre una base v4, `ensure_migrated` rehusa pero
    `get_conn` entrega datos. Hoy no es alcanzable en el servicio porque el
    arranque aborta antes de atender ninguna peticion; queda anotado como
    superviviente en docs/65 seccion 8.
    """
    db = tmp_path / "auth.db"
    auth_db.migrate(db)
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version VALUES (4, '2026-01-01T00:00:00')")
    conn.commit()
    conn.close()

    # El arranque SI esta cubierto.
    with pytest.raises(schema_compat.SchemaCompatibilityError):
        auth_db.ensure_migrated(db)

    # El acceso a datos NO. Si esto empieza a levantar la excepcion, el hueco
    # se ha cerrado: actualiza `get_conn.__doc__`, el docstring de
    # `schema_compat` y docs/65 seccion 1, y convierte esta prueba en la
    # contraria.
    with auth_db.get_conn(db) as conexion:
        assert conexion.execute("SELECT 1").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# AQUI HUBO UNA PRUEBA QUE COMPROBABA LA VERACIDAD DE LOS DOCSTRINGS.
# Se ha BORRADO. Conviene saber por que, para que nadie la reponga.
#
# `test_la_afirmacion_escrita_no_promete_mas_de_lo_que_cubre` exigia que en los
# docstrings de `get_conn` y `ensure_migrated` apareciesen tres cadenas
# verdaderas. La revision independiente la rompio en las DOS direcciones:
#
#   N-4 (falso negativo, el que importa): basta con AÑADIR la promesa falsa
#        --"la garantia es que NINGUN acceso ocurre nunca fuera de rango: la
#        puerta no se puede rodear..."-- dejando intactas las tres cadenas
#        exigidas. Reproducido aqui: 17 passed, VERDE, con la mentira dentro.
#   N-5 (falso positivo): reescribir la frase honesta con sinonimos
#        ("NO se comprueba" -> "no se verifica"), sin cambio semantico, la
#        ponia ROJA.
#   N-6: bajo `python -OO` los docstrings son None y fallaba por un motivo
#        ajeno a la seguridad.
#
# Tampoco se ha "invertido" para PROHIBIR las frases falsas en vez de exigir
# las verdaderas, porque no funciona: la frase honesta de `ensure_migrated`
# contiene literalmente «ningún acceso ocurre fuera de rango» --negada: «...no
# «ningún acceso ocurre fuera de rango»»-- y la mentira de N-4 contiene esa
# MISMA cadena en afirmativo. Separarlas exige entender la negacion, no buscar
# subcadenas; y una lista de prohibidas falla EN ABIERTO ante el primer
# parafraseo. Es decir: confianza sin cobertura, justo lo que no se acepta.
#
# La veracidad de la prosa no es un invariante comprobable comparando cadenas.
# Lo que SI congela el resultado de seguridad es la prueba de COMPORTAMIENTO de
# arriba, `test_la_puerta_cubre_el_arranque_no_cada_acceso`: si alguien cierra
# el hueco, se pone roja y obliga a revisar lo que esta escrito.
# ---------------------------------------------------------------------------
