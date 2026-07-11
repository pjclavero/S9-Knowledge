"""Tests unitarios para la validación semántica de relaciones en ingest_rpg.py."""
import os
import sys

# Igual que test_schemas.py: el paquete `schemas` se importa como top-level
# (no como `app.schemas`), así que el directorio `app/` debe estar en sys.path.
# Usamos una ruta calculada en vez de la ruta fija de despliegue (/opt/...)
# para que el test funcione también fuera del contenedor Docker.
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)
sys.path.insert(0, "/opt/knowledge-services/property-graph/app")

import types  # noqa: E402

# `ingest_rpg.py` hace `import fcntl` a nivel de módulo para el locking de
# ficheros (solo se usa dentro de funciones que no ejercitamos aquí). `fcntl`
# no existe en Windows, así que se stubea con un módulo falso únicamente para
# permitir el import — no se ejecuta ninguna lógica de locking en este test.
if sys.platform == "win32" and "fcntl" not in sys.modules:
    _fcntl_stub = types.ModuleType("fcntl")
    _fcntl_stub.flock = lambda *a, **k: None
    _fcntl_stub.LOCK_EX = 2
    _fcntl_stub.LOCK_UN = 8
    _fcntl_stub.LOCK_NB = 4
    sys.modules["fcntl"] = _fcntl_stub

from schemas.rpg_schema import EntityBase, RelationshipBase  # noqa: E402
from ingest_rpg import _check_relation_semantics  # noqa: E402


def make_entity(canonical_name, entity_type, **kwargs):
    defaults = dict(
        canonical_name=canonical_name,
        display_name=canonical_name,
        entity_type=entity_type,
        workspace="leyenda",
        source_document="test.pdf",
        source_pages=[1],
        confidence=0.9,
    )
    defaults.update(kwargs)
    return EntityBase(**defaults)


def make_rel(source_canonical, relation_type, target_canonical, **kwargs):
    defaults = dict(
        source_canonical=source_canonical,
        relation_type=relation_type,
        target_canonical=target_canonical,
        source_document="test.pdf",
        source_pages=[1],
        confidence=0.9,
    )
    defaults.update(kwargs)
    return RelationshipBase(**defaults)


def test_has_fought_location_normalizes_to_fought_at(tmp_path):
    """HAS_FOUGHT con target Location debe normalizarse a FOUGHT_AT (in-place)."""
    creature = make_entity("Oni de la Montaña Negra", "Creature")
    location = make_entity("Santuario abandonado", "Location")
    rel = make_rel("Oni de la Montaña Negra", "HAS_FOUGHT", "Santuario abandonado")

    warnings_path = tmp_path / "semantic_review.md"
    verdict, warning = _check_relation_semantics(
        rel, [creature, location], warnings_path
    )

    assert verdict == "ok"
    assert rel.relation_type == "FOUGHT_AT"
    assert rel.relation_label_es == "combatido en"
    assert warning is not None
    assert "normalized" in warning
    assert "HAS_FOUGHT" in warning and "FOUGHT_AT" in warning
    # La normalización es silenciosa: no debe escribirse en el archivo de
    # revisión manual, ya que no es un problema sino una corrección.
    assert not warnings_path.exists()


def test_has_fought_region_normalizes_to_fought_at():
    """El mismo comportamiento debe aplicar para target_type == Region."""
    creature = make_entity("Bestia del Bosque", "Creature")
    region = make_entity("Región Sombría", "Region")
    rel = make_rel("Bestia del Bosque", "HAS_FOUGHT", "Región Sombría")

    verdict, warning = _check_relation_semantics(
        rel, [creature, region], "unused_path.md"
    )

    assert verdict == "ok"
    assert rel.relation_type == "FOUGHT_AT"


def test_has_fought_character_target_unaffected():
    """HAS_FOUGHT entre dos seres no debe tocarse (comportamiento previo)."""
    creature = make_entity("Oni de la Montaña Negra", "Creature")
    character = make_entity("Kaito", "Character")
    rel = make_rel("Oni de la Montaña Negra", "HAS_FOUGHT", "Kaito")

    verdict, warning = _check_relation_semantics(
        rel, [creature, character], "unused_path.md"
    )

    assert verdict == "ok"
    assert rel.relation_type == "HAS_FOUGHT"
    assert warning is None


def test_attacked_location_still_dubious():
    """Las reglas 'dudosas' preexistentes para otras relaciones no cambian."""
    character = make_entity("Kaito", "Character")
    location = make_entity("Santuario abandonado", "Location")
    rel = make_rel("Kaito", "ATTACKED", "Santuario abandonado")

    verdict, warning = _check_relation_semantics(
        rel, [character, location], "unused_path.md"
    )

    assert verdict == "dubious"
    assert rel.relation_type == "ATTACKED"
