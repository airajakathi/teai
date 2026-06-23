---
name: superpowers-builder
description: "Superpowers-inspired product build workflow for TeAI Builder: spec first, plan before code, task-scoped execution, and verification before completion."
metadata: {"teai_builder": {"emoji": "⚡", "always": true}}
---

# Superpowers Builder

Use this workflow for any real build task, especially apps, SaaS products, games, backend systems, or multi-file features.

This is a TeAI Builder-native adaptation inspired by `obra/superpowers`, mapped onto TeAI Builder's own tools, skills, project docs, and employee workflow.

## Outcome

Before code reaches the user, the build should have:

- clarified the actual problem and success criteria
- a written spec or design artifact
- a written implementation plan
- a live task board
- task-scoped execution through specialists or subagents
- independent verification before completion

## Required Order

1. **Research first**
   - Use the `research` skill and write `RESEARCH.md`.
   - Identify the real product goal, expected workflow, and platform.

2. **Write the spec**
   - Save specs/design decisions under `docs/superpowers/specs/`.
   - Cover UX, architecture, runtime strategy, and constraints.

3. **Write the implementation plan**
   - Save a concrete plan under `docs/superpowers/plans/`.
   - Break work into small, verifiable tasks with owners and expected outputs.

4. **Sync the live project docs**
   - Reflect the approved plan in `PLAN.md` and `TASKS.md`.
   - `TASKS.md` becomes the execution source of truth.

5. **Execute task-by-task**
   - Use TeAI Builder's employee/subagent flow instead of ad-hoc coding.
   - Give each worker exact file paths, task ids, and verification expectations.
   - Prefer parallel work only when tasks are truly independent.

6. **Verify before completion**
   - Run real checks, not self-reported success.
   - Use `run_verification(...)` and the appropriate test/build/runtime checks.
   - Do not declare completion until the runnable app or artifact is actually proven.

## Mapping To TeAI Builder

- Superpowers brainstorming -> TeAI Builder `research` + spec docs
- Superpowers writing-plans -> `PLAN.md`, `TASKS.md`, `docs/superpowers/plans/`
- Superpowers subagent-driven-development -> TeAI Builder employee/subagent spawning
- Superpowers verification-before-completion -> `run_verification(...)` + runtime health checks

## Non-Negotiables

- Do not jump straight from idea to code on non-trivial builds.
- Do not let the CEO/orchestrator silently become the main coder.
- Do not skip the written plan just because the feature feels obvious.
- Do not mark tasks done without evidence.
- Do not deliver without verification and a live local or deployed preview when applicable.

## For TeAI Builder Projects

When scaffolding or creating a project, ensure these exist and are used:

- `RESEARCH.md`
- `PLAN.md`
- `TASKS.md`
- `SUPERPOWERS.md`
- `docs/superpowers/specs/`
- `docs/superpowers/plans/`

## Completion Standard

A build follows this skill correctly only if:

- the problem was clarified before coding
- the spec and plan were written before major implementation
- execution followed tracked tasks
- verification happened independently
- the user can inspect a real running result or concrete proof artifact
