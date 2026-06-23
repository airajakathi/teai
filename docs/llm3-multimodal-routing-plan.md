# LLM3 Multimodal Routing Plan

## Status

Draft multimodal routing plan.

This document defines how the new `LLM1 / LLM2 / LLM3` architecture should
handle text, image, audio, video, and files as one coherent orchestration
system.

This document extends:

- [`llm3-orchestration-plan.md`](./llm3-orchestration-plan.md)
- [`llm3-orchestration-spec.md`](./llm3-orchestration-spec.md)
- [`llm3-turn-schema.md`](./llm3-turn-schema.md)
- [`llm3-execution-contract.md`](./llm3-execution-contract.md)
- [`llm3-worker-runtime-plan.md`](./llm3-worker-runtime-plan.md)
- [`llm3-capability-router-plan.md`](./llm3-capability-router-plan.md)
- [`llm3-event-model.md`](./llm3-event-model.md)
- [`llm3-state-model.md`](./llm3-state-model.md)
- [`llm3-task-graph-plan.md`](./llm3-task-graph-plan.md)

## Purpose

The purpose of this document is to define one multimodal routing and fusion
strategy for the new architecture.

The system must be able to treat these as part of one orchestration brain:

- text
- image
- audio
- video
- file/document inputs

At the same time, the plan must stay honest about the current TeAI Builder reality:

- text/chat is the strongest path today
- image generation is fairly real
- transcription is real but separate
- TTS is narrower
- video generation is currently the thinnest path

This document defines how to unify these without pretending they are already one perfect native omni runtime.

## Current Reality

TeAI Builder already has real separate multimodal seams:

- image generation provider seam in [image_generation.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/providers/image_generation.py)
- video generation provider seam in [video_generation.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/providers/video_generation.py)
- audio generation provider seam in [audio_generation.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/providers/audio_generation.py)
- transcription registry in [transcription_registry.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/audio/transcription_registry.py)

This is valuable because the codebase already recognizes that multimodal capabilities are not identical to generic text chat.

However, those paths are still fragmented. The new architecture must unify them under one orchestration decision layer.

## Main Goal

Create one multimodal routing model where:

- all user inputs are normalized into one turn object
- modality-specific processing is routed through the same orchestration framework
- `LLM1`, `LLM2`, and `LLM3` can reason over fused multimodal context
- generation tasks remain capability-specific but orchestration-consistent

## Core Principle

The architecture must not have:

- one brain for text
- one brain for image
- one brain for audio
- one brain for video

Instead it must have:

- one orchestration system
- multiple modality capabilities routed inside that system

## Multimodal Scope

The multimodal plan must cover:

- text input
- image input
- audio input
- video input
- file/document input
- image generation
- audio generation
- video generation
- multimodal understanding
- multimodal output packaging

## Two Different Multimodal Classes

The architecture must distinguish two broad multimodal classes:

1. multimodal understanding
2. multimodal generation

### Multimodal Understanding

Examples:

- user uploads image and asks question
- user uploads audio that must be transcribed and understood
- user uploads video that must be summarized
- user uploads file/document requiring extraction and reasoning

### Multimodal Generation

Examples:

- user asks to generate image
- user asks to generate speech audio
- user asks to generate video

These are not the same problem and should not be forced through one fake universal API path.

## Multimodal Routing Principles

The multimodal routing system must follow these principles:

- all modalities normalize into one top-level turn
- modality-specific preprocessing should be explicit
- routing should happen by capability, not by ad hoc flags only
- multimodal outputs must remain traceable to artifacts and events
- the architecture must support partial multimodal maturity without breaking the unified model

## Unified Turn Requirement

All multimodal inputs must enter through `UnifiedTurn`.

That means:

- text goes into `user_message`
- image/audio/video inputs become `MediaInput`
- files become `AttachmentRef`
- extracted summaries and transcripts become derived structured fields

This avoids transport-specific modality drift.

## Multimodal Processing Stages

The target multimodal flow should have these stages:

1. intake normalization
2. modality detection
3. preprocessing
4. capability routing
5. understanding or generation execution
6. fusion into execution/review context
7. artifact production and response packaging

## Stage 1: Intake Normalization

The system must normalize all raw inputs into:

