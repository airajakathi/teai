from pathlib import Path

import pytest

from teai_builder.security.workspace_access import workspace_sandbox_status


def test_workspace_sandbox_disabled(tmp_path: Path) -> None:
    status = workspace_sandbox_status(
        restrict_to_workspace=False,
        workspace=tmp_path,
        environ={},
    )

    assert status.level == "off"
    assert status.enforced is False
    assert status.provider == "none"
    assert status.exec_backend == ""
    assert status.as_dict()["workspace_root"] == str(tmp_path.resolve())


def test_workspace_sandbox_application_guard(tmp_path: Path) -> None:
    status = workspace_sandbox_status(
        restrict_to_workspace=True,
        workspace=tmp_path,
        environ={},
    )

    assert status.level == "application"
    assert status.enforced is False
    assert status.provider == "none"
    assert status.exec_backend_available is False
    assert "application-level" in status.summary


def test_workspace_sandbox_system_provider_from_compact_env(tmp_path: Path) -> None:
    status = workspace_sandbox_status(
        restrict_to_workspace=True,
        workspace=tmp_path,
        environ={"TEAI_BUILDER_SANDBOX_ENFORCED": "macos_app_sandbox"},
    )

    assert status.level == "system"
    assert status.enforced is True
    assert status.provider == "macos_app_sandbox"
    assert status.provider_label == "macOS App Sandbox"


def test_workspace_sandbox_system_provider_from_boolean_env(tmp_path: Path) -> None:
    status = workspace_sandbox_status(
        restrict_to_workspace=True,
        workspace=tmp_path,
        environ={
            "TEAI_BUILDER_WORKSPACE_SANDBOX_ENFORCED": "true",
            "TEAI_BUILDER_WORKSPACE_SANDBOX_PROVIDER": "macOS App Sandbox",
        },
    )

    assert status.level == "system"
    assert status.enforced is True
    assert status.provider == "macos_app_sandbox"


def test_workspace_sandbox_false_env_does_not_enforce(tmp_path: Path) -> None:
    status = workspace_sandbox_status(
        restrict_to_workspace=True,
        workspace=tmp_path,
        environ={"TEAI_BUILDER_WORKSPACE_SANDBOX_ENFORCED": "false"},
    )

    assert status.level == "application"
    assert status.enforced is False


def test_workspace_sandbox_process_enforced_exec_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/bwrap" if name == "bwrap" else None)
    status = workspace_sandbox_status(
        restrict_to_workspace=True,
        workspace=tmp_path,
        sandbox_backend="bwrap",
    )

    assert status.level == "process"
    assert status.enforced is True
    assert status.provider == "bwrap"
    assert status.exec_backend == "bwrap"
    assert status.exec_backend_available is True
    assert "process-enforced" in status.summary


def test_workspace_sandbox_degraded_when_strict_backend_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    status = workspace_sandbox_status(
        restrict_to_workspace=True,
        workspace=tmp_path,
        sandbox_backend="bwrap",
        strict_execution=True,
    )

    assert status.level == "degraded"
    assert status.enforced is False
    assert status.exec_backend == "bwrap"
    assert status.exec_backend_available is False
    assert status.exec_backend_required is True
    assert "block exec commands" in status.summary


def test_workspace_sandbox_application_fallback_when_backend_missing_and_not_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    status = workspace_sandbox_status(
        restrict_to_workspace=True,
        workspace=tmp_path,
        sandbox_backend="bwrap",
        strict_execution=False,
    )

    assert status.level == "application"
    assert status.enforced is False
    assert status.exec_backend == "bwrap"
    assert status.exec_backend_required is False
    assert "falling back" in status.summary
