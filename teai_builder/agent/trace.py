"""Trace and span utilities for agent observability."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Span:
    span_id: str
    parent_id: str | None
    name: str
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def finish(self) -> None:
        self.finished_at = time.time()

    @property
    def duration_ms(self) -> float:
        started = self.started_at
        finished = self.finished_at or time.time()
        return max(0.0, (finished - started) * 1000)


@dataclass
class Trace:
    trace_id: str
    root_span_id: str
    spans: list[Span] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_span(self, span: Span) -> None:
        self.spans.append(span)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "root_span_id": self.root_span_id,
            "spans": [
                {
                    "span_id": span.span_id,
                    "parent_id": span.parent_id,
                    "name": span.name,
                    "started_at": span.started_at,
                    "finished_at": span.finished_at,
                    "duration_ms": span.duration_ms,
                    "attributes": span.attributes,
                }
                for span in self.spans
            ],
            "metadata": self.metadata,
        }


class TraceStore:
    def __init__(self) -> None:
        self.traces: dict[str, Trace] = {}

    def create_trace(self, trace_id: str, root_span_id: str, metadata: dict[str, Any] | None = None) -> Trace:
        trace = Trace(trace_id=trace_id, root_span_id=root_span_id, metadata=metadata or {})
        self.traces[trace_id] = trace
        return trace

    def get_trace(self, trace_id: str) -> Trace | None:
        return self.traces.get(trace_id)
