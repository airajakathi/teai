# Live Tasks: {project name}

> Real-time task board derived from `PLAN.md`. The CEO updates statuses here as
> work progresses — this is the single source of truth for "what's done / what's
> next". Update it after every subagent finishes and before spawning the next.
>
> **Status legend:** `[ ]` TODO · `[~]` IN PROGRESS · `[x]` DONE · `[!]` BLOCKED
> Each task: `id  title — owner: <role>  (depends: <ids>)`

_Last updated: {date}_

## Summary
- **Current phase:** <phase name>
- **Done:** 0 / <total> tasks
- **Next up:** <task id + title>
- **Blocked:** <none, or list>

## Phase 1: <name>  — status: in progress
- [ ] 1.1 <task> — owner: architect
  - [ ] 1.1.1 <subtask>
  - [ ] 1.1.2 <subtask>
- [ ] 1.2 <task> — owner: frontend_engineer (depends: 1.1)

## Phase 2: <name>  — status: todo
- [ ] 2.1 <task> — owner: backend_engineer

## Phase 3: <name>  — status: todo
- [ ] 3.1 <task> — owner: qa_engineer

## Blocked / Issues
- (none yet — list any blocker here with the task id and what's needed)
