# LLM3 Codebase Replacement Map

## Status

Draft codebase replacement map.

This document maps the current TeAI Builder orchestration-related codebase to
the target `LLM1 / LLM2 / LLM3` architecture.

It answers:

- what current files/modules already exist
- what role they play today
- what role they should play in the target architecture
- whether each should be kept, wrapped, absorbed, or retired

This document extends:

- [`llm3-interface-map.md`](./llm3-interface-map.md)
- [`llm3-migration-roadmap.md`](./llm3-migration-roadmap.md)

## Purpose

The purpose of this document is to prevent migration confusion.

Without a replacement map, implementation tends to fail in one of two ways:

- developers rewrite too much because they do not know what can be reused
- developers keep too much because they do not know what still owns behavior

This document creates the bridge between:

- current runtime ownership
- target runtime ownership

## Replacement Labels

Each current module in this document is classified as one of:

- `Keep`
- `Wrap`
- `Absorb`
- `Refactor`
- `Retire`

### Keep

Keep as a useful low-level subsystem with limited change.

### Wrap

Preserve internally, but place behind a new interface so it stops being a direct top-level owner.

### Absorb

Merge its behavior into a new broader orchestration component.

### Refactor

Preserve the module family, but change its internal contract and ownership.

### Retire

Remove top-level orchestration ownership and eventually deprecate direct use.

## Current To Target Map

## 1. Channel Ingress

### Current

- [base.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/channels/base.py)
- [websocket.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/channels/websocket.py)

### Current Role

- accept external messages
- normalize some metadata
- publish `InboundMessage` onto the bus

### Target Role

- remain transport ingress layers only
- stop being implicit owners of orchestration semantics

### Migration Label

- `Keep`

### Notes

These modules should keep transport responsibilities, but the new turn-building and orchestration semantics should move above them.

## 2. Message Bus

### Current

- [events.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/bus/events.py)
- [queue.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/bus/queue.py)

### Current Role

- transport inbound/outbound chat messages

### Target Role

- continue to move channel messages
- coexist with normalized orchestration events

### Migration Label

- `Keep`

### Notes

The message bus remains important, but it should no longer double as the only orchestration lifecycle model.

## 3. Runtime Event Bus

### Current

- [runtime_events.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/bus/runtime_events.py)

### Current Role

- in-process runtime state notifications

### Target Role

- become an implementation vehicle for the new orchestration event model

### Migration Label

- `Refactor`

### Notes

Keep the pub/sub idea, but expand it from a few runtime notifications into the canonical orchestration event stream emitter path.

## 4. Progress Signaling

### Current

- [progress.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/bus/progress.py)

### Current Role

- send user-visible progress as outbound message metadata

### Target Role

- become a rendering adapter on top of normalized orchestration events

### Migration Label

- `Wrap`

### Notes

This should stop being the primary semantics layer and become a compatibility/rendering helper.

## 5. Agent Loop

### Current

- [loop.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/loop.py)

### Current Role

- top-level turn owner
- context builder
- execution coordinator
- runtime state publisher
- workflow/subagent/tool integration point

### Target Role

- execution backend and compatibility layer beneath the new executive runtime

### Migration Label

- `Wrap` then partial `Absorb`

### Notes

This is the most important ownership shift in the migration.

`loop.py` should stop being the undocumented top-level orchestration brain.

## 6. Agent Runner

### Current

- [runner.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/runner.py)

### Current Role

- iterative tool-call loop
- model invocation and tool execution inside one run

### Target Role

- remain a low-level execution primitive beneath `LLM3`

### Migration Label

- `Keep` / `Wrap`

### Notes

The runner is useful, but it should operate under structured `ExecutionBrief` ownership rather than as a hidden top-level orchestration loop.

## 7. Subagent Manager

### Current

- [subagent.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/subagent.py)

### Current Role

- spawn background subagents
- track subagent status

### Target Role

- temporary internal executor beneath the new worker runtime

### Migration Label

- `Wrap` then `Retire` as a direct public orchestration primitive

### Notes

The internal execution mechanics may stay useful for a while, but direct raw spawn semantics should disappear.

## 8. Parallel Executor

### Current

- [parallel_executor.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/parallel_executor.py)

### Current Role

- parallel task scheduling around subagent tasks

### Target Role

- scheduler logic source for the new worker runtime and task graph engine

### Migration Label

- `Absorb`

### Notes

Its behavior should move into the unified scheduler rather than remain a separate orchestration subsystem.

## 9. Workflow Engine

### Current

- [workflow_engine.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/workflow_engine.py)

### Current Role

- run deterministic workflow steps
- persist workflow run state
- manage checkpoints

### Target Role

- workflow definitions and durable run knowledge become graph templates/builders and graph-backed execution state

### Migration Label

