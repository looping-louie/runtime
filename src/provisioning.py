"""Provision configured runtime workers once."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from configuration.runtime import RuntimeConfig, load_config, persist_worker_id


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
