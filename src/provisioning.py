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


def provision_missing_workers(
    *,
    config_path: str | Path,
    config: RuntimeConfig,
    client: WorkerProvisioningClient,
    harnesses: tuple[str, ...],
) -> RuntimeConfig:
    """Provision missing workers once and persist every API-generated ID."""

    prepared = config
    for project in prepared.projects:
        if project.worker_id is not None:
            continue
        worker_id = client.provision(
            project_id=project.project_id,
            harnesses=harnesses,
        )
        # Persist each successful registration before another remote call can fail.
        persist_worker_id(
            config_path,
            project_id=project.project_id,
            worker_id=worker_id,
        )
        prepared = load_config(config_path)
    return prepared
