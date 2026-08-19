"""Load and validate runtime workspace checkout mappings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class WorkspaceCheckout:
    """One API workspace and the checkout a runtime may execute within."""

    workspace_id: str
    repository_path: Path


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Runtime connection settings and authorized workspace checkouts."""

    api_base_url: str
    worker_id: str
    poll_interval_seconds: float
    workspaces: tuple[WorkspaceCheckout, ...]

    def checkout_for(self, workspace_id: str) -> WorkspaceCheckout:
        """Return the configured checkout for one API workspace."""

        for workspace in self.workspaces:
            if workspace.workspace_id == workspace_id:
                return workspace
        raise ValueError(f'No checkout is configured for workspace {workspace_id!r}.')

    def validate_checkouts(self) -> None:
        """Require every configured checkout to be an existing Git repository."""

        for workspace in self.workspaces:
            if not workspace.repository_path.is_dir():
                raise ValueError(
                    f'Checkout for workspace {workspace.workspace_id!r} does not exist: '
                    f'{workspace.repository_path}'
                )
            if not (workspace.repository_path / '.git').exists():
                raise ValueError(
                    f'Checkout for workspace {workspace.workspace_id!r} is not a Git '
                    f'repository: {workspace.repository_path}'
                )


def load_config(path: str | Path) -> RuntimeConfig:
    """Load one strict JSON runtime configuration file."""

    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding='utf-8'))
    except OSError as exc:
        raise ValueError(f'Could not read runtime configuration {config_path}: {exc}') from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f'Runtime configuration {config_path} is not valid JSON.') from exc
    if not isinstance(raw, dict):
        raise ValueError('Runtime configuration must be a JSON object.')
    _reject_unknown_fields(
        raw,
        {'api_base_url', 'worker_id', 'poll_interval_seconds', 'workspaces'},
        'Runtime configuration',
    )
    return RuntimeConfig(
        api_base_url=_require_http_url(raw.get('api_base_url'), 'api_base_url'),
        worker_id=_require_text(raw.get('worker_id'), 'worker_id'),
        poll_interval_seconds=_require_positive_number(
            raw.get('poll_interval_seconds'), 'poll_interval_seconds',
        ),
        workspaces=_parse_workspaces(raw.get('workspaces')),
    )


def _parse_workspaces(value: object) -> tuple[WorkspaceCheckout, ...]:
    """Validate distinct workspace mappings from JSON configuration."""

    if not isinstance(value, list) or not value:
        raise ValueError('workspaces must be a non-empty array.')
    workspaces: list[WorkspaceCheckout] = []
    workspace_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f'workspaces[{index}] must be an object.')
        _reject_unknown_fields(item, {'workspace_id', 'repository_path'}, f'workspaces[{index}]')
        workspace_id = _require_text(item.get('workspace_id'), f'workspaces[{index}].workspace_id')
        if workspace_id in workspace_ids:
            raise ValueError(f'workspaces contains duplicate workspace_id {workspace_id!r}.')
        workspace_ids.add(workspace_id)
        workspaces.append(
            WorkspaceCheckout(
                workspace_id=workspace_id,
                repository_path=Path(
                    _require_text(
                        item.get('repository_path'),
                        f'workspaces[{index}].repository_path',
                    )
                ).expanduser(),
            )
        )
    return tuple(workspaces)


def _require_http_url(value: object, field_name: str) -> str:
    """Return an absolute HTTP URL accepted for API communication."""

    text = _require_text(value, field_name)
    parsed = urlparse(text)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise ValueError(f'{field_name} must be an absolute HTTP or HTTPS URL.')
    return text.rstrip('/')


def _require_positive_number(value: object, field_name: str) -> float:
    """Return a finite positive polling interval."""

    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ValueError(f'{field_name} must be a positive number.')
    return float(value)


def _require_text(value: object, field_name: str) -> str:
    """Return one non-empty configuration string."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field_name} must be a non-empty string.')
    return value.strip()


def _reject_unknown_fields(
    value: dict[str, Any],
    allowed_fields: set[str],
    context: str,
) -> None:
    """Reject misspelled configuration fields rather than ignoring them."""

    unknown_fields = sorted(set(value) - allowed_fields)
    if unknown_fields:
        raise ValueError(f'{context} contains unsupported fields: {", ".join(unknown_fields)}.')