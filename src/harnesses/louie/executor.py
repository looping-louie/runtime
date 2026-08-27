"""Execute default Louie Harness checkpoint actions in one checkout."""

from __future__ import annotations

from pathlib import Path

from services.checkout.changes import (
    get_changed_files,
    get_git_diff,
    read_changed_file_contents,
)
from services.checkout.operations import apply_file_operations
from services.checkout.policy import commit_policy_error, load_git_policy
from services.checkout.repository import (
    commit_all,
    get_current_branch,
    get_head_sha,
    has_changes,
)
from services.checkout.snapshot import (
    build_project_profile,
    build_repository_context,
    load_constitution,
)


def execute_louie_action(
    *,
    response: dict[str, object],
    checkout_path: Path,
    policy: dict[str, object],
) -> dict[str, object]:
    """Build a result for one default Louie Harness checkpoint action."""

    action = _require_text(response, 'next_action')
    if action == 'collect_snapshot':
        return {
            'action': 'collect_snapshot',
            'repo_context': build_repository_context(checkout_path),
            'checkout_metadata': {
                'checkout_path': str(checkout_path),
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
    raise RuntimeError(f'Unsupported Louie Harness action: {action!r}.')


def prepare_louie_execution(checkout_path: Path) -> dict[str, object]:
    """Capture the local policy before Louie changes the checkout."""

    return load_git_policy(checkout_path)


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
    except ValueError as error:
        return {'action': 'apply_operations', 'applied': False, 'error': str(error)}
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
    except RuntimeError as error:
        return {'action': 'commit_if_allowed', 'committed': False, 'error': str(error)}
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
    except RuntimeError as error:
        return {'action': 'commit_if_allowed', 'committed': False, 'error': str(error)}
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
