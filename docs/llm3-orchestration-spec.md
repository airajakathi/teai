# LLM3 Orchestration Specification

## Status

Draft technical specification.

This document converts the high-level plan in
[`llm3-orchestration-plan.md`](./llm3-orchestration-plan.md) into a stricter
implementation-oriented specification.

This spec defines:

- the required runtime roles
- the execution contracts between `LLM1`, `LLM2`, and `LLM3`
- the orchestration states and control flow
- the minimum data structures required to implement the new system correctly

This spec still does **not** introduce MiniCPM or another offline omni model.

## Scope

This specification covers only the new orchestration architecture in front of
and around the current TeAI Builder runtime.

It does not yet define:

- final prompt templates
- exact provider choices for each role
- final frontend UX
- complete database or persistence schema
- detailed security policy for every tool

## Normative Terms

The terms **must**, **should**, and **may** are used as follows:

- **must** means required for architectural correctness
- **should** means strongly recommended default behavior
- **may** means optional implementation choice

## System Roles

## LLM1

LLM1 is the executive user-facing orchestrator.

LLM1 must:

- own user intent understanding
- own the final user-facing answer
- decide whether a request is direct or execution-backed
- issue execution briefs to `LLM3`
- review `LLM3` outputs against user intent
- decide whether to accept, continue, revise, retry, escalate, or ask the user

LLM1 must not:

- directly own low-level tool scheduling
- directly own worker lifecycle management
- bypass the result review loop when execution occurred

## LLM2

LLM2 is the private critique and reflective reasoning partner for `LLM1`.

LLM2 must:

- critique LLM1's interpretation of the user request
- critique LLM1's execution strategy
- review `LLM3` outputs for mismatch, incompleteness, risk, or low quality
- help produce continuation guidance when `LLM3` output is rejected

LLM2 must not:

- speak directly to the user
- directly control tools or workers
- become an independent top-level orchestrator

## LLM3

LLM3 is the execution runtime.

LLM3 must:

- accept only structured execution requests from `LLM1`
- execute tools, worker tasks, and workflows
- return structured outputs, evidence, artifacts, and status
- remain bounded by budgets, scopes, and policies

LLM3 must not:

- own the final user answer
- own top-level user intent interpretation
- bypass `LLM1` acceptance decisions

## Runtime Layers

The system must be decomposed into the following layers:

1. `Ingress Layer`
2. `Unified Turn Builder`
3. `Executive Layer`
4. `Execution Layer`
5. `State Layer`
6. `Event Layer`
7. `Egress Layer`

## 1. Ingress Layer

The ingress layer receives input from:

- WebUI
- CLI
- websocket channels
- external messaging channels

The ingress layer must normalize transport-specific fields before orchestration
begins.

## 2. Unified Turn Builder

The unified turn builder must produce one canonical turn object regardless of
channel or modality.

## 3. Executive Layer

The executive layer contains:

- `ExecutiveController`
- `LLM1`
- `LLM2`
- `IntentInterpreter`
- `ModeSelector`
- `AcceptanceReviewer`

This layer decides what should happen.

## 4. Execution Layer

The execution layer contains:

- `LLM3ExecutionAdapter`
- `TaskGraphRuntime`
- `ToolRuntime`
- `WorkerRuntime`
- `WorkflowRuntime`
- `CapabilityRouter`

This layer does the work.

## 5. State Layer

The state layer stores:

- active turns
- active tasks
- worker states
- checkpoints
- accepted artifacts
- review decisions
- cancellations
- retries

## 6. Event Layer

The event layer must emit one normalized event stream for:

- UI rendering
- persistence
- debugging
- recovery

## 7. Egress Layer

The egress layer returns:

- user-facing messages
- structured progress updates
- media artifacts
- completion/failure states

## Canonical Turn Object

Every inbound request must be converted into `UnifiedTurn`.

```ts
type UnifiedTurn = {
  turn_id: string;
  session_key: string;
  channel: string;
  user_message: string;
  created_at: number;
  attachments: AttachmentRef[];
  image_inputs: MediaInput[];
  audio_inputs: MediaInput[];
  video_inputs: MediaInput[];
  workspace_scope: WorkspaceScopeSnapshot;
  workspace_snapshot?: WorkspaceSnapshot;
  session_memory?: SessionMemorySnapshot;
  goal_state?: GoalStateSnapshot | null;
  ui_hints?: Record<string, unknown>;
  requested_capabilities?: CapabilityRequest[];
  metadata?: Record<string, unknown>;
};
```

The turn builder must ensure:

- all channels become one turn representation
- all modalities use the same top-level structure
- missing modalities are represented consistently
- execution code never depends on raw transport envelopes

