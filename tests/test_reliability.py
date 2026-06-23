from __future__ import annotations

import json
from pathlib import Path

from teai_builder.config.schema import Config
from teai_builder.reliability import (
    collect_pending_crash_reports,
    emit_telemetry_event,
    record_handled_exception,
    reliability_runtime_snapshot,
)


def _configure_paths(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance" / "config.json"
    monkeypatch.setattr("teai_builder.config.paths.get_config_path", lambda: config_file)


def test_emit_telemetry_event_writes_jsonl(monkeypatch, tmp_path: Path) -> None:
    _configure_paths(monkeypatch, tmp_path)
    config = Config.model_validate(
        {
            "reliability": {
                "telemetry": {
                    "enabled": True,
                    "maxEvents": 100,
                }
            }
        }
    )

    path = emit_telemetry_event(
        config,
        component="gateway",
        event="process_start",
        payload={"pid": 123},
    )

    assert path is not None
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["component"] == "gateway"
    assert payload["event"] == "process_start"
    assert payload["payload"]["pid"] == 123


def test_record_and_collect_pending_crash_reports(monkeypatch, tmp_path: Path) -> None:
    _configure_paths(monkeypatch, tmp_path)
    config = Config()

    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        path = record_handled_exception(
            config,
            component="agent",
            exc=exc,
            source="unit-test",
        )

    assert path is not None
    assert path.exists()

    summaries = collect_pending_crash_reports(config)
    assert len(summaries) == 1
    assert summaries[0].component == "agent"
    assert summaries[0].error_type == "RuntimeError"
    assert summaries[0].error_message == "boom"

    archive_dir = tmp_path / "instance" / "crash_reports" / "archive"
    assert any(archive_dir.glob("*.json"))
    assert collect_pending_crash_reports(config) == []


def test_reliability_runtime_snapshot_counts_files(monkeypatch, tmp_path: Path) -> None:
    _configure_paths(monkeypatch, tmp_path)
    config = Config.model_validate(
        {
            "reliability": {
                "telemetry": {
                    "enabled": True,
                }
            }
        }
    )
    pending_dir = tmp_path / "instance" / "crash_reports" / "pending"
    archive_dir = tmp_path / "instance" / "crash_reports" / "archive"
    pending_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)
    (pending_dir / "a.json").write_text("{}", encoding="utf-8")
    (archive_dir / "b.json").write_text("{}", encoding="utf-8")

    snapshot = reliability_runtime_snapshot(config, component="gateway")

    assert snapshot["telemetry"]["enabled"] is True
    assert snapshot["crash_reports"]["pending_count"] == 1
    assert snapshot["crash_reports"]["archived_count"] == 1
    assert snapshot["logs"]["path"].endswith("logs/gateway.log")
