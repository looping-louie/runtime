"""Value objects shared by Pipeline claim and execution components."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClaimedPipelineRun:
    """A worker-owned API run and the lease token authorizing its execution."""

    project_id: str
    pipeline_id: str
    run_id: str
    lease_token: str
    payload: dict[str, object]