## Executive Deliberation Cycle

The executive deliberation cycle must follow this sequence:

1. `LLM1` interprets user intent
2. `LLM2` critiques intent interpretation
3. `LLM1` selects orchestration mode
4. if direct response:
   - `LLM1` answers
5. if execution required:
   - `LLM1` creates execution brief
   - `LLM3` executes
   - `LLM1` and `LLM2` review
   - accept or continue loop

This cycle must be explicit in the runtime and must not remain implicit prompt behavior only.

## Orchestration Modes

The runtime must support exactly one unified orchestration framework with these
mode values:

- `direct`
- `assisted`
- `delegated`
- `workflow`

Mode selection must happen before entering execution.

### Direct

Used when no runtime execution is required.

Execution rules:

- no `LLM3` call is required
- no tool graph is created
- `LLM1` may consult `LLM2`

### Assisted

Used when limited execution is required.

Execution rules:

- `LLM3` may run tools
- worker spawning should be avoided unless escalation occurs
- task graph is small and bounded

### Delegated

Used when worker specialization is required but a full long workflow is not yet necessary.

Execution rules:

- `LLM3` may create worker tasks
- workers are bounded by explicit scope and budget
- result must return to executive review

### Workflow

Used for complex long-running builds.

Execution rules:

- `LLM3` must use the task graph runtime
- checkpoints and validation nodes should be enabled
- retry and cancellation policies must be explicit

## LLM1 -> LLM3 Execution Contract

`LLM1` must never send free-form ambiguous execution prompts directly into the
runtime once the new architecture is active.

All execution requests must conform to `ExecutionBrief`.

```ts
type ExecutionBrief = {
  request_id: string;
  turn_id: string;
  session_key: string;
  mode: "assisted" | "delegated" | "workflow";
  objective: string;
  user_intent_summary: string;
  success_criteria: string[];
  constraints: string[];
  allowed_capabilities: string[];
  workspace_scope: WorkspaceScopeSnapshot;
  tool_budget?: {
    max_calls?: number;
    max_mutations?: number;
  };
  worker_budget?: {
    max_workers?: number;
    max_parallel?: number;
  };
  time_budget?: {
    soft_timeout_ms?: number;
    hard_timeout_ms?: number;
  };
  artifact_requirements?: ArtifactRequirement[];
  result_schema?: Record<string, unknown>;
  continuation_of?: string | null;
};
```

Rules:

- `objective` must be short and exact
- `success_criteria` must be explicit
- `allowed_capabilities` must be policy-bound
- `continuation_of` should be set when this is a follow-up pass after review rejection

## LLM3 -> LLM1 Result Contract

`LLM3` must return `ExecutionResult`.

```ts
type ExecutionResult = {
  request_id: string;
  turn_id: string;
  session_key: string;
  status: "completed" | "partial" | "failed" | "cancelled";
  summary: string;
  evidence: EvidenceItem[];
  artifacts: ArtifactRef[];
  worker_results?: WorkerResult[];
  validation_results?: ValidationResult[];
  next_recommendation?:
    | "accept"
    | "continue"
    | "retry"
    | "revise"
    | "ask_user"
    | "escalate";
  final_user_safe_answer_candidate?: string | null;
  raw_metadata?: Record<string, unknown>;
};
```

Rules:

- `status` must reflect true completion state
- `summary` must be concise and factual
- `evidence` must be sufficient for `LLM1` review
- `final_user_safe_answer_candidate` is advisory only
- `LLM1` remains the authority that answers the user

## LLM1 / LLM2 Review Contract

Review must produce a structured decision rather than only free-form reasoning.

```ts
type ReviewDecision = {
  turn_id: string;
  request_id: string;
  decision: "accept" | "continue" | "retry" | "revise" | "ask_user" | "escalate";
  rationale: string;
  unmet_criteria: string[];
  continuation_brief?: {
    objective_delta?: string;
    additional_constraints?: string[];
    focus_areas?: string[];
  };
};
```

Rules:

- every execution result must receive a review decision
- `accept` is required before the final answer is sent
- `continue` and `revise` must produce machine-usable continuation data

## Worker Runtime Contract

Spawned subagents must be replaced by worker tasks.

Every worker task must conform to `WorkerTaskSpec`.

```ts
type WorkerTaskSpec = {
  worker_id: string;
  parent_request_id: string;
  role: string;
  objective: string;
  expected_output_schema?: Record<string, unknown>;
  depends_on?: string[];
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
};
```

Rules:

- workers must not be launched without explicit role and objective
- workers must inherit bounded workspace scope
- workers must not own final user response
- workers must return structured output, not only free-form text

