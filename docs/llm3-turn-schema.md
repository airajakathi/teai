# LLM3 Turn Schema

## Status

Draft shared schema document.

This document defines the canonical object model for the new `LLM1 / LLM2 / LLM3`
orchestration architecture.

It is the schema companion to:

- [`llm3-orchestration-plan.md`](./llm3-orchestration-plan.md)
- [`llm3-orchestration-spec.md`](./llm3-orchestration-spec.md)

This document focuses only on:

- shared object shapes
- field meanings
- validation rules
- object relationships

It does not define:

- database migrations
- exact prompt content
- exact API transport mapping
- provider-specific payload formats

## Design Goals

The schema must make the new orchestration architecture possible by ensuring:

- all channels normalize into one common turn structure
- all modalities are represented consistently
- `LLM1`, `LLM2`, and `LLM3` read from the same top-level state objects
- execution, review, and response objects are machine-usable
- spawned workers stop being ad hoc text prompts and become typed runtime objects

## Schema Principles

All schema objects in this document must follow these rules:

- every object must have a stable id when it can be referenced later
- every object must be serializable
- every object must support file-backed persistence in the first implementation
- every cross-object reference should use ids, not embedded runtime-only pointers
- objects should separate user-facing text from execution metadata
- missing data should be represented explicitly rather than by inconsistent null-like patterns

## Primitive Type Conventions

The examples in this document use TypeScript-like syntax for readability.

Common conventions:

- `string` means UTF-8 text
- `number` means integer or float depending on field semantics
- timestamps are Unix epoch milliseconds unless stated otherwise
- optional fields use `?`
- nullable fields use `| null`

## Core Object Map

The minimum shared object model must include:

- `UnifiedTurn`
- `TurnContextEnvelope`
- `AttachmentRef`
- `MediaInput`
- `WorkspaceScopeSnapshot`
- `WorkspaceSnapshot`
- `SessionMemorySnapshot`
- `GoalStateSnapshot`
- `CapabilityRequest`
- `ExecutionBrief`
- `ExecutionResult`
- `ReviewDecision`
- `WorkerTaskSpec`
- `WorkerResult`
- `ValidationResult`
- `ArtifactRef`
- `EvidenceItem`
- `OrchestrationEvent`

## Object Relationships

The core relationships are:

- one `UnifiedTurn` may produce zero or more `ExecutionBrief`s
- one `ExecutionBrief` produces one `ExecutionResult`
- one `ExecutionResult` must produce one `ReviewDecision`
- one `ExecutionBrief` may create zero or more `WorkerTaskSpec`s
- one `WorkerTaskSpec` may produce one `WorkerResult`
- one `ExecutionResult` may contain zero or more `ArtifactRef`s
- one `UnifiedTurn` may emit many `OrchestrationEvent`s

## UnifiedTurn

`UnifiedTurn` is the top-level canonical input object for the orchestration runtime.

```ts
type UnifiedTurn = {
  turn_id: string;
  session_key: string;
  channel: string;
  created_at: number;
  user_message: string;
  message_kind: "user" | "system" | "automation";
  channel_message_id?: string | null;
  attachments: AttachmentRef[];
  image_inputs: MediaInput[];
  audio_inputs: MediaInput[];
  video_inputs: MediaInput[];
  workspace_scope: WorkspaceScopeSnapshot;
  workspace_snapshot?: WorkspaceSnapshot | null;
  session_memory?: SessionMemorySnapshot | null;
  goal_state?: GoalStateSnapshot | null;
  requested_capabilities: CapabilityRequest[];
  ui_hints?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};
```

### UnifiedTurn Rules

- `turn_id` must be globally unique within the runtime
- `session_key` must identify the user conversation context
- `channel` must be normalized to one stable runtime value
- `user_message` may be empty only when at least one media input exists
- `attachments`, `image_inputs`, `audio_inputs`, and `video_inputs` must always exist as arrays
- missing optional snapshots should be `null` or omitted consistently
- `requested_capabilities` should always exist, even if empty

## TurnContextEnvelope

`TurnContextEnvelope` is the executive-ready wrapper around the turn that both
`LLM1` and `LLM2` should consume.

