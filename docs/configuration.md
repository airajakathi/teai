# Configuration

TeAi Builder reads its configuration from `~/.teai_builder/config.json` or an
instance-local `config.json` when you run from an instance directory.

## Reference

The full schema-backed reference is generated from
`teai_builder/config/schema.py`:

- [Configuration reference](configuration-reference.md)

Regenerate it with:

```bash
python scripts/generate_config_reference.py
```

## Identity

```json
{
  "agents": {
    "defaults": {
      "botName": "TeAi Builder",
      "botIcon": "🍵"
    }
  }
}
```

## Primary model

```json
{
  "agents": {
    "defaults": {
      "model": "your-model-name",
      "provider": "openai"
    }
  },
  "providers": {
    "openai": {
      "apiKey": "...",
      "apiBase": "https://your-provider/v1"
    }
  }
}
```

## Model presets

Named model + generation-parameter sets. The primary model delegates to these
automatically per task.

```json
{
  "modelPresets": {
    "reasoning": { "model": "...", "provider": "..." },
    "coding": { "model": "...", "provider": "..." },
    "vision": { "model": "...", "provider": "..." }
  },
  "agents": {
    "defaults": {
      "modelPreset": "coding"
    }
  }
}
```

When an inbound message contains images and a distinct `vision` preset is
configured, TeAi Builder routes that turn through the vision model and then
restores the previous preset.

## Generative model slots

Each generative capability has its own configurable slot under `tools`:

```json
{
  "tools": {
    "imageGeneration": { "provider": "...", "model": "..." },
    "videoGeneration": { "provider": "custom", "model": "...", "enabled": false },
    "audioGeneration": {
      "provider": "stepfun",
      "model": "stepaudio-2.5-tts",
      "enabled": true,
      "voice": "...",
      "format": "mp3"
    }
  }
}
```

Provider base URLs are respected exactly. If your key is scoped to a proxy
endpoint, set `apiBase` to that endpoint so requests go through the authorized
route.

## Workspace

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.teai_builder/workspace"
    }
  }
}
```

The workspace holds the agent's `SOUL.md`, `AGENTS.md`, skills, sessions, and
project output under `projects/<name>/`.

## Tool governance

Tool availability and approval are now separate.

```json
{
  "tools": {
    "governance": {
      "activeProfile": "safe",
      "profiles": {
        "safe": {
          "enabledTools": ["read_*", "grep", "web_*", "mcp_*"],
          "disabledTools": ["exec", "apply_patch"]
        }
      },
      "permissions": {
        "exec": "confirm",
        "apply_patch": "confirm",
        "mcp_private_*": "deny"
      }
    }
  }
}
```

- Profiles control which tools are exposed to the runtime at all.
- Permissions control whether an available tool is auto-allowed, requires confirmation, or is denied.
- Supported permission values are `allow`, `confirm`, and `deny`.

## Exec sandbox

Shell execution can be wrapped in a host sandbox backend:

```json
{
  "tools": {
    "restrictToWorkspace": true,
    "exec": {
      "sandbox": "bwrap",
      "strictSandbox": true
    }
  }
}
```

- `sandbox` selects the backend used for `exec` tool process isolation.
- `strictSandbox: true` is fail-closed: if the backend is unavailable, `exec` is blocked instead of silently running unsandboxed.
- `strictSandbox: false` allows fallback to application-level guards only, which is less safe and mainly useful for constrained environments.

## Extensions

The runtime plugin directory now supports manifest-based extensions. Each
extension lives in its own folder with a `teai-extension.toml` file:

```toml
[extension]
id = "sample-extension"
version = "0.1.0"
entrypoint = "plugin.py"
capabilities = ["tools"]
```

Legacy single-file plugins still load, but manifest-based extensions are the
preferred format going forward.

## Reliability

TeAi Builder now supports local crash reporting and opt-in telemetry audit logs.

```json
{
  "reliability": {
    "telemetry": {
      "enabled": true,
      "localAuditLog": true,
      "captureUsage": true,
      "captureErrors": true,
      "maxEvents": 1000
    },
    "crashReports": {
      "enabled": true,
      "keepReports": 20,
      "startupReportLimit": 5
    }
  }
}
```

- Telemetry is local-only in this phase and writes JSONL audit events under the instance runtime directory.
- Crash reports are written locally and surfaced once on the next startup before being archived.
- Runtime logs are also written per component under the instance `logs/` directory.
