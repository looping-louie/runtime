"""Tests for the Codex-to-runtime commit authorization handoff."""

from __future__ import annotations

import subprocess
from pathlib import Path

from runs.executor import ActivityExecutor
from runs.models import ClaimedPipelineRun


class CommitActivityClient:
    """Advance one Codex result through the API-authorized commit checkpoint."""

    def __init__(self) -> None:
        """Initialize the submitted checkpoint log."""

        self.continuations: list[dict[str, object]] = []

    def get_run(self, **_: str) -> dict[str, object]:
        """Return one pending Codex Harness checkpoint."""

        return {
            'status': 'in_progress',
            'next_action': 'run_harness',
            'continuation_token': 'continuation-1',
        }

    def continue_run(self, **payload: object) -> dict[str, object]:
        """Return the commit handoff after Codex and then complete the Activity."""

        self.continuations.append(payload)
        if len(self.continuations) == 1:
            result = payload['result']
            assert isinstance(result, dict)
            return {
                'status': 'in_progress',
                'next_action': 'commit_if_allowed',
                'continuation_token': 'continuation-2',
                'payload': {'commit_message': result['commit_message']},
            }
        return {'status': 'completed', 'next_action': 'none'}


class TerminalPipelineClient:
    """Accept lease renewals and complete the Pipeline after its child."""

    def renew_lease(self, **_: str) -> None:
        """Accept the fixture's lease renewal."""

    def continue_run(self, **_: str) -> dict[str, object]:
        """Return the terminal Pipeline state."""

        return {'status': 'completed', 'current_activity_run': None}


def test_codex_commit_message_is_used_only_after_api_handoff(tmp_path: Path) -> None:
    """Codex proposes a message and the later commit checkpoint performs Git."""

    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    _git(checkout, 'init')
    _git(checkout, 'config', 'user.name', 'Runtime Test')
    _git(checkout, 'config', 'user.email', 'runtime@example.com')
    (checkout / 'README.md').write_text('seed\n', encoding='utf-8')
    _git(checkout, 'add', 'README.md')
    _git(checkout, 'commit', '-m', 'seed')
    activity_client = CommitActivityClient()

    def run_harness(_: dict[str, object], __: Path) -> dict[str, object]:
        """Leave one Codex change uncommitted and propose its commit message."""

        (checkout / 'result.txt').write_text('implemented\n', encoding='utf-8')
        return {
            'action': 'run_harness',
            'completed': True,
            'final_response': 'Implemented the requested change.',
            'commit_message': 'feat: implement requested change',
        }

    executor = ActivityExecutor(
        activity_client=activity_client,
        pipeline_client=TerminalPipelineClient(),
        harness_runner=run_harness,
    )

    executor.execute_claim(_claim(), checkout)

    harness_result = activity_client.continuations[0]['result']
    commit_result = activity_client.continuations[1]['result']
    assert isinstance(harness_result, dict)
    assert harness_result['commit_message'] == 'feat: implement requested change'
    assert isinstance(commit_result, dict)
    assert commit_result['committed'] is True
    assert _git_output(checkout, 'log', '-1', '--pretty=%s') == (
        'feat: implement requested change'
    )


def _claim() -> ClaimedPipelineRun:
    """Build one claimed Pipeline with a current Codex Activity."""

    return ClaimedPipelineRun(
        project_id='project-1', pipeline_id='pipeline-1',
        run_id='pipeline-run-1', lease_token='lease-1',
        payload={
            'status': 'claimed',
            'current_activity_run': {
                'id': 'activity-run-1',
                'activity_id': 'activity-1',
            },
        },
    )


def _git(repo: Path, *arguments: str) -> None:
    """Run one successful Git command in the fixture checkout."""

    subprocess.run(
        ['git', '-C', str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


def _git_output(repo: Path, *arguments: str) -> str:
    """Return stripped stdout from one successful Git command."""

    return subprocess.run(
        ['git', '-C', str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
