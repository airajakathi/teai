# LLM3 Worker Runtime Plan

## Status

Draft worker runtime plan.

This document defines how the new orchestration architecture should replace the
current spawned subagent model with a single bounded worker runtime.

This document extends:

- [`llm3-orchestration-plan.md`](./llm3-orchestration-plan.md)
- [`llm3-orchestration-spec.md`](./llm3-orchestration-spec.md)
- [`llm3-turn-schema.md`](./llm3-turn-schema.md)
- [`llm3-execution-contract.md`](./llm3-execution-contract.md)

## Purpose

The purpose of this document is to make worker execution reliable, inspectable,
and compatible with the new `LLM1 / LLM2 / LLM3` architecture.

Today, TeAI Builder already has:

- subagent spawning
- a parallel executor
- workflow execution concepts

But those behaviors are still too fragmented and fragile to act as a single
production orchestration runtime.

This document defines how to replace those fragmented pieces with one worker
runtime under `LLM3`.

## Current Reality

The current codebase shows that TeAI Builder already has real subagent and
parallel orchestration pieces:

- [subagent.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/subagent.py)
- [parallel_executor.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/parallel_executor.py)

The current direction is valuable, but there are architectural problems:

- spawned subagents are still treated too much like background mini-agents instead of typed worker tasks
- worker lifecycle is not the single source of truth for execution state
- task scheduling, task dependency handling, and worker execution are not unified enough
- result contracts are not strict enough for executive review
- worker creation and worker usage are too tightly coupled to current internal agent behavior

## Why The Current Spawn Path Feels Brittle

The current subagent path is brittle for structural reasons:

- spawn behavior is still centered on ad hoc task execution rather than a typed runtime contract
- worker status is tracked, but not yet fully elevated into the main orchestration object model
- parallel execution depends on a separate executor instead of a shared task graph scheduler
- current subagent execution is still too close to a reused agent loop instead of a dedicated worker protocol
- mode switching between normal execution, spawned execution, and workflow execution is still fragmented

In short:

- the current system can spawn
- but it does not yet treat spawned execution as one first-class orchestration primitive

That is the key thing this document fixes.

## Main Goal

Replace the current subagent concept with a `Worker Runtime` where every spawned
unit of work becomes a typed, bounded, reviewable worker task.

The new worker runtime must:

- live under `LLM3`
- be controlled by the `ExecutionBrief`
- be review-compatible with `LLM1` and `LLM2`
- support normal parallel execution
- support complex build decomposition
- support resume, cancellation, checkpointing, and validation

## Worker Runtime Principles

The new runtime must follow these principles:

- one worker model for all spawned execution
- one scheduler for parallel and dependent tasks
- one status model for worker state
- one result contract for worker outputs
- one policy model for worker permissions and budgets

Workers must stop being:

- hidden background assistants
- free-form agent prompts
- loosely tracked subtasks

Workers must become:

- typed task units
- bounded execution nodes
- inspectable runtime objects

## Worker Definition

A worker is a bounded execution unit created by `LLM3` in order to complete part
of an `ExecutionBrief`.

A worker is not:

- a user-facing agent
- a top-level orchestrator
- an autonomous long-lived personality

A worker is:

- a task-specific executor
- a scoped specialist
- a child of one parent execution request

## Required Worker Object

The worker runtime must use the shared `WorkerTaskSpec` object as the canonical
worker definition.

```ts
type WorkerTaskSpec = {
  worker_id: string;
  parent_request_id: string;
  turn_id: string;
  session_key: string;
  role: string;
  objective: string;
  expected_output_schema?: Record<string, unknown>;
  depends_on: string[];
  permissions: {
    can_edit: boolean;
    can_run_commands: boolean;
    can_spawn_workers: boolean;
  };
  workspace_scope: WorkspaceScopeSnapshot;
  budget?: {
    max_iterations?: number;
    soft_timeout_ms?: number;
  };
  checkpoint_policy?: "none" | "step" | "milestone";
  metadata?: Record<string, unknown>;
};
```

## Worker Creation Rules

`LLM3` may create workers only when:

- the execution mode permits it
- the `worker_budget` allows it
- a task can be clearly decomposed
- the worker role and objective can be stated explicitly

`LLM3` must not create workers when:

- the task is trivial
- worker roles would be ambiguous
- the work can be completed safely within the parent execution path
- worker spawning would only hide poor planning

## When Workers Should Be Used

Workers should be used for:

- parallel research tasks
- specialized code analysis
- isolated artifact generation
- branch-specific build subtasks
- validation branches
- long multi-step decomposition under one parent objective

Workers should not be used for:

- simple normal chat
- single direct tool calls
- tiny follow-up actions
- unclear tasks that need more user clarification first

## Worker Roles

Worker roles should be explicit and narrow.

