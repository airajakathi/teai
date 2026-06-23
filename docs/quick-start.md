# Quick start

## Requirements

- Python 3.11+
- A model provider API key
- (Optional) [Bun](https://bun.sh) if you want to rebuild the web UI from source

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configure

Run the interactive setup to choose a provider, paste an API key, and pick a model:

```bash
teai_builder onboard
```

This writes `~/.teai_builder/config.json` and creates your workspace at
`~/.teai_builder/workspace`.

## Run

### Terminal

```bash
teai_builder agent -m "Build me a landing page for a coffee shop"
```

### Gateway + Web UI

```bash
teai_builder gateway
```

Open the printed URL in your browser. Use the chat to describe what you want built; the
**Canvas** panel on the right shows live previews, generated media, code, and files as
the agent works.

> If a file/preview fails to load, restart `teai_builder gateway` so the latest routes
> are active.

## Rebuilding the web UI (optional)

```bash
cd webui
bun install
bun run build      # outputs to teai_builder/web/dist
```
