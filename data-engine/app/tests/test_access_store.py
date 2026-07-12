"""Test básico de access_store.py (no se amplía el módulo en esta fase).

access_store.py ya tiene un selftest exhaustivo propio (access_store.py
--selftest). Este archivo solo añade cobertura pytest mínima para que quede
dentro de la suite estándar (`pytest data-engine/app/tests/`), sin tocar el
módulo ni implementar permisos por personaje todavía.
"""
from access import access_store


def test_request_and_approve_character_link(tmp_path):
    db = str(tmp_path / "access.db")
    access_store.init_db(db)

    link_id = access_store.request_character(
        username="ana", workspace="leyenda", character_id="char-kimi",
        character_name="Kimi", db_path=db,
    )
    links = access_store.list_links(username="ana", db_path=db)
    assert len(links) == 1
    assert links[0]["status"] == "pending"

    ok = access_store.approve_link(link_id, approved_by="admin", db_path=db)
    assert ok
    links = access_store.list_links(username="ana", db_path=db)
    assert links[0]["status"] == "approved"


def test_workspace_permission_defaults_and_upsert(tmp_path):
    db = str(tmp_path / "access.db")
    access_store.init_db(db)

    access_store.set_workspace_permission("pedro", "leyenda", can_view_secret=1, db_path=db)
    perm = access_store.get_workspace_permission("pedro", "leyenda", db_path=db)
    assert perm is not None
    assert perm["can_view_secret"] == 1
    assert perm["can_view_characters"] == 1  # default heredado


def test_audit_log_records_events(tmp_path):
    db = str(tmp_path / "access.db")
    access_store.init_db(db)

    access_store.request_character(
        username="ana", workspace="leyenda", character_id="char-kimi", db_path=db,
    )
    entries = access_store.list_audit(username="ana", db_path=db)
    assert len(entries) >= 1
    assert entries[0]["event"] == "user_character_requested"
