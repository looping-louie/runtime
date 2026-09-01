"""Detect locally executable Harness capabilities for worker provisioning."""

from __future__ import annotations

import os
import subprocess
from time import monotonic
from typing import Callable


class HarnessCapabilityDetector:
    """Cache local Harness readiness for bounded heartbeat refreshes."""

    def __init__(
        self,
        *,
        refresh_interval_seconds: float = 30,
        clock: Callable[[], float] = monotonic,
        detect: Callable[[], tuple[str, ...]] | None = None,
    ) -> None:
        """Store the refresh cadence and injectable detection boundaries."""

        self._refresh_interval_seconds = refresh_interval_seconds
        self._clock = clock
        self._detect = detect or detect_harness_capabilities
        self._capabilities: tuple[str, ...] | None = None
        self._refresh_after = 0.0

    def current(self) -> tuple[str, ...]:
        """Return recent capabilities, refreshing local authentication when stale."""

        now = self._clock()
        if self._capabilities is None or now >= self._refresh_after:
            self._capabilities = self._detect()
            self._refresh_after = now + self._refresh_interval_seconds
        return self._capabilities


def detect_harness_capabilities(
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[str, ...]:
    """Advertise Codex only when its executable and local login are usable."""

    capabilities = ['louie']
    command = os.environ.get('LOUIE_CODEX_COMMAND', 'codex').strip()
    if command and _command_succeeds([command, '--version'], run=run) and _command_succeeds(
        [command, 'login', 'status'], run=run,
    ):
        capabilities.append('codex_cli')
    return tuple(capabilities)


def _command_succeeds(
    command: list[str],
    *,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> bool:
    """Return whether one bounded, non-interactive capability check succeeds."""

    try:
        result = run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
