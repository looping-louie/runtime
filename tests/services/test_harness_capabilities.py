"""Tests for local Harness capability detection."""

from __future__ import annotations

import subprocess

from harnesses.capabilities import (
    HarnessCapabilityDetector,
    detect_harness_capabilities,
)


def test_detect_harnesses_includes_authenticated_codex() -> None:
    """Codex is advertised only after executable and login checks succeed."""

    calls: list[list[str]] = []

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        """Record successful Codex preflight commands."""

        calls.append(command)
        return subprocess.CompletedProcess(command, 0, '', '')

    capabilities = detect_harness_capabilities(run=run)

    assert capabilities == ('louie', 'codex_cli')
    assert calls == [['codex', '--version'], ['codex', 'login', 'status']]


def test_detect_harnesses_omits_unauthenticated_codex() -> None:
    """A failed login check prevents the worker from claiming Codex runs."""

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        """Make only the executable check succeed."""

        return subprocess.CompletedProcess(
            command,
            0 if command[-1] == '--version' else 1,
            '',
            '',
        )

    assert detect_harness_capabilities(run=run) == ('louie',)


def test_detect_harnesses_omits_missing_codex() -> None:
    """A missing configured executable leaves Louie as the sole capability."""

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        """Simulate an executable absent from PATH."""

        raise FileNotFoundError(command[0])

    assert detect_harness_capabilities(run=run) == ('louie',)


def test_capability_detector_refreshes_authentication_after_interval() -> None:
    """A later heartbeat can advertise Codex after local login succeeds."""

    now = [0.0]
    observed = iter((('louie',), ('louie', 'codex_cli')))
    detector = HarnessCapabilityDetector(
        refresh_interval_seconds=30,
        clock=lambda: now[0],
        detect=lambda: next(observed),
    )

    assert detector.current() == ('louie',)
    now[0] = 29
    assert detector.current() == ('louie',)
    now[0] = 30
    assert detector.current() == ('louie', 'codex_cli')
