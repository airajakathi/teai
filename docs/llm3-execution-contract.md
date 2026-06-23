# LLM3 Execution Contract

## Status

Draft execution contract document.

This document defines the operational contract between:

- `LLM1` as the executive user-facing orchestrator
- `LLM2` as the private critique and reflection partner
- `LLM3` as the execution runtime

This document extends:

- [`llm3-orchestration-plan.md`](./llm3-orchestration-plan.md)
- [`llm3-orchestration-spec.md`](./llm3-orchestration-spec.md)
- [`llm3-turn-schema.md`](./llm3-turn-schema.md)

It focuses on:

- execution request lifecycle
- `LLM1 -> LLM3` request contract
- `LLM3 -> LLM1` response contract
- continuation and retry loops
- progress and completion semantics
- failure semantics
- acceptance gates

## Purpose

The purpose of this contract is to stop `LLM3` from behaving like an
unbounded top-level agent and instead make it a controlled execution engine.

The contract must ensure:

- `LLM1` owns user satisfaction
- `LLM3` owns bounded execution
- `LLM2` improves review quality without becoming a second execution engine
- execution can continue through multiple passes without losing structure
- the runtime can support simple and complex orchestration using the same control protocol

## Core Rule

`LLM3` must never be treated as the final authority for the user-facing answer.

`LLM3` may propose:

- completion
- evidence
- artifacts
- candidate answers
- next-step recommendations

But only `LLM1`, after review with `LLM2`, may authorize the final answer that
is shown to the user.

## Execution Lifecycle

Every execution-bearing turn must follow this lifecycle:

1. `UnifiedTurn` is built
2. `LLM1` interprets intent
3. `LLM2` critiques interpretation and plan
4. `LLM1` creates `ExecutionBrief`
5. `LLM3` accepts or rejects the brief
6. `LLM3` executes
7. `LLM3` emits progress events
8. `LLM3` returns `ExecutionResult`
9. `LLM1` and `LLM2` review result
10. review outputs one `ReviewDecision`
11. one of:
   - accept
   - continue
   - retry
   - revise
   - escalate
   - ask user
12. if accepted, `LLM1` produces final user response

## Contract Layers

The execution contract has five layers:

1. intake contract
2. execution contract
3. progress contract
4. result contract
5. review / continuation contract

## 1. Intake Contract

The intake contract governs what `LLM3` may receive.

`LLM3` must only receive:

- `ExecutionBrief`
- continuation or retry requests derived from a previous review
- bounded runtime context needed for execution

`LLM3` must not receive:

- raw websocket envelopes
- raw UI state blobs
- ambiguous free-form top-level user prompts without structured execution context

## Execution Modes Allowed For LLM3

`LLM3` may only be invoked in these modes:

- `assisted`
- `delegated`
- `workflow`

`direct` mode must not invoke `LLM3`.

## ExecutionBrief

The request shape must conform to the shared schema definition.

