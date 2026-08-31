"""Execute runtime-owned Activity checkpoints in mapped Git checkouts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from harnesses.codex_cli import execute_codex_cli
from harnesses.louie import execute_louie_action, prepare_louie_execution
from runs.lease_keepalive import LeaseKeepalive
from runs.models import ClaimedPipelineRun


ACTIVITY_RUN_STATUSES = frozenset({'in_progress', 'completed', 'failed', 'stopped'})
PIPELINE_RUN_STATUSES = frozenset({'queued', 'claimed', 'in_progress', 'failed', 'completed'})
LEASE_KEEPALIVE_INTERVAL_SECONDS = 30.0


class ActivityCheckpointClient(Protocol):
    """Access one Activity run and submit its local checkpoint results."""

    def get_run(
        self,
        *,
        project_id: str,
        activity_id: str,
        run_id: str,
    ) -> dict[str, object]:
        """Return one Activity run from the API."""

    def continue_run(
        self,
        *,
        project_id: str,
        activity_id: str,
        run_id: str,
        pipeline_run_id: str,
        lease_token: str,
        continuation_token: str,
        idempotency_key: str,
        result: dict[str, object],
    ) -> dict[str, object]:
        """Submit one local checkpoint result and return its next state."""


class PipelineContinuationClient(Protocol):
    """Advance claimed Pipelines after their selected Activity child is terminal."""

    def continue_run(
        self,
        *,
        project_id: str,
        pipeline_id: str,
        run_id: str,
        lease_token: str,
    ) -> dict[str, object]:
        """Return the pipeline state scheduled after its terminal current child."""

    def renew_lease(
        self,
        *,
        project_id: str,
        pipeline_id: str,
        run_id: str,
        lease_token: str,
    ) -> None:
        """Extend the active claim lease before a runtime-owned mutation."""


class ActivityExecutor:
    """Resume claimed Activity runs through runtime-owned local checkpoints."""

    def __init__(
        self,
        *,
        activity_client: ActivityCheckpointClient,
        pipeline_client: PipelineContinuationClient,
        harness_runner: Callable[[dict[str, object], Path], dict[str, object]] = execute_codex_cli,
        lease_keepalive_interval_seconds: float = LEASE_KEEPALIVE_INTERVAL_SECONDS,
    ) -> None:
        """Store the API clients used to complete Activity and Pipeline runs."""

        self._activity_client = activity_client
        self._pipeline_client = pipeline_client
        self._harness_runner = harness_runner
        self._lease_keepalive_interval_seconds = lease_keepalive_interval_seconds

    def execute_claim(self, claim: ClaimedPipelineRun, checkout_path: Path) -> None:
        """Execute the claimed child's supported checkpoint actions to completion."""

        pipeline_run = claim.payload
        _require_pipeline_response(pipeline_run)
        policy = prepare_louie_execution(checkout_path)
        while (child := pipeline_run.get('current_activity_run')) is not None:
            if not isinstance(child, dict):
                raise RuntimeError('Pipeline run has an invalid current_activity_run.')
            self._execute_child(
                claim=claim,
                child=child,
                checkout_path=checkout_path,
                policy=policy,
            )
            self._renew_lease(claim)
            pipeline_run = self._pipeline_client.continue_run(
                project_id=claim.project_id,
                pipeline_id=claim.pipeline_id,
                run_id=claim.run_id,
                lease_token=claim.lease_token,
            )
            _require_pipeline_response(pipeline_run)

    def _execute_child(
        self,
        *,
        claim: ClaimedPipelineRun,
        child: dict[str, object],
        checkout_path: Path,
        policy: dict[str, object],
    ) -> None:
        """Resume one scheduled Activity child through its local checkpoints."""

        activity_id = _require_text(child, 'activity_id')
        run_id = _require_text(child, 'id')
        response = self._activity_client.get_run(
            project_id=claim.project_id,
            activity_id=activity_id,
            run_id=run_id,
        )
        _require_activity_status(response)
        while response.get('status') == 'in_progress':
            self._renew_lease(claim)
            response = self._activity_client.continue_run(
                project_id=claim.project_id,
                activity_id=activity_id,
                run_id=run_id,
                pipeline_run_id=claim.run_id,
                lease_token=claim.lease_token,
                continuation_token=_require_text(response, 'continuation_token'),
                idempotency_key=uuid4().hex,
                result=self._action_result(
                    claim=claim,
                    response=response,
                    checkout_path=checkout_path,
                    policy=policy,
                ),
            )
            _require_activity_status(response)

    def _renew_lease(self, claim: ClaimedPipelineRun) -> None:
        """Keep the current worker lease active before mutating API state."""

        self._pipeline_client.renew_lease(
            project_id=claim.project_id,
            pipeline_id=claim.pipeline_id,
            run_id=claim.run_id,
            lease_token=claim.lease_token,
        )

    def _action_result(
        self,
        *,
        claim: ClaimedPipelineRun,
        response: dict[str, object],
        checkout_path: Path,
        policy: dict[str, object],
    ) -> dict[str, object]:
        """Build one supported local checkpoint result for the current Activity state."""

        action = _require_text(response, 'next_action')
        if action == 'run_harness':
            with LeaseKeepalive(
                renew=lambda: self._renew_lease(claim),
                interval_seconds=self._lease_keepalive_interval_seconds,
            ):
                return self._harness_runner(response, checkout_path)
        return execute_louie_action(
            response=response,
            checkout_path=checkout_path,
            policy=policy,
        )


def _require_text(value: dict[str, object], field_name: str) -> str:
    """Return a required non-empty response string."""

    field_value = value.get(field_name)
    if not isinstance(field_value, str) or not field_value:
        raise RuntimeError(f'Activity run is missing {field_name}.')
    return field_value


def _require_activity_status(response: dict[str, object]) -> str:
    """Return a recognized Activity status before pipeline scheduling uses it."""

    status = response.get('status')
    if not isinstance(status, str) or status not in ACTIVITY_RUN_STATUSES:
        raise RuntimeError(f'Activity run has invalid status: {status!r}.')
    return status


def _require_pipeline_response(response: dict[str, object]) -> None:
    """Require the scheduler fields that determine whether work remains."""

    status = response.get('status')
    if not isinstance(status, str) or status not in PIPELINE_RUN_STATUSES:
        raise RuntimeError(f'Pipeline run has invalid status: {status!r}.')
    if 'current_activity_run' not in response:
        raise RuntimeError('Pipeline run is missing current_activity_run.')
    current_child = response['current_activity_run']
    if current_child is not None and not isinstance(current_child, dict):
        raise RuntimeError('Pipeline run has invalid current_activity_run.')
