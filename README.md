<div align="center">

<img src="images/teai_builder_logo.png" alt="TeAi Builder" width="120" />

# TeAi Builder

**An autonomous AI software company that researches, builds, verifies, and ships production-ready apps.**

🍵 _Give it an idea. It plans, builds, tests, and ships — like a real software team._

</div>

---

> **Proprietary software — not for public use.** See [`LICENSE`](LICENSE). All rights reserved.

## What is TeAi Builder?

TeAi Builder is an autonomous AI agent designed to build, verify, and deploy production-ready applications across web, mobile, and desktop platforms. It combines deep reasoning with a rich toolset to handle the entire software development lifecycle.

## Key Features

### Builds real applications
- **Web apps** — modern, production-quality front ends and back ends.
- **Mobile apps** — real **Expo / React Native** apps (not HTML mockups) with live Expo Go QR previews and an in-canvas mobile preview.
- **Desktop apps** — packaged with Tauri (preferred) or Electron.

### Multi-model, multi-modal
- **Model presets** — named model + parameter sets (`primary`, `reasoning`, `coding`, `vision`, …) selected automatically per task.
- **Vision auto-routing** — switches to a vision model when a message contains images.
- **Image/Video/Speech generation** — Integrated support for multi-modal generation.

### Controls the computer like a human
- Full shell / filesystem access, long-running task management, and a first-class **`screenshot`** tool used for "look → judge → fix" UI loops and deploy verification.

### Web UI with an auto-canvas
The bundled web UI includes an adaptive **Canvas** panel that auto-detects and renders whatever the agent produces — live web previews, mobile Expo QR + preview, images, video, audio, code, terminal output, and workspace files.

## Installation

To install TeAi Builder in editable mode, run the following commands in the project root:

```bash
# 1. Install dependencies and the package
pip install -e .

# 2. Build the WebUI (if not already built)
cd webui
npm install
npm run build
cd ..
```

## Quick Start

You can start the TeAi Builder gateway and access the WebUI directly. The gateway is configured to start without requiring pre-configured channel or AI API keys; these can be configured later within the WebUI settings.

```bash
# Start the gateway
teai_builder gateway --port 18790 --host 0.0.0.0
```

Once the gateway is running, open your browser and navigate to:
`http://localhost:18790`

## Configuration

Configuration lives in `~/.teai_builder/config.json`. You can manage your AI providers, API keys, and model presets directly from the WebUI settings page.

