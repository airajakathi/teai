"""Sandbox backends for shell command execution.

To add a new backend, implement a function with the signature:
    _wrap_<name>(command: str, workspace: str, cwd: str) -> str
and register it in _BACKENDS below.
"""

from __future__ import annotations

import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from teai_builder.config.paths import get_media_dir


@dataclass(frozen=True)
class SandboxBackendStatus:
    """Resolved availability for an execution sandbox backend."""

    backend: str
    available: bool
    provider: str
    provider_label: str
    summary: str


_BACKEND_LABELS = {
    "bwrap": "Bubblewrap",
}


def _optional_media_dir() -> Path | None:
    try:
        return get_media_dir().resolve()
    except OSError:
        return None


def _bwrap(command: str, workspace: str, cwd: str) -> str:
    """Wrap command in a bubblewrap sandbox (requires bwrap in container).

    Only the workspace is bind-mounted read-write; its parent dir (which holds
    config.json) is hidden behind a fresh tmpfs.  The media directory is
    bind-mounted read-only so exec commands can read uploaded attachments.
    """
    ws = Path(workspace).resolve()
    media = _optional_media_dir()

    try:
        sandbox_cwd = str(ws / Path(cwd).resolve().relative_to(ws))
    except ValueError:
        sandbox_cwd = str(ws)

    required = ["/usr"]
    optional = [
        "/bin",
        "/lib",
        "/lib64",
        "/etc/alternatives",
        "/etc/ssl/certs",
        "/etc/resolv.conf",
        "/etc/ld.so.cache",
    ]

    args = ["bwrap", "--new-session", "--die-with-parent", "--setenv", "HOME", str(ws)]
    for p in required:
        args += ["--ro-bind", p, p]
    for p in optional:
        args += ["--ro-bind-try", p, p]
    args += [
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--tmpfs", str(ws.parent),        # mask config dir
        "--dir", str(ws),                 # recreate workspace mount point
        "--bind", str(ws), str(ws),
        "--chdir", sandbox_cwd,
        "--", "sh", "-c", command,
    ]
    if media is not None:
        args[args.index("--chdir"):args.index("--chdir")] = [
            "--ro-bind-try", str(media), str(media),  # read-only access to media
        ]
    return shlex.join(args)


_BACKENDS = {"bwrap": _bwrap}


def sandbox_backend_status(sandbox: str) -> SandboxBackendStatus:
    """Return host availability for a named execution sandbox backend."""
    backend = sandbox.strip().lower()
    if backend not in _BACKENDS:
        raise ValueError(f"Unknown sandbox backend {sandbox!r}. Available: {list(_BACKENDS)}")

    label = _BACKEND_LABELS.get(backend, backend.replace("_", " ").title())
    if backend == "bwrap":
        if sys.platform == "win32":
            return SandboxBackendStatus(
                backend=backend,
                available=False,
                provider=backend,
                provider_label=label,
                summary="Bubblewrap is not available on Windows hosts.",
            )
        executable = shutil.which("bwrap")
        if executable:
            return SandboxBackendStatus(
                backend=backend,
                available=True,
                provider=backend,
                provider_label=label,
                summary=f"{label} is available at {executable}.",
            )
        return SandboxBackendStatus(
            backend=backend,
            available=False,
            provider=backend,
            provider_label=label,
            summary=f"{label} is not installed or not on PATH.",
        )

    return SandboxBackendStatus(
        backend=backend,
        available=True,
        provider=backend,
        provider_label=label,
        summary=f"{label} is available.",
    )


def wrap_command(sandbox: str, command: str, workspace: str, cwd: str) -> str:
    """Wrap *command* using the named sandbox backend."""
    if backend := _BACKENDS.get(sandbox):
        return backend(command, workspace, cwd)
    raise ValueError(f"Unknown sandbox backend {sandbox!r}. Available: {list(_BACKENDS)}")
