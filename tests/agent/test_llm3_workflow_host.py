from pathlib import Path

import pytest

from teai_builder.agent.llm3.workflow_host import LLM3WorkflowHost


def test_workflow_host_raises_when_storage_dir_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "blocked"
    original_mkdir = Path.mkdir

    def failing_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        if self == target:
            raise OSError("disk unavailable")
        original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", failing_mkdir)

    with pytest.raises(RuntimeError, match="workflow storage directory is unavailable"):
        LLM3WorkflowHost(
            parallel_executor=object(),
            storage_dir=target,
        )
