"""Resilience helpers for agent runtime and tool execution."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    failures: int = 0
    opened_at: float | None = None
    last_error: str | None = None

    def allow_request(self) -> bool:
        if self.opened_at is None:
            return True
        if time.time() - self.opened_at >= self.recovery_timeout:
            self.opened_at = None
            self.failures = 0
            return True
        return False

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None
        self.last_error = None

    def record_failure(self, error: BaseException | str | None = None) -> None:
        self.failures += 1
        message = str(error) if error is not None else "unknown error"
        self.last_error = message
        if self.failures >= self.failure_threshold:
            self.opened_at = time.time()


async def retry(
    fn: Callable[..., Awaitable[Any]],
    *args: Any,
    retries: int = 2,
    delay: float = 1.0,
    **kwargs: Any,
) -> Any:
    last_error: BaseException | None = None
    for attempt in range(1, max(retries, 1) + 1):
        try:
            return await fn(*args, **kwargs)
        except BaseException as exc:
            last_error = exc
            if attempt < max(retries, 1):
                await asyncio.sleep(min(delay * attempt, 10.0))
    if last_error is not None:
        raise last_error
    raise RuntimeError("retry failed without an exception")
