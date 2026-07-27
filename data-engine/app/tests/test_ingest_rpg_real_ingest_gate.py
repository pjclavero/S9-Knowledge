"""Tests para la llave S9K_ALLOW_REAL_INGEST en el camino A legacy (ingest_rpg.py).

Contexto (docs/v3/00-audit-current-system.md, W1-W3): `ingest_rpg.py` es el
único punto que escribe de verdad en Neo4j sin más guard que --dry-run /
--no-neo4j, y es alcanzable automáticamente desde
`youtube/fetch_youtube.py:run_rpg_extraction()` vía subprocess. La llave
`S9K_ALLOW_REAL_INGEST` corta justo antes de `Neo4jWriter.__init__` construya
el driver de neo4j, para que ningún camino (CLI directo o subproceso) pueda
escribir sin autorización explícita.

Checklist cubierto:
 1. Sin la llave -> Neo4jWriter aborta con exit code != 0 y NO instancia el
    driver de neo4j (mockeado).
 2. Con la llave ("1" o "true") -> la construcción del writer procede
    (mockeada) sin abortar por el gate.
 3. --dry-run / --no-neo4j sin la llave -> main() ni siquiera intenta conectar
    (no llega al gate), vía _should_connect_neo4j().
 4. Mutación: un test que falla si alguien quita la comprobación de la llave
    dentro de Neo4jWriter.__init__.
"""
from __future__ import annotations

import inspect
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Igual que test_ingest_semantics.py: `app/` debe estar en sys.path para que
# ingest_rpg.py y sus imports relativos (`schemas.*`) resuelvan igual que en
# ejecución real / CI.
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

# `ingest_rpg.py` importa `fcntl` a nivel de módulo (solo usado en funciones
# de locking que no ejercitamos aquí). Se stubea en plataformas sin fcntl.
if sys.platform == "win32" and "fcntl" not in sys.modules:
    _fcntl_stub = types.ModuleType("fcntl")
    _fcntl_stub.flock = lambda *a, **k: None
    _fcntl_stub.LOCK_EX = 2
    _fcntl_stub.LOCK_UN = 8
    _fcntl_stub.LOCK_NB = 4
    sys.modules["fcntl"] = _fcntl_stub

import ingest_rpg  # noqa: E402
from ingest_rpg import (  # noqa: E402
    ENV_ALLOW_REAL_INGEST,
    EXIT_INGEST_GATE_BLOCKED,
    Neo4jWriter,
    _real_ingest_allowed,
    _should_connect_neo4j,
)


_FAKE_CONFIG = {
    "neo4j": {
        "uri": "bolt://127.0.0.1:7687",
        "username": "neo4j",
        "password_file": "/does/not/matter/because/gate/aborts/first",
    }
}


def _clean_env():
    """Devuelve un contexto sin S9K_ALLOW_REAL_INGEST definido."""
    return patch.dict(os.environ, {}, clear=False)


@pytest.fixture(autouse=True)
def _no_real_ingest_key_leak():
    """Aísla cada test: la llave nunca debe quedar puesta entre tests."""
    backup = os.environ.pop(ENV_ALLOW_REAL_INGEST, None)
    yield
    if backup is None:
        os.environ.pop(ENV_ALLOW_REAL_INGEST, None)
    else:
        os.environ[ENV_ALLOW_REAL_INGEST] = backup


def _make_fake_neo4j_module():
    """Módulo `neo4j` falso para detectar si se instancia el driver."""
    fake_driver = MagicMock()
    fake_driver.verify_connectivity.return_value = None

    fake_graph_database = MagicMock()
    fake_graph_database.driver.return_value = fake_driver

    fake_module = types.ModuleType("neo4j")
    fake_module.GraphDatabase = fake_graph_database
    return fake_module, fake_graph_database


# ── 1. Sin llave -> aborto duro antes de cualquier conexión ───────────────────

def test_neo4jwriter_blocks_without_key_and_never_touches_driver():
    os.environ.pop(ENV_ALLOW_REAL_INGEST, None)

    fake_module, fake_graph_database = _make_fake_neo4j_module()
    with patch.dict(sys.modules, {"neo4j": fake_module}):
        with pytest.raises(SystemExit) as exc_info:
            Neo4jWriter(_FAKE_CONFIG)

    assert exc_info.value.code == EXIT_INGEST_GATE_BLOCKED
    assert exc_info.value.code != 0
    fake_graph_database.driver.assert_not_called()


