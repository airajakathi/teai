# LLM3 Event Model

## Status

Draft event model document.

This document defines the normalized event stream for the new `LLM1 / LLM2 / LLM3`
orchestration architecture.

This document extends:

- [`llm3-orchestration-plan.md`](./llm3-orchestration-plan.md)
- [`llm3-orchestration-spec.md`](./llm3-orchestration-spec.md)
- [`llm3-turn-schema.md`](./llm3-turn-schema.md)
- [`llm3-execution-contract.md`](./llm3-execution-contract.md)
- [`llm3-worker-runtime-plan.md`](./llm3-worker-runtime-plan.md)
- [`llm3-capability-router-plan.md`](./llm3-capability-router-plan.md)

## Purpose

The purpose of this document is to define one shared orchestration event model
for:

- runtime state tracking
- UI progress rendering
- persistence
- debugging
- recovery
- review visibility
- worker lifecycle visibility

Today, TeAI Builder already has:

- a message bus
- inbound and outbound message objects
- progress callbacks
- channel metadata used to signal UI state

Those are useful foundations, but they are still too fragmented to serve as the
event backbone for the target orchestration system.

## Current Reality

The current event foundation is visible in:

- [events.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/bus/events.py)
- [progress.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/bus/progress.py)

The current system already supports:

- `InboundMessage`
- `OutboundMessage`
- outbound metadata flags
- progress messages
- reasoning deltas
- tool hints
- file edit events

This is real infrastructure, but it is not yet a full normalized orchestration
event model.

## Main Problem

The current runtime mixes different kinds of state into:

- channel transport messages
- outbound progress metadata
- runtime-only state
- feature-specific UI metadata

That causes several problems:

- orchestration state is harder to inspect
- UI clients reconstruct state from mixed low-level signals
- recovery is harder because event meaning is inconsistent
- worker and review state do not cleanly fit into the same stream
- persistence becomes lossy or ad hoc

## Main Goal

Create one normalized event model that becomes the shared truth for orchestration
state changes across the full runtime.

The event model must:

- describe all major orchestration transitions
- be channel-agnostic
- support UI and persistence equally
- support direct mode and execution mode
- support worker and review visibility
- support recovery and replay
- support future multimodal events without redesign

## Event Model Principles

The event model must follow these principles:

- one event vocabulary for the orchestration runtime
- one canonical event object shape
- event meaning must be stable across channels
- transport rendering must be separate from event semantics
- UI should subscribe to normalized orchestration events, not infer state from mixed metadata
- persisted events should be sufficient for debugging and partial replay

## What The Event Model Is Not

The event model is not:

- a replacement for transport-specific websocket frames
- a replacement for stored artifacts
- a replacement for result objects like `ExecutionResult`
- a raw log dump

Instead, it is:

- the canonical stream of meaningful orchestration state changes

## Event Scope

The event model must cover:

- turn lifecycle
- intent interpretation
- critique lifecycle
- mode selection
- capability routing
- execution preparation
- execution progress
- tool progress
- worker lifecycle
- validation lifecycle
- review lifecycle
- continuation and retry decisions
- response readiness
- cancellation
- failure
- recovery

## Canonical Event Object

All runtime orchestration events must use one canonical object.

```ts
type OrchestrationEvent = {
  event_id: string;
  event_version: string;
  turn_id: string;
  session_key: string;
  request_id?: string | null;
  worker_id?: string | null;
  parent_event_id?: string | null;
  type:
    | "turn_started"
    | "turn_normalized"
    | "intent_interpreted"
    | "critique_started"
    | "critique_completed"
    | "mode_selected"
    | "route_selected"
    | "execution_prepared"
    | "execution_started"
    | "tool_started"
    | "tool_completed"
    | "worker_planned"
    | "worker_queued"
    | "worker_ready"
    | "worker_started"
    | "worker_progress"
    | "worker_checkpointed"
    | "worker_completed"
    | "worker_failed"
    | "worker_cancelled"
    | "validation_started"
    | "validation_completed"
    | "review_started"
    | "review_completed"
    | "continuation_requested"
    | "retry_requested"
    | "escalation_requested"
    | "response_ready"
    | "turn_completed"
    | "turn_failed"
    | "turn_cancelled"
    | "recovery_started"
    | "recovery_completed";
  created_at: number;
  level?: "debug" | "info" | "warning" | "error";
  summary?: string | null;
  payload?: Record<string, unknown>;
};
```

