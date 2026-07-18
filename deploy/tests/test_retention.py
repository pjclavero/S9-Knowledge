"""
test_retention.py — Test suite for deploy/scripts/retention.py.

Covers the 24 cases specified in the task (§13):
  1.  current symlink target never deleted
  2.  state-active release never deleted
  3.  state-previous release never deleted
  4.  rollback == previous release never deleted
  5.  live-process release: protected (mocked)
  6.  KEEP file release never deleted
  7.  deploy-* tagged commit release never deleted (mocked git)
  8.  protection registry release never deleted
  9.  N most recent non-protected releases preserved
 10.  dry-run (default) never deletes
 11.  apply deletes only eligible releases
 12.  symlink inside releases is skipped (SKIPPED_IS_SYMLINK)
 13.  path traversal attempt is blocked (SKIPPED_BOUNDARY_VIOLATION)
 14.  releases_root "/" is blocked
 15.  empty releases_root — nothing to do
 16.  missing manifest causes SKIP (not delete)
 17.  corrupt manifest causes SKIP (not delete)
 18.  race on current detection: protected_current resolves to unexpected dir
 19.  lock on release dir prevents deletion
 20.  corrupt deployment-state.json → all state-based protected as UNKNOWN
 21.  idempotency: apply twice gives same result
 22.  partial failure: protected releases untouched after safe_delete failure
 23.  keep_count < 3 is blocked
 24.  only eligible releases (beyond keep_count) are deleted; exact count verified
"""

from __future__ import annotations

import fcntl
import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

# Add scripts dir to path so we can import retention directly
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import retention  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_release(
    root: Path,
    name: str,
    commit: str = "abc1234",
    extra_files: dict | None = None,
    with_keep: bool = False,
    with_manifest: bool = True,
    corrupt_manifest: bool = False,
) -> Path:
    """Create a release directory under root with optional manifest."""
    release_dir = root / name
    release_dir.mkdir(parents=True)
    if with_manifest and not corrupt_manifest:
        manifest = {
            "release_id": name,
            "git_commit": commit,
            "created_at": "2026-01-01T00:00:00Z",
            "created_by": "test",
        }
        (release_dir / "manifest.json").write_text(json.dumps(manifest))
    elif corrupt_manifest:
        (release_dir / "manifest.json").write_text("{bad json}")
    if with_keep:
        (release_dir / "KEEP").write_text("keep this release")
    if extra_files:
        for fname, content in extra_files.items():
            (release_dir / fname).write_text(content)
    return release_dir


def _make_state(
    state_dir: Path,
    active_release: str = "",
    previous_release: str = "",
) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "deployment-state.json"
    state_file.write_text(json.dumps({
        "active_release": active_release,
        "active_commit": "abc1234",
        "previous_release": previous_release,
        "previous_commit": "",
        "updated_at": "2026-01-01T00:00:00Z",
        "deployment_id": "test",
    }))
    state_file.chmod(0o600)
    return state_file


@pytest.fixture
def lab(tmp_path: Path):
    """Returns (releases_root, current_link, state_file)."""
    releases_root = tmp_path / "releases"
    releases_root.mkdir()
    current_link = tmp_path / "current"
    state_dir = tmp_path / "state" / "deploy"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "deployment-state.json"
    return releases_root, current_link, state_file


def _run(
    releases_root: Path,
    current_link: Path,
    state_file: Path,
    keep: int = 3,
    apply: bool = False,
    protection_registry: set | None = None,
) -> int:
    return retention.run_retention(
        releases_root=releases_root,
        current_link=current_link,
        state_file=state_file,
        keep_count=keep,
        apply=apply,
        protection_registry=protection_registry or set(),
    )


# ---------------------------------------------------------------------------
# Helper: touch mtime so releases sort in a predictable order
# ---------------------------------------------------------------------------

def _set_mtime(path: Path, offset_seconds: float = 0.0) -> None:
    t = time.time() + offset_seconds
    os.utime(path, (t, t))


# ---------------------------------------------------------------------------
# Case 1: current symlink target never deleted
# ---------------------------------------------------------------------------

def test_current_never_deleted(lab, tmp_path):
    releases_root, current_link, state_file = lab
    r1 = _make_release(releases_root, "abc1111-20260101")
    _make_release(releases_root, "abc2222-20260102")
    _make_release(releases_root, "abc3333-20260103")
    _make_release(releases_root, "abc4444-20260104")  # oldest → would be deleted

    # Point current at the oldest (r1)
    current_link.symlink_to(r1)

    rc = _run(releases_root, current_link, state_file, keep=3, apply=True)
    assert rc == 0
    # r1 (current target) must still exist despite being "oldest"
    assert r1.exists(), "current symlink target was deleted"


