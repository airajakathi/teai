"""Health check utilities for the agent runtime."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HealthStatus:
    healthy: bool
    checks: dict[str, bool] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: float = field(default_factory=time.time)


class HealthCheck:
    def __init__(self) -> None:
        self.checks: dict[str, tuple[Any, bool]] = {}

    def register(self, name: str, checker: Any, critical: bool = True) -> None:
        self.checks[name] = (checker, critical)

    def run(self) -> HealthStatus:
        checks: dict[str, bool] = {}
        details: dict[str, Any] = {}
        for name, (checker, critical) in self.checks.items():
            try:
                result = checker()
                healthy = bool(result)
            except Exception as exc:
                healthy = False
                details[name] = {"error": str(exc)}
            else:
                details[name] = {"result": result}
            checks[name] = healthy
        healthy = all(value for value in checks.values())
        return HealthStatus(healthy=healthy, checks=checks, details=details)
