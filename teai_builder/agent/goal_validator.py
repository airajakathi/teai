"""Goal validation system to prevent premature completion in autonomous loops."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger
from teai_builder.config.paths import get_runtime_subdir


@dataclass
class Goal:
    """Represents a sustained goal with completion criteria."""
    
    goal_id: str
    description: str
    success_criteria: list[str]
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "active"  # active | paused | completed | failed
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "description": self.description,
            "success_criteria": self.success_criteria,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Goal:
        return cls(
            goal_id=data["goal_id"],
            description=data["description"],
            success_criteria=data["success_criteria"],
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            status=data.get("status", "active"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ValidationResult:
    """Result of goal completion validation."""
    
    is_complete: bool
    confidence: float  # 0.0-1.0
    reasoning: str
    failed_criteria: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


class GoalValidator:
    """Validates whether a goal has been truly completed.
    
    Uses an independent judge model to prevent premature completion
    in autonomous loops (MiMo-Code pattern).
    """
    
    def __init__(self, storage_dir: Path | None = None):
        if storage_dir is None:
            storage_dir = get_runtime_subdir("goals")
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def _path_for(self, goal_id: str) -> Path:
        return self.storage_dir / f"{goal_id}.json"
    
    def save(self, goal: Goal) -> Path:
        """Save goal state to disk."""
        path = self._path_for(goal.goal_id)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(goal.to_dict(), f, indent=2)
        tmp.replace(path)
        return path
    
    def load(self, goal_id: str) -> Goal | None:
        """Load goal state from disk."""
        path = self._path_for(goal_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Goal.from_dict(data)
    
    def validate(
        self,
        goal: Goal,
        evidence: dict[str, Any],
        judge_provider: Any | None = None,
    ) -> ValidationResult:
        """Validate if goal is complete based on evidence.
        
        If judge_provider is available, uses LLM judgment.
        Otherwise uses heuristic validation.
        """
        if judge_provider is not None:
            return self._llm_validate(goal, evidence, judge_provider)
        return self._heuristic_validate(goal, evidence)
    
    def _heuristic_validate(self, goal: Goal, evidence: dict[str, Any]) -> ValidationResult:
        """Heuristic validation when no judge model is available."""
        failed_criteria = []
        suggestions = []
        
        for criterion in goal.success_criteria:
            criterion_lower = criterion.lower()
            evidence_keys = [k.lower() for k in evidence.keys()]
            
            # Check for common evidence patterns
            if "test" in criterion_lower and not any("test" in k for k in evidence_keys):
                failed_criteria.append(f"Missing test evidence for: {criterion}")
                suggestions.append("Run tests and include results in evidence")
            elif "build" in criterion_lower and not any("build" in k for k in evidence_keys):
                failed_criteria.append(f"Missing build evidence for: {criterion}")
                suggestions.append("Run build and include output in evidence")
            elif "deploy" in criterion_lower and not any("deploy" in k for k in evidence_keys):
                failed_criteria.append(f"Missing deployment evidence for: {criterion}")
                suggestions.append("Deploy and include live URL in evidence")
            elif "document" in criterion_lower and not any("doc" in k for k in evidence_keys):
                failed_criteria.append(f"Missing documentation for: {criterion}")
                suggestions.append("Create documentation files")
        
        is_complete = len(failed_criteria) == 0
        confidence = 1.0 if is_complete else max(0.0, 1.0 - len(failed_criteria) * 0.2)
        
        return ValidationResult(
            is_complete=is_complete,
            confidence=confidence,
            reasoning=f"Heuristic check: {len(failed_criteria)} criteria failed" if failed_criteria else "All criteria met",
            failed_criteria=failed_criteria,
            suggestions=suggestions,
        )
    
    def _llm_validate(
        self,
        goal: Goal,
        evidence: dict[str, Any],
        judge_provider: Any,
    ) -> ValidationResult:
        """Use LLM to judge goal completion."""
        prompt = f"""You are an independent judge evaluating whether a goal has been completed.

Goal: {goal.description}

Success Criteria:
{chr(10).join(f"- {c}" for c in goal.success_criteria)}

Evidence Provided:
{json.dumps(evidence, indent=2)}

Evaluate whether the goal has been completed. Respond with JSON:
{{
  "is_complete": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "explanation",
  "failed_criteria": ["list of unmet criteria"],
  "suggestions": ["next steps"]
}}"""
        
        try:
            response = judge_provider.generate(
                prompt=prompt,
                max_tokens=1024,
                temperature=0.1,
            )
            # Parse JSON from response
            content = response.content if hasattr(response, "content") else str(response)
            # Extract JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            data = json.loads(content.strip())
            return ValidationResult(
                is_complete=data.get("is_complete", False),
                confidence=data.get("confidence", 0.5),
                reasoning=data.get("reasoning", ""),
                failed_criteria=data.get("failed_criteria", []),
                suggestions=data.get("suggestions", []),
            )
        except Exception as e:
            logger.warning(f"LLM validation failed, falling back to heuristic: {e}")
            return self._heuristic_validate(goal, evidence)


# Global goal validator instance
_goal_validator: GoalValidator | None = None


def get_goal_validator() -> GoalValidator:
    """Get the global goal validator."""
    global _goal_validator
    if _goal_validator is None:
        try:
            _goal_validator = GoalValidator()
        except OSError:
            _goal_validator = GoalValidator(storage_dir=Path("/tmp/teai_builder_goals"))
    return _goal_validator
