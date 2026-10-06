"""Validate configured local Harness capabilities for worker provisioning."""

from __future__ import annotations

import subprocess
from typing import Callable

from configuration.runtime import HarnessConfig


def validate_harness_capabilities(
    harnesses: tuple[HarnessConfig, ...],
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Require every configured Harness executable to be locally ready."""

    checks = {
        'codex_cli': ['login', 'status'],
        'copilot_cli': ['--version'],
    }
    for harness in harnesses:
        arguments = checks.get(harness.kind)
        if arguments is None:
            continue
        if harness.binary is None:
            raise RuntimeError(f'Configured Harness {harness.kind!r} has no binary.')
        command = [harness.binary, *arguments]
        if not _command_succeeds(command, run=run):
            raise RuntimeError(
                f"Configured Harness {harness.kind!r} is unavailable: "
                f"{' '.join(command)!r} did not succeed."
            )


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
