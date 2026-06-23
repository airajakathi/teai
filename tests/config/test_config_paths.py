from pathlib import Path

from teai_builder.config.paths import (
    get_bridge_install_dir,
    get_cli_history_path,
    get_crash_reports_dir,
    get_cron_dir,
    get_data_dir,
    get_legacy_sessions_dir,
    get_logs_dir,
    get_media_dir,
    get_runtime_subdir,
    get_telemetry_dir,
    get_workspace_path,
    is_default_workspace,
)


def test_runtime_dirs_follow_config_path(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance-a" / "config.json"
    monkeypatch.setattr("teai_builder.config.paths.get_config_path", lambda: config_file)

    assert get_data_dir() == config_file.parent
    assert get_runtime_subdir("cron") == config_file.parent / "cron"
    assert get_cron_dir() == config_file.parent / "cron"
    assert get_logs_dir() == config_file.parent / "logs"
    assert get_telemetry_dir() == config_file.parent / "telemetry"
    assert get_crash_reports_dir() == config_file.parent / "crash_reports"


def test_media_dir_supports_channel_namespace(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance-b" / "config.json"
    monkeypatch.setattr("teai_builder.config.paths.get_config_path", lambda: config_file)

    assert get_media_dir() == config_file.parent / "media"
    assert get_media_dir("telegram") == config_file.parent / "media" / "telegram"


def test_shared_and_legacy_paths_follow_active_data_dir(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance-shared" / "config.json"
    monkeypatch.setattr("teai_builder.config.paths.get_config_path", lambda: config_file)

    assert get_cli_history_path() == get_data_dir() / "history" / "cli_history"
    assert get_bridge_install_dir() == get_data_dir() / "bridge"
    assert get_legacy_sessions_dir() == Path.home() / ".teai_builder" / "sessions"


def test_workspace_path_is_explicitly_resolved(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance-c" / "config.json"
    monkeypatch.setattr("teai_builder.config.paths.get_config_path", lambda: config_file)

    assert get_workspace_path() == config_file.parent / "workspace"
    custom = tmp_path / "custom-workspace"
    assert get_workspace_path(str(custom)) == custom


def test_is_default_workspace_distinguishes_default_and_custom_paths(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "instance-d" / "config.json"
    monkeypatch.setattr("teai_builder.config.paths.get_config_path", lambda: config_file)

    assert is_default_workspace(None) is True
    assert is_default_workspace(config_file.parent / "workspace") is True
    assert is_default_workspace("~/custom-workspace") is False


def test_data_dir_temp_fallback_is_namespaced_by_config_root(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance-fallback" / "config.json"
    calls: list[Path] = []

    def _ensure_dir(path: Path) -> Path:
        calls.append(path)
        if path == config_file.parent:
            raise OSError("read-only")
        return path

    monkeypatch.setattr("teai_builder.config.paths.get_config_path", lambda: config_file)
    monkeypatch.setattr("teai_builder.config.paths.ensure_dir", _ensure_dir)

    result = get_data_dir()

    assert result.parent == Path("/tmp")
    assert result.name.startswith("teai_builder-")
    assert calls[0] == config_file.parent


def test_data_dir_temp_fallback_emits_warning_log(monkeypatch, tmp_path: Path) -> None:
    from loguru import logger as loguru_logger

    config_file = tmp_path / "instance-logged" / "config.json"
    records: list[Any] = []

    def _ensure_dir(path: Path) -> Path:
        if path == config_file.parent:
            raise OSError("read-only")
        return path

    monkeypatch.setattr("teai_builder.config.paths.get_config_path", lambda: config_file)
    monkeypatch.setattr("teai_builder.config.paths.ensure_dir", _ensure_dir)

    handler_id = loguru_logger.add(lambda m: records.append(m), level="WARNING")
    try:
        result = get_data_dir()
    finally:
        loguru_logger.remove(handler_id)

    assert result.parent == Path("/tmp")
    assert len(records) == 1
    rendered = str(records[0])
    assert "falling back" in rendered
    assert str(config_file.parent) in rendered
    assert "teai_builder-" in rendered
