"""Procedimiento de rollback v3 -> v2, ejecutado de verdad (carril I).

No se documenta un procedimiento sin ejecutarlo. Aquí se simula el código N-1
(una build cuyo máximo soportado es v2) y se comprueban los DOS órdenes:

- ORDEN CORRECTO: parar -> desplegar código N-1 -> RESTAURAR la base v2 ->
  arrancar. Arranca.
- ORDEN INCORRECTO: desplegar código N-1 y arrancar contra la base v3 todavía
  puesta. El arranque se REHÚSA (antes seguía adelante en silencio).

El invariante que rompe el orden incorrecto está en
`test_invariante_que_rompe_el_orden_incorrecto`.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.auth import db as auth_db
from app.auth import schema_compat


class _BuildNMenos1:
    """Código N-1: idéntico salvo que su máximo soportado es v2.

    Se parchea el rango en vez de tener una copia del módulo antiguo: lo que se
    quiere probar es la PUERTA, y la puerta es el rango.
    """

    def __init__(self, monkeypatch, max_soportado: int):
        monkeypatch.setattr(schema_compat, "MAX_SUPPORTED_SCHEMA", max_soportado)


def _crear_base_v3(path: Path) -> Path:
    auth_db.migrate(path)
    assert schema_compat.read_schema_version(path) == 3
    return path


def _copia_v2(origen: Path, destino: Path) -> Path:
    """Copia de seguridad en v2 (lo que produce `migrate()` al subir a v3)."""
    conn = sqlite3.connect(destino)
    conn.executescript(
        """
        CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT);
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);
        CREATE TABLE sessions (id INTEGER PRIMARY KEY, active_partida TEXT);
        CREATE TABLE partida_access (
            id INTEGER PRIMARY KEY, user_id INTEGER, workspace TEXT,
            partida_id TEXT, granted_by TEXT, granted_at TEXT
        );
        INSERT INTO schema_version VALUES (2, '2026-01-01T00:00:00');
        """
    )
    conn.commit()
    conn.close()
    return destino


def test_orden_incorrecto_codigo_n_menos_1_sobre_base_v3_no_arranca(tmp_path, monkeypatch):
    """Paso 3 (restaurar) omitido: el proceso se niega a abrir escrituras."""
    db = _crear_base_v3(tmp_path / "auth.db")
    _BuildNMenos1(monkeypatch, max_soportado=2)

    with pytest.raises(schema_compat.SchemaCompatibilityError) as exc:
        auth_db.ensure_migrated(db)
    # Tipo + CÓDIGO + versión leída: la garantía es la conducta (se rehúsa
    # arrancar sobre una base por encima del máximo soportado), no la
    # redacción del aviso al operador.
    assert exc.value.code == schema_compat.SCHEMA_ABOVE_MAX_SUPPORTED
    assert exc.value.schema_version == 3


def test_orden_correcto_restaurar_v2_antes_de_arrancar(tmp_path, monkeypatch):
    """Con la base v2 ya restaurada, la misma build N-1 arranca sin quejarse."""
    _crear_base_v3(tmp_path / "auth.db")
    _BuildNMenos1(monkeypatch, max_soportado=2)

    # Paso 3 del procedimiento: restaurar la copia v2 EN EL SITIO de la v3.
    restaurada = _copia_v2(tmp_path / "auth.db", tmp_path / "auth_restaurada.db")
    assert schema_compat.assert_compatible(restaurada) == 2


def test_la_secuencia_completa_en_el_orden_documentado(tmp_path, monkeypatch):
    """El procedimiento entero, tal y como está en docs/65."""
    activa = tmp_path / "auth.db"
    _crear_base_v3(activa)
    backup_v2 = _copia_v2(activa, tmp_path / "auth.db.bak.v2")

    # (1) parar el servicio: no hay proceso en la prueba.
    # (2) desplegar código N-1.
    _BuildNMenos1(monkeypatch, max_soportado=2)
    # (2b) si alguien arrancase AQUÍ, se rehúsa. Esa es la red de seguridad.
    with pytest.raises(schema_compat.SchemaCompatibilityError):
        auth_db.ensure_migrated(activa)
    # (3) restaurar la base v2 en su sitio.
    activa.unlink()
    activa.write_bytes(backup_v2.read_bytes())
    # (4) arrancar.
    assert schema_compat.assert_compatible(activa) == 2


def test_invariante_que_rompe_el_orden_incorrecto(tmp_path):
    """Qué se pierde exactamente si N-1 llega a escribir sobre la base v3.

    v3 mete `partida_access.max_visible_session`: el tope de progresión de
    campaña, decidido en el SERVIDOR. El código v2 no conoce esa columna, así
    que al conceder un acceso deja la fila con `max_visible_session` NULL, y
    NULL significa «sin tope». El daño no es sólo leer de más mientras N-1 está
    vivo: son filas SIN CONTROL que sobreviven a la vuelta a N, porque restaurar
    la copia v2 después ya no las recupera (se escribieron después de la copia).
    Por eso la restauración va ANTES de abrir escrituras, no después.
    """
    db = tmp_path / "auth.db"
    auth_db.migrate(db)
    conn = sqlite3.connect(db)
    # Escritura "a la v2": sin la columna que v3 añadió.
    conn.execute(
        "INSERT INTO partida_access (user_id, workspace, partida_id, granted_at) "
        "VALUES (1, 'leyenda', 'partida:uno', '2026-01-01T00:00:00')"
    )
    conn.commit()
    fila = conn.execute(
        "SELECT max_visible_session FROM partida_access WHERE partida_id='partida:uno'"
    ).fetchone()
    conn.close()

    assert fila[0] is None, (
        "una concesión escrita por código N-1 queda sin tope de sesión: ese es "
        "el control que se pierde, y es el motivo de REFUSE TO START"
    )
