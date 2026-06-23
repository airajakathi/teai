# Publishing

TeAi Builder ships to real targets. Web deploys are gated behind verification.

## Web

Supported targets: **Vercel, Netlify, Railway, Render, Fly.io, or a VPS**.

### Verified deploy gate (hard requirement)

Before a web project's phase can advance to "shipped", TeAi Builder must:

1. Run **`run_verification`** and get a passing report.
2. Hit the live URL with a **health check**.
3. Capture a live **`screenshot`** of the deployed site.
4. Advance the phase via **`project_gate`** only after the above succeed.

## Mobile

Real Expo / React Native apps are published with **Expo EAS**:

```bash
eas login
eas build:configure
eas build --platform android   # or ios
eas submit --platform android  # or ios
```

Submitting to the **Play Store** / **App Store** requires your developer credentials.
TeAi Builder will stop and ask for these rather than guessing.

## Desktop

The recommended route is the **CI desktop packaging workflow**:
`.github/workflows/desktop-package.yml` builds the desktop app on push tags and
produces OS artifacts. Use that workflow when you need `.exe`, `.dmg`, or
`.AppImage` outputs from the repository.

Local desktop packaging remains available via **Tauri** (preferred) or **Electron**,
but those paths need OS-specific toolchains and dependencies. For faster,
repeatable builds with preinstalled system dependencies, use the GitHub Actions
workflow instead.

If you use local Tauri or Electron packaging, continue to verify:
- build exits 0,
- installer artifacts exist,
- the packaged app launches.
