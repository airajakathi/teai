"""Built-in slash command handlers."""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from uuid import uuid4

from teai_builder import __version__
from teai_builder.bus.events import OutboundMessage
from teai_builder.command.router import CommandContext, CommandRouter
from teai_builder.utils.helpers import build_status_content
from teai_builder.utils.restart import set_restart_notice_to_env


@dataclass(frozen=True)
class BuiltinCommandSpec:
    command: str
    title: str
    description: str
    icon: str
    arg_hint: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "command": self.command,
            "title": self.title,
            "description": self.description,
            "icon": self.icon,
            "arg_hint": self.arg_hint,
        }


BUILTIN_COMMAND_SPECS: tuple[BuiltinCommandSpec, ...] = (
    BuiltinCommandSpec(
        "/new",
        "New chat",
        "Stop the current task and start a fresh conversation.",
        "square-pen",
    ),
    BuiltinCommandSpec(
        "/stop",
        "Stop current task",
        "Cancel the active agent turn for this chat.",
        "square",
    ),
    BuiltinCommandSpec(
        "/restart",
        "Restart teai_builder",
        "Restart the bot process in place.",
        "rotate-cw",
    ),
    BuiltinCommandSpec(
        "/status",
        "Show status",
        "Display runtime, provider, and channel status.",
        "activity",
    ),
    BuiltinCommandSpec(
        "/model",
        "Switch model preset",
        "Show or switch the active model preset.",
        "brain",
        "[preset]",
    ),
    BuiltinCommandSpec(
        "/history",
        "Show conversation history",
        "Print the last N persisted conversation messages.",
        "history",
        "[n]",
    ),
    BuiltinCommandSpec(
        "/goal",
        "Start long-running goal",
        "Tell the agent to treat the request as a long-running goal.",
        "activity",
        "<goal>",
    ),
    BuiltinCommandSpec(
        "/dream",
        "Run Dream",
        "Manually trigger memory consolidation.",
        "sparkles",
    ),
    BuiltinCommandSpec(
        "/dream-log",
        "Show Dream log",
        "Show what the last Dream consolidation changed.",
        "book-open",
    ),
    BuiltinCommandSpec(
        "/dream-restore",
        "Restore memory",
        "Revert memory to a previous Dream snapshot.",
        "undo-2",
    ),
    BuiltinCommandSpec(
        "/skill",
        "List skills",
        "List all enabled skills available to the agent.",
        "wrench",
    ),
    BuiltinCommandSpec(
        "/help",
        "Show help",
        "List available slash commands.",
        "circle-help",
    ),
    BuiltinCommandSpec(
        "/pairing",
        "Manage pairing",
        "List, approve, deny or revoke pairing requests.",
        "shield",
        "[list|approve <code>|deny <code>|revoke <user_id>]",
    ),
)

_WORKFLOW_ACTIONS = {"start", "status", "resume", "cancel"}


def builtin_command_palette() -> list[dict[str, str]]:
    """Return structured command metadata for UI command palettes."""
    return [spec.as_dict() for spec in BUILTIN_COMMAND_SPECS]


async def cmd_stop(ctx: CommandContext) -> OutboundMessage:
    """Cancel all active tasks and subagents for the session."""
    loop = ctx.loop
    msg = ctx.msg
    total = await loop._cancel_active_tasks(ctx.key)
    content = f"Stopped {total} task(s)." if total else "No active task to stop."
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, content=content,
        metadata=dict(msg.metadata or {})
    )


async def cmd_restart(ctx: CommandContext) -> OutboundMessage:
    """Restart the process in-place via os.execv."""
    msg = ctx.msg
    set_restart_notice_to_env(
        channel=msg.channel,
        chat_id=msg.chat_id,
        metadata=dict(msg.metadata or {}),
    )

    async def _do_restart():
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable, "-m", "teai_builder"] + sys.argv[1:])

    asyncio.create_task(_do_restart())
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, content="Restarting...",
        metadata=dict(msg.metadata or {})
    )


