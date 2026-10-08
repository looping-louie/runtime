"""Tests for one-time runtime worker provisioning."""

from __future__ import annotations

import json
from pathlib import Path

from configuration.runtime import load_config
from provisioning import provision_worker


class FakeWorkerClient:
    """Record worker registrations."""

    def __init__(self) -> None:
        """Initialize the registration log."""

        self.provisions: list[tuple[str, tuple[str, ...]]] = []
        self.enablements: list[tuple[str, str]] = []

    def provision(
        self,
        *,
        project_id: str,
        harnesses: tuple[str, ...],
    ) -> str:
        """Return a stable generated ID after recording the registration."""

        self.provisions.append((project_id, harnesses))
        return 'worker-generated'

    def enable_project(self, *, worker_id: str, project_id: str) -> None:
        """Record one Worker Project enablement."""

        self.enablements.append((worker_id, project_id))


def test_provision_worker_persists_one_id_and_enables_every_project(tmp_path: Path) -> None:
    """A Worker is created once and reconciles every Project assignment."""

    config_path = _write_config(tmp_path, worker_id=None)
    client = FakeWorkerClient()
    harnesses = ('louie', 'codex_cli')

    prepared = provision_worker(
        config_path=config_path,
        config=load_config(config_path),
        client=client,
        harnesses=harnesses,
    )
    provision_worker(
        config_path=config_path,
        config=load_config(config_path),
        client=client,
        harnesses=harnesses,
    )

    assert prepared.require_worker_id() == 'worker-generated'
    assert client.provisions == [('project-1', harnesses)]
    assert client.enablements == [
        ('worker-generated', 'project-1'),
        ('worker-generated', 'project-1'),
    ]


def _write_config(tmp_path: Path, *, worker_id: str | None) -> Path:
    """Write one provisioned or initial runtime configuration."""

    path = tmp_path / 'runtime.json'
    payload: dict[str, object] = {
            'api_base_url': 'https://api.example/api/v1',
            'user_id': 'user-1',
            'poll_interval_seconds': 2,
            'harnesses': [
                {'kind': 'louie'},
                {'kind': 'codex_cli'},
            ],
            'projects': [{
                'project_id': 'project-1',
                'repository_path': '/checkout',
            }],
        }
    if worker_id is not None:
        payload['worker_id'] = worker_id
    path.write_text(
        json.dumps(payload),
        encoding='utf-8',
    )
    return path
