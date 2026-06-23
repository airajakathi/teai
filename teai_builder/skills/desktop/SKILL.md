---
name: desktop
description: Package web apps into native desktop installers (.exe/.msi, .dmg, .AppImage/.deb) with Tauri (preferred) or Electron, including build verification and artifact surfacing.
metadata: {"teai_builder": {"emoji": "🖥️"}}
---

# Desktop App Packaging — Tauri (preferred) / Electron

Use this skill to turn a web frontend (React/Vue/Svelte/plain HTML) into an
installable desktop app. **Prefer Tauri**: it produces small binaries (a few MB
vs 100MB+ for Electron), uses the OS webview, and has a strong security model.
Use Electron only when the app needs full Node.js/Chromium APIs or an existing
Electron ecosystem.

## Cross-compilation reality (tell the user)

You can only natively build installers for the OS you are running on:
- Linux host → `.AppImage` / `.deb` (and `.rpm`).
- macOS host → `.dmg` / `.app` (and code-signing/notarization needs an Apple ID).
- Windows host → `.exe` / `.msi`.

For other targets, use CI (GitHub Actions matrix) — `tauri-apps/tauri-action`
builds for all three OSes. If the user wants a platform you can't build locally,
**say so** and offer the CI route. Code signing requires the user's certificates.

## Choosing the right tool

```
Need full Node/Chromium APIs, or porting an existing Electron app?  → Electron
Otherwise (most cases): smallest, fastest, most secure               → Tauri
```

## Tauri path (preferred)

### Step 0 — Prerequisites
- Rust toolchain: `curl https://sh.rustup.rs -sSf | sh` then `source ~/.cargo/env`
- Linux system deps (Debian/Ubuntu): `webkit2gtk`, `libgtk-3-dev`, `libayatana-appindicator3-dev`, `librsvg2-dev`, `build-essential`
- A working web build (`npm run build` produces `dist/`)

### Step 1 — Add Tauri to the existing web app
```bash
cd projects/<name>
npm install --save-dev @tauri-apps/cli
npx tauri init   # set: app name, window title,
                 #   "frontendDist" = ../dist (your build output),
                 #   "devUrl" = http://localhost:5173 (your dev server),
                 #   beforeBuildCommand = "npm run build"
```

### Step 2 — Dev + build
```bash
npx tauri dev      # live desktop window for testing
npx tauri build    # produces installers in src-tauri/target/release/bundle/
```

### Step 3 — Verify (gate)
- `run_verification(project="<name>")` passed (web build is sound).
- `npx tauri build` exits 0.
- Confirm the artifact exists, e.g.:
  ```bash
  ls -lh src-tauri/target/release/bundle/**/*  # .AppImage/.deb/.dmg/.msi/.exe
  ```
- Launch the built binary once to confirm it opens without crashing
  (`./src-tauri/target/release/<app>` on Linux) — or screenshot it.
- A build with no artifact = failure. Read the error, fix, rebuild.

## Electron path (when Node/Chromium APIs are required)

Use `electron-vite` + `electron-builder`:
```bash
cd projects/<name>
npm create @quick-start/electron@latest .   # or add electron + electron-builder manually
npm install
npm run build        # bundles main/preload/renderer
npx electron-builder # produces installers in dist/ (per electron-builder config)
```

`electron-builder` config (in `package.json` → `build`) sets `appId`,
`productName`, and per-OS targets (`nsis` for Windows, `dmg` for mac,
`AppImage`/`deb` for Linux). Verify the same way: build exits 0, installer
artifact exists, app launches.

## Surface the result
- Record the artifact path(s) in `PROJECT.md`.
- Show/deliver the installer to the user (its path), and screenshot the running
  app to canvas if a display is available.
- Advance the project only after a real artifact built successfully:
  `project_gate(action="advance", phase="deploy")`.

## Stop points to surface to the user (don't guess)
- "Code signing for macOS/Windows needs your developer certificate — provide it
  or I'll ship an unsigned build (users will see a security warning)."
- "I can't build a <Windows/macOS> installer from this <Linux> host — set up the
  GitHub Actions matrix, or run the build on that OS."

## Verification checklist (before reporting "packaged")
- [ ] `run_verification` passed and the web app builds
- [ ] `tauri build` / `electron-builder` exited 0
- [ ] Installer artifact(s) exist on disk (path verified with `ls`)
- [ ] Built app launches without crashing (or screenshot captured)
- [ ] Artifact paths recorded in `PROJECT.md`
- [ ] Any signing/cross-compile limits were clearly communicated to the user
