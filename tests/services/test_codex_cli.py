"""Tests for the local Codex CLI Harness adapter."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from harnesses.codex_cli import executor as codex_cli


def instruction_snapshot() -> dict[str, object]:
    """Build one immutable Persona and Skill snapshot from the API."""

    return {
        'snapshot_version': 1,
        'persona': {
            'id': 'persona-1',
            'name': 'Implementer',
            'content': 'Make the smallest coherent implementation.',
        },
        'skills': [
            {
                'id': 'skill-api',
                'name': 'API Compatibility',
                'description': 'Preserve existing API contracts.',
                'content': 'Keep public API contracts backwards compatible.',
            },
        ],
    }


def completed_events(completion: dict[str, str]) -> str:
    """Build Codex JSONL events around one structured final response."""

    return '\n'.join((
        json.dumps({'type': 'thread.started', 'thread_id': 'thread-1'}),
        json.dumps({
            'type': 'item.completed',
            'item': {
                'type': 'agent_message',
                'text': json.dumps(completion),
            },
        }),
        json.dumps({
            'type': 'turn.completed',
            'usage': {'input_tokens': 2, 'output_tokens': 3},
        }),
    )) + '\n'


def test_execute_codex_cli_reports_completed_turn(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """A successful JSONL Codex turn reports its response and checkout changes."""

    calls: list[tuple[list[str], dict[str, object]]] = []
    materialized_documents: list[str] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """Return a deterministic Codex JSONL response without starting a process."""

        calls.append((command, kwargs))
        materialized_documents.append(
            (tmp_path / '.agents' / 'skills' / 'api-compatibility' / 'SKILL.md')
            .read_text(encoding='utf-8')
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=completed_events({
                'final_response': 'Done.',
                'commit_message': 'feat: complete requested change',
            }),
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
                'commit_mode': 'allow',
                'instruction_snapshot': instruction_snapshot(),
                'repo_context': 'Repository context.',
                'constitution': '',
                'project_profile': {},
            },
        },
        tmp_path,
    )

    assert calls[0][0] == ['codex', 'exec', '--json', '--sandbox', 'workspace-write', '-']
    assert 'Persona instructions:\nMake the smallest coherent implementation.' in calls[0][1]['input']
    assert 'Apply these run-scoped Skills when relevant: $api-compatibility' in calls[0][1]['input']
    assert 'Do not run git commit or otherwise create a commit.' in calls[0][1]['input']
    assert '"commit_message": "feat: concise description"' in calls[0][1]['input']
    assert materialized_documents == [
        '---\n'
        'name: api-compatibility\n'
        'description: "Preserve existing API contracts."\n'
        '---\n\n'
        'Keep public API contracts backwards compatible.\n'
    ]
    assert not (tmp_path / '.agents' / 'skills' / 'api-compatibility').exists()
    assert result == {
        'action': 'run_harness',
        'completed': True,
        'final_response': 'Done.',
        'commit_message': 'feat: complete requested change',
        'final_diff': 'diff --git a/a b/a',
        'changed_files': ['a.txt'],
        'usage': {'input_tokens': 2, 'output_tokens': 3},
        'diagnostics': [],
        'session_reference': 'thread-1',
    }


def test_execute_codex_cli_removes_materialized_skills_after_failure(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """Run-scoped Skill files are removed when the Codex process fails."""

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        """Observe the temporary Skill and return a failed Codex process."""

        skill_path = tmp_path / '.agents' / 'skills' / 'api-compatibility' / 'SKILL.md'
        assert skill_path.is_file()
        return subprocess.CompletedProcess(command, 1, stdout='', stderr='Codex failed.')

    monkeypatch.setattr(codex_cli.subprocess, 'run', run)

    result = codex_cli.execute_codex_cli(
        {
            'input': 'Create a file.',
            'payload': {
                'harness': {'kind': 'codex_cli', 'version': 'v1', 'config': {}},
                'instruction_snapshot': instruction_snapshot(),
            },
        },
        tmp_path,
    )

    assert result == {
        'action': 'run_harness',
        'completed': False,
        'error': 'Codex failed.',
    }
    assert not (tmp_path / '.agents' / 'skills' / 'api-compatibility').exists()


def test_execute_codex_cli_preserves_an_existing_project_skill(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """A run refuses to overwrite a checkout-owned Skill with the same name."""

    skill_path = tmp_path / '.agents' / 'skills' / 'api-compatibility'
    skill_path.mkdir(parents=True)
    existing_document = skill_path / 'SKILL.md'
    existing_document.write_text('Existing project Skill.\n', encoding='utf-8')
    calls: list[list[str]] = []

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        """Record an unexpected subprocess invocation."""

        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout='', stderr='')

    monkeypatch.setattr(codex_cli.subprocess, 'run', run)

    result = codex_cli.execute_codex_cli(
        {
            'input': 'Create a file.',
            'payload': {
                'harness': {'kind': 'codex_cli', 'version': 'v1', 'config': {}},
                'instruction_snapshot': instruction_snapshot(),
            },
        },
        tmp_path,
    )

    assert result['completed'] is False
    assert 'already exists' in str(result['error'])
    assert existing_document.read_text(encoding='utf-8') == 'Existing project Skill.\n'
    assert calls == []


def test_execute_codex_cli_rejects_a_symlinked_agents_directory(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """Run-scoped Skills cannot escape the checkout through `.agents`."""

    outside = tmp_path / 'outside'
    outside.mkdir()
    (tmp_path / '.agents').symlink_to(outside, target_is_directory=True)
    calls: list[list[str]] = []

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        """Record an unexpected subprocess invocation."""

        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout='', stderr='')

    monkeypatch.setattr(codex_cli.subprocess, 'run', run)

    result = codex_cli.execute_codex_cli(
        {
            'input': 'Create a file.',
            'payload': {
                'harness': {'kind': 'codex_cli', 'version': 'v1', 'config': {}},
                'instruction_snapshot': instruction_snapshot(),
            },
        },
        tmp_path,
    )

    assert result['completed'] is False
    assert 'not a directory' in str(result['error'])
    assert list(outside.iterdir()) == []
    assert calls == []


def test_execute_codex_cli_rejects_missing_commit_message(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """An allowed turn fails when Codex omits its commit proposal."""

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        """Return a successful turn without the required commit message."""

        return subprocess.CompletedProcess(
            command,
            0,
            stdout=completed_events({'final_response': 'Done.'}),
            stderr='',
        )

    monkeypatch.setattr(codex_cli.subprocess, 'run', run)

    result = codex_cli.execute_codex_cli(
        {
            'input': 'Create a file.',
            'payload': {
                'harness': {'kind': 'codex_cli', 'version': 'v1', 'config': {}},
                'commit_mode': 'allow',
                'instruction_snapshot': instruction_snapshot(),
            },
        },
        tmp_path,
    )

    assert result['completed'] is False
    assert 'expected commit_message, final_response' in str(result['error'])


def test_execute_codex_cli_accepts_no_message_when_commit_is_forbidden(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """A forbidden turn reports completion without inventing a commit message."""

    calls: list[dict[str, object]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """Return the structured completion allowed by forbid mode."""

        calls.append(kwargs)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=completed_events({'final_response': 'Done without commit.'}),
            stderr='',
        )

    monkeypatch.setattr(codex_cli.subprocess, 'run', run)
    monkeypatch.setattr(codex_cli, 'get_git_diff', lambda _path: '')
    monkeypatch.setattr(codex_cli, 'get_changed_files', lambda _path: [])

    result = codex_cli.execute_codex_cli(
        {
            'input': 'Inspect the project.',
            'payload': {
                'harness': {'kind': 'codex_cli', 'version': 'v1', 'config': {}},
                'commit_mode': 'forbid',
                'instruction_snapshot': instruction_snapshot(),
            },
        },
        tmp_path,
    )

    assert result['completed'] is True
    assert result['final_response'] == 'Done without commit.'
    assert 'commit_message' not in result
    assert 'commit_message' not in str(calls[0]['input'])
