"""Load and validate runtime project checkout mappings."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class ProjectCheckout:
    """One API project and the checkout a runtime may execute within."""

    project_id: str
    worker_id: str
    repository_path: Path


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Runtime connection settings and authorized project checkouts."""

    api_base_url: str
    poll_interval_seconds: float
    projects: tuple[ProjectCheckout, ...]

    def checkout_for(self, project_id: str) -> ProjectCheckout:
        """Return the configured checkout for one API project."""

        for project in self.projects:
            if project.project_id == project_id:
                return project
        raise ValueError(f'No checkout is configured for project {project_id!r}.')

    def validate_checkouts(self) -> None:
        """Require every configured checkout to be an existing Git repository."""

        for project in self.projects:
            if not project.repository_path.is_dir():
                raise ValueError(
                    f'Checkout for project {project.project_id!r} does not exist: '
                    f'{project.repository_path}'
                )
            if not (project.repository_path / '.git').exists():
                raise ValueError(
                    f'Checkout for project {project.project_id!r} is not a Git '
                    f'repository: {project.repository_path}'
                )
            if _has_uncommitted_changes(project.repository_path):
                raise ValueError(
                    f'Checkout for project {project.project_id!r} contains '
                    'uncommitted changes.'
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
        {'api_base_url', 'poll_interval_seconds', 'projects'},
        'Runtime configuration',
    )
    return RuntimeConfig(
        api_base_url=_require_http_url(raw.get('api_base_url'), 'api_base_url'),
        poll_interval_seconds=_require_positive_number(
            raw.get('poll_interval_seconds'), 'poll_interval_seconds',
        ),
        projects=_parse_projects(raw.get('projects')),
    )


def _parse_projects(value: object) -> tuple[ProjectCheckout, ...]:
    """Validate distinct project mappings from JSON configuration."""

    if not isinstance(value, list) or not value:
        raise ValueError('projects must be a non-empty array.')
    projects: list[ProjectCheckout] = []
    project_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f'projects[{index}] must be an object.')
        _reject_unknown_fields(
            item,
            {'project_id', 'worker_id', 'repository_path'},
            f'projects[{index}]',
        )
        project_id = _require_text(item.get('project_id'), f'projects[{index}].project_id')
        if project_id in project_ids:
            raise ValueError(f'projects contains duplicate project_id {project_id!r}.')
        project_ids.add(project_id)
        projects.append(
            ProjectCheckout(
                project_id=project_id,
                worker_id=_require_text(item.get('worker_id'), f'projects[{index}].worker_id'),
                repository_path=Path(
                    _require_text(
                        item.get('repository_path'),
                        f'projects[{index}].repository_path',
                    )
                ).expanduser(),
            )
        )
    return tuple(projects)


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


def _has_uncommitted_changes(checkout_path: Path) -> bool:
    """Return whether a checkout has non-ignored changes to tracked or new files."""

    try:
        result = subprocess.run(
            [
                'git', '-C', str(checkout_path), 'status', '--porcelain',
                '--untracked-files=all',
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ValueError(f'Could not inspect Git checkout {checkout_path}: {exc}') from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ValueError(
            f'Could not inspect Git checkout {checkout_path}: {detail or "unknown error"}'
        )
    return bool(result.stdout.strip())


def _reject_unknown_fields(
    value: dict[str, Any],
    allowed_fields: set[str],
    context: str,
) -> None:
    """Reject misspelled configuration fields rather than ignoring them."""

    unknown_fields = sorted(set(value) - allowed_fields)
    if unknown_fields:
        raise ValueError(f'{context} contains unsupported fields: {", ".join(unknown_fields)}.')
