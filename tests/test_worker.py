"""Tests for the runtime polling worker."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from configuration.runtime import RuntimeConfig, ProjectCheckout
from polling.worker import RuntimeWorker
from runs.models import ClaimedPipelineRun


class FakeClaimClient:
    """Record claim requests and return preconfigured worker claims."""

    def __init__(self, claims: dict[str, ClaimedPipelineRun | None]) -> None:
        """Store claims returned by project identifier."""

        self._claims = claims
        self.calls: list[tuple[str, str]] = []

    def claim_next(
        self,
        *,
        project_id: str,
        worker_id: str,
    ) -> ClaimedPipelineRun | None:
        """Return the configured claim after recording its worker identity."""

        self.calls.append((project_id, worker_id))
        return self._claims[project_id]


class FakeHeartbeatClient:
    """Record worker heartbeat calls."""

    def __init__(self) -> None:
        """Initialize an empty heartbeat request log."""

        self.heartbeats: list[tuple[str, str, tuple[str, ...]]] = []

    def heartbeat(
        self,
        *,
        project_id: str,
        worker_id: str,
        harnesses: tuple[str, ...],
    ) -> None:
        """Record one project heartbeat request."""

        self.heartbeats.append((project_id, worker_id, harnesses))


def test_run_once_executes_claim_in_its_mapped_checkout(tmp_path: Path) -> None:
    """Each claimed project run is delegated to its configured checkout."""

    first_checkout = tmp_path / 'first'
    second_checkout = tmp_path / 'second'
    claim = ClaimedPipelineRun(
        project_id='project-1', pipeline_id='pipeline-1', run_id='run-1', lease_token='lease-1',
        payload={'id': 'run-1'},
    )
    client = FakeClaimClient(
        {'project-1': claim, 'project-2': None},
    )
    executions: list[tuple[ClaimedPipelineRun, Path]] = []
    worker = RuntimeWorker(
        config=RuntimeConfig(
            api_base_url='http://127.0.0.1:8000/api/v1',
            user_id='user-1',
            poll_interval_seconds=1,
            projects=(
                ProjectCheckout('project-1', 'worker-1', first_checkout),
                ProjectCheckout('project-2', 'worker-2', second_checkout),
            ),
        ),
        claim_client=client,
        execute_claim=lambda received_claim, checkout: executions.append(
            (received_claim, checkout),
        ),
    )

    claimed_count = worker.run_once()

    assert claimed_count == 1
    assert client.calls == [('project-1', 'worker-1'), ('project-2', 'worker-2')]
    assert executions == [(claim, first_checkout)]


def test_worker_heartbeats_each_provisioned_workspace_worker(
    tmp_path: Path,
) -> None:
    """Heartbeats precede project claims for provisioned identities."""

    first_checkout = tmp_path / 'first'
    second_checkout = tmp_path / 'second'
    heartbeat_client = FakeHeartbeatClient()
    worker = RuntimeWorker(
        config=RuntimeConfig(
            api_base_url='http://127.0.0.1:8000/api/v1',
            user_id='user-1',
            poll_interval_seconds=1,
            projects=(
                ProjectCheckout('project-1', 'worker-1', first_checkout),
                ProjectCheckout('project-2', 'worker-2', second_checkout),
            ),
        ),
        claim_client=FakeClaimClient({'project-1': None, 'project-2': None}),
        heartbeat_client=heartbeat_client,
        harness_capabilities=lambda: ('louie', 'codex_cli'),
        execute_claim=lambda _claim, _checkout: None,
    )

    worker.run_once()

    assert heartbeat_client.heartbeats == [
        ('project-1', 'worker-1', ('louie', 'codex_cli')),
        ('project-2', 'worker-2', ('louie', 'codex_cli')),
    ]


def test_run_once_continues_after_one_workspace_execution_fails(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed claim execution does not stop polling other projects."""

    first_checkout = tmp_path / 'first'
    second_checkout = tmp_path / 'second'
    first_claim = ClaimedPipelineRun(
        project_id='project-1', pipeline_id='pipeline-1', run_id='run-1',
        lease_token='lease-1', payload={'id': 'run-1'},
    )
    second_claim = ClaimedPipelineRun(
        project_id='project-2', pipeline_id='pipeline-2', run_id='run-2',
        lease_token='lease-2', payload={'id': 'run-2'},
    )
    client = FakeClaimClient(
        {'project-1': first_claim, 'project-2': second_claim},
    )
    executions: list[str] = []

    def execute_claim(claim: ClaimedPipelineRun, _: Path) -> None:
        """Fail the first claimed run and record both execution attempts."""

        executions.append(claim.project_id)
        if claim.project_id == 'project-1':
            raise RuntimeError('first project failed')

    worker = RuntimeWorker(
        config=RuntimeConfig(
            api_base_url='http://127.0.0.1:8000/api/v1',
            user_id='user-1',
            poll_interval_seconds=1,
            projects=(
                ProjectCheckout('project-1', 'worker-1', first_checkout),
                ProjectCheckout('project-2', 'worker-2', second_checkout),
            ),
        ),
        claim_client=client,
        execute_claim=execute_claim,
    )

    with caplog.at_level(logging.ERROR):
        claimed_count = worker.run_once()

    assert claimed_count == 1
    assert client.calls == [('project-1', 'worker-1'), ('project-2', 'worker-2')]
    assert executions == ['project-1', 'project-2']
    assert 'project-1' in caplog.text
