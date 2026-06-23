# LLM3 Unified Orchestration Plan

## Status

Draft implementation plan only.

This document defines how to replace the current fragmented orchestration with a
single unified orchestration system built around three top-level LLM roles:

- **LLM1** — user-facing executive model
- **LLM2** — private inner-deliberation / reflection model
- **LLM3** — execution and orchestration model

For this document, **LLM3** means the current main runtime LLM path that today
drives `AgentLoop` and `AgentRunner`.

This plan intentionally does **not** add MiniCPM or any new omni/offline model
yet. The architecture must first be made correct, stable, and extensible.

## Why This Change Is Needed

The current TeAI Builder runtime has real orchestration, but it is spread across
multiple independent control paths:

- user-message orchestration in `AgentLoop`
- tool iteration in `AgentRunner`
- spawned-worker orchestration in `SubagentManager`
- workflow orchestration in `WorkflowEngine`
- modality-specific routing for vision, transcription, image generation, video generation, and TTS
- UI/runtime progress orchestration through the bus and websocket events

This creates several known problems:

- spawned subagents are not consistently reliable
- simple chat and complex build flows do not share one executive brain
- multimodal input is not processed through one common reasoning pipeline
- provider/model routing is fragmented across chat, tools, and modality seams
- recovery, retries, checkpoints, and validation semantics are inconsistent

The goal is to replace all of that with **one orchestration brain** that can:

- answer normal user requests directly
- handle complex builds safely
- delegate to workers without fragile special paths
- fuse text, image, audio, video, files, and workspace state into one turn model
- support future offline and omni models without another architecture rewrite

## Target Mental Model

The new orchestration should behave more like a human executive brain than a
collection of separate runtimes.

The core behavior should be:

1. understand exactly what the user wants
2. analyze possible approaches internally
3. decide whether to answer directly or execute work
4. drive execution until the result is actually satisfactory
5. review the result and refine instructions if needed
6. only then return the final answer

In this design:

- **LLM1** is the external communicator and executive owner of the user request
- **LLM2** is the private inner-thought / critical reflection partner for LLM1
- **LLM3** is the operational brain that executes tools, workers, and workflows

LLM1 and LLM2 sit **in front of** the current main LLM path instead of replacing
it immediately.

## Role Definitions

## LLM1

LLM1 is the only top-level model directly responsible for satisfying the user.

Responsibilities:

- understand the user's actual intent
- maintain the user-facing contract
- decide whether the request needs direct response or execution
- produce execution briefs for LLM3
- review LLM3 outputs
- ask LLM3 to continue, revise, retry, or change direction when needed
- decide when the result is good enough to present back to the user

LLM1 should behave like:

- executive planner
- user advocate
- acceptance authority
- final responder

LLM1 must not become a second implementation runtime. It should drive decisions,
not duplicate full tool orchestration itself.

## LLM2

LLM2 is a private deliberation model connected to LLM1 only.

Responsibilities:

- act as internal critique and analysis
- challenge weak assumptions from LLM1
- help decompose ambiguous requests
- evaluate whether an LLM3 result truly matches the user intent
- help detect hallucination, shallow execution, or incomplete work
- recommend whether to answer, continue, retry, re-plan, or spawn workers

LLM2 should behave like:

- internal critic
- reasoning partner
- risk detector
- quality auditor

LLM2 is not user-facing and is not the main execution agent. It improves the
quality of LLM1 decisions.

## LLM3

LLM3 is the current main execution runtime evolved into a cleaner role.

Responsibilities:

- execute tasks from LLM1
- run tools
- run spawned workers
- run structured workflows
- collect evidence and artifacts
- return structured progress and completion payloads

LLM3 should behave like:

- operations brain
- tool-use engine
- delegation engine
- workflow executor

In the first migration stage, LLM3 can reuse most of the current `AgentLoop`,
`AgentRunner`, tool registry, workflow runtime, and worker runtime underneath a
new orchestration contract.

## Unified Orchestration Modes

There should be only **one orchestration system**, but it should support several
execution depths.

### Mode 1: Direct Response

Use when:

- the user asked a simple question
- no execution is required
- no tool, worker, or workflow is needed

Flow:

