# LLM3 State Model

## Status

Draft state model document.

This document defines the persistent and in-memory runtime state model for the
new `LLM1 / LLM2 / LLM3` orchestration architecture.

This document extends:

- [`llm3-orchestration-plan.md`](./llm3-orchestration-plan.md)
- [`llm3-orchestration-spec.md`](./llm3-orchestration-spec.md)
- [`llm3-turn-schema.md`](./llm3-turn-schema.md)
- [`llm3-execution-contract.md`](./llm3-execution-contract.md)
- [`llm3-worker-runtime-plan.md`](./llm3-worker-runtime-plan.md)
- [`llm3-capability-router-plan.md`](./llm3-capability-router-plan.md)
- [`llm3-event-model.md`](./llm3-event-model.md)

## Purpose

The purpose of this document is to define one coherent runtime state backbone
for the new orchestration system.

The target architecture needs more than events. It also needs stable state
objects for:

- active turns
- active execution requests
- worker lifecycle
- review lifecycle
- checkpoints
- recovery
- persistent goal and session state

Without this state backbone, the new architecture would still fragment into:

- transport state
- agent-loop state
- workflow state
- worker state
- UI-only state

That is exactly what this document is meant to prevent.

## Current Reality

TeAI Builder already has real state-related building blocks:

- runtime event state notifications in [runtime_events.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/bus/runtime_events.py)
- checkpoint persistence in [checkpoint.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/checkpoint.py)
- workflow run state in [workflow_engine.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/workflow_engine.py)

Those are important foundations, but they are still split by subsystem.

The new architecture needs one state model that can sit behind:

- the executive layer
- the execution layer
- the worker runtime
- the event model
- the recovery system

## Main Goal

Create one state model where every execution-bearing turn has a coherent state
record that can be:

- inspected
- persisted
- resumed
- reviewed
- replayed partially
- rendered in UI

## State Model Principles

The state model must follow these principles:

- one canonical state backbone for orchestration
- separate long-lived state from ephemeral transport details
- separate state objects from event objects
- use stable ids and references between objects
- allow first implementation to be file-backed
- support resume and recovery without requiring full raw-message reconstruction

## State Layers

The state model should be organized into six layers:

1. turn state
2. execution state
3. worker state
4. review state
5. checkpoint and recovery state
6. session and goal state

## 1. Turn State

Turn state is the top-level runtime state for one inbound user/system turn.

Each turn must have exactly one `TurnState` object.

```ts
type TurnState = {
  turn_id: string;
  session_key: string;
  channel: string;
  created_at: number;
  updated_at: number;
  status:
    | "started"
    | "normalized"
    | "interpreting"
    | "critiquing"
    | "mode_selected"
    | "executing"
    | "reviewing"
    | "responding"
    | "completed"
    | "failed"
    | "cancelled";
  active_mode?: "direct" | "assisted" | "delegated" | "workflow" | null;
  unified_turn: UnifiedTurn;
  direct_response?: DirectResponse | null;
  active_request_id?: string | null;
  review_id?: string | null;
  error?: string | null;
  metadata?: Record<string, unknown>;
};
```

### Turn State Rules

- every inbound request must produce one `TurnState`
- `status` must represent orchestration lifecycle, not transport lifecycle
- `active_request_id` should be set when execution mode is active
- turn state must remain the parent object for execution, review, and response flow

## 2. Execution State

Execution state represents one `LLM3` execution request under a turn.

One turn may have multiple execution states over time due to:

- continuation
- retry
- revision
- escalation

```ts
type ExecutionState = {
  request_id: string;
  turn_id: string;
  session_key: string;
  created_at: number;
  updated_at: number;
  status:
    | "prepared"
    | "accepted"
    | "running"
    | "waiting"
    | "partial"
    | "completed"
    | "failed"
    | "cancelled";
  brief: ExecutionBrief;
  result?: ExecutionResult | null;
  route?: RoutingDecision | null;
  worker_ids: string[];
  validation_ids: string[];
  checkpoint_ids: string[];
  continuation_of?: string | null;
  retry_of?: string | null;
  escalation_from?: string | null;
  error?: string | null;
  metadata?: Record<string, unknown>;
};
```

### Execution State Rules

