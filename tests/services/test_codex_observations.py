"""Tests for durable Codex CLI observations on success and failure."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harnesses.codex_cli import executor as codex_cli
from harnesses.codex_cli.observations import (
    enrich_with_session_settings,
    parse_codex_events,
)
from tests.contract_fixtures import load_harness_observation


def instruction_snapshot() -> dict[str, object]:
    """Build one immutable Persona and Skill snapshot for a failed turn."""

    return {
        'snapshot_version': 1,
        'persona': {'content': 'Implement carefully.'},
        'skills': [{
            'id': 'skill-api',
            'name': 'API Compatibility',
            'description': 'Preserve contracts.',
            'content': 'Keep the API compatible.',
            'version': 3,
        }],
    }


def test_session_context_supplies_actual_model_and_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Local Codex session metadata completes fields absent from public JSONL."""

    session_id = '0199a213-81c0-7800-8aa1-bbab2a035a53'
    session_dir = tmp_path / 'sessions' / '2026' / '08' / '31'
    session_dir.mkdir(parents=True)
    session_file = session_dir / f'rollout-2026-08-31T10-00-00-{session_id}.jsonl'
    session_file.write_text(json.dumps({
        'type': 'turn_context',
        'payload': {'model': 'gpt-5.1-codex', 'effort': 'high'},
    }) + '\n', encoding='utf-8')
    monkeypatch.setenv('CODEX_HOME', str(tmp_path))

    observations = enrich_with_session_settings(parse_codex_events(
        json.dumps({'type': 'thread.started', 'thread_id': session_id}) + '\n'
    ))

    assert observations.actual_model == 'gpt-5.1-codex'
    assert observations.reasoning_effort == 'high'


def test_failed_process_keeps_partial_session_tokens_and_checkout_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A non-zero exit still reports every observation emitted before failure."""

    timestamps = iter((
        datetime(2026, 8, 31, 10, 0, tzinfo=UTC),
        datetime(2026, 8, 31, 10, 0, 1, tzinfo=UTC),
    ))
    ticks = iter((20.0, 21.0))
    monkeypatch.setattr(codex_cli, '_utc_now', lambda: next(timestamps))
    monkeypatch.setattr(codex_cli, '_monotonic', lambda: next(ticks))
    monkeypatch.setattr(codex_cli, 'get_head_sha', lambda _path: 'source-sha')
    monkeypatch.setattr(codex_cli, 'get_git_diff', lambda _path: 'partial diff')
    monkeypatch.setattr(codex_cli, 'get_changed_files', lambda _path: ['partial.py'])

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        """Return a failed process with useful JSONL already written."""

        stdout = '\n'.join((
            json.dumps({'type': 'thread.started', 'thread_id': 'thread-partial'}),
            json.dumps({
                'type': 'turn.failed',
                'message': 'Codex emitted a partial response.',
                'usage': {
                    'input_tokens': 10,
                    'cached_input_tokens': 4,
                    'output_tokens': 3,
                    'reasoning_output_tokens': 2,
                },
            }),
        )) + '\n'
        return subprocess.CompletedProcess(command, 17, stdout=stdout, stderr='boom')

    monkeypatch.setattr(codex_cli.subprocess, 'run', run)

    result = codex_cli.execute_codex_cli({
        'input': 'Implement.',
        'payload': {
            'harness': {'kind': 'codex_cli', 'version': 'v1', 'config': {}},
            'requested_model': 'gpt-5-codex',
            'instruction_snapshot': instruction_snapshot(),
        },
    }, tmp_path)

    assert result == {
        'action': 'run_harness',
        **load_harness_observation('codex_cli_v1_failed.json'),
    }