async def cmd_status(ctx: CommandContext) -> OutboundMessage:
    """Build an outbound status message for a session."""
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    ctx_est = 0
    with suppress(Exception):
        ctx_est, _ = loop.consolidator.estimate_session_prompt_tokens(session)
    if ctx_est <= 0:
        ctx_est = loop._last_usage.get("prompt_tokens", 0)

    # Fetch web search provider usage (best-effort, never blocks the response)
    search_usage_text: str | None = None
    # Never let usage fetch break /status
    with suppress(Exception):
        from teai_builder.utils.searchusage import fetch_search_usage
        web_cfg = getattr(loop, "web_config", None)
        search_cfg = getattr(web_cfg, "search", None) if web_cfg else None
        if search_cfg is not None:
            provider = getattr(search_cfg, "provider", "duckduckgo")
            api_key = getattr(search_cfg, "api_key", "") or None
            usage = await fetch_search_usage(provider=provider, api_key=api_key)
            search_usage_text = usage.format()
    active_tasks = loop._active_tasks.get(ctx.key, [])
    task_count = sum(1 for t in active_tasks if not t.done())
    with suppress(Exception):
        task_count += loop.subagents.get_running_count_by_session(ctx.key)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_status_content(
            version=__version__, model=loop.model,
            start_time=loop._start_time, last_usage=loop._last_usage,
            context_window_tokens=loop.context_window_tokens,
            session_msg_count=len(session.get_history(max_messages=0)),
            context_tokens_estimate=ctx_est,
            search_usage_text=search_usage_text,
            active_task_count=task_count,
            max_completion_tokens=getattr(
                getattr(loop.provider, "generation", None), "max_tokens", 8192
            ),
        ),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_new(ctx: CommandContext) -> OutboundMessage:
    """Stop active task and start a fresh session."""
    loop = ctx.loop
    await loop._cancel_active_tasks(ctx.key)
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    snapshot = session.messages[session.last_consolidated:]
    session.clear()
    loop.sessions.save(session)
    loop.sessions.invalidate(session.key)
    if snapshot:
        loop._schedule_background(loop.consolidator.archive(snapshot, session_key=ctx.key))
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content="New session started.",
        metadata=dict(ctx.msg.metadata or {})
    )


def _format_preset_names(names: list[str]) -> str:
    return ", ".join(f"`{name}`" for name in names) if names else "(none configured)"


def _model_preset_names(loop) -> list[str]:
    names = set(loop.model_presets)
    names.add("default")
    return ["default", *sorted(name for name in names if name != "default")]


def _active_model_preset_name(loop) -> str:
    return loop.model_preset or "default"


def _command_error_message(exc: Exception) -> str:
    return str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)


def _model_command_status(loop) -> str:
    names = _model_preset_names(loop)
    active = _active_model_preset_name(loop)
    return "\n".join([
        "## Model",
        f"- Current model: `{loop.model}`",
        f"- Current preset: `{active}`",
        f"- Available presets: {_format_preset_names(names)}",
    ])


async def cmd_model(ctx: CommandContext) -> OutboundMessage:
    """Show or switch model presets."""
    loop = ctx.loop
    args = ctx.args.strip()
    metadata = {**dict(ctx.msg.metadata or {}), "render_as": "text"}

    if not args:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=_model_command_status(loop),
            metadata=metadata,
        )

    parts = args.split()
    if len(parts) != 1:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Usage: `/model [preset]`",
            metadata=metadata,
        )

    name = parts[0]
    try:
        loop.set_model_preset(name)
    except (KeyError, ValueError) as exc:
        names = _model_preset_names(loop)
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                f"Could not switch model preset: {_command_error_message(exc)}\n\n"
                f"Available presets: {_format_preset_names(names)}"
            ),
            metadata=metadata,
        )

    max_tokens = getattr(getattr(loop.provider, "generation", None), "max_tokens", None)
    lines = [
        f"Switched model preset to `{loop.model_preset}`.",
        f"- Model: `{loop.model}`",
        f"- Context window: {loop.context_window_tokens}",
    ]
    if max_tokens is not None:
        lines.append(f"- Max output tokens: {max_tokens}")
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="\n".join(lines),
        metadata=metadata,
    )


