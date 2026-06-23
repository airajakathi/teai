---
name: research
description: Mandatory research-before-code protocol — read context, web-search, write RESEARCH.md with findings and todo list before any implementation.
metadata: {"teai_builder": {"emoji": "🔍", "always": true}}
---

# Research-First Protocol

**This protocol is mandatory for every build task. Never write production code without completing it.**

## Protocol Steps

### Step 1: Read all existing context
Before searching the web, understand what already exists:
- Read `PROJECT.md` — current phase, tech stack, deployment target
- Read `DECISION_LOG.md` — decisions already made (do not re-decide)
- Read `docs/architecture.md` — system design and API spec
- List and read relevant source files — never assume what a file contains

### Step 2: Web research — the IDEA first, then the tech
**2a. Research the idea/product** (do this even for games and "simple" apps — it is
what makes the result feel real instead of a toy):
```
web_search("<product/genre> best examples <current year>")
web_search("<reference app/competitor> features list")
web_search("<product type> core mechanics / must-have features")
web_search("<product type> UX patterns common screens")
```
Capture: reference apps, the features users expect, screens/navigation, and what
makes the good ones good. This feeds the UI/UX and feature sections of `PLAN.md`.

**2b. Research the tech** for every library, framework, platform, or API you will use:
```
web_search("<library/framework> best practices <current year>")
web_search("<framework> <version> setup guide")
web_search("<platform> deploy <app type> guide")
web_search("<feature> security best practices")
```
Anchor on current, stable information. Do not rely on training data alone for:
- Library APIs and configuration (they change frequently)
- Deployment platform CLI and dashboard steps
- Security recommendations
- Package versions

**MANDATORY — Resolve the CURRENT/LATEST versions BEFORE scaffolding or installing:**
For Expo/React Native projects, explicitly search for and record:
- Current stable Expo SDK version (`npx expo --version` and current release notes)
- Supported React Native version for that SDK
- Current `create-expo-app` latest release
- Current recommended Node.js LTS version

Example web searches:
```
web_search("Expo SDK latest version 2026")
web_search("Expo SDK 54 React Native version")
web_search("create-expo-app latest version")
web_search("Node.js LTS version 2026")
web_search("React Native latest stable version 2026")
```
Record the exact versions in `RESEARCH.md` and in the project's `DECISION_LOG.md`. If installed versions differ, align them before writing code. **Never build on an outdated SDK.**

### Step 3: Write RESEARCH.md
Copy the template: `read_file("RESEARCH.md")`
Write to: `projects/<name>/research/<role>.md`

Fill in:
- Context read (checklist of files reviewed)
- Web research table (query → key finding)
- Key findings (top 3 actionable insights)
- Risks and unknowns
- **Ordered todo list** — every task in dependency order

### Step 4: Execute the todo list
Work through the todo list top-to-bottom. Do not skip items or reorder unless a blocker requires it.

## Anti-Patterns to Avoid

- **Assuming file contents** — always `read_file` before editing
- **Hardcoding config** — always use environment variables for URLs, ports, secrets
- **Mock data in production** — always connect to the real API and database
- **Skipping package docs** — always check current API for any library you install
- **Re-deciding already-logged decisions** — respect DECISION_LOG.md entries

## Mandatory Self-Verification Before Delivery (Run These)

### JavaScript / HTML5 files:
```bash
sed -n '/<script>/,/<\/script>/p' <file> | sed '/<script>/d; /<\/script>/d' > /tmp/_chk.js && node --check /tmp/_chk.js  # syntax (HTML files — strip both open+close tags)
grep -n "\.beginPath()\." <file>             # void chaining crash
grep -n "^const.*= canvas\." <file> | grep -v "() =>"  # stale resize constant
grep -n "frame % rand" <file>               # broken per-frame spawn
```
All checks must return zero matches/errors before the file is delivered.

### Python files:
```bash
python3 -m py_compile <file> && echo OK     # syntax
python3 -m flake8 <file> --max-line-length=100  # style
```

### Workspace paths — ALWAYS relative:
- WRONG: `write_file("instance/workspace/projects/game.html", ...)`
- CORRECT: `write_file("projects/game.html", ...)`

## Common JavaScript Bugs to Catch Before Delivery

- **Method chaining on void returns**: `ctx.beginPath().arc(...)` — `beginPath()` returns `undefined`, crashes immediately on first obstacle draw
- **Constants that need to be functions**: `const LANE_W = canvas.width / 3` is stale after resize. ALWAYS use `const LANE_W = () => canvas.width / 3`
- **Modulo on random numbers**: `frame % randInt(60, 120) === 0` — calls `randInt` every frame, nearly never hits. Use a counter: `if (frame >= nextSpawn) { spawn(); nextSpawn = frame + randInt(...); }`
- **Doubled workspace paths**: never include the workspace root in file path arguments — use `projects/name/file.html` not `instance/workspace/projects/name/file.html`

## When to Skip Research

Research can be skipped only for:
- Simple one-file changes (add a comment, fix a typo, update a single value)
- Changes where you have already done research this session and have the RESEARCH.md written

For everything else, follow the full protocol.
