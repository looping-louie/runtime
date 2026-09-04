"""Tests for the local Copilot CLI Harness adapter."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harnesses.copilot_cli import executor as copilot_cli
from tests.harness_fixtures import copilot_activity


@pytest.fixture(autouse=True)
def stable_observation_clocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make timestamps, duration, and Git heads deterministic in adapter tests."""

    timestamps = iter((
        datetime(2026, 9, 4, 10, 0, tzinfo=UTC),
        datetime(2026, 9, 4, 10, 0, 0, 250000, tzinfo=UTC),
    ))
    ticks = iter((10.0, 10.25))
    monkeypatch.setattr(copilot_cli, '_utc_now', lambda: next(timestamps))
    monkeypatch.setattr(copilot_cli, '_monotonic', lambda: next(ticks))
    monkeypatch.setattr(copilot_cli, 'get_head_sha', lambda _path: 'source-sha')
    monkeypatch.setattr(copilot_cli, '_checkout_state', lambda _path: ('source-sha', '', []))


def test_execute_copilot_cli_reports_completed_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A successful Copilot JSONL turn reports its response and checkout changes."""

    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """Return a deterministic Copilot JSONL response without starting a process."""

        calls.append((command, kwargs))
        assert (tmp_path / '.github' / 'skills' / 'api-compatibility' / 'SKILL.md').is_file()
        return subprocess.CompletedProcess(command, 0, '\n'.join((
            json.dumps({'type': 'assistant.message', 'data': {
                'content': json.dumps({
                    'final_response': 'Done.',
                    'commit_message': 'feat: complete requested change',
                }),
            }}),
            json.dumps({'type': 'result', 'sessionId': 'session-1', 'exitCode': 0,
                        'usage': {'premiumRequests': 1}}),
        )), '')

    monkeypatch.setattr(copilot_cli.subprocess, 'run', run)
    monkeypatch.setattr(copilot_cli, '_checkout_state', lambda _path: (
        'source-sha', 'diff --git a/a b/a', ['a.txt'],
    ))

    result = copilot_cli.execute_copilot_cli(copilot_activity('Create a file.'), tmp_path)

    assert calls[0][0] == [
        'copilot', '--allow-all-tools', '--no-ask-user', '--output-format', 'json',
        '--stream', 'off', '--model', 'gpt-5.6-terra', '--prompt', calls[0][0][-1],
    ]
    assert 'Persona instructions:\nMake the smallest coherent implementation.' in calls[0][0][-1]
    assert calls[0][1].get('input') is None
    assert not (tmp_path / '.github' / 'skills' / 'api-compatibility').exists()
    assert result == {
        'action': 'run_harness', 'schema_version': 'v1',
        'harness': {'kind': 'copilot_cli', 'version': 'v1', 'config': {}},
        'completed': True, 'started_at': '2026-09-04T10:00:00+00:00',
        'completed_at': '2026-09-04T10:00:00.250000+00:00', 'duration_ms': 250,
        'final_response': 'Done.', 'requested_model': 'gpt-5.6-terra',
        'actual_model': 'gpt-5.6-terra', 'reasoning_effort': None,
        'session_reference': 'session-1', 'usage': {'premiumRequests': 1},
        'exit_code': 0, 'diagnostics': [], 'materialized_skills': [{
            'id': 'skill-api', 'name': 'api-compatibility', 'version': 3,
        }], 'source_commit_sha': 'source-sha', 'final_commit_sha': 'source-sha',
        'final_diff': 'diff --git a/a b/a', 'changed_files': ['a.txt'],
        'commit_message': 'feat: complete requested change',
    }