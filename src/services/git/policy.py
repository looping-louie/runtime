"""Load local checkout Git policy used by runtime commit checkpoints."""

from __future__ import annotations

from pathlib import Path

import yaml


def load_git_policy(checkout_path: Path) -> dict[str, object]:
    """Load strict louie.yaml commit rules or return the default allow policy."""

    path = checkout_path / 'louie.yaml'
    default_policy: dict[str, object] = {
        'commit_allowed': True,
        'protected_branches': [],
        'config_path': str(path),
    }
    if not path.exists():
        return default_policy
    try:
        parsed = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RuntimeError(f'Could not read louie.yaml policy: {exc}') from exc
    if parsed is None:
        return default_policy
    if not isinstance(parsed, dict):
        raise RuntimeError('louie.yaml root must be a YAML object.')
    _require_only_fields(parsed, {'git'}, 'louie.yaml')
    git = parsed.get('git')
    if git is None:
        return default_policy
    if not isinstance(git, dict):
        raise RuntimeError('louie.yaml git section must be a YAML object.')
    _require_only_fields(git, {'actions_allowed', 'protected_branches'}, 'louie.yaml git section')
    actions = _string_list(git.get('actions_allowed'), 'git.actions_allowed')
    protected_branches = _string_list(git.get('protected_branches'), 'git.protected_branches')
    return {
        'commit_allowed': actions is None or 'commit' in actions,
        'protected_branches': protected_branches or [],
        'config_path': str(path),
    }


def commit_policy_error(
    *,
    policy: dict[str, object],
    current_branch: str,
) -> str | None:
    """Return a policy reason that blocks committing on the supplied branch."""

    config_path = policy.get('config_path', 'louie.yaml')
    if policy.get('commit_allowed', True) is False:
        return (
            f'Commit is denied by louie.yaml policy ({config_path}): '
            'git.actions_allowed does not include commit.'
        )
    protected_branches = policy.get('protected_branches')
    if not isinstance(protected_branches, list):
        return None
    if current_branch.casefold() in {
        branch.casefold() for branch in protected_branches if isinstance(branch, str)
    }:
        return (
            f'Commit is denied by louie.yaml policy ({config_path}): '
            f'branch {current_branch} is protected.'
        )
    return None


def _require_only_fields(value: dict[object, object], allowed: set[str], context: str) -> None:
    """Reject unsupported policy fields rather than silently ignoring them."""

    unknown_fields = sorted(str(field) for field in set(value) - allowed)
    if unknown_fields:
        raise RuntimeError(f'{context} contains unsupported fields: {", ".join(unknown_fields)}.')


def _string_list(value: object, name: str) -> list[str] | None:
    """Normalize an optional non-duplicated list of policy strings."""

    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError(f'louie.yaml {name} must be a list of strings.')
    normalized = [item.strip().casefold() for item in value if item.strip()]
    if len(normalized) != len(set(normalized)):
        raise RuntimeError(f'louie.yaml {name} cannot contain duplicate values.')
    return normalized