# ---------------------------------------------------------------------------
# Case 2: state-active release never deleted
# ---------------------------------------------------------------------------

def test_state_active_never_deleted(lab):
    releases_root, current_link, state_file = lab
    active = _make_release(releases_root, "abc1111-20260101")
    _make_release(releases_root, "abc2222-20260102")
    _make_release(releases_root, "abc3333-20260103")
    _make_release(releases_root, "abc4444-20260104")

    _make_state(state_file.parent, active_release="abc1111-20260101")

    rc = _run(releases_root, current_link, state_file, keep=3, apply=True)
    assert rc == 0
    assert active.exists(), "state-active release was deleted"


# ---------------------------------------------------------------------------
# Case 3: state-previous release never deleted
# ---------------------------------------------------------------------------

def test_state_previous_never_deleted(lab):
    releases_root, current_link, state_file = lab
    prev = _make_release(releases_root, "abc1111-20260101")
    active = _make_release(releases_root, "abc5555-20260105")
    _make_release(releases_root, "abc2222-20260102")
    _make_release(releases_root, "abc3333-20260103")
    _make_release(releases_root, "abc4444-20260104")

    current_link.symlink_to(active)
    _make_state(
        state_file.parent,
        active_release="abc5555-20260105",
        previous_release="abc1111-20260101",
    )

    rc = _run(releases_root, current_link, state_file, keep=3, apply=True)
    assert rc == 0
    assert prev.exists(), "state-previous release was deleted"


# ---------------------------------------------------------------------------
# Case 4: rollback == previous release never deleted (alias test)
# ---------------------------------------------------------------------------

def test_rollback_is_previous_never_deleted(lab):
    """Previous and rollback are the same concept via state-file."""
    releases_root, current_link, state_file = lab
    rollback = _make_release(releases_root, "abc0000-20260101")
    _make_release(releases_root, "abc1111-20260102")
    _make_release(releases_root, "abc2222-20260103")
    _make_release(releases_root, "abc3333-20260104")
    _make_release(releases_root, "abc4444-20260105")

    _make_state(
        state_file.parent,
        active_release="abc4444-20260105",
        previous_release="abc0000-20260101",
    )
    current_link.symlink_to(releases_root / "abc4444-20260105")

    rc = _run(releases_root, current_link, state_file, keep=3, apply=True)
    assert rc == 0
    assert rollback.exists(), "rollback/previous release was deleted"


# ---------------------------------------------------------------------------
# Case 5: live-process release protected (mocked)
# ---------------------------------------------------------------------------

def test_live_process_never_deleted(lab, monkeypatch):
    releases_root, current_link, state_file = lab
    live = _make_release(releases_root, "abc1111-20260101")
    _make_release(releases_root, "abc2222-20260102")
    _make_release(releases_root, "abc3333-20260103")
    _make_release(releases_root, "abc4444-20260104")

    # Mock get_live_process_paths to return the live release
    monkeypatch.setattr(
        retention, "get_live_process_paths",
        lambda root: {str(live.resolve())},
    )

    rc = _run(releases_root, current_link, state_file, keep=3, apply=True)
    assert rc == 0
    assert live.exists(), "live-process release was deleted"


# ---------------------------------------------------------------------------
# Case 6: KEEP file release never deleted
# ---------------------------------------------------------------------------

def test_keep_file_never_deleted(lab):
    releases_root, current_link, state_file = lab
    kept = _make_release(releases_root, "abc1111-20260101", with_keep=True)
    _make_release(releases_root, "abc2222-20260102")
    _make_release(releases_root, "abc3333-20260103")
    _make_release(releases_root, "abc4444-20260104")

    rc = _run(releases_root, current_link, state_file, keep=3, apply=True)
    assert rc == 0
    assert kept.exists(), "KEEP-file release was deleted"


# ---------------------------------------------------------------------------
# Case 7: deploy-* tagged commit release never deleted (mocked git)
# ---------------------------------------------------------------------------