```ts
type TurnContextEnvelope = {
  turn: UnifiedTurn;
  runtime_context: {
    active_mode?: OrchestrationMode | null;
    previous_request_id?: string | null;
    continuation_depth: number;
    active_execution?: ExecutionBrief | null;
  };
  policy_context: {
    allowed_capabilities: string[];
    local_only: boolean;
    cloud_allowed: boolean;
  };
};
```

### TurnContextEnvelope Rules

- this object should be assembled before executive deliberation starts
- it should contain all data needed for initial `LLM1` and `LLM2` reasoning
- it must not contain raw transport-layer websocket envelopes

## AttachmentRef

`AttachmentRef` represents any non-inline file or media object associated with the turn.

```ts
type AttachmentRef = {
  attachment_id: string;
  kind: "file" | "image" | "audio" | "video" | "document" | "other";
  name: string;
  mime_type?: string | null;
  local_path?: string | null;
  url?: string | null;
  size_bytes?: number | null;
  source: "user" | "system" | "generated";
  metadata?: Record<string, unknown>;
};
```

### AttachmentRef Rules

- at least one of `local_path` or `url` should be present
- `kind` must be normalized independently of mime type
- generated artifacts may later reference the same object shape

## MediaInput

`MediaInput` represents a media object promoted into first-class multimodal input.

```ts
type MediaInput = {
  media_id: string;
  attachment_id?: string | null;
  mime_type: string;
  local_path?: string | null;
  url?: string | null;
  transcript_text?: string | null;
  extracted_summary?: string | null;
  duration_ms?: number | null;
  width?: number | null;
  height?: number | null;
  metadata?: Record<string, unknown>;
};
```

### MediaInput Rules

- `image_inputs`, `audio_inputs`, and `video_inputs` each contain this object type
- audio inputs may include transcription text once available
- video inputs may later include frame-level derived summaries
- multimodal extraction should add derived fields rather than replacing the original media reference

## WorkspaceScopeSnapshot

`WorkspaceScopeSnapshot` defines the execution boundary allowed for the turn.

```ts
type WorkspaceScopeSnapshot = {
  project_path: string;
  allowed_root?: string | null;
  restrict_to_project: boolean;
  source: "session" | "turn" | "channel_default" | "system";
  label?: string | null;
  metadata?: Record<string, unknown>;
};
```

### WorkspaceScopeSnapshot Rules

- this object must be attached to every `UnifiedTurn`
- every execution object must reference the resolved workspace scope
- worker tasks must inherit or narrow this scope, never widen it

## WorkspaceSnapshot

`WorkspaceSnapshot` is the optional summarized project state at turn start.

```ts
type WorkspaceSnapshot = {
  snapshot_id: string;
  captured_at: number;
  root_path: string;
  branch_name?: string | null;
  dirty: boolean;
  changed_files?: string[];
  key_files?: string[];
  build_status?: "unknown" | "clean" | "dirty" | "broken";
  summary?: string | null;
  metadata?: Record<string, unknown>;
};
```

### WorkspaceSnapshot Rules

- this is a summary snapshot, not a full filesystem mirror
- capture should be cheap enough for normal request handling
- large repositories should use summarized state rather than exhaustive scans

## SessionMemorySnapshot

`SessionMemorySnapshot` represents long-lived conversational/project memory.

```ts
type SessionMemorySnapshot = {
  memory_id: string;
  session_key: string;
  summary?: string | null;
  active_topics: string[];
  active_constraints: string[];
  accepted_artifacts: string[];
  open_questions: string[];
  user_preferences?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};
```

### SessionMemorySnapshot Rules

- this must contain compressed, reusable context
- it should not be a raw dump of prior messages
- accepted artifacts should reference artifact ids, not duplicated payloads

## GoalStateSnapshot

`GoalStateSnapshot` captures long-running user objective state.

```ts
type GoalStateSnapshot = {
  goal_id: string;
  description: string;
  status: "active" | "paused" | "completed" | "failed";
  success_criteria: string[];
  progress_summary?: string | null;
  updated_at: number;
  metadata?: Record<string, unknown>;
};
```

