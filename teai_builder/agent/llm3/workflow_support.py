"""Workflow support helpers owned by llm3."""

from __future__ import annotations

from .workflow_models import WorkflowStep


class ContextCompactor:
    """Compacts workflow context when context size grows too large."""

    def __init__(self, max_chars: int = 12000) -> None:
        self.max_chars = max_chars

    def compact(self, context: str) -> str:
        if len(context) <= self.max_chars:
            return context
        head = context[: self.max_chars // 2]
        tail = context[-self.max_chars // 2 :]
        return "\n".join([head, "...", "... context trimmed ...", "...", tail])


class SemanticCheckpointTrigger:
    """Suggests checkpoint creation based on workflow semantics."""

    def __init__(self, keywords: tuple[str, ...] | None = None) -> None:
        self.keywords = keywords or (
            "scaffold",
            "plan",
            "implement",
            "review",
            "validate",
        )

    def should_checkpoint(self, step: WorkflowStep) -> bool:
        text = f"{step.step_id} {step.name} {step.prompt_template}".lower()
        return any(keyword in text for keyword in self.keywords)
