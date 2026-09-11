"""Tests for the long-running runtime worker loop."""

from __future__ import annotations

import logging

import pytest

from polling.loop import run_forever


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


def test_run_forever_retries_runtime_error_after_waiting(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Operational worker failures are logged and retried after one delay."""

    worker = _FlakyWorker()
    intervals: list[float] = []

    def stop_after_second_wait(interval: float) -> None:
        """Record retry delays and stop after the successful retry cycle."""

        intervals.append(interval)
        if len(intervals) == 2:
            raise RuntimeError('stop test loop')

    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match='stop test loop'):
            run_forever(
                worker=worker,
                poll_interval_seconds=2.5,
                sleep=stop_after_second_wait,
            )

    assert worker.calls == 2
    assert intervals == [2.5, 2.5]
    assert 'Runtime worker poll failed' in caplog.text


def test_run_forever_propagates_non_operational_failure() -> None:
    """Unexpected worker defects remain visible instead of retrying indefinitely."""

    with pytest.raises(ValueError, match='invalid worker state'):
        run_forever(
            worker=_InvalidWorker(),
            poll_interval_seconds=2.5,
            sleep=lambda _: pytest.fail('Unexpected retry delay.'),
        )


class _FlakyWorker:
    """Fail one poll before succeeding on the next retry."""

    def __init__(self) -> None:
        """Initialize the current poll count."""

        self.calls = 0

    def run_once(self) -> int:
        """Raise one operational failure, then succeed."""

        self.calls += 1
        if self.calls == 1:
            raise RuntimeError('transient API failure')
        return 0


class _InvalidWorker:
    """Raise a non-operational error that must not enter retry handling."""

    def run_once(self) -> int:
        """Report an unexpected worker state."""

        raise ValueError('invalid worker state')