### GoalStateSnapshot Rules

- this is required only when the turn is part of a broader sustained objective
- if absent, the runtime should treat the turn as self-contained unless execution creates a new goal

## CapabilityRequest

`CapabilityRequest` expresses requested or inferred capabilities for the turn.

```ts
type CapabilityRequest = {
  capability: string;
  source: "user" | "ui" | "channel" | "inferred";
  required: boolean;
  priority?: "low" | "medium" | "high";
  metadata?: Record<string, unknown>;
};
```

### CapabilityRequest Rules

- this object is advisory for `LLM1` and the capability router
- `required=true` means the runtime should not silently ignore the capability if execution depends on it

## OrchestrationMode

```ts
type OrchestrationMode = "direct" | "assisted" | "delegated" | "workflow";
```

This type must be shared across all runtime layers.

## ExecutionBrief

`ExecutionBrief` is the structured request from `LLM1` to `LLM3`.

```ts
type ExecutionBrief = {
  request_id: string;
  turn_id: string;
  session_key: string;
  mode: OrchestrationMode;
  created_at: number;
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
  metadata?: Record<string, unknown>;
};
```

### ExecutionBrief Rules

- `request_id` must be unique
- `turn_id` and `session_key` must always match the originating `UnifiedTurn`
- `mode` must not be `direct`
- `objective` must be concise and executable
- `success_criteria` must not be empty
- `continuation_of` should be set when generated after a rejected review loop

## ArtifactRequirement

```ts
type ArtifactRequirement = {
  kind: "code" | "document" | "image" | "audio" | "video" | "report" | "other";
  description: string;
  required: boolean;
  schema?: Record<string, unknown>;
};
```

## ExecutionResult

`ExecutionResult` is the structured output from `LLM3`.

```ts
type ExecutionResult = {
  request_id: string;
  turn_id: string;
  session_key: string;
  completed_at: number;
  status: "completed" | "partial" | "failed" | "cancelled";
  summary: string;
  evidence: EvidenceItem[];
  artifacts: ArtifactRef[];
  worker_results: WorkerResult[];
  validation_results: ValidationResult[];
  next_recommendation:
    | "accept"
    | "continue"
    | "retry"
    | "revise"
    | "ask_user"
    | "escalate";
  final_user_safe_answer_candidate?: string | null;
  metadata?: Record<string, unknown>;
};
```

### ExecutionResult Rules

- every execution request must return exactly one execution result
- `status` must reflect actual runtime completion state
- `worker_results` and `validation_results` must always be arrays
- `next_recommendation` is advisory, not authoritative
- the final answer candidate must never bypass review

## EvidenceItem

`EvidenceItem` gives `LLM1` and `LLM2` enough structured proof to review execution quality.

```ts
type EvidenceItem = {
  evidence_id: string;
  kind: "tool_output" | "worker_output" | "validation" | "artifact" | "observation" | "other";
  summary: string;
  source_id?: string | null;
  references?: string[];
  metadata?: Record<string, unknown>;
};
```

## ArtifactRef

`ArtifactRef` represents any execution product persisted by the runtime.

```ts
type ArtifactRef = {
  artifact_id: string;
  kind: "code" | "image" | "audio" | "video" | "document" | "report" | "other";
  name: string;
  local_path?: string | null;
  url?: string | null;
  mime_type?: string | null;
  created_at: number;
  producer: "llm3" | "worker" | "tool" | "system";
  producer_id?: string | null;
  metadata?: Record<string, unknown>;
};
```

### ArtifactRef Rules

- artifacts must be referenceable by id across review and memory systems
- local path and URL may coexist
- artifacts should not embed large binary payloads directly in the runtime object

## ReviewDecision

`ReviewDecision` is the structured acceptance output from `LLM1` and `LLM2`.

```ts
type ReviewDecision = {
  review_id: string;
  turn_id: string;
  request_id: string;
  created_at: number;
  decision: "accept" | "continue" | "retry" | "revise" | "ask_user" | "escalate";
  rationale: string;
  unmet_criteria: string[];
  continuation_brief?: {
    objective_delta?: string;
    additional_constraints?: string[];
    focus_areas?: string[];
  } | null;
  metadata?: Record<string, unknown>;
};
```

