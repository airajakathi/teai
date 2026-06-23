# LLM3 Task Graph Plan

## Status

Draft task graph plan.

This document defines the unified task-graph execution model for the new
`LLM1 / LLM2 / LLM3` orchestration architecture.

This document extends:

- [`llm3-orchestration-plan.md`](./llm3-orchestration-plan.md)
- [`llm3-orchestration-spec.md`](./llm3-orchestration-spec.md)
- [`llm3-turn-schema.md`](./llm3-turn-schema.md)
- [`llm3-execution-contract.md`](./llm3-execution-contract.md)
- [`llm3-worker-runtime-plan.md`](./llm3-worker-runtime-plan.md)
- [`llm3-capability-router-plan.md`](./llm3-capability-router-plan.md)
- [`llm3-event-model.md`](./llm3-event-model.md)
- [`llm3-state-model.md`](./llm3-state-model.md)

## Purpose

The purpose of this document is to define one execution engine that handles:

- normal execution-backed requests
- delegated worker execution
- complex workflows
- retries
- validation
- merge steps
- recovery-aware resumable progress

The current TeAI Builder runtime already has:

- agent-loop execution
- subagent spawning
- parallel execution
- workflow execution

Those are useful capabilities, but they still exist as separate orchestration
paths. The task graph plan unifies them under one execution model.

## Main Goal

Create one `Task Graph Engine` under `LLM3` so that all non-direct orchestration
flows run on the same execution substrate.

This engine must support:

- simple graphs for small tasks
- deeper graphs for complex builds
- bounded parallelism
- dependency ordering
- worker execution
- validation branches
- checkpoints
- resume and retry

## Core Principle

The new architecture must stop treating these as different top-level systems:

- normal tool execution
- spawned worker execution
- workflow execution

Instead, they should all become different graph shapes inside one execution
engine.

## What The Task Graph Solves

The unified task graph solves the current fragmentation where:

- simple execution uses one path
- subagents use another path
- workflows use another path
- validation is often bolted on later
- retries are inconsistent between paths

With a task graph:

- a small request becomes a small graph
- a complex build becomes a larger graph
- a worker branch becomes graph nodes
- a workflow becomes a graph definition, not a separate orchestration world

## Graph Principles

The task graph engine must follow these principles:

- one graph engine for all non-direct execution
- every executable unit is a node
- dependencies are explicit
- retries are explicit
- validation is explicit
- merge logic is explicit
- graph state is resumable

## Graph Entry Rule

Only `LLM3` may create or execute task graphs.

`LLM1` does not directly build graph internals.

Instead:

- `LLM1` creates `ExecutionBrief`
- `LLM3` interprets that brief into a task graph
- `LLM1` later reviews the `ExecutionResult`

This preserves executive/execution separation.

## When A Graph Is Required

A task graph is required for:

- `delegated` mode
- `workflow` mode

A task graph should usually also be used for:

- `assisted` mode when execution involves more than one meaningful step

For very small assisted requests, a trivial graph with only a few nodes is still recommended so the runtime stays consistent.

## Graph Shape Examples

### Tiny assisted request

- reason
- tool
- validation
- respond candidate

### Delegated request

- reason
- worker fan-out
- merge
- validation
- respond candidate

### Workflow build

- plan
- worker branch A
- worker branch B
- merge
- build validation
- test validation
- artifact review
- respond candidate

## Node Types

The engine should support these canonical node types:

- `reason`
- `tool`
- `worker`
- `workflow_step`
- `validation`
- `merge`
- `checkpoint`
- `respond_candidate`

### Reason Node

Used for:

- intermediate planning
- decomposition
- branch-specific reasoning
- merge reasoning

### Tool Node

Used for:

- direct tool execution
- bounded tool-call units

### Worker Node

Used for:

- delegated execution branches
- specialized subtasks

### Workflow Step Node

Used for:

- long-running named stages
- durable step-tracked execution

### Validation Node

Used for:

- test runs
- lint/build checks
- artifact review
- schema checks
- quality checks

### Merge Node

Used for:

- combining worker outputs
- resolving branch results
- building consolidated outputs

### Checkpoint Node

Used for:

- explicit save points
- resumable long-running branches

### Respond Candidate Node

Used for:

- preparing a structured candidate result for executive review

## Canonical Graph Object

