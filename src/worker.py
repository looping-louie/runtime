"""Poll configured workspaces and delegate claimed pipeline runs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from config import RuntimeConfig


@dataclass(frozen=True, slots=True)
class ClaimedPipelineRun:
    """A worker-owned API run and the lease token authorizing its execution."""

    pipeline_id: str
    run_id: str
    lease_token: str
    payload: dict[str, object]


class ClaimClient(Protocol):
    """Obtain queued pipeline runs from the API for one workspace."""

    def claim_next(
        self,
        *,
        workspace_id: str,
        worker_id: str,
    ) -> ClaimedPipelineRun | None:
        """Return one claimed run or None when no work is available."""


class RuntimeWorker:
    """Claim and execute at most one queued run from each mapped workspace."""

    def __init__(
        self,
        *,
        config: RuntimeConfig,
        claim_client: ClaimClient,
        execute_claim: Callable[[ClaimedPipelineRun, Path], None],
    ) -> None:
        """Store the workspace mapping, API client, and execution adapter."""

        self._config = config
        self._claim_client = claim_client
        self._execute_claim = execute_claim

    def run_once(self) -> int:
        """Claim and delegate one available pipeline run for each workspace."""

        claimed_count = 0
        for workspace in self._config.workspaces:
            claim = self._claim_client.claim_next(
                workspace_id=workspace.workspace_id,
                worker_id=self._config.worker_id,
            )
            if claim is None:
                continue
            self._execute_claim(claim, workspace.repository_path)
            claimed_count += 1
        return claimed_count