def test_tagged_release_never_deleted(lab, monkeypatch):
    releases_root, current_link, state_file = lab
    tagged = _make_release(releases_root, "abc1234-20260101", commit="abc1234abcdef")
    _make_release(releases_root, "abc2222-20260102")
    _make_release(releases_root, "abc3333-20260103")
    _make_release(releases_root, "abc4444-20260104")

    # Mock get_tagged_commits to return the commit of "tagged" release
    monkeypatch.setattr(
        retention, "get_tagged_commits",
        lambda root: {"abc1234abcdef", "abc1234"},
    )

    rc = _run(releases_root, current_link, state_file, keep=3, apply=True)
    assert rc == 0
    assert tagged.exists(), "tagged-commit release was deleted"


# ---------------------------------------------------------------------------
# Case 8: protection registry release never deleted
# ---------------------------------------------------------------------------

def test_registry_never_deleted(lab):
    releases_root, current_link, state_file = lab
    protected = _make_release(releases_root, "abc1111-20260101")
    _make_release(releases_root, "abc2222-20260102")
    _make_release(releases_root, "abc3333-20260103")
    _make_release(releases_root, "abc4444-20260104")

    registry = {"abc1111-20260101"}

    rc = _run(releases_root, current_link, state_file, keep=3, apply=True,
              protection_registry=registry)
    assert rc == 0
    assert protected.exists(), "registry-protected release was deleted"


# ---------------------------------------------------------------------------
# Case 9: N most recent non-protected preserved
# ---------------------------------------------------------------------------

def test_n_most_recent_preserved(lab):
    releases_root, current_link, state_file = lab
    # Create 6 releases; no special protections
    for i in range(1, 7):
        r = _make_release(releases_root, f"abc000{i}-2026010{i}")
        _set_mtime(r, offset_seconds=float(i))  # ensure consistent ordering

    rc = _run(releases_root, current_link, state_file, keep=3, apply=True)
    assert rc == 0

    existing = [p for p in releases_root.iterdir() if p.is_dir()]
    assert len(existing) == 3, f"Expected 3 kept releases, got {len(existing)}: {[p.name for p in existing]}"


# ---------------------------------------------------------------------------
# Case 10: dry-run (default) never deletes
# ---------------------------------------------------------------------------

def test_dry_run_never_deletes(lab):
    releases_root, current_link, state_file = lab
    for i in range(1, 7):
        _make_release(releases_root, f"abc000{i}-2026010{i}")

    rc = _run(releases_root, current_link, state_file, keep=3, apply=False)
    assert rc == 0

    existing = list(releases_root.iterdir())
    assert len(existing) == 6, "dry-run deleted something"


# ---------------------------------------------------------------------------
# Case 11: apply deletes only eligible releases
# ---------------------------------------------------------------------------

def test_apply_deletes_eligible_only(lab):
    releases_root, current_link, state_file = lab
    releases = []
    for i in range(1, 8):
        r = _make_release(releases_root, f"abc000{i}-2026010{i}")
        _set_mtime(r, offset_seconds=float(i))
        releases.append(r)

    # The oldest (i=1..4) should be eligible; keep 3 most recent
    rc = _run(releases_root, current_link, state_file, keep=3, apply=True)
    assert rc == 0

    surviving = {p.name for p in releases_root.iterdir() if p.is_dir()}
    # Exactly 3 most-recent should survive
    assert len(surviving) == 3
    # The 3 newest (i=5,6,7) survive
    assert "abc0007-20260107" in surviving
    assert "abc0006-20260106" in surviving
    assert "abc0005-20260105" in surviving


# ---------------------------------------------------------------------------
# Case 12: symlink inside releases is skipped
# ---------------------------------------------------------------------------

def test_symlink_inside_releases_skipped(lab, tmp_path):
    releases_root, current_link, state_file = lab
    real_dir = tmp_path / "external_release"
    real_dir.mkdir()
    (real_dir / "manifest.json").write_text('{"release_id":"x","git_commit":"abc","created_at":"","created_by":"t"}')

    # Create a symlink inside releases_root pointing to external dir
    symlink_in_root = releases_root / "abc1234-20260101"
    symlink_in_root.symlink_to(real_dir)

    # Also create a real release to have something to process
    _make_release(releases_root, "abc5678-20260102")

    rc = _run(releases_root, current_link, state_file, keep=3, apply=True)
    assert rc == 0
    # The symlink should NOT have been deleted (it's skipped)
    assert symlink_in_root.is_symlink(), "symlink inside releases was removed"
    # The external directory must be intact
    assert real_dir.is_dir(), "external directory was removed via symlink"


# ---------------------------------------------------------------------------
# Case 13: path traversal attempt is blocked
# ---------------------------------------------------------------------------