- user -> LLM1
- LLM1 consults LLM2 if needed
- LLM1 responds directly

### Mode 2: Assisted Response

Use when:

- the answer needs lightweight evidence
- one or a few tools are sufficient
- no full worker graph is needed

Flow:

- user -> LLM1
- LLM1 + LLM2 produce execution brief
- brief -> LLM3
- LLM3 runs tools and returns evidence
- LLM1 reviews and answers

### Mode 3: Delegated Work

Use when:

- the task is too large for a single tool loop
- specialist workers are required
- the task can still be handled as bounded execution

Flow:

- user -> LLM1
- LLM1 + LLM2 produce task brief
- LLM3 spawns worker tasks under policy
- LLM3 merges results and sends back structured outcome
- LLM1 approves or requests another pass

### Mode 4: Structured Build Workflow

Use when:

- the user asked for app building, multi-step implementation, deployment, or long-running work
- dependencies, checkpoints, retries, and validation are needed

Flow:

- user -> LLM1
- LLM1 + LLM2 approve plan and success criteria
- LLM3 builds a task graph / workflow
- LLM3 executes workers, tools, validation, checkpoints, and recovery
- LLM1 accepts or loops for refinement

These are not separate runtimes. They are different operating modes of one
orchestrator.

## Target End-to-End Flow

The new canonical flow should be:

1. user message arrives from WebUI or another channel
2. input is normalized into one unified turn object
3. LLM1 interprets the user intent
4. LLM2 critiques the interpretation and proposed response strategy
5. LLM1 chooses one of the unified orchestration modes
6. if execution is needed, LLM1 sends an execution brief to LLM3
7. LLM3 runs tools, workers, or workflow tasks
8. LLM3 returns structured outputs, evidence, artifacts, and completion state
9. LLM1 and LLM2 review the result
10. if unsatisfactory, LLM1 sends a continuation or correction brief to LLM3
11. once satisfactory, LLM1 sends the final user-facing answer

This creates a closed loop:

`user -> LLM1 <-> LLM2 -> LLM3 -> LLM1 <-> LLM2 -> user`

## Required Architectural Changes

## 1. Unified Turn Object

All incoming requests must be normalized into one shared structure before any
LLM sees them.

Suggested fields:

- `turn_id`
- `session_key`
- `channel`
- `user_message`
- `attachments`
- `image_inputs`
- `audio_inputs`
- `video_inputs`
- `workspace_scope`
- `workspace_snapshot`
- `session_memory`
- `goal_state`
- `requested_capabilities`
- `ui_hints`

This becomes the single perception object for LLM1, LLM2, and LLM3.

## 2. Executive Deliberation Layer

A new front layer must sit above the current runtime.

Components:

- `ExecutiveController`
- `LLM1Session`
- `LLM2DeliberationSession`
- `IntentInterpreter`
- `AcceptanceReviewer`

This layer owns:

- user intent understanding
- task classification
- answer-vs-execute decision
- acceptance criteria
- retry / continue / reject decisions for LLM3 output

## 3. LLM3 Execution Contract

LLM3 must stop acting like a vague general-purpose top-level brain.

It should receive a structured request from LLM1:

- `objective`
- `success_criteria`
- `mode`
- `constraints`
- `allowed_capabilities`
- `tool_budget`
- `worker_budget`
- `time_budget`
- `workspace_scope`
- `artifact_requirements`
- `response_schema`

LLM3 returns:

- `status`
- `summary`
- `evidence`
- `artifacts`
- `worker_results`
- `validation_results`
- `next_recommendation`
- `final_user_safe_answer_candidate`

This contract is the key step that makes LLM3 controllable.

## 4. Replace Spawn With Worker Tasks

Current spawned subagents must be redesigned as first-class worker tasks under
the unified execution engine.

Every spawned worker must have:

- `worker_id`
- `role`
- `objective`
- `expected_output_schema`
- `dependencies`
- `permissions`
- `workspace_scope`
- `budget`
- `timeout`
- `checkpoint_policy`

The system should stop thinking in terms of ad hoc spawned agents and start
thinking in terms of scheduled, typed worker tasks.

## 5. Merge Tool, Worker, and Workflow Execution

The system should have one `Task Graph Runtime`.

Each execution node is one of:

