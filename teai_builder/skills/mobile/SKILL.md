---
name: mobile
description: Build real Android/iOS apps with Expo. Start with a verified native foundation, then finish to the requested production scope.
metadata: {"teai_builder": {"emoji": "📱", "always": true}}
---

# Mobile App Development — Expo (React Native)

## The Golden Rule: Correct Native Foundation First

**Do NOT fake a mobile product with HTML. Start with a verified Expo foundation, then continue until the requested product is genuinely shippable.**

| Phase | Goal |
|-------|------|
| Foundation | Expo scaffold + verified native/web bundles |
| Product core | Main gameplay/app flows working end-to-end |
| Production pass | architecture cleanup, persistence, tests, packaging, runtime proof |

If the app cannot start correctly, stop and fix the foundation before feature work.

---

## Correct Expo Workflow (Follow Exactly)

### Step 1: Scaffold (2 minutes) — and VERIFY it succeeded
```bash
cd projects/
npx create-expo-app@latest <name> --template blank-typescript --yes
cd <name>
```
This gives you a working `App.tsx` that already runs. **Do not break it.**

**MANDATORY — verify you actually installed the latest SDK/tooling, not outdated cached versions:**
```bash
node -p "require('expo/package.json').version"
npx expo --version
node -p "require('react-native/package.json').version"
node -p "require('react/package.json').version"
```
If any of these are older than the current stable Expo SDK (as of your build date), **stop and reinstall**:
```bash
npx create-expo-app@latest . --template blank-typescript --overwrite
npx expo install react react-native react-dom react-native-web @expo/metro-runtime
```
Record the installed versions in `DECISION_LOG.md`. **Never ship with an outdated SDK.**

**MANDATORY verification — the #1 cause of `ConfigError: Cannot resolve entry file`:**
```bash
# create-expo-app sometimes fails silently (network/interactive prompt). Verify:
test -f App.tsx && node -e "process.exit(require('./package.json').main ? 0 : 1)" \
  && echo "scaffold OK: main=$(node -p "require('./package.json').main")" \
  || echo "SCAFFOLD INCOMPLETE — fix before continuing"
```

**If `create-expo-app` failed and you bootstrap manually (e.g. `npm init`), you MUST set the Expo entry point.**
A bare `npm init -y` sets `"main": "index.js"`, but Expo has no `index.js` → **`ConfigError: Cannot resolve entry file` and a broken/white preview.** Fix it:
```bash
# Point package.json at Expo's entry shim (it imports ./App via registerRootComponent)
npm pkg set main="expo/AppEntry.js"
# Install the React runtime that create-expo-app would have added (use expo install for matched versions):
npx expo install react react-dom react-native
```
Never leave `"main": "index.js"` unless you actually created an `index.js` that calls `registerRootComponent(App)`.

### Step 2: Install deps INCLUDING web preview support (2 minutes)
**Always install native deps with `npx expo install <pkg>` — NEVER `npm install <pkg>@<version>`.**
`expo install` picks the exact versions that match the installed Expo SDK. Hand-pinning versions (e.g. `react-native@0.73` on SDK 52, which expects `0.76`) causes peer-dependency conflicts, `--legacy-peer-deps` workarounds, and runtime crashes.

For a board game (Ludo, Chess, etc.) — use React Native's built-in drawing, no Skia needed for MVP:
```bash
npm install  # installs what create-expo-app added
# MANDATORY: web preview deps so the live preview iframe in canvas works
npx expo install react-dom react-native-web @expo/metro-runtime
```

**`react-dom` + `react-native-web` + `@expo/metro-runtime` are REQUIRED.** Without them, the canvas live-preview shows a blank screen because expo cannot serve the web bundle.

**DO NOT install Skia, Reanimated, or heavy deps for the MVP.** They cause install failures and TS errors. Get the app running first with simple `View`, `Text`, and `TouchableOpacity`. If you do add them later, install via `npx expo install react-native-reanimated react-native-gesture-handler` so versions match the SDK.