- every `ExecutionBrief` must have one `ExecutionState`
- each execution state must keep its own lifecycle independent of the parent turn
- continuation and retry lineage must be explicit
- worker and checkpoint references must be ids, not embedded objects only

## 3. Worker State

Worker state represents one bounded spawned worker task.

```ts
type WorkerState = {
  worker_id: string;
  parent_request_id: string;
  turn_id: string;
  session_key: string;
  created_at: number;
  updated_at: number;
  status:
    | "planned"
    | "queued"
    | "ready"
    | "running"
    | "waiting"
    | "checkpointed"
    | "completed"
    | "partial"
    | "failed"
    | "blocked"
    | "cancelled";
  spec: WorkerTaskSpec;
  route?: RoutingDecision | null;
  result?: WorkerResult | null;
  retry_count: number;
  depends_on: string[];
  blocked_by?: string[] | null;
  checkpoint_ids: string[];
  error?: string | null;
  metadata?: Record<string, unknown>;
};
```

### Worker State Rules

- every spawned worker must create one `WorkerState`
- worker state must be centrally tracked
- worker dependencies must be explicit
- blocked state must not be hidden in free-form text
- completed workers must have a result object

## 4. Review State

Review state represents the acceptance process after one execution pass.

```ts
type ReviewState = {
  review_id: string;
  turn_id: string;
  request_id: string;
  created_at: number;
  updated_at: number;
  status: "started" | "completed";
  decision?: ReviewDecision | null;
  reviewed_by: {
    llm1: boolean;
    llm2: boolean;
  };
  metadata?: Record<string, unknown>;
};
```

### Review State Rules

- every `ExecutionResult` must produce one `ReviewState`
- review state must be explicit, not inferred only from final messages
- review decision should be stored directly in state once completed

## 5. Checkpoint State

Checkpoint state represents resumable snapshots of orchestration progress.

The new model should build on the current checkpoint idea in [checkpoint.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/checkpoint.py)
but make it orchestration-wide instead of only session-context oriented.

```ts
type CheckpointState = {
  checkpoint_id: string;
  turn_id?: string | null;
  request_id?: string | null;
  worker_id?: string | null;
  session_key: string;
  created_at: number;
  kind: "turn" | "execution" | "worker" | "workflow" | "recovery";
  status: "created" | "restored" | "stale";
  summary?: string | null;
  snapshot_ref: string;
  metadata?: Record<string, unknown>;
};
```

### Checkpoint State Rules

- checkpoints must reference the scope they belong to
- checkpoint kind must be explicit
- snapshot payload may be stored externally, but checkpoint state must remain inspectable
- restoring a checkpoint should create visible recovery state and events

## 6. Recovery State

Recovery state represents resume or repair work after interruption, timeout, or failure.

```ts
type RecoveryState = {
  recovery_id: string;
  turn_id: string;
  session_key: string;
  created_at: number;
  updated_at: number;
  status: "started" | "running" | "completed" | "failed" | "cancelled";
  source_checkpoint_id?: string | null;
  target_request_id?: string | null;
  reason:
    | "resume_after_interrupt"
    | "resume_after_timeout"
    | "resume_after_crash"
    | "repair_after_failure"
    | "manual_restore";
  summary?: string | null;
  metadata?: Record<string, unknown>;
};
```

### Recovery State Rules

- recovery must be a first-class state object
- it must not be hidden inside generic execution retries
- recovery lineage should connect to checkpoint and execution state where applicable

## 7. Session State

Session state captures long-lived conversational/runtime state across turns.

```ts
type SessionState = {
  session_key: string;
  created_at: number;
  updated_at: number;
  status: "active" | "paused" | "archived";
  active_turn_id?: string | null;
  active_goal_id?: string | null;
  last_completed_turn_id?: string | null;
  memory_snapshot?: SessionMemorySnapshot | null;
  metadata?: Record<string, unknown>;
};
```

### Session State Rules

- session state must remain lightweight
- it should reference active objects rather than embedding all history
- long-lived context should point to session memory snapshots or summaries

## 8. Goal State

Goal state captures sustained objectives spanning many turns.

This builds on the current direction already present in runtime events and workflow systems.

