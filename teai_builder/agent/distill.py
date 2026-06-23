"""Workflow mining utilities inspired by the `/distill` workflow."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from teai_builder.config.paths import get_runtime_subdir


@dataclass
class DistilledPattern:
    pattern_id: str
    name: str
    description: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "name": self.name,
            "description": self.description,
            "evidence": self.evidence,
            "tags": self.tags,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DistilledPattern:
        return cls(
            pattern_id=data["pattern_id"],
            name=data["name"],
            description=data.get("description", ""),
            evidence=data.get("evidence", []),
            tags=data.get("tags", []),
            created_at=data.get("created_at", time.time()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class DistilledSkill:
    skill_id: str
    name: str
    prompt_template: str
    source_patterns: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "prompt_template": self.prompt_template,
            "source_patterns": self.source_patterns,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DistilledSkill:
        return cls(
            skill_id=data["skill_id"],
            name=data["name"],
            prompt_template=data.get("prompt_template", ""),
            source_patterns=data.get("source_patterns", []),
            created_at=data.get("created_at", time.time()),
            metadata=data.get("metadata", {}),
        )


class Distiller:
    def __init__(self, storage_dir: Path | None = None) -> None:
        if storage_dir is None:
            storage_dir = get_runtime_subdir("distill")
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.storage_dir / f"{name}.json"

    def save_pattern(self, pattern: DistilledPattern) -> Path:
        path = self._path(pattern.pattern_id)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(pattern.to_dict(), f, indent=2)
        tmp.replace(path)
        return path

    def load_pattern(self, pattern_id: str) -> DistilledPattern | None:
        path = self._path(pattern_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return DistilledPattern.from_dict(json.load(f))

    def save_skill(self, skill: DistilledSkill) -> Path:
        path = self._path(skill.skill_id)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(skill.to_dict(), f, indent=2)
        tmp.replace(path)
        return path

    def load_skill(self, skill_id: str) -> DistilledSkill | None:
        path = self._path(skill_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return DistilledSkill.from_dict(json.load(f))

    def list_patterns(self) -> list[DistilledPattern]:
        patterns = []
        for path in self.storage_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    patterns.append(DistilledPattern.from_dict(json.load(f)))
            except (OSError, json.JSONDecodeError):
                continue
        patterns.sort(key=lambda p: p.created_at, reverse=True)
        return patterns

    def list_skills(self) -> list[DistilledSkill]:
        skills = []
        for path in self.storage_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    skills.append(DistilledSkill.from_dict(json.load(f)))
            except (OSError, json.JSONDecodeError):
                continue
        skills.sort(key=lambda s: s.created_at, reverse=True)
        return skills

    @staticmethod
    def summarize_workflow_run(run: Any) -> str:
        workflow_id = getattr(run, "workflow_id", "workflow")
        state = getattr(run, "state", "unknown")
        step_states = getattr(run, "step_states", {}) or {}
        completed = []
        failed = []
        skipped = []
        for step_id, step_run in step_states.items():
            step_state = getattr(step_run, "state", "")
            if step_state == "completed":
                completed.append(step_id)
            elif step_state == "failed":
                failed.append(step_id)
            elif step_state == "skipped":
                skipped.append(step_id)
        parts = [
            f"Workflow {workflow_id} finished with state {state}.",
        ]
        if completed:
            parts.append("Completed steps: " + ", ".join(completed) + ".")
        if failed:
            parts.append("Failed steps: " + ", ".join(failed) + ".")
        if skipped:
            parts.append("Skipped steps: " + ", ".join(skipped) + ".")
        error = getattr(run, "error", None)
        if error:
            parts.append(f"Error: {error}.")
        return " ".join(parts)

    @staticmethod
    def _keywords_for_run(run: Any, run_summary: str) -> list[str]:
        keywords: list[str] = []
        lowered = run_summary.lower()
        for keyword in ["scaffold", "plan", "implement", "review", "validate", "verify", "test", "build"]:
            if keyword in lowered:
                keywords.append(keyword)
        for step_id, step_run in (getattr(run, "step_states", {}) or {}).items():
            step_name = getattr(step_run, "name", step_id)
            for token in [str(step_id), str(step_name)]:
                token_lower = token.strip().lower().replace("_", " ")
                if any(word in token_lower for word in ["plan", "review", "validate", "verify", "build", "test", "scaffold", "implement"]):
                    keywords.append(token_lower.replace(" ", "_"))
        seen: set[str] = set()
        ordered: list[str] = []
        for keyword in keywords:
            normalized = keyword.strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered

    def mine_from_workflow_run(self, run_summary: str, run_metadata: dict[str, Any] | None = None) -> list[DistilledPattern]:
        findings: list[DistilledPattern] = []
        lowered = run_summary.lower()
        for keyword in ["scaffold", "plan", "implement", "review", "validate"]:
            if keyword in lowered:
                pattern = DistilledPattern(
                    pattern_id=hashlib.sha1(keyword.encode()).hexdigest()[:12],
                    name=f"Workflow keyword: {keyword}",
                    description=f"Detected workflow activity around '{keyword}' from run summary.",
                    evidence=[{"summary": run_summary[:300]}],
                    tags=["workflow", keyword],
                    metadata=run_metadata or {},
                )
                findings.append(pattern)
        for pattern in findings:
            self.save_pattern(pattern)
        return findings

    def mine_from_run(self, run: Any) -> list[DistilledPattern]:
        summary = self.summarize_workflow_run(run)
        metadata = dict(getattr(run, "metadata", {}) or {})
        metadata.update(
            {
                "workflow_id": getattr(run, "workflow_id", None),
                "run_id": getattr(run, "run_id", None),
                "state": getattr(run, "state", None),
            }
        )
        evidence = {
            "run_id": getattr(run, "run_id", None),
            "workflow_id": getattr(run, "workflow_id", None),
            "state": getattr(run, "state", None),
            "summary": summary[:300],
        }
        findings: list[DistilledPattern] = []
        workflow_id = str(getattr(run, "workflow_id", "workflow"))
        for keyword in self._keywords_for_run(run, summary):
            seed = f"{workflow_id}:{keyword}"
            pattern = DistilledPattern(
                pattern_id=hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12],
                name=f"{workflow_id}: {keyword}",
                description=f"Distilled from workflow `{workflow_id}` around `{keyword}`.",
                evidence=[evidence],
                tags=["workflow", workflow_id, keyword, str(getattr(run, "state", "unknown"))],
                metadata=metadata,
            )
            self.save_pattern(pattern)
            findings.append(pattern)
        return findings

    def mine_recent_runs(self, runs: list[Any]) -> list[DistilledPattern]:
        findings: list[DistilledPattern] = []
        for run in runs:
            findings.extend(self.mine_from_run(run))
        return findings

    def build_skill_from_patterns(self, skill_name: str, pattern_ids: list[str]) -> DistilledSkill:
        prompt_lines = [
            f"# {skill_name}",
            "Use this skill when executing similar workflows.",
            "Learned from prior successful patterns:",
        ]
        for pattern_id in pattern_ids:
            pattern = self.load_pattern(pattern_id)
            if pattern:
                prompt_lines.append(f"- {pattern.name}: {pattern.description}")
        skill = DistilledSkill(
            skill_id=hashlib.sha1(skill_name.encode()).hexdigest()[:12],
            name=skill_name,
            prompt_template="\n".join(prompt_lines),
            source_patterns=pattern_ids,
            metadata={"generated_from": "distill"},
        )
        self.save_skill(skill)
        return skill

    def refine_prompt(self, base_prompt: str, run_summary: str) -> str:
        additions: list[str] = []
        lowered = run_summary.lower()
        if "error" in lowered or "failed" in lowered:
            additions.append("If a step fails, retry it once before escalating.")
        if "checkpoint" in lowered:
            additions.append("Create a semantic checkpoint before risky steps.")
        if not additions:
            return base_prompt
        return base_prompt + "\n\nRefinements:\n" + "\n".join(f"- {item}" for item in additions)


# Global singleton
_distiller: Distiller | None = None


def get_distiller() -> Distiller:
    global _distiller
    if _distiller is None:
        try:
            _distiller = Distiller()
        except OSError:
            _distiller = Distiller(storage_dir=Path("/tmp/teai_builder_distill"))
    return _distiller