```ts
type TaskGraph = {
  graph_id: string;
  request_id: string;
  turn_id: string;
  session_key: string;
  mode: "assisted" | "delegated" | "workflow";
  created_at: number;
  updated_at: number;
  status: "planned" | "running" | "paused" | "completed" | "failed" | "cancelled";
  root_objective: string;
  nodes: TaskNode[];
  edges: TaskEdge[];
  metadata?: Record<string, unknown>;
};
```

## Canonical Node Object

```ts
type TaskNode = {
  node_id: string;
  graph_id: string;
  type:
    | "reason"
    | "tool"
    | "worker"
    | "workflow_step"
    | "validation"
    | "merge"
    | "checkpoint"
    | "respond_candidate";
  label: string;
  status:
    | "pending"
    | "ready"
    | "running"
    | "completed"
    | "partial"
    | "failed"
    | "blocked"
    | "skipped"
    | "cancelled";
  depends_on: string[];
  payload?: Record<string, unknown>;
  result_ref?: string | null;
  retry_count: number;
  metadata?: Record<string, unknown>;
};
```

## Canonical Edge Object

```ts
type TaskEdge = {
  edge_id: string;
  from_node_id: string;
  to_node_id: string;
  kind: "dependency" | "data_flow" | "validation_of" | "checkpoint_after";
};
```

## Graph Rules

- every node must have a stable `node_id`
- dependencies must be explicit in `depends_on` and/or edges
- a node cannot run until dependencies are satisfied
- node status must be centrally tracked
- graph status must summarize overall graph state without hiding node-level truth

## Graph Lifecycle

The target graph lifecycle should be:

1. `planned`
2. `running`
3. optional `paused`
4. one of:
   - `completed`
   - `failed`
   - `cancelled`

## Node Lifecycle

Node lifecycle should be:

1. `pending`
2. `ready`
3. `running`
4. one of:
   - `completed`
   - `partial`
   - `failed`
   - `blocked`
   - `skipped`
   - `cancelled`

## Scheduler Role

The task graph engine must own the scheduler.

The scheduler must:

- find ready nodes
- enforce dependencies
- respect budgets
- respect parallelism limits
- dispatch worker/tool/validation execution
- record outcomes
- update graph state

This scheduler becomes the higher-level parent of worker scheduling, not a parallel system beside it.

## Worker Integration

Worker execution should appear as graph nodes, not a separate hidden side system.

Rules:

- every worker branch corresponds to one or more `worker` nodes
- worker node output should link to `WorkerState` and `WorkerResult`
- worker failures should remain visible at graph level

## Tool Integration

Tool calls should become `tool` nodes or substeps within bounded nodes.

For the first implementation:

- a node may internally execute multiple tool calls

Later:

- individual significant tool actions may become fully materialized node units

The important rule is that tool execution must remain graph-accounted.

## Workflow Integration

The current workflow engine should migrate into the task graph model.

That means:

- workflow definitions become graph templates or graph builders
- workflow steps become graph nodes
- workflow state becomes graph plus execution state

This removes the need for a separate workflow-only orchestration core.

## Graph Templates

The engine should support graph templates for common execution patterns.

Examples:

- research template
- implementation template
- build-and-validate template
- artifact-generation template
- workflow pipeline template

Templates should not replace dynamic planning.

They should provide:

- repeatable structure
- safer execution defaults
- easier validation

## Dynamic Graph Building

`LLM3` should be able to build graphs dynamically from the `ExecutionBrief`.

Dynamic graph building is important for:

- user-specific tasks
- unknown complexity
- adaptive planning
- continuation and retry flows

The first graph does not need to be perfect. The system may revise or extend it during execution if policy allows.

## Graph Expansion Rules

Graph expansion should be allowed only when:

- it stays within budget
- it stays within scope
- it does not invalidate review visibility
- newly added nodes are recorded explicitly

Graph expansion must not become hidden uncontrolled planning drift.

## Validation Strategy

Validation must be explicit in the graph.

Good patterns:

- tool nodes produce artifacts
- validation nodes test or review them
- merge nodes consolidate validated outputs

Bad pattern:

- do work
- hope it is fine
- narrate confidence without explicit validation

## Merge Strategy

Merge nodes must be first-class, not implicit.

Merge nodes are needed to:

- combine worker outputs
- resolve partial branch outputs
- aggregate artifacts
- build consolidated summaries