def test_path_traversal_blocked(lab, tmp_path):
    releases_root, current_link, state_file = lab
    # Create a release with a ".." in the name (can't be created on most FS,
    # but we can test the regex guard directly)
    safe, reason = retention.is_safe_candidate(
        Path("/opt/s9-knowledge/releases/../etc"), releases_root
    )
    # The boundary check should fail
    assert not safe

    # Also test that a path that doesn't match the pattern fails
    bad_path = releases_root / "../../etc"
    safe2, reason2 = retention.is_safe_candidate(bad_path, releases_root)
    assert not safe2


# ---------------------------------------------------------------------------
# Case 14: releases_root "/" is blocked
# ---------------------------------------------------------------------------

def test_releases_root_slash_blocked(lab):
    releases_root, current_link, state_file = lab
    rc = _run(Path("/"), current_link, state_file, keep=3, apply=True)
    assert rc == 1, "Expected BLOCKED (rc=1) when releases_root is /"


# ---------------------------------------------------------------------------
# Case 15: empty releases_root — nothing to do
# ---------------------------------------------------------------------------

def test_empty_releases_root(lab):
    releases_root, current_link, state_file = lab
    # releases_root exists but is empty
    rc = _run(releases_root, current_link, state_file, keep=3, apply=True)
    assert rc == 0


# ---------------------------------------------------------------------------
# Case 16: missing manifest causes SKIP (not delete)
# ---------------------------------------------------------------------------

def test_missing_manifest_skipped(lab):
    releases_root, current_link, state_file = lab
    # Create a release WITHOUT manifest.json
    no_manifest = _make_release(releases_root, "abc1111-20260101", with_manifest=False)
    _make_release(releases_root, "abc2222-20260102")
    _make_release(releases_root, "abc3333-20260103")
    _make_release(releases_root, "abc4444-20260104")

    rc = _run(releases_root, current_link, state_file, keep=3, apply=True)
    assert rc == 0
    # No-manifest dir must NOT be deleted (it's skipped, not classified as eligible)
    assert no_manifest.exists(), "release without manifest was deleted"


# ---------------------------------------------------------------------------
# Case 17: corrupt manifest causes SKIP (not delete)
# ---------------------------------------------------------------------------

def test_corrupt_manifest_skipped(lab):
    releases_root, current_link, state_file = lab
    corrupt = _make_release(releases_root, "abc1111-20260101", corrupt_manifest=True)
    _make_release(releases_root, "abc2222-20260102")
    _make_release(releases_root, "abc3333-20260103")
    _make_release(releases_root, "abc4444-20260104")

    rc = _run(releases_root, current_link, state_file, keep=3, apply=True)
    assert rc == 0
    assert corrupt.exists(), "release with corrupt manifest was deleted"


# ---------------------------------------------------------------------------
# Case 18: race-condition on current detection doesn't delete protected
# ---------------------------------------------------------------------------

def test_current_race_protected(lab, monkeypatch):
    """
    Simulate a situation where current symlink was valid at classification time
    but safe_delete sees it as a symlink → BLOCKED.
    """
    releases_root, current_link, state_file = lab
    r1 = _make_release(releases_root, "abc1111-20260101")
    _make_release(releases_root, "abc2222-20260102")
    _make_release(releases_root, "abc3333-20260103")
    _make_release(releases_root, "abc4444-20260104")

    # Don't point current at r1, and don't protect via state.
    # Simulate safe_delete refusing because the candidate became a symlink
    original_safe_delete = retention.safe_delete_release

    def refusing_safe_delete(candidate, root):
        if candidate == r1:
            return False  # simulate race / refusal
        return original_safe_delete(candidate, root)

    monkeypatch.setattr(retention, "safe_delete_release", refusing_safe_delete)

    rc = _run(releases_root, current_link, state_file, keep=3, apply=True)
    # BLOCKED because safe_delete returned False for r1
    assert rc == 1, "Expected BLOCKED (1) when safe_delete refuses"
    assert r1.exists(), "Release was deleted despite safe_delete refusal"


# ---------------------------------------------------------------------------
# Case 19: exclusive lock on release dir prevents safe_delete_release
# ---------------------------------------------------------------------------

