"""Tests for runtime workspace checkout configuration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from looping_louie_runtime.config import load_config


def write_config(tmp_path: Path, payload: dict[str, object]) -> Path:
    """Write one JSON configuration fixture and return its path."""

    path = tmp_path / 'runtime.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    return path


def test_load_config_resolves_workspace_checkout(tmp_path: Path) -> None:
    """A runtime maps every configured workspace to one checkout path."""

    checkout_path = tmp_path / 'checkout'
    checkout_path.mkdir()
    config = load_config(
        write_config(
            tmp_path,
            {
                'api_base_url': 'http://127.0.0.1:8000/api/v1/',
                'worker_id': 'runtime-local-01',
                'poll_interval_seconds': 2,
                'workspaces': [
                    {
                        'workspace_id': 'workspace-local',
                        'repository_path': str(checkout_path),
                    }
                ],
            },
        )
    )

    assert config.api_base_url == 'http://127.0.0.1:8000/api/v1'
    assert config.checkout_for('workspace-local').repository_path == checkout_path


def test_load_config_rejects_duplicate_workspace_mapping(tmp_path: Path) -> None:
    """Duplicate mappings cannot make a claimed run choose an arbitrary checkout."""

    path = write_config(
        tmp_path,
        {
            'api_base_url': 'http://127.0.0.1:8000/api/v1',
            'worker_id': 'runtime-local-01',
            'poll_interval_seconds': 2,
            'workspaces': [
                {'workspace_id': 'workspace-local', 'repository_path': '/first'},
                {'workspace_id': 'workspace-local', 'repository_path': '/second'},
            ],
        },
    )

    with pytest.raises(ValueError, match='duplicate workspace_id'):
        load_config(path)


def test_validate_checkouts_requires_git_repository(tmp_path: Path) -> None:
    """A mapped directory must be a checkout before the runtime starts."""

    checkout_path = tmp_path / 'checkout'
    checkout_path.mkdir()
    config = load_config(
        write_config(
            tmp_path,
            {
                'api_base_url': 'http://127.0.0.1:8000/api/v1',
                'worker_id': 'runtime-local-01',
                'poll_interval_seconds': 2,
                'workspaces': [
                    {
                        'workspace_id': 'workspace-local',
                        'repository_path': str(checkout_path),
                    }
                ],
            },
        )
    )

    with pytest.raises(ValueError, match='not a Git repository'):
        config.validate_checkouts()