def test_neo4jwriter_blocks_with_falsy_key_values():
    """Valores distintos de "1"/"true" (p.ej. "false", "0", vacío) abortan."""
    fake_module, fake_graph_database = _make_fake_neo4j_module()
    for bad_value in ("false", "0", "", "no", "yes"):
        os.environ[ENV_ALLOW_REAL_INGEST] = bad_value
        with patch.dict(sys.modules, {"neo4j": fake_module}):
            with pytest.raises(SystemExit) as exc_info:
                Neo4jWriter(_FAKE_CONFIG)
        assert exc_info.value.code == EXIT_INGEST_GATE_BLOCKED, bad_value
        fake_graph_database.driver.assert_not_called()


def test_gate_message_mentions_review_path_and_env_var(caplog):
    """El mensaje debe explicar la llave y señalar la ruta soportada (camino B)."""
    os.environ.pop(ENV_ALLOW_REAL_INGEST, None)
    fake_module, _ = _make_fake_neo4j_module()
    with patch.dict(sys.modules, {"neo4j": fake_module}):
        with caplog.at_level("ERROR"):
            with pytest.raises(SystemExit):
                Neo4jWriter(_FAKE_CONFIG)

    combined = " ".join(r.message for r in caplog.records)
    assert ENV_ALLOW_REAL_INGEST in combined
    assert "ingest-approved" in combined or "data_review" in combined


# ── 2. Con la llave -> procede (mockeado) ─────────────────────────────────────

@pytest.mark.parametrize("value", ["1", "true", "TRUE", "True"])
def test_neo4jwriter_proceeds_with_key(value):
    os.environ[ENV_ALLOW_REAL_INGEST] = value

    fake_module, fake_graph_database = _make_fake_neo4j_module()
    with patch.dict(sys.modules, {"neo4j": fake_module}), \
         patch("ingest_rpg.read_password", return_value="fake-password"):
        writer = Neo4jWriter(_FAKE_CONFIG)

    fake_graph_database.driver.assert_called_once()
    assert writer.driver is fake_graph_database.driver.return_value


def test_real_ingest_allowed_helper():
    os.environ.pop(ENV_ALLOW_REAL_INGEST, None)
    assert _real_ingest_allowed() is False

    os.environ[ENV_ALLOW_REAL_INGEST] = "1"
    assert _real_ingest_allowed() is True

    os.environ[ENV_ALLOW_REAL_INGEST] = "true"
    assert _real_ingest_allowed() is True

    os.environ[ENV_ALLOW_REAL_INGEST] = "false"
    assert _real_ingest_allowed() is False


# ── 3. --dry-run / --no-neo4j sin llave -> no intentan conectar ──────────────

def _fake_args(**overrides):
    ns = types.SimpleNamespace(no_neo4j=False, dry_run=False)
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def test_dry_run_does_not_attempt_neo4j_connection_without_key():
    os.environ.pop(ENV_ALLOW_REAL_INGEST, None)
    args = _fake_args(dry_run=True)
    assert _should_connect_neo4j(args) is False


def test_no_neo4j_flag_does_not_attempt_connection_without_key():
    os.environ.pop(ENV_ALLOW_REAL_INGEST, None)
    args = _fake_args(no_neo4j=True)
    assert _should_connect_neo4j(args) is False


def test_normal_mode_without_flags_does_attempt_connection():
    """Sin --dry-run ni --no-neo4j, main() SÍ intenta conectar (y entonces
    el gate de Neo4jWriter decide si lo permite). Esto no cambia con la llave:
    la llave se evalúa dentro de Neo4jWriter, no en esta condición."""
    args = _fake_args()
    assert _should_connect_neo4j(args) is True


# ── 4. Mutación: falla si alguien quita la comprobación de la llave ──────────

def test_mutation_guard_neo4jwriter_init_calls_gate_check():
    """Si se elimina la llamada a _real_ingest_allowed() (o el sys.exit que la
    acompaña) dentro de Neo4jWriter.__init__, este test debe fallar.

    Se comprueba tanto por inspección de código fuente (para detectar el
    borrado literal de la comprobación) como por comportamiento (arriba, en
    test_neo4jwriter_blocks_without_key_and_never_touches_driver)."""
    source = inspect.getsource(Neo4jWriter.__init__)
    assert "_real_ingest_allowed" in source, (
        "Neo4jWriter.__init__ ya no comprueba _real_ingest_allowed(): "
        "el gate S9K_ALLOW_REAL_INGEST se ha roto."
    )
    assert "sys.exit" in source and "EXIT_INGEST_GATE_BLOCKED" in source, (
        "Neo4jWriter.__init__ ya no aborta con EXIT_INGEST_GATE_BLOCKED "
        "cuando la llave no autoriza escritura real."
    )
