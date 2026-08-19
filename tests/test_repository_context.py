"""Tests for read-only repository context collection."""

from __future__ import annotations

import subprocess
from pathlib import Path

from services.git.repository_context import get_changed_files, get_git_diff


def _git(checkout_path: Path, *arguments: str) -> str:
    """Run one successful Git command in a temporary checkout."""

    result = subprocess.run(
        ['git', '-C', str(checkout_path), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_context_includes_untracked_files_without_changing_git_index(tmp_path: Path) -> None:
    """Untracked review context does not stage intent-to-add entries."""

    checkout_path = tmp_path / 'checkout'
    checkout_path.mkdir()
    _git(checkout_path, 'init')
    _git(checkout_path, 'config', 'user.name', 'Runtime Test')
    _git(checkout_path, 'config', 'user.email', 'runtime@example.com')
    (checkout_path / 'README.md').write_text('seed\n', encoding='utf-8')
    _git(checkout_path, 'add', 'README.md')
    _git(checkout_path, 'commit', '-m', 'seed')
    (checkout_path / 'new-file.txt').write_text('untracked\n', encoding='utf-8')

    changed_files = get_changed_files(checkout_path)
    diff = get_git_diff(checkout_path)

    assert changed_files == ['new-file.txt']
    assert 'new-file.txt' in diff
    assert _git(checkout_path, 'status', '--porcelain') == '?? new-file.txt\n'