```ts
type GoalState = {
  goal_id: string;
  session_key: string;
  created_at: number;
  updated_at: number;
  status: "active" | "paused" | "completed" | "failed" | "cancelled";
  description: string;
  success_criteria: string[];
  active_request_id?: string | null;
  active_worker_ids: string[];
  last_review_id?: string | null;
  progress_summary?: string | null;
  metadata?: Record<string, unknown>;
};
```

### Goal State Rules

- goal state must be durable across turns
- it should support long-running build workflows
- it should remain connected to review and execution outcomes

## 9. Validation State

Validation state represents structured validation activity.

```ts
type ValidationState = {
  validation_id: string;
  parent_request_id: string;
  turn_id: string;
  created_at: number;
  updated_at: number;
  status: "started" | "passed" | "failed" | "warning" | "skipped";
  result?: ValidationResult | null;
  metadata?: Record<string, unknown>;
};
```

### Validation State Rules

- validations must not live only in free-form execution summaries
- validation state should remain queryable and visible for review

## 10. Artifact State

Artifact state keeps persistent references to execution products.

```ts
type ArtifactState = {
  artifact_id: string;
  turn_id?: string | null;
  request_id?: string | null;
  worker_id?: string | null;
  session_key: string;
  created_at: number;
  status: "created" | "accepted" | "superseded" | "deleted";
  artifact: ArtifactRef;
  metadata?: Record<string, unknown>;
};
```

### Artifact State Rules

- artifacts should remain referenceable across review and memory layers
- accepted artifacts should be explicitly markable
- superseded artifacts should not disappear from history

## 11. Route State

Route state captures model/provider choices for auditability and recovery.

```ts
type RouteState = {
  route_id: string;
  turn_id?: string | null;
  request_id?: string | null;
  worker_id?: string | null;
  created_at: number;
  role: string;
  decision: RoutingDecision;
};
```

### Route State Rules

- route decisions should be persistable
- recovery and debugging should be able to inspect prior route choices

## State Relationships

The minimum object relationships are:

- one `SessionState` may have many `TurnState`s
- one `TurnState` may have many `ExecutionState`s
- one `ExecutionState` may have many `WorkerState`s
- one `ExecutionState` may have many `ValidationState`s
- one `ExecutionState` must have at most one `ReviewState`
- one `TurnState` may have many `CheckpointState`s
- one `ExecutionState` may have many `CheckpointState`s
- one `WorkerState` may have many `CheckpointState`s
- one `TurnState` may have one or more `ArtifactState`s
- one `GoalState` may span many turns and execution states

## State Store Responsibilities

The new runtime should eventually have a dedicated orchestration state store.

The state store must support:

- create
- update
- read by id
- read by session
- read active objects
- append history
- persist snapshots
- load for recovery

The state store should be the source of truth for current orchestration state.

## State Store Layers

The state store should be split logically into:

- `SessionStore`
- `TurnStore`
- `ExecutionStore`
- `WorkerStore`
- `ReviewStore`
- `CheckpointStore`
- `RecoveryStore`
- `ArtifactStore`
- `RouteStore`

These may share one backing store in the first implementation.

## In-Memory vs Persistent State

The architecture must distinguish:

- in-memory hot state
- persistent recoverable state

### In-Memory State

Use for:

- fast lookup of active turns
- active worker scheduling
- current progress rendering

### Persistent State

Use for:

- checkpoints
- recovery
- postmortem debugging
- workflow continuation
- accepted artifacts
- review history

The first implementation may persist to files, but the object model must remain stable enough to later move to a database.

## State and Event Relationship

Events and state must remain distinct.

Rules:

- events describe that something happened
- state describes what the system currently believes is true
- events may be used to rebuild state partially
- state should not require replaying the entire raw event stream for normal reads

This distinction is essential.

## Current Component Mapping

The most likely migration from current runtime pieces is:

- current runtime turn status -> evolves into `TurnState`
- current execution loop state -> evolves into `ExecutionState`
- current subagent status -> evolves into `WorkerState`
- current workflow run state -> partially maps into `ExecutionState`, `WorkerState`, and checkpoint/recovery state
- current checkpoint objects -> evolve into `CheckpointState` plus external snapshot payloads
- current goal/runtime metadata -> evolves into `GoalState`

## Workflow State Mapping

The current workflow engine already has:

- workflow definitions
- workflow step runs
- workflow run state
- status history

