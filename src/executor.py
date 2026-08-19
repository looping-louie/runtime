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
        continuation_token: str,
        idempotency_key: str,
        result: dict[str, object],
    ) -> dict[str, object]:
        """Submit one local checkpoint result and return its next state."""


class ActivityExecutor:
    """Resume claimed Activity runs through runtime-owned local checkpoints."""

    def __init__(self, *, activity_client: ActivityCheckpointClient) -> None:
        """Store the API checkpoint client used to continue Activity runs."""

        self._activity_client = activity_client

    def execute_claim(self, claim: ClaimedPipelineRun, checkout_path: Path) -> None:
        """Execute the claimed child's supported checkpoint actions to completion."""

        child = _require_child(claim.payload)
        activity_id = _require_text(child, 'activity_id')
        run_id = _require_text(child, 'id')
        response = self._activity_client.get_run(
            workspace_id=claim.workspace_id,
            activity_id=activity_id,
            run_id=run_id,
        )
        while response.get('status') == 'in_progress':
            response = self._activity_client.continue_run(
                workspace_id=claim.workspace_id,
                activity_id=activity_id,
                run_id=run_id,
                continuation_token=_require_text(response, 'continuation_token'),
                idempotency_key=uuid4().hex,
                result=self._action_result(response=response, checkout_path=checkout_path),
            )

    @staticmethod
    def _action_result(
        *,
        response: dict[str, object],
        checkout_path: Path,
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
            return _commit_result(response=response, checkout_path=checkout_path)
        raise RuntimeError(f'Unsupported runtime activity action: {action!r}.')


def _require_child(payload: dict[str, object]) -> dict[str, object]:
    """Return the current Activity run supplied by a pipeline claim response."""

    child = payload.get('current_activity_run')
    if not isinstance(child, dict):
        raise RuntimeError('Claimed pipeline run is missing current_activity_run.')
    return child


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


def _commit_result(*, response: dict[str, object], checkout_path: Path) -> dict[str, object]:
    """Commit API-approved changes unless local checkout policy blocks the action."""

    try:
        policy_error = commit_policy_error(
            policy=load_git_policy(checkout_path),
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
