# LLM3 Interface Map

## Status

Draft implementation interface map.

This document translates the `LLM1 / LLM2 / LLM3` architecture into concrete
module and interface boundaries inside the TeAI Builder codebase.

It is the bridge between:

- architecture documents
- implementation planning
- actual code changes

This document extends:

- [`llm3-orchestration-spec.md`](./llm3-orchestration-spec.md)
- [`llm3-turn-schema.md`](./llm3-turn-schema.md)
- [`llm3-execution-contract.md`](./llm3-execution-contract.md)
- [`llm3-worker-runtime-plan.md`](./llm3-worker-runtime-plan.md)
- [`llm3-capability-router-plan.md`](./llm3-capability-router-plan.md)
- [`llm3-event-model.md`](./llm3-event-model.md)
- [`llm3-state-model.md`](./llm3-state-model.md)
- [`llm3-task-graph-plan.md`](./llm3-task-graph-plan.md)
- [`llm3-migration-roadmap.md`](./llm3-migration-roadmap.md)

## Purpose

The purpose of this document is to define:

- what new modules should exist
- what their responsibilities are
- which interfaces should be public
- which current runtime components they should wrap

Without this document, implementation would likely blur:

- architecture boundaries
- module ownership
- transition responsibilities

## Interface Design Principles

The new interfaces must follow these rules:

- executive responsibilities must be separate from execution responsibilities
- interface contracts must be typed and serializable
- new code should wrap current runtime pieces before replacing them
- orchestration interfaces must depend on shared object types, not transport-specific payloads
- module names should describe ownership clearly

## Proposed Package Layout

The first implementation should introduce a new package family under:

- `teai_builder/agent/llm3/`

Recommended modules:

- `types.py`
- `turn_builder.py`
- `executive.py`
- `mode_selector.py`
- `execution_bridge.py`
- `review.py`
- `state_store.py`
- `event_emitter.py`
- `worker_runtime.py`
- `capability_router.py`
- `task_graph.py`
- `recovery.py`

The first implementation does not need all of them fully built.

But the interface map should still define them now so code grows toward the target architecture rather than sideways.

## 1. `types.py`

### Responsibility

Own shared `LLM3` orchestration object types used by the new runtime layer.

### Primary Types

- `UnifiedTurn`
- `TurnContextEnvelope`
- `CapabilityRequest`
- `ExecutionBrief`
- `ExecutionResult`
- `ReviewDecision`
- `WorkerTaskSpec`
- `WorkerResult`
- `ValidationResult`
- `OrchestrationEvent`
- `DirectResponse`

### Public Interface

- type definitions
- serialization helpers
- enum/string constant helpers where needed

### Notes

This module must remain dependency-light and reusable across the new runtime.

## 2. `turn_builder.py`

### Responsibility

Convert current inbound runtime messages into canonical `UnifiedTurn` objects.

### Public Interface

```python
def build_unified_turn(...) -> UnifiedTurn
```

### Input Sources

- `InboundMessage`
- resolved session key
- workspace scope metadata
- normalized attachments/media metadata

### Wraps Current Reality

- channel ingress objects
- media/document extraction decisions
- session-key resolution already happening in the loop and channels

## 3. `mode_selector.py`

### Responsibility

Choose orchestration mode for the turn.

### Public Interface

```python
def select_mode(turn: UnifiedTurn, ...) -> str
```

### Output

- `direct`
- `assisted`
- `delegated`
- `workflow`

### Notes

The first implementation may use heuristics.

Later implementations may use `LLM1` + `LLM2` reasoning.

## 4. `executive.py`

### Responsibility

Provide the new top-level executive wrapper that owns:

- intent interpretation
- direct vs execution decision
- execution brief creation
- final response authority

### Public Interface

```python
class ExecutiveOrchestrator:
    async def handle_turn(...) -> ExecutiveTurnResult: ...
```

### Wraps Current Reality

- `AgentLoop` remains the lower execution backend in early phases

### Notes

This is the module that should eventually represent `LLM1` and coordinate `LLM2`.

## 5. `execution_bridge.py`

### Responsibility

Adapt the new execution contract to the current runtime.

### Public Interface

```python
class ExecutionBridge:
    async def execute(brief: ExecutionBrief, ...) -> ExecutionResult: ...
```

### Wraps Current Reality

- current `AgentLoop`
- current `AgentRunner`
- current tool-use execution path

### Notes

This is the safest first migration layer because it lets the new architecture talk to the current runtime without rewriting everything first.

## 6. `review.py`

### Responsibility

Own post-execution review and acceptance gating.

### Public Interface

```python
class ReviewCoordinator:
    async def review(result: ExecutionResult, ...) -> ReviewDecision: ...
```

### Notes

The first implementation may use a deterministic acceptance rule or a simple stub.

