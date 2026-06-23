"""Local crash reporting, telemetry audit logs, and runtime reliability helpers."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import sys
import threading
import traceback
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from teai_builder import __version__
from teai_builder.config.paths import get_crash_reports_dir, get_logs_dir, get_telemetry_dir

_FILE_LOG_SINKS: dict[Path, int] = {}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _trim_jsonl(path: Path, max_events: int) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    if len(lines) <= max_events:
        return
    path.write_text("\n".join(lines[-max_events:]) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any], *, max_events: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
    _trim_jsonl(path, max_events)


@dataclass(frozen=True)
class CrashReportSummary:
    report_id: str
    occurred_at: str
    component: str
    source: str
    error_type: str
    error_message: str
    file_name: str


@dataclass(frozen=True)
class ReliabilityStatus:
    component: str
    log_path: str
    telemetry_enabled: bool
    telemetry_path: str | None
    pending_crash_reports: list[CrashReportSummary]


def install_file_logging(component: str) -> Path:
    """Add an instance-scoped log file sink for the current process."""
    log_path = get_logs_dir() / f"{component}.log"
    if log_path not in _FILE_LOG_SINKS:
        _FILE_LOG_SINKS[log_path] = logger.add(
            log_path,
            level="DEBUG",
            enqueue=False,
            backtrace=False,
            diagnose=False,
            encoding="utf-8",
        )
    return log_path


def telemetry_log_path(component: str) -> Path:
    return get_telemetry_dir() / f"{component}.jsonl"


def emit_telemetry_event(
    config: Any,
    *,
    component: str,
    event: str,
    payload: dict[str, Any] | None = None,
    level: str = "info",
) -> Path | None:
    """Append a local telemetry audit event when telemetry is enabled."""
    telemetry = config.reliability.telemetry
    if not telemetry.enabled or not telemetry.local_audit_log:
        return None
    path = telemetry_log_path(component)
    _append_jsonl(
        path,
        {
            "timestamp": _utc_now(),
            "component": component,
            "event": event,
            "level": level,
            "version": __version__,
            "payload": payload or {},
        },
        max_events=telemetry.max_events,
    )
    return path


def record_handled_exception(
    config: Any,
    *,
    component: str,
    exc: BaseException,
    source: str,
    metadata: dict[str, Any] | None = None,
) -> Path | None:
    """Persist a crash report for a handled-but-fatal exception."""
    crash_cfg = config.reliability.crash_reports
    if not crash_cfg.enabled:
        return None
    report_id = uuid.uuid4().hex
    occurred_at = _utc_now()
    pending_dir = get_crash_reports_dir() / "pending"
    path = pending_dir / f"{occurred_at.replace(':', '-')}--{report_id}.json"
    payload = {
        "report_id": report_id,
        "occurred_at": occurred_at,
        "component": component,
        "source": source,
        "version": __version__,
        "pid": os.getpid(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": sys.version,
        },
        "exception": {
            "type": type(exc).__name__,
            "message": str(exc),
        },
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        "metadata": metadata or {},
    }
    _atomic_write_json(path, payload)
    emit_telemetry_event(
        config,
        component=component,
        event="crash_report_written",
        level="error",
        payload={
            "report_id": report_id,
            "source": source,
            "error_type": type(exc).__name__,
        },
    )
    return path


def _summary_from_payload(file_name: str, payload: dict[str, Any]) -> CrashReportSummary:
    exception = payload.get("exception") or {}
    return CrashReportSummary(
        report_id=str(payload.get("report_id") or ""),
        occurred_at=str(payload.get("occurred_at") or ""),
        component=str(payload.get("component") or ""),
        source=str(payload.get("source") or ""),
        error_type=str(exception.get("type") or "UnknownError"),
        error_message=str(exception.get("message") or ""),
        file_name=file_name,
    )


def collect_pending_crash_reports(config: Any) -> list[CrashReportSummary]:
    """Collect pending crash reports and archive them so they are shown only once."""
    crash_cfg = config.reliability.crash_reports
    if not crash_cfg.enabled:
        return []
    pending_dir = get_crash_reports_dir() / "pending"
    archive_dir = get_crash_reports_dir() / "archive"
    if not pending_dir.exists():
        return []

    summaries: list[CrashReportSummary] = []
    files = sorted(pending_dir.glob("*.json"))
    limit = crash_cfg.startup_report_limit
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {
                "report_id": "",
                "occurred_at": "",
                "component": "",
                "source": "unreadable",
                "exception": {
                    "type": "UnreadableCrashReport",
                    "message": f"Could not parse {path.name}",
                },
            }
        if len(summaries) < limit:
            summaries.append(_summary_from_payload(path.name, payload))
        archive_dir.mkdir(parents=True, exist_ok=True)
        path.replace(archive_dir / path.name)

    archived = sorted(archive_dir.glob("*.json"))
    excess = len(archived) - crash_cfg.keep_reports
    if excess > 0:
        for path in archived[:excess]:
            path.unlink(missing_ok=True)
    return summaries


def reliability_runtime_snapshot(config: Any, *, component: str) -> dict[str, Any]:
    """Return the current reliability state for UI payloads."""
    crash_root = get_crash_reports_dir()
    pending_dir = crash_root / "pending"
    archive_dir = crash_root / "archive"
    telemetry = config.reliability.telemetry
    return {
        "telemetry": {
            "enabled": telemetry.enabled,
            "local_audit_log": telemetry.local_audit_log,
            "capture_usage": telemetry.capture_usage,
            "capture_errors": telemetry.capture_errors,
            "max_events": telemetry.max_events,
            "path": str(telemetry_log_path(component)) if telemetry.enabled and telemetry.local_audit_log else None,
        },
        "crash_reports": {
            "enabled": config.reliability.crash_reports.enabled,
            "pending_count": len(list(pending_dir.glob("*.json"))) if pending_dir.exists() else 0,
            "archived_count": len(list(archive_dir.glob("*.json"))) if archive_dir.exists() else 0,
            "path": str(crash_root),
        },
        "logs": {
            "path": str(get_logs_dir() / f"{component}.log"),
        },
    }


def install_crash_handlers(config: Any, *, component: str) -> None:
    """Install process-level crash handlers that persist reports before delegating."""
    previous_excepthook = sys.excepthook

    def _sys_hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            previous_excepthook(exc_type, exc, tb)
            return
        record_handled_exception(config, component=component, exc=exc, source="sys.excepthook")
        previous_excepthook(exc_type, exc, tb)

    sys.excepthook = _sys_hook

    if hasattr(threading, "excepthook"):
        previous_thread_hook = threading.excepthook

        def _thread_hook(args: threading.ExceptHookArgs) -> None:
            if args.exc_type is not None and not issubclass(args.exc_type, KeyboardInterrupt):
                record_handled_exception(
                    config,
                    component=component,
                    exc=args.exc_value,
                    source=f"threading:{args.thread.name if args.thread else 'unknown'}",
                )
            previous_thread_hook(args)

        threading.excepthook = _thread_hook


def install_asyncio_exception_handler(loop: asyncio.AbstractEventLoop, config: Any, *, component: str) -> None:
    """Persist unexpected asyncio loop exceptions."""
    previous_handler = loop.get_exception_handler()

    def _handler(current_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exc = context.get("exception")
        if exc is not None:
            record_handled_exception(
                config,
                component=component,
                exc=exc,
                source="asyncio",
                metadata={"message": context.get("message", "")},
            )
        if previous_handler is not None:
            previous_handler(current_loop, context)
        else:
            current_loop.default_exception_handler(context)

    loop.set_exception_handler(_handler)


def setup_runtime_reliability(config: Any, *, component: str) -> ReliabilityStatus:
    """Initialize log sinks, crash handlers, and return pending crash summaries."""
    log_path = install_file_logging(component)
    install_crash_handlers(config, component=component)
    pending = collect_pending_crash_reports(config)
    telemetry_path = emit_telemetry_event(
        config,
        component=component,
        event="process_start",
        payload={"pid": os.getpid()},
    )
    return ReliabilityStatus(
        component=component,
        log_path=str(log_path),
        telemetry_enabled=config.reliability.telemetry.enabled,
        telemetry_path=str(telemetry_path) if telemetry_path else None,
        pending_crash_reports=pending,
    )


def emit_process_stop(config: Any, *, component: str, reason: str) -> None:
    emit_telemetry_event(config, component=component, event="process_stop", payload={"reason": reason})


def reliability_status_as_dict(status: ReliabilityStatus) -> dict[str, Any]:
    payload = asdict(status)
    payload["pending_crash_reports"] = [asdict(item) for item in status.pending_crash_reports]
    return payload