async def cmd_dream(ctx: CommandContext) -> OutboundMessage:
    """Manually trigger a Dream consolidation run."""
    import time

    loop = ctx.loop
    msg = ctx.msg

    async def _run_dream():
        from teai_builder.agent.memory import MemoryStore

        dream_session_key = MemoryStore.dream_session_key
        build_dream_commit_message = MemoryStore.build_dream_commit_message
        prune_dream_sessions = MemoryStore.prune_dream_sessions

        store = loop.context.memory
        content = ""
        resp = None
        t0 = time.monotonic()
        try:
            result = store.build_dream_prompt()
            if result is None:
                await loop.bus.publish_outbound(OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="Dream: nothing to process.",
                ))
                return
            prompt, last_cursor = result
            key = dream_session_key()
            resp = await loop.process_direct(
                prompt,
                session_key=key,
                ephemeral=True,
                tools=store.build_dream_tools(),
            )
            elapsed = time.monotonic() - t0
            if MemoryStore.dream_run_completed(resp):
                store.set_last_dream_cursor(last_cursor)
                content = f"Dream completed in {elapsed:.1f}s."
            else:
                content = (
                    f"Dream did not complete after {elapsed:.1f}s; "
                    "memory cursor was not advanced."
                )
        except Exception as e:
            elapsed = time.monotonic() - t0
            content = f"Dream failed after {elapsed:.1f}s: {e}"
        finally:
            from teai_builder.webui.token_usage import record_response_token_usage

            record_response_token_usage(
                resp,
                source="dream",
                timezone_name=getattr(loop.context, "timezone", None),
            )
            if store.git.is_initialized():
                commit_msg = build_dream_commit_message("dream: manual run", resp)
                sha = store.git.auto_commit(commit_msg)
                if sha:
                    content += f" (commit {sha})"
            store.compact_history()
            prune_dream_sessions(loop.sessions.sessions_dir)
        await loop.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=content,
        ))

    asyncio.create_task(_run_dream())
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, content="Dreaming...",
    )


def _extract_changed_files(diff: str) -> list[str]:
    """Extract changed file paths from a unified diff."""
    files: list[str] = []
    seen: set[str] = set()
    for line in diff.splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        path = parts[3]
        if path.startswith("b/"):
            path = path[2:]
        if path in seen:
            continue
        seen.add(path)
        files.append(path)
    return files


def _format_changed_files(diff: str) -> str:
    files = _extract_changed_files(diff)
    if not files:
        return "No tracked memory files changed."
    return ", ".join(f"`{path}`" for path in files)


def _format_dream_log_content(commit, diff: str, *, requested_sha: str | None = None) -> str:
    files_line = _format_changed_files(diff)
    lines = [
        "## Dream Update",
        "",
        "Here is the selected Dream memory change." if requested_sha else "Here is the latest Dream memory change.",
        "",
        f"- Commit: `{commit.sha}`",
        f"- Time: {commit.timestamp}",
        f"- Changed files: {files_line}",
    ]
    if diff:
        lines.extend([
            "",
            f"Use `/dream-restore {commit.sha}` to undo this change.",
            "",
            "```diff",
            diff.rstrip(),
            "```",
        ])
    else:
        lines.extend([
            "",
            "Dream recorded this version, but there is no file diff to display.",
        ])
    return "\n".join(lines)


def _format_dream_restore_list(commits: list) -> str:
    lines = [
        "## Dream Restore",
        "",
        "Choose a Dream memory version to restore. Latest first:",
        "",
    ]
    for c in commits:
        lines.append(f"- `{c.sha}` {c.timestamp} - {c.message.splitlines()[0]}")
    lines.extend([
        "",
        "Preview a version with `/dream-log <sha>` before restoring it.",
        "Restore a version with `/dream-restore <sha>`.",
    ])
    return "\n".join(lines)


async def cmd_dream_log(ctx: CommandContext) -> OutboundMessage:
    """Show what the last Dream changed.

    Default: diff of the latest commit (HEAD~1 vs HEAD).
    With /dream-log <sha>: diff of that specific commit.
    """
    store = ctx.loop.consolidator.store
    git = store.git

    if not git.is_initialized():
        if store.get_last_dream_cursor() == 0:
            msg = "Dream has not run yet. Run `/dream`, or wait for the next scheduled Dream cycle."
        else:
            msg = "Dream history is not available because memory versioning is not initialized."
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content=msg, metadata={"render_as": "text"},
        )

    args = ctx.args.strip()

    if args:
        # Show diff of a specific commit
        sha = args.split()[0]
        result = git.show_commit_diff(sha)
        if not result:
            content = (
                f"Couldn't find Dream change `{sha}`.\n\n"
                "Use `/dream-restore` to list recent versions, "
                "or `/dream-log` to inspect the latest one."
            )
        else:
            commit, diff = result
            content = _format_dream_log_content(commit, diff, requested_sha=sha)
    else:
        # Default: show the latest commit's diff
        commits = git.log(max_entries=1)
        result = git.show_commit_diff(commits[0].sha) if commits else None
        if result:
            commit, diff = result
            content = _format_dream_log_content(commit, diff)
        else:
            content = "Dream memory has no saved versions yet."

    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content=content, metadata={"render_as": "text"},
    )


