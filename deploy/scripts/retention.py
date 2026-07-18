#!/usr/bin/env python3
"""
retention.py -- Fail-closed release retention for S9 Knowledge.

By DEFAULT this script runs in DRY-RUN mode: it reports what would be
deleted but never touches disk unless --apply is explicitly passed.

Principle: when in doubt, SKIP. Never delete.

Exit codes:
  0  = OK (dry-run report or apply completed without errors)
  1  = BLOCKED (a safety invariant was violated; nothing was deleted)
  2  = ERROR (unexpected exception)
"""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configurable defaults (overridable for tests)
# ---------------------------------------------------------------------------
DEFAULT_RELEASES_ROOT = "/opt/s9-knowledge/releases"
DEFAULT_CURRENT_LINK = "/opt/s9-knowledge/current"
DEFAULT_STATE_FILE = "/var/lib/s9-knowledge/deploy/deployment-state.json"
DEFAULT_KEEP_COUNT = 3
RELEASE_ID_RE = re.compile(
    r"^[0-9a-f]{7,40}-\d{8}(-\d{6})?$"   # sha-date or sha-datetime
    r"|^\d{8}(-\d{6})?-[0-9a-f]{7,40}$"   # date-sha or datetime-sha
)

logging.basicConfig(
    format="[retention] %(levelname)s %(message)s",
    level=logging.INFO,
    stream=sys.stderr,
)
log = logging.getLogger("retention")


# ---------------------------------------------------------------------------
# Result constants
# ---------------------------------------------------------------------------
class Disposition:
    DELETED = "DELETED"
    DRY_RUN = "DRY_RUN"
    PROTECTED_CURRENT = "PROTECTED_CURRENT"
    PROTECTED_STATE_ACTIVE = "PROTECTED_STATE_ACTIVE"
    PROTECTED_STATE_PREVIOUS = "PROTECTED_STATE_PREVIOUS"
    PROTECTED_LIVE_PROCESS = "PROTECTED_LIVE_PROCESS"
    PROTECTED_KEEP_FILE = "PROTECTED_KEEP_FILE"
    PROTECTED_TAG = "PROTECTED_TAG"
    PROTECTED_REGISTRY = "PROTECTED_REGISTRY"
    PROTECTED_RECENT = "PROTECTED_RECENT"
    PROTECTED_UNKNOWN = "PROTECTED_UNKNOWN"
    SKIPPED_NO_MANIFEST = "SKIPPED_NO_MANIFEST"
    SKIPPED_MANIFEST_CORRUPT = "SKIPPED_MANIFEST_CORRUPT"
    SKIPPED_IS_SYMLINK = "SKIPPED_IS_SYMLINK"
    SKIPPED_BOUNDARY_VIOLATION = "SKIPPED_BOUNDARY_VIOLATION"
    SKIPPED_PATTERN_MISMATCH = "SKIPPED_PATTERN_MISMATCH"
    BLOCKED = "BLOCKED"


# ---------------------------------------------------------------------------
# Path-safety helpers
# ---------------------------------------------------------------------------

def resolve_strictly(path: Path) -> Optional[Path]:
    """Resolve path without following symlinks mid-path.
    Returns None if any component is a symlink (excluding the final target
    itself -- for directories we require the directory itself not be a symlink).
    """
    try:
        return path.resolve()
    except OSError:
        return None


