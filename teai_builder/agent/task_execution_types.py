"""Shared task execution primitives for legacy and llm3 runtimes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class TaskStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    BLOCKED = auto()
    CANCELLED = auto()


@dataclass
class TaskResult:
    task_id: str
    status: TaskStatus
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    started_at: float = 0.0
    finished_at: float = 0.0
    upstream_ids: list[str] = field(default_factory=list)
    downstream_ids: list[str] = field(default_factory=list)


@dataclass
class ParallelTask:
    goal_id: str
    task_id: str
    description: str
    prompt: str
    model: str | None = None
    depends_on: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    metadata: dict[str, Any] = field(default_factory=dict)
