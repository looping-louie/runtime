"""Tests for the local Codex CLI Harness adapter."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harnesses.codex_cli import executor as codex_cli
from tests.contract_fixtures import load_harness_observation
from tests.harness_fixtures import codex_activity


@pytest.fixture(autouse=True)
def stable_observation_clocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make timestamps, duration, and Git heads deterministic in adapter tests."""

    timestamps = iter((
        datetime(2026, 8, 31, 10, 0, tzinfo=UTC),
        datetime(2026, 8, 31, 10, 0, 0, 250000, tzinfo=UTC),
    ))
    ticks = iter((10.0, 10.25))
    monkeypatch.setattr(codex_cli, '_utc_now', lambda: next(timestamps))
    monkeypatch.setattr(codex_cli, '_monotonic', lambda: next(ticks))
    monkeypatch.setattr(codex_cli, 'get_head_sha', lambda _path: 'source-sha')
    monkeypatch.setattr(codex_cli, 'get_git_diff', lambda _path: '')
    monkeypatch.setattr(codex_cli, 'get_changed_files', lambda _path: [])


def completed_events(
    completion: dict[str, object],
    *,
    actual_model: str | None = None,
) -> str:
    """Build Codex JSONL events around one structured final response."""

    thread_started = {'type': 'thread.started', 'thread_id': 'thread-1'}
    if actual_model is not None:
        thread_started['model'] = actual_model
    return '\n'.join((
        json.dumps(thread_started),
        json.dumps({
            'type': 'item.completed',
            'item': {
                'type': 'agent_message',
                'text': json.dumps(completion),
            },
        }),
        json.dumps({
            'type': 'turn.completed',
            'usage': {
                'input_tokens': 2,
                'cached_input_tokens': 1,
                'output_tokens': 3,
                'total_tokens': 5,
            },
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
            stdout=completed_events(
                {
                    'final_response': 'Done.',
                    'commit_message': 'feat: complete requested change',
                },
                actual_model='gpt-5.1-codex',
            ),
            stderr='',
        )

    monkeypatch.setattr(codex_cli.subprocess, 'run', run)
    monkeypatch.setattr(codex_cli, 'get_git_diff', lambda _path: 'diff --git a/a b/a')
    monkeypatch.setattr(codex_cli, 'get_changed_files', lambda _path: ['a.txt'])

    result = codex_cli.execute_codex_cli(codex_activity(
        'Create a file.',
        commit_mode='allow',
        repo_context='Repository context.',
        constitution='',
        project_profile={},
    ), tmp_path)

    assert calls[0][0] == [
        'codex', 'exec', '--json', '--model', 'gpt-5-codex',
        '--sandbox', 'workspace-write', '-',
    ]
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
    expected = load_harness_observation('codex_cli_v1_completed.json')
    expected.pop('error')
    assert result == {'action': 'run_harness', **expected}


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

    result = codex_cli.execute_codex_cli(codex_activity('Create a file.'), tmp_path)

    assert result['completed'] is False
    assert result['error'] == 'Codex failed.'
    assert result['exit_code'] == 1
    assert result['source_commit_sha'] == 'source-sha'
    assert result['final_commit_sha'] == 'source-sha'
    assert result['materialized_skills'] == [{
        'id': 'skill-api',
        'name': 'api-compatibility',
        'version': 3,
    }]
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

    result = codex_cli.execute_codex_cli(codex_activity('Create a file.'), tmp_path)

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

    result = codex_cli.execute_codex_cli(codex_activity('Create a file.'), tmp_path)

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

    result = codex_cli.execute_codex_cli(codex_activity(
        'Create a file.', commit_mode='allow',
    ), tmp_path)

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

    result = codex_cli.execute_codex_cli(codex_activity(
        'Inspect the project.', commit_mode='forbid',
    ), tmp_path)

    assert result['completed'] is True
    assert result['final_response'] == 'Done without commit.'
    assert result['requested_model'] == 'gpt-5-codex'
    assert result['actual_model'] == 'gpt-5-codex'
    assert result['exit_code'] == 0
    assert 'commit_message' not in result
    assert 'commit_message' not in str(calls[0]['input'])


def test_execute_codex_cli_rejects_a_missing_requested_model(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """The runtime never falls back to the worker's local Codex model."""

    calls: list[list[str]] = []

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        """Record an unexpected subprocess invocation."""

        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout='', stderr='')

    monkeypatch.setattr(codex_cli.subprocess, 'run', run)

    result = codex_cli.execute_codex_cli(codex_activity(
        'Inspect the project.', requested_model=None,
    ), tmp_path)

    assert result['action'] == 'run_harness'
    assert result['completed'] is False
    assert result['error'] == 'Activity response is missing its requested model.'
    assert result['started_at'] == '2026-08-31T10:00:00+00:00'
    assert result['completed_at'] == '2026-08-31T10:00:00.250000+00:00'
    assert result['duration_ms'] == 250
    assert calls == []


@pytest.mark.parametrize(
    ('phase', 'completion', 'expected_output'),
    [
        ('proposal', {'proposal': 'Use the existing service.'}, {
            'proposal': 'Use the existing service.',
        }),
        ('review', {'approved': False, 'feedback': 'Add a boundary test.'}, {
            'approved': False, 'feedback': 'Add a boundary test.',
        }),
    ],
)
def test_execute_codex_cli_supports_read_only_loop_turns(
    monkeypatch: object,
    tmp_path: Path,
    phase: str,
    completion: dict[str, object],
    expected_output: dict[str, object],
) -> None:
    """Proposal and review turns use read-only Codex with structured output."""

    calls: list[tuple[list[str], str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """Capture the command and return the requested semantic result."""

        calls.append((command, str(kwargs['input'])))
        return subprocess.CompletedProcess(
            command, 0, stdout=completed_events(completion), stderr='',
        )

    monkeypatch.setattr(codex_cli.subprocess, 'run', run)
    response = codex_activity('Evaluate the task.', commit_mode='allow')
    response['payload']['turn'] = {
        'id': f'1:{phase}:agent-1',
        'phase': phase,
        'iteration': 1,
        'agent_id': 'agent-1',
        'role': 'reviewer' if phase == 'review' else 'generator',
        'workspace_access': 'read_only',
    }

    result = codex_cli.execute_codex_cli(response, tmp_path)

    assert calls[0][0][6] == 'read-only'
    assert 'commit_message' not in calls[0][1]
    assert result['completed'] is True
    assert result['turn_id'] == f'1:{phase}:agent-1'
    assert result['phase'] == phase
    assert result['output'] == expected_output