## Task Graph Runtime

The unified execution runtime must represent work as a graph.

Supported node types:

- `reason`
- `tool`
- `worker`
- `workflow_step`
- `validation`
- `merge`
- `respond_candidate`

The runtime must support:

- sequential execution
- bounded parallel execution
- dependency ordering
- checkpoint insertion
- retry policy
- cancellation
- resume

## Orchestration State Machine

The top-level orchestration state machine must be:

1. `ingest`
2. `normalize`
3. `interpret`
4. `critique`
5. `select_mode`
6. `prepare_execution`
7. `execute`
8. `review`
9. `respond`
10. `done`

Allowed transitions:

- `ingest -> normalize`
- `normalize -> interpret`
- `interpret -> critique`
- `critique -> select_mode`
- `select_mode -> respond`
- `select_mode -> prepare_execution`
- `prepare_execution -> execute`
- `execute -> review`
- `review -> respond`
- `review -> prepare_execution`
- `respond -> done`

The only loop-back path is:

- `review -> prepare_execution`

This is the executive satisfaction loop.

## Event Model

The system must emit normalized events across the full orchestration lifecycle.

Minimum event types:

- `turn_started`
- `turn_normalized`
- `intent_interpreted`
- `critique_completed`
- `mode_selected`
- `execution_prepared`
- `execution_started`
- `tool_started`
- `tool_completed`
- `worker_started`
- `worker_completed`
- `worker_failed`
- `validation_completed`
- `review_completed`
- `continuation_requested`
- `response_ready`
- `turn_completed`
- `turn_failed`

Rules:

- UI and persistence should consume these normalized events instead of reconstructing orchestration state from low-level mixed messages
- events must be tied to `turn_id` and `request_id` where applicable

## Capability Routing

The orchestration runtime must use one capability router for all model/provider selection.

The router must accept:

- requested role: `LLM1`, `LLM2`, `LLM3`, worker, modality tool, validation
- requested capabilities
- latency/cost policy
- local/cloud constraints

The router must return:

- provider
- model
- modality support
- tool-call support
- structured output support
- routing rationale

The router must be used for:

- executive model selection
- execution model selection
- worker model selection
- multimodal processing selection

## Compatibility With Current Runtime

The initial implementation must reuse the current runtime where possible.

### Current Components That May Be Wrapped As LLM3 Internals

- `AgentLoop`
- `AgentRunner`
- `ToolRegistry`
- `SubagentManager`
- `ParallelExecutor`
- `WorkflowEngine`
- websocket and bus infrastructure

### Required Boundary Change

The current runtime must stop being the top-level executive owner of the user turn.

That responsibility must move to the new executive layer.

## Required Persistence Objects

At minimum, the new runtime should persist:

- `UnifiedTurn`
- `ExecutionBrief`
- `ExecutionResult`
- `ReviewDecision`
- `WorkerTaskSpec`
- task graph snapshots
- orchestration events

Persistence may initially be file-backed, but the object model must be stable.

## Failure Semantics

The runtime must distinguish:

- `execution failed`
- `execution incomplete`
- `review rejected`
- `worker failed`
- `user clarification needed`
- `cancelled`

These are not equivalent and must not collapse into a single generic error.

## Acceptance Rules

The system must not send an execution-derived final answer to the user unless:

- `LLM3` returned a structured result
- `LLM1` and `LLM2` completed review
- the review decision was `accept`

This is the most important control rule in the architecture.

## Minimum Implementation Milestone Order

Implementation should proceed in this exact dependency order:

1. define shared object types
2. define executive layer interfaces
3. define `LLM1 -> LLM3` execution brief contract
4. define `LLM3 -> LLM1` execution result contract
5. define review decision contract
6. implement executive wrapper around current runtime
7. convert spawn behavior into worker-task semantics
8. introduce task graph runtime
9. unify capability routing
10. decommission old fragmented ownership

## Out of Scope For This Spec

This spec does not yet define:

- offline local model integration
- exact multimodal fusion algorithm
- exact workflow DSL
- database schema migration
- exact prompt contents for LLM1, LLM2, or LLM3

Those belong in follow-up implementation documents.

## Follow-Up Documents

After this spec, the next documents should be:

1. `llm3-turn-schema.md`
2. `llm3-execution-contract.md`
3. `llm3-worker-runtime-plan.md`
4. `llm3-capability-router-plan.md`
5. `llm3-event-model.md`

## Final Constraint

If any implementation choice causes:

- `LLM3` to keep top-level user ownership
- workers to remain a special side runtime
- tools, workers, and workflows to remain different orchestration systems
- review to remain optional

then the implementation is non-compliant with this specification.