async def cmd_dream_restore(ctx: CommandContext) -> OutboundMessage:
    """Restore memory files from a previous dream commit.

    Usage:
        /dream-restore          — list recent commits
        /dream-restore <sha>    — revert a specific commit
    """
    store = ctx.loop.consolidator.store
    git = store.git
    if not git.is_initialized():
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content="Dream history is not available because memory versioning is not initialized.",
        )

    args = ctx.args.strip()
    if not args:
        # Show recent commits for the user to pick
        commits = git.log(max_entries=10)
        if not commits:
            content = "Dream memory has no saved versions to restore yet."
        else:
            content = _format_dream_restore_list(commits)
    else:
        sha = args.split()[0]
        result = git.show_commit_diff(sha)
        changed_files = _format_changed_files(result[1]) if result else "the tracked memory files"
        new_sha = git.revert(sha)
        if new_sha:
            content = (
                f"Restored Dream memory to the state before `{sha}`.\n\n"
                f"- New safety commit: `{new_sha}`\n"
                f"- Restored files: {changed_files}\n\n"
                f"Use `/dream-log {new_sha}` to inspect the restore diff."
            )
        else:
            content = (
                f"Couldn't restore Dream change `{sha}`.\n\n"
                "It may not exist, or it may be the first saved version with no earlier state to restore."
            )
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content=content, metadata={"render_as": "text"},
    )


_HISTORY_DEFAULT_COUNT = 10
_HISTORY_MAX_COUNT = 50
_HISTORY_MAX_CONTENT_CHARS = 200


def _format_history_message(msg: dict) -> str | None:
    """Format a single history message for display. Returns None to skip."""
    role = msg.get("role")
    if role not in ("user", "assistant"):
        return None
    content = msg.get("content") or ""
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        content = " ".join(parts)
    content = str(content).strip()
    if not content:
        return None
    if len(content) > _HISTORY_MAX_CONTENT_CHARS:
        content = content[:_HISTORY_MAX_CONTENT_CHARS] + "…"
    label = "👤 You" if role == "user" else "🤖 Bot"
    return f"{label}: {content}"


async def cmd_history(ctx: CommandContext) -> OutboundMessage:
    """Show the last N messages of the current session (default 10, max 50).

    Usage: /history [count]
    """
    count = _HISTORY_DEFAULT_COUNT
    if ctx.args.strip():
        try:
            count = max(1, min(int(ctx.args.strip()), _HISTORY_MAX_COUNT))
        except ValueError:
            return OutboundMessage(
                channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
                content="Usage: /history [count] — e.g. /history 5 (default: 10, max: 50)",
                metadata=dict(ctx.msg.metadata or {}),
            )

    session = ctx.session or ctx.loop.sessions.get_or_create(ctx.key)
    history = session.get_history(max_messages=0)
    visible = [_format_history_message(m) for m in history]
    visible = [m for m in visible if m is not None]
    recent = visible[-count:]

    if not recent:
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content="No conversation history yet.",
            metadata=dict(ctx.msg.metadata or {}),
        )

    header = f"Last {len(recent)} message(s):\n"
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content=header + "\n".join(recent),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


_GOAL_PROMPT_TEMPLATE = """The user declared a sustained objective for this thread.

Inspect or clarify if needed, then call `long_task` with the refined objective (and optional short ui_summary). Work proceeds as normal assistant turns using your usual tools. When the objective is fully done and verified, call `complete_goal` with a brief recap. If the user later cancels or changes direction, still call `complete_goal` with an honest recap (then `long_task` again only after there is no active goal). Do not use `long_task` / `complete_goal` for trivial one-shot answers.

Goal:
{goal}
"""


async def cmd_goal(ctx: CommandContext) -> OutboundMessage | None:
    """Rewrite /goal into a normal agent turn that nudges long_task use."""
    goal = ctx.args.strip()
    if not goal:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Usage: /goal <long-running task description>",
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )
    if ctx.session is None:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                "A task is already running for this chat. "
                "Use `/stop` first, then send `/goal <long-running task description>` again."
            ),
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    ctx.msg.metadata = {
        **dict(ctx.msg.metadata or {}),
        "original_command": "/goal",
        "original_content": ctx.raw,
        "goal_started_at": time.time(),
    }
    ctx.msg.content = _GOAL_PROMPT_TEMPLATE.format(goal=goal)
    return None


async def cmd_pairing(ctx: CommandContext) -> OutboundMessage:
    """List, approve, deny or revoke pairing requests."""
    from teai_builder.pairing import PAIRING_COMMAND_META_KEY, handle_pairing_command

    reply = handle_pairing_command(ctx.msg.channel, ctx.args)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=reply,
        metadata={PAIRING_COMMAND_META_KEY: True},
    )


