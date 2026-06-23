# Canvas Workspace Panel

You have a powerful **canvas workspace panel** in the WebUI – a live right-side panel that acts like a mini computer screen you fully control.

## What it can display

| Type | When to use | Example |
|------|-------------|---------|
| `url` | A web app or server is running | `canvas(type="url", content="http://localhost:3000", title="My App")` |
| `mobile_url` | User needs to test on a phone (shows QR code) | `canvas(type="mobile_url", content="http://localhost:3000")` |
| `html` | You built raw HTML, want to preview it | `canvas(type="html", content="<h1>Hello</h1>")` |
| `image` | You generated or found an image | `canvas(type="image", content="/workspace/output.png")` |
| `video` | You created or referenced a video | `canvas(type="video", content="/workspace/demo.mp4")` |
| `code` | You wrote code the user should read | `canvas(type="code", content="print('hi')", lang="python")` |
| `terminal` | You ran commands and want to show output | `canvas(type="terminal", content="$ npm run build\n✓ Done")` |
| `document` | You created a Markdown report/doc | `canvas(type="document", content="# Report\n...")` |
| `screenshot` | You need to see the current canvas state | `canvas(type="screenshot", content="")` |

## Rules

1. **Always push to the canvas** after building or launching anything visual – web apps, images, videos, code snippets, HTML pages.
2. **Use `mobile_url` instead of `url`** when the task explicitly involves mobile apps or the user says "show on phone" / "QR code". A phone mockup + QR code will appear automatically.
3. **Use `terminal`** when running long shell commands that produce interesting output – push the summarised output so the user can see it formatted.
4. **Use `document`** for Markdown reports, README files, analysis results.
5. **You can push multiple items** – each call adds a new item to the canvas navigation bar.
6. **Request a screenshot** (`type="screenshot"`) when you need visual confirmation of what is displayed. The user will see the prompt to capture and return the image.

## Workflow: Mobile App Preview (Expo) — For Android/iOS Apps

For REAL mobile apps built with Expo, follow the **mobile skill**. Start Expo
bound to the LAN IP via a persistent service (NOT `--tunnel`):
```
# 1. Start Expo as a persistent LAN-bound service (see mobile skill for full command)
LAN_IP=$(hostname -I | awk '{print $1}')
systemd-run --user --unit=expo-<name> \
  --setenv=REACT_NATIVE_PACKAGER_HOSTNAME=$LAN_IP \
  bash -c 'cd "projects/<name>" && ./node_modules/.bin/expo start --port 8081'

# 2. Wait, then extract the LAN exp:// URL (must be the LAN IP, not 127.0.0.1)
exec("sleep 15 && journalctl --user -u expo-<name> --no-pager | grep -o 'exp://[^ ]*' | head -1")

# 3. Show as mobile QR in canvas — user scans with Expo Go app
canvas(type="mobile_url", content="exp://<LAN_IP>:8081", title="<App> — Scan with Expo Go on your phone")
```

The user opens **Expo Go** (free app) on their Android or iOS phone and scans this QR code to run the actual native app.

**This is the ONLY correct way to preview a mobile (Android/iOS) app.**

---

## Workflow: previewing a local HTML file (web prototype only) — ONLY FOR WEB APPS

The gateway does NOT serve workspace files directly. **Always** use the port 9090 file server:

```
# 1. Start workspace file server (exact command — copy this)
exec("pgrep -f 'http.server 9090' > /dev/null || (cd /home/sharan/Teai\\ builder/instance/workspace && python3 -m http.server 9090 > /tmp/ws-server.log 2>&1 &) && sleep 1 && echo 'Server ready'")

# 2. Verify it's serving (optional sanity check)
exec("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9090/projects/<name>/index.html")

# 3. Show mobile preview with QR code (PREFERRED for games/mobile apps)
canvas(type="mobile_url", content="http://127.0.0.1:9090/projects/<name>/index.html", title="<Name> — Scan to play on mobile")
```

**IMPORTANT**:
- NEVER use `canvas(type="html", path="projects/...")` — the gateway cannot serve workspace files by path
- ALWAYS use `type="mobile_url"` for games and mobile-style apps (shows phone frame + QR code)
- Use `type="url"` only for full desktop web apps

## Workflow: building + previewing a web app

```
# 1. Scaffold app
exec("npx create-react-app myapp --template typescript")
# 2. Start dev server
exec("cd myapp && npm start &")
# 3. Show in canvas immediately
canvas(type="url", content="http://localhost:3000", title="React App")
# 4. For mobile testing
canvas(type="mobile_url", content="http://localhost:3000", title="Mobile Preview")
```

## Workflow: generating + showing an image

```
path = generate_image("a neon city skyline")
canvas(type="image", content=path, title="Generated artwork")
```

## Workflow: showing code you wrote

```
code = read_file("src/main.py")
canvas(type="code", content=code, lang="python", title="main.py")
```

## Workflow: capturing + reviewing a live page (screenshot tool)

Use the `screenshot` tool to actually *see* a web page or local HTML — for
verifying deploys and self-reviewing UI (a real capture, not a request prompt):

```
result = screenshot(url="https://my-app.vercel.app")   # or a local path / file
# result.artifact.path is a PNG artifact:
canvas(type="image", content="<artifact path>", title="Live site")
# Now look at it and fix anything wrong, then re-screenshot to confirm.
```

- Works with `http(s)://` URLs and workspace-relative HTML files.
- Backed by headless Chromium (Playwright if installed, else a system Chromium
  binary). If neither is available it returns a clear install hint.
- This is the real capture behind the canvas "camera" button for URL views.

## The canvas is aware

- The canvas **auto-detects** certain content from your messages: local URLs you mention (`http://localhost:XXXX`) and image/video attachments are automatically shown.
- But **prefer calling `canvas()` explicitly** for precise control over what is shown and how.
- The canvas supports **QR codes** for mobile URLs, full browser navigation for web URLs, syntax highlighting for code, and ANSI colours for terminal output.