### Step 2b: Fix app.json — NEVER reference assets that don't exist
When you create files inline (instead of via `create-expo-app`), the `assets/` folder is EMPTY. If `app.json` references `./assets/icon.png`, `splash.png`, etc., **Metro fails to bundle and the phone shows a WHITE SCREEN.**

Write a minimal `app.json` with NO asset references:
```json
{
  "expo": {
    "name": "<App Name>",
    "slug": "<slug>",
    "version": "1.0.0",
    "orientation": "portrait",
    "userInterfaceStyle": "light",
    "assetBundlePatterns": ["**/*"],
    "ios": { "supportsTablet": true },
    "android": {},
    "web": { "bundler": "metro" }
  }
}
```
Add `icon`/`splash` only AFTER you actually generate the image files. **A missing asset = white screen = failed delivery.**

### Step 3: Build a working vertical slice, then modularize before delivery
Start with the minimum files needed to verify the runtime, but do **not** leave a serious product trapped in one giant `App.tsx`.
Move into feature modules, shared components, state, and services before calling the project done.

Use ONLY the minimum runtime-safe primitives for the first slice:
- `View` — for board squares and layout
- `Text` — for labels, scores, dice face
- `TouchableOpacity` or `Pressable` — for tappable pieces
- `StyleSheet.create({})` — for all styling
- `useState`, `useCallback` — for game state

No Canvas, no Skia, no complex components for the first verified slice unless the design truly needs them.

### Step 4: Start Expo immediately after the first verified slice

**TWO SEPARATE exec calls — never combine them!**

**Call 1: Get the LAN IP first**
```bash
LAN_IP=$(hostname -I | awk '{print $1}'); echo "LAN IP: $LAN_IP"
```

**Call 2: Clean up any stale preview, then start expo as a persistent background process**

First kill leftover Expo processes for THIS project (stale previews from earlier runs leak and hold ports/CPU):
```bash
pkill -f "expo start.*projects/<name>" 2>/dev/null || true
pkill -f "expo start --port 8081" 2>/dev/null || true
```

Then start Expo so it survives the exec call. **Prefer `systemd-run --user` when a user systemd/D-Bus session exists, otherwise fall back to `setsid`** (works in headless/server/container environments where `systemd-run --user` fails with "Failed to connect to bus"):
```bash
LAN_IP=$(hostname -I | awk '{print $1}')
PROJ="/home/sharan/Teai builder/instance/workspace/projects/<name>"
if systemctl --user show-environment >/dev/null 2>&1; then
  systemctl --user stop expo-<name> 2>/dev/null || true
  systemd-run --user --unit=expo-<name> \
    --setenv=REACT_NATIVE_PACKAGER_HOSTNAME=$LAN_IP \
    bash -c "cd \"$PROJ\" && ./node_modules/.bin/expo start --port 8081"
  echo "Expo started via systemd-run"
else
  cd "$PROJ" && REACT_NATIVE_PACKAGER_HOSTNAME=$LAN_IP \
    setsid nohup ./node_modules/.bin/expo start --port 8081 > /tmp/expo-<name>.log 2>&1 &
  echo "Expo started via setsid (PID $!) — logs at /tmp/expo-<name>.log"
fi
```

**Why not a plain `&` or `nohup` alone?** A bare background job can be killed when the exec session ends. `systemd-run --user` (when available) or `setsid` detaches the process into its own session so it survives. Always run the cleanup `pkill` above first so you don't stack duplicate Metro servers on the same port.

**Wait 20 seconds, then Call 3: Confirm Metro started** (read whichever log/journal applies)
```bash
sleep 20 && { journalctl --user -u expo-<name> --no-pager -n 20 2>/dev/null || tail -30 /tmp/expo-<name>.log; }
```

**Call 4: Build the exp:// URL and show in canvas**
```bash
LAN_IP=$(hostname -I | awk '{print $1}'); echo "exp://$LAN_IP:8081"
```

Then call canvas:
```
canvas(type="mobile_url", content="exp://192.168.x.x:8081", title="<App> — Scan with Expo Go")
```