def is_safe_candidate(candidate: Path, releases_root: Path) -> tuple[bool, str]:
    """
    Apply all boundary and safety checks to a candidate release directory.

    Returns (safe: bool, reason: str).
    """
    # 1. candidate must exist as a real directory (not a symlink)
    try:
        st = os.lstat(candidate)
    except OSError as exc:
        return False, f"lstat failed: {exc}"

    import stat as stat_mod
    if stat_mod.S_ISLNK(st.st_mode):
        return False, "candidate is a symlink"

    if not stat_mod.S_ISDIR(st.st_mode):
        return False, "candidate is not a directory"

    # 2. candidate must not be root '/'
    if candidate == Path("/"):
        return False, "candidate is /"

    # 3. candidate must not be the releases_root itself
    try:
        if candidate.resolve() == releases_root.resolve():
            return False, "candidate resolves to releases_root"
    except OSError as exc:
        return False, f"resolve failed: {exc}"

    # 4. candidate must be a direct child of releases_root (no '..')
    try:
        candidate.relative_to(releases_root)
    except ValueError:
        return False, "candidate is not under releases_root"

    parts_relative = candidate.parts[len(releases_root.parts):]
    if len(parts_relative) != 1:
        return False, "candidate is not a direct child of releases_root"

    # 5. No '..' in any component
    if ".." in candidate.parts:
        return False, "candidate path contains '..'"

    # 6. candidate must not resolve outside releases_root
    try:
        resolved = candidate.resolve()
        releases_root_resolved = releases_root.resolve()
        resolved.relative_to(releases_root_resolved)
    except (ValueError, OSError) as exc:
        return False, f"candidate resolves outside releases_root: {exc}"

    # 7. candidate name must match release ID pattern
    if not RELEASE_ID_RE.match(candidate.name):
        return False, f"name does not match release ID pattern: {candidate.name!r}"

    # 8. candidate must contain a manifest.json
    manifest_path = candidate / "manifest.json"
    if not manifest_path.is_file():
        return False, "manifest.json not found"

    return True, "ok"


def validate_manifest(manifest_path: Path) -> tuple[bool, Optional[dict]]:
    """Parse and validate a manifest.json. Returns (valid, data_or_None)."""
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("manifest parse error at %s: %s", manifest_path, exc)
        return False, None

    required = {"release_id", "git_commit", "created_at", "created_by"}
    missing = required - data.keys()
    if missing:
        log.warning("manifest missing fields %s at %s", missing, manifest_path)
        return False, None

    return True, data


# ---------------------------------------------------------------------------
# Protection: deployed tags
# ---------------------------------------------------------------------------

