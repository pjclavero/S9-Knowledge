"""Tests del kind 'video' en job_store y del bridge opcional a jobs.db."""
from pathlib import Path

from jobs import job_store
from media.job_store_bridge import JobStoreBridge, map_status
from media.models import (
    MediaSource,
    STATUS_COMPLETE,
    STATUS_TRANSCRIBING,
)


def test_job_store_accepts_video_kind(tmp_path):
    db = str(tmp_path / "jobs.db")
    job_store.init_db(db)
    job_id = job_store.create_job("leyenda", "video", source_path="/x/sesion.mp4", db_path=db)
    job = job_store.get_job(job_id, db_path=db)
    assert job["source_kind"] == "video"
    assert job["status"] == "pending"


def test_map_status_translates_media_states():
    assert map_status(STATUS_TRANSCRIBING) == "transcribing"
    assert map_status(STATUS_COMPLETE) == "completed"
    assert map_status("estado_inexistente") is None


def test_bridge_registers_and_syncs(tmp_path):
    db = str(tmp_path / "jobs.db")
    bridge = JobStoreBridge(db_path=db)
    assert bridge.enabled is True

    source = MediaSource(
        source_id="media_bridge01",
        source_kind="audio",
        workspace="leyenda",
        original_path="/x/charla.mp3",
        original_filename="charla.mp3",
        sha256="hash",
        status="pending",
    )
    job_id = bridge.register(source)
    assert job_id is not None

    source.status = STATUS_COMPLETE
    source.output_markdown = "/out/media_bridge01.md"
    bridge.sync_status(source)

    job = job_store.get_job(job_id, db_path=db)
    assert job["status"] == "completed"
    assert job["output_markdown_path"] == "/out/media_bridge01.md"
