# Architecture

## Runtime overview

```
User ──▶ Gateway / CLI ──▶ AgentLoop (CEO)
                              │
                              ├─ AgentRunner      (LLM + tool iteration)
                              ├─ SubagentManager  (background AI employees)
                              ├─ ToolRegistry     (exec, fs, web, media, screenshot, …)
                              ├─ ModelPresets     (primary / vision / image / video / audio)
                              └─ MessageBus       (streaming events to the Web UI)
```

- **AgentLoop** is the orchestrator ("CEO"). It manages state, selects model presets,
  and registers tools via a `ToolContext`.
- **AgentRunner** performs the LLM ↔ tool iteration for a single agent.
- **SubagentManager** runs specialized roles as background workers.
- **MessageBus** streams progress, media, and canvas items to the Web UI.

## The company model

The CEO receives an idea, then drives a lifecycle:

1. **Research** — gather knowledge, constraints, and references.
2. **Plan** — produce options with rationale and a detailed to-do list.
3. **Build** — delegate implementation to subagents (architect, frontend, backend …).
4. **Verify** — run independent checks (`run_verification`) and UI review (`screenshot`).
5. **Ship** — deploy behind a verified deploy gate.

## Gates and verification

- `projects/<name>/.teai_builder/state.json` is a machine-readable record of phases,
  artifacts, and verification results.
- **`project_gate`** advances phases only when required artifacts exist and gates pass —
  it can block delivery and deployment.
- **`run_verification`** re-runs static analysis, type checks, builds, and bundle checks
  and returns a structured pass/fail report the agent must consume.

## Model routing

- A single **primary** model drives the conversation.
- **Presets** define alternate models for `reasoning`, `coding`, `vision`, etc.
- **Vision auto-routing**: image attachments temporarily switch to the `vision` preset.
- Dedicated tools route to their own model slots: `generate_image`, `generate_video`,
  `generate_speech`.

## Tools (selection)

`exec` / `write_stdin`, filesystem (`read_file`, `write_file`, `edit_file`,
`apply_patch`, `list_dir`, `find_files`, `grep`), web (`web_search`, `web_fetch`),
orchestration (`spawn`, `long_task`, `complete_goal`, `project_gate`,
`run_verification`), media (`canvas`, `generate_image`, `generate_video`,
`generate_speech`, `screenshot`), plus `message`, `cron`, and `run_cli_app`.
