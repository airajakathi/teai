"""Auto-evaluation utilities for workflow runs."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowEvaluation:
    run_id: str
    workflow_id: str
    score: float = 0.0
    duration_s: float = 0.0
    retry_count: int = 0
    checkpoint_count: int = 0
    failure_reasons: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    evaluated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "score": self.score,
            "duration_s": self.duration_s,
            "retry_count": self.retry_count,
            "checkpoint_count": self.checkpoint_count,
            "failure_reasons": self.failure_reasons,
            "recommendations": self.recommendations,
            "evaluated_at": self.evaluated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowEvaluation:
        return cls(
            run_id=data["run_id"],
            workflow_id=data["workflow_id"],
            score=data.get("score", 0.0),
            duration_s=data.get("duration_s", 0.0),
            retry_count=data.get("retry_count", 0),
            checkpoint_count=data.get("checkpoint_count", 0),
            failure_reasons=data.get("failure_reasons", []),
            recommendations=data.get("recommendations", []),
            evaluated_at=data.get("evaluated_at", time.time()),
            metadata=data.get("metadata", {}),
        )


class AutoEvaluator:
    def __init__(self) -> None:
        self.scores: dict[str, list[float]] = {}

    def evaluate(self, run: Any) -> WorkflowEvaluation:
        duration_s = 0.0
        if run.started_at and run.finished_at:
            duration_s = max(0.0, run.finished_at - run.started_at)
        evaluation = WorkflowEvaluation(
            run_id=run.run_id,
            workflow_id=run.workflow_id,
            duration_s=duration_s,
            metadata=run.metadata or {},
        )
        if run.state == "completed":
            evaluation.score = 1.0
            evaluation.recommendations.append("Workflow succeeded; preserve current prompts.")
        else:
            evaluation.score = 0.0
            evaluation.failure_reasons = [run.error or "unknown"] if run.error else ["unknown"]
            evaluation.recommendations.append("Add retries to failed steps and review prompt clarity.")
        self.scores.setdefault(run.workflow_id, []).append(evaluation.score)
        return evaluation

    def avg_score(self, workflow_id: str) -> float:
        scores = self.scores.get(workflow_id) or []
        return sum(scores) / len(scores) if scores else 0.0
