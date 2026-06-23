"""GitHub pull request and review tooling."""

from __future__ import annotations

import os
from typing import Any

from teai_builder.agent.tools.base import Tool, tool_parameters
from teai_builder.agent.tools.schema import (
    BooleanSchema,
    StringSchema,
    tool_parameters_schema,
)


def _gh(args: list[str]) -> tuple[int, str, str]:
    completed = __import__("subprocess").run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


@tool_parameters(
    tool_parameters_schema(
        title=StringSchema("Pull request title"),
        body=StringSchema("Pull request description", nullable=True),
        head=StringSchema("Source branch"),
        base=StringSchema("Target branch", nullable=True),
        draft=BooleanSchema(description="Create as draft PR", default=False, nullable=True),
        required=["title", "head"],
    )
)
class CreatePullRequestTool(Tool):
    """Create a GitHub pull request from the current repository."""

    _scopes = {"core", "subagent"}

    @property
    def name(self) -> str:
        return "create_pull_request"

    @property
    def description(self) -> str:
        return "Create a GitHub pull request using gh."

    async def execute(
        self,
        title: str,
        head: str,
        base: str | None = "main",
        body: str | None = None,
        draft: bool | None = False,
        **kwargs: Any,
    ) -> Any:
        if not self._has_gh():
            return "Error: gh CLI is not available."

        args = ["pr", "create", "--title", title, "--head", head, "--base", base or "main"]
        if body:
            args.extend(["--body", body])
        if draft:
            args.append("--draft")

        code, stdout, stderr = _gh(args)
        if code != 0:
            return f"Error creating PR:\n{stderr or stdout}"
        return stdout.strip()

    @staticmethod
    def _has_gh() -> bool:
        return __import__("shutil").which("gh") is not None


@tool_parameters(
    tool_parameters_schema(
        pr_number=StringSchema("Pull request number or URL"),
        body=StringSchema("Review comment text"),
        event=StringSchema(
            "Review event",
            enum=["APPROVE", "REQUEST_CHANGES", "COMMENT"],
            nullable=True,
        ),
        required=["pr_number", "body"],
    )
)
class ReviewPullRequestTool(Tool):
    """Submit a GitHub pull request review."""

    _scopes = {"core", "subagent"}

    @property
    def name(self) -> str:
        return "review_pull_request"

    @property
    def description(self) -> str:
        return "Submit a review on a GitHub pull request using gh."

    async def execute(
        self,
        pr_number: str,
        body: str,
        event: str | None = "COMMENT",
        **kwargs: Any,
    ) -> Any:
        if not self._has_gh():
            return "Error: gh CLI is not available."

        event_flag = "comment" if not event or event == "COMMENT" else event.lower().replace("_", "-")
        args = [
            "pr",
            "review",
            pr_number,
            f"--{event_flag}",
            "--body",
            body,
        ]

        code, stdout, stderr = _gh(args)
        if code != 0:
            return f"Error reviewing PR:\n{stderr or stdout}"
        return stdout.strip()

    @staticmethod
    def _has_gh() -> bool:
        return __import__("shutil").which("gh") is not None
