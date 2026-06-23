"""Shared workflow models owned by llm3."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


class WorkflowState:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass
class WorkflowStep:
    step_id: str
    name: str
    prompt_template: str
    depends_on: list[str] = field(default_factory=list)
    max_retries: int = 0
    checkpoint_after: bool = False
    continue_on_error: bool = False
    run_if: str | None = None
    timeout_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowDefinition:
    workflow_id: str
    name: str
    description: str
    steps: list[WorkflowStep]
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowStepRun:
    step_id: str
    name: str
    state: str = WorkflowState.PENDING
    attempts: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    output: Any | None = None
    skipped_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowRun:
    run_id: str
    workflow_id: str
    goal_id: str
    state: str = WorkflowState.PENDING
    current_step: str | None = None
    step_results: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str | None = None
    cancel_requested: bool = False
    status_history: list[dict[str, Any]] = field(default_factory=list)
    step_states: dict[str, WorkflowStepRun] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