## Canonical Event Rules

- every event must have a unique `event_id`
- every event must include `turn_id` and `session_key`
- execution events should include `request_id`
- worker events should include `worker_id`
- event semantics must not depend on transport
- `payload` must remain structured and JSON-serializable

## Event Versioning

The event model should be versioned.

The first version should be:

- `llm3-event-v1`

This should be stored in `event_version`.

## Event Categories

The event model should organize events into these conceptual categories:

1. turn events
2. executive events
3. routing events
4. execution events
5. worker events
6. validation events
7. review events
8. outcome events
9. recovery events

## 1. Turn Events

Turn events represent the start and normalization of the inbound request.

Events:

- `turn_started`
- `turn_normalized`
- `turn_completed`
- `turn_failed`
- `turn_cancelled`

### Turn Event Rules

- `turn_started` should be emitted once per inbound turn
- `turn_normalized` should be emitted after `UnifiedTurn` creation
- terminal turn events must be mutually exclusive

## 2. Executive Events

Executive events represent the `LLM1 / LLM2` layer.

Events:

- `intent_interpreted`
- `critique_started`
- `critique_completed`
- `mode_selected`
- `review_started`
- `review_completed`

### Executive Event Rules

- these events should not expose hidden chain-of-thought content
- they should expose status and summarized rationale, not raw private reasoning
- review lifecycle must be visible as first-class orchestration state

## 3. Routing Events

Routing events represent capability-router decisions.

Events:

- `route_selected`

This event should be emitted for:

- `LLM1`
- `LLM2`
- `LLM3`
- workers
- validation tasks
- multimodal tasks

### Routing Event Payload

The payload should include:

- role
- selected provider
- selected model
- fallback summary
- routing rationale

## 4. Execution Events

Execution events represent parent request execution under `LLM3`.

Events:

- `execution_prepared`
- `execution_started`
- `tool_started`
- `tool_completed`

### Execution Event Rules

- `execution_prepared` should follow creation of `ExecutionBrief`
- `execution_started` should indicate active execution begin
- tool events must remain structured and tied to `request_id`
- tool events must not be the only way to understand execution outcome

## 5. Worker Events

Worker events represent spawned bounded execution tasks.

Events:

- `worker_planned`
- `worker_queued`
- `worker_ready`
- `worker_started`
- `worker_progress`
- `worker_checkpointed`
- `worker_completed`
- `worker_failed`
- `worker_cancelled`

### Worker Event Rules

- worker events must map to a known `worker_id`
- worker events must be visible within the parent turn/request stream
- worker failures must not disappear into generic parent summaries
- worker checkpoint events should be emitted only when checkpointing is enabled

## 6. Validation Events

Validation events represent validation branches or nodes.

Events:

- `validation_started`
- `validation_completed`

### Validation Event Rules

- validation should be modeled explicitly instead of hidden inside narrative output
- the completed event should indicate pass/fail/warning/skipped state in payload

## 7. Review Events

Review events represent post-execution acceptance decisions.

Events:

- `review_started`
- `review_completed`
- `continuation_requested`
- `retry_requested`
- `escalation_requested`

### Review Event Rules

- every `ExecutionResult` should lead to `review_started` and `review_completed`
- if review chooses `continue`, `retry`, or `escalate`, there should be a corresponding explicit event
- review events must not reveal hidden private reasoning text

## 8. Outcome Events

Outcome events represent readiness to answer the user and the turn conclusion.

Events:

- `response_ready`
- `turn_completed`
- `turn_failed`
- `turn_cancelled`

### Outcome Event Rules

- `response_ready` means the final user-facing response is ready to be rendered or sent
- `response_ready` does not replace the actual final response payload
- turn terminal events must reflect actual state

## 9. Recovery Events

Recovery events represent resume and repair operations after interruption or failure.

Events:

- `recovery_started`
- `recovery_completed`

### Recovery Event Rules

- recovery should be explicit and visible
- recovery events should include a summarized reason in payload
- replay and resume systems should build on these events, not on ad hoc flags

## Event Payload Guidance

Every event may carry a `payload`, but the payload must remain structured.

Good payload examples:

- selected route summary
- worker status details
- validation status
- review decision
- checkpoint reference

Bad payload patterns:

- raw low-level provider dumps
- massive logs
- ambiguous free-form paragraphs that hide state transitions

## Event Payload Examples

