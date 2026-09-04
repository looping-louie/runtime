"""Keep one Pipeline claim lease active during a blocking local action."""

from __future__ import annotations

from threading import Event, Thread
from types import TracebackType
from typing import Callable


class LeaseKeepalive:
    """Renew a lease periodically until its blocking action finishes."""

    def __init__(
        self,
        *,
        renew: Callable[[], None],
        interval_seconds: float,
    ) -> None:
        """Store the renewal callback and its positive interval."""

        if interval_seconds <= 0:
            raise ValueError('Lease keepalive interval must be positive.')
        self._renew = renew
        self._interval_seconds = interval_seconds
        self._stop = Event()
        self._error: Exception | None = None
        self._thread = Thread(
            target=self._run,
            name='pipeline-lease-keepalive',
            daemon=True,
        )

    def __enter__(self) -> LeaseKeepalive:
        """Start periodic renewal in a daemon thread."""

        self._thread.start()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """Stop renewal and surface its failure after a successful action."""

        del exception, traceback
        self._stop.set()
        self._thread.join()
        if exception_type is None and self._error is not None:
            raise RuntimeError(
                f'Pipeline lease keepalive failed: {self._error}'
            ) from self._error
        return False

    def _run(self) -> None:
        """Renew after each interval until stopped or rejected by the API."""

        while not self._stop.wait(self._interval_seconds):
            try:
                self._renew()
            except Exception as error:
                self._error = error
                self._stop.set()
                return