Examples:

- `code_research_worker`
- `api_integration_worker`
- `ui_worker`
- `test_validation_worker`
- `artifact_review_worker`
- `documentation_worker`

Worker roles should be capability-oriented, not personality-oriented.

## Worker Runtime Layers

The worker runtime should contain these layers:

1. `WorkerPlanner`
2. `WorkerScheduler`
3. `WorkerExecutor`
4. `WorkerStateStore`
5. `WorkerCheckpointManager`
6. `WorkerResultCollector`
7. `WorkerEventPublisher`

## 1. WorkerPlanner

The `WorkerPlanner` decides whether the parent execution should spawn workers.

It must:

- inspect the parent objective
- identify decomposable units
- define worker roles and objectives
- assign dependencies
- estimate budgets

It must not:

- execute workers directly
- bypass policy checks

## 2. WorkerScheduler

The `WorkerScheduler` is the single scheduler for all worker tasks.

It must:

- queue workers
- enforce dependencies
- respect parallelism limits
- track readiness
- handle blocked states
- handle retries and cancellation

It must replace the current split between:

- raw spawning behavior
- separate parallel executor control

## 3. WorkerExecutor

The `WorkerExecutor` runs one worker task.

It must:

- translate `WorkerTaskSpec` into one bounded execution session
- create the worker execution context
- attach permissions and scope
- attach capability routing
- collect output, evidence, and artifacts

It must not:

- let workers override their own scope
- let workers become top-level user responders
- allow unlimited recursive spawning by default

## 4. WorkerStateStore

The `WorkerStateStore` must be the source of truth for worker lifecycle state.

It should track:

- `pending`
- `ready`
- `running`
- `waiting`
- `completed`
- `failed`
- `blocked`
- `cancelled`

It should also track:

- parent request id
- dependencies
- timestamps
- retries
- checkpoint state
- summarized failure reason

## 5. WorkerCheckpointManager

The worker checkpoint manager should support resumable execution for complex work.

It should manage:

- step checkpoints
- milestone checkpoints
- partial artifact state
- worker resume eligibility

Checkpointing should be used for:

- long build tasks
- expensive tool-use branches
- multi-stage workers

Checkpointing should not be required for every tiny worker.

## 6. WorkerResultCollector

The collector must normalize worker outputs into shared objects.

Each worker must return:

- one `WorkerResult`
- zero or more `EvidenceItem`s
- zero or more `ArtifactRef`s
- optional validation outputs

No worker should return only raw free-form text as its complete runtime output.

## 7. WorkerEventPublisher

The event publisher must emit normalized worker events into the shared
orchestration event model.

Minimum worker event types:

- `worker_planned`
- `worker_queued`
- `worker_ready`
- `worker_started`
- `worker_progress`
- `worker_checkpointed`
- `worker_completed`
- `worker_failed`
- `worker_cancelled`

These should map into the broader shared event model used by the runtime and UI.

## Worker Lifecycle

The target worker lifecycle should be:

1. `planned`
2. `queued`
3. `ready`
4. `running`
5. one of:
   - `completed`
   - `failed`
   - `blocked`
   - `cancelled`
6. optional `retry_queued`
7. `done`

## Worker Lifecycle Rules

- a worker cannot enter `running` until dependencies are satisfied
- a worker cannot enter `completed` without a `WorkerResult`
- a worker cannot silently disappear after failure
- a blocked worker must identify the blocking dependency or condition
- retries must create explicit retry state rather than mutating history invisibly

## Worker Result Object

The runtime must use the shared worker result object.

```ts
type WorkerResult = {
  worker_id: string;
  parent_request_id: string;
  status: "completed" | "failed" | "cancelled" | "partial";
  summary: string;
  output?: Record<string, unknown> | null;
  evidence: EvidenceItem[];
  artifacts: ArtifactRef[];
  error?: string | null;
  metadata?: Record<string, unknown>;
};
```

## Worker Result Rules

- every worker must return exactly one result
- result status must match real lifecycle outcome
- `summary` must be short and factual
- `evidence` must support parent review and merge logic
- worker failure must remain visible to the parent result

## Dependency Model

Workers must support explicit dependency graphs.

Dependency relationships must be represented with worker ids.

Allowed dependency patterns:

- independent parallel workers
- simple fan-out
- simple fan-in
- staged pipelines
- validation branches

Disallowed dependency behavior:

- hidden implicit dependencies
- dependency tracking only in prompts
- unresolved cycles without explicit failure

## Parallelism Rules

Parallelism must be controlled by one scheduler-level policy.

The runtime should enforce:

- global max worker count per parent request
- max parallel workers per request
- optional worker-class limits

Parallelism must not depend on ad hoc executor branches outside the scheduler.

## Permission Model

Each worker must have explicit permissions.

Minimum permission flags:

- `can_edit`
- `can_run_commands`
- `can_spawn_workers`

Additional permission fields may later include:

- `can_access_network`
- `can_use_mutating_tools`
- `can_publish_artifacts`

Worker permissions must always be narrower than or equal to the parent request policy.

## Recursive Worker Spawning

Recursive worker spawning should be disabled by default.

If enabled, it must require:

- explicit permission
- remaining budget
- scheduler support
- explicit parent-child lineage tracking

This is important because uncontrolled recursive spawning is one of the fastest
ways to recreate the same instability that exists today.

## Worker Merge Model

Parent execution must be able to merge worker outputs coherently.

The merge layer should support:

- merging summaries
- merging artifacts
- merging evidence
- resolving conflicting outputs
- marking incomplete branches

Parent merge should not:

- silently drop failed worker outputs
- flatten conflicting outputs into fake certainty

## Validation Workers

Validation should often be handled as worker tasks or validation nodes, not as
informal afterthought reasoning.

Good examples:

- test validation worker
- build validation worker
- output review worker
- artifact integrity worker

This helps the runtime keep execution and review evidence structured.

## Worker Budget Model

Each parent execution should define worker budgets.

Minimum budget controls:

- max worker count
- max parallel count
- max iterations per worker
- soft timeout per worker
- total worker runtime budget per request

If the budget is exhausted:

- no new workers may be scheduled
- currently running workers may complete or wind down
- the parent result should become `partial` unless already successful

## Failure Semantics

The worker runtime must distinguish:

- worker planning failure
- worker start failure
- worker execution failure
- dependency failure
- timeout
- permission violation
- policy rejection
- cancellation

These must remain visible at both worker and parent execution level.

## Retry Semantics

Retries should be explicit and policy-bounded.

Possible retry classes:

- immediate retry
- revised retry
- resumed retry from checkpoint

Each retry should record:

- retry count
- previous failure reason
- whether prompt/objective changed
- whether dependencies changed

## Cancellation Semantics

Worker cancellation must be explicit and inspectable.

Cancellation sources may include:

- user cancellation
- parent execution cancellation
- policy cancellation
- timeout cancellation

When cancellation happens:

- worker state must become `cancelled`
- parent request must be informed
- partial outputs may still be collected if safe

## Worker Runtime And Review

Workers exist inside `LLM3`, but their outputs must be review-friendly for
`LLM1` and `LLM2`.

That means:

- workers must produce structured results
- parent execution must preserve worker evidence
- worker failure must remain visible in `ExecutionResult`
- review must be able to decide whether to continue, revise, or escalate based on worker outcomes

## Migration From Current Runtime

The migration should happen in phases.

### Phase 1

Wrap current subagent execution behind `WorkerExecutor`.

Goal:

- keep current internal agent reuse temporarily
- stop exposing raw spawn semantics upward

### Phase 2

Replace separate parallel execution logic with `WorkerScheduler`.

Goal:

- one scheduler for all worker concurrency

### Phase 3

Normalize all worker outputs into `WorkerResult`.

Goal:

- make review and merge deterministic

### Phase 4

Attach worker events to the shared event model.

Goal:

- make UI/runtime/debugging consistent

### Phase 5

Move workflow branch execution onto the same worker runtime.

Goal:

- stop maintaining separate spawned and workflow execution worlds

### Phase 6

Deprecate direct legacy subagent ownership.

Goal:

- workers become the only supported spawned execution primitive

## Mapping From Current Components

The most likely migration map is:

- current `SubagentManager` -> temporary implementation inside `WorkerExecutor`
- current `ParallelExecutor` -> replaced by `WorkerScheduler`
- current workflow branch execution -> gradually rewritten as scheduler-managed worker/task graph execution
- current status tracking -> moved into `WorkerStateStore`

## Minimum Compliance Requirements

The worker runtime is compliant only if:

- every spawned unit uses `WorkerTaskSpec`
- every worker returns `WorkerResult`
- worker status is centrally tracked
- worker dependencies are explicit
- worker permissions are explicit
- worker budgets are enforced
- worker failures remain visible to parent review

If any implementation still allows:

- free-form spawn prompts with no typed worker record
- hidden worker lineage
- unbounded recursive spawning
- invisible worker failure
- separate parallel orchestration outside the scheduler

then it is not compliant with this plan.

## Recommended Next Documents

The best next documents after this one are:

1. `llm3-capability-router-plan.md`
2. `llm3-event-model.md`
3. `llm3-state-model.md`
4. `llm3-task-graph-plan.md`

## Final Summary

This worker runtime plan is the bridge between:

- the current fragile spawn/subagent world
- and the target unified orchestration runtime

Once implemented, spawned execution will stop being a side feature and become a
first-class, bounded, schedulable execution primitive under `LLM3`.