- `UnifiedTurn`
- `AttachmentRef`
- `MediaInput`

This stage must not do heavy reasoning yet.

Its job is:

- transport normalization
- metadata capture
- raw reference creation

## Stage 2: Modality Detection

The runtime must determine:

- which modalities are present
- which modalities require immediate preprocessing
- whether the request is understanding-focused or generation-focused

Examples:

- image upload with question -> understanding
- audio upload -> transcription first
- prompt with "generate an image" -> generation
- prompt with mixed text + image + file -> understanding plus possible execution

## Stage 3: Preprocessing

Preprocessing should be explicit and routable.

Examples:

- audio -> transcription
- image -> metadata extraction or vision analysis
- video -> frame sampling or summary extraction
- document/file -> parsing or chunk extraction

Preprocessing should be treated as:

- graph-accounted work
- event-producing work
- state-producing work

It must not remain a hidden side-effect only.

## Stage 4: Capability Routing

After preprocessing, the capability router must choose:

- which model/provider handles understanding
- which model/provider handles generation
- whether one multimodal-capable model is sufficient
- whether multiple specialized routes are needed

The router should prefer:

- the fewest necessary processing stages
- the most policy-compliant route
- the strongest capability match

## Stage 5: Understanding Or Generation Execution

At this stage, the runtime does one of two things.

### Understanding Path

The runtime may:

- call a vision-capable model
- call transcription service
- call file/document extraction tools
- combine extracted information into a fused context package

### Generation Path

The runtime may:

- call image generation provider
- call TTS provider
- call video generation provider

These generation routes still remain part of the same orchestration flow, even if they hit different provider families.

## Stage 6: Context Fusion

After preprocessing or understanding, the results must be fused into a shared reasoning context.

The fused context should include:

- user message
- extracted image insights
- extracted transcript
- extracted video summary
- document/file summary
- workspace/project context

This fusion layer is what allows the orchestration system to act more like one brain rather than isolated modality silos.

## Stage 7: Output Packaging

Final outputs may include:

- text response
- image artifacts
- audio artifacts
- video artifacts
- mixed response bundles

The runtime must represent these with:

- `ArtifactRef`
- event updates
- state references

not only raw blob outputs.

## Multimodal Roles In The Architecture

The multimodal system interacts with the main roles like this:

### LLM1

`LLM1` owns:

- interpreting what the user wants across modalities
- deciding whether the request needs multimodal execution
- deciding whether the final result satisfies the user

### LLM2

`LLM2` owns:

- critiquing modality interpretation
- checking whether extracted multimodal context seems sufficient
- checking whether multimodal outputs satisfy the request

### LLM3

`LLM3` owns:

- running the multimodal processing graph
- calling preprocessing, understanding, and generation capabilities
- returning structured multimodal results

## Current Modality Maturity

The architecture must be honest about current maturity levels.

### Text

Current state:

- strongest path
- fully integrated with orchestration

### Image Understanding

Current state:

- partially real through vision-capable model routing
- depends on configured vision-capable model availability

### Image Generation

Current state:

- real provider seam
- meaningful provider coverage

### Audio Input

Current state:

- transcription-first path
- not yet a native speech-to-speech conversational loop

### Audio Generation

Current state:

- real TTS seam
- narrower provider coverage than text/image

### Video Understanding

Current state:

- comparatively weak today
- needs explicit routing and likely preprocessing stages

### Video Generation

Current state:

- very thin compared with image/text
- currently more of a provider seam than a mature fully integrated path

## Multimodal Capability Taxonomy

The capability router should use explicit multimodal capabilities such as:

- `vision_understanding`
- `image_captioning`
- `document_understanding`
- `audio_transcription`
- `audio_understanding`
- `video_understanding`
- `image_generation`
- `audio_generation`
- `video_generation`
- `multimodal_fusion`

This lets the orchestrator choose precise routes instead of hand-written modality branches.

## Understanding Modes

The first implementation should support three understanding modes:

### Native Single-Model Understanding

Use when:

- one model can consume the required modalities directly

### Pipeline Understanding

Use when:

- preprocessing is required first
- example: audio -> transcript -> reasoning

### Hybrid Understanding

Use when:

- multiple modality-specific processing steps are required
- example: video summary + file summary + text reasoning

