"""Provision configured runtime workers once."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from configuration.runtime import RuntimeConfig, load_config, persist_worker_id
from polling.loop import PollingWorker


class WorkerProvisioningClient(Protocol):
    """Create workers through the API control plane."""

    def provision(
        self,
        *,
        project_id: str,
        harnesses: tuple[str, ...],
    ) -> str:
        """Create one worker and return its API-generated ID."""

    def enable_project(self, *, worker_id: str, project_id: str) -> None:
        """Enable one worker to claim work for one Project."""


def provision_worker(
    *,
    config_path: str | Path,
    config: RuntimeConfig,
    client: WorkerProvisioningClient,
    harnesses: tuple[str, ...],
) -> RuntimeConfig:
    """Register one Worker and reconcile its Project enablements."""

    prepared = config
    if prepared.worker_id is None:
        worker_id = client.provision(
            project_id=prepared.projects[0].project_id,
            harnesses=harnesses,
        )
        persist_worker_id(
            config_path,
            worker_id=worker_id,
        )
        prepared = load_config(config_path)
    worker_id = prepared.require_worker_id()
    for project in prepared.projects:
        client.enable_project(worker_id=worker_id, project_id=project.project_id)
    return prepared


class ProvisioningRuntimeWorker:
    """Provision the runtime before delegating API polling to a configured worker."""

    def __init__(
        self,
        *,
        config_path: str | Path,
        config: RuntimeConfig,
        client: WorkerProvisioningClient,
        harnesses: tuple[str, ...],
        worker_factory: Callable[[RuntimeConfig], PollingWorker],
    ) -> None:
        """Store the provisioning dependencies and defer polling worker construction."""

        self._config_path = config_path
        self._config = config
        self._client = client
        self._harnesses = harnesses
        self._worker_factory = worker_factory
        self._worker: PollingWorker | None = None

    def run_once(self) -> int:
        """Provision once successfully, then run one normal polling cycle."""

        if self._worker is None:
            config = provision_worker(
                config_path=self._config_path,
                config=self._config,
                client=self._client,
                harnesses=self._harnesses,
            )
            self._config = config
            self._worker = self._worker_factory(config)
        return self._worker.run_once()
