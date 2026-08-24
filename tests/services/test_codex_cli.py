"""Tests for the local Codex CLI Harness adapter."""

from __future__ import annotations

import subprocess
from pathlib import Path

from services import codex_cli


def test_execute_codex_cli_reports_completed_turn(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """A successful JSONL Codex turn reports its response and checkout changes."""

    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """Return a deterministic Codex JSONL response without starting a process."""

        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=(
                '{"type":"thread.started","thread_id":"thread-1"}\n'
                '{"type":"item.completed","item":{"type":"agent_message","text":"Done."}}\n'
                '{"type":"turn.completed","usage":{"input_tokens":2,"output_tokens":3}}\n'
            ),
            stderr='',
        )

    monkeypatch.setattr(codex_cli.subprocess, 'run', run)
    monkeypatch.setattr(codex_cli, 'get_git_diff', lambda _path: 'diff --git a/a b/a')
    monkeypatch.setattr(codex_cli, 'get_changed_files', lambda _path: ['a.txt'])

    result = codex_cli.execute_codex_cli(
        {
            'input': 'Create a file.',
            'payload': {
                'harness': {'kind': 'codex_cli', 'version': 'v1', 'config': {}},
                'repo_context': 'Repository context.',
                'constitution': '',
                'project_profile': {},
            },
        },
        tmp_path,
    )

    assert calls[0][0] == ['codex', 'exec', '--json', '--sandbox', 'workspace-write', '-']
    assert result == {
        'action': 'run_harness',
        'completed': True,
        'final_response': 'Done.',
        'final_diff': 'diff --git a/a b/a',
        'changed_files': ['a.txt'],
        'usage': {'input_tokens': 2, 'output_tokens': 3},
        'diagnostics': [],
        'session_reference': 'thread-1',
    }