- `DirectAnswerNode`
- `ToolNode`
- `WorkerNode`
- `WorkflowNode`
- `ValidationNode`
- `MergeNode`
- `RespondNode`

Normal chat uses a tiny graph.
Complex builds use a larger graph.
Same runtime, same state model, same recovery model.

## 6. Unified Capability Router

Model/provider selection must be capability-driven instead of being split
between chat presets and modality-specific tool seams.

Each provider/model capability should declare:

- `supports_text_in`
- `supports_text_out`
- `supports_image_in`
- `supports_image_out`
- `supports_audio_in`
- `supports_audio_out`
- `supports_video_in`
- `supports_video_out`
- `supports_tool_calls`
- `supports_streaming`
- `supports_structured_output`
- `is_local`
- `latency_profile`
- `cost_profile`
- `best_for`

LLM1, LLM2, and LLM3 should use this shared router instead of hardcoded
provider decisions spread across the runtime.

## 7. Unified Runtime State

One runtime state store must become the source of truth for:

- active turns
- worker tasks
- workflows
- checkpoints
- retries
- current mode
- accepted artifacts
- pending review loops
- cancellation state

This state layer should replace ad hoc coordination split across session files,
workflow files, transcript metadata, and runtime-local structures.

## 8. Review and Satisfaction Loop

LLM1 must be able to reject an LLM3 result and send it back for another pass.

This requires an explicit review loop:

1. LLM3 completes work
2. result is summarized into a review packet
3. LLM1 + LLM2 review against user intent and acceptance criteria
4. decision becomes one of:
   - accept
   - continue
   - revise
   - retry
   - escalate to workers
   - ask user

Without this loop, LLM1 is not truly the executive owner of the task.

## 9. Multimodal Readiness Without New Omni Model Yet

Even without MiniCPM for now, the architecture must be prepared for unified
multimodal processing later.

The system must treat these as first-class inputs:

- text
- images
- audio
- video
- files
- workspace state

The important change right now is architectural:

- one input schema
- one executive decision layer
- one task graph runtime
- one provider capability router

Then offline or omni models can be added later without restructuring the system.

## Module-Level Replacement Plan

## Layer A: Preserve Initially

These can be kept in the first migration stage and adapted behind new contracts:

- `MessageBus`
- websocket ingress / bootstrap
- transcript persistence
- `ToolRegistry`
- existing tool implementations
- current provider adapters
- checkpoint storage
- workflow run storage

## Layer B: Wrap and Control

These should remain temporarily but be driven through the new orchestration API:

- `AgentLoop`
- `AgentRunner`
- `SubagentManager`
- `ParallelExecutor`
- `WorkflowEngine`

In the first phase, these become implementation backends under LLM3.

## Layer C: Replace

These should be replaced conceptually by the new system:

- top-level decision logic currently inside `AgentLoop`
- direct spawn semantics
- fragmented workflow-vs-tool-vs-worker selection
- modality routing scattered across different runtime branches
- provider selection spread across config, presets, and tool seams

## Implementation Phases

## Phase 0: Architecture Freeze

Goal:

- agree on the LLM1 / LLM2 / LLM3 architecture and contracts before coding

Deliverables:

- this plan
- execution contract for LLM3
- review contract for LLM1 / LLM2
- unified turn schema
- unified event schema

Exit criteria:

- no ambiguity remains about each LLM role

## Phase 1: Introduce the Executive Layer

Goal:

- add LLM1 and LLM2 in front of the current runtime without breaking current channels

Deliverables:

- `ExecutiveController`
- LLM1 request interpreter
- LLM2 critique loop
- decision engine for direct response vs execution

Exit criteria:

- simple user messages can be processed by LLM1 / LLM2 without invoking the old execution path unnecessarily

## Phase 2: Convert Current Runtime Into LLM3

Goal:

- turn the current main orchestration path into a controlled execution engine

Deliverables:

- structured input contract from LLM1 to LLM3
- structured output contract from LLM3 to LLM1
- adapter layer around current `AgentLoop` / `AgentRunner`

Exit criteria:

- LLM3 no longer owns top-level user interaction decisions

## Phase 3: Worker Task Runtime

Goal:

