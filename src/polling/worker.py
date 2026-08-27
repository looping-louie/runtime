"""Poll configured projects and delegate claimed pipeline runs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from configuration.runtime import RuntimeConfig
from runs.models import ClaimedPipelineRun


LOGGER = logging.getLogger(__name__)


class ClaimClient(Protocol):
    """Obtain queued pipeline runs from the API for one project."""

    def claim_next(
        self,
        *,
        project_id: str,
        worker_id: str,
    ) -> ClaimedPipelineRun | None:
        """Return one claimed run or None when no work is available."""


class WorkerHeartbeatClient(Protocol):
    """Refresh liveness signals for provisioned runtime identities."""

    def heartbeat(self, *, project_id: str, worker_id: str) -> None:
        """Record one worker liveness heartbeat."""


class RuntimeWorker:
    """Claim and execute at most one queued run from each mapped project."""

    def __init__(
        self,
        *,
        config: RuntimeConfig,
        claim_client: ClaimClient,
        heartbeat_client: WorkerHeartbeatClient | None = None,
        execute_claim: Callable[[ClaimedPipelineRun, Path], None],
    ) -> None:
        """Store the project mapping, API client, and execution adapter."""

        self._config = config
        self._claim_client = claim_client
        self._heartbeat_client = heartbeat_client
        self._execute_claim = execute_claim

    def run_once(self) -> int:
        """Claim and delegate one available pipeline run for each project."""

        claimed_count = 0
        for project in self._config.projects:
            try:
                if self._heartbeat_client is not None:
                    self._heartbeat_client.heartbeat(
                        project_id=project.project_id,
                        worker_id=project.worker_id,
                    )
                claim = self._claim_client.claim_next(
                    project_id=project.project_id,
                    worker_id=project.worker_id,
                )
                if claim is None:
                    continue
                self._execute_claim(claim, project.repository_path)
                claimed_count += 1
            except RuntimeError:
                LOGGER.exception(
                    'Runtime worker failed for project %s; continuing with other projects.',
                    project.project_id,
                )
        return claimed_count
