"""Long-running polling loop for the configured runtime worker."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol


LOGGER = logging.getLogger(__name__)


class PollingWorker(Protocol):
    """Perform one bounded scan for queue work."""

    def run_once(self) -> int:
        """Claim and execute available work once."""


def run_forever(
    *,
    worker: PollingWorker,
    poll_interval_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Poll indefinitely while allowing a failed claim cycle to recover on retry."""

    while True:
        try:
            worker.run_once()
        except Exception:
            LOGGER.exception('Runtime worker poll failed; retrying after delay.')
        sleep(poll_interval_seconds)