The router should choose among these modes based on capability and policy.

## Generation Modes

The first implementation should support:

### Direct Generation

Examples:

- text prompt to image
- text prompt to speech
- text prompt to video

### Guided Generation

Examples:

- image generation with reference images
- video generation from reference image
- voice synthesis with voice/format/speed controls

### Multi-Artifact Generation

Examples:

- produce text summary plus image
- produce text explanation plus audio narration

These should still be graph-accounted execution paths.

## Multimodal Graph Integration

Multimodal processing should run on the unified task graph engine.

Examples:

- audio upload -> transcription node -> understanding node -> validation node
- image upload -> vision node -> merge node -> response candidate node
- text prompt -> image-generation node -> artifact validation node -> response candidate node

This is critical because multimodal orchestration must not create another side execution system.

## Multimodal Event Integration

The event model should expose multimodal processing clearly.

Examples of useful payload patterns:

- route selected for vision understanding
- transcription completed
- image generation completed
- video generation pending/completed
- multimodal fusion completed

These can reuse the normalized event vocabulary rather than inventing separate ad hoc event systems.

## Multimodal State Integration

The state model should store multimodal activity through:

- `ExecutionState`
- `ValidationState`
- `ArtifactState`
- `RouteState`

Additional modality-specific metadata may live in payloads or artifact metadata, but should not create separate orchestration truth stores.

## File and Document Inputs

Files/documents should be treated as first-class multimodal context, not as awkward non-media exceptions.

Good examples:

- PDF summary request
- codebase artifact uploaded for analysis
- document + image + text combined request

The preprocessing path may involve:

- parsing
- summarization
- OCR
- chunk extraction

Those should still feed into the same fused context model.

## Quality and Validation

Multimodal outputs should be explicitly validated when reasonable.

Examples:

- ensure transcription is non-empty
- ensure image generation returned artifact data
- ensure video generation artifact is downloadable/decodable
- ensure fused context exists before final reasoning

This is important because multimodal failures are often silent if validation is weak.

## Local vs Cloud Multimodal Policy

The multimodal plan must support local/cloud policy without changing orchestration shape.

That means:

- local-only multimodal processing should still flow through the same routing system
- cloud multimodal processing should still flow through the same routing system
- hybrid pipelines should remain visible and policy-checked

The architecture should not hardcode multimodal work as automatically cloud-only or automatically local-only.

## Degraded Capability Handling

If a requested modality is unsupported or weakly supported:

- the router must report that limitation explicitly
- execution should return `partial` or `ask_user` or `revise` as appropriate
- the system must not pretend the modality was fully processed

Examples:

- no vision-capable route available
- no video-understanding route available
- requested output modality blocked by policy

This honesty is required for the architecture to remain trustworthy.

## Migration Plan

### Phase 1

Normalize all modality inputs into shared turn schema objects.

Goal:

- one intake model for text, image, audio, video, and files

### Phase 2

Route preprocessing and understanding capabilities through the capability router.

Goal:

- stop using disconnected modality-specific decision paths

### Phase 3

Run multimodal flows on the unified task graph engine.

Goal:

- one execution model for text and multimodal work

### Phase 4

Attach multimodal artifacts, events, and state to the shared models.

Goal:

- one inspectable runtime story

### Phase 5

Improve weaker modalities like video understanding/generation under the same architecture.

Goal:

- grow capability maturity without redesigning orchestration

## Minimum Compliance Requirements

The multimodal plan is compliant only if:

- all modalities normalize into the shared turn schema
- multimodal routing uses the shared capability router
- multimodal execution uses the shared task graph
- multimodal outputs use shared event/state/artifact models
- degraded modality support is surfaced honestly

If implementation still relies mainly on:

- disconnected modality-specific orchestration paths
- hidden preprocessing side effects
- multimodal outputs that bypass state and artifact tracking
- fake unified marketing with fragmented actual execution

then it is not compliant with this plan.

## Recommended Next Documents

The best next document after this one is:

1. `llm3-migration-roadmap.md`

## Final Summary

This multimodal routing plan makes the new architecture capable of acting like
one orchestration brain across text, image, audio, video, and files, while still
respecting the real differences in provider maturity and execution paths that
exist in TeAI Builder today.