Under the new architecture, workflow-specific state should no longer remain a separate orchestration world.

Instead:

- workflow run becomes a specialized execution/task-graph state
- step runs become graph node or worker/task state
- workflow checkpoints become checkpoint state entries

This reduces fragmentation.

## Checkpoint Mapping

The current checkpoint system already stores:

- session key
- messages
- state
- metadata

The new model should keep that strength, but attach checkpoints more directly to:

- turn
- execution request
- worker
- recovery flow

## Recovery Semantics

Recovery should be able to resume from:

- latest checkpoint for a turn
- latest checkpoint for an execution request
- latest checkpoint for a worker branch
- explicitly selected checkpoint

Recovery should preserve:

- lineage
- source checkpoint id
- reason for recovery
- new request or state ids created during recovery

## State Transition Rules

Each major state object must have controlled transitions.

### TurnState transitions

- `started -> normalized`
- `normalized -> interpreting`
- `interpreting -> critiquing`
- `critiquing -> mode_selected`
- `mode_selected -> responding`
- `mode_selected -> executing`
- `executing -> reviewing`
- `reviewing -> responding`
- `responding -> completed`
- any active state -> failed
- any active state -> cancelled

### ExecutionState transitions

- `prepared -> accepted`
- `accepted -> running`
- `running -> waiting`
- `running -> partial`
- `running -> completed`
- `running -> failed`
- `running -> cancelled`
- `waiting -> running`

### WorkerState transitions

- `planned -> queued`
- `queued -> ready`
- `ready -> running`
- `running -> checkpointed`
- `checkpointed -> running`
- `running -> completed`
- `running -> partial`
- `running -> failed`
- `running -> blocked`
- `running -> cancelled`

### ReviewState transitions

- `started -> completed`

### RecoveryState transitions

- `started -> running`
- `running -> completed`
- `running -> failed`
- `running -> cancelled`

## State Integrity Rules

The state model must enforce these integrity rules:

- every `ExecutionState` must reference an existing `TurnState`
- every `WorkerState` must reference an existing `ExecutionState`
- every `ReviewState` must reference an existing `ExecutionState`
- terminal states must not continue mutating except through explicit recovery or superseding state
- ids must remain stable across persistence boundaries

## Minimal Persistence Envelope

Every persisted state object should support a stable wrapper like:

```ts
type PersistedStateEnvelope<T> = {
  schema_version: string;
  object_type: string;
  payload: T;
};
```

Suggested initial version:

- `llm3-state-v1`

## Migration Plan

The migration should happen in phases.

### Phase 1

Define canonical state objects and ids.

Goal:

- establish a single object model before runtime rewiring

### Phase 2

Create a lightweight state store that tracks active turn, execution, worker, and review state.

Goal:

- centralize current runtime status

### Phase 3

Attach checkpoint, artifact, and route state.

Goal:

- support inspection and recovery

### Phase 4

Map workflow and subagent state into the new state model.

Goal:

- stop maintaining separate orchestration state worlds

### Phase 5

Use the state store as the backing layer for UI and recovery flows.

Goal:

- normalized runtime introspection

### Phase 6

Deprecate fragmented subsystem-owned state as top-level orchestration truth.

Goal:

- one orchestration state backbone remains

## Minimum Compliance Requirements

The state model is compliant only if:

- every turn has a `TurnState`
- every execution request has an `ExecutionState`
- every worker has a `WorkerState`
- every review has a `ReviewState`
- checkpoints and recovery are explicit state objects
- long-running goals are durable
- workflow state is absorbed into the new orchestration state model

If implementation still relies mainly on:

- transport-layer state
- hidden in-memory-only worker status
- separate workflow-only truth
- implicit review state
- checkpoint files with no orchestration-level linkage

then it is not compliant with this plan.

## Recommended Next Documents

The best next documents after this one are:

1. `llm3-task-graph-plan.md`
2. `llm3-multimodal-routing-plan.md`
3. `llm3-migration-roadmap.md`

## Final Summary

This state model is the persistence and recovery backbone of the new architecture.

The event model explains what happened.

The state model explains what is currently true.

The new orchestration system needs both. Without this state model, the runtime
would still be forced to reconstruct truth from scattered subsystem state, which
is one of the main problems the new architecture is supposed to solve.