Merge nodes should expose:

- input branches
- merge summary
- unresolved conflicts if any

## Retry Strategy

Retries must happen at node or graph level explicitly.

Retry classes should include:

- node retry
- branch retry
- graph retry
- resume from checkpoint

Rules:

- retries must increment explicit counters
- retries must preserve lineage
- retries must not erase prior failures

## Checkpoint Strategy

Checkpoint nodes or checkpoint actions should be inserted for:

- long-running workflow branches
- expensive worker branches
- risky mutation points
- major merge boundaries

Checkpointing must be visible in:

- state model
- event model
- recovery flows

## Cancellation Strategy

Cancellation should work at:

- graph level
- branch level
- node level

Rules:

- cancellation must propagate to active child work when appropriate
- partially completed outputs must remain inspectable
- cancelled nodes must not remain indistinguishable from failed nodes

## Failure Strategy

The engine must distinguish:

- node failure
- branch failure
- validation failure
- merge conflict
- dependency deadlock
- graph failure

These conditions must remain explicit.

## Deadlock Handling

The engine must detect dependency deadlocks.

If deadlock occurs:

- graph status becomes `failed`
- blocked nodes remain visible
- error state should identify unresolved dependency cycle or unmet dependency condition

This matters because current fragmented parallel/workflow patterns can hide these failures.

## Budget Model

Graph execution must respect:

- tool budgets
- worker budgets
- time budgets
- optional cost budgets

Budgets should be enforced at:

- graph level
- node level where applicable

Budget exhaustion should produce:

- `partial`
- `failed`
- or `cancelled`

depending on context and policy.

## Graph and Review

The task graph is internal to `LLM3`, but review must still be able to understand it.

That means the final `ExecutionResult` should preserve:

- graph summary
- key node outcomes
- validation outcomes
- merge outcomes
- worker outcomes

`LLM1` and `LLM2` should not need to reverse-engineer hidden internal graph behavior from raw logs.

## Graph and Event Model

Graph execution should emit normalized events such as:

- `execution_prepared`
- `execution_started`
- `worker_planned`
- `worker_started`
- `validation_started`
- `validation_completed`
- `worker_completed`
- `review_completed`

The event model already defines the vocabulary; the graph engine becomes one of its primary producers.

## Graph and State Model

The graph engine should map to state objects like:

- `ExecutionState`
- `WorkerState`
- `ValidationState`
- `CheckpointState`

The graph object itself should also be persistable for:

- resume
- debugging
- developer tooling

## Mapping From Current Runtime

The likely migration path is:

- current agent-loop multi-step execution -> small task graphs
- current parallel executor -> scheduler logic inside task graph engine
- current workflow engine -> graph template / workflow graph builder
- current subagent branches -> worker nodes
- current validation logic -> validation nodes

## Migration Plan

### Phase 1

Define canonical graph objects and node types.

Goal:

- establish shared execution model

### Phase 2

Use small task graphs for assisted execution.

Goal:

- normalize even small multi-step execution

### Phase 3

Move worker execution under graph-managed scheduling.

Goal:

- unify delegated execution

### Phase 4

Map workflow definitions into graph templates/builders.

Goal:

- stop maintaining separate workflow orchestration ownership

### Phase 5

Attach checkpoints, validation, and recovery to the graph.

Goal:

- make graph execution resumable and inspectable

### Phase 6

Deprecate fragmented execution paths outside the graph engine.

Goal:

- one execution engine remains under `LLM3`

## Minimum Compliance Requirements

The task graph plan is compliant only if:

- all non-direct execution is graph-representable
- workers are graph-accounted
- validations are graph-accounted
- dependencies are explicit
- retries and checkpoints are explicit
- workflows are absorbed into the same execution model

If implementation still relies on:

- separate workflow orchestration as a different top-level engine
- hidden worker branches outside graph tracking
- validation outside explicit execution structure
- retries that do not preserve lineage

then it is not compliant with this plan.

## Recommended Next Documents

The best next documents after this one are:

1. `llm3-multimodal-routing-plan.md`
2. `llm3-migration-roadmap.md`

## Final Summary

This task graph plan is the execution unification layer of the new architecture.

It ensures that:

- small tasks
- delegated tasks
- long workflows
- validation
- retries
- checkpoints

all run on one coherent execution substrate instead of several disconnected orchestration paths.
