"""Tests for configured local Harness capability validation."""

from __future__ import annotations

import subprocess

import pytest

from harnesses.capabilities import validate_harness_capabilities


def test_validate_harnesses_accepts_authenticated_codex() -> None:
    """Configured Codex requires a successful local login check."""

    calls: list[list[str]] = []

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        """Record successful Codex preflight commands."""

        calls.append(command)
        return subprocess.CompletedProcess(command, 0, '', '')

    validate_harness_capabilities(('louie', 'codex_cli'), run=run)

    assert calls == [['codex', 'login', 'status']]


def test_validate_harnesses_accepts_available_copilot() -> None:
    """Configured Copilot requires a successful executable preflight."""

    calls: list[list[str]] = []

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        """Record successful Harness preflight commands."""

        calls.append(command)
        return subprocess.CompletedProcess(command, 0, '', '')

    validate_harness_capabilities(('louie', 'copilot_cli'), run=run)

    assert calls == [['copilot', '--version']]


def test_validate_harnesses_rejects_unauthenticated_codex() -> None:
    """A failed login check prevents the runtime from starting with Codex."""

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        """Reject the local login check."""

        return subprocess.CompletedProcess(command, 1, '', '')

    with pytest.raises(RuntimeError, match='codex_cli'):
        validate_harness_capabilities(('louie', 'codex_cli'), run=run)


def test_validate_harnesses_rejects_missing_codex() -> None:
    """A missing configured executable prevents the runtime from starting."""

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        """Simulate an executable absent from PATH."""

        raise FileNotFoundError(command[0])

    with pytest.raises(RuntimeError, match='codex_cli'):
        validate_harness_capabilities(('louie', 'codex_cli'), run=run)