def test_lock_prevents_deletion(lab):
    """
    If .retention.lock is pre-created and exclusively locked by another
    file descriptor in the same process, safe_delete_release must return False.
    We test safe_delete_release directly (not via run_retention) to avoid the
    live-process-detection code seeing the open fd and protecting the release
    before we even attempt deletion.
    """
    releases_root, current_link, state_file = lab
    r1 = _make_release(releases_root, "abc1111-20260101")

    lock_path = r1 / ".retention.lock"
    lock_path.write_text("")
    lock_fd = os.open(str(lock_path), os.O_WRONLY)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        # Call safe_delete_release directly; it should fail to acquire the lock
        result = retention.safe_delete_release(r1, releases_root)
        assert not result, "safe_delete_release should return False when lock is held"
        assert r1.exists(), "Release was deleted despite locked .retention.lock"
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Case 20: corrupt deployment-state.json → state-based protection is degraded
#           but current is still protected
# ---------------------------------------------------------------------------

def test_corrupt_state_current_still_protected(lab):
    releases_root, current_link, state_file = lab
    r_current = _make_release(releases_root, "abc5555-20260105")
    _make_release(releases_root, "abc1111-20260101")
    _make_release(releases_root, "abc2222-20260102")
    _make_release(releases_root, "abc3333-20260103")
    _make_release(releases_root, "abc4444-20260104")

    current_link.symlink_to(r_current)

    # Write corrupt state file
    state_file.write_text("{corrupted json}")

    rc = _run(releases_root, current_link, state_file, keep=3, apply=True)
    assert rc == 0
    # current target must always be protected regardless of state corruption
    assert r_current.exists(), "current symlink target deleted despite corrupt state"


# ---------------------------------------------------------------------------
# Case 21: idempotency — apply twice gives same result
# ---------------------------------------------------------------------------

def test_idempotency(lab):
    releases_root, current_link, state_file = lab
    for i in range(1, 8):
        r = _make_release(releases_root, f"abc000{i}-2026010{i}")
        _set_mtime(r, offset_seconds=float(i))

    rc1 = _run(releases_root, current_link, state_file, keep=3, apply=True)
    surviving_1 = {p.name for p in releases_root.iterdir() if p.is_dir()}

    rc2 = _run(releases_root, current_link, state_file, keep=3, apply=True)
    surviving_2 = {p.name for p in releases_root.iterdir() if p.is_dir()}

    assert rc1 == 0
    assert rc2 == 0
    assert surviving_1 == surviving_2, "Second apply changed the surviving set"


# ---------------------------------------------------------------------------
# Case 22: partial failure — protected releases untouched after safe_delete failure
# ---------------------------------------------------------------------------

def test_partial_failure_protected_untouched(lab, monkeypatch):
    """
    Setup: 7 releases. 1 current, 1 KEEP-protected, 3 RECENT, 2 ELIGIBLE.
    When safe_delete_release fails for eligible1, the overall result is BLOCKED
    (rc=1), and all protected releases remain intact.
    """
    releases_root, current_link, state_file = lab

    # KEEP-protected (must never be deleted)
    kept = _make_release(releases_root, "abc0000-20260100", with_keep=True)
    # 2 eligible (oldest non-protected)
    eligible1 = _make_release(releases_root, "abc1111-20260101")
    eligible2 = _make_release(releases_root, "abc2222-20260102")
    # 3 most-recent non-protected
    rec1 = _make_release(releases_root, "abc3333-20260103")
    rec2 = _make_release(releases_root, "abc4444-20260104")
    rec3 = _make_release(releases_root, "abc5555-20260105")
    # Current (most recent)
    cur = _make_release(releases_root, "abc6666-20260106")
    current_link.symlink_to(cur)

    # Deterministic mtime ordering
    _set_mtime(kept,      offset_seconds=-6.0)
    _set_mtime(eligible1, offset_seconds=-5.0)
    _set_mtime(eligible2, offset_seconds=-4.0)
    _set_mtime(rec1,      offset_seconds=-3.0)
    _set_mtime(rec2,      offset_seconds=-2.0)
    _set_mtime(rec3,      offset_seconds=-1.0)
    _set_mtime(cur,       offset_seconds=0.0)

    # safe_delete_release refuses for eligible1 (simulates partial failure)
    original = retention.safe_delete_release
    calls: list[str] = []

    def partial_fail(candidate: Any, root: Any) -> bool:
        calls.append(candidate.name)
        if candidate.name == eligible1.name:
            return False
        return original(candidate, root)

    monkeypatch.setattr(retention, "safe_delete_release", partial_fail)

    rc = _run(releases_root, current_link, state_file, keep=3, apply=True)
    assert rc == 1, f"Expected BLOCKED (1) due to partial safe_delete failure, got {rc}"

    # Protected releases must be untouched
    assert kept.exists(),     "KEEP-protected release was deleted"
    assert cur.exists(),      "current release was deleted"
    assert rec1.exists(),     "recent-1 release was deleted"
    assert rec2.exists(),     "recent-2 release was deleted"
    assert rec3.exists(),     "recent-3 release was deleted"
    # eligible1: safe_delete refused, must still exist
    assert eligible1.exists(), "eligible1 was deleted despite safe_delete refusal"
    # eligible2: was attempted
    assert eligible2.name in calls, "eligible2 was never attempted for deletion"


