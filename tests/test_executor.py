"""Tests for runtime-owned activity checkpoint execution."""

from __future__ import annotations

import subprocess
from pathlib import Path

from executor import ActivityExecutor
from worker import ClaimedPipelineRun


class FakeActivityClient:
    """Expose one claimed Activity run and record its continuation result."""

    def __init__(self) -> None:
        """Initialize the initial checkpoint response and empty submissions."""

        self.continuations: list[dict[str, object]] = []
        self._responses = iter(
            [
                {
                    'id': 'activity-run-1',
                    'activity_id': 'activity-1',
                    'status': 'in_progress',
                    'next_action': 'apply_operations',
                    'continuation_token': 'token-2',
                    'payload': {
                        'operations': [
                            {
                                'operation': 'create',
                                'path': 'output.txt',
                                'content': 'created by runtime\n',
                            }
                        ]
                    },
                },
                {
                    'id': 'activity-run-1',
                    'activity_id': 'activity-1',
                    'status': 'in_progress',
                    'next_action': 'submit_review_input',
                    'continuation_token': 'token-3',
                },
                {
                    'id': 'activity-run-1',
                    'activity_id': 'activity-1',
                    'status': 'in_progress',
                    'next_action': 'commit_if_allowed',
                    'continuation_token': 'token-4',
                    'payload': {'commit_message': 'feat: runtime output'},
                },
                {
                    'id': 'activity-run-1',
                    'activity_id': 'activity-1',
                    'status': 'completed',
                    'next_action': 'none',
                },
            ]
        )

    def get_run(
        self,
        *,
        workspace_id: str,
        activity_id: str,
        run_id: str,
    ) -> dict[str, object]:
        """Return the pending snapshot checkpoint for the claimed child run."""

        assert (workspace_id, activity_id, run_id) == (
            'workspace-1',
            'activity-1',
            'activity-run-1',
        )
        return {
            'id': run_id,
            'activity_id': activity_id,
            'status': 'in_progress',
            'next_action': 'collect_snapshot',
            'continuation_token': 'token-1',
        }

    def continue_run(self, **payload: object) -> dict[str, object]:
        """Record the local snapshot result and finish the Activity run."""

        self.continuations.append(payload)
        return next(self._responses)


class FakePipelineClient:
    """Return sequential Activity children after terminal child runs."""

    def __init__(self) -> None:
        """Initialize the pipeline responses and continuation request log."""

        self.continuations: list[dict[str, str]] = []
        self._responses = iter(
            [
                {
                    'id': 'run-1',
                    'pipeline_id': 'pipeline-1',
                    'status': 'in_progress',
                    'current_activity_run': {
                        'id': 'activity-run-2',
                        'activity_id': 'activity-2',
                    },
                },
                {
                    'id': 'run-1',
                    'pipeline_id': 'pipeline-1',
                    'status': 'completed',
                    'current_activity_run': None,
                },
            ]
        )

    def continue_run(
        self,
        *,
        workspace_id: str,
        pipeline_id: str,
        run_id: str,
        lease_token: str,
    ) -> dict[str, object]:
        """Record one pipeline continuation and return its next scheduler state."""

        self.continuations.append(
            {
                'workspace_id': workspace_id,
                'pipeline_id': pipeline_id,
                'run_id': run_id,
                'lease_token': lease_token,
            }
        )
        return next(self._responses)

    def renew_lease(self, **_: str) -> None:
        """Accept runtime lease renewals while the fake claim remains active."""