### `mode_selected`

```ts
{
  "mode": "workflow",
  "reason": "Task requires decomposition, validation, and bounded worker execution."
}
```

### `route_selected`

```ts
{
  "role": "llm3",
  "provider": "openrouter",
  "model": "anthropic/claude-4-sonnet",
  "fallback_count": 2,
  "rationale": "Best tool-calling and structured-output fit for execution mode."
}
```

### `worker_completed`

```ts
{
  "status": "completed",
  "role": "ui_worker",
  "summary": "Finished UI prototype branch and produced 3 artifact files."
}
```

### `review_completed`

```ts
{
  "decision": "continue",
  "unmet_criteria_count": 2
}
```

## Event Ordering

The event stream should preserve causal ordering within a turn as much as possible.

Recommended guarantees:

- per-turn ordering should be stable
- per-request ordering should be stable
- per-worker ordering should be stable

Cross-worker global ordering may be approximate when execution is parallel, but
timestamps and parent references should make causality understandable.

## Parent/Child Event Relationships

`parent_event_id` should be used when one event is directly caused by another.

Examples:

- a `worker_started` event may point to the preceding `worker_ready`
- a `retry_requested` event may point to the related `review_completed`
- a `recovery_completed` event may point to `recovery_started`

This is helpful for debugging and later visualization.

## Event Model And UI

The WebUI should eventually consume normalized orchestration events instead of
depending mostly on:

- mixed outbound metadata flags
- channel-specific heuristics
- separate feature-specific client-side reconstruction rules

The UI should derive:

- turn progress
- worker activity
- validation status
- review status
- route visibility
- failure state
- recovery state

from the normalized event stream.

## Event Model And Persistence

The event model should be persisted as an event log per turn or session.

That log should support:

- debugging
- progress audit
- recovery
- state reconstruction
- developer tooling

The event log should not be treated as the only persisted data model.

Artifacts, results, reviews, and checkpoints still need their own structured objects.

## Event Model And Recovery

Recovery should rely on persisted normalized events plus structured state objects.

The runtime should be able to answer questions like:

- what step was the turn in when interrupted?
- which workers were active?
- which validations completed?
- did review happen already?
- was a continuation requested?

This is only reliable if the event stream is normalized and complete enough.

## Event Model And Current Bus

The current message bus should remain useful, but its role should become clearer:

- bus transports messages and events
- normalized orchestration events describe runtime meaning
- transport-specific outbound messages render those events for channels

This means the migration should not throw away the bus.

It should instead stop overloading `OutboundMessage.metadata` as the main long-term event model.

## Migration Plan

The migration should happen in phases.

### Phase 1

Define the canonical `OrchestrationEvent` object and event vocabulary.

Goal:

- establish one stable event contract

### Phase 2

Emit normalized turn, execution, and outcome events in parallel with current metadata-based progress signaling.

Goal:

- preserve compatibility while adding the new layer

### Phase 3

Emit worker, review, routing, and validation events.

Goal:

- cover all orchestration-critical state transitions

### Phase 4

Adapt WebUI to consume normalized events for orchestration state.

Goal:

- reduce client-side reconstruction complexity

### Phase 5

Persist event logs and use them for recovery and developer tooling.

Goal:

- make runtime introspection and resume reliable

### Phase 6

Deprecate ad hoc event semantics spread across metadata flags and subsystem-specific message formats.

Goal:

- one orchestration event model remains

## Minimum Compliance Requirements

The event model is compliant only if:

- all major orchestration transitions emit normalized events
- the UI can consume normalized events
- worker and review lifecycle are visible as first-class events
- execution, routing, and recovery use the same event vocabulary
- event semantics are transport-agnostic

If implementation still relies primarily on:

- ad hoc metadata flags
- hidden worker state
- hidden review outcomes
- transport-specific lifecycle meaning

then it is not compliant with this plan.

## Recommended Next Documents

The best next documents after this one are:

1. `llm3-state-model.md`
2. `llm3-task-graph-plan.md`
3. `llm3-multimodal-routing-plan.md`
4. `llm3-migration-roadmap.md`

## Final Summary

This event model gives the new orchestration architecture one shared language
for runtime state changes.

That is essential because the target system cannot work cleanly if:

- UI sees one lifecycle
- workers use another lifecycle
- review uses another lifecycle
- recovery uses another lifecycle

With this model, all of those become part of one inspectable orchestration event stream.
