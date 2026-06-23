#!/usr/bin/env python3
"""Gateway and WebUI bootstrap smoke checks for TeAi Builder."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from teai_builder.channels.websocket import WebSocketConfig
from teai_builder.config.loader import load_config, resolve_config_env_vars, set_config_path


def _http_get(url: str, *, timeout: float = 5.0) -> tuple[dict[str, str], bytes]:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - local CI smoke endpoint
        headers = {k.lower(): v for k, v in response.headers.items()}
        body = response.read()
        return headers, body


def _json_get(url: str, *, timeout: float = 5.0) -> dict:
    _headers, body = _http_get(url, timeout=timeout)
    return json.loads(body.decode("utf-8"))


def _wait_for_json(url: str, *, timeout_s: float, label: str) -> dict:
    deadline = time.time() + timeout_s
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return _json_get(url)
        except (URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"{label} did not become ready at {url}: {last_error}") from last_error


def _load_runtime(config_path: Path) -> tuple[object, WebSocketConfig]:
    set_config_path(config_path)
    config = resolve_config_env_vars(load_config(config_path))
    extras = getattr(config.channels, "__pydantic_extra__", {}) or {}
    websocket_raw = extras.get("websocket", {"enabled": True})
    websocket = WebSocketConfig.model_validate(websocket_raw)
    return config, websocket


def _start_gateway(config_path: Path) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.Popen(
        [sys.executable, "-m", "teai_builder.cli.commands", "gateway", "--config", str(config_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        cwd=str(config_path.parent.parent if config_path.parent.name == "instance" else config_path.parent),
        env=env,
    )


def _stop_gateway(process: subprocess.Popen[str]) -> str:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    output = ""
    if process.stdout is not None:
        output = process.stdout.read()
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Run gateway and WebUI bootstrap smoke checks.")
    parser.add_argument("--config", required=True, help="Path to config.json")
    parser.add_argument("--timeout", type=float, default=30.0, help="Startup timeout in seconds")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        raise SystemExit(f"Config not found: {config_path}")

    config, websocket = _load_runtime(config_path)
    health_url = f"http://{config.gateway.host}:{config.gateway.port}/health"
    bootstrap_url = f"http://{websocket.host}:{websocket.port}/webui/bootstrap"
    shell_url = f"http://{websocket.host}:{websocket.port}/"
    expected_model = config.resolve_preset().model
    expected_ws_url = f"ws://{websocket.host}:{websocket.port}{websocket.path}"

    process = _start_gateway(config_path)
    output = ""
    try:
        health = _wait_for_json(health_url, timeout_s=args.timeout, label="gateway health")
        if health != {"status": "ok"}:
            raise RuntimeError(f"unexpected health payload: {health!r}")
        print(f"[ok] gateway health: {health_url}")

        bootstrap = _wait_for_json(bootstrap_url, timeout_s=args.timeout, label="webui bootstrap")
        if bootstrap.get("model_name") != expected_model:
            raise RuntimeError(
                f"unexpected bootstrap model: expected {expected_model!r}, got {bootstrap.get('model_name')!r}"
            )
        if bootstrap.get("ws_url") != expected_ws_url:
            raise RuntimeError(
                f"unexpected bootstrap ws_url: expected {expected_ws_url!r}, got {bootstrap.get('ws_url')!r}"
            )
        print(f"[ok] webui bootstrap: {bootstrap_url}")

        shell_headers, shell_body = _http_get(shell_url, timeout=5.0)
        shell_html = shell_body.decode("utf-8", errors="replace")
        content_type = shell_headers.get("content-type", "")
        if "text/html" not in content_type:
            raise RuntimeError(f"unexpected shell content type: {content_type!r}")
        if "<title>TeAi Builder</title>" not in shell_html:
            raise RuntimeError("webui shell did not contain the expected title")
        if '<div id="root">' not in shell_html:
            raise RuntimeError("webui shell did not contain the expected root mount")
        print(f"[ok] webui shell: {shell_url}")
    finally:
        output = _stop_gateway(process)

    if process.returncode not in (0, -15):
        raise RuntimeError(f"gateway exited unexpectedly with code {process.returncode}\n{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
