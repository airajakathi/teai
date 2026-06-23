# LLM3 Migration Roadmap

## Status

Draft migration roadmap.

This document defines the phased implementation roadmap for moving TeAI Builder
from the current fragmented orchestration runtime to the new
`LLM1 / LLM2 / LLM3` architecture.

This document extends and operationalizes:

- [`llm3-orchestration-plan.md`](./llm3-orchestration-plan.md)
- [`llm3-orchestration-spec.md`](./llm3-orchestration-spec.md)
- [`llm3-turn-schema.md`](./llm3-turn-schema.md)
- [`llm3-execution-contract.md`](./llm3-execution-contract.md)
- [`llm3-worker-runtime-plan.md`](./llm3-worker-runtime-plan.md)
- [`llm3-capability-router-plan.md`](./llm3-capability-router-plan.md)
- [`llm3-event-model.md`](./llm3-event-model.md)
- [`llm3-state-model.md`](./llm3-state-model.md)
- [`llm3-task-graph-plan.md`](./llm3-task-graph-plan.md)
- [`llm3-multimodal-routing-plan.md`](./llm3-multimodal-routing-plan.md)

## Purpose

The purpose of this document is to answer the practical question:

- how do we move from the current runtime to the target architecture without breaking the system?

The answer is:

- not with a big-bang rewrite
- not by deleting the current runtime first
- not by implementing every new concept at once

Instead, this roadmap uses a staged migration where:

- new architecture layers are introduced above or around current components
- compatibility is preserved where useful
- ownership gradually moves from old fragmented paths to the new unified stack

## Current Reality

Today TeAI Builder already has valuable production pieces:

- message bus
- agent loop
- agent runner
- provider registry and factory
- tool registry
- subagent spawning
- parallel executor
- workflow engine
- checkpoint system
- runtime event bus
- multimodal provider seams

The problem is not that nothing exists.

The problem is that too many of these pieces still behave like separate orchestration systems.

So the roadmap must:

- preserve what already works
- wrap and absorb what is fragmented
- replace only the ownership model first

## Main Migration Goal

The main goal is to end with one architecture where:

- `LLM1` owns user intent and final answer
- `LLM2` owns critique and reflective review
- `LLM3` owns bounded execution
- one capability router chooses models/providers
- one task graph engine runs execution
- one worker runtime handles spawned execution
- one state model and one event model describe runtime truth

## Migration Strategy

The migration strategy must be a strangler pattern.

That means:

- introduce the new architecture beside current runtime pieces
- route specific responsibilities into the new layers
- progressively reduce old top-level ownership
- retire old fragmented entry points only after the new path is proven

## Migration Rules

The roadmap must follow these rules:

- keep existing working paths alive during early phases
- introduce new contracts before replacing implementations
- move ownership before rewriting everything underneath
- keep all major changes behind feature flags or explicit activation paths
- preserve observability at every phase

## Phased Roadmap Overview

The roadmap is split into `10` phases:

1. architecture foundation
2. executive wrapper
3. execution contract enforcement
4. state and event backbone
5. worker runtime migration
6. capability router migration
7. task graph adoption
8. multimodal unification
9. UI and recovery adoption
10. legacy decommissioning

## Phase 1: Architecture Foundation

### Goal

Create the shared contract layer before major runtime changes.

### Deliverables

- plan document
- orchestration spec
- turn schema
- execution contract
- worker runtime plan
- capability router plan
- event model
- state model
- task graph plan
- multimodal routing plan
- migration roadmap

### Why This Comes First

Without stable contracts:

- implementation will drift
- different subsystems will reinvent different object models
- the new architecture will fragment before it is even built

### Exit Criteria

- shared documents exist
- shared ids, object models, and lifecycle meanings are stable enough to implement against

## Phase 2: Executive Wrapper

### Goal

Introduce `LLM1` and `LLM2` as the new top-level orchestration owner without replacing the whole execution runtime yet.

### What Changes

- current inbound turn still arrives through existing channels
- new executive layer wraps the current runtime
- `LLM1` interprets intent and decides direct vs execution
- `LLM2` critiques the interpretation/plan
- current runtime temporarily acts as an early `LLM3` execution backend

### What Stays The Same

- current agent loop
- current runner
- current tools
- current provider instantiation

### Why This Is Critical

This phase changes ownership first.

That is the most important architectural move.

### Exit Criteria

- the top-level turn no longer belongs directly to the old agent loop
- the executive wrapper can issue a structured execution request

