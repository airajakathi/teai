"""Task dependency management and result merging for parallel agent work."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from teai_builder.config.paths import get_runtime_subdir


class DependencyError(Exception):
    """Raised when task dependencies cannot be satisfied."""


@dataclass
class TaskNode:
    task_id: str
    description: str
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class DependencyGraph:
    def __init__(self) -> None:
        self._nodes: dict[str, TaskNode] = {}
        self._edges: dict[str, set[str]] = {}

    def add_task(self, task: TaskNode) -> None:
        self._nodes[task.task_id] = task
        self._edges.setdefault(task.task_id, set())
        for dep in task.depends_on:
            self._edges.setdefault(dep, set()).add(task.task_id)

    def validate(self) -> None:
        visited: set[str] = set()
        temp: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in temp:
                raise DependencyError(f"Cyclic dependency detected involving {node_id}")
            if node_id in visited:
                return
            temp.add(node_id)
            for dep in self._nodes[node_id].depends_on:
                if dep not in self._nodes:
                    raise DependencyError(f"Missing dependency {dep} for task {node_id}")
                visit(dep)
            temp.remove(node_id)
            visited.add(node_id)

        for node_id in self._nodes:
            visit(node_id)

    def topological_order(self) -> list[str]:
        self.validate()
        visited: set[str] = set()
        order: list[str] = []

        def visit(node_id: str) -> None:
            if node_id in visited:
                return
            visited.add(node_id)
            for dep in self._nodes[node_id].depends_on:
                visit(dep)
            order.append(node_id)

        for node_id in self._nodes:
            visit(node_id)
        return order

    def ready_tasks(self, completed: set[str]) -> list[str]:
        ready = []
        for task_id, node in self._nodes.items():
            if task_id in completed:
                continue
            if all(dep in completed for dep in node.depends_on):
                ready.append(task_id)
        return ready


@dataclass
class MergedResult:
    task_id: str
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)


class ResultMerger:
    def __init__(self, storage_dir: Path | None = None) -> None:
        if storage_dir is None:
            storage_dir = get_runtime_subdir("results")
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def merge(self, results: dict[str, dict[str, Any]]) -> MergedResult:
        merged: dict[str, Any] = {}
        warnings: list[str] = []
        conflicts: list[dict[str, Any]] = []
        status = "completed"

        for task_id, result in results.items():
            task_status = result.get("status", "unknown")
            if task_status != "completed":
                status = task_status
                warnings.append(f"Task {task_id} ended with status {task_status}")

            output = result.get("output", {})
            for key, value in output.items():
                if key in merged:
                    conflicts.append({
                        "key": key,
                        "task_id": task_id,
                        "existing_value": merged[key],
                        "new_value": value,
                    })
                    warnings.append(f"Key conflict on {key} from {task_id}")
                else:
                    merged[key] = value

        summary = MergedResult(
            task_id="merged",
            status=status,
            output=merged,
            warnings=warnings,
            conflicts=conflicts,
        )
        self._persist(summary)
        return summary

    def _persist(self, result: MergedResult) -> Path:
        timestamp = int(time.time())
        path = self.storage_dir / f"merge_{timestamp}.json"
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({
                "task_id": result.task_id,
                "status": result.status,
                "output": result.output,
                "warnings": result.warnings,
                "conflicts": result.conflicts,
            }, f, indent=2)
        tmp.replace(path)
        return path