**CRITICAL**: 
- `REACT_NATIVE_PACKAGER_HOSTNAME=<LAN_IP>` — without it, expo uses `127.0.0.1` in the manifest and phones can't download the bundle
- Use `systemd-run --user` when available, else `setsid` — both detach Expo so it survives the exec call. Do NOT rely on a bare `&`.
- Always `pkill` the project's old Expo process before starting a new one, so you don't leak duplicate Metro servers.
- To stop later: `systemctl --user stop expo-<name>` (systemd path) or `pkill -f "expo start.*projects/<name>"` (setsid path)

### Step 5: VERIFY the bundle compiles (catches white screen BEFORE delivery)

**This step is MANDATORY. A QR code that opens to a white screen = failed delivery.**

Compile the web bundle and confirm it returns HTTP 200 with real content:
```bash
# Warm up + verify the web bundle (this is what the live preview loads)
BUNDLE_URL="http://127.0.0.1:8081/node_modules/expo/AppEntry.bundle?platform=web&dev=true"
SIZE=$(curl -s -o /dev/null -w "%{size_download}" "$BUNDLE_URL")
echo "Web bundle size: $SIZE bytes"
# Also verify the native (ios) bundle compiles — this is what Expo Go downloads
NATIVE_URL="http://127.0.0.1:8081/node_modules/expo/AppEntry.bundle?platform=ios&dev=true"
NSIZE=$(curl -s -o /dev/null -w "%{size_download}" "$NATIVE_URL")
echo "Native bundle size: $NSIZE bytes"
```
- If size is **< 10000 bytes**, the bundle FAILED — read the response body for the error (likely a missing asset or a JS error). Fix it before delivering.
- A healthy bundle is **hundreds of KB to several MB**.
- Common white-screen cause: missing asset in `app.json` (see Step 2b) or a runtime error in `App.tsx`.

### Step 5b: VERIFY the UI actually renders (white-screen check)

**A 200 OK bundle does NOT mean the UI renders. Do this check BEFORE reporting success.**

Pick ONE of:
- **Headless check (preferred when no real browser is available):** write a tiny `smoke-test.js` in the project root:
```js
// smoke-test.js — loads the served web bundle URL and reports console errors + root children count
const http = require('http');
const url = process.argv[2] || 'http://127.0.0.1:8081/';
http.get(url, (res) => {
  let html = '';
  res.on('data', (chunk) => { html += chunk; });
  res.on('end', () => {
    const hasBody = /<body[^>]*>/i.test(html) && html.replace(/<body[^>]*>/i, '').trim().length > 0;
    console.log('status:', res.statusCode, 'hasBody:', hasBody, 'bytes:', Buffer.byteLength(html));
    process.exit(res.statusCode === 200 && hasBody ? 0 : 2);
  });
}).on('error', (err) => { console.error('smoke-test error:', err.message); process.exit(3); });
```
```bash
node smoke-test.js "http://127.0.0.1:8081/"
```
- **Canvas/live-preview check:** open `http://127.0.0.1:8081` and confirm the app UI is visible, not a blank page. If it is blank, inspect `App.tsx` for components imported from the wrong package (especially gesture handlers from `'react-native'`) or a runtime exception in the top-level component.

Never mark delivery as successful after only the bundle-size check.

### Step 6: Show in canvas (native Expo handoff first, web mirror separately)
```bash
LAN_IP=$(hostname -I | awk '{print $1}'); echo "exp://$LAN_IP:8081"
```

Then call canvas:
```
canvas(type="mobile_url", content="exp://192.168.x.x:8081", title="<App> — Scan with Expo Go")
```

If the web mirror was verified in Step 5b, also show it separately:
```
canvas(type="url", content="http://127.0.0.1:8081", title="<App> — Expo Web Mirror")
```

When `canvas()` is called from the project workspace, TeAI Builder now records
these preview artifacts automatically for the delivery gate.

**Do not treat `exp://` as a browser iframe URL.** Use `mobile_url` for the real
Expo Go/native handoff, and use a separate `url` canvas item only for the
verified web mirror.

---

## What to use for different game types

| Game type | Approach |
|-----------|----------|
| Board game (Ludo, Chess) | `View` grid + `TouchableOpacity` tokens — pure React Native, no Canvas |
| Endless runner (Temple Run) | Expo + `react-native-game-engine` — installed AFTER app starts |
| Graphics-heavy | Expo + `@shopify/react-native-skia` or `expo-gl`/`expo-three` — only add after MVP works and the plain app renders cleanly |