- replace fragile spawn behavior with typed worker tasks

Deliverables:

- worker task schema
- worker lifecycle manager
- dependency handling
- permissions / budget enforcement
- worker result schemas

Exit criteria:

- spawned workers are launched, tracked, and reviewed through one standard runtime path

## Phase 4: Unified Task Graph Runtime

Goal:

- merge tools, workers, and workflows into one graph-driven execution system

Deliverables:

- task graph model
- graph executor
- checkpoint hooks
- retry / recovery policy
- cancellation policy

Exit criteria:

- complex build flows no longer rely on separate orchestration concepts

## Phase 5: Capability Router

Goal:

- centralize all model/provider selection decisions

Deliverables:

- capability registry
- routing policy
- role-based model selection for LLM1, LLM2, LLM3
- modality-to-provider mapping

Exit criteria:

- model selection becomes capability-driven and inspectable

## Phase 6: Review and Acceptance Loop

Goal:

- make LLM1 the true owner of user satisfaction

Deliverables:

- result review packets
- acceptance criteria evaluator
- retry / continue / revise loop
- explicit user-safe final answer selection

Exit criteria:

- LLM3 outputs are never blindly returned to the user

## Phase 7: State and Event Unification

Goal:

- unify runtime state and UI updates

Deliverables:

- single runtime state store
- normalized orchestration events
- worker / workflow / tool / review event stream

Exit criteria:

- the WebUI sees one coherent orchestration timeline

## Phase 8: Legacy Decommission

Goal:

- remove old fragmented orchestration ownership

Deliverables:

- disable legacy top-level agent decision path
- disable legacy spawn-only orchestration path
- reduce workflow engine to task-graph internals or remove it

Exit criteria:

- one orchestration system remains

## Success Criteria

The new system is successful only if all of the following are true:

- normal user requests are faster and simpler than today
- complex build requests are more reliable than today
- LLM1 always owns the user contract
- LLM2 improves quality without becoming a second user-facing runtime
- LLM3 becomes a controllable execution engine
- spawned workers stop being a fragile special case
- workflows, workers, and tools share one execution model
- multimodal support can be expanded later without another architecture rewrite

## Non-Goals For This Stage

This document does not include:

- MiniCPM or another offline omni model integration
- a full provider capability matrix
- implementation details of prompt content
- exact class names that must be final
- frontend redesign details

Those should be defined after the orchestration contracts are accepted.

## Risks

## Risk 1: LLM1 Becomes Too Heavy

If LLM1 starts doing too much execution logic itself, the architecture will
collapse back into another overloaded top-level loop.

Mitigation:

- LLM1 owns decisions, not operational execution

## Risk 2: LLM2 Becomes Redundant

If LLM2 does not have a clear critique role, it will just duplicate LLM1.

Mitigation:

- give LLM2 explicit critique, challenge, and acceptance responsibilities

## Risk 3: LLM3 Remains Too Autonomous

If LLM3 still owns top-level task decisions, the architecture will not really change.

Mitigation:

- require structured execution briefs and structured outputs

## Risk 4: Spawn Runtime Is Rebuilt Instead Of Replaced

If subagents remain a separate orchestration subsystem, the main problem stays alive.

Mitigation:

- redesign subagents as worker tasks inside the unified task graph runtime

## Risk 5: Big-Bang Rewrite Failure

Replacing everything at once would be risky.

Mitigation:

- migrate in layers
- keep current runtime as LLM3 backend first
- decommission old ownership gradually

## Immediate Next Documents

After this plan is accepted, the next documents to create should be:

1. `llm3-orchestration-spec.md`
2. `llm3-turn-schema.md`
3. `llm3-execution-contract.md`
4. `llm3-worker-runtime-plan.md`
5. `llm3-capability-router-plan.md`

## Final Summary

The correct migration strategy is:

- treat the current main runtime as **LLM3**
- add **LLM1** and **LLM2** in front of it
- make LLM1 the user-facing executive
- make LLM2 the private reflection partner
- reduce LLM3 into a structured execution engine
- merge tools, workers, and workflows into one unified orchestration runtime

This is the cleanest path to a single orchestration system that works for both:

- normal user requests
- complex build execution

without keeping the current fragmented orchestration model alive.
