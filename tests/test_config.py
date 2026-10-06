"""Tests for runtime project checkout configuration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from configuration.runtime import (
    HarnessConfig,
    initialize_config,
    load_config,
    persist_worker_id,
)


def write_config(tmp_path: Path, payload: dict[str, object]) -> Path:
    """Write one JSON configuration fixture and return its path."""

    path = tmp_path / 'runtime.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    return path


def config_payload(checkout_path: Path | str = '/checkout') -> dict[str, object]:
    """Return a valid configuration payload with one project mapping."""

    return {
        'api_base_url': 'http://127.0.0.1:8000/api/v1',
        'user_id': 'user-local',
        'poll_interval_seconds': 2,
        'harnesses': [{'kind': 'louie'}],
        'projects': [{
            'project_id': 'project-local',
            'worker_id': 'worker-1',
            'repository_path': str(checkout_path),
        }],
    }


def test_load_config_resolves_workspace_checkout(tmp_path: Path) -> None:
    """A runtime maps every configured project to one checkout path."""

    checkout_path = tmp_path / 'checkout'
    checkout_path.mkdir()
    payload = config_payload(checkout_path)
    payload['harnesses'] = [{'kind': 'louie'}, {'kind': 'codex_cli'}]
    config = load_config(write_config(tmp_path, payload))

    assert config.api_base_url == 'http://127.0.0.1:8000/api/v1'
    assert config.user_id == 'user-local'
    assert config.harnesses == (
        HarnessConfig(kind='louie'),
        HarnessConfig(kind='codex_cli', binary='codex'),
    )
    assert config.harness_kinds == ('louie', 'codex_cli')
    assert config.harness_binaries == {'codex_cli': 'codex'}
    assert config.checkout_for('project-local').repository_path == checkout_path
    assert config.checkout_for('project-local').worker_id == 'worker-1'


def test_load_config_rejects_duplicate_workspace_mapping(tmp_path: Path) -> None:
    """Duplicate mappings cannot make a claimed run choose an arbitrary checkout."""

    payload = config_payload()
    payload['projects'] = [
        {'project_id': 'project-local', 'worker_id': 'worker-1', 'repository_path': '/first'},
        {'project_id': 'project-local', 'worker_id': 'worker-2', 'repository_path': '/second'},
    ]

    with pytest.raises(ValueError, match='duplicate project_id'):
        load_config(write_config(tmp_path, payload))


def test_load_config_requires_user_identity(tmp_path: Path) -> None:
    """API communication cannot start without an explicit acting User."""

    payload = config_payload()
    del payload['user_id']

    with pytest.raises(ValueError, match='user_id'):
        load_config(write_config(tmp_path, payload))


@pytest.mark.parametrize(
    ('harnesses', 'message'),
    (
        (None, 'must be an array'),
        ([{'kind': 'louie'}, {'kind': 'louie'}], 'must not contain duplicates'),
        ([{'kind': 'louie'}, {'kind': 'unknown'}], 'unsupported Harness'),
    ),
)
def test_load_config_rejects_invalid_harness_declaration(
    tmp_path: Path,
    harnesses: object,
    message: str,
) -> None:
    """Harness declarations must be explicit, supported, and unambiguous."""

    payload = config_payload()
    payload['harnesses'] = harnesses

    with pytest.raises(ValueError, match=message):
        load_config(write_config(tmp_path, payload))


def test_load_config_accepts_a_cli_only_harness_declaration(tmp_path: Path) -> None:
    """Every supported Harness can be declared without Louie."""

    payload = config_payload()
    payload['harnesses'] = [{'kind': 'codex_cli', 'binary': '/opt/bin/codex'}]

    config = load_config(write_config(tmp_path, payload))

    assert config.harnesses == (
        HarnessConfig(kind='codex_cli', binary='/opt/bin/codex'),
    )
    assert config.harness_binaries == {'codex_cli': '/opt/bin/codex'}


def test_load_config_accepts_an_empty_harness_declaration(tmp_path: Path) -> None:
    """A runtime can remain connected while declaring no executable Harnesses."""

    payload = config_payload()
    payload['harnesses'] = []

    assert load_config(write_config(tmp_path, payload)).harnesses == ()


def test_validate_checkouts_requires_git_repository(tmp_path: Path) -> None:
    """A mapped directory must be a checkout before the runtime starts."""

    checkout_path = tmp_path / 'checkout'
    checkout_path.mkdir()
    config = load_config(write_config(tmp_path, config_payload(checkout_path)))

    with pytest.raises(ValueError, match='not a Git repository'):
        config.validate_checkouts()


def test_validate_checkouts_rejects_dirty_git_repository(tmp_path: Path) -> None:
    """Mapped checkouts cannot contain pre-existing changes to commit."""

    checkout_path = tmp_path / 'checkout'
    checkout_path.mkdir()
    subprocess.run(['git', '-C', str(checkout_path), 'init'], check=True)
    (checkout_path / 'unrelated.txt').write_text('do not commit\n', encoding='utf-8')
    config = load_config(write_config(tmp_path, config_payload(checkout_path)))

    with pytest.raises(ValueError, match='contains uncommitted changes'):
        config.validate_checkouts()


def test_validate_checkouts_accepts_clean_git_repository(tmp_path: Path) -> None:
    """A clean mapped Git checkout is valid for runtime execution."""

    checkout_path = tmp_path / 'checkout'
    checkout_path.mkdir()
    subprocess.run(['git', '-C', str(checkout_path), 'init'], check=True)
    config = load_config(write_config(tmp_path, config_payload(checkout_path)))

    config.validate_checkouts()


def test_persist_worker_id_completes_initial_project_provisioning(tmp_path: Path) -> None:
    """An API-generated worker ID is stored for subsequent runtime starts."""

    payload = config_payload()
    project = payload['projects'][0]
    assert isinstance(project, dict)
    project.pop('worker_id')
    path = write_config(tmp_path, payload)

    assert load_config(path).checkout_for('project-local').worker_id is None

    persist_worker_id(path, project_id='project-local', worker_id='worker-1')

    assert load_config(path).checkout_for('project-local').worker_id == 'worker-1'


def test_initialize_config_creates_a_first_start_configuration(tmp_path: Path) -> None:
    """First-start flags materialize a valid writable runtime configuration."""

    defaults_path = write_config(tmp_path, {
        'api_base_url': '',
        'user_id': '',
        'poll_interval_seconds': 2,
        'harnesses': [],
        'projects': [],
    })
    config_path = tmp_path / 'runtime-config' / 'runtime.json'

    created = initialize_config(
        config_path,
        defaults_path=defaults_path,
        api_base_url='http://host.docker.internal:2000/api/v1',
        user_id='local-user',
        project_id='local-project',
        repository_path='/workspaces/project',
        harnesses=('codex_cli',),
        poll_interval_seconds=None,
    )

    config = load_config(config_path)

    assert created is True
    assert config.api_base_url == 'http://host.docker.internal:2000/api/v1'
    assert config.poll_interval_seconds == 2
    assert config.harnesses == (HarnessConfig(kind='codex_cli', binary='codex'),)
    assert config.checkout_for('local-project').repository_path == Path('/workspaces/project')


def test_initialize_config_preserves_an_existing_configuration(tmp_path: Path) -> None:
    """First-start flags never replace a provisioned runtime configuration."""

    config_path = write_config(tmp_path, config_payload())

    created = initialize_config(
        config_path,
        defaults_path=config_path,
        api_base_url=None,
        user_id=None,
        project_id=None,
        repository_path=None,
        harnesses=(),
        poll_interval_seconds=None,
    )

    assert created is False
    assert load_config(config_path).user_id == 'user-local'