async def cmd_skill(ctx: CommandContext) -> OutboundMessage:
    """List all enabled skills (name and description only)."""
    loop = ctx.loop
    skills = loop.context.skills.list_skills(filter_unavailable=False)
    if not skills:
        content = "No skills available."
    else:
        lines = [f"Available skills ({len(skills)}):", ""]
        for entry in skills:
            desc = loop.context.skills._get_skill_description(entry["name"])
            lines.append(f"- **{entry['name']}** — {desc}")
        content = "\n".join(lines)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata=dict(ctx.msg.metadata or {}),
    )

async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    """Return available slash commands."""
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_help_text(),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_workflow(ctx: CommandContext) -> OutboundMessage:
    """Start or manage a built-in workflow run."""
    parts = shlex.split(ctx.args)
    if not parts:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                "Usage:\n"
                "- `/workflow <workflow_id> [args...]`\n"
                "- `/workflow start <workflow_id> [args...]`\n"
                "- `/workflow status [run_id]`\n"
                "- `/workflow resume <run_id>`\n"
                "- `/workflow cancel <run_id>`"
            ),
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )
    action = parts[0] if parts[0] in _WORKFLOW_ACTIONS else "start"
    action_parts = parts[1:] if action != "start" or parts[0] in _WORKFLOW_ACTIONS else parts

    from teai_builder.agent.goal_validator import Goal
    from teai_builder.agent.llm3.workflow_library import get_workflow
    from teai_builder.agent.llm3.workflow_models import WorkflowState

    def _format_run_summary(run) -> str:
        lines = [
            f"Run: `{run.run_id}`",
            f"Workflow: `{run.workflow_id}`",
            f"State: `{run.state}`",
        ]
        if ctx.loop.workflow_engine.is_run_active(run.run_id):
            lines.append("Active: `yes`")
        if run.current_step:
            lines.append(f"Current step: `{run.current_step}`")
        if run.error:
            lines.append(f"Error: {run.error}")
        if run.step_states:
            lines.append("")
            lines.append("Steps:")
            for step_run in run.step_states.values():
                detail = f"- `{step_run.step_id}`: `{step_run.state}`"
                if step_run.attempts:
                    detail += f" (attempts: {step_run.attempts})"
                if step_run.skipped_reason:
                    detail += f" - {step_run.skipped_reason}"
                elif step_run.error:
                    detail += f" - {step_run.error}"
                lines.append(detail)
        return "\n".join(lines)

    async def _publish_run_completion(run, workflow) -> None:
        status = run.state
        details = [
            f"Workflow `{workflow.workflow_id}` finished with state `{status}`.",
            "",
            f"Run: `{run.run_id}`",
        ]
        if run.error:
            details.extend(["", f"Error: {run.error}"])
        if run.step_states:
            details.extend(["", "Steps:"])
            for step_run in run.step_states.values():
                details.append(f"- `{step_run.step_id}`: `{step_run.state}`")
        await ctx.loop.bus.publish_outbound(
            OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content="\n".join(details),
                metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
            )
        )

    if action == "status":
        run_id = action_parts[0] if action_parts else None
        load_run = getattr(ctx.loop, "load_llm3_workflow_run", None)
        list_runs = getattr(ctx.loop, "list_llm3_workflow_runs", None)
        if run_id:
            run = (
                load_run(run_id)
                if callable(load_run)
                else ctx.loop.workflow_engine.load_run(run_id)
            )
            if run is None:
                return OutboundMessage(
                    channel=ctx.msg.channel,
                    chat_id=ctx.msg.chat_id,
                    content=f"Workflow run `{run_id}` not found.",
                    metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
                )
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content=_format_run_summary(run),
                metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
            )
        runs = (
            list_runs(limit=5)
            if callable(list_runs)
            else ctx.loop.workflow_engine.list_runs(limit=5)
        )
        if not runs:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content="No workflow runs found yet.",
                metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
            )
        lines = ["Recent workflow runs:", ""]
        for run in runs:
            lines.append(f"- `{run.run_id}` `{run.workflow_id}` `{run.state}`")
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="\n".join(lines),
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    if action == "cancel":
        if not action_parts:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content="Usage: `/workflow cancel <run_id>`",
                metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
            )
        run_id = action_parts[0]
        cancel_run = getattr(ctx.loop, "cancel_llm3_workflow_run", None)
        cancelled = (
            cancel_run(run_id)
            if callable(cancel_run)
            else ctx.loop.workflow_engine.request_cancel(run_id)
        )
        content = (
            f"Cancellation requested for workflow run `{run_id}`."
            if cancelled
            else f"Could not cancel workflow run `{run_id}`."
        )
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=content,
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    if action == "resume":
        if not action_parts:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content="Usage: `/workflow resume <run_id>`",
                metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
            )
        run_id = action_parts[0]
        load_run = getattr(ctx.loop, "load_llm3_workflow_run", None)
        is_active = getattr(ctx.loop, "is_llm3_workflow_active", None)
        goal_from_run = getattr(ctx.loop, "llm3_workflow_goal_from_run", None)
        variables_from_run = getattr(ctx.loop, "llm3_workflow_variables_from_run", None)
        run = (
            load_run(run_id)
            if callable(load_run)
            else ctx.loop.workflow_engine.load_run(run_id)
        )
        if run is None:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content=f"Workflow run `{run_id}` not found.",
                metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
            )
        if (
            is_active(run_id)
            if callable(is_active)
            else ctx.loop.workflow_engine.is_run_active(run_id)
        ):
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content=f"Workflow run `{run_id}` is already active.",
                metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
            )
        if run.state == WorkflowState.COMPLETED:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content=f"Workflow run `{run_id}` is already completed.",
                metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
            )
        workflow = get_workflow(run.workflow_id)
        goal = (
            goal_from_run(run)
            if callable(goal_from_run)
            else ctx.loop.workflow_engine.goal_from_run(run)
        )
        variables = (
            variables_from_run(run)
            if callable(variables_from_run)
            else ctx.loop.workflow_engine.variables_from_run(run)
        )
        if workflow is None or goal is None:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content=(
                    f"Workflow run `{run_id}` cannot be resumed because its "
                    "definition or goal metadata is missing."
                ),
                metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
            )
        resume_workflow = getattr(ctx.loop, "resume_llm3_workflow_execution", None)
        if callable(resume_workflow):
            resume_workflow(
                workflow=workflow,
                run=run,
                goal=goal,
                variables=variables,
                on_completed=_publish_run_completion,
            )
        else:
            async def _resume_workflow() -> None:
                recovery_id = None
                start_recovery = getattr(ctx.loop, "start_llm3_workflow_recovery", None)
                complete_recovery = getattr(ctx.loop, "complete_llm3_workflow_recovery", None)
                sync_task_graph = getattr(ctx.loop, "sync_llm3_workflow_graph", None)
                if callable(sync_task_graph):
                    sync_task_graph(workflow=workflow, run=run, goal=goal)
                if callable(start_recovery):
                    recovery_id = start_recovery(
                        run=run,
                        goal=goal,
                        reason="manual_restore",
                    )
                try:
                    resumed = await ctx.loop.dynamic_workflow.execute(workflow, goal, variables, run=run)
                    if recovery_id is not None and callable(complete_recovery):
                        complete_recovery(
                            recovery_id,
                            goal=goal,
                            run=resumed,
                            status=resumed.state,
                            summary=f"Workflow resume finished with state {resumed.state}",
                        )
                    await _publish_run_completion(resumed, workflow)
                except Exception:
                    if recovery_id is not None and callable(complete_recovery):
                        complete_recovery(
                            recovery_id,
                            goal=goal,
                            run=run,
                            status="failed",
                            summary="Workflow resume failed before completion",
                        )
                    raise

            task = ctx.loop._schedule_background(_resume_workflow())
            ctx.loop.workflow_engine.register_active_run(run.run_id, task)
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                f"Resumed workflow `{workflow.workflow_id}`.\n\n"
                f"Run: `{run.run_id}`"
            ),
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    workflow_id = action_parts[0]
    workflow = get_workflow(workflow_id)
    if workflow is None:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=f"Unknown workflow: `{workflow_id}`",
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    required_fields = list(workflow.input_schema.get("required", []))
    values = action_parts[1:]
    if len(values) < len(required_fields):
        if required_fields:
            arg_list = " ".join(f"<{field}>" for field in required_fields)
            usage = f"Usage: `/workflow {workflow_id} {arg_list}`"
        else:
            usage = f"Usage: `/workflow {workflow_id}`"
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                f"Workflow `{workflow_id}` is available.\n\n"
                f"Name: {workflow.name}\n"
                f"Description: {workflow.description}\n\n"
                f"{usage}"
            ),
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    variables = {field: values[index] for index, field in enumerate(required_fields)}
    goal = Goal(
        goal_id=f"{workflow_id}:{uuid4().hex[:8]}",
        description=workflow.description,
        success_criteria=[f"complete {step.step_id}" for step in workflow.steps],
        metadata={
            "workflow_id": workflow_id,
            "variables": variables,
            "session_key": ctx.key,
            "channel": ctx.msg.channel,
            "chat_id": ctx.msg.chat_id,
        },
    )
    start_workflow = getattr(ctx.loop, "start_llm3_workflow_execution", None)
    if callable(start_workflow):
        handle = start_workflow(
            workflow=workflow,
            goal=goal,
            variables=variables,
            on_completed=_publish_run_completion,
        )
        run = handle.run
    else:
        run = ctx.loop.workflow_engine.create_run(workflow, goal, variables, executor="dynamic")
        sync_task_graph = getattr(ctx.loop, "sync_llm3_workflow_graph", None)
        if callable(sync_task_graph):
            sync_task_graph(workflow=workflow, run=run, goal=goal)

        async def _run_workflow() -> None:
            completed = await ctx.loop.dynamic_workflow.execute(workflow, goal, variables, run=run)
            await _publish_run_completion(completed, workflow)

        task = ctx.loop._schedule_background(_run_workflow())
        ctx.loop.workflow_engine.register_active_run(run.run_id, task)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=(
            f"Started workflow `{workflow_id}`.\n\n"
            f"Run: `{run.run_id}`\n"
            f"Name: {workflow.name}\n"
            f"Description: {workflow.description}\n\n"
            "Use `/workflow status "
            f"{run.run_id}` to check progress or `/workflow cancel {run.run_id}` to stop it."
        ),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_checkpoint(ctx: CommandContext) -> OutboundMessage:
    """Save, restore, rebuild, delete, or list orchestration checkpoints."""
    from teai_builder.agent.checkpoint import (
        Checkpoint,
        build_rebuild_summary,
        get_checkpoint_store,
        summarize_checkpoint,
    )

    parts = ctx.args.strip().split()
    action = parts[0] if parts else "list"
    session = ctx.session or ctx.loop.sessions.get_or_create(ctx.key)
    store = get_checkpoint_store()

    if action == "save":
        messages = session.get_history(max_messages=0)
        checkpoint = Checkpoint(
            checkpoint_id=f"{int(time.time())}",
            session_key=session.key,
            created_at=time.time(),
            context_budget_pct=0.0,
            state={"max_iterations": ctx.loop.max_iterations},
            messages=messages,
            metadata={
                "kind": "session",
                "label": " ".join(parts[1:]).strip() or None,
            },
        )
        store.save(checkpoint)
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=f"Saved checkpoint `{checkpoint.checkpoint_id}` for session `{session.key}`.",
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    if action == "restore":
        if len(parts) < 2:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content="Usage: `/checkpoint restore <checkpoint_id>`",
                metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
            )
        restored = store.load(session.key, parts[1])
        if restored is None:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content=f"Checkpoint `{parts[1]}` not found.",
                metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
            )
        session.messages = restored.messages
        ctx.loop.sessions.save(session)
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=f"Restored checkpoint `{parts[1]}` for session `{session.key}`.",
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    if action == "rebuild":
        if len(parts) < 2:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content="Usage: `/checkpoint rebuild <checkpoint_id>`",
                metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
            )
        checkpoint = store.load(session.key, parts[1])
        if checkpoint is None:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content=f"Checkpoint `{parts[1]}` not found.",
                metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
            )
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=build_rebuild_summary(checkpoint),
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    if action == "delete":
        if len(parts) < 2:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content="Usage: `/checkpoint delete <checkpoint_id>`",
                metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
            )
        deleted = store.delete(session.key, parts[1])
        content = (
            f"Deleted checkpoint `{parts[1]}`."
            if deleted
            else f"Checkpoint `{parts[1]}` not found."
        )
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=content,
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    items = store.list_for_session(session.key)
    if not items:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="No checkpoints found for this session.",
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )
    lines = [
        "## Checkpoints",
        "",
        f"Session: `{session.key}`",
        "",
    ]
    for item in items:
        summary = summarize_checkpoint(
            Checkpoint(
                checkpoint_id=item["checkpoint_id"],
                session_key=session.key,
                created_at=item["created_at"],
                context_budget_pct=item["context_budget_pct"],
                state=item.get("state", {}),
                messages=[{}] * int(item.get("message_count", 0)),
                metadata=item.get("metadata", {}),
            )
        )
        line = (
            f"- `{item['checkpoint_id']}` — "
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(item['created_at']))} "
            f"(`{summary['kind']}`"
        )
        if summary["workflow_id"]:
            line += f", workflow `{summary['workflow_id']}`"
        if summary["step_id"]:
            line += f", step `{summary['step_id']}`"
        line += ")"
        lines.append(line)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="\n".join(lines),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_distill(ctx: CommandContext) -> OutboundMessage:
    """Mine recent workflow runs into reusable patterns."""
    from teai_builder.agent.distill import get_distiller

    args = ctx.args.strip()
    if not args:
        distiller = get_distiller()
        patterns = distiller.list_patterns()
        if not patterns:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content="No distilled patterns yet. Run `/distill mine` to create some.",
                metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
            )
        lines = ["## Distilled Patterns", ""]
        for pattern in patterns[:20]:
            lines.append(f"- `{pattern.pattern_id}`: {pattern.name}")
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="\n".join(lines),
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    action = args.split()[0]
    if action == "mine":
        parts = args.split()[1:]
        limit = 5
        workflow_id: str | None = None
        if parts:
            try:
                limit = max(1, min(int(parts[0]), 20))
                if len(parts) > 1:
                    workflow_id = parts[1]
            except ValueError:
                workflow_id = parts[0]
                if len(parts) > 1:
                    try:
                        limit = max(1, min(int(parts[1]), 20))
                    except ValueError:
                        return OutboundMessage(
                            channel=ctx.msg.channel,
                            chat_id=ctx.msg.chat_id,
                            content="Usage: `/distill mine [limit] [workflow_id]`",
                            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
                        )
        distiller = get_distiller()
        runs = ctx.loop.workflow_engine.list_runs(workflow_id=workflow_id, limit=limit)
        if not runs:
            target = f" for `{workflow_id}`" if workflow_id else ""
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content=f"No workflow runs found{target} to distill.",
                metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
            )
        mined = distiller.mine_recent_runs(runs)
        if not mined:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content=(
                    f"Scanned {len(runs)} workflow run(s) but did not find reusable patterns."
                ),
                metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
            )
        lines = [
            f"Mined {len(mined)} pattern(s) from {len(runs)} workflow run(s).",
            "",
        ]
        for pattern in mined[:10]:
            tags = ", ".join(f"`{tag}`" for tag in pattern.tags[:4])
            lines.append(f"- `{pattern.pattern_id}`: {pattern.name}")
            if tags:
                lines.append(f"  Tags: {tags}")
        if len(mined) > 10:
            lines.extend(["", f"Showing 10 of {len(mined)} mined patterns."])
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="\n".join(lines),
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="Usage: `/distill [mine [limit] [workflow_id]]`",
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


