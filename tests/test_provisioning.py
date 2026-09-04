"""Tests for one-time runtime worker provisioning."""

from __future__ import annotations

import json
from pathlib import Path

from configuration.runtime import load_config
from provisioning import provision_missing_workers


class FakeWorkerClient:
    """Record worker registrations."""

    def __init__(self) -> None:
        """Initialize the registration log."""

        self.provisions: list[tuple[str, tuple[str, ...]]] = []

    def provision(
        self,
        *,
        project_id: str,
        harnesses: tuple[str, ...],
    ) -> str:
        """Return a stable generated ID after recording the registration."""

        self.provisions.append((project_id, harnesses))
        return 'worker-generated'


def test_provision_missing_workers_persists_each_id_only_once(tmp_path: Path) -> None:
    """A missing worker is created once and reused after a configuration reload."""

    config_path = _write_config(tmp_path, worker_id=None)
    client = FakeWorkerClient()
    harnesses = ('louie', 'codex_cli')

    prepared = provision_missing_workers(
        config_path=config_path,
        config=load_config(config_path),
        client=client,
        harnesses=harnesses,
    )
    provision_missing_workers(
        config_path=config_path,
        config=load_config(config_path),
        client=client,
        harnesses=harnesses,
    )

    assert prepared.checkout_for('project-1').worker_id == 'worker-generated'
    assert client.provisions == [('project-1', harnesses)]


def _write_config(tmp_path: Path, *, worker_id: str | None) -> Path:
    """Write one provisioned or initial runtime configuration."""

    project: dict[str, object] = {
        'project_id': 'project-1',
        'repository_path': '/checkout',
    }
    if worker_id is not None:
        project['worker_id'] = worker_id
    path = tmp_path / 'runtime.json'
    path.write_text(
        json.dumps({
            'api_base_url': 'https://api.example/api/v1',
            'user_id': 'user-1',
            'poll_interval_seconds': 2,
            'projects': [project],
        }),
        encoding='utf-8',
    )
    return path
