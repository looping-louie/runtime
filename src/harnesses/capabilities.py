"""Detect locally executable Harness capabilities for worker provisioning."""

from __future__ import annotations

import os
import subprocess
from typing import Callable


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