def build_help_text() -> str:
    """Build canonical help text shared across channels."""
    lines = ["🍵 teai_builder commands:"]
    for spec in BUILTIN_COMMAND_SPECS:
        command = spec.command
        if spec.arg_hint:
            command = f"{command} {spec.arg_hint}"
        lines.append(f"{command} — {spec.description}")
    return "\n".join(lines)


def register_builtin_commands(router: CommandRouter) -> None:
    """Register the default set of slash commands."""
    router.priority("/stop", cmd_stop)
    router.priority("/restart", cmd_restart)
    router.priority("/status", cmd_status)
    router.exact("/new", cmd_new)
    router.exact("/model", cmd_model)
    router.prefix("/model ", cmd_model)
    router.exact("/history", cmd_history)
    router.prefix("/history ", cmd_history)
    router.exact("/goal", cmd_goal)
    router.prefix("/goal ", cmd_goal)
    router.exact("/dream", cmd_dream)
    router.exact("/dream-log", cmd_dream_log)
    router.prefix("/dream-log ", cmd_dream_log)
    router.exact("/dream-restore", cmd_dream_restore)
    router.prefix("/dream-restore ", cmd_dream_restore)
    router.exact("/skill", cmd_skill)
    router.exact("/help", cmd_help)
    router.exact("/pairing", cmd_pairing)
    router.prefix("/pairing ", cmd_pairing)
    router.exact("/workflow", cmd_workflow)
    router.prefix("/workflow ", cmd_workflow)
    router.exact("/checkpoint", cmd_checkpoint)
    router.prefix("/checkpoint ", cmd_checkpoint)
    router.exact("/distill", cmd_distill)
    router.prefix("/distill ", cmd_distill)