- `Absorb` / `Refactor`

### Notes

The concept is valuable, but workflow execution should stop being its own orchestration world.

## 10. Checkpoint System

### Current

- [checkpoint.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/agent/checkpoint.py)

### Current Role

- save session/runtime snapshots
- rebuild/restore context checkpoints

### Target Role

- remain the persistence foundation for orchestration checkpoint state and recovery

### Migration Label

- `Refactor`

### Notes

Keep the store idea, but connect checkpoints directly to turn/execution/worker state instead of only session-centered rebuild flows.

## 11. Provider Registry

### Current

- [registry.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/providers/registry.py)

### Current Role

- provider metadata source of truth

### Target Role

- remain provider metadata source beneath the capability router

### Migration Label

- `Keep`

## 12. Provider Factory

### Current

- [factory.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/providers/factory.py)

### Current Role

- build provider instances from config/preset/model

### Target Role

- remain lower-level provider construction layer beneath the capability router

### Migration Label

- `Keep`

## 13. Image Generation Provider Seam

### Current

- [image_generation.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/providers/image_generation.py)

### Current Role

- image generation provider registry and clients

### Target Role

- remain capability-specific generation backend beneath the multimodal routing system

### Migration Label

- `Keep`

## 14. Audio Generation Provider Seam

### Current

- [audio_generation.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/providers/audio_generation.py)

### Current Role

- TTS provider seam

### Target Role

- remain capability-specific generation backend beneath the multimodal routing system

### Migration Label

- `Keep`

## 15. Video Generation Provider Seam

### Current

- [video_generation.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/providers/video_generation.py)

### Current Role

- video generation provider seam

### Target Role

- remain capability-specific generation backend, but grow under the unified multimodal routing model

### Migration Label

- `Keep` / `Refactor`

### Notes

The seam is useful but still thin, so it should be improved inside the new multimodal framework rather than replaced prematurely.

## 16. Transcription Registry

### Current

- [transcription_registry.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/audio/transcription_registry.py)

### Current Role

- speech-to-text provider registry

### Target Role

- remain a capability-specific backend registry beneath multimodal routing

### Migration Label

- `Keep`

## 17. Tool Registry / Tool Loader

### Current

- `tools/registry.py`
- `tools/loader.py`

### Current Role

- define and load callable tools

### Target Role

- remain the tool surface beneath `LLM3` execution and task graph nodes

### Migration Label

- `Keep`

## 18. Session Manager / Session State

### Current

- session manager and session helpers under `teai_builder/session`

### Current Role

- persist conversational history and some goal/runtime metadata

### Target Role

- remain useful session persistence infrastructure beneath the new orchestration state store

### Migration Label

- `Refactor`

### Notes

Session state should stop being the only place where orchestration truth is reconstructed.

## 19. WebUI Stream / History Hydration

### Current

- websocket delivery and frontend stream handling

### Current Role

- render mixed outbound messages and ad hoc runtime metadata

### Target Role

- render normalized orchestration events and state

### Migration Label

- `Wrap` then `Refactor`

## Replacement Order

The safest replacement order is:

1. wrap top-level turn ownership
2. wrap execution contract
3. wrap subagent spawn path
4. refactor runtime events into normalized event emission
5. refactor session/checkpoint state into orchestration state store
6. absorb parallel executor into worker/task-graph scheduler
7. absorb workflow engine into graph templates/builders
8. refactor UI to consume normalized orchestration state/events
9. retire legacy direct orchestration ownership

## What Must Not Be Replaced Early

Do not replace early:

- provider factory internals
- provider registry internals
- tool registry internals
- channel ingress fundamentals

These are useful low-level assets and not the main cause of orchestration fragmentation.

## What Must Be Replaced Early

Replace early:

- top-level loop ownership
- raw spawn ownership
- disconnected routing ownership
- fragmented execution-path ownership
- ad hoc orchestration lifecycle signaling

## Final Mapping Summary

The final architecture should look like this:

- channel ingress -> `Keep`
- message bus -> `Keep`
- runtime event bus -> `Refactor`
- progress signaling -> `Wrap`
- agent loop -> `Wrap` then partial `Absorb`
- agent runner -> `Keep` / `Wrap`
- subagent manager -> `Wrap` then `Retire` as direct orchestration primitive
- parallel executor -> `Absorb`
- workflow engine -> `Absorb` / `Refactor`
- checkpoint system -> `Refactor`
- provider registry -> `Keep`
- provider factory -> `Keep`
- image/audio/video/transcription seams -> `Keep` inside unified multimodal routing

## Final Summary

This replacement map shows that the migration is not about throwing away TeAI Builder.

It is about:

- preserving strong low-level infrastructure
- moving orchestration ownership into the new architecture
- absorbing fragmented execution systems into one coherent runtime