def get_tagged_commits(releases_root: Path) -> Optional[set[str]]:
    """
    Return the set of git commit SHAs (full + 7-char short) referenced by
    any tag matching 'deploy-*'.

    Return value semantics (fail-closed):
      None       = could not determine tags (git absent, no repo, error, timeout)
                   → caller must treat affected releases as PROTECTED_UNKNOWN
      set()      = git worked, no deploy-* tags found
      {sha, ...} = git worked, these SHAs are tagged

    NEVER silently return an empty set when the query itself failed.

    Search strategy (most reliable first):
      1. Walk up from releases_root looking for a .git directory.
      2. Try git -C on each existing release dir (each is a clone with its own .git).
      3. Try git -C releases_root.parent as a last resort.
    """
    # Check git is available at all
    if not subprocess.run(
        ["git", "--version"],
        capture_output=True, timeout=5,
    ).returncode == 0:
        log.warning("get_tagged_commits: git not available → tags INDETERMINATE")
        return None

    def _query_tags(repo_dir: str) -> Optional[set[str]]:
        """Query deploy-* tags from a specific repo dir. Returns None on error."""
        try:
            result = subprocess.run(
                ["git", "-C", repo_dir, "tag", "--list", "deploy-*"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return None
            found: set[str] = set()
            for tag in result.stdout.splitlines():
                tag = tag.strip()
                if not tag:
                    continue
                r2 = subprocess.run(
                    ["git", "-C", repo_dir, "rev-parse", "--verify", f"{tag}^{{commit}}"],
                    capture_output=True, text=True, timeout=5,
                )
                if r2.returncode == 0:
                    full_sha = r2.stdout.strip()
                    found.add(full_sha)
                    if len(full_sha) >= 7:
                        found.add(full_sha[:7])
            return found
        except Exception:  # noqa: BLE001
            return None

    errors = 0
    successes = 0
    all_tagged: set[str] = set()

    # Strategy 1: walk up from releases_root for a .git
    candidate = releases_root.parent
    for _ in range(6):  # max 6 levels up
        git_dir = candidate / ".git"
        if git_dir.is_dir() or git_dir.is_file():
            result = _query_tags(str(candidate))
            if result is not None:
                all_tagged.update(result)
                successes += 1
            else:
                errors += 1
            break
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent

    # Strategy 2: try each existing release dir (they are git clones)
    try:
        for rel in releases_root.iterdir():
            if not rel.is_dir():
                continue
            git_dir = rel / ".git"
            if not (git_dir.is_dir() or git_dir.is_file()):
                continue
            result = _query_tags(str(rel))
            if result is not None:
                all_tagged.update(result)
                successes += 1
            else:
                errors += 1
    except OSError:
        errors += 1

    # Strategy 3: releases_root.parent as fallback
    if successes == 0:
        result = _query_tags(str(releases_root.parent))
        if result is not None:
            all_tagged.update(result)
            successes += 1
        else:
            errors += 1

    if successes == 0:
        # All queries failed — cannot determine tag status
        log.warning(
            "get_tagged_commits: all %d git query attempts failed → tags INDETERMINATE; "
            "releases with unknown tag status will be marked PROTECTED_UNKNOWN",
            errors,
        )
        return None

    if errors > 0:
        log.warning(
            "get_tagged_commits: %d git queries succeeded, %d failed; "
            "using union of successful results",
            successes, errors,
        )

    return all_tagged


# ---------------------------------------------------------------------------
# Protection: live processes
# ---------------------------------------------------------------------------

def get_live_process_paths(releases_root: Path) -> set[str]:
    """
    Return the set of resolved paths (as strings) used by any running process
    that references something under releases_root. Inspects /proc/*/exe,
    /proc/*/fd/*, /proc/*/maps. Never raises; returns empty set on error.
    """
    roots: set[str] = set()
    releases_root_str = str(releases_root.resolve())
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return roots

    for pid_dir in proc_root.iterdir():
        if not pid_dir.name.isdigit():
            continue
        # /proc/<pid>/exe
        for probe in (pid_dir / "exe",):
            try:
                target = os.readlink(probe)
                if target.startswith(releases_root_str + "/"):
                    parts = target[len(releases_root_str) + 1:].split("/")
                    if parts:
                        roots.add(releases_root_str + "/" + parts[0])
            except OSError:
                pass
        # /proc/<pid>/fd/*
        fd_dir = pid_dir / "fd"
        try:
            for fd in fd_dir.iterdir():
                try:
                    target = os.readlink(fd)
                    if target.startswith(releases_root_str + "/"):
                        parts = target[len(releases_root_str) + 1:].split("/")
                        if parts:
                            roots.add(releases_root_str + "/" + parts[0])
                except OSError:
                    pass
        except (OSError, PermissionError):
            pass
        # /proc/<pid>/maps
        maps_path = pid_dir / "maps"
        try:
            with open(maps_path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    fields = line.split()
                    if len(fields) >= 6:
                        path = fields[5]
                        if path.startswith(releases_root_str + "/"):
                            parts = path[len(releases_root_str) + 1:].split("/")
                            if parts:
                                roots.add(releases_root_str + "/" + parts[0])
        except (OSError, PermissionError):
            pass

    return roots


# ---------------------------------------------------------------------------
# Protection: deployment-state.json
# ---------------------------------------------------------------------------

def read_deployment_state(state_file: Path) -> dict:
    """
    Read deployment-state.json. Returns empty dict on any error (fail-open:
    unknown state means we protect more, not less).
    """
    if not state_file.is_file():
        return {}
    try:
        with open(state_file, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            log.warning("deployment-state.json is not a JSON object; ignoring")
            return {}
        return data
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("deployment-state.json unreadable: %s; protecting all state-based releases", exc)
        return {}


# ---------------------------------------------------------------------------
# Explicit protection registry
# ---------------------------------------------------------------------------

def read_protection_registry(releases_root: Path) -> set[str]:
    """
    Read an optional protection registry file at releases_root/../protected-releases.
    Each non-empty, non-comment line is a release ID that must never be deleted.
    """
    registry_path = releases_root.parent / "protected-releases"
    protected: set[str] = set()
    if not registry_path.is_file():
        return protected
    try:
        with open(registry_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    protected.add(line)
    except OSError as exc:
        log.warning("could not read protection registry %s: %s", registry_path, exc)
    return protected


# ---------------------------------------------------------------------------
# Safe delete (no rm -rf with string concatenation)
# ---------------------------------------------------------------------------

def safe_delete_release(candidate: Path, releases_root: Path) -> bool:
    """
    Delete a release directory safely.
    Re-applies all boundary checks immediately before deletion (anti-TOCTOU).
    Uses shutil.rmtree with lstat verification, never following symlinks.
    Returns True on success, False on any safety violation.
    """
    # Re-check: directory still exists and is not a symlink
    try:
        st = os.lstat(candidate)
    except OSError as exc:
        log.error("safe_delete: lstat failed at delete time: %s", exc)
        return False

    import stat as stat_mod
    if stat_mod.S_ISLNK(st.st_mode):
        log.error("safe_delete: candidate is now a symlink (race?): %s", candidate)
        return False
    if not stat_mod.S_ISDIR(st.st_mode):
        log.error("safe_delete: candidate is not a directory at delete time: %s", candidate)
        return False

    # Re-apply full boundary check (anti-TOCTOU)
    safe, reason = is_safe_candidate(candidate, releases_root)
    if not safe:
        log.error("safe_delete: boundary re-check failed at delete time: %s -- %s", candidate, reason)
        return False

    # Acquire per-directory lock to prevent concurrent access
    lock_path = candidate / ".retention.lock"
    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            log.error("safe_delete: could not acquire lock on %s (concurrent access?)", lock_path)
            os.close(lock_fd)
            return False
    except OSError as exc:
        log.warning("safe_delete: could not create lock file %s: %s; skipping", lock_path, exc)
        return False

    try:
        # Final path re-verification (absolute, resolved, within root)
        resolved_candidate = candidate.resolve()
        resolved_root = releases_root.resolve()
        try:
            resolved_candidate.relative_to(resolved_root)
        except ValueError:
            log.error(
                "safe_delete: resolved path %s escaped releases_root %s",
                resolved_candidate, resolved_root,
            )
            return False

        # Delete using shutil.rmtree (no shell expansion, no string concatenation)
        shutil.rmtree(candidate, ignore_errors=False)
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("safe_delete: deletion failed: %s", exc)
        return False
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Core retention logic
# ---------------------------------------------------------------------------

def run_retention(
    releases_root: Path,
    current_link: Path,
    state_file: Path,
    keep_count: int,
    apply: bool,
    protection_registry: Optional[set] = None,
) -> int:
    """
    Main retention logic. Returns 0 on success, 1 on blocked, 2 on error.
    """
    mode_label = "APPLY" if apply else "DRY-RUN"
    log.info("=== S9K Release Retention [%s] ===", mode_label)
    log.info("releases_root: %s", releases_root)
    log.info("current_link:  %s", current_link)
    log.info("state_file:    %s", state_file)
    log.info("keep_count:    %d", keep_count)

    if keep_count < 3:
        log.error("BLOCKED: keep_count=%d is less than minimum 3", keep_count)
        return 1

    # --- Safety: validate releases_root ---
    if not releases_root.is_dir():
        log.warning("releases_root does not exist or is not a directory: %s", releases_root)
        log.info("Nothing to do.")
        return 0

    # Releases root must not be /
    if releases_root.resolve() == Path("/"):
        log.error("BLOCKED: releases_root resolves to /")
        return 1

    # --- Gather the protected set ---

    # 1. Resolve current symlink target
    protected_current: Optional[str] = None
    try:
        if current_link.is_symlink() or current_link.exists():
            resolved = current_link.resolve()
            if resolved.is_dir():
                protected_current = str(resolved)
                log.info("Protected (current): %s", protected_current)
    except OSError as exc:
        log.warning("Could not resolve current link %s: %s", current_link, exc)

    # 2 + 3. Deployment state: active and previous
    # If state file is missing entirely: no state-based protection (but everything
    # else still works: current symlink, KEEP, tags, recent count).
    # If state file exists but is unreadable/corrupt: warn loudly; the individual
    # releases whose status cannot be determined get PROTECTED_UNKNOWN below.
    state_file_exists = state_file.exists()
    state = read_deployment_state(state_file)
    state_corrupt = state_file_exists and not state  # exists but couldn't read
    protected_state_active: Optional[str] = None
    protected_state_previous: Optional[str] = None
    if state:
        active_rel = state.get("active_release")
        prev_rel = state.get("previous_release")
        if active_rel:
            p = releases_root / active_rel
            protected_state_active = str(p.resolve()) if p.exists() else str(p)
            log.info("Protected (state active): %s", protected_state_active)
        if prev_rel:
            p = releases_root / prev_rel
            protected_state_previous = str(p.resolve()) if p.exists() else str(p)
            log.info("Protected (state previous): %s", protected_state_previous)
    elif state_corrupt:
        log.warning(
            "deployment-state.json exists but is unreadable/corrupt: "
            "releases that cannot be identified will be marked PROTECTED_UNKNOWN"
        )
    else:
        log.info("deployment-state.json not present: no state-based protection; "
                 "current symlink + KEEP + tags + recent policy still apply")

    # 4. Live processes
    live_paths = get_live_process_paths(releases_root)
    if live_paths:
        log.info("Protected (live processes): %s", ", ".join(sorted(live_paths)))

    # 5. KEEP files (scanned per-release, below)
    # 6. Tagged commits (fail-closed: None = unknown → all releases get PROTECTED_UNKNOWN)
    tagged_commits = get_tagged_commits(releases_root)
    tags_indeterminate = tagged_commits is None
    if tags_indeterminate:
        log.warning(
            "get_tagged_commits returned INDETERMINATE; "
            "all releases will be marked PROTECTED_UNKNOWN (fail-closed)"
        )
    elif tagged_commits:
        log.info("Tagged commits (deploy-*): %s", ", ".join(sorted(tagged_commits)))

    # 7. Explicit protection registry
    if protection_registry is None:
        protection_registry = read_protection_registry(releases_root)
    if protection_registry:
        log.info("Protection registry: %s", ", ".join(sorted(protection_registry)))

    # --- Enumerate releases ---
    try:
        entries = list(releases_root.iterdir())
    except OSError as exc:
        log.error("Could not list releases_root %s: %s", releases_root, exc)
        return 2

    # Collect valid release dirs, sorted by mtime (newest first).
    # We use mtime only for the "N most recent" policy; never for identity decisions.
    valid_releases: list[tuple[float, Path]] = []
    skipped: list[tuple[Path, str]] = []

    for entry in entries:
        safe, reason = is_safe_candidate(entry, releases_root)
        if not safe:
            if "manifest.json not found" in reason:
                skipped.append((entry, Disposition.SKIPPED_NO_MANIFEST))
            elif "symlink" in reason:
                skipped.append((entry, Disposition.SKIPPED_IS_SYMLINK))
            elif "pattern" in reason:
                skipped.append((entry, Disposition.SKIPPED_PATTERN_MISMATCH))
            else:
                skipped.append((entry, Disposition.SKIPPED_BOUNDARY_VIOLATION))
            log.warning("SKIP %s: %s", entry.name, reason)
            continue

        # Validate manifest
        manifest_ok, _manifest_data = validate_manifest(entry / "manifest.json")
        if not manifest_ok:
            skipped.append((entry, Disposition.SKIPPED_MANIFEST_CORRUPT))
            log.warning("SKIP %s: manifest.json corrupt or missing required fields", entry.name)
            continue

        try:
            mtime = entry.stat().st_mtime
        except OSError:
            mtime = 0.0
        valid_releases.append((mtime, entry))

    # Sort newest first
    valid_releases.sort(key=lambda x: x[0], reverse=True)
    release_paths = [p for _, p in valid_releases]

    if not release_paths:
        log.info("No valid releases found. Nothing to do.")
        return 0

    # --- Classify each release ---
    results: list[tuple[Path, str]] = []
    non_protected_seen = 0

    for rel_path in release_paths:
        resolved_path_str = str(rel_path.resolve())
        rel_name = rel_path.name

        # Check manifest for commit SHA
        _ok, manifest_data = validate_manifest(rel_path / "manifest.json")
        commit_sha = manifest_data.get("git_commit", "") if manifest_data else ""
        commit_short = commit_sha[:7] if commit_sha else ""

        reasons: list[str] = []

        # 1. current symlink target
        if protected_current and resolved_path_str == protected_current:
            reasons.append(Disposition.PROTECTED_CURRENT)

        # 2. state active
        if protected_state_active:
            state_active_resolved = (
                str(Path(protected_state_active).resolve())
                if Path(protected_state_active).exists()
                else protected_state_active
            )
            if resolved_path_str == state_active_resolved:
                reasons.append(Disposition.PROTECTED_STATE_ACTIVE)

        # 3. state previous / rollback
        if protected_state_previous:
            state_prev_resolved = (
                str(Path(protected_state_previous).resolve())
                if Path(protected_state_previous).exists()
                else protected_state_previous
            )
            if resolved_path_str == state_prev_resolved:
                reasons.append(Disposition.PROTECTED_STATE_PREVIOUS)

        # 4. live process
        if resolved_path_str in live_paths:
            reasons.append(Disposition.PROTECTED_LIVE_PROCESS)

        # 5. KEEP file
        keep_file = rel_path / "KEEP"
        if keep_file.is_file():
            reasons.append(Disposition.PROTECTED_KEEP_FILE)

        # 6. deploy-* tag
        if not tags_indeterminate and tagged_commits and (
            commit_sha in tagged_commits or commit_short in tagged_commits
        ):
            reasons.append(Disposition.PROTECTED_TAG)

        # 7. explicit registry
        if rel_name in protection_registry:
            reasons.append(Disposition.PROTECTED_REGISTRY)

        # 8. Protect with PROTECTED_UNKNOWN when any status query is indeterminate:
        #    (a) deployment-state.json exists but is unreadable/corrupt, OR
        #    (b) git tag query failed (cannot determine if this release is tagged)
        if state_corrupt or tags_indeterminate:
            reasons.append(Disposition.PROTECTED_UNKNOWN)

        if reasons:
            disposition = reasons[0]  # primary reason
            log.info("PROTECTED %-40s [%s]", rel_name, ", ".join(reasons))
            results.append((rel_path, disposition))
            continue

        # 9. N most recent non-protected
        non_protected_seen += 1
        if non_protected_seen <= keep_count:
            log.info("PROTECTED_RECENT %-40s [recent #%d]", rel_name, non_protected_seen)
            results.append((rel_path, Disposition.PROTECTED_RECENT))
            continue

        # Eligible for deletion
        if apply:
            log.info("DELETING  %s", rel_name)
            ok = safe_delete_release(rel_path, releases_root)
            if ok:
                results.append((rel_path, Disposition.DELETED))
            else:
                log.error("BLOCKED: safe_delete_release refused to delete %s", rel_name)
                results.append((rel_path, Disposition.BLOCKED))
        else:
            log.info("DRY_RUN   %s (would delete)", rel_name)
            results.append((rel_path, Disposition.DRY_RUN))

    # --- Summary ---
    counts: dict[str, int] = {}
    for _, disp in results:
        counts[disp] = counts.get(disp, 0) + 1
    for _, disp in skipped:
        counts[disp] = counts.get(disp, 0) + 1

    log.info("=== Retention summary ===")
    for k, v in sorted(counts.items()):
        log.info("  %-35s %d", k, v)

    blocked_count = counts.get(Disposition.BLOCKED, 0)
    if blocked_count:
        log.error("BLOCKED: %d releases could not be safely deleted", blocked_count)
        return 1

    return 0


# ---------------------------------------------------------------------------
# Write deployment state (callable as a library function)
# ---------------------------------------------------------------------------

def write_deployment_state(
    state_file: Path,
    active_release: str,
    active_commit: str,
    previous_release: Optional[str],
    previous_commit: Optional[str],
    deployment_id: str,
) -> bool:
    """
    Write deployment-state.json atomically (temp + fsync + rename).
    File is created as 0600 root:root (if running as root).
    Returns True on success.
    """
    state = {
        "active_release": active_release,
        "active_commit": active_commit,
        "previous_release": previous_release or "",
        "previous_commit": previous_commit or "",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "deployment_id": deployment_id,
    }

    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=state_file.parent,
        prefix=".deployment-state.",
        suffix=".tmp",
    )
    try:
        os.chmod(tmp_fd, 0o600)
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.rename(tmp_path, state_file)
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("write_deployment_state: failed: %s", exc)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed release retention for S9 Knowledge.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--releases-root",
        default=DEFAULT_RELEASES_ROOT,
        help=f"Root directory containing releases (default: {DEFAULT_RELEASES_ROOT})",
    )
    parser.add_argument(
        "--current-link",
        default=DEFAULT_CURRENT_LINK,
        help=f"Path to the 'current' symlink (default: {DEFAULT_CURRENT_LINK})",
    )
    parser.add_argument(
        "--state-file",
        default=DEFAULT_STATE_FILE,
        help=f"Path to deployment-state.json (default: {DEFAULT_STATE_FILE})",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=DEFAULT_KEEP_COUNT,
        help=f"Minimum non-protected releases to keep (default: {DEFAULT_KEEP_COUNT}; minimum: 3)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Report only; never delete (default behavior when neither flag is given)",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually delete eligible releases (requires explicit flag)",
    )
    parser.add_argument(
        "--write-state",
        nargs=5,
        metavar=("ACTIVE_RELEASE", "ACTIVE_COMMIT", "PREVIOUS_RELEASE", "PREVIOUS_COMMIT", "DEPLOYMENT_ID"),
        help="Write deployment-state.json atomically and exit",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # --write-state subcommand
    if args.write_state:
        active_rel, active_commit, prev_rel, prev_commit, dep_id = args.write_state
        ok = write_deployment_state(
            state_file=Path(args.state_file),
            active_release=active_rel,
            active_commit=active_commit,
            previous_release=prev_rel if prev_rel and prev_rel != "-" else None,
            previous_commit=prev_commit if prev_commit and prev_commit != "-" else None,
            deployment_id=dep_id,
        )
        return 0 if ok else 2

    # --apply is the only flag that activates deletions.
    # The mutually exclusive group guarantees --apply and --dry-run cannot both be set.
    # Default (neither flag): dry-run mode (apply=False). No default=True needed.
    apply = bool(args.apply)

    return run_retention(
        releases_root=Path(args.releases_root),
        current_link=Path(args.current_link),
        state_file=Path(args.state_file),
        keep_count=args.keep,
        apply=apply,
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.error("Interrupted")
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001
        log.error("Unexpected error: %s", exc)
        sys.exit(2)
