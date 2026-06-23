---
name: models
description: Multi-model routing — which model preset to use for each spawn role, how to add new providers, image generation configuration.
metadata: {"teai_builder": {"emoji": "🤖"}}
---

# Multi-Model Routing

## Model Presets Available

| Preset | Intended Use | Temperature |
|--------|-------------|-------------|
| `primary` | General tasks, conversation, simple code | 0.1 |
| `reasoning` | Architecture decisions, complex analysis, system design | 0.05 |
| `coding` | Code generation, debugging, testing, DevOps scripts | 0.02 |
| `vision` | Screenshot analysis, image understanding, UI review | 0.1 |

## Role-to-Preset Mapping

Always pass `model_preset` when spawning an employee:

```
spawn(role="architect",          model_preset="reasoning")
spawn(role="designer",           model_preset="primary")
spawn(role="frontend_engineer",  model_preset="coding")
spawn(role="backend_engineer",   model_preset="coding")
spawn(role="devops_engineer",    model_preset="coding")
spawn(role="qa_engineer",        model_preset="coding")
```

## Vision Auto-Routing (automatic)

You do **not** need to manually switch to the vision model when looking at
screenshots. When a turn includes image attachments, the agent loop
**automatically routes that turn to the `vision` preset** — but only when the
`vision` preset resolves to a genuinely different model than the active one.

- Today all StepFun presets point at the same model, so the route is a
  deliberate no-op (no behavior change, no extra cost).
- The moment you point `vision` at a real vision model (e.g. add an
  Anthropic/Gemini/OpenAI key and set `vision.model` to a vision-capable
  model), image turns will route to it with **no code change**.
- Subagents that must read images should still be spawned with
  `model_preset="vision"` so their reasoning runs on the vision model.

## Image Generation

Image generation uses a **separate tool**, not an LLM model preset:
- Tool: `generate_image(prompt="...", aspect_ratio="1:1")`
- Configured via `tools.imageGeneration` in config.json (provider, model, aspect_ratio)
- Does NOT use the `model_preset` parameter of `spawn`
- Used by: Designer role for logo concepts, UI mockup generation

## Audio / Speech (separate model slot)

Speech has **two distinct model slots**, both independent of the text model:

- **Text-to-speech (TTS)** — the `generate_speech` tool:
  - `generate_speech(text="...", voice="...", response_format="mp3")`
  - Configured via `tools.audioGeneration` (default provider `stepfun`, model
    `stepaudio-2.5-tts`). Returns a persistent audio artifact you deliver via the
    `message` tool's `media` parameter.
  - Auto-called when the user wants narration, voiceovers, or a spoken reply.
- **Speech-to-text (STT / transcription)** — handled automatically for incoming
  audio via `transcription` config (StepFun default `stepaudio-2.5-asr`). This is
  the inbound direction and needs no tool call.

To point TTS at another provider, set `tools.audioGeneration.provider` +
`model` and add the provider key under `providers.<name>` (OpenAI-compatible
`/audio/speech` endpoints work out of the box).

## Video Generation (separate model slot)

Video generation is a **distinct model slot**, independent of the text and
image models — a different model, different provider, auto-called when video is
needed:
- Tool: `generate_video(prompt="...", duration_seconds=5, aspect_ratio="16:9")`
- Optionally animate a still: `generate_video(prompt="...", reference_image="<path>")`
- Configured via `tools.videoGeneration` in config.json (`enabled`, `provider`, `model`)
- **Disabled by default** (no default video provider key ships with teai_builder).
  To enable: set `videoGeneration.enabled = true`, choose a `provider` (a
  custom OpenAI-compatible `/video/generations` endpoint works out of the box),
  set `videoGeneration.model`, and add the provider key under `providers.<name>`.
- Returns persistent artifacts (paths) that you deliver via the `message` tool
  or show with `canvas(type="video", content="<path>")`.

## Adding New Models or Providers

To use a different LLM provider (e.g., Anthropic Claude for reasoning, OpenAI GPT for coding):

1. Add the provider API key to `config.json` under `providers.<name>.apiKey`
2. Add a new preset to `config.json` under `model_presets`:
   ```json
   "reasoning": {
     "label": "Claude 4 Reasoning",
     "provider": "anthropic",
     "model": "claude-opus-4-5",
     "temperature": 0.05
   }
   ```
3. Restart the teai_builder gateway for the config change to take effect
4. The `spawn` tool will now automatically use the new provider for that preset

## How Model Routing Works

When you call `spawn(model_preset="coding")`:
1. The `SubagentManager` looks up the `coding` preset in the config
2. Resolves the provider and model from the preset definition
3. If the provider is different from the main agent's provider, creates a fresh runner
4. The subagent runs entirely on that model until it completes
5. Results are returned to the CEO regardless of which model was used

The user never needs to manually select models — the CEO handles routing automatically.
