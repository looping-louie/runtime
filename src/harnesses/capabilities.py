"""Validate configured local Harness capabilities for worker provisioning."""

from __future__ import annotations

import os
import subprocess
from typing import Callable


def validate_harness_capabilities(
    harnesses: tuple[str, ...],
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Require every configured Harness executable to be locally ready."""

    checks = {
        'codex_cli': [_command('LOUIE_CODEX_BINARY', 'codex'), 'login', 'status'],
        'copilot_cli': [_command('LOUIE_COPILOT_BINARY', 'copilot'), '--version'],
    }
    for harness in harnesses:
        command = checks.get(harness)
        if command is not None and not _command_succeeds(command, run=run):
            raise RuntimeError(
                f"Configured Harness {harness!r} is unavailable: "
                f"{' '.join(command)!r} did not succeed."
            )


def _command(variable: str, default: str) -> str:
    """Return the configured Harness command or an empty invalid command."""

    return os.environ.get(variable, default).strip()


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
