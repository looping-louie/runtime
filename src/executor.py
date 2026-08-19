"""Execute runtime-owned Activity checkpoints in mapped Git checkouts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import uuid4

from file_operations import apply_file_operations
from policy import commit_policy_error, load_git_policy
from repository_context import (
    build_project_profile,
    build_repository_context,
    get_changed_files,
    commit_all,
    get_current_branch,
    get_git_diff,
    get_head_sha,
    has_changes,
    load_constitution,
    read_changed_file_contents,
)
from worker import ClaimedPipelineRun


ACTIVITY_RUN_STATUSES = frozenset({'in_progress', 'completed', 'failed', 'stopped'})
PIPELINE_RUN_STATUSES = frozenset({'queued', 'claimed', 'in_progress', 'failed', 'completed'})


class ActivityCheckpointClient(Protocol):
    """Access one Activity run and submit its local checkpoint results."""

    def get_run(
        self,
        *,
        workspace_id: str,
        activity_id: str,
        run_id: str,
    ) -> dict[str, object]:
        """Return one Activity run from the API."""

    def continue_run(
        self,
        *,
        workspace_id: str,
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
        workspace_id: str,
        pipeline_id: str,
        run_id: str,
        lease_token: str,
    ) -> dict[str, object]:
        """Return the pipeline state scheduled after its terminal current child."""

    def renew_lease(
        self,
        *,
        workspace_id: str,
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
    ) -> None:
        """Store the API clients used to complete Activity and Pipeline runs."""

        self._activity_client = activity_client
        self._pipeline_client = pipeline_client

    def execute_claim(self, claim: ClaimedPipelineRun, checkout_path: Path) -> None:
        """Execute the claimed child's supported checkpoint actions to completion."""

        pipeline_run = claim.payload
        _require_pipeline_response(pipeline_run)
        policy = load_git_policy(checkout_path)
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
                workspace_id=claim.workspace_id,
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
            workspace_id=claim.workspace_id,
            activity_id=activity_id,
            run_id=run_id,
        )
        _require_activity_status(response)
        while response.get('status') == 'in_progress':
            self._renew_lease(claim)
            response = self._activity_client.continue_run(
                workspace_id=claim.workspace_id,
                activity_id=activity_id,
                run_id=run_id,
                pipeline_run_id=claim.run_id,
                lease_token=claim.lease_token,
                continuation_token=_require_text(response, 'continuation_token'),
                idempotency_key=uuid4().hex,
                result=self._action_result(
                    response=response,
                    checkout_path=checkout_path,
                    policy=policy,
                ),
            )
            _require_activity_status(response)

    def _renew_lease(self, claim: ClaimedPipelineRun) -> None:
        """Keep the current worker lease active before mutating API state."""

        self._pipeline_client.renew_lease(
            workspace_id=claim.workspace_id,
            pipeline_id=claim.pipeline_id,
            run_id=claim.run_id,
            lease_token=claim.lease_token,
        )

    @staticmethod
    def _action_result(
        *,
        response: dict[str, object],
        checkout_path: Path,
        policy: dict[str, object],
    ) -> dict[str, object]:
        """Build one supported local checkpoint result for the current Activity state."""

        action = _require_text(response, 'next_action')
        if action == 'collect_snapshot':
            return {
                'action': 'collect_snapshot',
                'repo_context': build_repository_context(checkout_path),
                'workspace_metadata': {
                    'workspace_path': str(checkout_path),
                    'source_commit_sha': get_head_sha(checkout_path),
                },
                'constitution': load_constitution(checkout_path),
                'project_profile': build_project_profile(checkout_path),
            }
        if action == 'apply_operations':
            return _apply_operations_result(response=response, checkout_path=checkout_path)
        if action == 'submit_review_input':
            changed_files = get_changed_files(checkout_path)
            return {
                'action': 'submit_review_input',
                'final_diff': get_git_diff(checkout_path),
                'changed_file_contents': read_changed_file_contents(
                    checkout_path,
                    changed_files,
                ),
            }
        if action == 'commit_if_allowed':
            return _commit_result(
                response=response,
                checkout_path=checkout_path,
                policy=policy,
            )
        raise RuntimeError(f'Unsupported runtime activity action: {action!r}.')


def _apply_operations_result(
    *,
    response: dict[str, object],
    checkout_path: Path,
) -> dict[str, object]:
    """Apply API operations and report the resulting checkout state."""

    payload = response.get('payload')
    operations = payload.get('operations') if isinstance(payload, dict) else None
    if not isinstance(operations, list):
        return {
            'action': 'apply_operations',
            'applied': True,
            'final_diff': get_git_diff(checkout_path),
            'changed_files': get_changed_files(checkout_path),
        }
    try:
        apply_file_operations(checkout_path, operations)
    except ValueError as exc:
        return {'action': 'apply_operations', 'applied': False, 'error': str(exc)}
    return {
        'action': 'apply_operations',
        'applied': True,
        'final_diff': get_git_diff(checkout_path),
        'changed_files': get_changed_files(checkout_path),
    }


def _commit_result(
    *,
    response: dict[str, object],
    checkout_path: Path,
    policy: dict[str, object],
) -> dict[str, object]:
    """Commit API-approved changes unless local checkout policy blocks the action."""

    try:
        policy_error = commit_policy_error(
            policy=policy,
            current_branch=get_current_branch(checkout_path),
        )
    except RuntimeError as exc:
        return {'action': 'commit_if_allowed', 'committed': False, 'error': str(exc)}
    if policy_error is not None:
        return {'action': 'commit_if_allowed', 'committed': False, 'error': policy_error}
    payload = response.get('payload')
    commit_message = payload.get('commit_message') if isinstance(payload, dict) else None
    if not isinstance(commit_message, str) or not commit_message.strip():
        return {
            'action': 'commit_if_allowed',
            'committed': False,
            'error': 'Activity run did not provide a commit_message.',
        }
    if not has_changes(checkout_path):
        return {
            'action': 'commit_if_allowed',
            'committed': False,
            'error': 'No repository changes were found to commit.',
        }
    try:
        commit_sha = commit_all(checkout_path, commit_message)
    except RuntimeError as exc:
        return {'action': 'commit_if_allowed', 'committed': False, 'error': str(exc)}
    return {
        'action': 'commit_if_allowed',
        'committed': True,
        'commit_sha': commit_sha,
        'commit_message': commit_message,
    }


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
