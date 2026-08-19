"""Tests for the runtime polling worker."""

from __future__ import annotations

from pathlib import Path

from config import RuntimeConfig, WorkspaceCheckout
from worker import ClaimedPipelineRun, RuntimeWorker


class FakeClaimClient:
    """Record claim requests and return preconfigured worker claims."""

    def __init__(self, claims: dict[str, ClaimedPipelineRun | None]) -> None:
        """Store claims returned by workspace identifier."""

        self._claims = claims
        self.calls: list[tuple[str, str]] = []

    def claim_next(
        self,
        *,
        workspace_id: str,
        worker_id: str,
    ) -> ClaimedPipelineRun | None:
        """Return the configured claim after recording its worker identity."""

        self.calls.append((workspace_id, worker_id))
        return self._claims[workspace_id]


def test_run_once_executes_claim_in_its_mapped_checkout(tmp_path: Path) -> None:
    """Each claimed workspace run is delegated to its configured checkout."""

    first_checkout = tmp_path / 'first'
    second_checkout = tmp_path / 'second'
    claim = ClaimedPipelineRun(
        workspace_id='workspace-1', pipeline_id='pipeline-1', run_id='run-1', lease_token='lease-1',
        payload={'id': 'run-1'},
    )
    client = FakeClaimClient(
        {'workspace-1': claim, 'workspace-2': None},
    )
    executions: list[tuple[ClaimedPipelineRun, Path]] = []
    worker = RuntimeWorker(
        config=RuntimeConfig(
            api_base_url='http://127.0.0.1:8000/api/v1', worker_id='worker-1',
            poll_interval_seconds=1,
            workspaces=(
                WorkspaceCheckout('workspace-1', first_checkout),
                WorkspaceCheckout('workspace-2', second_checkout),
            ),
        ),
        claim_client=client,
        execute_claim=lambda received_claim, checkout: executions.append(
            (received_claim, checkout),
        ),
    )

    claimed_count = worker.run_once()

    assert claimed_count == 1
    assert client.calls == [('workspace-1', 'worker-1'), ('workspace-2', 'worker-1')]
    assert executions == [(claim, first_checkout)]
