"""
conftest.py — shared pytest configuration for deploy/tests/.

Default behavior: mock get_tagged_commits to return set() (no deploy-* tags,
git "worked but found no tags"). This avoids depending on git being available
in the test environment while keeping the fail-closed logic testable.

Tests that specifically exercise tag behavior override this default via their
own monkeypatch.setattr call (the last setattr wins).
Tests that specifically exercise indeterminate/fail-closed behavior set it
to return None (simulating git unavailable).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure retention.py is importable in conftest (loaded before test modules)
_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import retention as _retention_module  # noqa: E402


@pytest.fixture(autouse=True)
def default_no_git_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set get_tagged_commits to return set() by default.

    This simulates "git worked, zero deploy-* tags found" for all tests
    that do not care about tag behaviour. Individual tests override this
    by calling monkeypatch.setattr(retention, "get_tagged_commits", ...)
    after this autouse fixture runs (last setattr wins).
    """
    monkeypatch.setattr(
        _retention_module,
        "get_tagged_commits",
        lambda root: set(),
    )
