# Plan: {project name}

> The master build plan. Write this AFTER research and BEFORE any code, for every
> non-trivial project. The CEO owns it and keeps it in sync with `TASKS.md`.
> Every spawned employee MUST read the relevant sections before starting work.

_Created: {date} · Last updated: {date}_

## 1. Idea & Goal
- **What we're building:** <one paragraph — the product and who it's for>
- **Core value:** <the single most important thing it must do well>
- **Success criteria (measurable):**
  - <e.g. user can play a full round end-to-end without errors>
  - <e.g. builds clean, verification passes, preview renders on device>

## 2. Research Summary (the idea, not just the tech)
> Fill from web research + reference apps. Link sources. Do NOT rely on memory alone.
- **Reference / competitor apps:** <names> — what works, what to copy, what to avoid
- **Core mechanics / features users expect:** <bulleted, prioritized>
- **Chosen tech stack + why:** <stack> (cross-ref `DECISION_LOG.md`)
- **Risks / unknowns:** <hard parts, perf concerns, platform limits>

## 3. UX / UI Plan
- **Screens / views:** <list each screen and its purpose>
- **Navigation flow:** <screen A → B → C>
- **Key components & interactions:** <controls, gestures, inputs>
- **Visual style:** <colors, typography, layout> (cross-ref `docs/design-system.md`)

## 4. Backend / Data Plan
- **Data models / entities:** <entities + key fields> (write "client-only, no backend" if true)
- **Persistence:** <local storage / DB / files>
- **APIs / services:** <endpoints or third-party services, auth>

## 5. Architecture Plan
- **Module / file structure:** <folders and what lives where> (cross-ref `docs/architecture.md`)
- **State management:** <approach>
- **Key algorithms / systems:** <game loop, collision, scheduling, etc.>

## 6. Phased Breakdown (Phases → Tasks → Subtasks)
> This is the work decomposition. Mirror it into `TASKS.md` with live statuses.
> Assign each task an owner role (architect, designer, frontend_engineer,
> backend_engineer, qa_engineer, devops_engineer).

### Phase 1: <name> — <goal>
- **Task 1.1** <task> — owner: <role>
  - 1.1.1 <subtask>
  - 1.1.2 <subtask>
- **Task 1.2** <task> — owner: <role> (depends: 1.1)

### Phase 2: <name> — <goal>
- **Task 2.1** <task> — owner: <role>

### Phase 3: <name> — <goal>
- **Task 3.1** <task> — owner: <role>

## 7. Milestones & Definition of Done
- **Milestone 1:** <smallest runnable slice>
- **Milestone 2:** <core features complete>
- **Final DoD:** builds clean · `run_verification` passes · preview renders (no white screen) · all Phase tasks in `TASKS.md` are `[x]`
