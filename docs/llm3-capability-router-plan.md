# LLM3 Capability Router Plan

## Status

Draft capability router plan.

This document defines how the new orchestration architecture should choose the
right model/provider for:

- `LLM1`
- `LLM2`
- `LLM3`
- worker tasks
- validation tasks
- multimodal tasks

This document extends:

- [`llm3-orchestration-plan.md`](./llm3-orchestration-plan.md)
- [`llm3-orchestration-spec.md`](./llm3-orchestration-spec.md)
- [`llm3-turn-schema.md`](./llm3-turn-schema.md)
- [`llm3-execution-contract.md`](./llm3-execution-contract.md)
- [`llm3-worker-runtime-plan.md`](./llm3-worker-runtime-plan.md)

## Purpose

The purpose of this document is to replace fragmented provider/model selection
with one unified routing system that works across the full orchestration stack.

Today, TeAI Builder already has:

- a provider registry
- a provider factory
- model presets
- failover support
- separate generation/transcription/media provider paths

Those are valuable building blocks, but they are not yet a single orchestration
capability router.

The target architecture needs one routing layer that answers:

- which model should power `LLM1`
- which model should power `LLM2`
- which model should power `LLM3`
- which model should power a given worker role
- which provider should handle a multimodal or generation task
- when to use local vs cloud
- when to use fallback

## Current Reality

The current text-provider foundation is already real:

