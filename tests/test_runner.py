"""Tests for the long-running runtime worker loop."""

from __future__ import annotations

import pytest

from runner import run_forever


class FakeWorker:
    """Count polling invocations made by the runtime loop."""

    def __init__(self) -> None:
        """Initialize the poll invocation counter."""

        self.calls = 0

    def run_once(self) -> int:
        """Record one worker poll iteration."""

        self.calls += 1
        return 0


def test_run_forever_polls_then_waits_for_configured_interval() -> None:
    """The runtime sleeps only after each completed worker poll."""

    worker = FakeWorker()
    intervals: list[float] = []

    def stop_after_wait(interval: float) -> None:
        """Record the wait and stop the otherwise infinite runtime loop."""

        intervals.append(interval)
        raise RuntimeError('stop test loop')

    with pytest.raises(RuntimeError, match='stop test loop'):
        run_forever(worker=worker, poll_interval_seconds=2.5, sleep=stop_after_wait)

    assert worker.calls == 1
    assert intervals == [2.5]