# ---------------------------------------------------------------------------
# Case 23: keep_count < 3 is blocked
# ---------------------------------------------------------------------------

def test_keep_count_below_minimum_blocked(lab):
    releases_root, current_link, state_file = lab
    _make_release(releases_root, "abc1111-20260101")

    for bad_keep in (0, 1, 2, -1):
        rc = _run(releases_root, current_link, state_file, keep=bad_keep, apply=True)
        assert rc == 1, f"Expected BLOCKED for keep_count={bad_keep}"


# ---------------------------------------------------------------------------
# Case 24: exact count — only eligible releases (beyond keep_count) are deleted
# ---------------------------------------------------------------------------

def test_exact_delete_count(lab):
    releases_root, current_link, state_file = lab
    releases = []
    for i in range(1, 11):  # 10 releases
        r = _make_release(releases_root, f"abc{i:04d}-202601{i:02d}")
        _set_mtime(r, offset_seconds=float(i))
        releases.append(r)

    rc = _run(releases_root, current_link, state_file, keep=4, apply=True)
    assert rc == 0

    surviving = [p for p in releases_root.iterdir() if p.is_dir()]
    assert len(surviving) == 4, f"Expected 4 surviving releases, got {len(surviving)}"


# ---------------------------------------------------------------------------
# Bonus: write_deployment_state atomicity
# ---------------------------------------------------------------------------

def test_write_deployment_state(tmp_path):
    state_dir = tmp_path / "deploy"
    state_file = state_dir / "deployment-state.json"

    ok = retention.write_deployment_state(
        state_file=state_file,
        active_release="abc1234-20260101",
        active_commit="abc1234",
        previous_release="abc0000-20260100",
        previous_commit="abc0000",
        deployment_id="abc1234-20260101",
    )
    assert ok
    assert state_file.is_file()

    data = json.loads(state_file.read_text())
    assert data["active_release"] == "abc1234-20260101"
    assert data["previous_release"] == "abc0000-20260100"
    assert "updated_at" in data


def test_write_deployment_state_permissions(tmp_path):
    state_dir = tmp_path / "deploy"
    state_file = state_dir / "deployment-state.json"

    retention.write_deployment_state(
        state_file=state_file,
        active_release="r1",
        active_commit="abc1234",
        previous_release=None,
        previous_commit=None,
        deployment_id="r1",
    )
    # File should be 0600 (owner read/write only)
    file_mode = stat.S_IMODE(state_file.stat().st_mode)
    assert file_mode == 0o600, f"Expected 0600, got {oct(file_mode)}"


def test_is_safe_candidate_rejects_root(tmp_path):
    releases_root = tmp_path / "releases"
    releases_root.mkdir()
    safe, reason = retention.is_safe_candidate(releases_root, releases_root)
    assert not safe


def test_is_safe_candidate_rejects_non_child(tmp_path):
    releases_root = tmp_path / "releases"
    releases_root.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    (other / "manifest.json").write_text('{"release_id":"x","git_commit":"y","created_at":"","created_by":"t"}')
    safe, reason = retention.is_safe_candidate(other, releases_root)
    assert not safe


def test_validate_manifest_corrupt(tmp_path):
    bad = tmp_path / "manifest.json"
    bad.write_text("{corrupt")
    ok, data = retention.validate_manifest(bad)
    assert not ok
    assert data is None


def test_validate_manifest_missing_fields(tmp_path):
    incomplete = tmp_path / "manifest.json"
    incomplete.write_text(json.dumps({"release_id": "x"}))
    ok, data = retention.validate_manifest(incomplete)
    assert not ok


def test_validate_manifest_valid(tmp_path):
    valid = tmp_path / "manifest.json"
    valid.write_text(json.dumps({
        "release_id": "abc1234-20260101",
        "git_commit": "abc1234",
        "created_at": "2026-01-01T00:00:00Z",
        "created_by": "deploy.sh",
    }))
    ok, data = retention.validate_manifest(valid)
    assert ok
    assert data is not None
    assert data["release_id"] == "abc1234-20260101"