## Phase 3: Execution Contract Enforcement

### Goal

Force all execution-bearing turns through the new `ExecutionBrief -> ExecutionResult -> ReviewDecision` loop.

### What Changes

- introduce explicit execution brief object
- current execution backend accepts structured requests
- result returned as structured execution result
- review becomes explicit and mandatory

### What Is Wrapped

- current multi-step execution becomes the first implementation of `LLM3`
- current free-form execution prompting gets constrained by the new contract

### Why This Matters

This phase stops the architecture from collapsing back into:

- one giant top-level agent that does everything

### Exit Criteria

- every execution-bearing turn has structured brief/result/review objects
- final user answer is gated behind explicit review acceptance

## Phase 4: State and Event Backbone

### Goal

Introduce the canonical state model and event model as the shared runtime truth.

### What Changes

- create orchestration state store
- create canonical orchestration event emission layer
- map current runtime notifications into new event/state objects

### What Is Wrapped

- current runtime event bus
- current progress metadata
- current checkpoint metadata
- current workflow status state

### Why This Matters

Without this phase:

- UI and recovery would still depend on fragmented subsystem state

### Exit Criteria

- active turns, executions, workers, and reviews are centrally represented
- normalized orchestration events exist for major lifecycle transitions

## Phase 5: Worker Runtime Migration

### Goal

Replace fragile spawned subagents with typed bounded worker tasks.

### What Changes

- current `SubagentManager` gets wrapped inside a `WorkerExecutor`
- every spawned task becomes `WorkerTaskSpec`
- worker state and worker results become canonical
- separate parallel execution ownership begins to move under the worker scheduler

### What Is Preserved Temporarily

- current internal subagent execution logic

### Why This Matters

This is the phase that addresses the current subagent/spawn brittleness most directly.

### Exit Criteria

- every spawned execution unit is typed and centrally tracked
- worker failures and budgets are explicit

## Phase 6: Capability Router Migration

### Goal

Move model/provider selection into one role-and-capability-based router.

### What Changes

- introduce capability profiles
- introduce routing request/decision objects
- route `LLM1`, `LLM2`, `LLM3`, and workers through the new router

### What Is Reused

- current provider registry
- current provider factory
- current fallback provider logic where useful

### Why This Matters

This phase stops model selection from remaining fragmented across:

- text execution
- workers
- validation
- multimodal paths

### Exit Criteria

- all major role-based model selection uses routing decisions
- fallback becomes inspectable

## Phase 7: Task Graph Adoption

### Goal

Replace fragmented execution paths with one task graph engine.

### What Changes

- assisted execution becomes small graphs
- delegated execution becomes graph-managed worker branches
- workflow execution becomes graph templates/builders
- validation and merge become explicit node types

### What Is Replaced

- separate workflow ownership
- separate parallel orchestration ownership
- partially ad hoc multi-step execution ownership

### Why This Matters

This is the execution unification phase.

### Exit Criteria

- non-direct execution is graph-representable
- workers and validations are graph-accounted

## Phase 8: Multimodal Unification

### Goal

Bring text, image, audio, video, and file flows under the same orchestration framework.

### What Changes

- all modality inputs normalize into shared turn schema
- preprocessing becomes explicit graph-accounted work
- multimodal capability routing becomes shared
- multimodal artifacts/events/state become shared

### What Is Reused

- current image generation seam
- current audio generation seam
- current video generation seam
- current transcription registry

### Why This Matters

This phase ensures the new system does not become:

- a unified text architecture plus old fragmented multimodal side systems

### Exit Criteria

- multimodal work is routed through shared router, graph, event, and state layers

## Phase 9: UI and Recovery Adoption

### Goal

Move WebUI/runtime introspection and recovery flows onto the new backbone.

### What Changes

- UI consumes normalized orchestration events
- UI can inspect workers, routing, validation, and review state
- recovery flows use checkpoint + state + event lineage
- progress display is derived from orchestration truth, not low-level metadata guesswork

### What Gets Reduced

- dependence on ad hoc metadata flags
- dependence on subsystem-specific UI heuristics

### Why This Matters

This is where the new architecture becomes visible and operable for users and developers.

### Exit Criteria

- UI reflects normalized orchestration state
- recovery paths use explicit checkpoint/recovery state

## Phase 10: Legacy Decommissioning

### Goal

Retire old fragmented orchestration ownership.

### What Gets Removed Or Hollowed Out

