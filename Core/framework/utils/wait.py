from __future__ import annotations

import time


def wait_until(predicate, timeout: float, interval: float = 0.2):
    """Waits for a predicate to return a truthy value."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    return predicate()
