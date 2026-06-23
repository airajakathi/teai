# Debug Session: expo-cache-block

- Status: OPEN
- Started: 2026-06-14
- Scope:
  - Expo/mobile build fails with a read-only home directory error.
  - WebUI shows aborted requests for `/`, `/api/settings/cli-apps`, and `/api/settings/mcp-presets`.
  - Verify which roadmap features are truly implemented versus partially stubbed.

- Initial symptoms:
  - "I'm hitting a hard wall with Expo in this environment — the home directory is mounted read-only, and Expo's native module cache can't write."
  - Browser console reports `net::ERR_ABORTED` for gateway/WebUI requests.
  - Browser console reports multiple `ERR_BLOCKED_BY_ORB` requests to external provider sites/favicon URLs.

- Hypotheses:
  1. Expo tooling is still resolving cache/state under `$HOME` instead of the TeAI Builder workspace, so mobile scaffolding/build commands fail on read-only home mounts.
  2. The WebUI preview is loading without the expected auth/bootstrap token, causing settings API requests to abort even though the gateway root is healthy.
  3. The `cli-apps` and `mcp-presets` settings endpoints are doing outbound metadata/favicon fetches that the preview browser flags as ORB-blocked, which may be noisy but not fatal.
  4. TeAI Builder’s mobile/scaffold workflow exists, but the runtime command path does not yet inject the environment overrides needed for Expo in restricted environments.
  5. Some roadmap items are present only as primitives or stubs, so “implemented” needs to be verified feature-by-feature rather than assumed from file names.

- Evidence to collect:
  - Reproduce Expo/mobile failure from the actual TeAI Builder scaffold/build path.
  - Inspect runtime env/cache path handling for Expo/mobile commands.
  - Verify the settings API responses directly over HTTP, with and without preview/browser context.
  - Confirm current implementation status of Monaco, parallel execution, dynamic workflow execution, and related roadmap items.

- Evidence collected:
  - Reproduced the original failure from `ScaffoldProjectTool(platform="mobile")`:
    - `create-expo-app` tried writing `/home/sharan/.expo/state.json...`
    - error: `EROFS: read-only file system`
  - Direct unauthenticated HTTP checks to `/api/settings`, `/api/settings/cli-apps`, and `/api/settings/mcp-presets` returned `401 Unauthorized`, confirming those routes are token-protected by design.
  - Fresh browser tab after rebuild/restart showed:
    - no console errors
    - bootstrap + settings requests succeeded in the authenticated app flow
  - Fresh mobile scaffold now succeeds in a temp workspace.
  - `ExecTool` now resolves `HOME` to `<workspace>/.teai_builder-home` when the real home is not writable.

- Fixes applied:
  1. Mobile scaffolding now injects writable local runtime directories for Expo/NPM state.
  2. Shell execution now falls back to workspace-local runtime dirs, with a temp fallback if the workspace root is also read-only.
  3. WebUI logo fallback ordering now prefers proxy/favicon services before direct third-party origins, reducing ORB noise from provider/app brand icons.

- Current status:
  - OPEN
  - Awaiting user confirmation that the mobile-game build path and the WebUI behavior match expectations.