- [registry.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/providers/registry.py)
- [factory.py](file:///home/sharan/Teai%20builder/teai_builder/teai_builder/providers/factory.py)

The current system already supports:

- provider metadata
- backend mapping
- preset resolution
- fallback chains
- gateway detection
- local provider detection

That means the new capability router should build on top of the current provider
registry and factory rather than discard them.

## Main Problem

The current provider layer answers:

- "how do I build a provider instance for this model/preset?"

But the new orchestration runtime needs to answer:

- "what role is being executed?"
- "what capability is required?"
- "what policy applies?"
- "what latency/cost/reliability trade-off is best?"
- "is local-only required?"
- "is tool calling required?"
- "is multimodal input required?"

That is the difference between:

- provider construction
- capability routing

## Main Goal

Create one `Capability Router` that becomes the only routing authority for
model/provider selection across the new orchestration runtime.

The router must:

- understand runtime role
- understand required capabilities
- understand policy constraints
- understand local/cloud constraints
- understand fallback and failover behavior
- return a structured routing decision

## Router Principles

The capability router must follow these principles:

- one routing system for the entire orchestration stack
- route by capability and role, not by hardcoded provider branches
- keep current provider factory as a lower-level construction layer
- support local and cloud providers under the same decision model
- support explicit fallback rather than hidden fallback
- make routing decisions inspectable and explainable

## Router Scope

The router must be used for:

- `LLM1` selection
- `LLM2` selection
- `LLM3` selection
- worker model selection
- validation model selection
- multimodal understanding tasks
- image generation tasks
- audio generation tasks
- video generation tasks
- transcription tasks

The router should eventually own all model/provider selection in the runtime.

## Router Inputs

The capability router should accept a structured `RoutingRequest`.

```ts
type RoutingRequest = {
  request_id: string;
  turn_id?: string | null;
  role:
    | "llm1"
    | "llm2"
    | "llm3"
    | "worker"
    | "validation"
    | "vision"
    | "transcription"
    | "tts"
    | "image_generation"
    | "video_generation";
  worker_role?: string | null;
  required_capabilities: string[];
  preferred_capabilities?: string[];
  input_modalities: ("text" | "image" | "audio" | "video" | "file")[];
  output_modalities: ("text" | "image" | "audio" | "video" | "file")[];
  execution_mode?: "direct" | "assisted" | "delegated" | "workflow" | null;
  policy: {
    local_only: boolean;
    cloud_allowed: boolean;
    mutating_tools_allowed?: boolean;
    max_cost_tier?: "low" | "medium" | "high";
    max_latency_tier?: "low" | "medium" | "high";
  };
  workspace_scope?: {
    project_path?: string | null;
  };
  metadata?: Record<string, unknown>;
};
```

## Router Outputs

The router must return a structured `RoutingDecision`.

```ts
type RoutingDecision = {
  route_id: string;
  request_id: string;
  selected_provider: string;
  selected_model: string;
  backend: string;
  role:
    | "llm1"
    | "llm2"
    | "llm3"
    | "worker"
    | "validation"
    | "vision"
    | "transcription"
    | "tts"
    | "image_generation"
    | "video_generation";
  supports: {
    input_modalities: string[];
    output_modalities: string[];
    tool_calling: boolean;
    structured_output: boolean;
    streaming: boolean;
    local: boolean;
  };
  fallback_chain?: Array<{
    provider: string;
    model: string;
  }>;
  rationale: string;
  metadata?: Record<string, unknown>;
};
```

## Router Rules

- every non-direct runtime model selection should produce a routing decision
- the decision must be inspectable
- fallback chain should be explicit where applicable
- routing rationale must be short but meaningful
- routing should fail clearly if no candidate meets policy and capability constraints

## Role-Based Routing

The router must route differently depending on runtime role.

### LLM1

`LLM1` should prefer:

- strong intent understanding
- high-quality user-facing response synthesis
- good instruction following
- strong reasoning under bounded latency

`LLM1` does not inherently require:

- deep tool execution
- workflow ownership
- worker orchestration

### LLM2

`LLM2` should prefer:

- critique quality
- consistency checking
- contradiction detection
- reflective reasoning

`LLM2` may use a smaller or cheaper model than `LLM1` if review quality remains strong.

### LLM3

`LLM3` should prefer:

- strong tool-use reliability
- strong execution-following behavior
- structured output quality
- long-context execution quality
- stability under multi-step tasks

### Worker

Workers should route based on worker role and task type.

Examples:

- research worker -> cheaper strong-reading model
- code worker -> coding-strong model
- validation worker -> precise review/analysis model
- doc worker -> lower-cost generation model if acceptable

### Validation

Validation routing should prefer:

- precision
- consistency
- lower hallucination risk

### Vision / Multimodal

Vision or multimodal routing should prefer:

- image understanding support
- video understanding support when needed
- file/image interpretation strength

### Generation Roles

Image/audio/video generation routes should be capability-specific and separate
from general text-execution routes.

## Capability Taxonomy

The router should use one shared capability taxonomy.

Initial capability groups should include:

- `intent_understanding`
- `response_synthesis`
- `critique`
- `tool_calling`
- `structured_output`
- `long_context`
- `code_generation`
- `code_editing`
- `code_review`
- `validation_reasoning`
- `vision_understanding`
- `image_generation`
- `audio_transcription`
- `audio_generation`
- `video_understanding`
- `video_generation`
- `low_latency`
- `low_cost`
- `offline_local`

This taxonomy should become the common language between orchestration and provider routing.

## Capability Profile Model

Every routable model/provider target should eventually expose a capability profile.

Suggested shape:

```ts
type CapabilityProfile = {
  provider: string;
  model: string;
  backend: string;
  local: boolean;
  supports: {
    input_modalities: ("text" | "image" | "audio" | "video" | "file")[];
    output_modalities: ("text" | "image" | "audio" | "video" | "file")[];
    tool_calling: boolean;
    structured_output: boolean;
    streaming: boolean;
    prompt_caching?: boolean;
  };
  strengths: string[];
  limits?: string[];
  cost_tier?: "low" | "medium" | "high";
  latency_tier?: "low" | "medium" | "high";
  metadata?: Record<string, unknown>;
};
```

## Relationship To Current Provider Registry

The current provider registry should remain the metadata source for provider-level information.

The new router should not duplicate all of that logic blindly.

The likely relationship is:

- `registry.py` remains provider metadata source
- `factory.py` remains provider construction path
- new `Capability Registry` becomes orchestration-facing routing metadata
- new `Capability Router` selects a candidate and then delegates actual construction to the provider factory

## Relationship To Current Provider Factory

The current provider factory should become the lower-level instantiation layer.

That means:

- the capability router decides *what should be used*
- the provider factory decides *how to instantiate it*

This is important because it avoids breaking the current provider implementation system.

## Local vs Cloud Policy

The router must make local/cloud policy explicit.

Supported policy patterns:

- `local_only`
- `cloud_preferred`
- `cloud_allowed`
- `hybrid_allowed`

Examples:

- private session with no cloud allowed
- normal web session with cloud allowed
- offline execution path using local models first
- fallback to cloud only when local capability is insufficient and policy allows it

## Fallback Model

The router should support explicit fallback chains.

Fallback selection should consider:

- same role
- same required capability set
- policy compatibility
- provider health
- cost and latency constraints

Fallback must not be invisible.

The routing decision should expose:

- primary route
- fallback candidates
- why the selected route was chosen

## Health and Availability Awareness

The router should eventually consume provider/model health information.

Useful health signals:

- recent request failure rate
- timeout rate
- authentication failure
- provider disabled in config
- local model availability
- provider latency degradation

This should allow routing away from unhealthy options before execution fails.

## Multimodal Routing

The router must support multimodal routing without splitting orchestration into separate brains.

That means:

- text-oriented executive routing
- multimodal understanding routing
- generation routing

must all remain part of one routing framework.

Examples:

- turn with text + image -> route vision understanding capability
- turn with audio upload -> route transcription capability
- turn with image generation intent -> route image generation capability
- workflow step needing video understanding -> route video-understanding capable model/provider

## Current Media Reality

TeAI Builder already has separate paths for:

- text/chat providers
- transcription providers
- image generation providers
- audio generation providers
- video generation providers

The new router should unify selection across these categories without pretending
that they are all the same backend.

So the router must support:

- one decision framework
- multiple provider families
- multiple backend types

## Cost and Latency Routing

The router should support explicit trade-off controls.

Minimum route preferences:

- `fastest acceptable`
- `lowest cost acceptable`
- `best quality acceptable`
- `local preferred`
- `balanced`

These should be driven by:

- role
- execution mode
- policy
- user or product configuration

## Role Defaults

The first implementation should define explicit defaults for each major role.

Example direction:

- `LLM1` -> balanced high-quality chat/reasoning model
- `LLM2` -> critique-capable lower-cost review model
- `LLM3` -> strong tool-use and structured-output model
- `worker` -> role-specific models
- `validation` -> precise low-hallucination model

These defaults should be configurable, but the runtime should not rely on implicit assumptions.

## Routing Decision Flow

The target routing flow should be:

1. receive `RoutingRequest`
2. validate role and policy
3. derive required capability set
4. enumerate candidate capability profiles
5. filter by policy
6. filter by modality support
7. filter by role requirements
8. rank by quality/cost/latency/locality
9. produce primary route and fallback chain
10. return `RoutingDecision`

## Ranking Factors

Candidate ranking should consider:

- capability match quality
- role suitability
- modality compatibility
- local/cloud compatibility
- configured preference
- provider health
- latency tier
- cost tier
- structured output support
- tool-call support if required

## Capability Router And Workers

The worker runtime must not choose models ad hoc.

Instead:

- each worker task requests a route through the capability router
- the routing request includes `worker_role`
- the scheduler/executor uses the returned route

This is critical because otherwise the new worker runtime would inherit the same fragmented model-selection problem as the current spawn path.

## Capability Router And LLM1 / LLM2 / LLM3

The executive architecture requires explicit separation:

- `LLM1` may use one route
- `LLM2` may use another route
- `LLM3` may use another route

These should not be assumed to share one model by default.

That separation is one of the key architectural changes in the new design.

## Capability Router And FallbackProvider

The current fallback provider logic remains useful.

The likely migration path is:

- capability router selects the primary route and explicit fallback chain
- provider factory builds the primary provider
- existing fallback provider support may be reused underneath
- routing metadata stays visible at orchestration level

So failover can still happen, but it must be policy-aware and inspectable.

## Migration Plan

The migration should happen in phases.

### Phase 1

Introduce capability profiles on top of current provider metadata.

Goal:

- keep provider registry intact
- add orchestration-facing capability metadata

### Phase 2

Create a capability router service that returns structured routing decisions.

Goal:

- start selecting by role + capability instead of preset alone

### Phase 3

Route `LLM1`, `LLM2`, and `LLM3` through the new router.

Goal:

- make the executive/runtime split real

### Phase 4

Route worker tasks and validation tasks through the same router.

Goal:

- unify spawned execution model selection

### Phase 5

Route multimodal and generation tasks through the same framework.

Goal:

- unify text/media routing under one decision layer

### Phase 6

Deprecate fragmented provider-selection paths.

Goal:

- one routing authority remains

## Minimum Compliance Requirements

The capability router plan is compliant only if:

- role-based routing exists
- capability-based filtering exists
- policy-aware local/cloud routing exists
- fallback is explicit
- routing decisions are inspectable
- workers use the same router
- multimodal routes use the same framework

If the implementation still relies on:

- hardcoded provider branches per subsystem
- hidden worker model selection
- silent local/cloud switching
- disconnected routing logic for text vs media

then it does not comply with this plan.

## Recommended Next Documents

The best next documents after this one are:

1. `llm3-event-model.md`
2. `llm3-state-model.md`
3. `llm3-task-graph-plan.md`
4. `llm3-multimodal-routing-plan.md`

## Final Summary

This capability router plan upgrades TeAI Builder from:

- "build a provider from a preset"

to:

- "select the right model/provider for the right runtime role and capability under one orchestration policy"

That is the routing foundation required to make the full `LLM1 / LLM2 / LLM3`
architecture coherent and scalable.