Later this becomes the runtime home of `LLM1 + LLM2` review logic.

## 7. `state_store.py`

### Responsibility

Own orchestration runtime state:

- turn state
- execution state
- worker state
- review state
- checkpoint state
- recovery state

### Public Interface

```python
class OrchestrationStateStore:
    def create_turn(...)
    def update_turn(...)
    def create_execution(...)
    def update_execution(...)
    ...
```

### Wraps Current Reality

- current checkpoint store
- current workflow state
- current runtime status fragments

## 8. `event_emitter.py`

### Responsibility

Emit canonical orchestration events.

### Public Interface

```python
class OrchestrationEventEmitter:
    async def emit(...)
```

### Wraps Current Reality

- current runtime event bus
- current progress signaling
- current WebUI/runtime status notifications

## 9. `worker_runtime.py`

### Responsibility

Own typed spawned execution.

### Public Interface

```python
class WorkerRuntime:
    async def schedule(...)
    async def cancel(...)
    async def retry(...)
```

### Wraps Current Reality

- `SubagentManager`
- `ParallelExecutor`

## 10. `capability_router.py`

### Responsibility

Own model/provider selection for:

- `LLM1`
- `LLM2`
- `LLM3`
- workers
- validation
- multimodal tasks

### Public Interface

```python
class CapabilityRouter:
    def route(request: RoutingRequest) -> RoutingDecision: ...
```

### Wraps Current Reality

- provider registry
- provider factory
- model presets
- fallback provider

## 11. `task_graph.py`

### Responsibility

Own unified graph execution model.

### Public Interface

```python
class TaskGraphEngine:
    async def build_graph(...)
    async def run_graph(...)
```

### Wraps Current Reality

- workflow engine
- worker scheduler
- portions of current loop multi-step execution

## 12. `recovery.py`

### Responsibility

Own resume and repair orchestration.

### Public Interface

```python
class RecoveryCoordinator:
    async def resume(...)
    async def restore(...)
```

### Wraps Current Reality

- checkpoint rebuild flows
- workflow resume flows

## Current Runtime Interfaces To Wrap First

The first implementation should wrap these existing runtime surfaces:

- [AgentLoop](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/loop.py)
- [AgentRunner](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/runner.py)
- [SubagentManager](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/subagent.py)
- [ParallelExecutor](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/parallel_executor.py)
- [WorkflowEngine](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/workflow_engine.py)
- [RuntimeEventBus](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/bus/runtime_events.py)

## Recommended Phase 1 Public Surface

The first safe implementation slice only needs a minimal subset:

- `types.py`
- `turn_builder.py`
- `mode_selector.py`
- `execution_bridge.py`

And one minimal integration surface in:

- [loop.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/loop.py)

## Phase 1 Interface Contract

The minimal phase 1 live contract should be:

```python
unified_turn = build_unified_turn(...)
mode = select_mode(unified_turn, ...)
execution_brief = build_execution_brief(unified_turn, mode, ...)
execution_result = await execution_bridge.execute(execution_brief, ...)
```

In the earliest version:

- `execution_bridge.execute(...)` may still call the current loop/runner path
- `review` may be a deterministic acceptance stub

## Integration Points In Current Code

The first practical integration points are:

- channel ingress:
  - [base.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/channels/base.py)
  - [websocket.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/channels/websocket.py)
- turn processing:
  - [loop.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/loop.py)
- runtime state/events:
  - [runtime_events.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/bus/runtime_events.py)

## Interface Ownership Rules

The new interfaces must obey these ownership rules:

- `executive.py` owns turn-level orchestration decisions
- `execution_bridge.py` owns adapting new contracts to old execution
- `worker_runtime.py` owns spawned execution
- `capability_router.py` owns model/provider routing
- `task_graph.py` owns graph execution
- `state_store.py` owns orchestration state
- `event_emitter.py` owns normalized event emission

No old runtime module should continue acting as the undocumented owner of those responsibilities once the corresponding new interface exists.

## Anti-Patterns To Avoid

Avoid:

- adding new architecture types directly inside `loop.py`
- letting transport-specific channel modules become owners of `UnifiedTurn`
- mixing provider-routing logic into execution-bridge code
- mixing worker scheduling into the executive module
- exposing raw current-runtime internals upward as if they were the new interfaces

## Initial Implementation Guidance

The first implementation should prefer:

- pure dataclasses or typed objects
- small adapter layers
- deterministic behavior
- observability metadata

It should avoid:

- trying to fully implement `LLM1` and `LLM2` behaviors immediately
- coupling every new module to every old subsystem at once

## Final Summary

This interface map defines the module boundaries that implementation should
follow.

It is the point where the architecture becomes concrete enough to code against
without letting the new orchestration system dissolve back into the old loop.