### ReviewDecision Rules

- every `ExecutionResult` must produce exactly one `ReviewDecision`
- `accept` means the system may proceed to final response generation
- non-accept decisions should explain unmet criteria
- `continuation_brief` should exist when the decision is `continue` or `revise`

## WorkerTaskSpec

`WorkerTaskSpec` defines a spawned worker as a first-class task.

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

### WorkerTaskSpec Rules

- workers must never be launched without `role` and `objective`
- `depends_on` must always exist as an array
- worker scope must be equal to or narrower than the parent request scope
- worker permissions must be explicit rather than implied

## WorkerResult

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

## ValidationResult

```ts
type ValidationResult = {
  validation_id: string;
  kind: "lint" | "test" | "build" | "review" | "schema" | "custom";
  status: "passed" | "failed" | "skipped" | "warning";
  summary: string;
  details?: string | null;
  references?: string[];
  metadata?: Record<string, unknown>;
};
```

## OrchestrationEvent

`OrchestrationEvent` is the normalized event object shared by runtime, UI, and persistence.

```ts
type OrchestrationEvent = {
  event_id: string;
  turn_id: string;
  session_key: string;
  request_id?: string | null;
  worker_id?: string | null;
  type:
    | "turn_started"
    | "turn_normalized"
    | "intent_interpreted"
    | "critique_completed"
    | "mode_selected"
    | "execution_prepared"
    | "execution_started"
    | "tool_started"
    | "tool_completed"
    | "worker_started"
    | "worker_completed"
    | "worker_failed"
    | "validation_completed"
    | "review_completed"
    | "continuation_requested"
    | "response_ready"
    | "turn_completed"
    | "turn_failed";
  created_at: number;
  summary?: string | null;
  payload?: Record<string, unknown>;
};
```

### OrchestrationEvent Rules

- all events must include `turn_id` and `session_key`
- execution and worker events should include `request_id` or `worker_id` when applicable
- UI rendering should consume these normalized events instead of transport-specific raw frames where possible

## Direct Response Object

For direct-mode requests that do not invoke `LLM3`, the runtime should still produce a normalized direct-response object.

```ts
type DirectResponse = {
  turn_id: string;
  session_key: string;
  response_text: string;
  rationale_summary?: string | null;
  metadata?: Record<string, unknown>;
};
```

This prevents direct mode from becoming a special untyped path.

## Validation Rules Summary

The following validation rules are mandatory:

- every inbound request must become a valid `UnifiedTurn`
- every execution-bearing turn must produce an `ExecutionBrief`
- every `ExecutionBrief` must produce one `ExecutionResult`
- every `ExecutionResult` must produce one `ReviewDecision`
- every worker must use `WorkerTaskSpec`
- every emitted runtime event must use `OrchestrationEvent`

If these rules are not satisfied, the runtime is not compliant with this schema.

## Nullability Rules

To reduce implementation confusion:

- collections should default to `[]`
- optional compound snapshots may be `null` or omitted
- required ids must never be null
- user-facing text fields should default to `""` only when empty content is valid by contract

## Versioning

The orchestration schema should include an internal schema version when persisted.

Suggested wrapper:

```ts
type VersionedEnvelope<T> = {
  schema_version: string;
  payload: T;
};
```

The first version should be:

- `llm3-schema-v1`

## Compatibility Requirement

The first implementation may adapt current TeAI Builder runtime objects into
these schemas rather than replacing every old structure immediately.

However:

- new executive logic must consume the new schema
- new execution and review logic must produce the new schema
- old internal runtime shapes must not leak upward into executive orchestration APIs

## Follow-Up Documents

After this schema document, the next most useful documents are:

1. `llm3-execution-contract.md`
2. `llm3-worker-runtime-plan.md`
3. `llm3-capability-router-plan.md`
4. `llm3-event-model.md`

## Final Constraint

If implementation keeps:

- raw channel envelopes as orchestration inputs
- free-form spawn calls as worker definitions
- untyped execution results
- optional review outputs

then the implementation violates this schema design.