---

## TypeScript Error Rule

If `npx tsc --noEmit` shows errors:
1. Fix **maximum 3 errors at a time**, then re-run
2. **Time limit: 5 minutes on TS errors**. If not clean in 5 minutes, use `// @ts-ignore` on the specific line and move on
3. **Never spend 30+ minutes fixing TS errors before the app even starts**
4. A working app with some `@ts-ignore` is infinitely better than a broken app with perfect types

---

## Production-Ready Checklist

**MVP ≠ production.** Before declaring an app "ready", verify:

```bash
# 1. Clean TypeScript build
npx tsc --noEmit

# 2. No console errors in the bundle
curl -s "http://127.0.0.1:8081/node_modules/expo/AppEntry.bundle?platform=web&dev=true" | grep -i "uncaught\|error\|undefined is not" || echo "No obvious JS errors in bundle"

# 3. Assets exist and are referenced correctly
ls assets/ 2>/dev/null || echo "No assets dir — ensure app.json does not reference missing files"

# 4. EAS build configured (for real stores)
eas build:configure
eas build --platform all --profile preview
```

Required before shipping:
- [ ] No `undefined` component imports / runtime errors
- [ ] All assets referenced in `app.json` exist on disk
- [ ] `eas.json` exists with at least a `preview` and `production` profile
- [ ] App handles offline/poor network gracefully (loading states, retry)
- [ ] No hardcoded secrets/API keys
- [ ] Version + build number bumped in `app.json`

---

## Common Mistakes That Cause Failures

- ❌ **`package.json` `"main"` left as `"index.js"` after a manual `npm init` (no such file)** → `ConfigError: Cannot resolve entry file` and a broken preview. Set `"main": "expo/AppEntry.js"`.
- ❌ **Importing `PanGestureHandler`/`GestureDetector`/`PanGestureHandlerGestureEvent` from `'react-native'`** → they don't exist there (they're in `react-native-gesture-handler`), so the component is `undefined` → **runtime white screen that bundles fine and passes the size check.** Import gesture components from `react-native-gesture-handler`, and wrap the app in `GestureHandlerRootView`.
- ⚠️ **A 200 OK bundle of several MB does NOT mean the UI renders.** A bad import or a render-time exception still produces a blank screen. After the bundle check, scan `App.tsx` for components used but not imported (or imported from the wrong package), and check the Metro/`/tmp/expo-<name>.log` for `Unable to resolve`/`is not defined` warnings before declaring success.
- ❌ **Hand-pinning native dep versions (`npm install react-native@0.73`)** → peer-dependency conflicts and runtime crashes. Use `npx expo install`.
- ❌ **Relying on `systemd-run --user` in a headless/container env** → "Failed to connect to bus". Fall back to `setsid`.
- ❌ **Referencing `./assets/icon.png` etc. in app.json when the files don't exist** → white screen
- ❌ **Skipping `expo install react-dom react-native-web @expo/metro-runtime`** → blank live preview
- ❌ **Delivering without verifying the bundle compiles (Step 5)** → QR opens to white screen
- ❌ Installing Skia + Reanimated + GestureHandler ALL at once before testing
- ❌ Building 10 separate component files before running `expo start` once
- ❌ Trying to fix all TypeScript errors before the app even starts
- ❌ Using complex architecture (layers, engines, hooks) for a game MVP
- ❌ Starting Expo with `--tunnel` (requires Expo account, often fails)

---

## Reporting to CEO

After starting Expo:
1. Report the `exp://IP:PORT` URL
2. Report the verified bundle sizes (web + native) from Step 5
3. Report any startup errors from the log
4. CEO shows the URL in canvas as `mobile_url` with QR + live preview
5. CEO tells user to open Expo Go and scan, or watch the live preview

**Never report "done" without completing Step 5 (bundle verification). A white screen is a failed delivery.**
**Never report "still working on TypeScript errors" after 10 minutes. That means something is wrong.**
