"""Inspect and mutate Git state in a configured checkout."""

from __future__ import annotations

import subprocess
from pathlib import Path


def get_head_sha(checkout_path: Path) -> str:
    """Return the configured checkout's current Git commit SHA."""

    return run_git(checkout_path, 'rev-parse', 'HEAD')


def get_current_branch(checkout_path: Path) -> str:
    """Return the current non-detached branch for one configured checkout."""

    return run_git(checkout_path, 'symbolic-ref', '--quiet', '--short', 'HEAD').strip()


def has_changes(checkout_path: Path) -> bool:
    """Return whether the checkout has staged, unstaged, or untracked changes."""

    return bool(run_git(checkout_path, 'status', '--porcelain').strip())


def commit_all(checkout_path: Path, message: str) -> str:
    """Stage and commit every pending checkout change, returning its new SHA."""

    run_git(checkout_path, 'add', '--all')
    run_git(checkout_path, 'commit', '-m', message)
    return get_head_sha(checkout_path)


def run_git(checkout_path: Path, *arguments: str) -> str:
    """Run one Git command and return stdout or raise a contextual error."""

    result = subprocess.run(
        ['git', '-C', str(checkout_path), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout
    detail = result.stderr.strip() or result.stdout.strip()
    raise RuntimeError(f'Git command failed: {detail or "unknown error"}')