```ts
type ExecutionBrief = {
  request_id: string;
  turn_id: string;
  session_key: string;
  mode: "assisted" | "delegated" | "workflow";
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

## ExecutionBrief Mandatory Rules

- `request_id` must be unique
- `turn_id` must identify the source turn
- `mode` must be non-direct
- `objective` must be a single clear execution objective
- `success_criteria` must define acceptance targets
- `constraints` must reflect policy, safety, workspace, and product boundaries
- `allowed_capabilities` must define what `LLM3` is permitted to use
- `workspace_scope` must be attached and already resolved

## ExecutionBrief Quality Rules

`LLM1` should ensure:

- the objective is specific enough to execute
- the success criteria are reviewable
- the request is not overloaded with unrelated instructions
- the allowed capabilities are no broader than necessary

If `LLM1` cannot produce a valid brief, it should:

- ask the user a clarifying question
- or choose `direct` mode instead of weak execution mode

## 2. Execution Acceptance Contract

Before doing work, `LLM3` should validate the incoming brief.

`LLM3` may reject execution if:

- required fields are missing
- the mode is invalid
- the request exceeds policy or budget constraints
- the workspace scope is invalid
- the requested capabilities are unsupported

If `LLM3` rejects the brief, it must return an immediate structured failure result.

## Execution Acceptance Result

If the brief is valid, `LLM3` should transition to `running`.

If invalid, `LLM3` should transition to `failed` without partial execution.

## 3. Allowed Actions Inside LLM3

While executing, `LLM3` may:

- call tools
- schedule worker tasks
- build or execute a task graph
- run validation
- checkpoint progress
- return partial progress signals

While executing, `LLM3` must not:

- return final user-facing acceptance on its own
- widen workspace scope beyond the brief
- exceed explicit worker or tool budgets without escalation
- silently skip success criteria

## Capability Boundaries

`LLM3` must treat `allowed_capabilities` as a hard policy boundary.

If a needed capability is not allowed, `LLM3` must:

- return `partial` or `failed`
- explain the unmet need in structured output
- recommend `revise`, `continue`, or `ask_user`

It must not silently use disallowed capabilities.

## Tool Budget Rules

If `tool_budget` is present:

- `LLM3` must not exceed `max_calls`
- `LLM3` must not exceed `max_mutations`

If a budget is reached before success:

- `LLM3` should stop cleanly
- mark status as `partial` unless the objective is already satisfied
- report which budget boundary was hit

## Worker Budget Rules

If `worker_budget` is present:

- `LLM3` must not exceed `max_workers`
- `LLM3` must not exceed `max_parallel`

If worker budget is exhausted:

- `LLM3` must continue using available paths if possible
- otherwise return `partial` with clear recommendation

## Time Budget Rules

If `time_budget` is present:

- `soft_timeout_ms` should trigger a graceful wind-down
- `hard_timeout_ms` must stop active execution

If `hard_timeout_ms` is hit:

- `LLM3` must return immediately with `partial` or `cancelled`
- any incomplete worker states must be reflected in the result

## 4. Progress Contract

`LLM3` must emit structured progress during execution.

Progress is needed for:

- UI transparency
- cancellation
- recovery
- review context

## Progress Event Categories

`LLM3` progress should include:

- execution started
- tool started
- tool completed
- worker started
- worker completed
- worker failed
- validation started
- validation completed
- checkpoint created
- graph step completed
- execution paused
- execution resumed

## Progress Event Rules

Progress events must:

- be tied to `turn_id`
- include `request_id`
- include timestamps
- summarize what changed
- avoid leaking raw provider internals unless needed for debugging

Progress events should not:

- be the only source of final status truth
- replace `ExecutionResult`

## 5. ExecutionResult

At the end of each execution pass, `LLM3` must return exactly one `ExecutionResult`.

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

## ExecutionResult Mandatory Rules

- exactly one result per execution request
- status must match real execution outcome
- evidence must be non-empty when work actually happened
- artifacts must be listed explicitly when produced
- worker results must be included if workers were used
- validation results must be included if validation was run
- the final candidate answer must be optional and non-authoritative

## ExecutionResult Status Semantics

### completed

Use when:

- execution finished
- success criteria appear satisfied
- no unresolved blocker remains inside `LLM3`

This does not imply final acceptance by `LLM1`.

### partial

Use when:

- meaningful work was completed
- but one or more criteria remain unmet
- or a budget/time boundary stopped full completion

### failed

Use when:

- execution could not proceed meaningfully
- the brief was invalid
- execution hit an unrecoverable error

### cancelled

Use when:

- cancellation was requested by the user or system
- or a hard termination policy interrupted execution

## Result Summary Semantics

The `summary` field must be:

- factual
- concise
- review-oriented

It should answer:

- what was attempted
- what succeeded
- what did not succeed
- what state the execution ended in

## Evidence Contract

`evidence` exists for review, not just logging.

Evidence should include:

- important tool outcomes
- important worker outcomes
- validation findings
- references to artifacts
- observed blockers or contradictions

Evidence should not:

- be a raw unfiltered dump of logs
- require `LLM1` to reverse-engineer execution from scratch

## Artifact Contract

If execution produces outputs, they must be represented as artifacts.

Examples:

- code changes
- generated docs
- images
- audio
- video
- reports

Artifacts must be referenceable by id and reviewable without reconstructing them from raw text.

## Worker Result Contract

If `LLM3` uses workers:

- each worker must produce a `WorkerResult`
- each `WorkerResult` must map back to its `worker_id`
- failures must not disappear into the parent summary

## Validation Result Contract

If validation is part of the execution path:

- each validation pass must be represented as a `ValidationResult`
- failures and warnings must remain visible to review
- validation must not be silently folded into generic narrative text

## 6. Review Contract

Every `ExecutionResult` must be reviewed before any user-facing final response is emitted.

`LLM1` and `LLM2` together must produce one `ReviewDecision`.

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

## Review Decision Meanings

### accept

Use when:

- execution result satisfies user intent
- evidence is sufficient
- no follow-up execution is needed

Effect:

- `LLM1` may produce final user response

### continue

Use when:

- execution is on the right track
- additional work is needed
- same broad objective still holds

Effect:

- create new `ExecutionBrief` with `continuation_of`

### retry

Use when:

- execution failed due to transient or recoverable issues
- the same objective should be attempted again

Effect:

- create new `ExecutionBrief` with retry metadata

### revise

Use when:

- the approach was wrong or incomplete
- the objective or constraints need refinement

Effect:

- create a new modified execution brief

### ask_user

Use when:

- user clarification is required
- execution cannot continue responsibly without it

Effect:

- `LLM1` asks user directly

### escalate

Use when:

- more complex execution mode is now needed
- for example assisted -> delegated or delegated -> workflow

Effect:

- `LLM1` creates a new execution brief with a deeper mode

## Continuation Contract

If review outputs `continue`, `retry`, or `revise`, the next pass must be linked to the prior one.

This linkage must include:

- prior `request_id`
- review rationale
- unmet criteria
- continuation delta

The next `ExecutionBrief` should include:

- `continuation_of`
- narrowed or refined objective
- updated constraints if needed
- preserved workspace scope unless explicitly changed by policy

## Retry Contract

Retries must be explicit, not implicit.

The runtime should distinguish:

- same-plan retry
- revised-plan retry
- resumed-partial retry

Retries should carry metadata such as:

- retry count
- previous failure reason
- changed constraints if any

## Escalation Contract

Escalation means the orchestration mode changes because the current one is insufficient.

Allowed escalations:

- `assisted -> delegated`
- `delegated -> workflow`
- `assisted -> workflow` if justified

Escalation must never happen silently.

It must be represented in:

- review decision
- next execution brief
- orchestration event stream

## Failure Contract

The runtime must distinguish these conditions:

- invalid request
- unsupported capability
- tool failure
- worker failure
- validation failure
- policy violation
- budget exhaustion
- timeout
- cancellation
- incomplete execution

These should not collapse into one generic error string.

## Failure Reporting Rules

If `LLM3` fails:

- `status` must be `failed` or `partial`
- `summary` must describe the failure boundary
- `evidence` should include the primary blocker
- `next_recommendation` should point toward the most appropriate next move

## Acceptance Gate

The acceptance gate is the strict control point between execution and user response.

The system must not let execution-derived content reach the user as the final
answer unless:

- `ExecutionResult` exists
- `ReviewDecision` exists
- `ReviewDecision.decision === "accept"`

This is mandatory.

## Final User Response Contract

When review accepts, `LLM1` must produce the final response to the user.

That final response may use:

- the execution summary
- evidence
- artifacts
- the candidate answer from `LLM3`

But `LLM1` must remain responsible for:

- tone
- correctness framing
- user-facing completeness
- next-step communication

## Cancellation Contract

Cancellation may be initiated by:

- user action
- system timeout
- policy intervention

When cancellation happens:

- `LLM3` should stop further expansion of work
- active workers should be cancelled or marked incomplete
- the final `ExecutionResult` must use `cancelled` or `partial`
- the review layer must still receive a structured result when possible

## Direct Mode Bypass Rule

When `LLM1` selects `direct` mode:

- no `ExecutionBrief` is created
- no `ExecutionResult` is required
- no review loop is required
- `LLM1` may still consult `LLM2`

This keeps normal chat fast while preserving strict structure for execution-backed flows.

## Contract Compliance Conditions

The system is compliant with this execution contract only if:

- `LLM3` accepts structured requests only
- `LLM3` returns structured results only
- execution always passes through review before final answer
- retries and continuations are explicit
- workers remain bounded and typed
- escalation is explicit and inspectable

If any implementation allows:

- free-form top-level execution prompts to `LLM3`
- silent auto-accept of `LLM3` output
- untracked spawned workers
- hidden retries
- mode escalation without review

then the implementation violates this contract.

## Recommended Next Documents

The best next documents after this one are:

1. `llm3-worker-runtime-plan.md`
2. `llm3-capability-router-plan.md`
3. `llm3-event-model.md`
4. `llm3-state-model.md`

## Final Summary

This execution contract makes the architecture operational:

- `LLM1` issues bounded execution requests
- `LLM3` performs bounded execution
- `LLM2` helps critique and review
- every result is reviewed before being accepted
- continuations, retries, escalations, and failures remain explicit

That is the key step that turns the new `LLM1 / LLM2 / LLM3` architecture from a
concept into an implementable orchestration system.
