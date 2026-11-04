"""Tests for one-time runtime worker provisioning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from configuration.runtime import load_config
from polling.loop import run_forever
from provisioning import ProvisioningRuntimeWorker, provision_worker


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


def test_provisioning_worker_retries_api_outage_before_polling(tmp_path: Path) -> None:
    """An unavailable API delays startup without terminating the runtime process."""

    config_path = _write_config(tmp_path, worker_id=None)
    client = _FlakyWorkerClient()
    polling_worker = _PollingWorker()
    worker = ProvisioningRuntimeWorker(
        config_path=config_path,
        config=load_config(config_path),
        client=client,
        harnesses=('louie',),
        worker_factory=lambda _: polling_worker,
    )
    intervals: list[float] = []

    def stop_after_second_wait(interval: float) -> None:
        """Stop after the failed provisioning cycle and its successful retry."""

        intervals.append(interval)
        if len(intervals) == 2:
            raise RuntimeError('stop test loop')

    with pytest.raises(RuntimeError, match='stop test loop'):
        run_forever(
            worker=worker,
            poll_interval_seconds=2.5,
            sleep=stop_after_second_wait,
        )

    assert client.provision_attempts == 2
    assert polling_worker.calls == 1
    assert intervals == [2.5, 2.5]


class _FlakyWorkerClient(FakeWorkerClient):
    """Fail the first registration attempt to simulate an unavailable API."""

    def __init__(self) -> None:
        """Initialize the registration attempt counter."""

        super().__init__()
        self.provision_attempts = 0

    def provision(
        self,
        *,
        project_id: str,
        harnesses: tuple[str, ...],
    ) -> str:
        """Reject the initial request and delegate the retry to the fake client."""

        self.provision_attempts += 1
        if self.provision_attempts == 1:
            raise RuntimeError('connection refused')
        return super().provision(project_id=project_id, harnesses=harnesses)


class _PollingWorker:
    """Record polling after successful provisioning."""

    def __init__(self) -> None:
        """Initialize the polling counter."""

        self.calls = 0

    def run_once(self) -> int:
        """Record one delegated polling cycle."""

        self.calls += 1
        return 0


def _write_config(tmp_path: Path, *, worker_id: str | None) -> Path:
    """Write one provisioned or initial runtime configuration."""

    path = tmp_path / '.env.json'
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
