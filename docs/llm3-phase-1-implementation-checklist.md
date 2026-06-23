# LLM3 Phase 1 Implementation Checklist

## Status

Draft phase 1 implementation checklist.

This document defines the first safe implementation slice for the new
`LLM1 / LLM2 / LLM3` architecture.

It is intentionally narrow.

Phase 1 is not:

- full executive intelligence
- full worker runtime replacement
- full task graph adoption
- full multimodal unification

Phase 1 is:

- introducing the new orchestration contract into the live runtime safely

## Phase 1 Goal

The goal of phase 1 is to put the new architecture into the live runtime in the
smallest real way possible.

At the end of phase 1, the runtime should have:

- a canonical `UnifiedTurn`
- a basic orchestration mode decision
- a structured `ExecutionBrief`
- a minimal execution bridge on top of the current runtime
- a minimal structured review decision

This is the first point where the architecture stops being docs only.

## Scope Boundary

Phase 1 must stay inside this boundary:

- shared types
- turn normalization
- mode selection
- execution brief creation
- execution bridge
- minimal review gate
- basic observability metadata/events

Phase 1 must not attempt:

- full `LLM1` reasoning
- full `LLM2` critique reasoning
- full worker runtime rewrite
- full task graph engine
- full capability router
- UI redesign

## Deliverables

Phase 1 should produce:

- new `llm3` runtime module skeleton
- canonical shared dataclasses/types
- turn builder
- mode selector
- execution brief builder
- execution bridge wrapper
- review decision stub
- integration into the current loop
- focused tests

## Checklist

## A. New Runtime Module Skeleton

- [ ] create new package `teai_builder/agent/llm3/`
- [ ] add `__init__.py`
- [ ] add `types.py`
- [ ] add `turn_builder.py`
- [ ] add `mode_selector.py`
- [ ] add `execution_bridge.py`
- [ ] add `review.py`

## B. Shared Types

- [ ] define `UnifiedTurn`
- [ ] define minimal `ExecutionBrief`
- [ ] define minimal `ExecutionResult`
- [ ] define minimal `ReviewDecision`
- [ ] add serialization helpers if needed

## C. Turn Builder

- [ ] build `UnifiedTurn` from current `InboundMessage`
- [ ] include `turn_id`
- [ ] include `session_key`
- [ ] include content, media, metadata, and workspace scope summary
- [ ] ensure image/audio/video/file arrays normalize consistently

## D. Mode Selector

- [ ] add deterministic phase-1 mode selector
- [ ] support at least `direct` and `assisted`
- [ ] optionally support provisional `delegated` / `workflow` heuristics without activating deep behavior yet
- [ ] keep decisions observable in metadata/state

## E. Execution Brief Builder

- [ ] create minimal brief from `UnifiedTurn`
- [ ] include `request_id`
- [ ] include objective
- [ ] include success criteria
- [ ] include constraints
- [ ] include allowed capabilities summary

## F. Execution Bridge

- [ ] create bridge that accepts `ExecutionBrief`
- [ ] adapt it to current loop/runner execution path
- [ ] return structured `ExecutionResult`
- [ ] preserve current runtime behavior as much as possible

## G. Review Stub

- [ ] add minimal `ReviewDecision` builder
- [ ] mark successful phase-1 execution as `accept`
- [ ] mark obvious execution failure as `retry` or `revise`
- [ ] keep this deterministic for now

## H. Live Integration

- [ ] integrate new turn builder into [loop.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/loop.py)
- [ ] integrate mode selection before current run phase
- [ ] attach execution brief to turn context
- [ ] run current execution through the bridge
- [ ] store review decision on the turn context or metadata

## I. Observability

- [ ] include minimal orchestration metadata for debugging
- [ ] emit or record the selected mode
- [ ] emit or record request id
- [ ] emit or record review outcome

## J. Tests

- [ ] add unit tests for `turn_builder`
- [ ] add unit tests for `mode_selector`
- [ ] add unit tests for `execution_bridge`
- [ ] add focused integration test for loop metadata / orchestration contract path

## K. Diagnostics

- [ ] run diagnostics on all edited Python files
- [ ] run focused pytest slice for the new runtime modules and touched loop behavior

## Recommended Module Interfaces

Phase 1 should implement at least these interfaces:

```python
def build_unified_turn(...) -> UnifiedTurn
def select_mode(...) -> str
def build_execution_brief(...) -> ExecutionBrief

class ExecutionBridge:
    async def execute(...) -> ExecutionResult: ...

def build_review_decision(...) -> ReviewDecision
```

## Recommended Integration Shape

The first runtime wiring should look roughly like:

```python
unified_turn = build_unified_turn(...)
mode = select_mode(unified_turn, ...)
execution_brief = build_execution_brief(unified_turn, mode, ...)
execution_result = await execution_bridge.execute(execution_brief, ...)
review = build_review_decision(execution_result, ...)
```

The current loop still owns the deeper execution internals in phase 1, but it should no longer be the only place where orchestration structure exists.

## Success Criteria

Phase 1 is successful if:

- the runtime constructs a canonical turn object
- a structured execution brief exists before execution
- current execution is reachable through the new bridge
- a structured review decision exists after execution
- no major existing behavior regresses

## Failure Conditions

Phase 1 should be considered failed if:

- the new code is only dead scaffolding with no runtime integration
- the loop still has no canonical orchestration objects in the live path
- the bridge is just renamed old code with no contract change
- review remains totally implicit
- the change breaks existing normal message handling

## Out Of Scope For Phase 1

Explicitly out of scope:

- true `LLM1` and `LLM2` model-backed reasoning
- worker runtime migration
- capability router migration
- task graph engine activation
- multimodal graph processing
- checkpoint/recovery migration

## Recommended Follow-Up After Phase 1

After phase 1 is complete, the next implementation target should be:

- phase 2: richer executive wrapper and structured runtime state/event recording

That should happen before trying to fully replace workers or workflows.

## Final Summary

This checklist defines the first safe real code slice of the new architecture.

If implemented correctly, phase 1 gives TeAI Builder:

- a real canonical turn object
- a real execution brief
- a real review object
- a real bridge from new architecture to current runtime

That is the correct place to start implementation.