def test_execute_claim_submits_repository_snapshot(tmp_path: Path) -> None:
    """The runtime resumes a claimed child and sends its mapped checkout context."""

    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    _git(checkout, 'init')
    _git(checkout, 'config', 'user.name', 'Runtime Test')
    _git(checkout, 'config', 'user.email', 'runtime@example.com')
    (checkout / 'README.md').write_text('seed\n', encoding='utf-8')
    _git(checkout, 'add', 'README.md')
    _git(checkout, 'commit', '-m', 'seed')
    (checkout / 'notes.md').write_text('runtime context\n', encoding='utf-8')
    client = FakeActivityClient()
    executor = ActivityExecutor(
        activity_client=client,
        pipeline_client=_TerminalPipelineClient(),
    )
    claim = ClaimedPipelineRun(
        workspace_id='workspace-1', pipeline_id='pipeline-1', run_id='run-1',
        lease_token='lease-1',
        payload={
            'current_activity_run': {
                'id': 'activity-run-1',
                'activity_id': 'activity-1',
            }
        },
    )

    executor.execute_claim(claim, checkout)

    assert len(client.continuations) == 4
    result = client.continuations[0]['result']
    assert isinstance(result, dict)
    assert result['action'] == 'collect_snapshot'
    assert result['workspace_metadata']['workspace_path'] == str(checkout)
    assert 'README.md' in result['repo_context']
    assert 'notes.md' in result['repo_context']
    applied_result = client.continuations[1]['result']
    assert isinstance(applied_result, dict)
    assert applied_result['action'] == 'apply_operations'
    assert applied_result['applied'] is True
    assert applied_result['changed_files'] == ['notes.md', 'output.txt']
    assert (checkout / 'output.txt').read_text(encoding='utf-8') == 'created by runtime\n'
    review_result = client.continuations[2]['result']
    assert isinstance(review_result, dict)
    assert review_result['action'] == 'submit_review_input'
    assert review_result['changed_file_contents']['output.txt'] == 'created by runtime\n'
    commit_result = client.continuations[3]['result']
    assert isinstance(commit_result, dict)
    assert commit_result['action'] == 'commit_if_allowed'
    assert commit_result['committed'] is True
    assert isinstance(commit_result['commit_sha'], str)


def test_execute_claim_advances_pipeline_through_sequential_children(
    tmp_path: Path,
) -> None:
    """The runtime executes children scheduled after each terminal Activity run."""

    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    activity_client = _CompletedActivityClient()
    pipeline_client = FakePipelineClient()
    executor = ActivityExecutor(
        activity_client=activity_client,
        pipeline_client=pipeline_client,
    )
    claim = ClaimedPipelineRun(
        workspace_id='workspace-1', pipeline_id='pipeline-1', run_id='run-1',
        lease_token='lease-1',
        payload={
            'current_activity_run': {
                'id': 'activity-run-1',
                'activity_id': 'activity-1',
            }
        },
    )

    executor.execute_claim(claim, checkout)

    assert activity_client.requested_runs == [
        ('activity-1', 'activity-run-1'),
        ('activity-2', 'activity-run-2'),
    ]
    assert pipeline_client.continuations == [
        {
            'workspace_id': 'workspace-1',
            'pipeline_id': 'pipeline-1',
            'run_id': 'run-1',
            'lease_token': 'lease-1',
        },
        {
            'workspace_id': 'workspace-1',
            'pipeline_id': 'pipeline-1',
            'run_id': 'run-1',
            'lease_token': 'lease-1',
        },
    ]


class _CompletedActivityClient:
    """Return an immediately completed state for each scheduled child run."""

    def __init__(self) -> None:
        """Initialize the requested child-run log."""

        self.requested_runs: list[tuple[str, str]] = []

    def get_run(
        self,
        *,
        workspace_id: str,
        activity_id: str,
        run_id: str,
    ) -> dict[str, object]:
        """Return a completed Activity run for the requested scheduler child."""

        assert workspace_id == 'workspace-1'
        self.requested_runs.append((activity_id, run_id))
        return {
            'id': run_id,
            'activity_id': activity_id,
            'status': 'completed',
            'next_action': 'none',
        }

    def continue_run(self, **payload: object) -> dict[str, object]:
        """Reject checkpoint continuation because this test uses terminal children."""

        raise AssertionError(f'Unexpected Activity continuation: {payload}')


class _TerminalPipelineClient:
    """Return a completed pipeline after the fixture's only Activity child."""

    def continue_run(self, **_payload: str) -> dict[str, object]:
        """Return the terminal scheduler state for the executed child."""

        return {'status': 'completed', 'current_activity_run': None}

    def renew_lease(self, **_payload: str) -> None:
        """Accept the single-child fixture's lease renewals."""


def _git(repo: Path, *arguments: str) -> None:
    """Run one Git command in the temporary test checkout."""

    subprocess.run(
        ['git', '-C', str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
