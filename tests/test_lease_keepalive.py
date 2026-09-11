"""Tests for concurrent Pipeline lease renewal during Harness execution."""

from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest

from runs.executor import ActivityExecutor
from runs.models import ClaimedPipelineRun


class HarnessActivityClient:
    """Expose one Harness checkpoint and record its submitted result."""

    def __init__(self) -> None:
        """Initialize an empty checkpoint log."""

        self.continuations: list[dict[str, object]] = []

    def get_run(self, **_: str) -> dict[str, object]:
        """Return one pending Harness action."""

        return {
            'status': 'in_progress',
            'next_action': 'run_harness',
            'continuation_token': 'continuation-1',
        }

    def continue_run(self, **payload: object) -> dict[str, object]:
        """Record the Harness result and complete the Activity."""

        self.continuations.append(payload)
        return {'status': 'completed', 'next_action': 'none'}


class RecordingPipelineClient:
    """Record lease renewals and optionally reject the concurrent one."""

    def __init__(self, *, fail_concurrent_renewal: bool = False) -> None:
        """Configure whether the second renewal should fail."""

        self.fail_concurrent_renewal = fail_concurrent_renewal
        self.renewal_count = 0
        self.concurrent_renewal = Event()
        self.continuation_count = 0

    def renew_lease(self, **_: str) -> None:
        """Record renewal and signal when the background thread reaches the API."""

        self.renewal_count += 1
        if self.renewal_count < 2:
            return
        self.concurrent_renewal.set()
        if self.fail_concurrent_renewal:
            raise RuntimeError('lease expired')

    def continue_run(self, **_: str) -> dict[str, object]:
        """Complete the Pipeline after its terminal Activity."""

        self.continuation_count += 1
        return {'status': 'completed', 'current_activity_run': None}


def test_harness_execution_renews_lease_concurrently(tmp_path: Path) -> None:
    """A blocking Harness receives a renewal before it returns its result."""

    activity_client = HarnessActivityClient()
    pipeline_client = RecordingPipelineClient()

    def run_harness(_: dict[str, object], __: Path) -> dict[str, object]:
        """Wait until the keepalive renews the lease from its background thread."""

        assert pipeline_client.concurrent_renewal.wait(timeout=1)
        return {'action': 'run_harness', 'completed': True}

    executor = ActivityExecutor(
        activity_client=activity_client,
        pipeline_client=pipeline_client,
        harness_runner=run_harness,
        lease_keepalive_interval_seconds=0.01,
    )

    executor.execute_claim(_claim(), tmp_path)

    assert pipeline_client.renewal_count >= 3
    assert len(activity_client.continuations) == 1
    assert pipeline_client.continuation_count == 1


def test_failed_keepalive_does_not_submit_harness_result(tmp_path: Path) -> None:
    """A rejected concurrent renewal fences the completed local result."""

    activity_client = HarnessActivityClient()
    pipeline_client = RecordingPipelineClient(fail_concurrent_renewal=True)

    def run_harness(_: dict[str, object], __: Path) -> dict[str, object]:
        """Finish only after observing the rejected background renewal."""

        assert pipeline_client.concurrent_renewal.wait(timeout=1)
        return {'action': 'run_harness', 'completed': True}

    executor = ActivityExecutor(
        activity_client=activity_client,
        pipeline_client=pipeline_client,
        harness_runner=run_harness,
        lease_keepalive_interval_seconds=0.01,
    )

    with pytest.raises(RuntimeError, match='keepalive failed: lease expired'):
        executor.execute_claim(_claim(), tmp_path)

    assert activity_client.continuations == []
    assert pipeline_client.continuation_count == 0


def _claim() -> ClaimedPipelineRun:
    """Build one claimed Pipeline with a current Harness Activity."""

    return ClaimedPipelineRun(
        project_id='project-1',
        pipeline_id='pipeline-1',
        run_id='pipeline-run-1',
        lease_token='lease-1',
        payload={
            'status': 'claimed',
            'current_activity_run': {
                'id': 'activity-run-1',
                'activity_id': 'activity-1',
            },
        },
    )
