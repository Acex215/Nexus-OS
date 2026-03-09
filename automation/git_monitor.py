#!/usr/bin/env python3
"""NEXUS OS CAF — Git Monitor

Tracks new commits in the NEXUS git repository and triggers incremental
re-indexing of changed files.

Public API:
    check_for_new_commits(repo_path)       -> list[str]
    get_changed_files(repo_path, commit)   -> list[str]
    trigger_incremental_reindex(files)     -> None
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("git_monitor")

# ── Constants ──────────────────────────────────────────────────────────────────

DEFAULT_REPO_PATH = "/opt/nexus"
STATE_FILE        = "/opt/nexus/automation/.git_monitor_state"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _git(repo_path: str, *args: str, timeout: int = 30) -> Optional[str]:
    """Run a git command in repo_path. Returns stdout on success, None on error."""
    cmd = ["git", "-C", repo_path, *args]
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if r.returncode == 0:
            return r.stdout.strip()
        log.debug("git %s exited %d: %s", " ".join(args), r.returncode,
                  r.stderr.strip()[:120])
        return None
    except subprocess.TimeoutExpired:
        log.warning("git %s timed out", " ".join(args[:2]))
        return None
    except Exception as e:
        log.warning("git error: %s", e)
        return None


def _read_state() -> Optional[str]:
    """Return last-checked commit hash, or None if state file is absent/empty."""
    p = Path(STATE_FILE)
    if p.exists():
        val = p.read_text().strip()
        return val if val else None
    return None


def _write_state(commit_hash: str) -> None:
    Path(STATE_FILE).write_text(commit_hash)


# ── Public API ─────────────────────────────────────────────────────────────────

def check_for_new_commits(repo_path: str = DEFAULT_REPO_PATH) -> list[str]:
    """Return list of new commit hashes since last check.

    Uses STATE_FILE to remember the last-checked HEAD.
    Updates STATE_FILE to current HEAD after each call.
    Returns an empty list if the repo is unreachable or has no new commits.
    """
    current_head = _git(repo_path, "rev-parse", "HEAD")
    if not current_head:
        log.warning("check_for_new_commits: cannot read HEAD from %s", repo_path)
        return []

    last_hash = _read_state()

    if not last_hash:
        # First run — record current HEAD and return no commits (baseline)
        log.info("git_monitor: baseline set to %s", current_head[:12])
        _write_state(current_head)
        return []

    if last_hash == current_head:
        # No change
        return []

    raw = _git(repo_path, "log", f"{last_hash}..HEAD", "--format=%H")
    if raw is None:
        # Range error (e.g. last_hash was pruned) — reset baseline
        log.warning("git_monitor: range %s..HEAD failed; resetting baseline", last_hash[:12])
        _write_state(current_head)
        return []

    commits = [line.strip() for line in raw.splitlines() if line.strip()]
    if commits:
        log.info("git_monitor: %d new commit(s) since %s", len(commits), last_hash[:12])
        _write_state(current_head)

    return commits


def get_changed_files(repo_path: str, commit_hash: str) -> list[str]:
    """Return list of file paths changed by a single commit."""
    raw = _git(
        repo_path,
        "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash,
    )
    if not raw:
        return []
    return [f.strip() for f in raw.splitlines() if f.strip()]


def trigger_incremental_reindex(changed_files: list[str]) -> None:
    """Re-index only the changed files via the CAF indexer.

    Groups files by parent directory and calls the indexer with --dir for each
    unique parent. Skips files that don't exist on disk (deleted/renamed).
    """
    if not changed_files:
        return

    # Resolve absolute paths and collect unique parent directories
    dirs_to_index: set[str] = set()
    for rel_path in changed_files:
        abs_path = Path("/opt/nexus") / rel_path
        if abs_path.exists() and abs_path.is_file():
            dirs_to_index.add(str(abs_path.parent))

    if not dirs_to_index:
        log.debug("trigger_incremental_reindex: no existing files to index")
        return

    indexer = "/opt/nexus/automation/indexer.py"
    for directory in sorted(dirs_to_index):
        log.info("trigger_incremental_reindex: indexing %s", directory)
        try:
            subprocess.Popen(
                ["python3", indexer, "--dir", directory],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            log.warning("trigger_incremental_reindex: failed for %s: %s", directory, e)
