"""Metrics collection for agent runs."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricPoint:
    name: str
    value: float
    recorded_at: float = field(default_factory=time.time)
    labels: dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    def __init__(self) -> None:
        self.points: list[MetricPoint] = []

    def record(self, name: str, value: float, **labels: str) -> None:
        self.points.append(MetricPoint(name=name, value=value, labels=labels))

    def summarize(self, name: str) -> dict[str, float]:
        values = [point.value for point in self.points if point.name == name]
        if not values:
            return {"count": 0.0}
        return {
            "count": float(len(values)),
            "sum": float(sum(values)),
            "avg": float(sum(values) / len(values)),
            "min": float(min(values)),
            "max": float(max(values)),
        }
