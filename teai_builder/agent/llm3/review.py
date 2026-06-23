"""Phase 1 deterministic review gate for bridged execution."""

from __future__ import annotations

import uuid

from .types import ExecutionResult, ReviewDecision


def build_review_decision(result: ExecutionResult) -> ReviewDecision:
    """Create a minimal structured review decision for phase 1."""

    decision = "accept"
    rationale = "Execution completed successfully."
    unmet_criteria: list[str] = []
    if result.status == "failed":
        decision = "retry"
        rationale = "Execution failed and should be retried or revised."
        unmet_criteria.append("Execution did not complete successfully.")
    elif result.status == "partial":
        decision = "revise"
        rationale = "Execution only partially completed and needs a refined follow-up pass."
        unmet_criteria.append("Execution completed partially.")
    elif result.status == "cancelled":
        decision = "ask_user"
        rationale = "Execution was cancelled and needs explicit user direction."
        unmet_criteria.append("Execution was cancelled.")
    return ReviewDecision(
        review_id=f"review-{uuid.uuid4().hex[:10]}",
        turn_id=result.turn_id,
        request_id=result.request_id,
        decision=decision,
        rationale=rationale,
        unmet_criteria=unmet_criteria,
    )
