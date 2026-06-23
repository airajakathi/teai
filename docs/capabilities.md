# Capabilities

TeAi Builder is built to deliver **production-ready** software, not throwaway demos.

## 1. Acts like a software company

A single **CEO agent** receives the idea and orchestrates specialized **subagents**:

| Role | Responsibility |
| --- | --- |
| Architect | System design, tech-stack options with rationale, project scaffolding |
| Frontend Engineer | UI implementation (web and real Expo/React Native mobile) |
| Backend Engineer | APIs, data, integrations |
| QA Engineer | Tests, type/lint/build checks, UI review |
| DevOps Engineer | Deployment and verified release |

### Research & planning before code
Knowledge gathering and a detailed to-do list precede any code change. Decisions
(tech stack, UI direction, etc.) are made by generating **options with rationale** —
"proof of work" — rather than on a whim.

## 2. Quality is gated, not assumed

- **Phase state** is tracked in `projects/<name>/.teai_builder/state.json`.
- **`project_gate`** validates required artifacts and blocks delivery/deploy until the
  current phase's gates pass.
- **`run_verification`** independently re-runs static analysis, builds, and bundle
  checks, returning structured pass/fail results.
- **Verified deploy gate**: web deploys require a live health check **and** a captured
  screenshot before the phase can advance.

## 3. Multi-model, multi-modal

- **Model presets**: named model + generation-parameter sets (`primary`, `reasoning`,
  `coding`, `vision`, …). The primary model delegates automatically.
- **Vision auto-routing**: when an inbound message carries images, TeAi Builder
  temporarily routes to a configured vision model, then restores the previous preset.
- **Generative slots** (each independently configurable):
  - `generate_image`
  - `generate_video`
  - `generate_speech` (text-to-speech, e.g. StepFun `stepaudio-2.5-tts`)

## 4. Controls the computer

Full shell and filesystem access, long-running task supervision, and a first-class
**`screenshot`** tool (Playwright with a headless-Chromium fallback) that powers
"look → judge → fix" UI loops and deploy verification.

## 5. Targets

- **Web** apps (front end + back end).
- **Mobile** apps as real Expo / React Native projects with Expo Go QR + live preview.
- **Desktop** apps packaged via Tauri (preferred) or Electron.

## 6. Web UI auto-canvas

The bundled web UI's **Canvas** panel auto-detects content and renders live web
previews, mobile previews + Expo QR, images, video, audio, code, terminal output, and
workspace files — a single adaptive surface instead of separate tabs.
