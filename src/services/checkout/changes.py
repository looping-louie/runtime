"""Collect bounded local checkout changes for API checkpoints."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .repository import run_git


MAX_REVIEW_FILES = 120
MAX_REVIEW_FILE_CHARS = 120_000
MAX_TOTAL_REVIEW_CHARS = 1_200_000


def get_git_diff(checkout_path: Path) -> str:
    """Return the current checkout diff, including untracked files."""

    tracked_diff = run_git(checkout_path, 'diff', '--binary', 'HEAD')
    untracked_diff = ''.join(
        _untracked_file_diff(checkout_path, relative_path)
        for relative_path in _untracked_files(checkout_path)
    )
    return f'{tracked_diff}{untracked_diff}'


def get_changed_files(checkout_path: Path) -> list[str]:
    """Return checkout paths changed from HEAD, including untracked files."""

    tracked_files = run_git(checkout_path, 'diff', '--name-only', 'HEAD').splitlines()
    return sorted({*tracked_files, *_untracked_files(checkout_path)})


def read_changed_file_contents(
    checkout_path: Path,
    changed_files: list[str],
) -> dict[str, str]:
    """Return bounded UTF-8 content for changed files supplied to reviewers."""

    root = checkout_path.resolve()
    contents: dict[str, str] = {}
    total_chars = 0
    for relative_path in changed_files[:MAX_REVIEW_FILES]:
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        try:
            content = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        if len(content) > MAX_REVIEW_FILE_CHARS:
            content = f'{content[:MAX_REVIEW_FILE_CHARS]}\n\n[TRUNCATED]'
        if total_chars + len(content) > MAX_TOTAL_REVIEW_CHARS:
            break
        contents[relative_path] = content
        total_chars += len(content)
    return contents


def _untracked_files(checkout_path: Path) -> list[str]:
    """Return non-ignored untracked paths without altering the Git index."""

    return run_git(checkout_path, 'ls-files', '--others', '--exclude-standard').splitlines()


def _untracked_file_diff(checkout_path: Path, relative_path: str) -> str:
    """Return a binary diff for one untracked file without staging it."""

    result = subprocess.run(
        [
            'git', '-C', str(checkout_path), 'diff', '--no-index', '--binary',
            '--', '/dev/null', relative_path,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode in (0, 1):
        return result.stdout
    detail = result.stderr.strip() or result.stdout.strip()
    raise RuntimeError(f'Git command failed: {detail or "unknown error"}')