- direct legacy top-level execution ownership in old loop
- raw spawn semantics as public orchestration primitive
- separate workflow-only orchestration ownership
- hidden routing logic spread across subsystems
- ad hoc progress metadata as primary lifecycle truth

### What Remains

- useful low-level implementation components reused under the new architecture

### Why This Matters

This is how the migration becomes real instead of permanent dual-stack complexity.

### Exit Criteria

- one orchestration stack is authoritative
- old paths are compatibility wrappers at most, not co-equal runtime owners

## Recommended Build Order Inside The Phases

Within the roadmap, the recommended implementation order is:

1. shared object types
2. executive wrapper
3. execution contract
4. state store
5. event emission
6. worker runtime wrapper
7. capability router
8. task graph engine
9. multimodal unification
10. UI and recovery adoption
11. legacy removal

## Feature Flag Strategy

Every major migration phase should use feature flags or scoped activation.

Recommended flags:

- `llm3_executive_enabled`
- `llm3_execution_contract_enabled`
- `llm3_state_store_enabled`
- `llm3_worker_runtime_enabled`
- `llm3_capability_router_enabled`
- `llm3_task_graph_enabled`
- `llm3_multimodal_enabled`
- `llm3_ui_event_mode_enabled`

This allows:

- staged rollout
- targeted testing
- fallback to prior stable paths when needed

## Validation Strategy Per Phase

Each phase should have explicit validation gates.

### Foundation

- document consistency review

### Executive wrapper

- direct mode and execution mode routing tests

### Execution contract

- brief/result/review lifecycle tests

### State and event backbone

- turn/execution/worker/review state consistency tests
- event emission ordering tests

### Worker runtime

- spawn lineage, budget, cancellation, and failure visibility tests

### Capability router

- role-based route selection and fallback tests

### Task graph

- dependency, retry, checkpoint, and merge tests

### Multimodal

- text/image/audio/video/file normalization and routing tests

### UI and recovery

- end-to-end visibility and resume tests

## Rollout Strategy

Recommended rollout:

1. internal dev-only
2. selected sessions
3. opt-in beta path
4. default for non-critical flows
5. default for all supported flows
6. legacy fallback retained temporarily
7. legacy fallback retired

## Key Risks

### Risk 1: Big-bang rewrite temptation

If attempted:

- project will likely stall
- behavior regressions will multiply

Mitigation:

- enforce phased strangler migration

### Risk 2: Dual-stack forever

If not managed:

- old and new orchestration systems will coexist too long
- complexity will rise instead of fall

Mitigation:

- explicit decommissioning phase

### Risk 3: Hidden contract drift

If allowed:

- different subsystems will reinterpret the architecture differently

Mitigation:

- implement directly against shared docs and object models

### Risk 4: Worker/runtime fragmentation returns

If worker/task graph migration is incomplete:

- spawn brittleness will remain

Mitigation:

- make worker runtime and task graph central phases, not optional extras

### Risk 5: Multimodal remains bolted on

If multimodal migration is deferred too long:

- text architecture will unify
- media architecture will remain fragmented

Mitigation:

- reserve explicit multimodal unification phase before final legacy retirement

## What Should Be Wrapped First

The first runtime pieces to wrap should be:

- top-level turn ownership
- execution request/response contract
- worker spawn path
- route selection

These yield the biggest structural gains with the least initial destruction.

## What Should Be Rewritten Later

The pieces that should be rewritten later, not first, are:

- deep internals of all provider implementations
- full workflow implementation internals
- mature multimodal enhancements for weaker modalities like video

Those improvements are valuable, but they should happen after ownership and contracts are fixed.

## Success Criteria For The Whole Roadmap

The migration is successful only if the final runtime can truthfully say:

- every turn is owned by the executive layer
- every execution request is bounded and review-gated
- every spawned task is a typed worker
- every major lifecycle change emits normalized events
- every major runtime object is reflected in the state model
- all non-direct execution uses one task graph engine
- multimodal work uses the same orchestration framework

## Final Constraint

If the migration ends with:

- old loop still owning top-level turns
- raw spawn still acting as a special side system
- workflows still acting as a separate orchestration brain
- multimodal still handled by disconnected paths

then the migration is incomplete even if a lot of new code was added.

## Final Summary

This roadmap is the implementation bridge from current TeAI Builder to the target
architecture.

It makes the migration practical by sequencing the work so that:

- ownership changes first
- contracts come before deep rewrites
- workers and graphs unify execution
- multimodal gets folded into the same architecture
- old fragmented orchestration is retired only after the new path is ready
